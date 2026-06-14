from fastapi import APIRouter, Depends, HTTPException, status, Response
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.db.session import get_db
from app.schemas.user import AuthContext, UserResponse, UserUpdate
from app.services.user_service import UserService

router = APIRouter()


@router.get("/me", response_model=UserResponse)
async def get_current_user_profile(
    current_user: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get the authenticated user's profile."""
    user = UserService.get_user(db, int(current_user.user_id))
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user


@router.put("/me", response_model=UserResponse)
async def update_user_profile(
    user_update: UserUpdate,
    current_user: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update the authenticated user's profile."""
    user = UserService.update_user(db, int(current_user.user_id), user_update)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user


@router.get("/{user_id}", response_model=UserResponse)
async def get_user(user_id: int, db: Session = Depends(get_db)):
    """Get a user by ID."""
    user = UserService.get_user(db, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user


@router.delete("/me", status_code=status.HTTP_204_NO_CONTENT)
async def delete_current_user(
    current_user: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Delete the authenticated user's account."""
    user = UserService.delete_user(db, int(current_user.user_id))
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)

