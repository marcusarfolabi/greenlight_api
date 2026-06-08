import logging
from datetime import datetime, timedelta
from typing import Optional
from sqlalchemy.orm import Session

from app.models.subscription import Subscription, SubscriptionPlan
from app.models.organization import Organization

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
        # Get the plan to retrieve ai_tokens
        plan = db.query(SubscriptionPlan).filter(
            SubscriptionPlan.id == plan_id
        ).first()
        
        if not plan:
            raise ValueError(f"Subscription plan {plan_id} not found")
        
        # Get the organization
        organization = db.query(Organization).filter(
            Organization.id == organization_id
        ).first()
        
        if not organization:
            raise ValueError(f"Organization {organization_id} not found")
        
        # Set default period dates if not provided
        if period_start is None:
            period_start = datetime.utcnow()
        if period_end is None:
            if plan.interval == "year":
                period_end = period_start + timedelta(days=365)
            else:
                period_end = period_start + timedelta(days=30)
        
        # Cancel any existing active subscriptions
        existing = db.query(Subscription).filter(
            Subscription.organization_id == organization_id,
            Subscription.status == "active"
        ).first()
        
        if existing:
            existing.status = "canceled"
            existing.canceled_at = period_start
            logger.info(f"Canceled existing subscription {existing.id} for org {organization_id}")
        
        # Allocate AI tokens from the plan to the organization (add to existing)
        organization.capped_tokens = (organization.capped_tokens or 0) + plan.ai_tokens
        logger.info(f"Added {plan.ai_tokens} tokens to organization {organization_id} (total: {organization.capped_tokens})")
        
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
        
        db.add(subscription)
        db.commit()
        db.refresh(subscription)
        
        logger.info(
            f"Created subscription {subscription.id} for org {organization_id} "
            f"on plan {plan_id} ({plan.name}) with {plan.ai_tokens} AI tokens"
        )
        
        return subscription

    @staticmethod
    def get_organization_tokens(
        db: Session,
        organization_id: int
    ) -> dict:
        """
        Get token information for an organization.
        
        Args:
            db: Database session
            organization_id: Organization ID
            
        Returns:
            Dictionary with token usage info
        """
        organization = db.query(Organization).filter(
            Organization.id == organization_id
        ).first()
        
        if not organization:
            raise ValueError(f"Organization {organization_id} not found")
        
        subscription = db.query(Subscription).filter(
            Subscription.organization_id == organization_id,
            Subscription.status == "active"
        ).first()
        
        if not subscription:
            return {
                "total_tokens": 0,
                "used_tokens": 0,
                "remaining_tokens": 0,
                "plan_name": "None",
                "plan_type": "None",
                "has_tokens": False
            }
        
        # Get token usage from arenas and preview logs
        from app.models.arena import Arena, ArenaTokenUsageLog
        from sqlalchemy import func
        
        total_used_in_arenas = db.query(Arena).filter(
            Arena.creator_organization_id == organization_id
        ).with_entities(
            func.sum(Arena.ai_tokens_used).label("total")
        ).scalar() or 0
        
        preview_used = db.query(func.coalesce(func.sum(ArenaTokenUsageLog.tokens_used), 0)).filter(
            ArenaTokenUsageLog.organization_id == organization_id,
            ArenaTokenUsageLog.operation == "ai_question_generation_preview"
        ).scalar() or 0
        
        total_used = total_used_in_arenas + preview_used
        remaining = subscription.plan.ai_tokens - total_used
        
        return {
            "total_tokens": subscription.plan.ai_tokens,
            "used_tokens": total_used,
            "remaining_tokens": max(0, remaining),
            "plan_name": subscription.plan.name,
            "plan_type": subscription.plan.plan_type,
            "has_tokens": remaining > 0
        }
