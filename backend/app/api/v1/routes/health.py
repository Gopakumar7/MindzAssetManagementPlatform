from datetime import datetime, UTC

from fastapi import APIRouter, HTTPException, status

from app import database
from app.core.config import settings
from app.schemas import HealthResponse, ReadinessResponse

router = APIRouter(prefix='/health', tags=['health'])


@router.get('', response_model=HealthResponse)
async def health_check() -> dict[str, str]:
    return {
        'status': 'ok',
        'service': 'mindzen-alcm',
        'version': settings.app_version,
    }


@router.get('/ready', response_model=ReadinessResponse)
async def readiness_check() -> dict[str, object]:
    is_available, reason = database.check_database_health()
    if not is_available:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                'status': 'not_ready',
                'database': {'available': False, 'message': reason},
                'timestamp': datetime.now(UTC).isoformat(),
            },
        )

    return {
        'status': 'ready',
        'database': {'available': True, 'message': reason},
    }
