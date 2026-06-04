from typing import List, Optional, TYPE_CHECKING
from datetime import datetime
import enum
from sqlalchemy import String, Enum, func, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.wallet import Wallet
from .base import Base

if TYPE_CHECKING:
    from .organization import Organization 

class UserRole(enum.Enum):
    USER = "user"
    HOST = "host"
    SUPERADMIN = "superadmin"

class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255))
    first_name: Mapped[Optional[str]] = mapped_column(String(255))
    last_name: Mapped[Optional[str]] = mapped_column(String(255))
    
    role: Mapped[str] = mapped_column(String(50), default="user")    
    is_active: Mapped[bool] = mapped_column(default=False)
    email_verified_at: Mapped[datetime] = mapped_column(insert_default=func.now())
    created_at: Mapped[datetime] = mapped_column(insert_default=func.now())
    
    organization_id: Mapped[Optional[int]] = mapped_column(ForeignKey("organizations.id"), nullable=True)

    # Relationships
    owned_organization: Mapped[Optional["Organization"]] = relationship(
        "Organization",
        back_populates="owner",
        foreign_keys="[Organization.owner_id]",
        uselist=False,
    )
    organization: Mapped[Optional["Organization"]] = relationship(
        "Organization",
        back_populates="members",
        foreign_keys="[User.organization_id]",
    )
    payout_profile: Mapped[Optional["PayoutProfile"]] = relationship(back_populates="user", uselist=False)
    wallet: Mapped[Optional["Wallet"]] = relationship(
        "Wallet",
        back_populates="user",
        foreign_keys=[Wallet.user_id],
        uselist=False,
    )

class PayoutProfile(Base):
    __tablename__ = "payout_profiles"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True)
    
    bank_name: Mapped[str] = mapped_column(String(100))
    account_holder_name: Mapped[str] = mapped_column(String(100))
    account_number: Mapped[str] = mapped_column(String(50))
    sort_code: Mapped[Optional[str]] = mapped_column(String(20))
    iban: Mapped[Optional[str]] = mapped_column(String(50))
    
    user: Mapped["User"] = relationship(back_populates="payout_profile")