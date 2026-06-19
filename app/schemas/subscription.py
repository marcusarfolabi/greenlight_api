from pydantic import BaseModel
from typing import Optional
from datetime import datetime
from enum import Enum

class CreatePaymentIntentRequest(BaseModel):
    organization_id: int
    plan_id: int


class ConfirmPaymentRequest(BaseModel):
    organization_id: int
    plan_id: int
    payment_intent_id: str
class SubscriptionPlanTypeSchema(str, Enum):
    FREE = "free"
    STANDARD = "standard"
    PRO = "pro"


class SubscriptionPlanBase(BaseModel):
    name: str
    description: str
    price: float
    currency: str
    interval: str
    max_players: Optional[int] = None
    max_arenas: Optional[int] = None
    max_custom_themes: Optional[int] = None
    api_access: bool = False
    analytics: bool = False
    white_label: bool = False
    priority_support: bool = False
    ai_tokens: int = 0


class SubscriptionPlanCreate(SubscriptionPlanBase):
    plan_type: SubscriptionPlanTypeSchema
    stripe_product_id: Optional[str] = None
    stripe_price_id: Optional[str] = None
    display_order: int = 0
    ai_tokens: int = 0


class SubscriptionPlanUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    price: Optional[float] = None
    max_players: Optional[int] = None
    max_arenas: Optional[int] = None
    api_access: Optional[bool] = None
    analytics: Optional[bool] = None
    white_label: Optional[bool] = None
    priority_support: Optional[bool] = None
    ai_tokens: Optional[int] = None
    is_active: Optional[bool] = None


class SubscriptionPlanResponse(SubscriptionPlanBase):
    id: int
    plan_type: SubscriptionPlanTypeSchema
    stripe_product_id: Optional[str] = None
    stripe_price_id: Optional[str] = None
    is_active: bool
    display_order: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class SubscriptionBase(BaseModel):
    organization_id: int
    plan_id: int
    status: str = "active"


class SubscriptionCreate(SubscriptionBase):
    stripe_subscription_id: Optional[str] = None
    stripe_customer_id: Optional[str] = None


class SubscriptionResponse(SubscriptionBase):
    id: int
    stripe_subscription_id: Optional[str] = None
    stripe_customer_id: Optional[str] = None
    started_at: datetime
    canceled_at: Optional[datetime] = None
    current_period_start: Optional[datetime] = None
    current_period_end: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    plan: SubscriptionPlanResponse

    class Config:
        from_attributes = True


class SubscriptionWithPlanDetails(SubscriptionResponse):
    """Subscription response with full plan details"""
    pass


from typing import Any

# 1. This handles the subscription database conversion cleanly
class SubscriptionPayloadResponse(SubscriptionBase):
    id: int
    stripe_subscription_id: Optional[str] = None
    stripe_customer_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

# 2. This matches your composite controller return dictionary
class SubscriptionAuthWrapperResponse(BaseModel):
    subscription: SubscriptionPayloadResponse
    access_token: str
    token_type: str
    user: Any  # Replace with your User response schema if preferred