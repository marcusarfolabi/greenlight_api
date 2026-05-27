from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime


class QuestionSchema(BaseModel):
    prompt_text: str
    time_limit_seconds: int = Field(ge=5, le=300)
    options: List[str]
    correct_option_index: int
    point_value: int
    is_ai_generated: bool = False
    ai_tokens_cost: int = 0

    class Config:
        from_attributes = True


class QuestionResponse(QuestionSchema):
    id: int

    class Config:
        from_attributes = True


class ArenaCreate(BaseModel):
    arena_name: str
    category: str
    is_public: bool
    questions: List[QuestionSchema]


class ArenaUpdate(BaseModel):
    arena_name: Optional[str] = None
    category: Optional[str] = None
    is_public: Optional[bool] = None


class ArenaTokenInfo(BaseModel):
    ai_tokens_used: int
    ai_tokens_budget: Optional[int] = None
    total_questions: int
    ai_generated_questions: int


class ArenaResponse(ArenaCreate):
    id: int
    creator_id: int
    creator_organization_id: Optional[int] = None
    created_at: datetime
    updated_at: datetime
    ai_tokens_used: int
    questions: List[QuestionResponse] = []

    class Config:
        from_attributes = True


class ArenaDetailResponse(ArenaResponse):
    token_info: ArenaTokenInfo

    class Config:
        from_attributes = True


class TokenUsageResponse(BaseModel):
    total_tokens: int
    used_tokens: int
    remaining_tokens: int
    plan_name: str
    plan_type: str
    has_tokens: bool

    class Config:
        from_attributes = True