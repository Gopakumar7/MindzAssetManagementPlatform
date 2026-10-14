from fastapi import FastAPI, Request
from fastapi.exceptions import HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1.router import router as api_router
from app.core.config import settings
from app.core.logging_config import configure_logging

configure_logging()

app = FastAPI(
    title=settings.app_title,
    version=settings.app_version,
    description='MindZen ALCM / ITAM backend foundation',
    openapi_url='/openapi.json',
    docs_url='/docs',
    redoc_url='/redoc',
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=['*'],
    allow_headers=['*'],
)


@app.exception_handler(HTTPException)
async def http_exception_handler(_: Request, exc: HTTPException) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={'detail': exc.detail})


@app.exception_handler(Exception)
async def general_exception_handler(_: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=500, content={'detail': 'Internal server error'})


app.include_router(api_router, prefix=settings.api_prefix)


@app.get('/')
async def root() -> dict[str, str]:
    return {'service': settings.app_title, 'status': 'running'}
