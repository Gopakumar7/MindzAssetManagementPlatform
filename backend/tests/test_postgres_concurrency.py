import os
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, delete
from sqlalchemy.orm import sessionmaker

from app.models import Asset, AssetCategory, AssetDepartmentUsage, AssetHistory, AssetNumberRule, Company
from app.schemas import AssetCreate, CompanyCreate
from app.services import create_asset, create_company


@pytest.mark.skipif(not os.getenv('TEST_DATABASE_URL'), reason='set TEST_DATABASE_URL to run PostgreSQL concurrency integration')
def test_concurrent_asset_number_allocation_is_unique():
    engine = create_engine(os.environ['TEST_DATABASE_URL'], pool_pre_ping=True)
    sessions = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    setup = sessions()
    company = None
    try:
        company = create_company(
            setup,
            CompanyCreate(code=f'CT{uuid4().hex[:12]}', name='Numbering concurrency test', number_prefix='CON'),
        )
        category = setup.query(AssetCategory).filter_by(company_id=company.id, code='LAPTOP').one()
        company_id, category_id = company.id, category.id

        def create_one(index: int) -> str:
            with sessions() as session:
                return create_asset(
                    session,
                    company_id,
                    AssetCreate(category_id=category_id, serial_number=f'CONCURRENCY-{index}'),
                ).asset_number

        with ThreadPoolExecutor(max_workers=8) as executor:
            numbers = list(executor.map(create_one, range(24)))
        assert len(numbers) == len(set(numbers)) == 24
        assert set(numbers) == {f'CON-{number:06d}' for number in range(1, 25)}
    finally:
        if company is not None:
            setup.execute(delete(AssetHistory).where(AssetHistory.company_id == company.id))
            setup.execute(delete(AssetDepartmentUsage).where(AssetDepartmentUsage.company_id == company.id))
            setup.execute(delete(Asset).where(Asset.company_id == company.id))
            setup.execute(delete(AssetNumberRule).where(AssetNumberRule.company_id == company.id))
            setup.execute(delete(AssetCategory).where(AssetCategory.company_id == company.id))
            setup.execute(delete(Company).where(Company.id == company.id))
            setup.commit()
        setup.close()
        engine.dispose()
