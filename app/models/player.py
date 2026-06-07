from __future__ import annotations

from typing import TYPE_CHECKING, Optional
from datetime import datetime 
from sqlalchemy import String, ForeignKey, Integer, UniqueConstraint, func, Float, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base

if TYPE_CHECKING:
    from .arena import Arena, Question
    from .organization import Organization


class Player(Base):
    __tablename__ = "players"

    id: Mapped[int] = mapped_column(primary_key=True)
    arena_id: Mapped[int] = mapped_column(ForeignKey("arenas.id"))
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"))
    arena_access_code: Mapped[int] = mapped_column(Integer)
    username: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    attempt_date: Mapped[datetime] = mapped_column(insert_default=func.now())
    status: Mapped[str] = mapped_column(String(20), default="joined")  # joined, in_progress, completed
    
    # Completion tracking
    completed_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    score: Mapped[Optional[int]] = mapped_column(default=None, nullable=True)  # Final score
    answers_submitted: Mapped[Optional[int]] = mapped_column(default=None, nullable=True)  # Total answers submitted
    correct_answers: Mapped[Optional[int]] = mapped_column(default=None, nullable=True)  # Total correct answers
    rank: Mapped[Optional[int]] = mapped_column(default=None, nullable=True)  # Player's rank

    arena: Mapped["Arena"] = relationship("Arena", back_populates="players")
    organization: Mapped["Organization"] = relationship("Organization")
    answer_scores: Mapped[list["PlayerAnswerScore"]] = relationship("PlayerAnswerScore", back_populates="player")
    
    __table_args__ = (
        UniqueConstraint('arena_id', 'username', name='_arena_nickname_uc'),
    )


class PlayerAnswerScore(Base):
    """
    Records individual player answer attempts with timing-based scoring.
    Tracks answer selection, time taken, points earned, and correctness.
    Used for leaderboards, statistics, and real-time score updates.
    """
    __tablename__ = "player_answer_scores"

    id: Mapped[int] = mapped_column(primary_key=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id"))
    arena_id: Mapped[int] = mapped_column(ForeignKey("arenas.id"))
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id"))
    
    # Answer data
    answer_selected: Mapped[int] = mapped_column(Integer)  # Option index (0-based)
    is_correct: Mapped[bool] = mapped_column(Boolean, default=False)
    
    # Timing data (in seconds)
    time_taken: Mapped[float] = mapped_column(Float)  # Seconds from question start to answer
    question_time_limit: Mapped[int] = mapped_column(Integer)  # Total question duration in seconds
    
    # Score data
    points_earned: Mapped[int] = mapped_column(Integer)  # Final calculated score
    max_points: Mapped[int] = mapped_column(Integer)  # Maximum points possible for this question
    
    # Metadata
    answered_at: Mapped[datetime] = mapped_column(insert_default=func.now())

    # Relationships
    player: Mapped["Player"] = relationship("Player", back_populates="answer_scores")
    arena: Mapped["Arena"] = relationship("Arena")
    question: Mapped["Question"] = relationship("Question")
    
    @staticmethod
    def calculate_score(time_taken: float, question_time_limit: int, max_points: int, is_correct: bool) -> int:
        """
        Calculate score based on answer timing.
        - Correct answer in 1st second: 100% of points
        - Each additional second reduces score by a percentage
        - After time limit: 0 points
        
        Scoring formula:
        - time_taken as % of time_limit determines score percentage
        - 20% time = 100% score, 40% time = 80% score, 60% time = 60% score, 100% time = 0% score
        """
        if not is_correct or time_taken > question_time_limit:
            return 0
        
        # Calculate percentage of time used (0.0 to 1.0)
        time_percentage = time_taken / question_time_limit
        
        # Map time percentage to score percentage
        # 0% time -> 100%, 20% time -> 100%, 40% time -> 80%, 60% time -> 60%, 100% time -> 0%
        if time_percentage <= 0.2:
            score_percentage = 1.0  # First 20% of time = full points
        else:
            # Linear decay: from 100% at 20% time to 0% at 100% time
            # score_percentage = 1 - ((time_percentage - 0.2) / 0.8)
            score_percentage = max(0, 1 - (time_percentage - 0.2) / 0.8)
        
        # Calculate final points
        points = int(max_points * score_percentage)
        return max(0, points)
