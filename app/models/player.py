from __future__ import annotations

from typing import TYPE_CHECKING, Optional
from datetime import datetime 
from sqlalchemy import String, ForeignKey, Integer, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base

if TYPE_CHECKING:
    from .arena import Arena
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
    
    __table_args__ = (
        UniqueConstraint('arena_id', 'username', name='_arena_nickname_uc'),
    )
