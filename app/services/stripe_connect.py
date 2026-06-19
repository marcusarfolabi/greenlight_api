import logging
from typing import NoReturn, Optional,  Any, cast 

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

# 1. ISO 3166-1 Alpha-2 Mapping Dictionary for Global Onboarding
COUNTRY_NAME_TO_ISO = {
    "kenya": "KE",
    "united kingdom": "GB",
    "uk": "GB",
    "united states": "US",
    "usa": "US",
    "canada": "CA",
    "nigeria": "NG",
    "ghana": "GH",
    "south africa": "ZA",
    "australia": "AU",
    "germany": "DE",
    "france": "FR",
    "ireland": "IE",
}


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

       # Fix: Use direct attribute access or bracket notation instead of .get()
        org.stripe_charges_enabled = bool(getattr(account, "charges_enabled", False))
        org.stripe_payouts_enabled = bool(getattr(account, "payouts_enabled", False))
        org.stripe_details_submitted = bool(getattr(account, "details_submitted", False))
        org.is_verified = (
            org.stripe_charges_enabled
            and org.stripe_payouts_enabled
            and org.stripe_details_submitted
        )
        db.commit()
        db.refresh(org)
        return StripeConnectService.connect_status(org)


    # @staticmethod
    # def create_connect_account(
    #     db: Session,
    #     org: Organization,
    #     owner_email: str,
    # ) -> Organization:
    #     if org.stripe_connect_id:
    #         return org

    #     StripeConnectService._client()

    #     # 2. Extract country string cleanly, standardize it, and determine ISO code
    #     db_country = (org.country or "").strip().lower()
        
    #     # If it's already an explicit 2-letter ISO format, use it directly
    #     if len(db_country) == 2:
    #         iso_country = db_country.upper()
    #     else:
    #         # Look up standard translation string or default safely to platform hub (GB)
    #         iso_country = COUNTRY_NAME_TO_ISO.get(db_country, "GB")

    #     # Use Uppercase Any, and cast it to Any to fully stop Pylance from enforcing the strict structural sub-type
    #     controller_params = cast(Any, {
    #         "fees": {"payer": "application"},
    #         "losses": {"payments": "application"},  
    #         "requirement_collection": "stripe",
    #     })
        
    #     try:
    #         # 3. Request account routing using dynamic country and updated modern v2 structure
    #         account = stripe.Account.create(
    #             type="express",
    #             country=iso_country,
    #             email=owner_email,
    #             controller=controller_params,  # Passed completely un-restrictive here
    #             capabilities={
    #                 "transfers": {"requested": True},
    #             },
    #             business_type="individual",
    #             metadata={"organization_id": str(org.id)},
    #         )
    #     except stripe.StripeError as exc:
    #         StripeConnectService._raise_stripe_error(
    #             exc, f"Unable to create Stripe Connect account for country {iso_country}."
    #         )

    #     org.stripe_connect_id = account.id
    #     db.commit()
    #     db.refresh(org)
    #     return org

    # @staticmethod
    # def create_connect_account(
    #     db: Session,
    #     org: Organization,
    #     owner_email: str,
    # ) -> Organization:
    #     """
    #     Creates a new Stripe Connect account using the exact Stripe Accounts V2 API schema.
    #     Pre-populates all available organization and geographic info.
    #     """
    #     if org.stripe_connect_id:
    #         return org

    #     if not settings.STRIPE_SECRET_KEY:
    #         raise HTTPException(
    #             status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
    #             detail="Stripe is not configured. Set STRIPE_SECRET_KEY on the server.",
    #         )
        
    #     client = stripe.StripeClient(settings.STRIPE_SECRET_KEY)

    #     db_country = (org.country or "").strip().lower()
    #     if len(db_country) == 2:
    #         iso_country = db_country
    #     else:
    #         iso_country = COUNTRY_NAME_TO_ISO.get(db_country, "gb")

    #     business_details: dict[str, Any] = {
    #         "registered_name": org.name,
    #     }

    #     address_payload: dict[str, str] = {
    #         "country": iso_country
    #     }
    #     if org.city:
    #         address_payload["city"] = org.city
    #     if org.state:
    #         address_payload["state"] = org.state
        
    #     if org.city or org.state:
    #         business_details["address"] = address_payload

    #     v2_params = cast(Any, {
    #         "contact_email": owner_email,
    #         "display_name": org.name,
    #         "identity": {
    #             "country": iso_country,
    #             "entity_type": "individual",  
    #             "business_details": business_details,
    #         },
    #         "configuration": {
    #             "merchant": {
    #                 "capabilities": {
    #                     "card_payments": {"requested": True}
    #                 }
    #             }
    #         },
    #         "defaults": {
    #             "responsibilities": {
    #                 "fees_collector": "application",
    #                 "losses_collector": "application",
    #             },
    #         },
    #         "dashboard": "express",  
    #         "metadata": {
    #             "organization_id": str(org.id),
    #             "subdomain": org.subdomain,
    #             "industry": org.industry
    #         },
    #     })

    #     try:
    #         account = client.v2.core.accounts.create(params=v2_params)
    #     except stripe.StripeError as exc:
    #         StripeConnectService._raise_stripe_error(
    #             exc, f"Unable to create Stripe Connect account via V2 for country {iso_country}."
    #         )

    #     # 6. Save the unique structural V2 tracking token
    #     org.stripe_connect_id = account.id
    #     db.commit()
    #     db.refresh(org)
    #     return org
    
    @staticmethod
    def create_connect_account(
        db: Session,
        org: Organization,
        owner_email: str,
    ) -> Organization:
        """
        Creates a new Stripe Connect account using the universally supported V1 API,
        properly configuring an Express dashboard configuration via the controller block.
        """
        if org.stripe_connect_id:
            return org

        # 1. Initialize global V1 settings client
        StripeConnectService._client()

        # 2. Extract country string cleanly, standardize it, and determine ISO code (Uppercase for V1)
        db_country = (org.country or "").strip().lower()
        if len(db_country) == 2:
            iso_country = db_country.upper()
        else:
            iso_country = COUNTRY_NAME_TO_ISO.get(db_country, "GB").upper()

        # 3. Configure the controller params strictly according to the V1 specifications
        # Adding dashboard: express tells Stripe how to combine fees/losses collection safely
        controller_params = cast(Any, {
            "fees": {"payer": "application"},
            "losses": {"payments": "application"},
            "requirement_collection": "stripe",
            "dashboard": {"type": "express"},  # 👈 Added this to explicitly avoid the "full dashboard" error
        })
        
        try:
            # 4. Create the account with the dashboard definition nested inside the controller
            account = stripe.Account.create(
                country=iso_country,
                email=owner_email,
                controller=controller_params,
                capabilities={
                    "transfers": {"requested": True},
                },
                business_type="individual",
                metadata={
                    "organization_id": str(org.id),
                    "subdomain": org.subdomain,
                    "industry": org.industry
                },
            )
        except stripe.StripeError as exc:
            StripeConnectService._raise_stripe_error(
                exc, f"Unable to create Stripe Connect account for country {iso_country}."
            )

        # 5. Save the generated Account ID directly to your database
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