from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict


class OrganizationBase(BaseModel):
    name: str
    subdomain: str
    industry: str
    stripe_connect_id: Optional[str] = None


class OrganizationCreate(OrganizationBase):
    owner_id: Optional[int] = None


class OrganizationUpdate(BaseModel):
    name: Optional[str] = None
    subdomain: Optional[str] = None
    industry: Optional[str] = None
    is_verified: Optional[bool] = None
    stripe_connect_id: Optional[str] = None


class OrganizationResponse(OrganizationBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    owner_id: int
    is_verified: bool
    created_at: datetime
    updated_at: datetime