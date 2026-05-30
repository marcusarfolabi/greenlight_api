from pydantic import BaseModel, ConfigDict, Field
from typing import Optional
from datetime import datetime


class CategoryCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100) 


class CategoryUpdate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)


class CategorySchema(BaseModel):
    id: Optional[int] = None
    name: str
    slug: str
    org_id: int


class CategoryResponse(CategorySchema):
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
