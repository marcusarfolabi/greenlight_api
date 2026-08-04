from datetime import datetime

from pydantic import BaseModel, ConfigDict


class NewsCreate(BaseModel):
    title: str
    summary: str | None = None
    content: str | None = None
    topic: str | None = None
    origin: str | None = None
    ai_generated: bool = False
    ai_model: str | None = None
    ai_tokens_cost: int | None = 0


class NewsResponse(BaseModel):
    id: int
    title: str
    slug: str | None
    summary: str | None
    content: str | None
    topic: str | None
    origin: str | None
    ai_generated: bool
    ai_model: str | None
    ai_tokens_cost: int | None
    published_at: datetime | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
