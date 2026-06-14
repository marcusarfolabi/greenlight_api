import logging
from datetime import datetime, timedelta
from typing import Optional
from pydantic import BaseModel

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.orm import Session
import stripe  # type: ignore

from app.db.session import get_db
from app.core.config import settings
from app.models.subscription import SubscriptionPlan, Subscription
from app.models.organization import Organization
from app.schemas.subscription import (
    ConfirmPaymentRequest,
    CreatePaymentIntentRequest,
    SubscriptionPlanResponse,
    SubscriptionResponse,
    SubscriptionCreate,
)
from app.core.security import get_current_user
from app.schemas.user import AuthContext
from app.services.subscription_service import SubscriptionService


router = APIRouter()

logging.basicConfig(level=logging.INFO)
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


@router.get("/organization", response_model=SubscriptionResponse)
async def get_organization_subscription( 
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_current_user),
    
):
    """Get the current subscription for an organization"""
    subscription = db.query(Subscription).filter(
        Subscription.organization_id == auth.org_id,
        Subscription.status == "active"
    ).first()
    
    if not subscription:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active subscription found for this organization"
        )
    
    return subscription


@router.post("", response_model=SubscriptionResponse)
async def create_subscription(
    subscription_data: SubscriptionCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_current_user)
):
    """Create a new subscription for an organization"""
    
    # Verify user has a valid organization
    if not auth.org_id or auth.org_id == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User must belong to an organization to create a subscription"
        )
    
    # Verify plan exists
    plan = db.query(SubscriptionPlan).filter(
        SubscriptionPlan.id == subscription_data.plan_id
    ).first()
    
    if not plan:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Subscription plan not found"
        )
    
    # Create subscription using service (handles token allocation)
    subscription = SubscriptionService.create_subscription(
        db=db,
        organization_id=auth.org_id,
        plan_id=subscription_data.plan_id,
        stripe_subscription_id=subscription_data.stripe_subscription_id,
        stripe_customer_id=subscription_data.stripe_customer_id,
        background_tasks=background_tasks,
    )
    
    return subscription


@router.post("/payment-intent")
async def create_payment_intent(
    request: CreatePaymentIntentRequest,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_current_user)
):
    """Create a Stripe Payment Intent for embedded payment element"""
    
    # Verify user has a valid organization
    if not auth.org_id or auth.org_id == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User must belong to an organization to create a payment intent"
        )
    
    # Verify plan exists
    plan = db.query(SubscriptionPlan).filter(
        SubscriptionPlan.id == request.plan_id,
        SubscriptionPlan.is_active == True
    ).first()
    
    if not plan:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Subscription plan not found or inactive"
        )
    
    # Free plan should use direct subscription
    if plan.price == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Use the subscription endpoint for free plans"
        )
    
    # Verify organization exists
    organization = db.query(Organization).filter(
        Organization.id == auth.org_id
    ).first()
    
    if not organization:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found"
        )
    
    if not settings.STRIPE_SECRET_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Stripe is not configured"
        )
    
    stripe.api_key = settings.STRIPE_SECRET_KEY
    
    try:
        # Check if organization already has a Stripe customer
        existing_subscription = db.query(Subscription).filter(
            Subscription.organization_id == auth.org_id
        ).first()
        
        if existing_subscription and existing_subscription.stripe_customer_id:
            stripe_customer_id = existing_subscription.stripe_customer_id
        else:
            # Create new customer
            customer = stripe.Customer.create(
                name=organization.name,
                metadata={
                    "organization_id": str(auth.org_id),
                }
            )
            stripe_customer_id = customer.id
        
        # Amount in cents
        amount = int(plan.price * 100)
        
        # Create Payment Intent
        payment_intent = stripe.PaymentIntent.create(
            amount=amount,
            currency=plan.currency,
            customer=stripe_customer_id,
            automatic_payment_methods={"enabled": True},
            metadata={
                "organization_id": str(auth.org_id),
                "plan_id": str(request.plan_id),
            },
        )
        
        return {
            "client_secret": payment_intent.client_secret,
            "payment_intent_id": payment_intent.id,
        }
    
    except Exception as e:
        logger.error(f"Stripe error creating payment intent: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to create payment intent: {str(e)}"
        )


@router.post("/confirm-payment")
async def confirm_payment(
    request: ConfirmPaymentRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_current_user)
):
    """Confirm payment and create subscription after successful payment"""
    
    # Verify plan exists
    plan = db.query(SubscriptionPlan).filter(
        SubscriptionPlan.id == request.plan_id
    ).first()
    
    if not plan:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Subscription plan not found"
        )
    
    # Verify organization exists
    organization = db.query(Organization).filter(
        Organization.id == auth.org_id
    ).first()
    
    if not organization:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found"
        )
    
    if not settings.STRIPE_SECRET_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Stripe is not configured"
        )
    
    stripe.api_key = settings.STRIPE_SECRET_KEY
    
    try:
        payment_intent = stripe.PaymentIntent.retrieve(request.payment_intent_id)

        if payment_intent.status != "succeeded":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Payment not completed. Status: {payment_intent.status}"
            )
        
        stripe_customer_id = str(payment_intent.customer) if payment_intent.customer else None
        
        # Create subscription using service (handles token allocation and canceling old subscriptions)
        subscription = SubscriptionService.create_subscription(
            db=db,
            organization_id=auth.org_id,
            plan_id=request.plan_id,
            stripe_subscription_id=payment_intent.id,
            stripe_customer_id=stripe_customer_id,
            background_tasks=background_tasks,
        )
        
        logger.info(f"Subscription created for org {auth.org_id} on plan {request.plan_id}")
        
        return {
            "success": True,
            "message": "Subscription activated successfully",
            "subscription_id": subscription.id
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error confirming payment: {str(e)}")
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create subscription"
        )
