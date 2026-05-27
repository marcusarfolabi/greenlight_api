import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.subscription import SubscriptionPlan, Subscription
from app.schemas.subscription import (
    SubscriptionPlanResponse,
    SubscriptionResponse,
    SubscriptionCreate,
)

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/plans", response_model=list[SubscriptionPlanResponse])
async def get_all_plans(db: Session = Depends(get_db)):
    """Get all available subscription plans"""
    plans = db.query(SubscriptionPlan).filter(
        SubscriptionPlan.is_active == True
    ).order_by(SubscriptionPlan.display_order).all()
    return plans


@router.get("/plans/{plan_id}", response_model=SubscriptionPlanResponse)
async def get_plan(plan_id: int, db: Session = Depends(get_db)):
    """Get a specific subscription plan by ID"""
    plan = db.query(SubscriptionPlan).filter(
        SubscriptionPlan.id == plan_id
    ).first()
    
    if not plan:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Subscription plan not found"
        )
    
    return plan


@router.get("/organization/{organization_id}", response_model=SubscriptionResponse)
async def get_organization_subscription(
    organization_id: int,
    db: Session = Depends(get_db)
):
    """Get the current subscription for an organization"""
    subscription = db.query(Subscription).filter(
        Subscription.organization_id == organization_id,
        Subscription.status == "active"
    ).first()
    
    if not subscription:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active subscription found for this organization"
        )
    
    return subscription


@router.post("/", response_model=SubscriptionResponse)
async def create_subscription(
    subscription_data: SubscriptionCreate,
    db: Session = Depends(get_db)
):
    """Create a new subscription for an organization"""
    
    # Verify plan exists
    plan = db.query(SubscriptionPlan).filter(
        SubscriptionPlan.id == subscription_data.plan_id
    ).first()
    
    if not plan:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Subscription plan not found"
        )
    
    # Cancel any existing active subscriptions
    existing = db.query(Subscription).filter(
        Subscription.organization_id == subscription_data.organization_id,
        Subscription.status == "active"
    ).first()
    
    if existing:
        existing.status = "canceled"
    
    # Create new subscription
    subscription = Subscription(
        organization_id=subscription_data.organization_id,
        plan_id=subscription_data.plan_id,
        stripe_subscription_id=subscription_data.stripe_subscription_id,
        stripe_customer_id=subscription_data.stripe_customer_id,
        status=subscription_data.status
    )
    
    db.add(subscription)
    db.commit()
    db.refresh(subscription)
    
    return subscription
