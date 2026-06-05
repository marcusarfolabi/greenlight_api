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
    score: Optional[int] = None
    answers_submitted: Optional[int] = None
    correct_answers: Optional[int] = None


class PlayerResponse(PlayerCreate):
    id: int
    rank: Optional[int] = None
    arena_name: Optional[str] = None
    total_players: Optional[int] = None

    model_config = ConfigDict(from_attributes=True)
