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
