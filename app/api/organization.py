import logging
from decimal import Decimal
from app.db.session import get_db
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
import stripe  # type: ignore
from app.core.config import settings
from fastapi import BackgroundTasks

from app.core.security import create_access_token, get_current_user

from app.schemas.organization import (
    OrganizationCreate, OrgSettingsUpdate, OrgSettingsResponse, OrgSettingsSaveResponse,
    PayoutRuleCreate, PayoutRuleResponse,
    WalletSummaryResponse,
)
from app.models.arena import Arena
from app.schemas.organization import CreateTopUpRequest, ConfirmTopUpRequest, CreateTopUpResponse
from app.models.wallet import Transaction, TransactionType
from app.models.subscription import Subscription
from app.models.organization import PayoutRule
from app.services.user_service import UserService
from app.services.organization import OrganizationService
from app.schemas.user import AuthContext
from app.utils.currency import from_minor_units, to_minor_units


router = APIRouter()
logger = logging.getLogger(__name__)


def _payout_rule_amount_minor(amount: float, currency: str) -> int:
    return to_minor_units(Decimal(str(amount)), currency)


def _total_payout_required_minor(rules: list[PayoutRule], currency: str) -> int:
    return sum(
        _payout_rule_amount_minor(rule.amount, currency)
        for rule in rules
        if rule.amount and rule.amount > 0
    )


def _build_rules_summary(rules: list[PayoutRule], currency: str) -> str:
    if not rules:
        return "no payout rules"

    parts: list[str] = []
    for rule in rules:
        if not rule.amount or rule.amount <= 0:
            continue
        amount_major = from_minor_units(
            _payout_rule_amount_minor(rule.amount, currency),
            currency,
        )
        parts.append(
            f"{rule.position}:{float(amount_major):.2f} {currency.upper()}"
        )

    return ", ".join(parts) if parts else "no payout rules"


def _apply_pending_balance_delta(
    db: Session,
    wallet,
    previous_required_minor: int,
    next_required_minor: int,
    rules_summary: str,
) -> None:
    delta_minor = next_required_minor - previous_required_minor

    # Keep reserve buckets in sync with rule totals by transferring funds between
    # available balance and pending reserve.
    current_pending = wallet.pending_balance or 0
    current_available = wallet.balance or 0

    if delta_minor == 0:
        wallet.pending_balance = max(0, next_required_minor)
        db.add(wallet)
        return

    if delta_minor > 0 and current_available < delta_minor:
        required_major = from_minor_units(delta_minor, wallet.currency)
        available_major = from_minor_units(current_available, wallet.currency)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Insufficient wallet balance for payout scheduling. "
                f"Additional reserve needed: {float(required_major):.2f} {wallet.currency.upper()}, "
                f"Available: {float(available_major):.2f} {wallet.currency.upper()}. "
                "Please top up your wallet at /settings/wallet before saving payout settings."
            ),
        )

    if delta_minor > 0:
        wallet.balance = max(0, current_available - delta_minor)
        wallet.pending_balance = current_pending + delta_minor
    else:
        released = abs(delta_minor)
        wallet.balance = current_available + released
        wallet.pending_balance = max(0, current_pending - released)

    if delta_minor > 0:
        tx = Transaction(
            wallet_id=wallet.id,
            amount=-delta_minor,
            type=TransactionType.PRIZE_PAYOUT,
            status="pending",
            description=(
                f"Payout reserve increased by {float(from_minor_units(delta_minor, wallet.currency)):.2f} "
                f"{wallet.currency.upper()} (new reserved total: "
                f"{float(from_minor_units(next_required_minor, wallet.currency)):.2f} {wallet.currency.upper()}; "
                f"{rules_summary})"
            ),
        )
    else:
        released = abs(delta_minor)
        tx = Transaction(
            wallet_id=wallet.id,
            amount=released,
            type=TransactionType.REFUND,
            status="completed",
            description=(
                f"Payout reserve released by {float(from_minor_units(released, wallet.currency)):.2f} "
                f"{wallet.currency.upper()} (new reserved total: "
                f"{float(from_minor_units(next_required_minor, wallet.currency)):.2f} {wallet.currency.upper()}; "
                f"{rules_summary})"
            ),
        )

    db.add(wallet)
    db.add(tx)


@router.post("")
async def setup_host_organization(
    org_data: OrganizationCreate,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_current_user)
):
    user_id = auth.user_id

    user = UserService.get_user(db, user_id=user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User account not found."
        )

    if OrganizationService.get_by_subdomain(db, org_data.subdomain):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Organization workspace subdomain already taken",
        )

    # Create the new organization
    new_org = OrganizationService.create_organization_for_user(
        db=db, user_id=auth.user_id, org_data=org_data
    )

    hasSub = UserService.user_has_subscription(db, new_org.id)

    # Pack the freshly created org_id into the new JWT payload
    token_data = {
        "sub": str(user.id),
        "role": user.role,
        "username": user.username,
        "org_id": new_org.id,
        "has_subscription": hasSub
    }

    access_token = create_access_token(data=token_data)

    # Construct an updated user profile layout block for the frontend
    user_data = {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "role": user.role,
        "hasOrg": True,
        "org_id": new_org.id,
        "hasSub": hasSub,
        "subdomain": new_org.subdomain
    }

    # Return everything explicitly via JSON
    return {
        "organization": new_org,
        "access_token": access_token,
        "token_type": "bearer",
        "user": user_data
    }

@router.get("/wallet", response_model=WalletSummaryResponse)
async def get_organization_wallet(
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_current_user),
    offset: int = Query(0, ge=0),
    limit: int = Query(10, ge=1, le=100),
):
    """Retrieve wallet balance, summary stats, and recent transactions."""
    org = OrganizationService.get_by_owner(db, auth.user_id)
    if not org:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found",
        )

    return OrganizationService.get_wallet_summary(db, org, offset=offset, limit=limit)


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
        wallet = OrganizationService.get_or_create_wallet(db, org.id)
        existing_required_minor = _total_payout_required_minor(
            org.payout_rules,
            wallet.currency,
        )

        incoming_rules_payload = (
            settings_data.payouts.payout_rules
            if settings_data.payouts.enable_payouts and settings_data.payouts.payout_rules
            else []
        )
        incoming_required_minor = sum(
            _payout_rule_amount_minor(rule.amount, wallet.currency)
            for rule in incoming_rules_payload
            if rule.amount and rule.amount > 0
        )

        additional_required_minor = max(0, incoming_required_minor - existing_required_minor)
        if additional_required_minor > wallet.balance:
            required_major = from_minor_units(additional_required_minor, wallet.currency)
            available_major = from_minor_units(wallet.balance, wallet.currency)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "Insufficient wallet balance for payout scheduling. "
                    f"Additional reserve needed: {float(required_major):.2f} {wallet.currency.upper()}, "
                    f"Available: {float(available_major):.2f} {wallet.currency.upper()}. "
                    "Please top up your wallet at /settings/wallet before saving payout settings."
                ),
            )

        org.enable_payouts = settings_data.payouts.enable_payouts
        org.request_payout_details = settings_data.payouts.request_payout_details
        org.payout_method = settings_data.payouts.payout_method

        # Update payout rules if provided
        if settings_data.payouts.payout_rules is not None:
            db.query(PayoutRule).filter(PayoutRule.organization_id == org.id).delete()

            for rule_data in settings_data.payouts.payout_rules:
                db.add(
                    PayoutRule(
                        organization_id=org.id,
                        position=rule_data.position,
                        amount=rule_data.amount,
                    )
                )

        db.flush()

        refreshed_rules = db.query(PayoutRule).filter(PayoutRule.organization_id == org.id).all()
        next_required_minor = _total_payout_required_minor(refreshed_rules, wallet.currency)
        _apply_pending_balance_delta(
            db,
            wallet,
            existing_required_minor,
            next_required_minor,
            _build_rules_summary(refreshed_rules, wallet.currency),
        )

    db.commit()
    db.refresh(org)

    settings_response = OrganizationService.build_settings_response(org)
    return OrgSettingsSaveResponse(
        **settings_response.model_dump(),
    )


@router.post("/wallet/top-up", response_model=CreateTopUpResponse)
async def create_wallet_topup(
    request: CreateTopUpRequest,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_current_user),
):
    """Create a Stripe PaymentIntent to top-up the organization's wallet."""
    if not auth.org_id or auth.org_id == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User must belong to an organization to top-up wallet",
        )

    organization = OrganizationService.get_by_owner(db, auth.user_id)
    if not organization:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found",
        )

    if not settings.STRIPE_SECRET_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Stripe is not configured",
        )

    stripe.api_key = settings.STRIPE_SECRET_KEY

    try:
        # Try to reuse an existing subscription customer if present
        existing_sub = db.query(Subscription).filter(Subscription.organization_id == auth.org_id, Subscription.stripe_customer_id is not None).first()
        if existing_sub and existing_sub.stripe_customer_id:
            stripe_customer_id = existing_sub.stripe_customer_id
        else:
            customer = stripe.Customer.create(
                name=organization.name,
                metadata={"organization_id": str(auth.org_id)},
            )
            stripe_customer_id = customer.id

        if request.amount <= 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Top-up amount must be greater than 0",
            )

        wallet = OrganizationService.get_or_create_wallet(db, organization.id)
        amount = to_minor_units(Decimal(str(request.amount)), wallet.currency)

        payment_intent = stripe.PaymentIntent.create(
            amount=amount,
            currency=wallet.currency,
            customer=stripe_customer_id,
            automatic_payment_methods={"enabled": True},
            metadata={
                "organization_id": str(auth.org_id),
                "purpose": "wallet_topup",
            },
        )

        return {
            "client_secret": payment_intent.client_secret,
            "payment_intent_id": payment_intent.id,
            "amount": float(from_minor_units(int(payment_intent.amount), wallet.currency)),
            "currency": wallet.currency,
        }

    except Exception as e:
        logger.error(f"Stripe error creating top-up intent: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to create top-up intent: {str(e)}",
        )


@router.post("/wallet/confirm-topup")
async def confirm_wallet_topup(
    request: ConfirmTopUpRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_current_user),
):
    """Confirm a Stripe PaymentIntent and credit the organization's wallet."""
    organization = OrganizationService.get_by_owner(db, auth.user_id)
    if not organization:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found",
        )

    if not settings.STRIPE_SECRET_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Stripe is not configured",
        )

    stripe.api_key = settings.STRIPE_SECRET_KEY

    try:
        payment_intent = stripe.PaymentIntent.retrieve(request.payment_intent_id)

        if payment_intent.status != "succeeded":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Payment not completed. Status: {payment_intent.status}",
            )

        wallet = OrganizationService.get_or_create_wallet(db, organization.id)

        amount = int(payment_intent.amount)

        tx = Transaction(
            wallet_id=wallet.id,
            amount=amount,
            type=TransactionType.DEPOSIT,
            stripe_reference=payment_intent.id,
            status="completed",
            description="Top-up via Stripe",
        )
        db.add(tx)

        wallet.balance = (wallet.balance or 0) + amount

        db.commit()
        db.refresh(wallet)

        return {"success": True, "message": "Wallet topped up successfully", "balance": wallet.balance}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error confirming top-up: {str(e)}")
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to confirm top-up",
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

    wallet = OrganizationService.get_or_create_wallet(db, org.id)
    existing_required_minor = _total_payout_required_minor(org.payout_rules, wallet.currency)
    next_required_minor = existing_required_minor + _payout_rule_amount_minor(
        rule_data.amount, wallet.currency
    )
    additional_required_minor = max(0, next_required_minor - existing_required_minor)
    if additional_required_minor > wallet.balance:
        required_major = from_minor_units(additional_required_minor, wallet.currency)
        available_major = from_minor_units(wallet.balance, wallet.currency)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Insufficient wallet balance for payout scheduling. "
                f"Additional reserve needed: {float(required_major):.2f} {wallet.currency.upper()}, "
                f"Available: {float(available_major):.2f} {wallet.currency.upper()}. "
                "Please top up your wallet here before saving payout settings."
            ),
        )

    new_rule = PayoutRule(
        organization_id=org.id,
        position=rule_data.position,
        amount=rule_data.amount
    )
    db.add(new_rule)
    db.flush()

    refreshed_rules = db.query(PayoutRule).filter(PayoutRule.organization_id == org.id).all()
    next_required_minor = _total_payout_required_minor(refreshed_rules, wallet.currency)
    _apply_pending_balance_delta(
        db,
        wallet,
        existing_required_minor,
        next_required_minor,
        _build_rules_summary(refreshed_rules, wallet.currency),
    )

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

    wallet = OrganizationService.get_or_create_wallet(db, org.id)
    current_required_minor = _total_payout_required_minor(org.payout_rules, wallet.currency)
    existing_excluding_current_minor = sum(
        _payout_rule_amount_minor(r.amount, wallet.currency)
        for r in org.payout_rules
        if r.id != rule.id and r.amount and r.amount > 0
    )
    next_required_minor = existing_excluding_current_minor + _payout_rule_amount_minor(
        rule_data.amount, wallet.currency
    )
    additional_required_minor = max(0, next_required_minor - current_required_minor)
    if additional_required_minor > wallet.balance:
        required_major = from_minor_units(additional_required_minor, wallet.currency)
        available_major = from_minor_units(wallet.balance, wallet.currency)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Insufficient wallet balance for payout scheduling. "
                f"Additional reserve needed: {float(required_major):.2f} {wallet.currency.upper()}, "
                f"Available: {float(available_major):.2f} {wallet.currency.upper()}. "
                "Please top up your wallet at /settings/wallet before saving payout settings."
            ),
        )

    rule.position = rule_data.position
    rule.amount = rule_data.amount
    db.flush()

    refreshed_rules = db.query(PayoutRule).filter(PayoutRule.organization_id == org.id).all()
    next_required_minor = _total_payout_required_minor(refreshed_rules, wallet.currency)
    _apply_pending_balance_delta(
        db,
        wallet,
        current_required_minor,
        next_required_minor,
        _build_rules_summary(refreshed_rules, wallet.currency),
    )

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

    wallet = OrganizationService.get_or_create_wallet(db, org.id)
    current_required_minor = _total_payout_required_minor(org.payout_rules, wallet.currency)

    db.delete(rule)
    db.flush()

    refreshed_rules = db.query(PayoutRule).filter(PayoutRule.organization_id == org.id).all()
    next_required_minor = _total_payout_required_minor(refreshed_rules, wallet.currency)
    _apply_pending_balance_delta(
        db,
        wallet,
        current_required_minor,
        next_required_minor,
        _build_rules_summary(refreshed_rules, wallet.currency),
    )

    db.commit()


@router.get("/arena-settings", response_model=OrgSettingsResponse)
async def get_organization_arena_settings(
    access_code: int,
    db: Session = Depends(get_db),
):
    arena = (
        db.query(Arena)
        .filter(Arena.access_code == access_code)
        .first()
    )
    if not arena:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Arena not found"
        )
    if not arena.creator_organization_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Arena is not linked to an organization"
        )
    """Retrieve all organization settings (branding, visibility, payouts)"""
    org = OrganizationService.get_by_owner(db, arena.creator_id)

    if not org:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found"
        )

    return OrganizationService.build_settings_response(org)

