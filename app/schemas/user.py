from datetime import datetime

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
    role: UserRole | None = None
    location: str | None = None
    country_iso: str | None = None


class AppleTokenPayload(BaseModel):
    token: str
    role: UserRole | None = None
    location: str | None = None
    country_iso: str | None = None


class LinkedInTokenPayload(BaseModel):
    code: str
    role: UserRole | None = None
    location: str | None = None
    country_iso: str | None = None


class UserBase(BaseModel):
    username: str
    email: EmailStr


class UserCreate(UserBase):
    password: str
    role: str = "user"
    first_name: str | None = None
    last_name: str | None = None
    phone_number: str | None = None
    organization_id: str | None = None
    is_active: bool | None = False
    google_id: str | None = None
    linkedin_id: str | None = None
    apple_id: str | None = None
    location: str | None = None
    country_iso: str | None = None
    accepted_terms: bool = False
    client_ip: str | None = None

    @model_validator(mode="after")
    def validate_terms_acceptance(self) -> "UserCreate":
        if not self.accepted_terms:
            raise ValueError("Terms and Privacy Policy acceptance is required")
        return self


class UserOrgCreate(BaseModel):
    user: UserCreate
    organization: OrganizationCreate

    @model_validator(mode="after")
    def validate_host_organization(self) -> "UserOrgCreate":
        if self.user.role == UserRole.HOST and self.organization is None:
            raise ValueError("Organization data is required when role is HOST")
        return self


class UserUpdate(BaseModel):
    username: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    phone_number: str | None = None
    email: EmailStr | None = None
    avatar: str | None = None
    location: str | None = None
    is_active: bool | None = None
    password: str | None = None


class UserResponse(UserBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    role: UserRole
    is_active: bool
    created_at: datetime
    owned_organization: OrganizationResponse | None = None
    first_name: str | None = None
    last_name: str | None = None
    phone_number: str | None = None
    avatar: str | None = None
    username: str
    email: EmailStr
    google_id: str | None = None
    linkedin_id: str | None = None
    apple_id: str | None = None


class Token(BaseModel):
    model_config = ConfigDict(from_attributes=True)  # Pydantic V2

    access_token: str
    token_type: str
    role: UserRole
    username: str
    email: str
    id: int
    is_active: bool
    created_at: datetime


class PushSubscriptionCreate(BaseModel):
    fcm_token: str
    device_type: str | None = "fcm"
    device_meta: dict | None = None


class TokenPayload(BaseModel):
    sub: str | None = None
