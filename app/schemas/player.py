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
    id: Optional[int] = None
    rank: Optional[int] = None
    arena_name: Optional[str] = None
    total_players: Optional[int] = None

    model_config = ConfigDict(from_attributes=True)


class LobbyPlayer(BaseModel):
    id: Optional[int] = None
    username: Optional[str] = None
    joined_at: Optional[datetime] = None


class LobbyResponse(BaseModel):
    players: list[LobbyPlayer]
    total_players: int
    lobby_waiting_time: int = 30
    arena_name: Optional[str] = None
    arena_access_code: Optional[int] = None
    

    model_config = ConfigDict(from_attributes=True)
