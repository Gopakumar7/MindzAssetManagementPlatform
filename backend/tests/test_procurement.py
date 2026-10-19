from uuid import UUID

from sqlalchemy import select

from app.authentication import password_hasher
from app.models import (
    Asset,
    AuditEvent,
    CompanyMembership,
    GoodsReceipt,
    GoodsReceiptLine,
    PurchaseOrder,
    Role,
    User,
)


def test_purchase_order_receipt_registers_assets_and_preserves_audit(client, db_session):
    company = client.post(
        '/api/v1/companies',
        json={'code': 'PROC1', 'name': 'Procurement company', 'number_prefix': 'PRC'},
    ).json()
    category = client.get(f"/api/v1/companies/{company['id']}/categories").json()[0]
    supplier_response = client.post(
        f"/api/v1/companies/{company['id']}/suppliers",
        json={'code': 'SUP-1', 'name': 'Demo supplier'},
    )
    assert supplier_response.status_code == 201, supplier_response.text
    supplier = supplier_response.json()
    order_response = client.post(
        f"/api/v1/companies/{company['id']}/purchase-orders",
        json={
            'supplier_id': supplier['id'],
            'order_number': 'PO-DEMO-1',
            'ordered_date': '2026-10-16',
            'lines': [{
                'category_id': category['id'],
                'description': 'Demo laptop',
                'quantity_ordered': 3,
                'unit_cost': '1250.00',
            }],
        },
    )
    assert order_response.status_code == 201, order_response.text
    order = order_response.json()
    order_line = order['lines'][0]
    receipt_response = client.post(
        f"/api/v1/companies/{company['id']}/purchase-orders/{order['id']}/goods-receipts",
        json={
            'receipt_number': 'GRN-DEMO-1',
            'received_date': '2026-10-16',
            'delivery_reference': 'DN-55',
            'lines': [{
                'purchase_order_line_id': order_line['id'],
                'quantity_received': 2,
                'quantity_rejected': 1,
                'serial_numbers': ['DEMO-SERIAL-1'],
                'discrepancy_notes': 'One item arrived damaged',
            }],
        },
    )
    assert receipt_response.status_code == 201, receipt_response.text
    receipt = receipt_response.json()
    assert receipt['lines'][0]['quantity_received'] == 2
    assert receipt['lines'][0]['quantity_rejected'] == 1
    assert len(receipt['lines'][0]['assets']) == 1
    assert receipt['lines'][0]['assets'][0]['serial_number'] == 'DEMO-SERIAL-1'
    assert client.get(f"/api/v1/companies/{company['id']}/purchase-orders").json()[0]['status'] == 'partially_received'

    db_session.expire_all()
    asset = db_session.scalar(select(Asset).where(Asset.company_id == UUID(company['id'])))
    assert asset.goods_receipt_line_id is not None
    assert asset.status == 'in_stock'
    assert asset.vendor_reference == 'SUP-1'
    assert db_session.scalar(select(GoodsReceipt).where(GoodsReceipt.id == UUID(receipt['id']))) is not None
    assert db_session.scalar(select(GoodsReceiptLine).where(GoodsReceiptLine.goods_receipt_id == UUID(receipt['id']))) is not None
    order_audit = db_session.scalar(select(AuditEvent).where(
        AuditEvent.company_id == UUID(company['id']),
        AuditEvent.entity_type == 'PurchaseOrder',
        AuditEvent.action == 'purchase_order_created',
    ))
    assert order_audit is not None
    assert order_audit.changes['lines'][0]['quantity_ordered'] == 3
    receipt_audit = db_session.scalar(select(AuditEvent).where(
        AuditEvent.company_id == UUID(company['id']),
        AuditEvent.entity_type == 'GoodsReceipt',
        AuditEvent.action == 'goods_received',
    ))
    assert receipt_audit is not None
    assert receipt_audit.changes['lines'][0]['quantity_received'] == 2
    assert receipt_audit.changes['lines'][0]['quantity_rejected'] == 1
    assert receipt_audit.changes['lines'][0]['created_assets'][0]['asset_number'] == receipt['lines'][0]['assets'][0]['asset_number']
    assert db_session.scalar(select(PurchaseOrder).where(PurchaseOrder.id == UUID(order['id']))).status == 'partially_received'


def test_receipt_over_ordered_quantity_is_rejected_without_partial_data(client, db_session):
    company = client.post(
        '/api/v1/companies',
        json={'code': 'PROC2', 'name': 'Procurement company two', 'number_prefix': 'PR2'},
    ).json()
    category = client.get(f"/api/v1/companies/{company['id']}/categories").json()[0]
    supplier = client.post(
        f"/api/v1/companies/{company['id']}/suppliers",
        json={'code': 'SUP-2', 'name': 'Second supplier'},
    ).json()
    order = client.post(
        f"/api/v1/companies/{company['id']}/purchase-orders",
        json={
            'supplier_id': supplier['id'],
            'order_number': 'PO-DEMO-2',
            'ordered_date': '2026-10-16',
            'lines': [{
                'category_id': category['id'],
                'description': 'Demo monitor',
                'quantity_ordered': 1,
                'unit_cost': '300.00',
            }],
        },
    ).json()
    response = client.post(
        f"/api/v1/companies/{company['id']}/purchase-orders/{order['id']}/goods-receipts",
        json={
            'receipt_number': 'GRN-OVER',
            'received_date': '2026-10-16',
            'lines': [{
                'purchase_order_line_id': order['lines'][0]['id'],
                'quantity_received': 2,
            }],
        },
    )
    assert response.status_code == 422
    assert 'exceeds the remaining ordered quantity' in response.json()['detail']
    db_session.expire_all()
    assert db_session.scalar(select(GoodsReceipt).where(GoodsReceipt.receipt_number == 'GRN-OVER')) is None
    assert db_session.scalar(select(Asset).where(Asset.company_id == UUID(company['id']))) is None


def test_procurement_enforces_company_scope_and_management_permission(client, db_session):
    first_company = client.post(
        '/api/v1/companies',
        json={'code': 'PROC3', 'name': 'Procurement company three'},
    ).json()
    second_company = client.post(
        '/api/v1/companies',
        json={'code': 'PROC4', 'name': 'Procurement company four'},
    ).json()
    supplier = client.post(
        f"/api/v1/companies/{first_company['id']}/suppliers",
        json={'code': 'SUP-3', 'name': 'First-company supplier'},
    ).json()
    category = client.get(f"/api/v1/companies/{second_company['id']}/categories").json()[0]
    cross_company_order = client.post(
        f"/api/v1/companies/{second_company['id']}/purchase-orders",
        json={
            'supplier_id': supplier['id'],
            'order_number': 'PO-CROSS',
            'ordered_date': '2026-10-16',
            'lines': [{
                'category_id': category['id'],
                'description': 'Cross-company item',
                'quantity_ordered': 1,
                'unit_cost': '10.00',
            }],
        },
    )
    assert cross_company_order.status_code == 422

    auditor_role = db_session.scalar(select(Role).where(Role.scope == 'company', Role.code == 'auditor'))
    auditor = User(
        email='procurement-auditor@example.invalid',
        password_hash=password_hasher.hash('Auditor-Password-42!'),
        is_active=True,
    )
    db_session.add(auditor)
    db_session.flush()
    db_session.add(CompanyMembership(
        company_id=UUID(first_company['id']),
        user_id=auditor.id,
        role_id=auditor_role.id,
        status='active',
    ))
    db_session.commit()
    client.post('/api/v1/auth/logout')
    login = client.post(
        '/api/v1/auth/login',
        json={'email': auditor.email, 'password': 'Auditor-Password-42!'},
    )
    assert login.status_code == 200
    client.headers['X-CSRF-Token'] = client.cookies['mindzen_csrf']
    assert client.get(f"/api/v1/companies/{first_company['id']}/suppliers").status_code == 200
    assert client.post(
        f"/api/v1/companies/{first_company['id']}/suppliers",
        json={'code': 'SUP-DENIED', 'name': 'Forbidden supplier'},
    ).status_code == 403


def test_multiline_purchase_order_creation_totals_and_distinct_categories(client, db_session):
    company = client.post(
        '/api/v1/companies',
        json={'code': 'MLPO1', 'name': 'Multi-line PO Company', 'number_prefix': 'MLP'},
    ).json()
    categories = client.get(f"/api/v1/companies/{company['id']}/categories").json()
    assert len(categories) >= 3, 'Should have at least 3 default categories'
    cat1, cat2, cat3 = categories[0], categories[1], categories[2]

    supplier = client.post(
        f"/api/v1/companies/{company['id']}/suppliers",
        json={'code': 'SUP-MULTI', 'name': 'Global IT Supplies'},
    ).json()

    # 1. Create a PO with 3 lines belonging to distinct categories
    order_res = client.post(
        f"/api/v1/companies/{company['id']}/purchase-orders",
        json={
            'supplier_id': supplier['id'],
            'order_number': 'PO-MULTI-001',
            'ordered_date': '2026-10-18',
            'expected_date': '2026-10-25',
            'notes': 'Multi-line office refresh',
            'lines': [
                {
                    'category_id': cat1['id'],
                    'description': 'Executive Ultrabook',
                    'quantity_ordered': 5,
                    'unit_cost': '1200.00',
                },
                {
                    'category_id': cat2['id'],
                    'description': '27-inch 4K Display',
                    'quantity_ordered': 10,
                    'unit_cost': '350.50',
                },
                {
                    'category_id': cat3['id'],
                    'description': 'Ergonomic Desk Chair',
                    'quantity_ordered': 8,
                    'unit_cost': '225.00',
                },
            ],
        },
    )
    assert order_res.status_code == 201, order_res.text
    order = order_res.json()

    # 2. Verify authoritative totals
    # Line 1: 5 * 1200.00 = 6000.00
    # Line 2: 10 * 350.50 = 3505.00
    # Line 3: 8 * 225.00 = 1800.00
    # Subtotal: 6000.00 + 3505.00 + 1800.00 = 11305.00
    # Total Qty: 5 + 10 + 8 = 23
    assert order['total_quantity'] == 23
    assert order['subtotal'] == '11305.00'
    assert order['total_amount'] == '11305.00'
    assert len(order['lines']) == 3

    lines_by_desc = {line['description']: line for line in order['lines']}
    assert lines_by_desc['Executive Ultrabook']['line_subtotal'] == '6000.00'
    assert lines_by_desc['Executive Ultrabook']['line_total'] == '6000.00'
    assert lines_by_desc['Executive Ultrabook']['quantity_ordered'] == 5
    assert lines_by_desc['Executive Ultrabook']['quantity_received'] == 0
    assert lines_by_desc['Executive Ultrabook']['quantity_remaining'] == 5

    assert lines_by_desc['27-inch 4K Display']['line_subtotal'] == '3505.00'
    assert lines_by_desc['27-inch 4K Display']['line_total'] == '3505.00'
    assert lines_by_desc['27-inch 4K Display']['quantity_ordered'] == 10
    assert lines_by_desc['27-inch 4K Display']['quantity_remaining'] == 10

    assert lines_by_desc['Ergonomic Desk Chair']['line_subtotal'] == '1800.00'
    assert lines_by_desc['Ergonomic Desk Chair']['line_total'] == '1800.00'
    assert lines_by_desc['Ergonomic Desk Chair']['quantity_ordered'] == 8
    assert lines_by_desc['Ergonomic Desk Chair']['quantity_remaining'] == 8

    # 3. Retrieve single order and verify persistence
    get_res = client.get(f"/api/v1/companies/{company['id']}/purchase-orders/{order['id']}")
    assert get_res.status_code == 200
    fetched = get_res.json()
    assert fetched['order_number'] == 'PO-MULTI-001'
    assert fetched['total_quantity'] == 23
    assert fetched['total_amount'] == '11305.00'
    assert len(fetched['lines']) == 3

    # 4. Audit event verification
    db_session.expire_all()
    audit = db_session.scalar(select(AuditEvent).where(
        AuditEvent.company_id == UUID(company['id']),
        AuditEvent.entity_type == 'PurchaseOrder',
        AuditEvent.action == 'purchase_order_created',
        AuditEvent.entity_id == str(order['id']),
    ))
    assert audit is not None
    assert len(audit.changes['lines']) == 3


def test_update_open_purchase_order_add_edit_remove_lines_and_validations(client, db_session):
    company = client.post(
        '/api/v1/companies',
        json={'code': 'MLPO2', 'name': 'PO Edit Company', 'number_prefix': 'MLE'},
    ).json()
    categories = client.get(f"/api/v1/companies/{company['id']}/categories").json()
    cat1, cat2 = categories[0], categories[1]
    supplier = client.post(
        f"/api/v1/companies/{company['id']}/suppliers",
        json={'code': 'SUP-EDIT', 'name': 'Edit Supplier'},
    ).json()

    # Create initial PO with 2 lines
    order = client.post(
        f"/api/v1/companies/{company['id']}/purchase-orders",
        json={
            'supplier_id': supplier['id'],
            'order_number': 'PO-EDIT-001',
            'ordered_date': '2026-10-18',
            'lines': [
                {'category_id': cat1['id'], 'description': 'Item A', 'quantity_ordered': 2, 'unit_cost': '100.00'},
                {'category_id': cat2['id'], 'description': 'Item B', 'quantity_ordered': 3, 'unit_cost': '200.00'},
            ],
        },
    ).json()
    assert order['total_quantity'] == 5
    assert order['total_amount'] == '800.00'

    # Update PO: edit line 1, remove line 2, add line 3
    put_res = client.put(
        f"/api/v1/companies/{company['id']}/purchase-orders/{order['id']}",
        json={
            'supplier_id': supplier['id'],
            'order_number': 'PO-EDIT-001',
            'ordered_date': '2026-10-18',
            'expected_date': '2026-10-30',
            'notes': 'Updated order notes',
            'lines': [
                {'category_id': cat1['id'], 'description': 'Item A modified', 'quantity_ordered': 4, 'unit_cost': '150.00'},
                {'category_id': cat2['id'], 'description': 'Item C newly added', 'quantity_ordered': 1, 'unit_cost': '500.00'},
            ],
        },
    )
    assert put_res.status_code == 200, put_res.text
    updated = put_res.json()
    # 4 * 150 = 600, 1 * 500 = 500. Total = 1100.00. Total qty = 5.
    assert updated['total_quantity'] == 5
    assert updated['total_amount'] == '1100.00'
    assert len(updated['lines']) == 2
    assert {l['description'] for l in updated['lines']} == {'Item A modified', 'Item C newly added'}
    assert updated['notes'] == 'Updated order notes'

    # Validation: empty lines array rejected
    bad_empty = client.put(
        f"/api/v1/companies/{company['id']}/purchase-orders/{order['id']}",
        json={'lines': []},
    )
    assert bad_empty.status_code == 422

    # Validation: zero quantity rejected
    bad_qty = client.put(
        f"/api/v1/companies/{company['id']}/purchase-orders/{order['id']}",
        json={'lines': [{'category_id': cat1['id'], 'description': 'Invalid Qty', 'quantity_ordered': 0, 'unit_cost': '10.00'}]},
    )
    assert bad_qty.status_code == 422

    # Validation: negative unit cost rejected
    bad_cost = client.put(
        f"/api/v1/companies/{company['id']}/purchase-orders/{order['id']}",
        json={'lines': [{'category_id': cat1['id'], 'description': 'Invalid Cost', 'quantity_ordered': 1, 'unit_cost': '-5.00'}]},
    )
    assert bad_cost.status_code == 422

    # Validation: expected date before ordered date rejected
    bad_date = client.put(
        f"/api/v1/companies/{company['id']}/purchase-orders/{order['id']}",
        json={
            'ordered_date': '2026-10-20',
            'expected_date': '2026-10-15',
            'lines': [{'category_id': cat1['id'], 'description': 'Valid', 'quantity_ordered': 1, 'unit_cost': '10.00'}],
        },
    )
    assert bad_date.status_code == 422


def test_multiline_goods_receipt_partial_deliveries_and_over_receipt_protection(client, db_session):
    company = client.post(
        '/api/v1/companies',
        json={'code': 'MLPO3', 'name': 'PO Receipt Company', 'number_prefix': 'MLR'},
    ).json()
    categories = client.get(f"/api/v1/companies/{company['id']}/categories").json()
    cat_laptop, cat_monitor = categories[0], categories[1]
    supplier = client.post(
        f"/api/v1/companies/{company['id']}/suppliers",
        json={'code': 'SUP-RCV', 'name': 'Receiving Vendor'},
    ).json()

    # Create PO with 2 lines: Line 1 = 5 laptops, Line 2 = 3 monitors
    order = client.post(
        f"/api/v1/companies/{company['id']}/purchase-orders",
        json={
            'supplier_id': supplier['id'],
            'order_number': 'PO-RCV-001',
            'ordered_date': '2026-10-18',
            'lines': [
                {'category_id': cat_laptop['id'], 'description': 'Workstation Laptop', 'quantity_ordered': 5, 'unit_cost': '1500.00'},
                {'category_id': cat_monitor['id'], 'description': 'External Monitor', 'quantity_ordered': 3, 'unit_cost': '400.00'},
            ],
        },
    ).json()
    lines_by_desc = {l['description']: l for l in order['lines']}
    line_laptop = lines_by_desc['Workstation Laptop']
    line_monitor = lines_by_desc['External Monitor']

    # Partial Receipt 1: 2 laptops and 1 monitor received
    rcv1_res = client.post(
        f"/api/v1/companies/{company['id']}/purchase-orders/{order['id']}/goods-receipts",
        json={
            'receipt_number': 'GRN-PARTIAL-1',
            'received_date': '2026-10-19',
            'lines': [
                {
                    'purchase_order_line_id': line_laptop['id'],
                    'quantity_received': 2,
                    'quantity_rejected': 0,
                    'serial_numbers': ['LAPTOP-SN-1', 'LAPTOP-SN-2'],
                },
                {
                    'purchase_order_line_id': line_monitor['id'],
                    'quantity_received': 1,
                    'quantity_rejected': 0,
                    'serial_numbers': ['MON-SN-1'],
                },
            ],
        },
    )
    assert rcv1_res.status_code == 201, rcv1_res.text
    rcv1 = rcv1_res.json()
    assert len(rcv1['lines']) == 2
    rcv1_by_line = {l['purchase_order_line_id']: l for l in rcv1['lines']}
    assert len(rcv1_by_line[line_laptop['id']]['assets']) == 2
    assert len(rcv1_by_line[line_monitor['id']]['assets']) == 1

    # Check PO status and remaining quantities
    po_after_rcv1 = client.get(f"/api/v1/companies/{company['id']}/purchase-orders/{order['id']}").json()
    assert po_after_rcv1['status'] == 'partially_received'
    lines1 = {l['description']: l for l in po_after_rcv1['lines']}
    assert lines1['Workstation Laptop']['quantity_received'] == 2
    assert lines1['Workstation Laptop']['quantity_remaining'] == 3
    assert lines1['External Monitor']['quantity_received'] == 1
    assert lines1['External Monitor']['quantity_remaining'] == 2

    # Attempt to edit PO now -> must return 409 Conflict
    edit_attempt = client.put(
        f"/api/v1/companies/{company['id']}/purchase-orders/{order['id']}",
        json={
            'lines': [{'category_id': cat_laptop['id'], 'description': 'Trying to modify', 'quantity_ordered': 10, 'unit_cost': '10.00'}],
        },
    )
    assert edit_attempt.status_code == 409
    assert 'only open purchase orders may be modified' in edit_attempt.json()['detail']

    # Attempt over-receipt on Line 1: ordered 5, received 2, remaining 3. Trying to receive 4 -> 422
    over_res = client.post(
        f"/api/v1/companies/{company['id']}/purchase-orders/{order['id']}/goods-receipts",
        json={
            'receipt_number': 'GRN-OVER-ATTEMPT',
            'received_date': '2026-10-19',
            'lines': [
                {
                    'purchase_order_line_id': line_laptop['id'],
                    'quantity_received': 4,
                    'quantity_rejected': 0,
                },
            ],
        },
    )
    assert over_res.status_code == 422
    assert 'exceeds the remaining ordered quantity' in over_res.json()['detail']

    # Partial Receipt 2: complete remaining 3 laptops and remaining 2 monitors
    rcv2_res = client.post(
        f"/api/v1/companies/{company['id']}/purchase-orders/{order['id']}/goods-receipts",
        json={
            'receipt_number': 'GRN-PARTIAL-2',
            'received_date': '2026-10-19',
            'lines': [
                {
                    'purchase_order_line_id': line_laptop['id'],
                    'quantity_received': 3,
                    'quantity_rejected': 0,
                    'serial_numbers': ['LAPTOP-SN-3', 'LAPTOP-SN-4', 'LAPTOP-SN-5'],
                },
                {
                    'purchase_order_line_id': line_monitor['id'],
                    'quantity_received': 2,
                    'quantity_rejected': 0,
                    'serial_numbers': ['MON-SN-2', 'MON-SN-3'],
                },
            ],
        },
    )
    assert rcv2_res.status_code == 201

    # Now PO status must be 'received' and remaining quantities must be 0
    po_final = client.get(f"/api/v1/companies/{company['id']}/purchase-orders/{order['id']}").json()
    assert po_final['status'] == 'received'
    lines_final = {l['description']: l for l in po_final['lines']}
    assert lines_final['Workstation Laptop']['quantity_received'] == 5
    assert lines_final['Workstation Laptop']['quantity_remaining'] == 0
    assert lines_final['External Monitor']['quantity_received'] == 3
    assert lines_final['External Monitor']['quantity_remaining'] == 0

    # Total assets registered across both receipts: 5 laptops + 3 monitors = 8 assets
    db_session.expire_all()
    assets = db_session.scalars(select(Asset).where(Asset.company_id == UUID(company['id']))).all()
    assert len(assets) == 8
    laptop_assets = [a for a in assets if a.category_id == UUID(cat_laptop['id'])]
    monitor_assets = [a for a in assets if a.category_id == UUID(cat_monitor['id'])]
    assert len(laptop_assets) == 5
    assert len(monitor_assets) == 3

    # Attempting any receipt against a fully received PO is rejected with 409
    late_rcv = client.post(
        f"/api/v1/companies/{company['id']}/purchase-orders/{order['id']}/goods-receipts",
        json={
            'receipt_number': 'GRN-LATE',
            'received_date': '2026-10-19',
            'lines': [{'purchase_order_line_id': line_laptop['id'], 'quantity_received': 1}],
        },
    )
    assert late_rcv.status_code == 409

