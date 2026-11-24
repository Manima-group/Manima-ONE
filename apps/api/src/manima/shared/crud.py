"""Small helpers for tenant-scoped CRUD (defence in depth on top of RLS)."""

from __future__ import annotations

import uuid
from typing import TypeVar

from pydantic import BaseModel
from sqlalchemy.orm import Session

from manima.shared.http import AppError, not_found

M = TypeVar("M")


def get_or_404[M](
    db: Session,
    model: type[M],
    obj_id: uuid.UUID | None,
    tenant_id: uuid.UUID,
    what: str = "Record",
    *,
    lock: bool = False,
) -> M:
    if obj_id is None:
        raise not_found(what)
    obj = db.get(model, obj_id, with_for_update=lock) if lock else db.get(model, obj_id)
    if (
        obj is None
        or getattr(obj, "tenant_id", None) != tenant_id
        or getattr(obj, "deleted_at", None) is not None
    ):
        raise not_found(what)
    return obj


def ref_or_422(db: Session, model, obj_id: uuid.UUID | None, tenant_id: uuid.UUID, field: str, what: str):
    """Validate a referenced record belongs to the tenant (422, not 404, for body references)."""
    if obj_id is None:
        return None
    obj = db.get(model, obj_id)
    if obj is None or obj.tenant_id != tenant_id or getattr(obj, "deleted_at", None) is not None:
        raise AppError(
            422, "INVALID_REFERENCE", f"{what} not found.", [{"field": field, "issue": "not_found"}]
        )
    return obj


def apply_patch(obj, body: BaseModel, *, exclude: set[str] | None = None) -> None:
    data = body.model_dump(exclude_unset=True, exclude=(exclude or set()) | {"version"})
    expected = getattr(body, "version", None)
    if expected is not None and hasattr(obj, "version") and expected != obj.version:
        raise AppError(409, "VERSION_CONFLICT", "This record was changed by someone else. Reload and retry.")
    for k, v in data.items():
        setattr(obj, k, v)
    if hasattr(obj, "version"):
        obj.version = (obj.version or 0) + 1
