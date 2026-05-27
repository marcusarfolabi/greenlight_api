from typing import List, Optional, TYPE_CHECKING
from datetime import datetime
import enum
from sqlalchemy import String, ForeignKey, Integer, Enum, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .base import Base

if TYPE_CHECKING:
    from .user import User
    from .organization import Organization

class TransactionType(enum.Enum):
    DEPOSIT = "deposit"     # Host funding the wallet
    PRIZE_PAYOUT = "payout" # Money leaving to a winner
    REFUND = "refund"       # Canceled game refund
    PLATFORM_FEE = "fee"    # Your cut of the game
    SUBSCRIPTION = "subscription"    # Your cut of the game

class Wallet(Base):
    __tablename__ = "wallets"

    id: Mapped[int] = mapped_column(primary_key=True)
    
    # Linked to either an Organization (Host) or a User (Winner)
    # This allows both to have "Balances"
    organization_id: Mapped[Optional[int]] = mapped_column(ForeignKey("organizations.id"), unique=True)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), unique=True)
    
    balance: Mapped[int] = mapped_column(Integer, default=0) # Stored in cents (e.g. 1000 = $10.00)
    currency: Mapped[str] = mapped_column(String(3), default="usd")

    transactions: Mapped[List["Transaction"]] = relationship(back_populates="wallet", cascade="all, delete-orphan")
    organization: Mapped["Organization"] = relationship(back_populates="wallet")
    user: Mapped[Optional["User"]] = relationship(back_populates="wallet")
    
class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(primary_key=True)
    wallet_id: Mapped[int] = mapped_column(ForeignKey("wallets.id"))
    
    amount: Mapped[int] = mapped_column() # Negative for payouts, positive for deposits
    type: Mapped[TransactionType] = mapped_column(Enum(TransactionType))
    
    # Stripe reference so you can find the payment later
    stripe_reference: Mapped[Optional[str]] = mapped_column(String(100))
    
    status: Mapped[str] = mapped_column(String(20), default="pending") # pending, completed, failed
    # Context (e.g., "Winner of Quiz #402")
    description: Mapped[Optional[str]] = mapped_column(String(255))
    
    created_at: Mapped[datetime] = mapped_column(insert_default=func.now())

    wallet: Mapped["Wallet"] = relationship(back_populates="transactions")