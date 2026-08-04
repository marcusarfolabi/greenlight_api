from typing import Any

from pydantic import BaseModel


class WebSocketMessage(BaseModel):
    """Base schema for WebSocket messages."""

    type: str
    data: Any | None = None


class UserJoinMessage(BaseModel):
    type: str = "user_join"
    user_id: int
    username: str


class UserLeaveMessage(BaseModel):
    type: str = "user_leave"
    user_id: int


class QuizStartMessage(BaseModel):
    type: str = "quiz_start"
    quiz_id: int


class AnswerSubmitMessage(BaseModel):
    type: str = "answer_submit"
    question_id: int
    user_id: int
    answer: str


class ScoreUpdateMessage(BaseModel):
    type: str = "score_update"
    user_id: int
    score: int
