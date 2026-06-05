from typing import TYPE_CHECKING, Optional, List
from datetime import datetime
from sqlalchemy import String, ForeignKey, func, Float
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.wallet import Wallet
from .base import Base

if TYPE_CHECKING:
    from .user import User 

class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    subdomain: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    industry: Mapped[str] = mapped_column(String(50))
    capped_tokens: Mapped[Optional[int]] = mapped_column() 

    stripe_connect_id: Mapped[Optional[str]] = mapped_column(String(100))
    stripe_charges_enabled: Mapped[bool] = mapped_column(default=False)
    stripe_payouts_enabled: Mapped[bool] = mapped_column(default=False)
    stripe_details_submitted: Mapped[bool] = mapped_column(default=False)
    is_verified: Mapped[bool] = mapped_column(default=False)
    
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    owner: Mapped["User"] = relationship(
        "User",
        back_populates="owned_organization",
        foreign_keys=[owner_id],
    )
    members: Mapped[List["User"]] = relationship(
        "User",
        back_populates="organization",
        foreign_keys="[User.organization_id]",
        lazy="selectin",
    )

    # One-to-one link to their financial wallet
    wallet: Mapped["Wallet"] = relationship(
        "Wallet",
        back_populates="organization",
        foreign_keys="[Wallet.organization_id]",
        uselist=False,
    )

    # ============ BRANDING SETTINGS ============
    brand_color: Mapped[str] = mapped_column(String(7), default="#10B981")  # Hex color code
    
    # ============ VISIBILITY SETTINGS ============
    show_leaderboard: Mapped[bool] = mapped_column(default=True)
    show_final_podium: Mapped[bool] = mapped_column(default=True)
    engagement_overlays: Mapped[bool] = mapped_column(default=True)
    is_public: Mapped[bool] = mapped_column(default=False)
    timer_enabled: Mapped[bool] = mapped_column(default=True)
    waiting_lobby: Mapped[bool] = mapped_column(default=True)
    
    # ============ ARENA SETTINGS ============
    use_ai_for_arenas: Mapped[bool] = mapped_column(default=True)
    
    
    # ============ PAYOUT SETTINGS ============
    enable_payouts: Mapped[bool] = mapped_column(default=False)
    request_payout_details: Mapped[bool] = mapped_column(default=True)
    payout_method: Mapped[str] = mapped_column(String(20), default="stripe")  # "stripe" or "bank"
    
    # Relationship to payout rules
    payout_rules: Mapped[List["PayoutRule"]] = relationship(
        back_populates="organization", 
        cascade="all, delete-orphan",
        lazy="selectin"
    )

    created_at: Mapped[datetime] = mapped_column(insert_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(insert_default=func.now(), onupdate=func.now())


class PayoutRule(Base):
    __tablename__ = "payout_rules"

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"))
    
    position: Mapped[str] = mapped_column(String(50))  # "1st", "2nd", "3rd", "top_5", etc.
    amount: Mapped[float] = mapped_column(Float)  # Amount in dollars
    currency: Mapped[str] = mapped_column(String(3), default="usd")  # "usd" or "gbp"  

    stripe_product_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    stripe_price_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    stripe_transfer_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    
    organization: Mapped["Organization"] = relationship(back_populates="payout_rules")
    
    created_at: Mapped[datetime] = mapped_column(insert_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(insert_default=func.now(), onupdate=func.now())