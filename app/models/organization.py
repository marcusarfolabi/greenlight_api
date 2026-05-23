from typing import TYPE_CHECKING, Optional, List
from datetime import datetime
from sqlalchemy import String, ForeignKey, func, Integer
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

    stripe_connect_id: Mapped[Optional[str]] = mapped_column(String(100))
    is_verified: Mapped[bool] = mapped_column(default=False)
    
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    owner: Mapped["User"] = relationship(back_populates="owned_organization")
    
    
    # One-to-one link to their financial wallet
    wallet: Mapped["Wallet"] = relationship(back_populates="organization", uselist=False)

    created_at: Mapped[datetime] = mapped_column(insert_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(insert_default=func.now(), onupdate=func.now())