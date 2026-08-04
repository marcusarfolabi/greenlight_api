from __future__ import annotations

import secrets
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import JSON, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base

if TYPE_CHECKING:
    from .organization import Organization
    from .player import Player


class Arena(Base):
    __tablename__ = "arenas"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, index=True, default=lambda: str(uuid.uuid4())
    )
    arena_name: Mapped[str] = mapped_column(String(100), nullable=False)
    is_public: Mapped[bool] = mapped_column(default=False)
    creator_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    creator_organization_id: Mapped[int | None] = mapped_column(
        ForeignKey("organizations.id"), nullable=True
    )

    ai_tokens_used: Mapped[int] = mapped_column(default=0)
    access_code: Mapped[int | None] = mapped_column(
        default=lambda: secrets.randbelow(9000) + 1000, nullable=True
    )  # per-arena access code
    players_session_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, index=True
    )

    created_at: Mapped[datetime] = mapped_column(insert_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        insert_default=func.now(), onupdate=func.now()
    )

    questions: Mapped[list[Question]] = relationship(
        back_populates="arena", cascade="all, delete-orphan"
    )
    players: Mapped[list[Player]] = relationship(
        "Player", back_populates="arena", cascade="all, delete-orphan"
    )
    token_usage_logs: Mapped[list[ArenaTokenUsageLog]] = relationship(
        back_populates="arena", cascade="all, delete-orphan"
    )


class Question(Base):
    __tablename__ = "questions"

    id: Mapped[int] = mapped_column(primary_key=True)
    arena_id: Mapped[str] = mapped_column(ForeignKey("arenas.id"))
    prompt_text: Mapped[str] = mapped_column(Text, nullable=False)
    time_limit_seconds: Mapped[int] = mapped_column(default=10)
    point_value: Mapped[int] = mapped_column(default=10)
    status: Mapped[str] = mapped_column(
        String(10), default="ready"
    )  # ready, draft, deleted
    type: Mapped[str] = mapped_column(
        String(20), default="multiple_choice"
    )  # multiple_choice, multiple_select, true_false, numeric, short_answer

    # if type is image, this field can store the URL or path to the image
    # image_url: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    # if type is video, this field can store the URL or path to the video
    # video_url: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    correct_option_index: Mapped[int | None] = mapped_column(nullable=True)

    correct_answer_string: Mapped[str | None] = mapped_column(Text, nullable=True)

    correct_answers: Mapped[list[int] | None] = mapped_column(JSON, nullable=True)

    # AI token tracking
    ai_tokens_cost: Mapped[int] = mapped_column(default=0)
    is_ai_generated: Mapped[bool] = mapped_column(default=False)

    # JSON-based options storage (empty list [] is safe for text-based questions)
    options_json: Mapped[list] = mapped_column(
        JSON, default=list
    )  # [{"text": "option1"}, ...]

    created_at: Mapped[datetime] = mapped_column(insert_default=func.now())

    arena: Mapped[Arena] = relationship(back_populates="questions")


class ArenaTokenUsageLog(Base):
    """Detailed log of token usage per arena"""

    __tablename__ = "arena_token_usage_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    arena_id: Mapped[str | None] = mapped_column(ForeignKey("arenas.id"), nullable=True)
    organization_id: Mapped[int | None] = mapped_column(
        ForeignKey("organizations.id"), nullable=True
    )
    tokens_used: Mapped[int] = mapped_column()
    capped_tokens: Mapped[int | None] = mapped_column()
    operation: Mapped[str] = mapped_column(
        String(50)
    )  # "question_generation", "regenerate", etc.
    details: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(insert_default=func.now())

    arena: Mapped[Arena] = relationship(back_populates="token_usage_logs")
    organization: Mapped[Organization | None] = relationship("Organization")
