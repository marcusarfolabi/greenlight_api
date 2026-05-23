from pydantic import BaseModel, Field
from typing import List

class QuestionSchema(BaseModel):
    prompt_text: str
    time_limit_seconds: int = Field(ge=5, le=300)
    options: List[str]
    correct_option_index: int
    point_value: int

class ArenaCreate(BaseModel):
    arena_name: str
    category: str
    is_public: bool
    questions: List[QuestionSchema]

class ArenaResponse(ArenaCreate):
    id: int
    creator_id: int

    class Config:
        from_attributes = True