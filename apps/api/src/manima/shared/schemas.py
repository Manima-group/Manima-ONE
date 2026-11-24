from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_serializer


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Entity(ORM):
    id: uuid.UUID
    created_at: datetime | None = None
    updated_at: datetime | None = None
    version: int | None = None


class Msg(BaseModel):
    ok: bool = True
    message: str | None = None


class DecimalStr(BaseModel):
    """Mixin documenting that money/qty values serialise as strings (API_STANDARDS §1)."""

    @field_serializer("*", when_used="json", check_fields=False)
    def _ser(self, v):
        from decimal import Decimal

        return format(v, "f") if isinstance(v, Decimal) else v
