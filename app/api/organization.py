from app.schemas.organization import OrganizationCreate, OrganizationResponse
from app.core.security import get_current_user  # Assuming you have a dependency to grab the user payload
import logging
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session


from app.db.session import get_db
from app.models.user import UserRole
from app.services.user_service import UserService           
from app.services.organization import OrganizationService 


router = APIRouter()
logger = logging.getLogger(__name__) 

@router.post("/user/organization", response_model=OrganizationResponse)
async def setup_user_organization(
    org_data: OrganizationCreate, 
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user)  
):
    user = UserService.get_user(db, user_id=current_user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User account not found."
        )
        
    if user.role != UserRole.HOST:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only accounts configured with a HOST role can construct workspace domains."
        )

    # 2. Prevent subdomain duplicate overlaps
    if OrganizationService.get_by_subdomain(db, org_data.subdomain):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Organization workspace subdomain already taken",
        )

    # 3. Create organization and bind ownership identifier mapping reference
    # Modify your service method accordingly to accept the individual user_id and schema object
    new_org = OrganizationService.create_organization_for_user(
        db=db, 
        user_id=user.id, 
        org_data=org_data
    )
    
    return new_org