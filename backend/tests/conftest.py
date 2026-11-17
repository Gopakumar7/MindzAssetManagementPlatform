
def install_postgresql_triggers(engine):
    if engine.dialect.name != 'postgresql':
        return
    from sqlalchemy import text
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE OR REPLACE FUNCTION trg_fn_prevent_warehouse_receipt_mutation()
            RETURNS TRIGGER AS $$
            BEGIN
                IF TG_TABLE_NAME = 'goods_return_warehouse_receipts' THEN
                    RAISE EXCEPTION 'Warehouse receipt headers are strictly immutable and cannot be modified or deleted';
                ELSIF TG_TABLE_NAME = 'goods_return_warehouse_receipt_lines' THEN
                    IF TG_OP = 'DELETE' THEN
                        RAISE EXCEPTION 'Warehouse receipt lines cannot be deleted';
                    ELSIF TG_OP = 'UPDATE' THEN
                        IF (NEW.warehouse_receipt_id <> OLD.warehouse_receipt_id OR
                            NEW.goods_return_id <> OLD.goods_return_id OR
                            NEW.goods_return_line_id <> OLD.goods_return_line_id OR
                            NEW.asset_id <> OLD.asset_id OR
                            NEW.condition_on_return <> OLD.condition_on_return) THEN
                            RAISE EXCEPTION 'Core warehouse receipt line fields are immutable and cannot be modified';
                        END IF;
                    END IF;
                END IF;
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;

            DROP TRIGGER IF EXISTS trg_no_update_delete_gr_wr ON goods_return_warehouse_receipts;
            CREATE TRIGGER trg_no_update_delete_gr_wr
            BEFORE UPDATE OR DELETE ON goods_return_warehouse_receipts
            FOR EACH ROW EXECUTE FUNCTION trg_fn_prevent_warehouse_receipt_mutation();

            DROP TRIGGER IF EXISTS trg_no_update_delete_gr_wr_lines ON goods_return_warehouse_receipt_lines;
            CREATE TRIGGER trg_no_update_delete_gr_wr_lines
            BEFORE UPDATE OR DELETE ON goods_return_warehouse_receipt_lines
            FOR EACH ROW EXECUTE FUNCTION trg_fn_prevent_warehouse_receipt_mutation();

            CREATE OR REPLACE FUNCTION trg_fn_prevent_wr_correction_mutation()
            RETURNS TRIGGER AS $$
            BEGIN
                RAISE EXCEPTION 'Warehouse receipt correction records are append-only and strictly immutable';
            END;
            $$ LANGUAGE plpgsql;

            DROP TRIGGER IF EXISTS trg_no_update_delete_gr_wr_correction ON goods_return_warehouse_receipt_corrections;
            CREATE TRIGGER trg_no_update_delete_gr_wr_correction
            BEFORE UPDATE OR DELETE ON goods_return_warehouse_receipt_corrections
            FOR EACH ROW EXECUTE FUNCTION trg_fn_prevent_wr_correction_mutation();

            CREATE OR REPLACE FUNCTION reject_reference_sequence_audit_mutation() RETURNS trigger
            LANGUAGE plpgsql AS $$
            BEGIN
                RAISE EXCEPTION 'reference_sequence_audits is append-only';
            END;
            $$;

            DROP TRIGGER IF EXISTS reference_sequence_audits_no_update ON reference_sequence_audits;
            CREATE TRIGGER reference_sequence_audits_no_update
            BEFORE UPDATE ON reference_sequence_audits
            FOR EACH ROW EXECUTE FUNCTION reject_reference_sequence_audit_mutation();

            DROP TRIGGER IF EXISTS reference_sequence_audits_no_delete ON reference_sequence_audits;
            CREATE TRIGGER reference_sequence_audits_no_delete
            BEFORE DELETE ON reference_sequence_audits
            FOR EACH ROW EXECUTE FUNCTION reject_reference_sequence_audit_mutation();

            DROP TRIGGER IF EXISTS reference_sequence_audits_no_truncate ON reference_sequence_audits;
            CREATE TRIGGER reference_sequence_audits_no_truncate
            BEFORE TRUNCATE ON reference_sequence_audits
            FOR EACH STATEMENT EXECUTE FUNCTION reject_reference_sequence_audit_mutation();

            CREATE OR REPLACE FUNCTION reject_audit_event_mutation() RETURNS trigger
            LANGUAGE plpgsql AS $$
            BEGIN
                RAISE EXCEPTION 'audit_events is append-only';
            END;
            $$;

            DROP TRIGGER IF EXISTS audit_events_append_only ON audit_events;
            CREATE TRIGGER audit_events_append_only
            BEFORE UPDATE OR DELETE ON audit_events
            FOR EACH ROW EXECUTE FUNCTION reject_audit_event_mutation();

            DROP TRIGGER IF EXISTS audit_events_no_truncate ON audit_events;
            CREATE TRIGGER audit_events_no_truncate
            BEFORE TRUNCATE ON audit_events
            FOR EACH STATEMENT EXECUTE FUNCTION reject_audit_event_mutation();
        """))
import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.database import Base, get_db
from app.main import app
from app import models
from app.authentication import password_hasher
from app.security_seed import seed_security_defaults


@pytest.fixture
def client():
    test_database_url = os.environ.get('TEST_DATABASE_URL')
    if test_database_url:
        if make_url(test_database_url) == make_url(settings.database_url):
            raise RuntimeError('TEST_DATABASE_URL must not point to the application database')
        database_url = test_database_url
    else:
        database_url = 'sqlite://'

    engine = create_engine(
        database_url,
        connect_args={'check_same_thread': False} if database_url.startswith('sqlite') else {},
        poolclass=StaticPool if database_url == 'sqlite://' else None,
    )

    if database_url.startswith('sqlite'):
        @event.listens_for(engine, 'connect')
        def enable_foreign_keys(dbapi_connection, _):
            cursor = dbapi_connection.cursor()
            cursor.execute('PRAGMA foreign_keys=ON')
            cursor.close()

    Base.metadata.create_all(engine)
    if engine.dialect.name == "postgresql":
        install_postgresql_triggers(engine)
    TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    with TestingSession() as session:
        seed_security_defaults(session)
        role = session.query(models.Role).filter_by(scope='system', code='system_administrator').one()
        admin = models.User(email='test-admin@example.invalid', password_hash=password_hasher.hash('Correct-Horse-42!'), is_active=True)
        session.add(admin)
        session.flush()
        session.add(models.SystemRoleAssignment(user_id=admin.id, role_id=role.id, assigned_by_id=admin.id))
        session.commit()

    def override_get_db():
        session = TestingSession()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        login = test_client.post(
            '/api/v1/auth/login',
            json={'email': 'test-admin@example.invalid', 'password': 'Correct-Horse-42!'},
        )
        assert login.status_code == 200
        test_client.headers['X-CSRF-Token'] = test_client.cookies['mindzen_csrf']
        yield test_client
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def db_session(client):
    session_generator = app.dependency_overrides[get_db]()
    session = next(session_generator)
    try:
        yield session
    finally:
        session_generator.close()
