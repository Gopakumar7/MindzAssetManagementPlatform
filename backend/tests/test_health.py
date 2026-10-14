from fastapi.testclient import TestClient

from app import database
from app.main import app

client = TestClient(app)


def test_health_endpoint() -> None:
    response = client.get('/api/v1/health')

    assert response.status_code == 200
    payload = response.json()
    assert payload['status'] == 'ok'
    assert payload['service'] == 'mindzen-alcm'


def test_health_ready_endpoint_success(monkeypatch) -> None:
    monkeypatch.setattr(database, 'check_database_health', lambda: (True, 'database connection is healthy'))

    response = client.get('/api/v1/health/ready')

    assert response.status_code == 200
    payload = response.json()
    assert payload['status'] == 'ready'
    assert payload['database']['available'] is True


def test_health_ready_endpoint_failure(monkeypatch) -> None:
    def unavailable() -> tuple[bool, str]:
        return False, 'database unavailable: connection refused'

    monkeypatch.setattr(database, 'check_database_health', unavailable)

    response = client.get('/api/v1/health/ready')

    assert response.status_code == 503
    payload = response.json()
    assert payload['detail']['status'] == 'not_ready'
    assert payload['detail']['database']['available'] is False
