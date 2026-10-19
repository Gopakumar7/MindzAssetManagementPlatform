import concurrent.futures
from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.models import (
    Asset,
    AssetAssignment,
    AssetCategory,
    AssetDepreciationEntry,
    AssetDisposal,
    AssetFinancial,
    AuditEvent,
    Company,
    CompanyMembership,
    Role,
    User,
)


def _setup_company_and_category(client, company_code='FIN-CO-1'):
    comp_res = client.post('/api/v1/companies', json={'code': company_code, 'name': f'Finance Co {company_code}'})
    assert comp_res.status_code == 201
    comp_id = comp_res.json()['id']

    cat_res = client.post(f'/api/v1/companies/{comp_id}/categories', json={'code': 'FIN-LAP', 'name': 'Laptops'})
    assert cat_res.status_code == 201
    cat_id = cat_res.json()['id']
    return comp_id, cat_id


def test_financial_profile_configuration_and_validation(client):
    """Test 1: Financial profile creation, validation boundaries, and procurement derivation."""
    company_id, category_id = _setup_company_and_category(client, 'FIN-CFG-1')

    # Create asset with acquisition cost and date (simulating procurement receipt)
    asset_res = client.post(
        f'/api/v1/companies/{company_id}/assets',
        json={
            'category_id': category_id,
            'model': 'MacBook Pro 16',
            'acquisition_date': '2026-01-15',
            'acquisition_cost': 2400.00,
        },
    )
    assert asset_res.status_code == 201
    asset_id = asset_res.json()['id']

    # Auto-derive default financial profile
    get_res = client.get(f'/api/v1/companies/{company_id}/assets/{asset_id}/financial')
    assert get_res.status_code == 200
    fin_data = get_res.json()
    assert Decimal(str(fin_data['capitalised_cost'])) == Decimal('2400.00')
    assert fin_data['depreciation_start_date'] == '2026-01-15'
    assert fin_data['financial_status'] == 'active'
    assert Decimal(str(fin_data['current_book_value'])) == Decimal('2400.00')
    assert Decimal(str(fin_data['accumulated_depreciation'])) == Decimal('0.00')

    # Validation: residual value cannot exceed capitalised cost
    bad_res = client.put(
        f'/api/v1/companies/{company_id}/assets/{asset_id}/financial',
        json={
            'capitalised_cost': 2400.00,
            'useful_life_months': 36,
            'residual_value': 3000.00,  # Invalid! > 2400
            'depreciation_start_date': '2026-01-01',
        },
    )
    assert bad_res.status_code == 422

    # Validation: useful life must be > 0
    bad_life = client.put(
        f'/api/v1/companies/{company_id}/assets/{asset_id}/financial',
        json={
            'capitalised_cost': 2400.00,
            'useful_life_months': 0,
            'residual_value': 200.00,
            'depreciation_start_date': '2026-01-01',
        },
    )
    assert bad_life.status_code == 422

    # Configure valid profile
    cfg_res = client.put(
        f'/api/v1/companies/{company_id}/assets/{asset_id}/financial',
        json={
            'capitalised_cost': 2400.00,
            'useful_life_months': 24,
            'residual_value': 240.00,
            'depreciation_start_date': '2026-01-01',
        },
    )
    assert cfg_res.status_code == 200
    configured = cfg_res.json()
    assert configured['useful_life_months'] == 24
    assert Decimal(str(configured['residual_value'])) == Decimal('240.00')


def test_straight_line_depreciation_schedule_and_rounding(client):
    """Test 2: Schedule generation, rounding residuals, and final period absorption."""
    company_id, category_id = _setup_company_and_category(client, 'FIN-SCHED-1')

    # Asset: Cost 1000.00, Residual 0.00, Useful life 3 months
    # 1000 / 3 = 333.3333... -> 333.33 month 1, 333.33 month 2, 333.34 month 3 (absorbs residual!)
    asset_res = client.post(
        f'/api/v1/companies/{company_id}/assets',
        json={'category_id': category_id, 'model': 'Test Server', 'acquisition_date': '2026-01-01', 'acquisition_cost': 1000.00},
    )
    asset_id = asset_res.json()['id']

    client.put(
        f'/api/v1/companies/{company_id}/assets/{asset_id}/financial',
        json={
            'capitalised_cost': 1000.00,
            'useful_life_months': 3,
            'residual_value': 0.00,
            'depreciation_start_date': '2026-01-01',
        },
    )

    sched_res = client.get(f'/api/v1/companies/{company_id}/assets/{asset_id}/depreciation-schedule')
    assert sched_res.status_code == 200
    schedule = sched_res.json()
    assert len(schedule) == 3

    assert schedule[0]['period'] == '2026-01'
    assert Decimal(str(schedule[0]['depreciation_amount'])) == Decimal('333.33')
    assert Decimal(str(schedule[0]['book_value'])) == Decimal('666.67')

    assert schedule[1]['period'] == '2026-02'
    assert Decimal(str(schedule[1]['depreciation_amount'])) == Decimal('333.33')
    assert Decimal(str(schedule[1]['book_value'])) == Decimal('333.34')

    assert schedule[2]['period'] == '2026-03'
    # Final month absorbs residual!
    assert Decimal(str(schedule[2]['depreciation_amount'])) == Decimal('333.34')
    assert Decimal(str(schedule[2]['book_value'])) == Decimal('0.00')
    assert Decimal(str(schedule[2]['accumulated_depreciation'])) == Decimal('1000.00')


def test_posting_depreciation_boundaries_and_duplicate_protection(client):
    """Test 3: Single posting, boundary enforcement, duplicate protection (409), and full depreciation."""
    company_id, category_id = _setup_company_and_category(client, 'FIN-POST-1')

    # Asset: Cost 500.00, Residual 100.00, Useful life 2 months
    # Depreciable basis = 400.00 (200.00 / month)
    asset_res = client.post(
        f'/api/v1/companies/{company_id}/assets',
        json={'category_id': category_id, 'model': 'Monitor 4K', 'acquisition_date': '2026-02-10', 'acquisition_cost': 500.00},
    )
    asset_id = asset_res.json()['id']

    client.put(
        f'/api/v1/companies/{company_id}/assets/{asset_id}/financial',
        json={
            'capitalised_cost': 500.00,
            'useful_life_months': 2,
            'residual_value': 100.00,
            'depreciation_start_date': '2026-02-01',
        },
    )

    # Reject period prior to start date
    early_res = client.post(
        f'/api/v1/companies/{company_id}/assets/{asset_id}/depreciation-entries',
        json={'period': '2026-01'},
    )
    assert early_res.status_code == 422

    # Post period 1 (2026-02)
    post1_res = client.post(
        f'/api/v1/companies/{company_id}/assets/{asset_id}/depreciation-entries',
        json={'period': '2026-02', 'notes': 'February depreciation'},
    )
    assert post1_res.status_code == 201
    entry1 = post1_res.json()
    assert Decimal(str(entry1['depreciation_amount'])) == Decimal('200.00')
    assert Decimal(str(entry1['accumulated_depreciation_after'])) == Decimal('200.00')
    assert Decimal(str(entry1['book_value_after'])) == Decimal('300.00')

    # Duplicate posting for 2026-02 rejected (HTTP 409)
    dup_res = client.post(
        f'/api/v1/companies/{company_id}/assets/{asset_id}/depreciation-entries',
        json={'period': '2026-02'},
    )
    assert dup_res.status_code == 409

    # Historical integrity guard: cannot directly change capitalised_cost or useful_life once posted!
    tamper_res = client.put(
        f'/api/v1/companies/{company_id}/assets/{asset_id}/financial',
        json={
            'capitalised_cost': 800.00,
            'useful_life_months': 12,
            'residual_value': 100.00,
            'depreciation_start_date': '2026-02-01',
        },
    )
    assert tamper_res.status_code == 409

    # Post period 2 (2026-03) -> fully depreciates asset
    post2_res = client.post(
        f'/api/v1/companies/{company_id}/assets/{asset_id}/depreciation-entries',
        json={'period': '2026-03'},
    )
    assert post2_res.status_code == 201
    entry2 = post2_res.json()
    assert Decimal(str(entry2['depreciation_amount'])) == Decimal('200.00')
    assert Decimal(str(entry2['book_value_after'])) == Decimal('100.00')  # Exactly residual value!

    # Check financial profile status updated to 'fully_depreciated'
    fin_res = client.get(f'/api/v1/companies/{company_id}/assets/{asset_id}/financial')
    assert fin_res.json()['financial_status'] == 'fully_depreciated'

    # Cannot depreciate beyond useful life or once fully depreciated
    post3_res = client.post(
        f'/api/v1/companies/{company_id}/assets/{asset_id}/depreciation-entries',
        json={'period': '2026-04'},
    )
    assert post3_res.status_code == 422


def test_prospective_adjustment_workflow(client):
    """Test 4: Authorised prospective adjustment after posting without rewriting history."""
    company_id, category_id = _setup_company_and_category(client, 'FIN-ADJ-1')

    asset_res = client.post(
        f'/api/v1/companies/{company_id}/assets',
        json={'category_id': category_id, 'model': 'Heavy Switch', 'acquisition_date': '2026-01-01', 'acquisition_cost': 1200.00},
    )
    asset_id = asset_res.json()['id']

    client.put(
        f'/api/v1/companies/{company_id}/assets/{asset_id}/financial',
        json={
            'capitalised_cost': 1200.00,
            'useful_life_months': 12,
            'residual_value': 0.00,
            'depreciation_start_date': '2026-01-01',
        },
    )

    # Post 1 month (100.00) -> Book value becomes 1100.00
    p1 = client.post(
        f'/api/v1/companies/{company_id}/assets/{asset_id}/depreciation-entries',
        json={'period': '2026-01'},
    )
    assert p1.status_code == 201

    # Adjust residual value to 200.00 and extend useful life to 24 months
    adj_res = client.post(
        f'/api/v1/companies/{company_id}/assets/{asset_id}/financial/adjust',
        json={'useful_life_months': 24, 'residual_value': 200.00, 'notes': 'Life extended based on engineer inspection'},
    )
    assert adj_res.status_code == 200
    adjusted = adj_res.json()
    assert adjusted['useful_life_months'] == 24
    assert Decimal(str(adjusted['residual_value'])) == Decimal('200.00')
    # Historical entry 2026-01 remains intact
    entries_res = client.get(f'/api/v1/companies/{company_id}/assets/{asset_id}/depreciation-entries')
    entries = entries_res.json()
    assert len(entries) == 1
    assert Decimal(str(entries[0]['depreciation_amount'])) == Decimal('100.00')


def test_disposal_workflow_gain_loss_and_cutoff(client, db_session):
    """Test 5: Disposal cutoff, gain/loss calculation, active assignment guard, and status updates."""
    company_id, category_id = _setup_company_and_category(client, 'FIN-DISP-1')

    asset_res = client.post(
        f'/api/v1/companies/{company_id}/assets',
        json={'category_id': category_id, 'model': 'Fleet Truck', 'acquisition_date': '2026-01-01', 'acquisition_cost': 10000.00},
    )
    asset_id = asset_res.json()['id']

    client.put(
        f'/api/v1/companies/{company_id}/assets/{asset_id}/financial',
        json={
            'capitalised_cost': 10000.00,
            'useful_life_months': 10,
            'residual_value': 1000.00,
            'depreciation_start_date': '2026-01-01',
        },
    )

    # Post period 2026-01 (monthly rate: 900.00 -> NBV: 9100.00)
    p1 = client.post(
        f'/api/v1/companies/{company_id}/assets/{asset_id}/depreciation-entries',
        json={'period': '2026-01'},
    )
    assert p1.status_code == 201

    # Active assignment guard test: assign asset, then attempt disposal
    user = db_session.scalar(select(User).where(User.email == 'test-admin@example.invalid'))
    role = db_session.scalar(select(Role).where(Role.scope == 'company', Role.code == 'company_administrator'))
    membership = CompanyMembership(company_id=company_id, user_id=user.id, role_id=role.id, status='active')
    db_session.add(membership)
    db_session.commit()

    dept_res = client.post(f'/api/v1/companies/{company_id}/departments', json={'code': 'LOG', 'name': 'Logistics'})
    dept_id = dept_res.json()['id']
    assign_res = client.post(
        f'/api/v1/companies/{company_id}/assets/{asset_id}/assignments',
        json={'recipient_id': str(user.id), 'responsible_department_id': dept_id, 'effective_date': '2026-01-10'},
    )
    assert assign_res.status_code == 201

    # Disposal blocked while asset has active assignment (HTTP 409)
    blocked_disp = client.post(
        f'/api/v1/companies/{company_id}/assets/{asset_id}/dispose',
        json={
            'disposal_date': '2026-02-15',
            'disposal_reason': 'sale',
            'disposal_method': 'direct_sale',
            'sale_proceeds': 9500.00,
        },
    )
    assert blocked_disp.status_code == 409

    # Return asset
    assignment_id = assign_res.json()['id']
    ret_res = client.post(
        f'/api/v1/companies/{company_id}/assets/{asset_id}/assignments/{assignment_id}/return',
        json={'return_date': '2026-02-14', 'next_asset_status': 'in_stock'},
    )
    assert ret_res.status_code == 200

    # Cutoff test: If future period (2026-03) was posted, disposal in 2026-02 must be rejected!
    # Let's post 2026-02
    p2 = client.post(
        f'/api/v1/companies/{company_id}/assets/{asset_id}/depreciation-entries',
        json={'period': '2026-02'},
    )
    assert p2.status_code == 201  # NBV is now 8200.00
    # And post 2026-03
    p3 = client.post(
        f'/api/v1/companies/{company_id}/assets/{asset_id}/depreciation-entries',
        json={'period': '2026-03'},
    )
    assert p3.status_code == 201  # NBV is now 7300.00

    # Attempt to dispose on 2026-02-15 when 2026-03 is already posted -> HTTP 422!
    bad_cutoff = client.post(
        f'/api/v1/companies/{company_id}/assets/{asset_id}/dispose',
        json={
            'disposal_date': '2026-02-15',
            'disposal_reason': 'sale',
            'disposal_method': 'direct_sale',
            'sale_proceeds': 8000.00,
        },
    )
    assert bad_cutoff.status_code == 422

    # Dispose on 2026-03-20 (reconciles NBV at disposal: 7300.00, sale proceeds: 8000.00 -> Gain: 700.00)
    disp_res = client.post(
        f'/api/v1/companies/{company_id}/assets/{asset_id}/dispose',
        json={
            'disposal_date': '2026-03-20',
            'disposal_reason': 'sale',
            'disposal_method': 'direct_sale',
            'sale_proceeds': 8000.00,
            'notes': 'Sold to third party vendor',
        },
    )
    assert disp_res.status_code == 201
    disposal = disp_res.json()
    assert Decimal(str(disposal['net_book_value_at_disposal'])) == Decimal('7300.00')
    assert Decimal(str(disposal['sale_proceeds'])) == Decimal('8000.00')
    assert Decimal(str(disposal['gain_loss'])) == Decimal('700.00')

    # Check asset and financial status updated to 'disposed'
    asset_check = client.get(f'/api/v1/companies/{company_id}/assets/{asset_id}').json()
    assert asset_check['status'] == 'disposed'
    fin_check = client.get(f'/api/v1/companies/{company_id}/assets/{asset_id}/financial').json()
    assert fin_check['financial_status'] == 'disposed'

    # Cannot post depreciation after disposal date
    post_after = client.post(
        f'/api/v1/companies/{company_id}/assets/{asset_id}/depreciation-entries',
        json={'period': '2026-04'},
    )
    assert post_after.status_code == 422


def test_batch_depreciation_posting(client):
    """Test 6: Batch depreciation posting across multiple assets with atomicity and summary."""
    company_id, category_id = _setup_company_and_category(client, 'FIN-BATCH-1')

    # Create 3 assets
    asset_ids = []
    for i in range(3):
        res = client.post(
            f'/api/v1/companies/{company_id}/assets',
            json={'category_id': category_id, 'model': f'Batch Laptop {i}', 'acquisition_date': '2026-01-01', 'acquisition_cost': 1200.00},
        )
        aid = res.json()['id']
        asset_ids.append(aid)
        client.put(
            f'/api/v1/companies/{company_id}/assets/{aid}/financial',
            json={
                'capitalised_cost': 1200.00,
                'useful_life_months': 12,
                'residual_value': 0.00,
                'depreciation_start_date': '2026-01-01',
            },
        )

    # Post period 2026-01 manually on asset 0
    client.post(
        f'/api/v1/companies/{company_id}/assets/{asset_ids[0]}/depreciation-entries',
        json={'period': '2026-01'},
    )

    # Batch post 2026-01 for company: should post 2 assets, skip 1 asset (already posted)
    batch_res = client.post(
        f'/api/v1/companies/{company_id}/depreciation-entries/batch',
        json={'period': '2026-01', 'notes': 'January batch run'},
    )
    assert batch_res.status_code == 200
    batch_data = batch_res.json()
    assert batch_data['processed_count'] == 3
    assert batch_data['posted_count'] == 2
    assert batch_data['skipped_count'] == 1
    assert Decimal(str(batch_data['total_depreciation_posted'])) == Decimal('200.00')


def test_financial_reports_and_csv_export(client):
    """Test 7: Asset depreciation report and disposal report with CSV exports and reconciliation."""
    company_id, category_id = _setup_company_and_category(client, 'FIN-REP-1')

    # Create active asset
    a1_res = client.post(
        f'/api/v1/companies/{company_id}/assets',
        json={'category_id': category_id, 'model': 'Active Server', 'acquisition_date': '2026-01-01', 'acquisition_cost': 3000.00},
    )
    a1_id = a1_res.json()['id']
    client.put(
        f'/api/v1/companies/{company_id}/assets/{a1_id}/financial',
        json={'capitalised_cost': 3000.00, 'useful_life_months': 30, 'residual_value': 300.00, 'depreciation_start_date': '2026-01-01'},
    )
    client.post(f'/api/v1/companies/{company_id}/assets/{a1_id}/depreciation-entries', json={'period': '2026-01'})

    # Create disposed asset
    a2_res = client.post(
        f'/api/v1/companies/{company_id}/assets',
        json={'category_id': category_id, 'model': 'Old Printer', 'acquisition_date': '2025-01-01', 'acquisition_cost': 500.00},
    )
    a2_id = a2_res.json()['id']
    client.put(
        f'/api/v1/companies/{company_id}/assets/{a2_id}/financial',
        json={'capitalised_cost': 500.00, 'useful_life_months': 5, 'residual_value': 0.00, 'depreciation_start_date': '2025-01-01'},
    )
    client.post(
        f'/api/v1/companies/{company_id}/assets/{a2_id}/dispose',
        json={'disposal_date': '2026-01-10', 'disposal_reason': 'scrap', 'disposal_method': 'recycled', 'sale_proceeds': 50.00},
    )

    # 1. Depreciation report
    deprec_rep = client.get(f'/api/v1/companies/{company_id}/reports/asset-depreciation')
    assert deprec_rep.status_code == 200
    deprec_items = deprec_rep.json()
    assert len(deprec_items) == 2

    # CSV export
    deprec_csv = client.get(f'/api/v1/companies/{company_id}/reports/asset-depreciation?format=csv')
    assert deprec_csv.status_code == 200
    assert 'text/csv' in deprec_csv.headers['content-type']
    assert 'Asset Number,Asset Name,Category' in deprec_csv.text

    # 2. Disposal report
    disp_rep = client.get(f'/api/v1/companies/{company_id}/reports/asset-disposals')
    assert disp_rep.status_code == 200
    disp_items = disp_rep.json()
    assert len(disp_items) == 1
    assert disp_items[0]['disposal_reason'] == 'scrap'
    assert Decimal(str(disp_items[0]['gain_loss'])) == Decimal('-450.00')

    # CSV export
    disp_csv = client.get(f'/api/v1/companies/{company_id}/reports/asset-disposals?format=csv')
    assert disp_csv.status_code == 200
    assert 'text/csv' in disp_csv.headers['content-type']
    assert 'Disposal Date,Disposal Reason' in disp_csv.text

    # 3. Dashboard metrics
    dash_res = client.get(f'/api/v1/companies/{company_id}/dashboard/financial')
    assert dash_res.status_code == 200
    dash_data = dash_res.json()
    assert Decimal(str(dash_data['total_capitalised_cost'])) == Decimal('3000.00')
    assert dash_data['disposed_count'] == 1
    assert Decimal(str(dash_data['total_disposal_proceeds'])) == Decimal('50.00')
    assert Decimal(str(dash_data['total_disposal_gain_loss'])) == Decimal('-450.00')


def test_company_isolation_and_rbac(client, db_session):
    """Test 8: Strict company multi-tenancy and RBAC permission enforcement."""
    comp1_id, cat1_id = _setup_company_and_category(client, 'FIN-TENANT-1')
    comp2_id, cat2_id = _setup_company_and_category(client, 'FIN-TENANT-2')

    a1 = client.post(
        f'/api/v1/companies/{comp1_id}/assets',
        json={'category_id': cat1_id, 'model': 'Co1 Asset', 'acquisition_date': '2026-01-01', 'acquisition_cost': 1000.00},
    ).json()

    # Company 2 cannot read or post to Company 1's financial records
    cross_read = client.get(f'/api/v1/companies/{comp2_id}/assets/{a1["id"]}/financial')
    assert cross_read.status_code == 404

    cross_post = client.post(
        f'/api/v1/companies/{comp2_id}/assets/{a1["id"]}/depreciation-entries',
        json={'period': '2026-01'},
    )
    assert cross_post.status_code == 404


def test_concurrent_depreciation_postings_prevent_duplicates(client):
    """Test 9: Concurrent depreciation posting on same asset and period cannot duplicate entries."""
    company_id, category_id = _setup_company_and_category(client, 'FIN-CONCUR-1')

    asset_res = client.post(
        f'/api/v1/companies/{company_id}/assets',
        json={'category_id': category_id, 'model': 'Concurrent Asset', 'acquisition_date': '2026-01-01', 'acquisition_cost': 1200.00},
    )
    asset_id = asset_res.json()['id']
    client.put(
        f'/api/v1/companies/{company_id}/assets/{asset_id}/financial',
        json={'capitalised_cost': 1200.00, 'useful_life_months': 12, 'residual_value': 0.00, 'depreciation_start_date': '2026-01-01'},
    )

    url = f'/api/v1/companies/{company_id}/assets/{asset_id}/depreciation-entries'
    payload = {'period': '2026-01'}

    def post_deprec():
        return client.post(url, json=payload)

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(post_deprec) for _ in range(5)]
        responses = [f.result() for f in futures]

    status_codes = [r.status_code for r in responses]
    assert status_codes.count(201) == 1
    assert all(code in (201, 409) for code in status_codes)

    # Verify database has exactly 1 entry
    entries_res = client.get(f'/api/v1/companies/{company_id}/assets/{asset_id}/depreciation-entries')
    entries = entries_res.json()
    assert len(entries) == 1
    assert Decimal(str(entries[0]['depreciation_amount'])) == Decimal('100.00')
