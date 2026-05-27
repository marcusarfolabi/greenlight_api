from typing import List, Optional
from datetime import datetime
from sqlalchemy import String, ForeignKey, Text, Boolean, Integer, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .base import Base

class Arena(Base):
    __tablename__ = "arenas"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    title: Mapped[str] = mapped_column(String(100), nullable=False)
    is_public: Mapped[bool] = mapped_column(default=False)
    creator_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    creator_organization_id: Mapped[Optional[int]] = mapped_column(ForeignKey("organizations.id"), nullable=True)
    
    # AI Token tracking
    ai_tokens_used: Mapped[int] = mapped_column(default=0)
    ai_tokens_budget: Mapped[Optional[int]] = mapped_column(nullable=True)  # Optional per-arena budget

    created_at: Mapped[datetime] = mapped_column(insert_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(insert_default=func.now(), onupdate=func.now())

    questions: Mapped[List["Question"]] = relationship(
        back_populates="arena", cascade="all, delete-orphan"
    )
    token_usage_logs: Mapped[List["ArenaTokenUsageLog"]] = relationship(
        back_populates="arena", cascade="all, delete-orphan"
    )

class Question(Base):
    __tablename__ = "questions"

    id: Mapped[int] = mapped_column(primary_key=True)
    arena_id: Mapped[int] = mapped_column(ForeignKey("arenas.id"))
    prompt_text: Mapped[str] = mapped_column(Text, nullable=False)
    time_limit_seconds: Mapped[int] = mapped_column(default=10)
    point_value: Mapped[int] = mapped_column(default=10)
    correct_option_index: Mapped[int] = mapped_column()
    
    # AI token tracking
    ai_tokens_cost: Mapped[int] = mapped_column(default=0)  # Tokens used to generate this question
    is_ai_generated: Mapped[bool] = mapped_column(default=False)

    created_at: Mapped[datetime] = mapped_column(insert_default=func.now())

    arena: Mapped["Arena"] = relationship(back_populates="questions")
    options: Mapped[List["QuestionOption"]] = relationship(
        back_populates="question", cascade="all, delete-orphan"
    )

class QuestionOption(Base):
    __tablename__ = "question_options"
    id: Mapped[int] = mapped_column(primary_key=True)
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id"))
    text: Mapped[str] = mapped_column(String(255))
    
    question: Mapped["Question"] = relationship(back_populates="options")


class ArenaTokenUsageLog(Base):
    """Detailed log of token usage per arena"""
    __tablename__ = "arena_token_usage_logs"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    arena_id: Mapped[int] = mapped_column(ForeignKey("arenas.id"))
    tokens_used: Mapped[int] = mapped_column()
    operation: Mapped[str] = mapped_column(String(50))  # "question_generation", "regenerate", etc.
    details: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    created_at: Mapped[datetime] = mapped_column(insert_default=func.now())
    
    arena: Mapped["Arena"] = relationship(back_populates="token_usage_logs")