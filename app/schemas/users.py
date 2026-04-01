from __future__ import annotations

from pydantic import BaseModel


class CreateUserResponse(BaseModel):
    user_id: str
