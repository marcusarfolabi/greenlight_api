from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class PlayerCreate(BaseModel):
    arena_id: str
    organization_id: int
    arena_access_code: int
    session_id: Optional[str] = None
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


class PlayerAnswerScoreCreate(BaseModel):
    player_id: int
    arena_id: str
    question_id: int
    answer_selected: int
    is_correct: bool
    time_taken: float
    question_time_limit: int
    points_earned: int
    max_points: int


class PlayerAnswerScoreResponse(PlayerAnswerScoreCreate):
    id: int
    answered_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PlayerScoreboardResponse(BaseModel):
    """Player score info for leaderboard display"""
    player_id: int
    username: Optional[str] = None
    total_score: int
    answers_correct: int
    answers_total: int
    accuracy_percentage: float
    rank: Optional[int] = None
    last_answered_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class PlayerBankingProfileCreate(BaseModel):
    account_holder_name: str
    email: str
    phone_number: Optional[str] = None
    routing_number: Optional[str] = None
    account_number: Optional[str] = None
    bank_code: Optional[str] = None
    payout_method: Optional[str] = "bank_transfer"
    create_account: bool = False


class PlayerBankingProfileResponse(PlayerBankingProfileCreate):
    id: Optional[int] = None
    player_id: Optional[int] = None

    model_config = ConfigDict(from_attributes=True)
