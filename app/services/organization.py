import logging
from typing import Optional
from sqlalchemy.orm import Session
from fastapi import HTTPException, status

from sqlalchemy.orm import joinedload

from app.models.organization import Organization
from app.models.wallet import Wallet, Transaction
from app.schemas.organization import OrganizationCreate, OrgSettingsResponse
from app.models.user import User
from app.utils.currency import get_currency_by_country_code


logger = logging.getLogger(__name__)

class OrganizationService:
    """Service layer for organization and host onboarding."""

    @staticmethod
    def get_by_subdomain(db: Session, subdomain: str) -> Organization | None:
        return db.query(Organization).filter(Organization.subdomain == subdomain).first()

    @staticmethod
    def get_by_owner(db: Session, owner_id: int) -> Organization | None:
        """Get organization by owner user ID"""
        return db.query(Organization).filter(Organization.owner_id == owner_id).first()

    @staticmethod
    def build_settings_response(org: Organization) -> OrgSettingsResponse:
        return OrgSettingsResponse.model_validate(org).model_copy(update={"owner_id": org.owner_id, "is_verified": org.is_verified})

    @staticmethod
    def extract_location_parts(location: str) -> tuple[Optional[str], Optional[str], Optional[str]]:
        if not location:
            return None, None, None

        parts = [part.strip() for part in location.split(",") if part.strip()]
        if len(parts) >= 3:
            return parts[0], parts[1], parts[-1]
        if len(parts) == 2:
            return parts[0], None, parts[1]
        return None, None, parts[0]

    @staticmethod
    def create_organization_for_user(db: Session, user_id: int, org_data: OrganizationCreate) -> Organization:
        """
        Creates a new organization in the database and links it to a specific host user.
        """
        try:
            user = db.query(User).filter(User.id == user_id).first()
            if user is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="User not found while creating organization."
                )

            parsed_city, parsed_state, parsed_country = OrganizationService.extract_location_parts(user.location or "")
            db_org = Organization(
                name=org_data.name,
                subdomain=org_data.subdomain,
                industry=org_data.industry,
                city=org_data.city or parsed_city,
                state=org_data.state or parsed_state,
                country=org_data.country or parsed_country,
                owner_id=user_id,
            )

            db.add(db_org)
            db.flush()

            wallet = user.wallet
            if wallet is None:
                wallet = db.query(Wallet).filter(Wallet.user_id == user.id).first()

                if not wallet:
                    wallet = Wallet(
                        user_id=user.id,
                        currency=get_currency_by_country_code(user.location),
                    )
                    db.add(wallet)

            wallet.organization_id = db_org.id
            db.commit()

            user.organization_id = db_org.id
            user.first_name = org_data.first_name
            user.last_name = org_data.last_name
            user.phone_number = org_data.phone_number
            user.role = org_data.role

            db.commit()

            db.refresh(db_org)
            db.refresh(user)

            logger.info(f"Successfully created organization '{db_org.name}' for user ID {user_id}")
            return db_org

        except Exception as e:
            db.rollback()
            logger.error(f"Failed to create organization for user {user_id}. Error: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="An error occurred while creating your workspace setup."
            )

    @staticmethod
    def get_or_create_wallet(db: Session, organization_id: int) -> Wallet:
        wallet = (
            db.query(Wallet)
            .options(joinedload(Wallet.transactions))
            .filter(Wallet.organization_id == organization_id)
            .first()
        )
        if wallet:
            return wallet

        organization = db.query(Organization).filter(Organization.id == organization_id).first()
        if not organization:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Organization not found",
            )

        currency = OrganizationService.resolve_organization_currency(db, organization)
        wallet = Wallet(organization_id=organization_id, currency=currency)
        db.add(wallet)
        db.commit()
        db.refresh(wallet)
        return wallet

    @staticmethod
    def resolve_organization_currency(db: Session, org: Organization | None) -> str:
        """Resolve organization currency strictly from existing wallet records."""
        if not org:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Organization not found",
            )

        if org.wallet and org.wallet.currency:
            return org.wallet.currency.lower()

        owner = db.query(User).filter(User.id == org.owner_id).first()
        if owner and owner.wallet and owner.wallet.currency:
            return owner.wallet.currency.lower()

        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Wallet currency is missing for this organization",
        )

    @staticmethod
    def get_wallet_summary(db: Session, org: Organization, offset: int = 0, limit: int = 10) -> dict:
        wallet = OrganizationService.get_or_create_wallet(db, org.id)

        total_spent = sum(
            abs(transaction.amount)
            for transaction in wallet.transactions
            if transaction.amount < 0 and transaction.status == "completed"
        )
        pending_withheld = wallet.pending_balance or 0

        paged_transactions = (
            db.query(Transaction)
            .filter(Transaction.wallet_id == wallet.id)
            .order_by(Transaction.created_at.desc())
            .offset(offset)
            .limit(limit + 1)
            .all()
        )
        has_more = len(paged_transactions) > limit
        transactions = paged_transactions[:limit]

        return {
            "balance": wallet.balance,
            "total_spent": total_spent,
            "pending_withheld": pending_withheld,
            "currency": wallet.currency,
            "offset": offset,
            "limit": limit,
            "has_more": has_more,
            "transactions": [
                {
                    "id": transaction.id,
                    "amount": transaction.amount,
                    "type": transaction.type.value
                    if hasattr(transaction.type, "value")
                    else str(transaction.type),
                    "description": transaction.description,
                    "status": transaction.status,
                    "stripe_reference": transaction.stripe_reference,
                    "created_at": transaction.created_at,
                }
                for transaction in transactions
            ],
        }

organization_service = OrganizationService()
