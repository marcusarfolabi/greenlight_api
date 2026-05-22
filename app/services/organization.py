import logging
from sqlalchemy.orm import Session
from fastapi import HTTPException, status

from app.models.organization import Organization
from app.schemas.organization import OrganizationCreate


logger = logging.getLogger(__name__)

class OrganizationService:
    """Service layer for organization and host onboarding."""

    @staticmethod
    def get_by_subdomain(db: Session, subdomain: str) -> Organization | None:
        return db.query(Organization).filter(Organization.subdomain == subdomain).first()

    
    @staticmethod
    def create_organization_for_user(db: Session, user_id: int, org_data: OrganizationCreate) -> Organization:
        """
        Creates a new organization in the database and links it to a specific host user.
        """
        try:
            db_org = Organization(
                name=org_data.name,
                subdomain=org_data.subdomain,
                industry=org_data.industry,
                owner_id=user_id,          
            )
            
            db.add(db_org)
            db.commit()
            db.refresh(db_org)
            
            logger.info(f"Successfully created organization '{db_org.name}' for user ID {user_id}")
            return db_org

        except Exception as e:
            db.rollback()
            logger.error(f"Failed to create organization for user {user_id}. Error: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="An error occurred while creating your workspace setup."
            )
 
organization_service = OrganizationService()