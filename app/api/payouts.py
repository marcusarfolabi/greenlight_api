import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.db.session import get_db
from app.schemas.organization import StripeConnectStatus, StripeOnboardingResponse
from app.schemas.user import AuthContext
from app.services.organization import OrganizationService
from app.services.stripe_connect import StripeConnectService
from app.services.user_service import UserService

router = APIRouter()
logger = logging.getLogger(__name__)


def _get_host_organization(db: Session, auth: AuthContext):
    org = OrganizationService.get_by_owner(db, auth.user_id)
    if not org:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found",
        )
    return org


@router.get("/connect/status", response_model=StripeConnectStatus)
async def get_stripe_connect_status(
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_current_user),
):
    """Return Stripe Connect onboarding status for the host organization."""
    org = _get_host_organization(db, auth)
    if org.stripe_connect_id:
        return StripeConnectService.sync_account_status(db, org)
    return StripeConnectService.connect_status(org)


@router.post("/connect/onboarding", response_model=StripeOnboardingResponse)
async def start_stripe_connect_onboarding(
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_current_user),
):
    """Create (if needed) a Connect account and return the Stripe onboarding URL."""
    org = _get_host_organization(db, auth)
    user = UserService.get_user(db, user_id=auth.user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User account not found.",
        )

    org = StripeConnectService.create_connect_account(db, org, user.email)
    onboarding_url = StripeConnectService.ensure_onboarding(db, org, user.email)
    if not onboarding_url:
        onboarding_url = StripeConnectService.create_onboarding_link(org)

    return StripeOnboardingResponse(
        onboarding_url=onboarding_url,
        stripe_connect_id=org.stripe_connect_id or "",
    )
