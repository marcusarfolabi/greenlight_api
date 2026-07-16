import enum
import logging
from datetime import datetime, timezone
from typing import Optional

import requests
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.models.subscription import Subscription
from app.models.user import User
from app.schemas.user import UserCreate, UserUpdate

logger = logging.getLogger(__name__)


class UserService:
    """Service layer for user operations."""

    @staticmethod
    def resolve_location_from_ip(client_ip: str) -> dict:
        if not client_ip or client_ip in ["127.0.0.1", "localhost", "::1"]:
            return {}

        try:
            # Using a free GeoIP API (for production, swap with MaxMind GeoIP2 database for speed/limit reasons)
            response = requests.get(f"http://ip-api.com/json/{client_ip}", timeout=3)
            if response.status_code == 200:
                data = response.json()
                if data.get("status") == "success":
                    city = data.get("city", "")
                    region = data.get("regionName", "")
                    country = data.get("country", "")
                    currency = data.get("currency", "")
                    country_iso = data.get("countryCode", "").lower()
                    parts = [p for p in [city, region, country, currency, country_iso] if p]
                    location_str = ", ".join(parts)

                    return {
                        "location": location_str,
                        "country_iso": country_iso,
                        "currency": currency,
                    }
        except Exception as e:
            logger.error(f"Failed to resolve IP location: {e}")

        return {}

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
    def get_user_by_linkedin_id(db: Session, linkedin_id: str) -> Optional[User]:
        return db.query(User).filter(User.linkedin_id == linkedin_id).first()

    @staticmethod
    def get_user_by_apple_id(db: Session, apple_id: str) -> Optional[User]:
        return db.query(User).filter(User.apple_id == apple_id).first()

    @staticmethod
    def get_user_by_login(db: Session, login: str) -> Optional[User]:
        return (
            db.query(User)
            .filter((User.username == login) | (User.email == login))
            .first()
        )

    @staticmethod
    def create_user(db: Session, user_data: UserCreate) -> User:
        logger.debug(
            "UserService.create_user initiated with user_data: %r",
            user_data.model_dump(exclude={"password"}),
        )

        google_id = getattr(user_data, "google_id", None)
        linkedin_id = getattr(user_data, "linkedin_id", None)
        apple_id = getattr(user_data, "apple_id", None)

        email_verified_at = None
        if google_id or linkedin_id or apple_id:
            email_verified_at = datetime.now(timezone.utc)

        client_ip = getattr(user_data, "client_ip", None)
        location_data = UserService.resolve_location_from_ip(client_ip)

        db_user = User(
            email=user_data.email,
            username=user_data.username,
            hashed_password=hash_password(user_data.password),
            first_name=getattr(user_data, "first_name", None),
            last_name=getattr(user_data, "last_name", None),
            role=user_data.role.value
            if isinstance(user_data.role, enum.Enum)
            else user_data.role,
            is_active=bool(getattr(user_data, "is_active", False)),
            google_id=google_id,
            linkedin_id=linkedin_id,
            apple_id=apple_id,
            email_verified_at=email_verified_at,
            location=location_data.get("location"),
        )

        if getattr(user_data, "organization_id", None):
            logger.info(
                "Linking user to provided organization_id: %r",
                user_data.organization_id,
            )
            db_user.organization_id = user_data.organization_id

        db.add(db_user)
        db.commit()
        db.refresh(db_user)

        return db_user

    @staticmethod
    def update_user_social_id(
        db: Session, user_id: int, provider_field: str, provider_id: str
    ) -> Optional[User]:
        """
        Dynamically links any OAuth unique provider ID to an existing account profile.

        :param provider_field: Must be "google_id", "linkedin_id", or "apple_id"
        :param provider_id: The unique identifier string received from OAuth handshake payload
        """
        if provider_field not in ["google_id", "linkedin_id", "apple_id"]:
            raise ValueError(
                f"Invalid social authentication provider field: {provider_field}"
            )

        db_user = UserService.get_user(db, user_id)
        if not db_user:
            return None

        setattr(db_user, provider_field, provider_id)
        # When linking a social account, treat this as verified and active
        try:
            db_user.is_active = True
            db_user.email_verified_at = datetime.now(timezone.utc)
        except Exception:
            # best-effort: ignore if attributes missing
            pass

        db.add(db_user)
        db.commit()
        db.refresh(db_user)
        return db_user

    @staticmethod
    def update_user(
        db: Session, user_id: int, user_update: UserUpdate
    ) -> Optional[User]:
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
        existing = (
            db.query(Subscription)
            .filter(
                Subscription.organization_id == org_id, Subscription.status == "active"
            )
            .first()
        )
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
