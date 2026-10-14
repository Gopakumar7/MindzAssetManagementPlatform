from concurrent.futures import ThreadPoolExecutor


def create_company(client, code: str, prefix: str = 'ASSET'):
    response = client.post('/api/v1/companies', json={'code': code, 'name': f'{code} Ltd', 'number_prefix': prefix})
    assert response.status_code == 201, response.text
    return response.json()


def test_company_scoped_masters_and_company_isolation(client):
    company_a = create_company(client, 'ACME')
    company_b = create_company(client, 'BETA')

    department = client.post(
        f"/api/v1/companies/{company_a['id']}/departments",
        json={'code': 'OPS', 'name': 'Operations'},
    )
    site = client.post(
        f"/api/v1/companies/{company_a['id']}/sites",
        json={'code': 'HQ', 'name': 'Head Office', 'address': 'Main Street'},
    )
    assert department.status_code == 201
    assert site.status_code == 201
    location = client.post(
        f"/api/v1/companies/{company_a['id']}/sites/{site.json()['id']}/locations",
        json={'code': 'R1', 'name': 'Room 1'},
    )
    assert location.status_code == 201

    assert len(client.get(f"/api/v1/companies/{company_a['id']}/departments").json()) == 1
    assert client.get(f"/api/v1/companies/{company_b['id']}/departments").json() == []
    assert client.get(f"/api/v1/companies/{company_b['id']}/sites/{site.json()['id']}/locations").status_code == 404

    cross_company_department = client.post(
        f"/api/v1/companies/{company_b['id']}/departments",
        json={'code': 'OPS', 'name': 'Operations'},
    )
    assert cross_company_department.status_code == 201
    categories = client.get(f"/api/v1/companies/{company_a['id']}/categories").json()
    assert {category['name'] for category in categories} == {
        'Laptops', 'Desktops', 'Servers', 'Printers', 'Network equipment', 'Peripherals'
    }


def test_asset_numbering_precedence_manual_duplicate_and_invalid_rule(client):
    company = create_company(client, 'NUM', prefix='DEFAULT')
    categories = client.get(f"/api/v1/companies/{company['id']}/categories").json()
    laptop = next(category for category in categories if category['code'] == 'LAPTOP')
    desktop = next(category for category in categories if category['code'] == 'DESKTOP')
    server = next(category for category in categories if category['code'] == 'SERVER')

    default_rule = client.get(f"/api/v1/companies/{company['id']}/numbering-rules").json()[0]
    assert default_rule['prefix'] == 'DEFAULT'
    category_rule = client.put(
        f"/api/v1/companies/{company['id']}/numbering-rules?category_id={laptop['id']}",
        json={'prefix': 'LAP', 'separator': '-', 'padding': 4},
    )
    assert category_rule.status_code == 200

    first = client.post(
        f"/api/v1/companies/{company['id']}/assets",
        json={'category_id': laptop['id'], 'serial_number': 'SN-1'},
    )
    second = client.post(
        f"/api/v1/companies/{company['id']}/assets",
        json={'category_id': desktop['id']},
    )
    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    assert first.json()['asset_number'] == 'LAP-0001'
    assert second.json()['asset_number'] == 'DEFAULT-000002'
    assert first.json()['id'] != second.json()['id']

    same_prefix_rule = client.put(
        f"/api/v1/companies/{company['id']}/numbering-rules?category_id={server['id']}",
        json={'prefix': 'LAP', 'separator': '-', 'padding': 4},
    )
    assert same_prefix_rule.status_code == 200
    third = client.post(
        f"/api/v1/companies/{company['id']}/assets",
        json={'category_id': server['id']},
    )
    assert third.status_code == 201, third.text
    assert third.json()['asset_number'] == 'LAP-0003'
    assert len({first.json()['asset_number'], second.json()['asset_number'], third.json()['asset_number']}) == 3

    manually_numbered = client.post(
        f"/api/v1/companies/{company['id']}/assets",
        json={'category_id': desktop['id'], 'asset_number': 'LAP-0004'},
    )
    fourth = client.post(
        f"/api/v1/companies/{company['id']}/assets",
        json={'category_id': server['id']},
    )
    assert manually_numbered.status_code == 201, manually_numbered.text
    assert fourth.status_code == 201, fourth.text
    assert fourth.json()['asset_number'] == 'LAP-0005'

    duplicate = client.post(
        f"/api/v1/companies/{company['id']}/assets",
        json={'category_id': desktop['id'], 'asset_number': first.json()['asset_number']},
    )
    assert duplicate.status_code == 409

    invalid_rule = client.put(
        f"/api/v1/companies/{company['id']}/numbering-rules?category_id={desktop['id']}",
        json={'prefix': 'bad prefix', 'separator': '-', 'padding': 3},
    )
    assert invalid_rule.status_code == 422


def test_assets_validate_company_relationships_and_preserve_fields(client):
    company_a = create_company(client, 'AONE')
    company_b = create_company(client, 'BTWO')
    category_a = client.get(f"/api/v1/companies/{company_a['id']}/categories").json()[0]
    category_b = client.get(f"/api/v1/companies/{company_b['id']}/categories").json()[0]
    site = client.post(f"/api/v1/companies/{company_a['id']}/sites", json={'code': 'HQ', 'name': 'HQ'}).json()
    location = client.post(
        f"/api/v1/companies/{company_a['id']}/sites/{site['id']}/locations",
        json={'code': 'R1', 'name': 'Room 1'},
    ).json()
    department_b = client.post(
        f"/api/v1/companies/{company_b['id']}/departments",
        json={'code': 'OPS', 'name': 'Operations'},
    ).json()

    cross = client.post(
        f"/api/v1/companies/{company_b['id']}/assets",
        json={'category_id': category_b['id'], 'site_id': site['id'], 'location_id': location['id']},
    )
    assert cross.status_code == 404

    asset = client.post(
        f"/api/v1/companies/{company_a['id']}/assets",
        json={
            'category_id': category_a['id'],
            'site_id': site['id'],
            'location_id': location['id'],
            'custodian_name': 'Jordan Smith',
            'notes': 'Keep existing details',
        },
    )
    assert asset.status_code == 201, asset.text
    updated = client.patch(
        f"/api/v1/companies/{company_a['id']}/assets/{asset.json()['id']}",
        json={'status': 'deployed'},
    )
    assert updated.status_code == 200
    assert updated.json()['status'] == 'deployed'
    assert updated.json()['notes'] == 'Keep existing details'
    assert updated.json()['custodian_name'] == 'Jordan Smith'

    wrong_department = client.patch(
        f"/api/v1/companies/{company_a['id']}/assets/{asset.json()['id']}",
        json={'responsible_department_id': department_b['id']},
    )
    assert wrong_department.status_code == 404
    wrong_site_location = client.patch(
        f"/api/v1/companies/{company_a['id']}/assets/{asset.json()['id']}",
        json={'site_id': None},
    )
    assert wrong_site_location.status_code == 422


def test_shared_department_usage_history_and_filters(client):
    company = create_company(client, 'SHARE')
    other_company = create_company(client, 'OTHER')
    categories = client.get(f"/api/v1/companies/{company['id']}/categories").json()
    department_a = client.post(
        f"/api/v1/companies/{company['id']}/departments",
        json={'code': 'OPS', 'name': 'Operations'},
    ).json()
    department_b = client.post(
        f"/api/v1/companies/{company['id']}/departments",
        json={'code': 'FIN', 'name': 'Finance'},
    ).json()
    asset = client.post(
        f"/api/v1/companies/{company['id']}/assets",
        json={'category_id': categories[0]['id'], 'custodian_name': 'Alex User'},
    ).json()

    usage_a = client.post(
        f"/api/v1/companies/{company['id']}/assets/{asset['id']}/usages",
        json={'department_id': department_a['id'], 'purpose': 'Shared printing'},
    )
    usage_b = client.post(
        f"/api/v1/companies/{company['id']}/assets/{asset['id']}/usages",
        json={'department_id': department_b['id'], 'purpose': 'Backup use'},
    )
    assert usage_a.status_code == usage_b.status_code == 201
    foreign_department = client.post(
        f"/api/v1/companies/{other_company['id']}/departments",
        json={'code': 'EXT', 'name': 'External'},
    ).json()
    cross_company_usage = client.post(
        f"/api/v1/companies/{company['id']}/assets/{asset['id']}/usages",
        json={'department_id': foreign_department['id']},
    )
    assert cross_company_usage.status_code == 404
    duplicate = client.post(
        f"/api/v1/companies/{company['id']}/assets/{asset['id']}/usages",
        json={'department_id': department_a['id']},
    )
    assert duplicate.status_code == 409
    assert client.get(f"/api/v1/companies/{company['id']}/assets/{asset['id']}").json()['id'] == asset['id']
    unchanged_asset = client.get(f"/api/v1/companies/{company['id']}/assets/{asset['id']}").json()
    assert unchanged_asset['custodian_name'] == 'Alex User'
    assert unchanged_asset['site_id'] is None

    ended = client.post(
        f"/api/v1/companies/{company['id']}/assets/{asset['id']}/usages/{usage_a.json()['id']}/end"
    )
    assert ended.status_code == 200
    assert ended.json()['ended_at'] is not None
    history = client.get(f"/api/v1/companies/{company['id']}/assets/{asset['id']}/history").json()
    assert {entry['event_type'] for entry in history} >= {'created', 'department_usage_started', 'department_usage_ended'}

    current = client.get(
        f"/api/v1/companies/{company['id']}/assets",
        params={'department_id': department_a['id'], 'page': 1, 'page_size': 10},
    ).json()
    assert current['total'] == 0
    ended_query = client.get(
        f"/api/v1/companies/{company['id']}/assets/{asset['id']}/usages",
        params={'include_ended': True},
    )
    assert len(ended_query.json()) == 2


def test_pagination_and_department_deactivation(client):
    company = create_company(client, 'PAGE')
    categories = client.get(f"/api/v1/companies/{company['id']}/categories").json()
    for index in range(3):
        response = client.post(
            f"/api/v1/companies/{company['id']}/assets",
            json={'category_id': categories[0]['id'], 'serial_number': f'SERIAL-{index}'},
        )
        assert response.status_code == 201
    result = client.get(f"/api/v1/companies/{company['id']}/assets", params={'page': 2, 'page_size': 2})
    assert result.status_code == 200
    assert result.json()['total'] == 3
    assert len(result.json()['items']) == 1

    department = client.post(
        f"/api/v1/companies/{company['id']}/departments",
        json={'code': 'OLD', 'name': 'Old Department'},
    ).json()
    deactivated = client.delete(f"/api/v1/companies/{company['id']}/departments/{department['id']}")
    assert deactivated.status_code == 200
    assert deactivated.json()['is_active'] is False
