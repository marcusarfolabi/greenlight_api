from __future__ import annotations

from typing import TYPE_CHECKING, Optional
from datetime import datetime 
from sqlalchemy import String, ForeignKey, Integer, func
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
    score: Mapped[int] = mapped_column(default=0)  # Final score
    answers_submitted: Mapped[int] = mapped_column(default=0)  # Total answers submitted
    correct_answers: Mapped[int] = mapped_column(default=0)  # Total correct answers

    arena: Mapped["Arena"] = relationship("Arena", back_populates="players")
    organization: Mapped["Organization"] = relationship("Organization")
