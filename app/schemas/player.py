from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class PlayerCreate(BaseModel):
    arena_id: int
    organization_id: int
    arena_access_code: int
    username: Optional[str] = None
    attempt_date: Optional[datetime] = None
    status: Optional[str] = "joined"
    completed_at: Optional[datetime] = None
    score: int = 0
    answers_submitted: int = 0
    correct_answers: int = 0


class PlayerResponse(PlayerCreate):
    id: int

    model_config = ConfigDict(from_attributes=True)
