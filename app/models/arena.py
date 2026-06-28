from __future__ import annotations

import secrets
import uuid
from typing import TYPE_CHECKING, List, Optional
from datetime import datetime
from sqlalchemy import String, ForeignKey, Text, func, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .base import Base

if TYPE_CHECKING:
    from .organization import Organization
    from .player import Player

class Arena(Base):
    __tablename__ = "arenas"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, index=True, default=lambda: str(uuid.uuid4()))
    arena_name: Mapped[str] = mapped_column(String(100), nullable=False) 
    category: Mapped[str] = mapped_column(String(100), nullable=True)
    is_public: Mapped[bool] = mapped_column(default=False)
    creator_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    creator_organization_id: Mapped[Optional[int]] = mapped_column(ForeignKey("organizations.id"), nullable=True)
    
    ai_tokens_used: Mapped[int] = mapped_column(default=0)
    access_code: Mapped[Optional[int]] = mapped_column(default=lambda: secrets.randbelow(9000) + 1000, nullable=True)  # per-arena access code

    created_at: Mapped[datetime] = mapped_column(insert_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(insert_default=func.now(), onupdate=func.now())

    questions: Mapped[List["Question"]] = relationship(
        back_populates="arena", cascade="all, delete-orphan"
    )
    players: Mapped[List["Player"]] = relationship(
        "Player", back_populates="arena", cascade="all, delete-orphan"
    )
    token_usage_logs: Mapped[List["ArenaTokenUsageLog"]] = relationship(
        back_populates="arena", cascade="all, delete-orphan"
    )

class Question(Base):
    __tablename__ = "questions"

    id: Mapped[int] = mapped_column(primary_key=True)
    arena_id: Mapped[str] = mapped_column(ForeignKey("arenas.id"))
    prompt_text: Mapped[str] = mapped_column(Text, nullable=False)
    time_limit_seconds: Mapped[int] = mapped_column(default=10)
    point_value: Mapped[int] = mapped_column(default=10)
    status: Mapped[str] = mapped_column(String(10), default="ready")  # ready, draft, deleted
    type: Mapped[str] = mapped_column(String(20), default="multiple_choice")  # multiple_choice, multiple_select, true_false, numeric, short_answer
    
    correct_option_index: Mapped[Optional[int]] = mapped_column(nullable=True)
    
    correct_answer_string: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    correct_answers: Mapped[Optional[List[int]]] = mapped_column(JSON, nullable=True)
    
    # AI token tracking
    ai_tokens_cost: Mapped[int] = mapped_column(default=0)
    is_ai_generated: Mapped[bool] = mapped_column(default=False)
    
    # JSON-based options storage (empty list [] is safe for text-based questions)
    options_json: Mapped[list] = mapped_column(JSON, default=list)  # [{"text": "option1"}, ...]

    created_at: Mapped[datetime] = mapped_column(insert_default=func.now())

    arena: Mapped["Arena"] = relationship(back_populates="questions")

class ArenaTokenUsageLog(Base):
    """Detailed log of token usage per arena"""
    __tablename__ = "arena_token_usage_logs"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    arena_id: Mapped[Optional[str]] = mapped_column(ForeignKey("arenas.id"), nullable=True)
    organization_id: Mapped[Optional[int]] = mapped_column(ForeignKey("organizations.id"), nullable=True)
    tokens_used: Mapped[int] = mapped_column()
    capped_tokens: Mapped[Optional[int]] = mapped_column()
    operation: Mapped[str] = mapped_column(String(50))  # "question_generation", "regenerate", etc.
    details: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    created_at: Mapped[datetime] = mapped_column(insert_default=func.now())
    
    arena: Mapped["Arena"] = relationship(back_populates="token_usage_logs")
    organization: Mapped[Optional["Organization"]] = relationship("Organization")