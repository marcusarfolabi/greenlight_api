import logging
from typing import NoReturn, Optional

import stripe  # type: ignore
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.organization import Organization, PayoutRule
from app.schemas.organization import StripeConnectStatus

logger = logging.getLogger(__name__)

STRIPE_CONNECT_NOT_ENABLED_HINT = (
    "Stripe Connect is not enabled on your Stripe platform account. "
    "Open https://dashboard.stripe.com/connect and complete Connect setup, "
    "then use a secret key (sk_test_... or sk_live_...) from that same account."
)


class StripeConnectService:
    @staticmethod
    def _stripe_error_message(exc: stripe.StripeError) -> str:
        if getattr(exc, "user_message", None):
            return str(exc.user_message)
        error = getattr(exc, "error", None)
        if error is not None and getattr(error, "message", None):
            return str(error.message)
        return str(exc)

    @staticmethod
    def _raise_stripe_error(exc: stripe.StripeError, fallback: str) -> NoReturn:
        message = StripeConnectService._stripe_error_message(exc)
        logger.error("Stripe API error: %s", message)

        lowered = message.lower()
        if "signed up for connect" in lowered or (
            "connect" in lowered and "invalid_request" in lowered
        ):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=STRIPE_CONNECT_NOT_ENABLED_HINT,
            ) from exc

        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=message or fallback,
        ) from exc

    @staticmethod
    def _client() -> None:
        if not settings.STRIPE_SECRET_KEY:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Stripe is not configured. Set STRIPE_SECRET_KEY on the server.",
            )
        stripe.api_key = settings.STRIPE_SECRET_KEY

    @staticmethod
    def connect_status(org: Organization) -> StripeConnectStatus:
        onboarding_complete = bool(
            org.stripe_connect_id
            and org.stripe_charges_enabled
            and org.stripe_payouts_enabled
            and org.stripe_details_submitted
        )
        return StripeConnectStatus(
            connected=bool(org.stripe_connect_id),
            stripe_connect_id=org.stripe_connect_id,
            charges_enabled=org.stripe_charges_enabled,
            payouts_enabled=org.stripe_payouts_enabled,
            details_submitted=org.stripe_details_submitted,
            onboarding_complete=onboarding_complete,
        )

    @staticmethod
    def sync_account_status(db: Session, org: Organization) -> StripeConnectStatus:
        if not org.stripe_connect_id:
            return StripeConnectService.connect_status(org)

        StripeConnectService._client()
        try:
            account = stripe.Account.retrieve(org.stripe_connect_id)
        except stripe.StripeError as exc:
            StripeConnectService._raise_stripe_error(
                exc, "Unable to retrieve Stripe Connect account status."
            )

        org.stripe_charges_enabled = bool(account.get("charges_enabled"))
        org.stripe_payouts_enabled = bool(account.get("payouts_enabled"))
        org.stripe_details_submitted = bool(account.get("details_submitted"))
        org.is_verified = (
            org.stripe_charges_enabled
            and org.stripe_payouts_enabled
            and org.stripe_details_submitted
        )
        db.commit()
        db.refresh(org)
        return StripeConnectService.connect_status(org)

    @staticmethod
    def create_connect_account(
        db: Session,
        org: Organization,
        owner_email: str,
    ) -> Organization:
        if org.stripe_connect_id:
            return org

        StripeConnectService._client()
        try:
            account = stripe.Account.create(
                type="express",
                country="US",
                email=owner_email,
                capabilities={
                    "card_payments": {"requested": True},
                    "transfers": {"requested": True},
                },
                business_type="individual",
                metadata={"organization_id": str(org.id)},
            )
        except stripe.StripeError as exc:
            StripeConnectService._raise_stripe_error(
                exc, "Unable to create Stripe Connect account."
            )

        org.stripe_connect_id = account.id
        db.commit()
        db.refresh(org)
        return org

    @staticmethod
    def create_onboarding_link(org: Organization) -> str:
        if not org.stripe_connect_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Stripe Connect account does not exist for this organization.",
            )

        StripeConnectService._client()
        try:
            link = stripe.AccountLink.create(
                account=org.stripe_connect_id,
                refresh_url=settings.STRIPE_CONNECT_REFRESH_URL,
                return_url=settings.STRIPE_CONNECT_RETURN_URL,
                type="account_onboarding",
            )
        except stripe.StripeError as exc:
            StripeConnectService._raise_stripe_error(
                exc, "Unable to create Stripe onboarding link."
            )

        return link.url

    @staticmethod
    def ensure_onboarding(
        db: Session,
        org: Organization,
        owner_email: str,
    ) -> Optional[str]:
        """
        Ensure a Connect account exists and return an onboarding URL when setup
        is still incomplete.
        """
        org = StripeConnectService.create_connect_account(db, org, owner_email)
        status_payload = StripeConnectService.sync_account_status(db, org)

        if status_payload.onboarding_complete:
            return None

        return StripeConnectService.create_onboarding_link(org)

    @staticmethod
    def sync_payout_rules_to_stripe(
        db: Session,
        org: Organization,
        rules: list[PayoutRule],
    ) -> None:
        """
        Reserve Stripe product/price IDs per tier for future automated transfers.
        Skipped when Connect onboarding is incomplete or Stripe is unavailable.
        """
        if not org.stripe_connect_id or not settings.STRIPE_SECRET_KEY:
            return

        status_payload = StripeConnectService.sync_account_status(db, org)
        if not status_payload.onboarding_complete:
            return

        StripeConnectService._client()
        for rule in rules:
            if rule.stripe_price_id:
                continue
            try:
                currency = rule.currency.lower()

                product = stripe.Product.create(
                    name=f"{org.name} - {rule.position}",
                    metadata={
                        "organization_id": str(org.id),
                        "position": rule.position,
                    },
                    stripe_account=org.stripe_connect_id,
                )
                price = stripe.Price.create(
                    unit_amount=int(rule.amount * 100),
                    currency=currency,
                    product=product.id,
                    stripe_account=org.stripe_connect_id,
                )
                rule.stripe_product_id = product.id
                rule.stripe_price_id = price.id
            except stripe.StripeError as exc:
                logger.warning(
                    "Stripe product sync skipped for rule %s: %s",
                    rule.id,
                    exc,
                )

        db.commit()
