from __future__ import annotations

import csv
import io
import re
import threading
import time
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Literal
from uuid import UUID, uuid4

from fastapi import HTTPException, status
import openpyxl
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import record_security_event
from app.models import (
    Asset,
    AssetCategory,
    Company,
    CostCenter,
    Department,
    Location,
    Site,
)
from app.schemas import (
    AssetCreate,
    AssetImportConfirmResponse,
    AssetImportPreviewResponse,
    ImportRowError,
    ImportRowWarning,
)
from app.services import create_asset, get_company

MAX_FILE_SIZE_BYTES = 5 * 1024 * 1024  # 5 MB
MAX_IMPORT_ROWS = 1000
MAX_STAGED_IMPORTS = 100
STAGING_TTL_SECONDS = 30 * 60  # 30 minutes

ALLOWED_STATUSES = {
    'in_stock',
    'in_use',
    'in_maintenance',
    'retired',
    'disposed',
    'pending_disposal',
    'quarantine',
}

TEMPLATE_HEADERS = [
    'category_code',
    'serial_number',
    'manufacturer',
    'model',
    'status',
    'site_code',
    'location_code',
    'department_code',
    'cost_center_code',
    'acquisition_date',
    'acquisition_cost',
    'custodian_name',
    'vendor_reference',
    'invoice_reference',
    'warranty_start',
    'warranty_end',
    'notes',
    'asset_number',
]

HEADER_ALIASES: dict[str, list[str]] = {
    'category_code': ['category_code', 'category', 'category code', 'asset_category', 'category_name'],
    'serial_number': ['serial_number', 'serial number', 'serial', 'sn'],
    'manufacturer': ['manufacturer', 'make', 'brand'],
    'model': ['model', 'model_number', 'model number'],
    'status': ['status', 'asset_status'],
    'site_code': ['site_code', 'site', 'site code', 'site_name'],
    'location_code': ['location_code', 'location', 'location code', 'location_name'],
    'department_code': ['department_code', 'department', 'department code', 'responsible_department'],
    'cost_center_code': ['cost_center_code', 'cost_center', 'cost center', 'cost centre', 'cost_centre_code'],
    'acquisition_date': ['acquisition_date', 'acquisition date', 'purchase_date', 'purchase date'],
    'acquisition_cost': ['acquisition_cost', 'acquisition cost', 'cost', 'purchase_cost', 'purchase cost'],
    'custodian_name': ['custodian_name', 'custodian', 'custodian name', 'assigned_to'],
    'vendor_reference': ['vendor_reference', 'vendor reference', 'vendor', 'supplier'],
    'invoice_reference': ['invoice_reference', 'invoice reference', 'invoice', 'invoice_number'],
    'warranty_start': ['warranty_start', 'warranty start', 'warranty_start_date'],
    'warranty_end': ['warranty_end', 'warranty end', 'warranty_end_date'],
    'notes': ['notes', 'remarks', 'comments', 'description'],
    'asset_number': ['asset_number', 'asset number', 'tag', 'asset_tag'],
}


@dataclass
class StagedImport:
    token: str
    company_id: UUID
    actor_id: UUID
    created_at: float
    rows: list[AssetCreate]
    row_count: int
    is_processing: bool = False


_STAGING_LOCK = threading.Lock()
_STAGING_STORE: dict[str, StagedImport] = {}


def _clean_staging_store() -> None:
    now = time.time()
    expired = [
        token for token, item in _STAGING_STORE.items()
        if not item.is_processing and (now - item.created_at > STAGING_TTL_SECONDS)
    ]
    for token in expired:
        _STAGING_STORE.pop(token, None)

    # Bound maximum number of staged imports in memory
    if len(_STAGING_STORE) > MAX_STAGED_IMPORTS:
        sorted_tokens = sorted(
            [t for t, item in _STAGING_STORE.items() if not item.is_processing],
            key=lambda t: _STAGING_STORE[t].created_at,
        )
        overflow = len(_STAGING_STORE) - MAX_STAGED_IMPORTS
        for token in sorted_tokens[:overflow]:
            _STAGING_STORE.pop(token, None)


def _sanitize_formula(val: Any) -> Any:
    """Neutralize spreadsheet formula injection (CWE-1236).

    Untrusted text values beginning with formula trigger characters ('=', '+', '-', '@'),
    including values preceded by whitespace or ASCII control characters (\\x00-\\x1f, \\x7f),
    are prepended with a single quote (') to neutralize formula execution in spreadsheet
    applications (such as Microsoft Excel, LibreOffice, or Google Sheets).
    """
    if val is None:
        return ''
    s = str(val)
    if s and re.match(r'^[\s\x00-\x1f\x7f]*[=+\-@\t\r]', s):
        return "'" + s
    return s


def parse_date_value(val: Any) -> date | None:
    if val is None:
        return None
    if isinstance(val, date) and not isinstance(val, datetime):
        return val
    if isinstance(val, datetime):
        return val.date()
    s = str(val).strip()
    if not s:
        return None
    # Try ISO formats
    for fmt in ('%Y-%m-%d', '%Y/%m/%d', '%d-%m-%Y', '%d/%m/%Y'):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Invalid date '{s}'. Expected YYYY-MM-DD")


def parse_decimal_value(val: Any) -> Decimal | None:
    if val is None:
        return None
    if isinstance(val, (int, float, Decimal)):
        d = Decimal(str(val)).quantize(Decimal('0.01'))
        if d < Decimal('0'):
            raise ValueError('Acquisition cost must be non-negative')
        return d
    s = str(val).strip()
    if not s:
        return None
    # Clean currency symbols and commas
    cleaned = re.sub(r'[^\d.-]', '', s)
    try:
        d = Decimal(cleaned).quantize(Decimal('0.01'))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"Invalid numeric value '{s}'") from exc
    if d < Decimal('0'):
        raise ValueError('Acquisition cost must be non-negative')
    return d


def normalize_header(header: str) -> str:
    cleaned = re.sub(r'[\s_-]+', '_', header.strip().lower())
    for standard_name, aliases in HEADER_ALIASES.items():
        for alias in aliases:
            if cleaned == re.sub(r'[\s_-]+', '_', alias.lower()):
                return standard_name
    return cleaned


def extract_rows_from_csv(file_bytes: bytes) -> tuple[list[str], list[list[Any]]]:
    # Try UTF-8 with BOM first, then UTF-8, then Latin-1
    text = None
    for encoding in ('utf-8-sig', 'utf-8', 'latin-1'):
        try:
            text = file_bytes.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        raise HTTPException(status_code=400, detail='Unable to decode CSV file with supported encodings')

    reader = csv.reader(io.StringIO(text))
    headers: list[str] = []
    data_rows: list[list[Any]] = []
    for idx, row in enumerate(reader):
        if idx == 0:
            headers = [str(col).strip() for col in row]
        else:
            data_rows.append(row)
            if len(data_rows) > MAX_IMPORT_ROWS:
                break
    return headers, data_rows


def extract_rows_from_xlsx(file_bytes: bytes) -> tuple[list[str], list[list[Any]]]:
    # Check magic header
    if not file_bytes.startswith(b'PK\x03\x04'):
        raise HTTPException(status_code=400, detail='Invalid Excel file format')

    # Guard against macro-enabled spreadsheets
    try:
        with zipfile.ZipFile(io.BytesIO(file_bytes)) as z:
            file_names = [f.lower() for f in z.namelist()]
            if any('vbaproject.bin' in f or f.endswith(('.xlsm', '.xltm')) for f in file_names):
                raise HTTPException(
                    status_code=400,
                    detail='Macro-enabled spreadsheets (.xlsm) and embedded VBA macros are not allowed for security reasons',
                )
    except zipfile.BadZipFile as exc:
        raise HTTPException(status_code=400, detail='Corrupted or invalid Excel file archive') from exc

    try:
        wb = openpyxl.load_workbook(io.BytesIO(file_bytes), read_only=True, data_only=True)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f'Failed to parse Excel file: {str(exc)}') from exc

    sheet = wb.active
    if sheet is None:
        return [], []

    headers: list[str] = []
    data_rows: list[list[Any]] = []
    for idx, row in enumerate(sheet.iter_rows(values_only=True)):
        if idx == 0:
            headers = [str(col or '').strip() for col in row]
        else:
            data_rows.append(list(row))
            if len(data_rows) > MAX_IMPORT_ROWS:
                break
    wb.close()

    return headers, data_rows


def generate_template(db: Session, company_id: UUID, format_type: Literal['csv', 'xlsx']) -> tuple[bytes, str, str]:
    get_company(db, company_id, active=True)

    # Fetch sample company records to provide helpful sample values
    sample_cat = db.scalars(
        select(AssetCategory).where(AssetCategory.company_id == company_id, AssetCategory.is_active.is_(True))
    ).first()
    sample_site = db.scalars(
        select(Site).where(Site.company_id == company_id, Site.is_active.is_(True))
    ).first()
    sample_loc = None
    if sample_site:
        sample_loc = db.scalars(
            select(Location).where(
                Location.company_id == company_id,
                Location.site_id == sample_site.id,
                Location.is_active.is_(True),
            )
        ).first()
    sample_dept = db.scalars(
        select(Department).where(Department.company_id == company_id, Department.is_active.is_(True))
    ).first()
    sample_cc = db.scalars(
        select(CostCenter).where(CostCenter.company_id == company_id, CostCenter.is_active.is_(True))
    ).first()

    cat_code = sample_cat.code if sample_cat else 'LAPTOP'
    site_code = sample_site.code if sample_site else 'HQ'
    loc_code = sample_loc.code if sample_loc else 'STORE-ROOM'
    dept_code = sample_dept.code if sample_dept else 'ENG'
    cc_code = sample_cc.code if sample_cc else 'CC-101'

    sample_rows = [
        [
            cat_code,
            'SN-LTP-00101',
            'Dell',
            'Latitude 5540',
            'in_stock',
            site_code,
            loc_code,
            dept_code,
            cc_code,
            '2026-01-15',
            '1299.00',
            'Alice Smith',
            'Dell Technologies',
            'INV-2026-001',
            '2026-01-15',
            '2029-01-15',
            'Batch onboarding primary work laptops',
            '',  # Auto-generate asset_number
        ],
        [
            cat_code,
            'SN-LTP-00102',
            'Dell',
            'Latitude 5540',
            'in_stock',
            site_code,
            loc_code,
            dept_code,
            cc_code,
            '2026-01-15',
            '1299.00',
            'Bob Jones',
            'Dell Technologies',
            'INV-2026-001',
            '2026-01-15',
            '2029-01-15',
            'Batch onboarding primary work laptops',
            '',  # Auto-generate asset_number
        ],
    ]

    if format_type == 'xlsx':
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = 'Asset Import Template'

        # Header row with styles
        header_fill = openpyxl.styles.PatternFill(start_color='1E3A8A', end_color='1E3A8A', fill_type='solid')
        header_font = openpyxl.styles.Font(name='Segoe UI', size=11, bold=True, color='FFFFFF')

        ws.append(TEMPLATE_HEADERS)
        for col_idx in range(1, len(TEMPLATE_HEADERS) + 1):
            cell = ws.cell(row=1, column=col_idx)
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = openpyxl.styles.Alignment(horizontal='center', vertical='center')

        for row_data in sample_rows:
            ws.append([_sanitize_formula(val) for val in row_data])

        for col in ws.columns:
            max_len = max(len(str(cell.value or '')) for cell in col)
            col_letter = openpyxl.utils.get_column_letter(col[0].column)
            ws.column_dimensions[col_letter].width = max(max_len + 4, 15)

        output = io.BytesIO()
        wb.save(output)
        file_bytes = output.getvalue()
        media_type = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        filename = 'mindzen_asset_import_template.xlsx'
        return file_bytes, media_type, filename

    # CSV format
    output = io.StringIO()
    writer = csv.writer(output, lineterminator='\r\n')
    writer.writerow(TEMPLATE_HEADERS)
    for row in sample_rows:
        writer.writerow([_sanitize_formula(val) for val in row])

    # Prefix with UTF-8 BOM so Microsoft Excel opens it cleanly
    bom_bytes = b'\xef\xbb\xbf' + output.getvalue().encode('utf-8')
    media_type = 'text/csv; charset=utf-8'
    filename = 'mindzen_asset_import_template.csv'
    return bom_bytes, media_type, filename


def parse_and_validate_file(
    db: Session,
    company_id: UUID,
    actor_id: UUID,
    file_bytes: bytes,
    filename: str,
) -> AssetImportPreviewResponse:
    get_company(db, company_id, active=True)

    if len(file_bytes) > MAX_FILE_SIZE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f'File size exceeds maximum allowed limit of {MAX_FILE_SIZE_BYTES // (1024 * 1024)} MB',
        )

    lower_name = filename.lower()
    if lower_name.endswith(('.xlsm', '.xltm', '.xlsb')):
        raise HTTPException(
            status_code=400,
            detail='Macro-enabled spreadsheets (.xlsm) are not accepted for security reasons. Please use standard .xlsx or .csv',
        )
    elif lower_name.endswith('.xlsx'):
        headers, data_rows = extract_rows_from_xlsx(file_bytes)
    elif lower_name.endswith('.csv'):
        headers, data_rows = extract_rows_from_csv(file_bytes)
    else:
        raise HTTPException(
            status_code=400,
            detail="Unsupported file format. Please upload a '.csv' or '.xlsx' file",
        )

    if not headers or not data_rows:
        return AssetImportPreviewResponse(
            valid=False,
            total_rows=0,
            valid_rows=0,
            invalid_rows=0,
            preview_token=None,
            errors=[ImportRowError(row_number=1, field='headers', message='Uploaded spreadsheet contains no data rows')],
            warnings=[],
            preview_rows=[],
        )

    # Normalize header mapping
    header_map: dict[str, int] = {}
    for idx, h in enumerate(headers):
        norm = normalize_header(h)
        if norm in TEMPLATE_HEADERS and norm not in header_map:
            header_map[norm] = idx

    if 'category_code' not in header_map:
        return AssetImportPreviewResponse(
            valid=False,
            total_rows=len(data_rows),
            valid_rows=0,
            invalid_rows=len(data_rows),
            preview_token=None,
            errors=[
                ImportRowError(
                    row_number=1,
                    field='category_code',
                    message="Missing required header column 'category_code' (or 'category')",
                )
            ],
            warnings=[],
            preview_rows=[],
        )

    if len(data_rows) > MAX_IMPORT_ROWS:
        raise HTTPException(
            status_code=422,
            detail=f'Spreadsheet contains {len(data_rows)} rows, which exceeds the maximum batch limit of {MAX_IMPORT_ROWS} rows',
        )

    # Pre-fetch and index active company master data
    categories = db.scalars(
        select(AssetCategory).where(AssetCategory.company_id == company_id, AssetCategory.is_active.is_(True))
    ).all()
    cat_by_key: dict[str, AssetCategory] = {}
    for cat in categories:
        cat_by_key[cat.code.strip().upper()] = cat
        cat_by_key[cat.name.strip().upper()] = cat
        cat_by_key[str(cat.id)] = cat

    sites = db.scalars(
        select(Site).where(Site.company_id == company_id, Site.is_active.is_(True))
    ).all()
    site_by_key: dict[str, Site] = {}
    for site in sites:
        site_by_key[site.code.strip().upper()] = site
        site_by_key[site.name.strip().upper()] = site
        site_by_key[str(site.id)] = site

    locations = db.scalars(
        select(Location).where(Location.company_id == company_id, Location.is_active.is_(True))
    ).all()
    loc_by_site_key: dict[tuple[UUID, str], Location] = {}
    for loc in locations:
        loc_by_site_key[(loc.site_id, loc.code.strip().upper())] = loc
        loc_by_site_key[(loc.site_id, loc.name.strip().upper())] = loc
        loc_by_site_key[(loc.site_id, str(loc.id))] = loc

    departments = db.scalars(
        select(Department).where(Department.company_id == company_id, Department.is_active.is_(True))
    ).all()
    dept_by_key: dict[str, Department] = {}
    for dept in departments:
        dept_by_key[dept.code.strip().upper()] = dept
        dept_by_key[dept.name.strip().upper()] = dept
        dept_by_key[str(dept.id)] = dept

    cost_centers = db.scalars(
        select(CostCenter).where(CostCenter.company_id == company_id, CostCenter.is_active.is_(True))
    ).all()
    cc_by_key: dict[str, CostCenter] = {}
    for cc in cost_centers:
        cc_by_key[cc.code.strip().upper()] = cc
        cc_by_key[cc.name.strip().upper()] = cc
        cc_by_key[str(cc.id)] = cc

    existing_serials = {
        s.upper()
        for s in db.scalars(
            select(Asset.serial_number).where(
                Asset.company_id == company_id,
                Asset.serial_number.is_not(None),
            )
        ).all()
        if s
    }

    existing_asset_numbers = {
        n.upper()
        for n in db.scalars(
            select(Asset.asset_number).where(Asset.company_id == company_id)
        ).all()
        if n
    }

    errors: list[ImportRowError] = []
    warnings: list[ImportRowWarning] = []
    preview_rows: list[dict[str, Any]] = []
    validated_payloads: list[AssetCreate] = []

    batch_serials: set[str] = set()
    batch_asset_numbers: set[str] = set()

    for idx, raw_row in enumerate(data_rows, start=2):
        # Ignore completely empty rows
        if not raw_row or all(col is None or str(col).strip() == '' for col in raw_row):
            continue

        row_errors: list[ImportRowError] = []

        def get_val(col_name: str) -> str | None:
            col_idx = header_map.get(col_name)
            if col_idx is None or col_idx >= len(raw_row):
                return None
            val = raw_row[col_idx]
            if val is None:
                return None
            s = str(val).strip()
            return s if s != '' else None

        # 1. Category (Mandatory)
        cat_val = get_val('category_code')
        resolved_cat: AssetCategory | None = None
        if not cat_val:
            row_errors.append(
                ImportRowError(row_number=idx, field='category_code', value=None, message='Asset category is required')
            )
        else:
            resolved_cat = cat_by_key.get(cat_val.upper())
            if not resolved_cat:
                row_errors.append(
                    ImportRowError(
                        row_number=idx,
                        field='category_code',
                        value=cat_val,
                        message=f"Asset category '{cat_val}' not found or is inactive in company",
                    )
                )

        # 2. Serial Number
        serial_val = get_val('serial_number')
        if serial_val:
            if len(serial_val) > 120:
                row_errors.append(
                    ImportRowError(
                        row_number=idx,
                        field='serial_number',
                        value=serial_val,
                        message='Serial number exceeds maximum length of 120 characters',
                    )
                )
            s_upper = serial_val.upper()
            if s_upper in batch_serials:
                row_errors.append(
                    ImportRowError(
                        row_number=idx,
                        field='serial_number',
                        value=serial_val,
                        message=f"Duplicate serial number '{serial_val}' within this spreadsheet batch",
                    )
                )
            elif s_upper in existing_serials:
                row_errors.append(
                    ImportRowError(
                        row_number=idx,
                        field='serial_number',
                        value=serial_val,
                        message=f"Serial number '{serial_val}' already exists for an active asset in this company",
                    )
                )
            else:
                batch_serials.add(s_upper)

        # 3. Asset Number (Optional manual override)
        asset_num_val = get_val('asset_number')
        if asset_num_val:
            if len(asset_num_val) > 80:
                row_errors.append(
                    ImportRowError(
                        row_number=idx,
                        field='asset_number',
                        value=asset_num_val,
                        message='Asset number exceeds maximum length of 80 characters',
                    )
                )
            a_upper = asset_num_val.upper()
            if a_upper in batch_asset_numbers:
                row_errors.append(
                    ImportRowError(
                        row_number=idx,
                        field='asset_number',
                        value=asset_num_val,
                        message=f"Duplicate asset number '{asset_num_val}' within this spreadsheet batch",
                    )
                )
            elif a_upper in existing_asset_numbers:
                row_errors.append(
                    ImportRowError(
                        row_number=idx,
                        field='asset_number',
                        value=asset_num_val,
                        message=f"Asset number '{asset_num_val}' already exists in this company",
                    )
                )
            else:
                batch_asset_numbers.add(a_upper)

        # 4. Status
        status_val = (get_val('status') or 'in_stock').lower()
        if status_val not in ALLOWED_STATUSES:
            row_errors.append(
                ImportRowError(
                    row_number=idx,
                    field='status',
                    value=status_val,
                    message=f"Invalid status '{status_val}'. Allowed statuses: {', '.join(sorted(ALLOWED_STATUSES))}",
                )
            )

        # 5. Site & Location
        site_val = get_val('site_code')
        resolved_site: Site | None = None
        if site_val:
            resolved_site = site_by_key.get(site_val.upper())
            if not resolved_site:
                row_errors.append(
                    ImportRowError(
                        row_number=idx,
                        field='site_code',
                        value=site_val,
                        message=f"Site '{site_val}' not found or is inactive in company",
                    )
                )

        loc_val = get_val('location_code')
        resolved_loc: Location | None = None
        if loc_val:
            if not site_val or not resolved_site:
                row_errors.append(
                    ImportRowError(
                        row_number=idx,
                        field='location_code',
                        value=loc_val,
                        message="A valid site is required when specifying a location",
                    )
                )
            else:
                resolved_loc = loc_by_site_key.get((resolved_site.id, loc_val.upper()))
                if not resolved_loc:
                    row_errors.append(
                        ImportRowError(
                            row_number=idx,
                            field='location_code',
                            value=loc_val,
                            message=f"Location '{loc_val}' not found in site '{site_val}' or is inactive",
                        )
                    )

        # 6. Department
        dept_val = get_val('department_code')
        resolved_dept: Department | None = None
        if dept_val:
            resolved_dept = dept_by_key.get(dept_val.upper())
            if not resolved_dept:
                row_errors.append(
                    ImportRowError(
                        row_number=idx,
                        field='department_code',
                        value=dept_val,
                        message=f"Department '{dept_val}' not found or is inactive in company",
                    )
                )

        # 7. Cost Center
        cc_val = get_val('cost_center_code')
        resolved_cc: CostCenter | None = None
        if cc_val:
            resolved_cc = cc_by_key.get(cc_val.upper())
            if not resolved_cc:
                row_errors.append(
                    ImportRowError(
                        row_number=idx,
                        field='cost_center_code',
                        value=cc_val,
                        message=f"Cost center '{cc_val}' not found or is inactive in company",
                    )
                )

        # 8. Dates & Numeric Costs
        acq_date = None
        raw_acq = get_val('acquisition_date')
        if raw_acq:
            try:
                acq_date = parse_date_value(raw_acq)
            except ValueError as exc:
                row_errors.append(
                    ImportRowError(row_number=idx, field='acquisition_date', value=raw_acq, message=str(exc))
                )

        acq_cost = None
        raw_cost = get_val('acquisition_cost')
        if raw_cost:
            try:
                acq_cost = parse_decimal_value(raw_cost)
            except ValueError as exc:
                row_errors.append(
                    ImportRowError(row_number=idx, field='acquisition_cost', value=raw_cost, message=str(exc))
                )

        w_start = None
        raw_wstart = get_val('warranty_start')
        if raw_wstart:
            try:
                w_start = parse_date_value(raw_wstart)
            except ValueError as exc:
                row_errors.append(
                    ImportRowError(row_number=idx, field='warranty_start', value=raw_wstart, message=str(exc))
                )

        w_end = None
        raw_wend = get_val('warranty_end')
        if raw_wend:
            try:
                w_end = parse_date_value(raw_wend)
            except ValueError as exc:
                row_errors.append(
                    ImportRowError(row_number=idx, field='warranty_end', value=raw_wend, message=str(exc))
                )

        if w_start and w_end and w_end < w_start:
            row_errors.append(
                ImportRowError(
                    row_number=idx,
                    field='warranty_end',
                    value=str(w_end),
                    message='Warranty end date must be on or after warranty start date',
                )
            )
        elif w_start and not w_end:
            warnings.append(
                ImportRowWarning(
                    row_number=idx,
                    field='warranty_end',
                    message='Warranty start date is provided without a warranty end date',
                )
            )

        manufacturer = get_val('manufacturer')
        if manufacturer and len(manufacturer) > 120:
            row_errors.append(
                ImportRowError(
                    row_number=idx,
                    field='manufacturer',
                    value=manufacturer,
                    message='Manufacturer exceeds maximum length of 120 characters',
                )
            )

        model = get_val('model')
        if model and len(model) > 120:
            row_errors.append(
                ImportRowError(
                    row_number=idx,
                    field='model',
                    value=model,
                    message='Model exceeds maximum length of 120 characters',
                )
            )

        custodian = get_val('custodian_name')
        if custodian and len(custodian) > 160:
            row_errors.append(
                ImportRowError(
                    row_number=idx,
                    field='custodian_name',
                    value=custodian,
                    message='Custodian name exceeds maximum length of 160 characters',
                )
            )

        vendor_ref = get_val('vendor_reference')
        if vendor_ref and len(vendor_ref) > 160:
            row_errors.append(
                ImportRowError(
                    row_number=idx,
                    field='vendor_reference',
                    value=vendor_ref,
                    message='Vendor reference exceeds maximum length of 160 characters',
                )
            )

        invoice_ref = get_val('invoice_reference')
        if invoice_ref and len(invoice_ref) > 160:
            row_errors.append(
                ImportRowError(
                    row_number=idx,
                    field='invoice_reference',
                    value=invoice_ref,
                    message='Invoice reference exceeds maximum length of 160 characters',
                )
            )

        notes = get_val('notes')

        if row_errors:
            errors.extend(row_errors)
        elif resolved_cat:
            payload = AssetCreate(
                category_id=resolved_cat.id,
                asset_number=asset_num_val,
                serial_number=serial_val,
                manufacturer=manufacturer,
                model=model,
                status=status_val,
                site_id=resolved_site.id if resolved_site else None,
                location_id=resolved_loc.id if resolved_loc else None,
                responsible_department_id=resolved_dept.id if resolved_dept else None,
                cost_center_id=resolved_cc.id if resolved_cc else None,
                acquisition_date=acq_date,
                acquisition_cost=acq_cost,
                custodian_name=custodian,
                vendor_reference=vendor_ref,
                invoice_reference=invoice_ref,
                warranty_start=w_start,
                warranty_end=w_end,
                notes=notes,
            )
            validated_payloads.append(payload)

        # Keep first 25 rows for UI table preview
        if len(preview_rows) < 25:
            preview_rows.append({
                'row_number': idx,
                'category_code': cat_val or '',
                'category_name': resolved_cat.name if resolved_cat else '',
                'serial_number': serial_val or '',
                'manufacturer': manufacturer or '',
                'model': model or '',
                'status': status_val,
                'site_code': site_val or '',
                'location_code': loc_val or '',
                'department_code': dept_val or '',
                'cost_center_code': cc_val or '',
                'acquisition_date': str(acq_date) if acq_date else '',
                'acquisition_cost': str(acq_cost) if acq_cost is not None else '',
                'has_errors': len(row_errors) > 0,
            })

    total_valid = len(validated_payloads)
    total_invalid = len({e.row_number for e in errors})
    total_processed = total_valid + total_invalid

    preview_token: str | None = None
    # Staging token is only issued if all rows are completely valid (all-or-nothing guarantee)
    if total_invalid == 0 and total_valid > 0:
        preview_token = str(uuid4())
        with _STAGING_LOCK:
            _clean_staging_store()
            _STAGING_STORE[preview_token] = StagedImport(
                token=preview_token,
                company_id=company_id,
                actor_id=actor_id,
                created_at=time.time(),
                rows=validated_payloads,
                row_count=total_valid,
                is_processing=False,
            )

    return AssetImportPreviewResponse(
        valid=total_invalid == 0 and total_valid > 0,
        total_rows=total_processed,
        valid_rows=total_valid,
        invalid_rows=total_invalid,
        preview_token=preview_token,
        errors=errors,
        warnings=warnings,
        preview_rows=preview_rows,
    )


def confirm_import(
    db: Session,
    company_id: UUID,
    actor_id: UUID,
    preview_token: str,
) -> AssetImportConfirmResponse:
    get_company(db, company_id, active=True)

    with _STAGING_LOCK:
        _clean_staging_store()
        staged = _STAGING_STORE.get(preview_token)
        if staged is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail='Invalid or expired import preview token. Please re-upload and preview your file.',
            )

        if staged.is_processing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail='Import for this preview token is already being processed.',
            )

        # Mark in-progress atomically to prevent concurrent race conditions
        staged.is_processing = True

    # Validate company and actor ownership
    if staged.company_id != company_id:
        with _STAGING_LOCK:
            staged.is_processing = False
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail='Preview token does not belong to this company',
        )

    if staged.actor_id != actor_id:
        with _STAGING_LOCK:
            staged.is_processing = False
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail='Preview token was created by a different user session',
        )

    # Re-validate serial numbers right before creating assets to close interim race window
    batch_serials = [r.serial_number for r in staged.rows if r.serial_number]
    if batch_serials:
        conflicting_serials = set(
            db.scalars(
                select(Asset.serial_number).where(
                    Asset.company_id == company_id,
                    Asset.serial_number.in_(batch_serials),
                )
            ).all()
        )
        if conflicting_serials:
            with _STAGING_LOCK:
                staged.is_processing = False
            conflicts = ', '.join(sorted(conflicting_serials))
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f'Serial numbers conflicted with records created after preview: {conflicts}',
            )

    created_assets: list[Asset] = []
    try:
        for payload in staged.rows:
            asset = create_asset(db, company_id, payload, commit=False)
            created_assets.append(asset)
        db.flush()

        # Audit event for the bulk import operation
        record_security_event(
            db,
            action='asset.bulk_import',
            entity_type='Asset',
            company_id=company_id,
            actor_id=actor_id,
            outcome='success',
            changes={
                'imported_count': len(created_assets),
                'token': preview_token,
                'first_asset_number': created_assets[0].asset_number if created_assets else None,
                'last_asset_number': created_assets[-1].asset_number if created_assets else None,
            },
        )
        db.commit()
    except Exception as exc:
        db.rollback()
        with _STAGING_LOCK:
            # Unmark processing flag so user can retry if appropriate
            staged.is_processing = False
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f'Failed to import asset batch: {str(exc)}',
        ) from exc

    # Clean up staging cache on successful commit
    with _STAGING_LOCK:
        _STAGING_STORE.pop(preview_token, None)

    return AssetImportConfirmResponse(
        imported_count=len(created_assets),
        asset_numbers=[a.asset_number for a in created_assets],
    )
