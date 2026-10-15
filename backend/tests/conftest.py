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
