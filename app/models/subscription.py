from typing import TYPE_CHECKING, Optional, List
from datetime import datetime
from sqlalchemy import String, ForeignKey, func, Float, Enum
from sqlalchemy.orm import Mapped, mapped_column, relationship
import enum

from .base import Base

if TYPE_CHECKING:
    from .organization import Organization


class SubscriptionPlanType(str, enum.Enum):
    FREE = "free"
    STANDARD = "standard"
    PRO = "pro"


class SubscriptionPlan(Base):
    """Represents a subscription plan tier (Free, Standard, Pro)"""
    __tablename__ = "subscription_plans"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    plan_type: Mapped[SubscriptionPlanType] = mapped_column(Enum(SubscriptionPlanType))
    description: Mapped[str] = mapped_column(String(500), default="")
    
    # Pricing
    price: Mapped[float] = mapped_column(Float)  # Price in dollars
    currency: Mapped[str] = mapped_column(String(3), default="gbp")  # "usd", "eur", "gbp", etc.
    interval: Mapped[str] = mapped_column(String(20), default="month")  # "month" or "year"
    
    # Stripe integration
    stripe_product_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    stripe_price_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    
    # Features - stored as JSON or individual columns
    max_players: Mapped[Optional[int]] = mapped_column(nullable=True)  # None = unlimited
    max_arenas: Mapped[Optional[int]] = mapped_column(nullable=True)
    max_custom_themes: Mapped[Optional[int]] = mapped_column(nullable=True)
    api_access: Mapped[bool] = mapped_column(default=False)
    analytics: Mapped[bool] = mapped_column(default=False)
    white_label: Mapped[bool] = mapped_column(default=False)
    priority_support: Mapped[bool] = mapped_column(default=False)
    
    # AI Features
    ai_tokens: Mapped[int] = mapped_column(default=0)  # Monthly AI tokens for question generation, etc.
    
    # Status
    is_active: Mapped[bool] = mapped_column(default=True)
    display_order: Mapped[int] = mapped_column(default=0)  # For sorting plans
    
    created_at: Mapped[datetime] = mapped_column(insert_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(insert_default=func.now(), onupdate=func.now())


class Subscription(Base):
    """Represents an active subscription for an organization"""
    __tablename__ = "subscriptions"

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"))
    plan_id: Mapped[int] = mapped_column(ForeignKey("subscription_plans.id"))
    
    # Stripe subscription details
    stripe_subscription_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    stripe_customer_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    
    # Status
    status: Mapped[str] = mapped_column(String(20), default="active")  # "active", "canceled", "past_due"
    
    # Dates
    started_at: Mapped[datetime] = mapped_column(insert_default=func.now())
    canceled_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    current_period_start: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    current_period_end: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    
    plan: Mapped["SubscriptionPlan"] = relationship()
    
    created_at: Mapped[datetime] = mapped_column(insert_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(insert_default=func.now(), onupdate=func.now())
