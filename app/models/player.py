from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base

if TYPE_CHECKING:
    from .arena import Arena, Question
    from .organization import Organization


class Player(Base):
    __tablename__ = "players"

    id: Mapped[int] = mapped_column(primary_key=True)
    arena_id: Mapped[str] = mapped_column(ForeignKey("arenas.id"))
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"))
    arena_access_code: Mapped[int] = mapped_column(Integer)
    session_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, index=True
    )
    username: Mapped[str | None] = mapped_column(String(100), nullable=True)
    avatar: Mapped[str | None] = mapped_column(String(100), nullable=True)
    attempt_date: Mapped[datetime] = mapped_column(insert_default=func.now())
    status: Mapped[str] = mapped_column(
        String(20), default="joined"
    )  # joined, in_progress, completed

    # Completion tracking
    completed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    score: Mapped[int | None] = mapped_column(
        default=None, nullable=True
    )  # Final score
    answers_submitted: Mapped[int | None] = mapped_column(
        default=None, nullable=True
    )  # Total answers submitted
    correct_answers: Mapped[int | None] = mapped_column(
        default=None, nullable=True
    )  # Total correct answers
    rank: Mapped[int | None] = mapped_column(
        default=None, nullable=True
    )  # Player's rank

    # Relationships
    arena: Mapped[Arena] = relationship("Arena", back_populates="players")
    organization: Mapped[Organization] = relationship("Organization")
    answer_scores: Mapped[list[PlayerAnswerScore]] = relationship(
        "PlayerAnswerScore", back_populates="player"
    )

    banking_profile: Mapped[PlayerBankingProfile | None] = relationship(
        "PlayerBankingProfile",
        back_populates="player",
        uselist=False,
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        UniqueConstraint(
            "arena_id", "session_id", "username", name="_arena_session_nickname_uc"
        ),
    )


class PlayerBankingProfile(Base):
    """
    Stores payment details required to execute automated API bank transfers (via Wise, Dwolla, etc.).
    Keeps banking metadata distinct from operational game statistics.
    """

    __tablename__ = "player_banking_profiles"

    id: Mapped[int] = mapped_column(primary_key=True)
    player_id: Mapped[int] = mapped_column(
        ForeignKey("players.id", ondelete="CASCADE"), unique=True
    )

    account_holder_name: Mapped[str] = mapped_column(
        String(255)
    )  # Official legal name matching the bank account
    email: Mapped[str] = mapped_column(
        String(255)
    )  # Destination notification email address
    phone_number: Mapped[str | None] = mapped_column(String(50), nullable=True)

    routing_number: Mapped[str | None] = mapped_column(
        String(50), nullable=True
    )  # ACH Routing Number (US)
    account_number: Mapped[str | None] = mapped_column(
        String(50), nullable=True
    )  # Bank Account Number / IBAN
    bank_code: Mapped[str | None] = mapped_column(
        String(50), nullable=True
    )  # BIC / SWIFT code for global transfers

    external_recipient_id: Mapped[str | None] = mapped_column(
        String(150), nullable=True, index=True
    )
    payout_method: Mapped[str] = mapped_column(
        String(50), default="bank_transfer"
    )  # bank_transfer, wise, paypal, etc.

    created_at: Mapped[datetime] = mapped_column(insert_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        insert_default=func.now(), onupdate=func.now()
    )

    # Relationship back to the parent Player model
    player: Mapped[Player] = relationship("Player", back_populates="banking_profile")


class PlayerAnswerScore(Base):
    """
    Records individual player answer attempts with timing-based scoring.
    Tracks answer selection, time taken, points earned, and correctness.
    Used for leaderboards, statistics, and real-time score updates.
    """

    __tablename__ = "player_answer_scores"

    id: Mapped[int] = mapped_column(primary_key=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id"))
    arena_id: Mapped[str] = mapped_column(ForeignKey("arenas.id"))
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id"))

    # Answer data
    answer_selected: Mapped[int] = mapped_column(Integer)  # Option index (0-based)
    is_correct: Mapped[bool] = mapped_column(Boolean, default=False)

    # Timing data (in seconds)
    time_taken: Mapped[float] = mapped_column(
        Float
    )  # Seconds from question start to answer
    question_time_limit: Mapped[int] = mapped_column(
        Integer
    )  # Total question duration in seconds

    # Score data
    points_earned: Mapped[int] = mapped_column(Integer)  # Final calculated score
    max_points: Mapped[int] = mapped_column(
        Integer
    )  # Maximum points possible for this question

    # Metadata
    answered_at: Mapped[datetime] = mapped_column(insert_default=func.now())

    # Relationships
    player: Mapped[Player] = relationship("Player", back_populates="answer_scores")
    arena: Mapped[Arena] = relationship("Arena")
    question: Mapped[Question] = relationship("Question")

    @staticmethod
    def calculate_score(
        time_taken: float, question_time_limit: int, max_points: int, is_correct: bool
    ) -> int:
        if not is_correct or time_taken > question_time_limit:
            return 0

        time_percentage = time_taken / question_time_limit

        if time_percentage <= 0.2:
            score_percentage = 1.0
        else:
            score_percentage = max(0, 1 - (time_percentage - 0.2) / 0.8)

        points = int(max_points * score_percentage)
        return max(0, points)
