import logging
from datetime import datetime, timedelta
from typing import Optional

from fastapi import BackgroundTasks
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.arena import Arena, ArenaTokenUsageLog
from app.models.organization import Organization
from app.models.subscription import Subscription, SubscriptionPlan
from app.models.wallet import Transaction, TransactionType, Wallet
from app.services.mail_service import mail_service
from app.services.organization import OrganizationService

logger = logging.getLogger(__name__)


class SubscriptionService:
    """Service for managing subscription operations including token allocation"""

    @staticmethod
    def create_subscription(
        db: Session,
        organization_id: int,
        plan_id: int,
        stripe_subscription_id: Optional[str] = None,
        stripe_customer_id: Optional[str] = None,
        period_start: Optional[datetime] = None,
        period_end: Optional[datetime] = None,
        background_tasks: Optional[BackgroundTasks] = None,
    ) -> Subscription:
        """
        Create a subscription for an organization and allocate AI tokens.

        Args:
            db: Database session
            organization_id: Organization ID
            plan_id: Subscription plan ID
            stripe_subscription_id: Optional Stripe subscription ID
            stripe_customer_id: Optional Stripe customer ID
            period_start: Start date of the subscription period
            period_end: End date of the subscription period

        Returns:
            The created Subscription object
        """
        plan = db.query(SubscriptionPlan).filter(SubscriptionPlan.id == plan_id).first()

        if not plan:
            raise ValueError(f"Subscription plan {plan_id} not found")

        # Get the organization
        organization = (
            db.query(Organization).filter(Organization.id == organization_id).first()
        )

        if not organization:
            raise ValueError(f"Organization {organization_id} not found")

        if period_start is None:
            period_start = datetime.utcnow()
        if period_end is None:
            if plan.interval == "year":
                period_end = period_start + timedelta(days=365)
            else:
                period_end = period_start + timedelta(days=30)

        existing = (
            db.query(Subscription)
            .filter(
                Subscription.organization_id == organization_id,
                Subscription.status == "active",
            )
            .first()
        )

        if existing:
            existing.status = "canceled"
            existing.canceled_at = period_start
            logger.info(
                f"Canceled existing subscription {existing.id} for org {organization_id}"
            )

        organization.capped_tokens = (organization.capped_tokens or 0) + plan.ai_tokens
        organization.is_verified = True
        db.add(organization)
        db.commit()
        db.refresh(organization)

        logger.info(
            f"Added {plan.ai_tokens} tokens to organization {organization_id} (total: {organization.capped_tokens})"
        )

        # Create the new subscription
        subscription = Subscription(
            organization_id=organization_id,
            plan_id=plan_id,
            stripe_subscription_id=stripe_subscription_id,
            stripe_customer_id=stripe_customer_id,
            status="active",
            current_period_start=period_start,
            current_period_end=period_end,
        )

        wallet = OrganizationService.get_or_create_wallet(db, organization_id)

        transaction = Transaction(
            wallet_id=wallet.id if wallet else None,
            amount=-int(plan.price * 100),
            type=TransactionType.SUBSCRIPTION,
            stripe_reference=stripe_subscription_id,
            status="completed",
            description=f"{plan.name} subscription",
        )

        db.add(subscription)
        db.add(transaction)
        db.commit()
        db.refresh(subscription)

        if background_tasks:
            owner = organization.owner
            if owner and owner.email:
                owner_name = owner.first_name or owner.username or "there"
                background_tasks.add_task(
                    mail_service.send_subscription_message,
                    email=owner.email,
                    name=owner_name,
                    org_name=organization.name,
                    plan_details={
                        "plan_name": plan.name,
                        "plan_description": plan.description,
                        "plan_price": f"{plan.price:.2f}",
                        "currency": wallet.currency.upper(),
                        "interval": plan.interval,
                        "ai_tokens": plan.ai_tokens,
                        "max_players": plan.max_players,
                        "max_arenas": plan.max_arenas,
                        "max_custom_themes": plan.max_custom_themes,
                        "api_access": plan.api_access,
                        "analytics": plan.analytics,
                        "white_label": plan.white_label,
                        "priority_support": plan.priority_support,
                        "period_end": period_end.strftime("%B %d, %Y")
                        if period_end
                        else None,
                    },
                )

        logger.info(
            f"Created subscription {subscription.id} for org {organization_id} "
            f"on plan {plan_id} ({plan.name}) with {plan.ai_tokens} AI tokens"
        )

        return subscription

    @staticmethod
    def get_organization_tokens(db: Session, organization_id: int) -> dict:
        """
        Get token information for an organization.

        Args:
            db: Database session
            organization_id: Organization ID

        Returns:
            Dictionary with token usage info
        """
        organization = (
            db.query(Organization).filter(Organization.id == organization_id).first()
        )

        if not organization:
            raise ValueError(f"Organization {organization_id} not found")

        subscription = (
            db.query(Subscription)
            .filter(
                Subscription.organization_id == organization_id,
                Subscription.status == "active",
            )
            .first()
        )

        if not subscription:
            return {
                "total_tokens": 0,
                "used_tokens": 0,
                "remaining_tokens": 0,
                "plan_name": "None",
                "plan_type": "None",
                "has_tokens": False,
            }

        # Get token usage from arenas and preview logs

        total_used_in_arenas = (
            db.query(Arena)
            .filter(Arena.creator_organization_id == organization_id)
            .with_entities(func.sum(Arena.ai_tokens_used).label("total"))
            .scalar()
            or 0
        )

        preview_used = (
            db.query(func.coalesce(func.sum(ArenaTokenUsageLog.tokens_used), 0))
            .filter(
                ArenaTokenUsageLog.organization_id == organization_id,
                ArenaTokenUsageLog.operation == "ai_question_generation_preview",
            )
            .scalar()
            or 0
        )

        total_used = total_used_in_arenas + preview_used
        remaining = subscription.plan.ai_tokens - total_used

        return {
            "total_tokens": subscription.plan.ai_tokens,
            "used_tokens": total_used,
            "remaining_tokens": max(0, remaining),
            "plan_name": subscription.plan.name,
            "plan_type": subscription.plan.plan_type,
            "has_tokens": remaining > 0,
        }

    @staticmethod
    def buy_tokens_from_wallet(
        db: Session,
        organization_id: int,
        token_amount: int,
        background_tasks: Optional[BackgroundTasks] = None,
    ) -> dict:
        """
        Buy AI tokens from wallet balance.

        Pricing: 10000 tokens = £2.00 (or equivalent in currency)

        Args:
            db: Database session
            organization_id: Organization ID
            token_amount: Number of tokens to purchase
            background_tasks: Optional background tasks for email

        Returns:
            Dictionary with purchase details

        Raises:
            ValueError: If insufficient balance or organization not found
        """
        # Get organization
        organization = (
            db.query(Organization).filter(Organization.id == organization_id).first()
        )

        if not organization:
            raise ValueError(f"Organization {organization_id} not found")

        # Get wallet
        wallet = (
            db.query(Wallet).filter(Wallet.organization_id == organization_id).first()
        )

        if not wallet:
            raise ValueError(f"Wallet for organization {organization_id} not found")

        # Calculate cost: 10000 tokens = 200 cents (£2.00)
        # So 1 token = 0.02 cents = 0.0002 pounds
        cost_in_cents = int((token_amount / 10000) * 200)

        if wallet.balance < cost_in_cents:
            raise ValueError(
                f"Insufficient wallet balance. Required: {cost_in_cents / 100:.2f}, "
                f"Available: {wallet.balance / 100:.2f}"
            )

        # Deduct from wallet
        wallet.balance -= cost_in_cents
        db.add(wallet)

        # Add tokens to organization
        organization.capped_tokens = (organization.capped_tokens or 0) + token_amount
        db.add(organization)

        # Create transaction record
        transaction = Transaction(
            wallet_id=wallet.id,
            amount=-cost_in_cents,
            type=TransactionType.SUBSCRIPTION,
            status="completed",
            description=f"Token purchase: {token_amount} tokens",
        )
        db.add(transaction)

        db.commit()

        logger.info(
            f"Organization {organization_id} purchased {token_amount} tokens "
            f"for {cost_in_cents / 100:.2f} {wallet.currency.upper()}"
        )

        # Send confirmation email
        if background_tasks:
            owner = organization.owner
            if owner and owner.email:
                owner_name = owner.first_name or owner.username or "there"
                background_tasks.add_task(
                    mail_service.send_token_purchase_confirmation,
                    email=owner.email,
                    name=owner_name,
                    org_name=organization.name,
                    tokens_purchased=token_amount,
                    cost=cost_in_cents / 100,
                    currency=wallet.currency.upper(),
                    total_tokens=organization.capped_tokens or 0,
                )

        return {
            "success": True,
            "tokens_purchased": token_amount,
            "total_tokens": organization.capped_tokens or 0,
            "wallet_balance_remaining": wallet.balance,
            "currency": wallet.currency,
        }
