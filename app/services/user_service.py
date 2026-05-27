from datetime import datetime, timedelta
import enum
from typing import Optional

from sqlalchemy import and_
from sqlalchemy.orm import Session
from jose import jwt, JWTError

from app.core.security import hash_password
from app.models.user import User
from app.schemas.user import UserCreate, UserUpdate
from app.core.config import settings
class UserService:
    """Service layer for user operations."""

    @staticmethod
    def get_user(db: Session, user_id: int) -> Optional[User]:
        return db.query(User).filter(User.id == user_id).first()

    @staticmethod
    def get_user_by_username(db: Session, username: str) -> Optional[User]:
        return db.query(User).filter(User.username == username).first()

    @staticmethod
    def get_user_by_email(db: Session, email: str) -> Optional[User]:
        return db.query(User).filter(User.email == email).first()
    
    @staticmethod
    def get_user_by_login(db: Session, login: str) -> Optional[User]:
        return (
            db.query(User)
            .filter((User.username == login) | (User.email == login))
            .first()
        )

    @staticmethod
    def create_user(db: Session, user_data: UserCreate) -> User:
        db_user = User(
            email=user_data.email,
            username=user_data.username,
            hashed_password=hash_password(user_data.password),
            role=user_data.role.value if isinstance(user_data.role, enum.Enum) else user_data.role,
        )
        db.add(db_user)
        db.commit()
        db.refresh(db_user)
        return db_user

    @staticmethod
    def update_user(db: Session, user_id: int, user_update: UserUpdate) -> Optional[User]:
        db_user = UserService.get_user(db, user_id)
        if not db_user:
            return None

        update_data = user_update.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(db_user, field, value)

        db.add(db_user)
        db.commit()
        db.refresh(db_user)
        return db_user

    @staticmethod
    def delete_user(db: Session, user_id: int) -> Optional[User]:
        db_user = UserService.get_user(db, user_id)
        if not db_user:
            return None

        db.delete(db_user)
        db.commit()
        return db_user
    
    @staticmethod
    def user_has_org(db: Session, user_id: int) -> bool:
        user = UserService.get_user(db, user_id)
        if user is None:
            return False
        return user.owned_organization is not None
    
    @staticmethod
    def get_user_org_id(db: Session, user_id: int) -> Optional[int]:
        user = UserService.get_user(db, user_id)
        if user is None or user.owned_organization is None:
            return None
        return user.owned_organization.id
    
    @staticmethod
    def user_sub_domain(db: Session, user_id: int) -> Optional[str]:
        user = UserService.get_user(db, user_id)
        if user is None or user.owned_organization is None:
            return None
        return user.owned_organization.subdomain
     
 
user_service = UserService()
