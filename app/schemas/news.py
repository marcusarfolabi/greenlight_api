from datetime import datetime
from typing import Optional
from pydantic import BaseModel


class NewsCreate(BaseModel):
    title: str
    summary: Optional[str] = None
    content: Optional[str] = None
    topic: Optional[str] = None
    origin: Optional[str] = None
    ai_generated: bool = False
    ai_model: Optional[str] = None
    ai_tokens_cost: Optional[int] = 0


class NewsResponse(BaseModel):
    id: int
    title: str
    slug: Optional[str]
    summary: Optional[str]
    content: Optional[str]
    topic: Optional[str]
    origin: Optional[str]
    ai_generated: bool
    ai_model: Optional[str]
    ai_tokens_cost: Optional[int]
    published_at: Optional[datetime]
    created_at: datetime

    class Config:
        orm_mode = True
