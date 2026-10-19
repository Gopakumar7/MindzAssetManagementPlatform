from datetime import date, timedelta
from uuid import UUID

import pytest
from sqlalchemy import select

from app.authentication import password_hasher
from app.models import (
    Asset,
    AssetAssignment,
    AssetCategory,
    AssetHistory,
    AuditEvent,
    Company,
    CompanyMembership,
    Location,
    Role,
    Site,
    User,
    VerificationCampaign,
    VerificationDiscrepancy,
    VerificationExpectedAsset,
    VerificationObservation,
    VerificationUnregisteredAsset,
)


def _login_as(client, email: str, password: str = 'Password-123!'):
    res = client.post('/api/v1/auth/login', json={'email': email, 'password': password})
    assert res.status_code == 200, res.text
    client.headers['X-CSRF-Token'] = client.cookies['mindzen_csrf']


def _setup_company_with_assets(client, db_session):
    # Create company
    company_res = client.post(
        '/api/v1/companies',
        json={'code': 'VERIFCO', 'name': 'Verification Test Company', 'number_prefix': 'VTC'},
    )
    assert company_res.status_code == 201, company_res.text
    company = company_res.json()
    company_id = UUID(company['id'])

    # Get categories
    cats = db_session.scalars(
        select(AssetCategory).where(AssetCategory.company_id == company_id).order_by(AssetCategory.code)
    ).all()
    cat_laptops = cats[0]
    cat_displays = cats[1]
    cat_servers = cats[2]

    # Create site & locations
    site_res = client.post(
        f'/api/v1/companies/{company["id"]}/sites',
        json={'code': 'HQ', 'name': 'Headquarters Site'},
    )
    assert site_res.status_code == 201
    site = site_res.json()

    loc1_res = client.post(
        f'/api/v1/companies/{company["id"]}/sites/{site["id"]}/locations',
        json={'site_id': site['id'], 'code': 'ROOM-101', 'name': 'Room 101'},
    )
    assert loc1_res.status_code == 201
    loc1 = loc1_res.json()

    loc2_res = client.post(
        f'/api/v1/companies/{company["id"]}/sites/{site["id"]}/locations',
        json={'site_id': site['id'], 'code': 'ROOM-202', 'name': 'Room 202 Server Lab'},
    )
    assert loc2_res.status_code == 201
    loc2 = loc2_res.json()

    # Create 4 test assets
    # Asset 1: Laptop in Room 101
    a1_res = client.post(
        f'/api/v1/companies/{company["id"]}/assets',
        json={
            'category_id': str(cat_laptops.id),
            'site_id': site['id'],
            'location_id': loc1['id'],
            'manufacturer': 'Dell',
            'model': 'Latitude 7420',
            'serial_number': 'SN-DELL-001',
            'status': 'in_stock',
        },
    )
    assert a1_res.status_code == 201
    a1 = a1_res.json()

    # Asset 2: Monitor in Room 101
    a2_res = client.post(
        f'/api/v1/companies/{company["id"]}/assets',
        json={
            'category_id': str(cat_displays.id),
            'site_id': site['id'],
            'location_id': loc1['id'],
            'manufacturer': 'Dell',
            'model': 'UltraSharp 27',
            'serial_number': 'SN-MON-002',
            'status': 'in_stock',
        },
    )
    assert a2_res.status_code == 201
    a2 = a2_res.json()

    # Asset 3: Server in Room 202
    a3_res = client.post(
        f'/api/v1/companies/{company["id"]}/assets',
        json={
            'category_id': str(cat_servers.id),
            'site_id': site['id'],
            'location_id': loc2['id'],
            'manufacturer': 'HPE',
            'model': 'ProLiant DL380',
            'serial_number': 'SN-SRV-003',
            'status': 'in_stock',
        },
    )
    assert a3_res.status_code == 201
    a3 = a3_res.json()

    # Asset 4: Another Laptop assigned to a user
    custodian = User(
        email='custodian@example.invalid',
        password_hash=password_hasher.hash('Password-123!'),
        is_active=True,
    )
    db_session.add(custodian)
    db_session.flush()

    role_ro = db_session.scalar(select(Role).where(Role.scope == 'company', Role.code == 'read_only_user'))
    mem = CompanyMembership(
        company_id=company_id,
        user_id=custodian.id,
        role_id=role_ro.id,
        status='active',
    )
    db_session.add(mem)
    db_session.flush()

    a4_res = client.post(
        f'/api/v1/companies/{company["id"]}/assets',
        json={
            'category_id': str(cat_laptops.id),
            'site_id': site['id'],
            'location_id': loc1['id'],
            'manufacturer': 'Apple',
            'model': 'MacBook Pro 16',
            'serial_number': 'SN-MBP-004',
            'status': 'assigned',
            'custodian_name': custodian.email,
        },
    )
    assert a4_res.status_code == 201
    a4 = a4_res.json()

    # Create assignment record for a4
    assign = AssetAssignment(
        company_id=company_id,
        asset_id=UUID(a4['id']),
        recipient_id=custodian.id,
        effective_date=date.today(),
        status='active',
        notes='Initial laptop assignment',
    )
    db_session.add(assign)
    db_session.commit()

    return {
        'company': company,
        'cat_laptops': cat_laptops,
        'cat_displays': cat_displays,
        'cat_servers': cat_servers,
        'site': site,
        'loc1': loc1,
        'loc2': loc2,
        'assets': [a1, a2, a3, a4],
        'custodian': custodian,
    }


def test_campaign_lifecycle_scope_and_snapshot(client, db_session):
    data = _setup_company_with_assets(client, db_session)
    company_id = data['company']['id']
    cat_laptops = data['cat_laptops']
    cat_displays = data['cat_displays']
    loc1 = data['loc1']

    # 1. Invalid date validation
    bad_dates = client.post(
        f'/api/v1/companies/{company_id}/verification-campaigns',
        json={
            'campaign_reference': 'CMP-2026-BAD',
            'name': 'Bad Dates Campaign',
            'start_date': '2026-11-01',
            'end_date': '2026-10-01',
        },
    )
    assert bad_dates.status_code == 422
    assert 'end date must be on or after' in bad_dates.json()['detail']

    # 2. Valid creation in Draft
    c_res = client.post(
        f'/api/v1/companies/{company_id}/verification-campaigns',
        json={
            'campaign_reference': 'CMP-2026-001',
            'name': 'Q4 IT Asset Audit',
            'description': 'Annual comprehensive hardware verification',
            'start_date': '2026-10-01',
            'end_date': '2026-10-31',
            'scope_category_ids': [str(cat_laptops.id), str(cat_displays.id)],
            'scope_location_ids': [loc1['id']],
        },
    )
    assert c_res.status_code == 201, c_res.text
    campaign = c_res.json()
    assert campaign['status'] == 'draft'
    assert campaign['total_expected'] == 0  # No snapshot in draft

    # 3. Duplicate reference rejected
    dup_res = client.post(
        f'/api/v1/companies/{company_id}/verification-campaigns',
        json={
            'campaign_reference': 'CMP-2026-001',
            'name': 'Duplicate Campaign',
            'start_date': '2026-10-01',
            'end_date': '2026-10-31',
        },
    )
    assert dup_res.status_code == 409

    # 4. Update in draft is permitted
    patch_res = client.patch(
        f'/api/v1/companies/{company_id}/verification-campaigns/{campaign["id"]}',
        json={'name': 'Q4 IT Asset Audit (Updated)'},
    )
    assert patch_res.status_code == 200
    assert patch_res.json()['name'] == 'Q4 IT Asset Audit (Updated)'

    # 5. Transition: draft -> in_progress (creates stable snapshot)
    start_res = client.post(
        f'/api/v1/companies/{company_id}/verification-campaigns/{campaign["id"]}/status',
        json={'status': 'in_progress'},
    )
    assert start_res.status_code == 200, start_res.text
    started_camp = start_res.json()
    assert started_camp['status'] == 'in_progress'
    assert started_camp['started_at'] is not None

    # Expected assets snapshot check:
    # Scope was Laptops and Displays in loc1 (Room 101).
    # a1 (laptop in loc1), a2 (display in loc1), a4 (laptop in loc1) match.
    # a3 (server in loc2) does NOT match.
    assert started_camp['total_expected'] == 3

    # 6. Scope change in in_progress is rejected
    scope_change = client.patch(
        f'/api/v1/companies/{company_id}/verification-campaigns/{campaign["id"]}',
        json={'name': 'Attempted Name Change'},
    )
    assert scope_change.status_code == 422
    assert 'cannot be changed once verification has started' in scope_change.json()['detail']

    # 7. List expected assets
    ea_res = client.get(f'/api/v1/companies/{company_id}/verification-campaigns/{campaign["id"]}/expected-assets')
    assert ea_res.status_code == 200
    expected_list = ea_res.json()
    assert len(expected_list) == 3
    asset_numbers = [item['asset_number'] for item in expected_list]
    assert data['assets'][0]['asset_number'] in asset_numbers
    assert data['assets'][1]['asset_number'] in asset_numbers
    assert data['assets'][3]['asset_number'] in asset_numbers
    assert data['assets'][2]['asset_number'] not in asset_numbers  # Server excluded

    # Verify custodian snapshot on a4
    a4_item = next(item for item in expected_list if item['asset_number'] == data['assets'][3]['asset_number'])
    assert a4_item['expected_custodian_name'] == data['custodian'].email


def test_observations_discrepancies_and_duplicate_protection(client, db_session):
    data = _setup_company_with_assets(client, db_session)
    company_id = data['company']['id']
    loc1 = data['loc1']
    loc2 = data['loc2']

    # Create and start campaign covering all categories and locations
    c_res = client.post(
        f'/api/v1/companies/{company_id}/verification-campaigns',
        json={
            'campaign_reference': 'CMP-OBS-01',
            'name': 'Comprehensive Audit',
            'start_date': '2026-10-01',
            'end_date': '2026-10-31',
        },
    )
    campaign_id = c_res.json()['id']
    client.post(f'/api/v1/companies/{company_id}/verification-campaigns/{campaign_id}/status', json={'status': 'in_progress'})

    expected_assets = client.get(f'/api/v1/companies/{company_id}/verification-campaigns/{campaign_id}/expected-assets').json()
    assert len(expected_assets) == 4

    # Map by asset number
    ea_by_num = {ea['asset_number']: ea for ea in expected_assets}
    ea_laptop = ea_by_num[data['assets'][0]['asset_number']]
    ea_display = ea_by_num[data['assets'][1]['asset_number']]
    ea_server = ea_by_num[data['assets'][2]['asset_number']]

    # 1. Successful observation without discrepancies (Laptop found in Room 101, condition good)
    obs1_res = client.post(
        f'/api/v1/companies/{company_id}/verification-campaigns/{campaign_id}/expected-assets/{ea_laptop["id"]}/observations',
        json={
            'is_found': True,
            'actual_location_id': loc1['id'],
            'observed_condition': 'good',
            'remarks': 'Verified in desk position',
        },
    )
    assert obs1_res.status_code == 201, obs1_res.text
    obs1 = obs1_res.json()
    assert obs1['is_found'] is True
    assert obs1['observed_condition'] == 'good'

    # Duplicate observation attempt for the same asset rejected
    dup_obs = client.post(
        f'/api/v1/companies/{company_id}/verification-campaigns/{campaign_id}/expected-assets/{ea_laptop["id"]}/observations',
        json={'is_found': True, 'actual_location_id': loc1['id']},
    )
    assert dup_obs.status_code == 409
    assert 'already been recorded' in dup_obs.json()['detail']

    # 2. Location mismatch observation (Display found in Room 202 instead of Room 101)
    obs2_res = client.post(
        f'/api/v1/companies/{company_id}/verification-campaigns/{campaign_id}/expected-assets/{ea_display["id"]}/observations',
        json={
            'is_found': True,
            'actual_location_id': loc2['id'],
            'observed_condition': 'good',
            'remarks': 'Moved to Server Lab without update',
        },
    )
    assert obs2_res.status_code == 201

    # Master asset record must NOT have been changed yet!
    asset_display = db_session.get(Asset, UUID(data['assets'][1]['id']))
    assert asset_display.location_id == UUID(loc1['id'])

    # 3. Missing asset observation (Server not found in Room 202)
    obs3_res = client.post(
        f'/api/v1/companies/{company_id}/verification-campaigns/{campaign_id}/expected-assets/{ea_server["id"]}/observations',
        json={
            'is_found': False,
            'remarks': 'Rack slot empty',
        },
    )
    assert obs3_res.status_code == 201

    # Check discrepancies created
    disc_res = client.get(f'/api/v1/companies/{company_id}/verification-campaigns/{campaign_id}/discrepancies')
    assert disc_res.status_code == 200
    discrepancies = disc_res.json()
    assert len(discrepancies) == 2
    types = {d['discrepancy_type'] for d in discrepancies}
    assert 'location_mismatch' in types
    assert 'missing' in types

    # Check dashboard summary
    dash_res = client.get(f'/api/v1/companies/{company_id}/verification-campaigns/{campaign_id}/dashboard')
    assert dash_res.status_code == 200
    dash = dash_res.json()
    assert dash['total_expected'] == 4
    assert dash['total_verified'] == 3
    assert dash['total_unverified'] == 1
    assert dash['total_missing'] == 1
    assert dash['discrepancies_by_type']['location_mismatch'] == 1
    assert dash['discrepancies_by_type']['missing'] == 1
    assert dash['pending_resolutions'] == 2


def test_discrepancy_resolution_and_unregistered_asset_registration(client, db_session):
    data = _setup_company_with_assets(client, db_session)
    company_id = data['company']['id']
    cat_laptops = data['cat_laptops']
    loc1 = data['loc1']
    loc2 = data['loc2']

    # Start campaign
    c_res = client.post(
        f'/api/v1/companies/{company_id}/verification-campaigns',
        json={
            'campaign_reference': 'CMP-RES-01',
            'name': 'Resolution Campaign',
            'start_date': '2026-10-01',
            'end_date': '2026-10-31',
        },
    )
    campaign_id = c_res.json()['id']
    client.post(f'/api/v1/companies/{company_id}/verification-campaigns/{campaign_id}/status', json={'status': 'in_progress'})

    expected_assets = client.get(f'/api/v1/companies/{company_id}/verification-campaigns/{campaign_id}/expected-assets').json()
    ea_display = next(ea for ea in expected_assets if ea['asset_number'] == data['assets'][1]['asset_number'])

    # Record location mismatch
    client.post(
        f'/api/v1/companies/{company_id}/verification-campaigns/{campaign_id}/expected-assets/{ea_display["id"]}/observations',
        json={
            'is_found': True,
            'actual_location_id': loc2['id'],
            'observed_condition': 'good',
        },
    )

    # Record unregistered asset found in field
    unreg_res = client.post(
        f'/api/v1/companies/{company_id}/verification-campaigns/{campaign_id}/unregistered-assets',
        json={
            'description': 'Found ThinkPad X1 Carbon',
            'category_id': str(cat_laptops.id),
            'serial_number': 'SN-UNREG-999',
            'location_id': loc1['id'],
            'observed_condition': 'fair',
            'remarks': 'Found in storage cupboard without tag',
        },
    )
    assert unreg_res.status_code == 201, unreg_res.text
    unreg = unreg_res.json()
    assert unreg['status'] == 'pending'

    # Discrepancies list should have 2 (location_mismatch + unregistered_asset)
    discs = client.get(f'/api/v1/companies/{company_id}/verification-campaigns/{campaign_id}/discrepancies').json()
    assert len(discs) == 2
    disc_loc = next(d for d in discs if d['discrepancy_type'] == 'location_mismatch')

    # Resolve location mismatch with 'update_master'
    res_loc = client.post(
        f'/api/v1/companies/{company_id}/verification-campaigns/{campaign_id}/discrepancies/{disc_loc["id"]}/resolve',
        json={
            'resolution_action': 'update_master',
            'resolution_notes': 'Confirmed display was relocated to Room 202',
        },
    )
    assert res_loc.status_code == 200
    assert res_loc.json()['status'] == 'resolved'

    # Master asset must now be updated!
    db_session.expire_all()
    display_asset = db_session.get(Asset, UUID(data['assets'][1]['id']))
    assert str(display_asset.location_id) == str(loc2['id'])

    # AssetHistory must contain the update event
    hist = db_session.scalars(
        select(AssetHistory).where(
            AssetHistory.asset_id == display_asset.id,
            AssetHistory.field_name == 'location_id',
        )
    ).all()
    assert len(hist) > 0
    assert hist[-1].new_value == str(loc2['id'])

    # Now register the unregistered asset into the asset registry!
    reg_res = client.post(
        f'/api/v1/companies/{company_id}/verification-campaigns/{campaign_id}/unregistered-assets/{unreg["id"]}/register',
        json={
            'resolution_notes': 'Assigned new barcode and brought into active register',
        },
    )
    assert reg_res.status_code == 200, reg_res.text
    registered = reg_res.json()
    assert registered['status'] == 'registered'
    assert registered['registered_asset_id'] is not None
    assert registered['registered_asset_number'] is not None

    # Verify newly created asset in database
    new_asset_id = UUID(registered['registered_asset_id'])
    new_asset = db_session.get(Asset, new_asset_id)
    assert new_asset is not None
    assert new_asset.serial_number == 'SN-UNREG-999'
    assert new_asset.status == 'in_stock'
    assert 'Registered from verification campaign' in new_asset.notes

    # Retrying registration must be rejected with 409
    dup_reg = client.post(
        f'/api/v1/companies/{company_id}/verification-campaigns/{campaign_id}/unregistered-assets/{unreg["id"]}/register',
        json={'resolution_notes': 'Second attempt'},
    )
    assert dup_reg.status_code == 409


def test_completion_and_reports_csv_export(client, db_session):
    data = _setup_company_with_assets(client, db_session)
    company_id = data['company']['id']
    loc1 = data['loc1']

    # Create and start campaign
    c_res = client.post(
        f'/api/v1/companies/{company_id}/verification-campaigns',
        json={
            'campaign_reference': 'CMP-REP-01',
            'name': 'Reporting Verification',
            'start_date': '2026-10-01',
            'end_date': '2026-10-31',
        },
    )
    campaign_id = c_res.json()['id']
    client.post(f'/api/v1/companies/{company_id}/verification-campaigns/{campaign_id}/status', json={'status': 'in_progress'})

    # Advance to under_review
    rev_res = client.post(
        f'/api/v1/companies/{company_id}/verification-campaigns/{campaign_id}/status',
        json={'status': 'under_review'},
    )
    assert rev_res.status_code == 200
    assert rev_res.json()['status'] == 'under_review'

    # Advance to completed
    comp_res = client.post(
        f'/api/v1/companies/{company_id}/verification-campaigns/{campaign_id}/status',
        json={'status': 'completed'},
    )
    assert comp_res.status_code == 200
    completed = comp_res.json()
    assert completed['status'] == 'completed'
    assert completed['completed_at'] is not None

    # Test Reports Endpoint (JSON)
    rep_res = client.get(f'/api/v1/companies/{company_id}/reports/verification-campaigns')
    assert rep_res.status_code == 200
    reports = rep_res.json()
    assert len(reports) >= 1
    assert reports[0]['campaign_reference'] == 'CMP-REP-01'

    # Test Reports Endpoint (CSV export)
    csv_res = client.get(f'/api/v1/companies/{company_id}/reports/verification-campaigns?format=csv')
    assert csv_res.status_code == 200
    assert 'text/csv' in csv_res.headers['content-type']
    assert 'CMP-REP-01' in csv_res.text
    assert 'Reporting Verification' in csv_res.text

    # Test Discrepancies Report Endpoint (CSV export)
    disc_csv_res = client.get(f'/api/v1/companies/{company_id}/reports/verification-discrepancies?format=csv')
    assert disc_csv_res.status_code == 200
    assert 'text/csv' in disc_csv_res.headers['content-type']


def test_company_isolation_and_rbac(client, db_session):
    data = _setup_company_with_assets(client, db_session)
    company_id = data['company']['id']

    # Create campaign in company 1
    c_res = client.post(
        f'/api/v1/companies/{company_id}/verification-campaigns',
        json={
            'campaign_reference': 'CMP-ISO-01',
            'name': 'Isolation Test',
            'start_date': '2026-10-01',
            'end_date': '2026-10-31',
        },
    )
    campaign_id = c_res.json()['id']

    # Create Company 2
    c2_res = client.post(
        '/api/v1/companies',
        json={'code': 'COMP2', 'name': 'Second Company', 'number_prefix': 'CP2'},
    )
    c2_id = c2_res.json()['id']

    # Cross-company access rejected with 404
    cross_get = client.get(f'/api/v1/companies/{c2_id}/verification-campaigns/{campaign_id}')
    assert cross_get.status_code == 404

    # RBAC: Create read-only user
    ro_user = User(
        email='ro-verifier@example.invalid',
        password_hash=password_hasher.hash('Password-123!'),
        is_active=True,
    )
    db_session.add(ro_user)
    db_session.flush()

    ro_role = db_session.scalar(select(Role).where(Role.scope == 'company', Role.code == 'read_only_user'))
    mem = CompanyMembership(
        company_id=UUID(company_id),
        user_id=ro_user.id,
        role_id=ro_role.id,
        status='active',
    )
    db_session.add(mem)
    db_session.commit()

    # Login as read-only user
    _login_as(client, 'ro-verifier@example.invalid', 'Password-123!')

    # Read-only user CAN read campaigns
    ro_get = client.get(f'/api/v1/companies/{company_id}/verification-campaigns')
    assert ro_get.status_code == 200

    # Read-only user CANNOT create campaigns (403 Forbidden)
    ro_post = client.post(
        f'/api/v1/companies/{company_id}/verification-campaigns',
        json={
            'campaign_reference': 'CMP-FORBIDDEN',
            'name': 'Forbidden Campaign',
            'start_date': '2026-10-01',
            'end_date': '2026-10-31',
        },
    )
    assert ro_post.status_code == 403
