from datetime import datetime, timedelta
import enum
from typing import Optional

from sqlalchemy import and_
from sqlalchemy.orm import Session
from jose import jwt, JWTError

from app.core.security import hash_password
from app.models.user import User
from app.models.wallet import Wallet
from app.schemas.user import UserCreate, UserUpdate
from app.core.config import settings
from app.models.subscription import Subscription

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
    def get_user_by_google_id(db: Session, google_id: str) -> Optional[User]: 
        return db.query(User).filter(User.google_id == google_id).first()
    
    @staticmethod
    def get_user_by_login(db: Session, login: str) -> Optional[User]:
        return (
            db.query(User)
            .filter((User.username == login) | (User.email == login))
            .first()
        )

    @staticmethod
    def create_user(db: Session, user_data: UserCreate) -> User: 
        google_id = getattr(user_data, "google_id", None)
        linkedin_id = getattr(user_data, "linkedin_id", None)
        apple_id = getattr(user_data, "apple_id", None)

        db_user = User(
            email=user_data.email,
            username=user_data.username,
            hashed_password=hash_password(user_data.password),
            first_name=getattr(user_data, "first_name", None),
            last_name=getattr(user_data, "last_name", None),
            role=user_data.role.value if isinstance(user_data.role, enum.Enum) else user_data.role,
            is_active=user_data.is_active if getattr(user_data, "is_active", None) is not None else False,
            google_id=google_id,
            linkedin_id=linkedin_id,
            apple_id=apple_id
        )
        db.add(db_user)
        db.flush()
 
        db.commit()
        db.refresh(db_user)
        return db_user

    @staticmethod
    def update_user_social_id(db: Session, user_id: int, provider_field: str, provider_id: str) -> Optional[User]:
        """
        Dynamically links any OAuth unique provider ID to an existing account profile.
        
        :param provider_field: Must be "google_id", "linkedin_id", or "apple_id"
        :param provider_id: The unique identifier string received from OAuth handshake payload
        """
        if provider_field not in ["google_id", "linkedin_id", "apple_id"]:
            raise ValueError(f"Invalid social authentication provider field: {provider_field}")
            
        db_user = UserService.get_user(db, user_id)
        if not db_user:
            return None

        setattr(db_user, provider_field, provider_id)
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
        
        if "password" in update_data:
            raw_password = update_data.pop("password")
            if raw_password:
                db_user.hashed_password = hash_password(raw_password)

        for field, value in update_data.items():
            if hasattr(db_user, field):
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
    def user_has_subscription(db: Session, org_id: int) -> bool:
        existing = db.query(Subscription).filter(
            Subscription.organization_id == org_id,
            Subscription.status == "active"
        ).first() 
        return existing is not None
    
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
