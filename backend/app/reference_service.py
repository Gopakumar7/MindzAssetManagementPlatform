"""Central reference-number generation service for MindZen ERP.

Implements company-specific, concurrency-safe reference allocation
with permanent and financial-year numbering, strict prefix immutability,
collision protection, and controlled audit logging for exceptional support operations.
"""

from datetime import date, datetime
from typing import Any
from uuid import UUID, uuid4
import zoneinfo

from sqlalchemy import func, inspect, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models import Company, ReferenceSequence, ReferenceSequenceAudit

DEFAULT_TIMEZONE = zoneinfo.ZoneInfo("Asia/Kolkata")

DEFAULT_ENTITY_CONFIGS: dict[str, dict[str, Any]] = {
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

# Allowlisted table and reference column mappings for collision checks
ENTITY_REFERENCE_TARGETS: dict[str, dict[str, str]] = {
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
        company_id: UUID,
        entity_type: str,
        fiscal_year: str,
        is_permanent: bool = False,
    ) -> ReferenceSequence:
        """
        Ensures a reference_sequences row exists for the given company, entity_type, and fiscal_year.
        Lazy creation of future financial-year sequence rows is permitted ONLY when an approved
        prior sequence configuration already exists for that company and entity type.
        Unprovisioned companies or unapproved entity configurations raise SequenceNotFoundError.
        """
        existing = db.scalar(
            select(ReferenceSequence).where(
                ReferenceSequence.company_id == company_id,
                ReferenceSequence.entity_type == entity_type,
                ReferenceSequence.fiscal_year == fiscal_year,
            )
        )
        if existing:
            if not existing.is_active:
                raise SequenceInactiveError(
                    f"Reference sequence for entity '{entity_type}' ({fiscal_year}) in company {company_id} is inactive."
                )
            return existing

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
        company_id: UUID,
        entity_type: str,
        business_date: date | datetime | None = None,
        is_permanent: bool | None = None,
    ) -> str:
        """
        Atomically increments and returns the next formatted reference number.
        Uses PostgreSQL row-level locking (UPDATE ... RETURNING) to guarantee concurrency safety.
        Allocation occurs within caller's transaction; does not introduce internal commits.
        """
        cfg = DEFAULT_ENTITY_CONFIGS.get(entity_type, {})
        if is_permanent is None:
            is_perm = cfg.get("is_permanent", False)
        else:
            is_perm = is_permanent

        fy_token = "PERMANENT" if is_perm else cls.get_fiscal_year(business_date)

        # Atomic increment with row-level lock
        stmt = (
            update(ReferenceSequence)
            .where(
                ReferenceSequence.company_id == company_id,
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
                    ReferenceSequence.company_id == company_id,
                    ReferenceSequence.entity_type == entity_type,
                    ReferenceSequence.fiscal_year == fy_token,
                )
            )
            if existing and not existing.is_active:
                raise SequenceInactiveError(
                    f"Reference sequence for entity '{entity_type}' ({fy_token}) in company {company_id} is inactive."
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
    ) -> list[ReferenceSequence]:
        """
        Controlled company provisioning helper.
        Explicitly initializes sequences for all standard entities for a company.
        Requires an explicit prefix_base. Automatic derivation from company code
        or generic fallback prefixes ('ORG') are strictly prohibited.
        """
        clean_prefix_base = (prefix_base or "").strip().upper()
        if not clean_prefix_base:
            raise ValueError(
                "An explicit, non-empty prefix_base is required to provision company sequences. "
                "Automatic derivation from company code or generic fallbacks are not permitted."
            )

        company = db.get(Company, company_id)
        if not company:
            raise ValueError(f"Company {company_id} does not exist")

        fy = fiscal_year or cls.get_fiscal_year()
        sequences = []

        for ent_type, cfg in DEFAULT_ENTITY_CONFIGS.items():
            is_perm = cfg.get("is_permanent", False)
            fy_token = "PERMANENT" if is_perm else fy
            prefix = f"{clean_prefix_base}-{cfg.get('suffix', ent_type.upper())}"
            padding = cfg.get("padding", 5)

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
                    separator="-",
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
