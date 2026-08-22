from datetime import datetime

from pydantic import BaseModel, ConfigDict


class PlayerCreate(BaseModel):
    arena_id: str
    organization_id: int
    arena_access_code: int
    session_id: str | None = None
    username: str | None = None
    attempt_date: datetime | None = None
    status: str | None = "joined"
    completed_at: datetime | None = None
    score: int | None = None
    answers_submitted: int | None = None
    correct_answers: int | None = None


class PlayerResponse(PlayerCreate):
    id: int | None = None
    rank: int | None = None
    arena_name: str | None = None
    total_players: int | None = None

    model_config = ConfigDict(from_attributes=True)


class LobbyPlayer(BaseModel):
    id: int | None = None
    username: str | None = None
    avatar: str | None = None
    joined_at: datetime | None = None


class LobbyResponse(BaseModel):
    players: list[LobbyPlayer]
    total_players: int
    lobby_waiting_time: int = 30
    arena_name: str | None = None
    arena_access_code: int | None = None

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
    username: str | None = None
    total_score: int
    answers_correct: int
    answers_total: int
    accuracy_percentage: float
    rank: int | None = None
    last_answered_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class PlayerBankingProfileCreate(BaseModel):
    account_holder_name: str
    email: str
    phone_number: str | None = None
    routing_number: str | None = None
    account_number: str | None = None
    bank_code: str | None = None
    payout_method: str | None = "bank_transfer"
    create_account: bool = False


class PlayerBankingProfileResponse(PlayerBankingProfileCreate):
    id: int | None = None
    player_id: int | None = None

    model_config = ConfigDict(from_attributes=True)
