"""Error model, pagination and list helpers shared by every router."""

from __future__ import annotations

import uuid
from typing import Any, TypeVar

from fastapi import Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session

T = TypeVar("T")


class AppError(Exception):
    def __init__(
        self,
        status: int,
        code: str,
        message: str,
        details: list[dict[str, Any]] | None = None,
        **extra: Any,
    ):
        super().__init__(message)
        self.status, self.code, self.message, self.details, self.extra = status, code, message, details, extra


def not_found(what: str = "Resource") -> AppError:
    return AppError(404, "NOT_FOUND", f"{what} not found.")


def conflict(code: str, message: str) -> AppError:
    return AppError(409, code, message)


def invalid(code: str, message: str, field: str | None = None) -> AppError:
    details = [{"field": field, "issue": code.lower()}] if field else None
    return AppError(422, code, message, details)


def _body(request: Request, code: str, message: str, details=None, **extra) -> dict:
    err = {"code": code, "message": message, "request_id": getattr(request.state, "request_id", None)}
    if details:
        err["details"] = details
    err.update(extra)
    return {"error": err}


async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    headers = {"Retry-After": str(exc.extra["retry_after"])} if "retry_after" in exc.extra else None
    return JSONResponse(
        _body(request, exc.code, exc.message, exc.details, **exc.extra),
        status_code=exc.status,
        headers=headers,
    )


async def validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    details = [
        {"field": ".".join(str(p) for p in e["loc"][1:]), "issue": e["type"], "message": e["msg"]}
        for e in exc.errors()
    ]
    return JSONResponse(
        _body(request, "VALIDATION_FAILED", "Some fields are invalid.", details), status_code=422
    )


class Page[T](BaseModel):
    data: list[T]
    total: int
    limit: int
    offset: int


class PageParams:
    def __init__(
        self,
        limit: int = Query(25, ge=1, le=200),
        offset: int = Query(0, ge=0),
        q: str | None = Query(None, max_length=200),
        sort: str | None = Query(None, max_length=100),
    ):
        self.limit, self.offset, self.q, self.sort = limit, offset, q, sort


def paginate(
    db: Session,
    stmt: Select,
    params: PageParams,
    *,
    search_cols: tuple = (),
    sortable: dict[str, Any] | None = None,
    default_sort=None,
    schema=None,
) -> dict:
    if params.q and search_cols:
        like = f"%{params.q.strip()}%"
        stmt = stmt.where(or_(*[c.ilike(like) for c in search_cols]))
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    order = []
    if params.sort and sortable:
        for part in params.sort.split(","):
            desc = part.startswith("-")
            col = sortable.get(part.lstrip("-"))
            if col is not None:
                order.append(col.desc() if desc else col.asc())
    if not order and default_sort is not None:
        order = [default_sort]
    stmt = stmt.order_by(*order).limit(params.limit).offset(params.offset)
    rows = db.scalars(stmt).all()
    data = [schema.model_validate(r) for r in rows] if schema else rows
    return {"data": data, "total": total, "limit": params.limit, "offset": params.offset}


def new_request_id() -> str:
    return "req_" + uuid.uuid4().hex[:20]
