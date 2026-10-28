from uuid import UUID, uuid4
import pytest
from sqlalchemy import select

from app import models
from app.authentication import password_hasher


def _create_company(client, code: str, prefix: str = 'AST') -> dict:
    res = client.post('/api/v1/companies', json={'code': code, 'name': f'{code} Corp', 'number_prefix': prefix})
    assert res.status_code == 201, res.text
    return res.json()


def _get_category(client, company_id: str) -> dict:
    categories = client.get(f'/api/v1/companies/{company_id}/categories').json()
    assert len(categories) > 0
    return categories[0]


def _create_asset(client, company_id: str, category_id: str, serial_number: str | None = None, model: str = 'Model-X') -> dict:
    payload = {'category_id': category_id, 'model': model}
    if serial_number is not None:
        payload['serial_number'] = serial_number
    res = client.post(f'/api/v1/companies/{company_id}/assets', json=payload)
    assert res.status_code == 201, res.text
    return res.json()


def _login(client, email: str, password: str) -> None:
    res = client.post('/api/v1/auth/login', json={'email': email, 'password': password})
    assert res.status_code == 200, res.text
    client.headers['X-CSRF-Token'] = client.cookies['mindzen_csrf']


def test_lookup_exact_asset_number_match(client):
    company = _create_company(client, 'LKP-EXACT', prefix='LKP')
    cat = _get_category(client, company['id'])
    asset = _create_asset(client, company['id'], cat['id'], serial_number='SN-EXACT-001', model='MacBook Pro')

    res = client.get(f"/api/v1/companies/{company['id']}/assets/lookup", params={'code': asset['asset_number']})
    assert res.status_code == 200
    data = res.json()
    assert data['id'] == asset['id']
    assert data['asset_number'] == asset['asset_number']
    assert data['serial_number'] == 'SN-EXACT-001'
    assert data['model'] == 'MacBook Pro'


def test_lookup_exact_serial_number_fallback(client):
    company = _create_company(client, 'LKP-SERIAL', prefix='SNF')
    cat = _get_category(client, company['id'])
    asset = _create_asset(client, company['id'], cat['id'], serial_number='UNIQUE-SN-999', model='Dell XPS')

    # Look up by serial number instead of asset number
    res = client.get(f"/api/v1/companies/{company['id']}/assets/lookup", params={'code': 'UNIQUE-SN-999'})
    assert res.status_code == 200
    data = res.json()
    assert data['id'] == asset['id']
    assert data['asset_number'] == asset['asset_number']
    assert data['serial_number'] == 'UNIQUE-SN-999'


def test_lookup_asset_number_precedence_over_serial(client, db_session):
    company = _create_company(client, 'LKP-PREC', prefix='PRC')
    cat = _get_category(client, company['id'])

    # Asset 1 has generated asset_number e.g. PRC-000001
    asset1 = _create_asset(client, company['id'], cat['id'], serial_number='SN-A', model='Asset One')

    # Asset 2 has serial_number equal to Asset 1's asset_number
    asset2 = _create_asset(client, company['id'], cat['id'], serial_number=asset1['asset_number'], model='Asset Two')

    # Looking up that code MUST return Asset 1 (matched on asset_number), NOT Asset 2
    res = client.get(f"/api/v1/companies/{company['id']}/assets/lookup", params={'code': asset1['asset_number']})
    assert res.status_code == 200
    data = res.json()
    assert data['id'] == asset1['id']
    assert data['asset_number'] == asset1['asset_number']
    assert data['id'] != asset2['id']


def test_lookup_unknown_code_returns_404(client):
    company = _create_company(client, 'LKP-404', prefix='NOF')
    cat = _get_category(client, company['id'])
    _create_asset(client, company['id'], cat['id'], serial_number='SN-EXIST')

    res = client.get(f"/api/v1/companies/{company['id']}/assets/lookup", params={'code': 'NON-EXISTENT-CODE'})
    assert res.status_code == 404
    assert res.json()['detail'] == 'Asset not found in this company'


def test_lookup_empty_and_malformed_inputs(client):
    company = _create_company(client, 'LKP-VAL', prefix='VAL')

    # Missing code param
    res_missing = client.get(f"/api/v1/companies/{company['id']}/assets/lookup")
    assert res_missing.status_code == 422

    # Empty string code param
    res_empty = client.get(f"/api/v1/companies/{company['id']}/assets/lookup", params={'code': ''})
    assert res_empty.status_code == 422

    # Whitespace-only code param
    res_blank = client.get(f"/api/v1/companies/{company['id']}/assets/lookup", params={'code': '   '})
    assert res_blank.status_code == 422
    assert 'empty or blank' in res_blank.json()['detail']

    # Control characters / null byte
    res_ctrl = client.get(f"/api/v1/companies/{company['id']}/assets/lookup", params={'code': 'CODE\x00NULL'})
    assert res_ctrl.status_code == 422
    assert 'control characters' in res_ctrl.json()['detail']

    # Excessively long code (> 120 chars)
    res_long = client.get(f"/api/v1/companies/{company['id']}/assets/lookup", params={'code': 'X' * 121})
    assert res_long.status_code == 422


def test_lookup_denied_without_asset_read_permission(client, db_session):
    company = _create_company(client, 'LKP-PERM', prefix='PRM')
    cat = _get_category(client, company['id'])
    asset = _create_asset(client, company['id'], cat['id'], serial_number='SN-PERM-1')

    # Create a custom company role with ONLY 'company.read' permission (no 'asset.read')
    role_no_asset = models.Role(
        id=uuid4(),
        scope='company',
        code='limited_no_asset_read',
        name='Limited No Asset Read',
    )
    db_session.add(role_no_asset)
    db_session.flush()

    company_read_perm = db_session.scalar(
        select(models.Permission).where(models.Permission.code == 'company.read')
    )
    assert company_read_perm is not None
    db_session.execute(
        models.role_permissions.insert().values(
            role_id=role_no_asset.id,
            permission_id=company_read_perm.id,
        )
    )

    # Create user with this limited role
    limited_user = models.User(
        id=uuid4(),
        email='limited.viewer@example.invalid',
        password_hash=password_hasher.hash('Limited-Viewer-Pass-42!'),
        is_active=True,
    )
    db_session.add(limited_user)
    db_session.flush()

    admin = db_session.scalar(select(models.User).where(models.User.email == 'test-admin@example.invalid'))
    db_session.add(
        models.CompanyMembership(
            id=uuid4(),
            company_id=UUID(company['id']),
            user_id=limited_user.id,
            role_id=role_no_asset.id,
            status='active',
            assigned_by_id=admin.id,
        )
    )
    db_session.commit()

    # Login as limited user
    _login(client, 'limited.viewer@example.invalid', 'Limited-Viewer-Pass-42!')

    # Attempt to look up the asset -> MUST be 403 Forbidden
    res = client.get(f"/api/v1/companies/{company['id']}/assets/lookup", params={'code': asset['asset_number']})
    assert res.status_code == 403


def test_lookup_cross_company_isolation(client):
    company_a = _create_company(client, 'LKP-ISOL-A', prefix='COA')
    company_b = _create_company(client, 'LKP-ISOL-B', prefix='COB')

    cat_a = _get_category(client, company_a['id'])
    cat_b = _get_category(client, company_b['id'])

    asset_a = _create_asset(client, company_a['id'], cat_a['id'], serial_number='SN-SHARED-COA')
    asset_b = _create_asset(client, company_b['id'], cat_b['id'], serial_number='SN-SHARED-COB')

    # In Company A: can look up Asset A
    res_a = client.get(f"/api/v1/companies/{company_a['id']}/assets/lookup", params={'code': asset_a['asset_number']})
    assert res_a.status_code == 200
    assert res_a.json()['id'] == asset_a['id']

    # In Company A: cannot look up Asset B by asset_number or serial_number (returns 404, never leaks existence)
    res_b_by_num = client.get(f"/api/v1/companies/{company_a['id']}/assets/lookup", params={'code': asset_b['asset_number']})
    assert res_b_by_num.status_code == 404
    assert res_b_by_num.json()['detail'] == 'Asset not found in this company'

    res_b_by_sn = client.get(f"/api/v1/companies/{company_a['id']}/assets/lookup", params={'code': asset_b['serial_number']})
    assert res_b_by_sn.status_code == 404
    assert res_b_by_sn.json()['detail'] == 'Asset not found in this company'


def test_lookup_disposed_and_inactive_assets(client, db_session):
    company = _create_company(client, 'LKP-DISP', prefix='DSP')
    cat = _get_category(client, company['id'])
    asset = _create_asset(client, company['id'], cat['id'], serial_number='SN-DISP-01', model='Old ThinkPad')

    # Manually set status to 'disposed' in DB to test that lookup preserves reading inactive/disposed assets
    db_asset = db_session.get(models.Asset, UUID(asset['id']))
    db_asset.status = 'disposed'
    db_session.commit()

    res = client.get(f"/api/v1/companies/{company['id']}/assets/lookup", params={'code': asset['asset_number']})
    assert res.status_code == 200
    data = res.json()
    assert data['id'] == asset['id']
    assert data['status'] == 'disposed'

    # Fallback to serial for disposed asset also works
    res_sn = client.get(f"/api/v1/companies/{company['id']}/assets/lookup", params={'code': 'SN-DISP-01'})
    assert res_sn.status_code == 200
    assert res_sn.json()['id'] == asset['id']
    assert res_sn.json()['status'] == 'disposed'


def test_lookup_requires_authentication(client):
    company = _create_company(client, 'LKP-AUTH', prefix='ATH')

    # Logout to clear session cookies
    client.post('/api/v1/auth/logout')

    # Attempt lookup without authentication
    res = client.get(f"/api/v1/companies/{company['id']}/assets/lookup", params={'code': 'ATH-000001'})
    assert res.status_code == 401


def test_existing_asset_registry_and_import_unaffected(client):
    company = _create_company(client, 'LKP-REGR', prefix='RGR')
    cat = _get_category(client, company['id'])
    asset = _create_asset(client, company['id'], cat['id'], serial_number='SN-REGRESS-1')

    # 1. Existing paginated list works
    list_res = client.get(f"/api/v1/companies/{company['id']}/assets")
    assert list_res.status_code == 200
    assert list_res.json()['total'] == 1

    # 2. Existing read by UUID works
    uuid_res = client.get(f"/api/v1/companies/{company['id']}/assets/{asset['id']}")
    assert uuid_res.status_code == 200
    assert uuid_res.json()['id'] == asset['id']

    # 3. Existing import template endpoint works
    tmpl_res = client.get(f"/api/v1/companies/{company['id']}/assets/import/template?format=csv")
    assert tmpl_res.status_code == 200
    assert 'text/csv' in tmpl_res.headers['content-type']


def test_lookup_duplicate_serial_number_returns_safely(client):
    company = _create_company(client, 'LKP-DUPSN', prefix='DSN')
    cat = _get_category(client, company['id'])

    # Create two assets with identical serial numbers
    asset1 = _create_asset(client, company['id'], cat['id'], serial_number='SHARED-SN-001', model='Laptop Alpha')
    asset2 = _create_asset(client, company['id'], cat['id'], serial_number='SHARED-SN-001', model='Laptop Beta')

    res = client.get(f"/api/v1/companies/{company['id']}/assets/lookup", params={'code': 'SHARED-SN-001'})
    assert res.status_code == 200
    # Returns one of the matching assets cleanly without 500 error
    assert res.json()['id'] in [asset1['id'], asset2['id']]
    assert res.json()['serial_number'] == 'SHARED-SN-001'
