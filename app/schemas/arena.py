from pydantic import BaseModel, ConfigDict, Field
from typing import List, Optional
from datetime import datetime


class QuestionSchema(BaseModel):
    id: Optional[int] = None  # Make id optional for creation
    prompt_text: str
    time_limit_seconds: int = Field(ge=5, le=300)
    options: List[str]
    correct_option_index: int
    point_value: int
    is_ai_generated: bool = False
    ai_tokens_cost: int = 0
    status: str = "draft"  # active, draft, deleted

    class Config:
        from_attributes = True


class QuestionResponse(QuestionSchema):
    id: Optional[int] = None  # Make id optional
        


class ArenaCreate(BaseModel):
    arena_name: str
    category: str
    is_public: bool
    questions: List[QuestionSchema]


class AIQuestionGenerationRequest(BaseModel):
    subject: str
    num_questions: int = Field(ge=1, le=20)
    difficulty: str = Field(default="medium")  # easy, medium, hard
    language: str = Field(default="en")
    arena_id: Optional[int] = None


class ArenaUpdate(BaseModel):
    arena_name: Optional[str] = None
    status: Optional[str] = None  # active, draft, deleted
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

    model_config = ConfigDict(from_attributes=True)


class ArenaDetailResponse(ArenaResponse):
    token_info: ArenaTokenInfo

    class Config:
        from_attributes = True
class ArenaTokenUsageLogResponse(BaseModel):
    id: int
    arena_id: int
    tokens_used: int
    operation: str
    details: Optional[str] = None
    created_at: datetime

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