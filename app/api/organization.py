import logging
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.core.security import get_current_user  

from app.schemas.organization import (
    OrganizationCreate, OrganizationResponse, 
    OrgSettingsUpdate, OrgSettingsResponse, OrgSettingsSaveResponse,
    PayoutRuleCreate, PayoutRuleResponse,
    WalletSummaryResponse,
)
from app.services.stripe_connect import StripeConnectService
from app.models.user import UserRole
from app.models.organization import PayoutRule
from app.services.user_service import UserService           
from app.services.organization import OrganizationService
from app.schemas.user import AuthContext 


router = APIRouter()
logger = logging.getLogger(__name__) 

@router.post("", response_model=OrganizationResponse)
async def setup_user_organization(
    org_data: OrganizationCreate, 
    db: Session = Depends(get_db), 
    auth: AuthContext = Depends(get_current_user)
):
    user_id = auth.user_id
    
    user = UserService.get_user(db, user_id=user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User account not found."
        )
    # print it role
    if auth.role != UserRole.HOST.value:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only accounts configured with a HOST role can construct workspace domains."
        )

    if OrganizationService.get_by_subdomain(db, org_data.subdomain):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Organization workspace subdomain already taken",
        )

    new_org = OrganizationService.create_organization_for_user(
        db=db, 
        user_id=auth.user_id, 
        org_data=org_data
    )
    
    return new_org

@router.get("/wallet", response_model=WalletSummaryResponse)
async def get_organization_wallet(
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_current_user),
):
    """Retrieve wallet balance, summary stats, and recent transactions."""
    org = OrganizationService.get_by_owner(db, auth.user_id)
    if not org:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found",
        )

    return OrganizationService.get_wallet_summary(db, org)


@router.get("/settings", response_model=OrgSettingsResponse)
async def get_organization_settings(
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_current_user)
):
    """Retrieve all organization settings (branding, visibility, payouts)"""
    org = OrganizationService.get_by_owner(db, auth.user_id)
    if not org:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found"
        )

    if org.stripe_connect_id:
        StripeConnectService.sync_account_status(db, org)

    return OrganizationService.build_settings_response(org)


@router.put("/settings", response_model=OrgSettingsSaveResponse)
async def update_organization_settings(
    settings_data: OrgSettingsUpdate,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_current_user)
):
    """Update organization settings (branding, visibility, payouts)"""
    org = OrganizationService.get_by_owner(db, auth.user_id)
    if not org:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found"
        )

    stripe_onboarding_url = None

    # Update branding settings
    if settings_data.branding:
        org.brand_color = settings_data.branding.brand_color

    # Update visibility settings
    if settings_data.visibility:
        org.show_leaderboard = settings_data.visibility.show_leaderboard
        org.show_final_podium = settings_data.visibility.show_final_podium
        org.engagement_overlays = settings_data.visibility.engagement_overlays
        org.is_public = settings_data.visibility.is_public
        org.timer_enabled = settings_data.visibility.timer_enabled
        org.waiting_lobby = settings_data.visibility.waiting_lobby

    # Update arena settings
    if settings_data.arena:
        org.use_ai_for_arenas = settings_data.arena.use_ai_for_arenas

    # Update payout settings
    if settings_data.payouts:
        org.enable_payouts = settings_data.payouts.enable_payouts
        org.request_payout_details = settings_data.payouts.request_payout_details
        org.payout_method = settings_data.payouts.payout_method
        
        # Update payout rules if provided
        if settings_data.payouts.payout_rules is not None:
            # Clear existing rules
            db.query(PayoutRule).filter(PayoutRule.organization_id == org.id).delete()
            
            # Add new rules
            for rule_data in settings_data.payouts.payout_rules:
                new_rule = PayoutRule(
                    organization_id=org.id,
                    position=rule_data.position,
                    amount=rule_data.amount
                )
                db.add(new_rule)

        db.flush()

        if (
            org.enable_payouts
            and org.payout_method == "stripe"
            and settings_data.payouts.payout_rules
        ):
            user = UserService.get_user(db, user_id=auth.user_id)
            if user:
                stripe_onboarding_url = StripeConnectService.ensure_onboarding(
                    db, org, user.email
                )
                db.refresh(org)
                StripeConnectService.sync_payout_rules_to_stripe(
                    db, org, list(org.payout_rules)
                )

    db.commit()
    db.refresh(org)

    settings_response = OrganizationService.build_settings_response(org)
    return OrgSettingsSaveResponse(
        **settings_response.model_dump(),
        stripe_onboarding_url=stripe_onboarding_url,
    )


@router.get("/settings/payouts", response_model=list[PayoutRuleResponse])
async def get_payout_rules(
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_current_user)
):
    """Retrieve all payout rules for the organization"""
    org = OrganizationService.get_by_owner(db, auth.user_id)
    if not org:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found"
        )
    
    return org.payout_rules


@router.post("/settings/payouts", response_model=PayoutRuleResponse)
async def create_payout_rule(
    rule_data: PayoutRuleCreate,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_current_user)
):
    """Create a new payout rule for the organization"""
    org = OrganizationService.get_by_owner(db, auth.user_id)
    if not org:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found"
        )
    
    # Check if rule for this position already exists
    existing_rule = db.query(PayoutRule).filter(
        PayoutRule.organization_id == org.id,
        PayoutRule.position == rule_data.position
    ).first()
    
    if existing_rule:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Payout rule for position '{rule_data.position}' already exists"
        )
    
    new_rule = PayoutRule(
        organization_id=org.id,
        position=rule_data.position,
        amount=rule_data.amount
    )
    db.add(new_rule)
    db.commit()
    db.refresh(new_rule)
    return new_rule


@router.put("/settings/payouts/{rule_id}", response_model=PayoutRuleResponse)
async def update_payout_rule(
    rule_id: int,
    rule_data: PayoutRuleCreate,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_current_user)
):
    """Update an existing payout rule"""
    org = OrganizationService.get_by_owner(db, auth.user_id)
    if not org:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found"
        )
    
    rule = db.query(PayoutRule).filter(
        PayoutRule.id == rule_id,
        PayoutRule.organization_id == org.id
    ).first()
    
    if not rule:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Payout rule not found"
        )
    
    rule.position = rule_data.position
    rule.amount = rule_data.amount
    db.commit()
    db.refresh(rule)
    return rule


@router.delete("/settings/payouts/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_payout_rule(
    rule_id: int,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_current_user)
):
    """Delete a payout rule"""
    org = OrganizationService.get_by_owner(db, auth.user_id)
    if not org:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found"
        )
    
    rule = db.query(PayoutRule).filter(
        PayoutRule.id == rule_id,
        PayoutRule.organization_id == org.id
    ).first()
    
    if not rule:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Payout rule not found"
        )
    
    db.delete(rule)
    db.commit()