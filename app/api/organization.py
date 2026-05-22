import logging
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.core.security import get_current_user  

from app.schemas.organization import OrganizationCreate, OrganizationResponse
from app.models.user import UserRole
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
    print(f"DEBUG: User role: {auth.role}")
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