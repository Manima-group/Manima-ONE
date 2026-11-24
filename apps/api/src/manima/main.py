"""FastAPI app factory: middleware, error model, routers for every module."""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

import manima.models  # noqa: F401
from manima.core import routes_auth, routes_platform, routes_tenant
from manima.modules.catalog.module import router as catalog_router
from manima.modules.compliance_gst.routes import router as gst_router
from manima.modules.crm.module import router as crm_router
from manima.modules.inventory.module import router as inventory_router
from manima.modules.invoicing.module import router as invoicing_router
from manima.modules.payments.module import router as payments_router
from manima.modules.procurement.module import router as procurement_router
from manima.modules.reports.module import router as reports_router
from manima.modules.sales.module import router as sales_router
from manima.settings import get_settings
from manima.shared.db import session_factory
from manima.shared.http import AppError, app_error_handler, new_request_id, validation_handler

log = logging.getLogger("manima")

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(
        title="Manima One API",
        version="1.0.0",
        docs_url=None if s.environment == "production" else "/api/docs",
        openapi_url="/api/openapi.json",
    )

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request.state.request_id = request.headers.get("x-request-id") or new_request_id()
        # CSRF defence for cookie sessions (API_STANDARDS §2): writes need the custom header.
        if (
            request.method not in SAFE_METHODS
            and request.url.path.startswith("/api/")
            and request.headers.get("x-requested-with") != "manima"
        ):
            return JSONResponse(
                {
                    "error": {
                        "code": "CSRF_HEADER_MISSING",
                        "message": "Missing X-Requested-With header.",
                        "request_id": request.state.request_id,
                    }
                },
                status_code=400,
            )
        response = await call_next(request)
        response.headers["X-Request-Id"] = request.state.request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        return response

    app.add_middleware(
        CORSMiddleware,
        allow_origins=s.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-Id"],
    )
    app.add_exception_handler(AppError, app_error_handler)
    app.add_exception_handler(RequestValidationError, validation_handler)

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception):  # pragma: no cover
        log.exception("unhandled error request_id=%s", getattr(request.state, "request_id", None))
        return JSONResponse(
            {
                "error": {
                    "code": "INTERNAL_ERROR",
                    "message": "Something went wrong.",
                    "request_id": getattr(request.state, "request_id", None),
                }
            },
            status_code=500,
        )

    for r in (
        routes_auth.router,
        routes_tenant.router,
        routes_platform.router,
        gst_router,
        catalog_router,
        crm_router,
        sales_router,
        invoicing_router,
        payments_router,
        inventory_router,
        procurement_router,
        reports_router,
    ):
        app.include_router(r)

    @app.get("/healthz", include_in_schema=False)
    def healthz():
        with session_factory()() as db:
            db.execute(text("select 1"))
        return {"status": "ok"}

    return app


app = create_app()
