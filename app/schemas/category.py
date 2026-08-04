from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class CategoryCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)


class CategoryUpdate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)


class CategorySchema(BaseModel):
    id: int | None = None
    name: str
    slug: str
    org_id: int


class CategoryResponse(CategorySchema):
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
