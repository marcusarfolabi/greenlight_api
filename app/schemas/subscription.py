from datetime import datetime
from enum import Enum

from pydantic import BaseModel


class CreatePaymentIntentRequest(BaseModel):
    organization_id: int
    plan_id: int


class CreatePaymentIntentResponse(BaseModel):
    client_secret: str
    payment_intent_id: str
    amount: float
    currency: str


class ConfirmPaymentRequest(BaseModel):
    organization_id: int
    plan_id: int
    payment_intent_id: str


class BuyTokensRequest(BaseModel):
    token_amount: int  # Number of tokens to buy


class BuyTokensResponse(BaseModel):
    success: bool
    message: str
    tokens_purchased: int
    total_tokens: int
    wallet_balance_remaining: int
    cost_charged: float
    currency: str


class TokenPurchaseQuoteResponse(BaseModel):
    token_amount: int
    cost: float
    currency: str


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
    max_players: int | None = None
    max_arenas: int | None = None
    max_custom_themes: int | None = None
    api_access: bool = False
    analytics: bool = False
    white_label: bool = False
    priority_support: bool = False
    ai_tokens: int = 0


class SubscriptionPlanCreate(SubscriptionPlanBase):
    plan_type: SubscriptionPlanTypeSchema
    stripe_product_id: str | None = None
    stripe_price_id: str | None = None
    display_order: int = 0
    ai_tokens: int = 0


class SubscriptionPlanUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    price: float | None = None
    max_players: int | None = None
    max_arenas: int | None = None
    api_access: bool | None = None
    analytics: bool | None = None
    white_label: bool | None = None
    priority_support: bool | None = None
    ai_tokens: int | None = None
    is_active: bool | None = None


class SubscriptionPlanResponse(SubscriptionPlanBase):
    id: int
    plan_type: SubscriptionPlanTypeSchema
    stripe_product_id: str | None = None
    stripe_price_id: str | None = None
    converted_price: float | None = None
    converted_currency: str | None = None
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
    stripe_subscription_id: str | None = None
    stripe_customer_id: str | None = None


class SubscriptionResponse(SubscriptionBase):
    id: int
    stripe_subscription_id: str | None = None
    stripe_customer_id: str | None = None
    started_at: datetime
    canceled_at: datetime | None = None
    current_period_start: datetime | None = None
    current_period_end: datetime | None = None
    created_at: datetime
    updated_at: datetime
    plan: SubscriptionPlanResponse

    class Config:
        from_attributes = True


class SubscriptionWithPlanDetails(SubscriptionResponse):
    """Subscription response with full plan details"""


from typing import Any


# 1. This handles the subscription database conversion cleanly
class SubscriptionPayloadResponse(SubscriptionBase):
    id: int
    stripe_subscription_id: str | None = None
    stripe_customer_id: str | None = None
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
