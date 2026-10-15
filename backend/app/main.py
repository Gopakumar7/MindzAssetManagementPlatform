import logging
from uuid import UUID, uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1.router import router as api_router
from app.core.config import settings
from app.core.logging_config import configure_logging

configure_logging()
logger = logging.getLogger(__name__)

app = FastAPI(
    title=settings.app_title,
    version=settings.app_version,
    description='MindZen ALCM / ITAM backend foundation',
    openapi_url='/openapi.json' if settings.app_env.casefold() in {'development', 'dev'} else None,
    docs_url='/docs' if settings.app_env.casefold() in {'development', 'dev'} else None,
    redoc_url='/redoc' if settings.app_env.casefold() in {'development', 'dev'} else None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=['*'],
    allow_headers=['Content-Type', 'X-CSRF-Token', 'X-Request-ID'],
)


@app.middleware('http')
async def add_request_id(request: Request, call_next):
    requested_id = request.headers.get('x-request-id', '')
    try:
        request_id = str(UUID(requested_id))
    except ValueError:
        request_id = str(uuid4())
    request.state.request_id = request_id
    response = await call_next(request)
    response.headers['X-Request-ID'] = request_id
    return response


@app.exception_handler(HTTPException)
async def http_exception_handler(_: Request, exc: HTTPException) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={'detail': exc.detail})


@app.exception_handler(Exception)
async def general_exception_handler(_: Request, exc: Exception) -> JSONResponse:
    logger.error('Unhandled request exception', exc_info=(type(exc), exc, exc.__traceback__))
    return JSONResponse(status_code=500, content={'detail': 'Internal server error'})


app.include_router(api_router, prefix=settings.api_prefix)


@app.get('/')
async def root() -> dict[str, str]:
    return {'service': settings.app_title, 'status': 'running'}
