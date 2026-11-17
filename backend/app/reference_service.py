"""Central reference-number generation service for MindZen ERP.

Implements company-specific, concurrency-safe reference allocation
with permanent and financial-year numbering, strict prefix immutability,
collision protection, and controlled audit logging for exceptional support operations.
"""

import re
from datetime import date, datetime, timezone
from typing import Any
from uuid import UUID, uuid4
import zoneinfo

from sqlalchemy import func, inspect, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.audit import record_security_event
from app.models import Company, ReferenceSequence, ReferenceSequenceAudit, User
from app.security import actor_has_permission

DEFAULT_TIMEZONE = zoneinfo.ZoneInfo("Asia/Kolkata")

DEFAULT_ENTITY_CONFIGS: dict[str, dict[str, Any]] = {
    "company": {"prefix": "CMP", "separator": "-", "padding": 4, "is_permanent": True, "scope": "system"},
    "asset": {"suffix": "AST", "padding": 6, "is_permanent": True},
    "purchase_order": {"suffix": "PO", "padding": 5, "is_permanent": False},
    "goods_receipt": {"suffix": "GRN", "padding": 5, "is_permanent": False},
    "verification_campaign": {"suffix": "VC", "padding": 5, "is_permanent": False},
    "service_request": {"suffix": "SR", "padding": 5, "is_permanent": False},
    "maintenance_work_order": {"suffix": "MWO", "padding": 5, "is_permanent": False},
    "asset_transfer": {"suffix": "TRF", "padding": 5, "is_permanent": False},
    "asset_disposal": {"suffix": "DSP", "padding": 5, "is_permanent": False},
    "goods_return": {"suffix": "GRR", "padding": 5, "is_permanent": False},
}

MAX_COMPANY_CODE_LENGTH = 24
MAX_ENTITY_PREFIX_LENGTH = 28
ASSET_PREFIX_PATTERN = r"^[A-Za-z0-9]+(?:[_-][A-Za-z0-9]+)*$"
ALLOWED_NUMBER_SEPARATORS: tuple[str, ...] = ("-", "/")
DEFAULT_ASSET_PREFIX = "AST"


def normalize_company_prefix_base(raw_base: str, company_code: str | None = None) -> str:
    """Validates and normalizes a Company Code for operational sequence provisioning.

    Never silently truncates: enforces 1..24 characters (matching the 24-char rule column and
    leaving 4 characters for '-{SUFFIX}' within the 32-char sequence prefix column).
    """
    clean = (raw_base or "").strip().upper()
    if not clean:
        raise ValueError("Company code / prefix base cannot be empty.")
    if len(clean) > MAX_COMPANY_CODE_LENGTH:
        raise ValueError(
            f"Company code '{clean}' ({len(clean)} characters) exceeds the maximum supported length "
            f"of {MAX_COMPANY_CODE_LENGTH} characters."
        )
    if not re.fullmatch(r"[A-Z0-9]+(?:[_-][A-Z0-9]+)*", clean):
        raise ValueError(
            "Company code / prefix must contain only letters, digits, hyphens, or underscores "
            "(no leading/trailing separators or spaces)."
        )
    dash_parts = clean.split("-")
    if len(dash_parts) >= 2 and any(dash_parts[i] == dash_parts[i + 1] for i in range(len(dash_parts) - 1)):
        raise ValueError(f"Prefix '{clean}' contains duplicated segments (e.g. 'MO-MO-AST' is not permitted).")
    if clean.endswith("-AST") and len(clean) > 4:
        clean = clean[:-4]
    if company_code:
        cc = company_code.strip().upper()
        if clean == f"{cc}-{cc}":
            raise ValueError(f"Prefix '{clean}' contains duplicated company code '{cc}'.")
    return clean


def build_entity_prefix(prefix_base: str, entity_suffix: str) -> str:
    """Constructs '{COMPANY_CODE}-{ENTITY_IDENTIFIER}' without duplicating suffixes."""
    base = normalize_company_prefix_base(prefix_base)
    sfx = (entity_suffix or "").strip().upper()
    if not sfx:
        return base
    if base.endswith(f"-{sfx}"):
        return base
    return f"{base}-{sfx}"


def validate_numbering_format(
    prefix: str,
    separator: str,
    padding: int | None = None,
    entity_suffix: str | None = None,
) -> tuple[str, str]:
    """Single source of truth for asset numbering prefix/separator/padding validation.

    Supports company-code-based prefixes such as 'MO-AST' (or 'MO', which normalizes to 'MO-AST'
    when entity_suffix='AST') while rejecting duplicated prefixes such as 'MO-MO-AST' or 'AST-AST'.
    """
    clean = (prefix or "").strip().upper()
    if not clean or len(clean) > 28 or not re.fullmatch(r"[A-Z0-9]+(?:[_-][A-Z0-9]+)*", clean):
        raise ValueError(
            "Prefix must be 1-28 letters or digits (with optional '-' or '_' between segments, e.g. 'MO-AST')."
        )
    parts = clean.split("-")
    if len(parts) >= 2 and any(parts[i] == parts[i + 1] for i in range(len(parts) - 1)):
        raise ValueError(
            f"Prefix '{clean}' contains duplicated segments (e.g. 'MO-MO-AST' is not permitted)."
        )
    if entity_suffix:
        sfx = entity_suffix.strip().upper()
        if clean == sfx:
            raise ValueError(
                f"Prefix '{clean}' must include the company code before '{sfx}' (e.g. 'MO-{sfx}')."
            )
        if parts[-1] != sfx:
            clean = f"{clean}-{sfx}"
            if len(clean) > 28:
                raise ValueError("Prefix must not exceed 28 characters including entity suffix.")
    if separator not in ALLOWED_NUMBER_SEPARATORS:
        raise ValueError("Separator must be one of: " + ", ".join(ALLOWED_NUMBER_SEPARATORS))
    if padding is not None and not 1 <= padding <= 12:
        raise ValueError("Padding must be between 1 and 12")
    return clean, separator


# Allowlisted table and reference column mappings for collision checks
ENTITY_REFERENCE_TARGETS: dict[str, dict[str, str]] = {
    "company": {"table": "companies", "column": "reference_number"},
    "asset": {"table": "assets", "column": "asset_number"},
    "purchase_order": {"table": "purchase_orders", "column": "order_number"},
    "goods_receipt": {"table": "goods_receipts", "column": "receipt_number"},
    "verification_campaign": {"table": "verification_campaigns", "column": "campaign_reference"},
    "service_request": {"table": "maintenance_requests", "column": "request_number"},
    "maintenance_work_order": {"table": "maintenance_requests", "column": "work_order_number"},
    "asset_transfer": {"table": "asset_assignments", "column": "reference"},
    "asset_disposal": {"table": "asset_disposals", "column": "disposal_reference"},
    "goods_return": {"table": "goods_returns", "column": "return_number"},
}


class PrefixImmutabilityError(Exception):
    """Raised when an unauthorized attempt is made to modify an immutable sequence prefix."""
    pass


class SequenceNotFoundError(Exception):
    """Raised when a requested reference sequence cannot be found or initialized."""
    pass


class SequenceInactiveError(Exception):
    """Raised when reference allocation is attempted on an inactive sequence configuration."""
    pass


class ReservedPrefixCollisionError(Exception):
    """Raised when a manual identifier conflicts with a reserved managed sequence prefix."""
    pass


class ReferenceNumberService:
    @staticmethod
    def get_fiscal_year(target_date: date | datetime | None = None, start_month: int = 4) -> str:
        """
        Calculates the Indian Financial Year string (e.g. '2026-27')
        for a given date. Financial year runs April 1 to March 31.
        Evaluates current date in Asia/Kolkata (IST).
        """
        if target_date is None:
            dt = datetime.now(DEFAULT_TIMEZONE).date()
        elif isinstance(target_date, datetime):
            if target_date.tzinfo is None:
                # Naive datetime: assume it is already in Asia/Kolkata
                dt = target_date.date()
            else:
                dt = target_date.astimezone(DEFAULT_TIMEZONE).date()
        elif isinstance(target_date, date):
            dt = target_date
        else:
            raise ValueError(f"Invalid target_date type: {type(target_date)}")

        year = dt.year
        month = dt.month

        if month >= start_month:
            start_yr = year
            end_yr = year + 1
        else:
            start_yr = year - 1
            end_yr = year

        return f"{start_yr}-{str(end_yr)[-2:]}"

    @classmethod
    def ensure_sequence_exists(
        cls,
        db: Session,
        company_id: UUID | None,
        entity_type: str,
        fiscal_year: str,
        is_permanent: bool = False,
    ) -> ReferenceSequence:
        """
        Ensures a reference_sequences row exists for the given company (or system-wide),
        entity_type, and fiscal_year.
        Lazy creation of future financial-year sequence rows is permitted ONLY when an approved
        prior sequence configuration already exists for that company and entity type.
        Unprovisioned companies or unapproved entity configurations raise SequenceNotFoundError.
        """
        company_filter = (
            ReferenceSequence.company_id.is_(None)
            if company_id is None
            else ReferenceSequence.company_id == company_id
        )
        existing = db.scalar(
            select(ReferenceSequence).where(
                company_filter,
                ReferenceSequence.entity_type == entity_type,
                ReferenceSequence.fiscal_year == fiscal_year,
            )
        )
        if existing:
            if not existing.is_active:
                scope_str = "System-wide" if company_id is None else f"in company {company_id}"
                raise SequenceInactiveError(
                    f"Reference sequence for entity '{entity_type}' ({fiscal_year}) {scope_str} is inactive."
                )
            return existing

        if company_id is None:
            # System-level sequence (e.g. company reference numbers CMP-0001, etc.)
            cfg = DEFAULT_ENTITY_CONFIGS.get(entity_type, {})
            prefix = cfg.get("prefix", "CMP")
            separator = cfg.get("separator", "-")
            padding = cfg.get("padding", 4)
            is_postgres = db.get_bind().dialect.name == "postgresql"
            new_id = uuid4()
            if is_postgres:
                stmt = (
                    pg_insert(ReferenceSequence)
                    .values(
                        id=new_id,
                        company_id=None,
                        entity_type=entity_type,
                        fiscal_year=fiscal_year,
                        prefix=prefix,
                        separator=separator,
                        padding=padding,
                        current_value=0,
                        is_active=True,
                    )
                    .on_conflict_do_nothing(
                        index_elements=["entity_type", "fiscal_year"],
                        index_where=ReferenceSequence.company_id.is_(None),
                    )
                )
                db.execute(stmt)
                db.flush()
            else:
                try:
                    with db.begin_nested():
                        seq = ReferenceSequence(
                            id=new_id,
                            company_id=None,
                            entity_type=entity_type,
                            fiscal_year=fiscal_year,
                            prefix=prefix,
                            separator=separator,
                            padding=padding,
                            current_value=0,
                            is_active=True,
                        )
                        db.add(seq)
                        db.flush()
                except Exception:
                    pass

            seq = db.scalar(
                select(ReferenceSequence).where(
                    ReferenceSequence.company_id.is_(None),
                    ReferenceSequence.entity_type == entity_type,
                    ReferenceSequence.fiscal_year == fiscal_year,
                )
            )
            if seq is None:
                raise SequenceNotFoundError(
                    f"Failed to initialize system sequence for entity={entity_type}, fy={fiscal_year}"
                )
            return seq

        # Look up existing approved sequence configuration for this company and entity type from another FY
        prior_seq = db.scalar(
            select(ReferenceSequence)
            .where(
                ReferenceSequence.company_id == company_id,
                ReferenceSequence.entity_type == entity_type,
            )
            .order_by(ReferenceSequence.created_at.desc())
        )

        if not prior_seq:
            company = db.get(Company, company_id)
            comp_label = f"'{company.code}' ({company_id})" if company else str(company_id)
            raise SequenceNotFoundError(
                f"Company {comp_label} has not been provisioned with numbering rules for entity '{entity_type}'. "
                f"Explicit company provisioning is required."
            )

        if not prior_seq.is_active:
            raise SequenceInactiveError(
                f"Reference sequence configuration for entity '{entity_type}' in company {company_id} is inactive."
            )

        prefix = prior_seq.prefix
        separator = prior_seq.separator
        padding = prior_seq.padding

        # In PostgreSQL use ON CONFLICT DO NOTHING to guarantee safe parallel creation
        is_postgres = db.get_bind().dialect.name == "postgresql"
        new_id = uuid4()
        if is_postgres:
            stmt = (
                pg_insert(ReferenceSequence)
                .values(
                    id=new_id,
                    company_id=company_id,
                    entity_type=entity_type,
                    fiscal_year=fiscal_year,
                    prefix=prefix,
                    separator=separator,
                    padding=padding,
                    current_value=0,
                    is_active=True,
                )
                .on_conflict_do_nothing(
                    index_elements=["company_id", "entity_type", "fiscal_year"]
                )
            )
            db.execute(stmt)
            db.flush()
        else:
            try:
                seq = ReferenceSequence(
                    id=new_id,
                    company_id=company_id,
                    entity_type=entity_type,
                    fiscal_year=fiscal_year,
                    prefix=prefix,
                    separator=separator,
                    padding=padding,
                    current_value=0,
                    is_active=True,
                )
                db.add(seq)
                db.flush()
            except Exception:
                db.rollback()

        seq = db.scalar(
            select(ReferenceSequence).where(
                ReferenceSequence.company_id == company_id,
                ReferenceSequence.entity_type == entity_type,
                ReferenceSequence.fiscal_year == fiscal_year,
            )
        )
        if seq is None:
            raise SequenceNotFoundError(
                f"Failed to initialize sequence for company={company_id}, entity={entity_type}, fy={fiscal_year}"
            )
        return seq

    @classmethod
    def allocate(
        cls,
        db: Session,
        company_id: UUID | None,
        entity_type: str,
        business_date: date | datetime | None = None,
        is_permanent: bool | None = None,
    ) -> str:
        """
        Atomically increments and returns the next formatted reference number.
        Uses PostgreSQL row-level locking (UPDATE ... RETURNING) to guarantee concurrency safety.
        Allocation occurs within caller's transaction; does not introduce internal commits.
        Supports both tenant-scoped (company_id: UUID) and system-scoped (company_id: None) sequences.
        """
        cfg = DEFAULT_ENTITY_CONFIGS.get(entity_type, {})
        if is_permanent is None:
            is_perm = cfg.get("is_permanent", False)
        else:
            is_perm = is_permanent

        fy_token = "PERMANENT" if is_perm else cls.get_fiscal_year(business_date)
        company_filter = (
            ReferenceSequence.company_id.is_(None)
            if company_id is None
            else ReferenceSequence.company_id == company_id
        )

        # Atomic increment with row-level lock
        stmt = (
            update(ReferenceSequence)
            .where(
                company_filter,
                ReferenceSequence.entity_type == entity_type,
                ReferenceSequence.fiscal_year == fy_token,
                ReferenceSequence.is_active.is_(True),
            )
            .values(
                current_value=ReferenceSequence.current_value + 1,
                updated_at=func.now(),
            )
            .returning(
                ReferenceSequence.prefix,
                ReferenceSequence.separator,
                ReferenceSequence.padding,
                ReferenceSequence.current_value,
            )
        )
        row = db.execute(stmt).one_or_none()

        if row is None:
            # Check if sequence exists but is inactive
            existing = db.scalar(
                select(ReferenceSequence).where(
                    company_filter,
                    ReferenceSequence.entity_type == entity_type,
                    ReferenceSequence.fiscal_year == fy_token,
                )
            )
            if existing and not existing.is_active:
                scope_str = "System-wide" if company_id is None else f"in company {company_id}"
                raise SequenceInactiveError(
                    f"Reference sequence for entity '{entity_type}' ({fy_token}) {scope_str} is inactive."
                )

            # Sequence row does not exist yet; lazily initialize it and retry
            # ensure_sequence_exists will reject unprovisioned companies
            cls.ensure_sequence_exists(db, company_id, entity_type, fy_token, is_permanent=is_perm)
            row = db.execute(stmt).one_or_none()
            if row is None:
                raise SequenceNotFoundError(
                    f"Unable to allocate reference for company={company_id}, entity={entity_type}, fy={fy_token}"
                )

        prefix, sep, padding, allocated_num = row

        if is_perm:
            return f"{prefix}{sep}{allocated_num:0{padding}d}"
        else:
            return f"{prefix}{sep}{fy_token}{sep}{allocated_num:0{padding}d}"

    @classmethod
    def allocate_company_reference(cls, db: Session) -> str:
        """
        Atomically allocates the next platform-wide system-generated company reference number.
        Format: CMP-0001, CMP-0002, CMP-0003...
        Uses centralized reference sequence infrastructure with row-level locking.
        """
        return cls.allocate(db, company_id=None, entity_type="company", is_permanent=True)

    @classmethod
    def validate_manual_identifier(
        cls,
        db: Session,
        company_id: UUID,
        entity_type: str,
        identifier: str,
    ) -> None:
        """
        Validates that a manual business identifier does not collide with the company's
        reserved managed sequence prefix for the entity type.
        Prefix matching uses the exact configured namespace boundary (prefix + separator),
        not a loose substring match.
        """
        clean_id = (identifier or "").strip()
        if not clean_id:
            return

        seq = db.scalar(
            select(ReferenceSequence).where(
                ReferenceSequence.company_id == company_id,
                ReferenceSequence.entity_type == entity_type,
                ReferenceSequence.is_active.is_(True),
            )
        )
        if seq is None:
            raise SequenceNotFoundError(
                f"Company {company_id} has not been provisioned with {entity_type} numbering rules."
            )

        managed_boundary = f"{seq.prefix}{seq.separator}".upper()
        id_upper = clean_id.upper()
        if id_upper == seq.prefix.upper() or id_upper.startswith(managed_boundary):
            raise ReservedPrefixCollisionError(
                f"Manual {entity_type.replace('_', ' ')} identifier '{clean_id}' conflicts with the "
                f"managed sequence prefix '{seq.prefix}'. Manual identifiers cannot use the active generated prefix."
            )

    @classmethod
    def provision_company_sequences(
        cls,
        db: Session,
        company_id: UUID,
        prefix_base: str,
        fiscal_year: str | None = None,
        asset_prefix: str | None = None,
        asset_separator: str = "-",
        asset_padding: int | None = None,
    ) -> list[ReferenceSequence]:
        """
        Controlled company provisioning helper.
        Explicitly initializes sequences for all standard entities for a company.
        Requires an explicit prefix_base. Automatic derivation from company code
        or generic fallback prefixes ('ORG') are strictly prohibited.
        """
        raw_prefix_base = (prefix_base or "").strip()
        if not raw_prefix_base:
            raise ValueError(
                "An explicit, non-empty prefix_base is required to provision company sequences. "
                "Automatic derivation from company name or generic fallbacks are not permitted."
            )

        company = db.get(Company, company_id)
        if not company:
            raise ValueError(f"Company {company_id} does not exist")

        clean_prefix_base = normalize_company_prefix_base(raw_prefix_base, company_code=company.code)
        fy = fiscal_year or cls.get_fiscal_year()
        sequences = []

        for ent_type, cfg in DEFAULT_ENTITY_CONFIGS.items():
            if cfg.get("scope") == "system" or ent_type == "company":
                continue
            is_perm = cfg.get("is_permanent", False)
            fy_token = "PERMANENT" if is_perm else fy
            suffix = cfg.get("suffix", ent_type.upper())
            prefix = build_entity_prefix(clean_prefix_base, suffix)
            padding = cfg.get("padding", 5)
            separator = "-"
            if ent_type == "asset":
                target_asset_prefix = asset_prefix if asset_prefix is not None else prefix
                prefix, separator = validate_numbering_format(
                    target_asset_prefix, asset_separator, asset_padding, entity_suffix="AST"
                )
                padding = asset_padding or padding

            seq = db.scalar(
                select(ReferenceSequence).where(
                    ReferenceSequence.company_id == company_id,
                    ReferenceSequence.entity_type == ent_type,
                    ReferenceSequence.fiscal_year == fy_token,
                )
            )
            if not seq:
                seq = ReferenceSequence(
                    id=uuid4(),
                    company_id=company_id,
                    entity_type=ent_type,
                    fiscal_year=fy_token,
                    prefix=prefix,
                    separator=separator,
                    padding=padding,
                    current_value=0,
                    is_active=True,
                )
                db.add(seq)
                sequences.append(seq)
            else:
                sequences.append(seq)

        db.flush()
        return sequences

    @classmethod
    def update_sequence_standard(
        cls,
        db: Session,
        sequence_id: UUID,
        new_prefix: str,
        new_padding: int | None = None,
    ) -> ReferenceSequence:
        """
        Standard sequence update.
        Enforces strict prefix immutability: once current_value > 0, normal updates are blocked.
        """
        seq = db.scalar(
            select(ReferenceSequence)
            .where(ReferenceSequence.id == sequence_id)
            .with_for_update()
        )
        if not seq:
            raise SequenceNotFoundError(f"Sequence {sequence_id} not found")

        if seq.current_value > 0 and seq.prefix != new_prefix:
            raise PrefixImmutabilityError(
                f"Prefix for sequence '{seq.entity_type}' ({seq.fiscal_year}) is immutable "
                f"because {seq.current_value} references have already been issued. "
                "Exceptional changes require the controlled support procedure with an audit ticket."
            )

        seq.prefix = new_prefix
        if new_padding is not None:
            seq.padding = new_padding
        seq.updated_at = func.now()
        db.flush()
        return seq

    @classmethod
    def update_prefix_controlled(
        cls,
        db: Session,
        sequence_id: UUID,
        new_prefix: str,
        reason: str,
        performed_by_id: UUID,
        ticket_reference: str,
        new_padding: int | None = None,
    ) -> ReferenceSequence:
        """
        Controlled support procedure for exceptional prefix changes.
        Requires reason, operator ID, and ticket reference, and writes an immutable audit record.
        Validates collision protection against existing records in target entity tables before mutating.
        Preserves current_value to prevent duplicate reference issuance.
        """
        clean_reason = (reason or "").strip()
        if not clean_reason:
            raise ValueError("A documented reason is required for controlled prefix changes")

        clean_ticket = (ticket_reference or "").strip()
        if not clean_ticket:
            raise ValueError("A ticket reference is required for controlled prefix changes")

        clean_prefix = (new_prefix or "").strip()
        if not clean_prefix:
            raise ValueError("A new prefix string is required")

        if not performed_by_id:
            raise ValueError("performed_by_id (operator user ID) is required")

        seq = db.scalar(
            select(ReferenceSequence)
            .where(ReferenceSequence.id == sequence_id)
            .with_for_update()
        )
        if not seq:
            raise SequenceNotFoundError(f"Sequence {sequence_id} not found")

        # Collision protection: verify target entity table and reference column mapping
        target_mapping = ENTITY_REFERENCE_TARGETS.get(seq.entity_type)
        if not target_mapping:
            raise ValueError(
                f"Entity type '{seq.entity_type}' is not recognized in allowlisted reference targets; "
                "collision check cannot be performed safely."
            )

        table_name = target_mapping["table"]
        col_name = target_mapping["column"]

        inspector = inspect(db.get_bind())
        if not inspector.has_table(table_name):
            raise ValueError(
                f"Cannot verify prefix collisions safely: table '{table_name}' does not exist in schema"
            )

        cols = [c["name"] for c in inspector.get_columns(table_name)]
        if col_name not in cols:
            raise ValueError(
                f"Cannot verify prefix collisions safely: column '{col_name}' does not exist on table '{table_name}'"
            )

        # Collision query: check if any references already exist starting with clean_prefix
        if clean_prefix != seq.prefix:
            escaped_prefix = clean_prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            pattern = f"{escaped_prefix}%"
            collision_query = text(
                f"SELECT 1 FROM {table_name} WHERE company_id = :cid AND {col_name} LIKE :pat ESCAPE '\\' LIMIT 1"
            )
            cid_param = seq.company_id.hex if db.get_bind().dialect.name == "sqlite" else seq.company_id
            has_collision = db.execute(collision_query, {"cid": cid_param, "pat": pattern}).scalar()
            if has_collision:
                raise ValueError(
                    f"Cannot update prefix to '{clean_prefix}': references starting with this prefix already exist in {table_name}"
                )

            # Check if another sequence in the same company already uses clean_prefix
            other_seq = db.scalar(
                select(ReferenceSequence).where(
                    ReferenceSequence.company_id == seq.company_id,
                    ReferenceSequence.id != seq.id,
                    ReferenceSequence.prefix == clean_prefix,
                )
            )
            if other_seq:
                raise ValueError(
                    f"Cannot update prefix to '{clean_prefix}': prefix is already in use by sequence "
                    f"'{other_seq.entity_type}' ({other_seq.fiscal_year})"
                )

        old_prefix = seq.prefix
        old_padding = seq.padding
        target_padding = new_padding if new_padding is not None else old_padding

        # Record immutable audit log
        audit = ReferenceSequenceAudit(
            id=uuid4(),
            sequence_id=seq.id,
            company_id=seq.company_id,
            entity_type=seq.entity_type,
            fiscal_year=seq.fiscal_year,
            old_prefix=old_prefix,
            new_prefix=clean_prefix,
            old_padding=old_padding,
            new_padding=target_padding,
            reason=clean_reason,
            performed_by_id=performed_by_id,
            ticket_reference=clean_ticket,
        )
        db.add(audit)

        # Update sequence prefix and padding while preserving current_value
        seq.prefix = clean_prefix
        seq.padding = target_padding
        seq.updated_at = func.now()

        db.flush()
        return seq

    DEFAULT_ALIGNMENT_REASON = (
        "Standardize unissued legacy default prefix to company-code convention "
        "({COMPANY_CODE}-{ENTITY_IDENTIFIER})"
    )

    @classmethod
    def align_unissued_company_sequences(
        cls,
        db: Session,
        company_id: UUID,
        *,
        performed_by_id: UUID | None = None,
        reason: str = DEFAULT_ALIGNMENT_REASON,
        allow_inactive_company: bool = False,
        commit: bool = True,
    ) -> list[ReferenceSequence]:
        """Explicit transactional operation that aligns unissued (current_value == 0) operational
        sequences carrying eligible legacy default prefixes ('AST', 'AST-AST', 'AST-{SUFFIX}')
        to the company-code convention ('{COMPANY_CODE}-{SUFFIX}').

        - Rejects dirty sessions so unrelated pending changes can never be accidentally committed.
        - Enforces explicit authorization (and requires System Administrator 'system.companies.manage'
          plus allow_inactive_company=True when aligning an inactive company, preserving its inactive status).
        - Locks relevant sequence rows with SELECT ... FOR UPDATE.
        - Checks current_value == 0 (never alters issued sequences).
        - Checks whether the prefix is an eligible legacy default (preserves custom prefixes).
        - Records one complete per-sequence AuditEvent for every sequence changed.
        - Commits all sequence updates and audit records atomically, or rolls back completely on failure.
        """
        if db.new or db.dirty or db.deleted:
            raise RuntimeError(
                "Session contains uncommitted pending changes; sequence alignment must run in a clean transaction boundary."
            )

        clean_reason = (reason or "").strip()
        if not clean_reason:
            raise ValueError("A non-empty reason is required for sequence alignment.")

        actor_id = performed_by_id if performed_by_id is not None else db.info.get("audit_actor_id")
        if actor_id is None:
            raise PermissionError("An authenticated acting user ID (performed_by_id) is required for sequence alignment.")

        actor = db.get(User, actor_id)
        if actor is None or not actor.is_active:
            raise PermissionError("Acting user must be an existing active user.")

        company = db.get(Company, company_id)
        if not company:
            raise ValueError(f"Company {company_id} does not exist")

        is_sys_company_admin = actor_has_permission(db, actor_id, None, "system.companies.manage")
        has_org_manage = actor_has_permission(db, actor_id, company_id, "organization.manage")
        has_company_read = is_sys_company_admin or actor_has_permission(db, actor_id, company_id, "company.read")

        if not company.is_active:
            if not allow_inactive_company or not (is_sys_company_admin and has_org_manage):
                raise PermissionError(
                    f"Company '{company.code}' ({company_id}) is inactive; aligning an inactive company "
                    "requires explicit System Administrator ('system.companies.manage') authorization."
                )
        else:
            if not (has_company_read and has_org_manage):
                raise PermissionError(
                    "Insufficient permission: 'organization.manage' is required to align company sequences."
                )

        base = normalize_company_prefix_base(company.code, company_code=company.code)
        if base == "AST":
            return []

        updated: list[ReferenceSequence] = []
        try:
            with db.begin_nested():
                seqs = db.scalars(
                    select(ReferenceSequence)
                    .where(ReferenceSequence.company_id == company_id)
                    .order_by(ReferenceSequence.entity_type)
                    .with_for_update()
                ).all()
                now_iso = datetime.now(timezone.utc).isoformat()
                for seq in seqs:
                    if seq.current_value > 0:
                        continue
                    cfg = DEFAULT_ENTITY_CONFIGS.get(seq.entity_type, {})
                    suffix = cfg.get("suffix", seq.entity_type.upper())
                    expected_prefix = build_entity_prefix(base, suffix)
                    eligible_legacy_defaults = {"AST", "AST-AST", f"AST-{suffix}"}
                    if seq.prefix in eligible_legacy_defaults and seq.prefix != expected_prefix:
                        old_prefix = seq.prefix
                        current_val = seq.current_value
                        cls.update_sequence_standard(db, seq.id, expected_prefix)
                        record_security_event(
                            db,
                            action="sequence.prefix_aligned",
                            entity_type="ReferenceSequence",
                            entity_id=str(seq.id),
                            actor_id=actor_id,
                            company_id=company.id,
                            outcome="success",
                            changes={
                                "operation": "align_unissued_company_sequences",
                                "reason": clean_reason,
                                "outcome": "success",
                                "timestamp": now_iso,
                                "actor_id": str(actor_id),
                                "company_id": str(company.id),
                                "company_reference": company.reference_number,
                                "company_code": company.code,
                                "sequence_id": str(seq.id),
                                "entity_type": seq.entity_type,
                                "fiscal_year": seq.fiscal_year,
                                "current_value": current_val,
                                "old_prefix": old_prefix,
                                "new_prefix": expected_prefix,
                                "before": {
                                    "prefix": old_prefix,
                                    "separator": seq.separator,
                                    "padding": seq.padding,
                                    "current_value": current_val,
                                },
                                "after": {
                                    "prefix": expected_prefix,
                                    "separator": seq.separator,
                                    "padding": seq.padding,
                                    "current_value": seq.current_value,
                                },
                            },
                        )
                        updated.append(seq)
                db.flush()
            if commit and updated:
                db.commit()
        except Exception:
            db.rollback()
            raise
        return updated

    @classmethod
    def get_asset_sequence(cls, db: Session, company_id: UUID) -> ReferenceSequence:
        seq = db.scalar(
            select(ReferenceSequence).where(
                ReferenceSequence.company_id == company_id,
                ReferenceSequence.entity_type == "asset",
                ReferenceSequence.fiscal_year == "PERMANENT",
            )
        )
        if seq is None:
            raise SequenceNotFoundError(f"Company {company_id} has no asset numbering sequence provisioned")
        return seq

    @classmethod
    def configure_asset_sequence(
        cls, db: Session, company_id: UUID, prefix: str, separator: str, padding: int
    ) -> tuple[ReferenceSequence, dict]:
        """Configure asset numbering ONLY while no reference has been issued (current_value == 0).

        Once any reference is issued the prefix/separator/padding are frozen; changes must go through
        update_prefix_controlled (reason, ticket, ReferenceSequenceAudit). Returns (sequence, before-snapshot).
        """
        clean_prefix, clean_sep = validate_numbering_format(
            prefix, separator, padding, entity_suffix="AST"
        )
        seq = db.scalar(
            select(ReferenceSequence)
            .where(
                ReferenceSequence.company_id == company_id,
                ReferenceSequence.entity_type == "asset",
                ReferenceSequence.fiscal_year == "PERMANENT",
            )
            .with_for_update()
        )
        if seq is None:
            raise SequenceNotFoundError(f"Company {company_id} has no asset numbering sequence provisioned")
        if seq.current_value > 0:
            raise PrefixImmutabilityError(
                f"Asset numbering is locked because {seq.current_value} reference(s) have already been issued. "
                "Changes require the controlled support procedure with an audit ticket."
            )
        before = {"prefix": seq.prefix, "separator": seq.separator, "padding": seq.padding}
        seq.prefix = clean_prefix
        seq.separator = clean_sep
        seq.padding = padding
        seq.updated_at = func.now()
        db.flush()
        return seq, before
