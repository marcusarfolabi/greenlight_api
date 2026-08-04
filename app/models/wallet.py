import enum
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Enum, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base

if TYPE_CHECKING:
    from .organization import Organization
    from .user import User


class TransactionType(enum.Enum):
    DEPOSIT = "deposit"  # Host funding the wallet
    PRIZE_PAYOUT = "payout"  # Money leaving to a winner
    REFUND = "refund"  # Canceled game refund
    PLATFORM_FEE = "fee"  # Your cut of the game
    SUBSCRIPTION = "subscription"  # Your cut of the game


class Wallet(Base):
    __tablename__ = "wallets"

    id: Mapped[int] = mapped_column(primary_key=True)

    # Linked to either an Organization (Host) or a User (Winner)
    # This allows both to have "Balances"
    organization_id: Mapped[int | None] = mapped_column(
        ForeignKey("organizations.id"), unique=True
    )
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), unique=True)

    balance: Mapped[int] = mapped_column(Integer, default=0)
    pending_balance: Mapped[int] = mapped_column(Integer, default=0)
    currency: Mapped[str] = mapped_column(String(3), default="gbp")

    transactions: Mapped[list["Transaction"]] = relationship(
        back_populates="wallet", cascade="all, delete-orphan"
    )
    organization: Mapped[Optional["Organization"]] = relationship(
        "Organization",
        back_populates="wallet",
        foreign_keys="[Wallet.organization_id]",
    )
    user: Mapped[Optional["User"]] = relationship(
        "User",
        back_populates="wallet",
        foreign_keys="[Wallet.user_id]",
    )


class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(primary_key=True)
    wallet_id: Mapped[int] = mapped_column(ForeignKey("wallets.id"))

    amount: Mapped[int] = mapped_column()  # Negative for payouts, positive for deposits
    type: Mapped[TransactionType] = mapped_column(Enum(TransactionType))

    # Stripe reference so you can find the payment later
    stripe_reference: Mapped[str | None] = mapped_column(String(100))

    status: Mapped[str] = mapped_column(
        String(20), default="pending"
    )  # pending, completed, failed
    # Context (e.g., "Winner of Quiz #402")
    description: Mapped[str | None] = mapped_column(String(255))

    created_at: Mapped[datetime] = mapped_column(insert_default=func.now())

    wallet: Mapped["Wallet"] = relationship(back_populates="transactions")
