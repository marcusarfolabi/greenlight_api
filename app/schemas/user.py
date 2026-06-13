from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, EmailStr, model_validator

from app.models.user import UserRole
from app.schemas.organization import OrganizationCreate, OrganizationResponse

class AuthContext(BaseModel):
    token: str
    user_id: int
    org_id: int
    role: str
    username: str
    
class ResendOTPRequest(BaseModel):
    email: EmailStr

class VerifyOTPRequest(BaseModel):
    email: EmailStr
    otp: str
 
    
class ForgotPasswordRequest(BaseModel):
    email: EmailStr

class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str

class TokenRefreshRequest(BaseModel):
    refresh_token: str

class GoogleTokenPayload(BaseModel):
    token: str
    
class UserBase(BaseModel):
    username: str
    email: EmailStr

class UserCreate(UserBase):
    password: str
    role: str = "user" 
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    phone_number: Optional[str] = None # Added field
class UserOrgCreate(BaseModel):
    user: UserCreate
    organization: OrganizationCreate

    @model_validator(mode="after")
    def validate_host_organization(self) -> "UserOrgCreate":
        if self.user.role == UserRole.HOST and self.organization is None:
            raise ValueError("Organization data is required when role is HOST")
        return self
    


class UserUpdate(BaseModel):
    username: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    phone_number: Optional[str] = None # Added field
    email: Optional[EmailStr] = None
    is_active: Optional[bool] = None


class UserResponse(UserBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    role: UserRole
    is_active: bool
    created_at: datetime
    owned_organization: Optional[OrganizationResponse] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    phone_number: Optional[str] = None # Added field
    username: str
    email: EmailStr

class Token(BaseModel):
    model_config = ConfigDict(from_attributes=True) # Pydantic V2

    access_token: str
    token_type: str
    role: UserRole
    username: str
    email: str
    id: int
    is_active: bool
    created_at: datetime 
    


class TokenPayload(BaseModel):
    sub: Optional[str] = None
