import logging
from sqlalchemy.orm import Session
from fastapi import HTTPException, status

from sqlalchemy.orm import joinedload

from app.models.organization import Organization
from app.models.wallet import Wallet
from app.schemas.organization import OrganizationCreate, OrgSettingsResponse
from app.services.stripe_connect import StripeConnectService
from app.models.user import User


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
        return OrgSettingsResponse.model_validate(org).model_copy(
            update={"stripe_connect": StripeConnectService.connect_status(org)},
        )

    
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

            db_org = Organization(
                name=org_data.name,
                subdomain=org_data.subdomain,
                industry=org_data.industry,
                city=org_data.city,
                state=org_data.state,
                country=org_data.country,
                owner_id=user_id,
            )

            db.add(db_org)
            db.flush()

            db.add(Wallet(organization_id=db_org.id, user_id=user_id, balance=0, currency="gbp"))
            
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

        wallet = Wallet(organization_id=organization_id, user_id=None, balance=0, currency="gbp")
        db.add(wallet)
        db.commit()
        db.refresh(wallet)
        return wallet

    @staticmethod
    def get_wallet_summary(db: Session, org: Organization) -> dict:
        wallet = OrganizationService.get_or_create_wallet(db, org.id)

        total_spent = sum(
            abs(transaction.amount)
            for transaction in wallet.transactions
            if transaction.amount < 0 and transaction.status == "completed"
        )
        pending_withheld = sum(
            abs(transaction.amount)
            for transaction in wallet.transactions
            if transaction.status == "pending"
        )

        transactions = sorted(
            wallet.transactions,
            key=lambda transaction: transaction.created_at,
            reverse=True,
        )[:20]

        return {
            "balance": wallet.balance,
            "total_spent": total_spent,
            "pending_withheld": pending_withheld,
            "currency": wallet.currency,
            "stripe_connect_id": org.stripe_connect_id,
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