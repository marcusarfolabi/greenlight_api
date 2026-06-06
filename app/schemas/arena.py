from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from typing import Any, List, Optional
from datetime import datetime


class QuestionSchema(BaseModel):
    id: Optional[int] = None  # Make id optional for creation
    prompt_text: str
    time_limit_seconds: int = Field(ge=5, le=300)
    options: List[str]  # List of option text strings
    correct_option_index: int
    point_value: int
    is_ai_generated: bool = False
    ai_tokens_cost: int = 0
    status: str = "ready"  # ready, draft, deleted

    class Config:
        from_attributes = True


class QuestionResponse(QuestionSchema):
    id: Optional[int] = None  # Make id optional

    @model_validator(mode='before')
    @classmethod
    def handle_orm_object(cls, data: Any) -> Any:
        """Convert ORM object to dict with options extracted from options_json"""
        if hasattr(data, 'options_json'):
            # It's an ORM object, extract the data
            if isinstance(data.options_json, list) and len(data.options_json) > 0:
                if isinstance(data.options_json[0], dict):
                    options = [opt.get("text", "") for opt in data.options_json]
                else:
                    options = [opt.text if hasattr(opt, "text") else str(opt) for opt in data.options_json]
            else:
                options = []
            
            return {
                'id': data.id,
                'prompt_text': data.prompt_text,
                'time_limit_seconds': data.time_limit_seconds,
                'options': options,
                'correct_option_index': data.correct_option_index,
                'point_value': data.point_value,
                'is_ai_generated': data.is_ai_generated,
                'ai_tokens_cost': data.ai_tokens_cost,
                'status': data.status,
            }
        return data

    model_config = ConfigDict(from_attributes=True)


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
    questions: Optional[List[QuestionSchema]] = None


class ArenaTokenInfo(BaseModel):
    ai_tokens_used: int
    total_questions: int
    ai_generated_questions: int
    total_players: int = 0
    completed_players: int = 0
    completion_rate: float = 0.0


class ArenaResponse(BaseModel):
    id: int
    arena_name: str
    category: str
    is_public: bool
    creator_id: int
    creator_organization_id: Optional[int] = None
    access_code: int
    created_at: datetime
    updated_at: datetime
    ai_tokens_used: int
    questions: List[QuestionResponse]

    model_config = ConfigDict(from_attributes=True)


class ArenaDetailResponse(ArenaResponse):
    token_info: ArenaTokenInfo

    class Config:
        from_attributes = True
class ArenaTokenUsageLogResponse(BaseModel):
    id: int
    arena_id: Optional[int] = None
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