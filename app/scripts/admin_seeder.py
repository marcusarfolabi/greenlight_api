import os
import sys

from sqlalchemy import func

sys.path.insert(
    0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)

from app.core.config import settings
from app.core.security import hash_password
from app.db.session import SessionLocal
from app.models.organization import Organization
from app.models.subscription import SubscriptionPlan, SubscriptionPlanType
from app.models.user import User, UserRole
from app.models.wallet import Wallet
from app.services.subscription_service import SubscriptionService


def seed_superadmin():
    """Seeds the default system superadmin and corresponding operational platform wallet
    using credentials automatically loaded by the application config layer from environment variables."""

    admin_username = getattr(settings, "ADMIN_USERNAME", "superadmin")
    admin_email = getattr(settings, "ADMIN_EMAIL", "admin@greenlightquiz.com")
    admin_firstname = getattr(settings, "ADMIN_FIRSTNAME", "Moses")
    admin_lastname = getattr(settings, "ADMIN_LASTNAME", "David")
    admin_raw_password = getattr(settings, "ADMIN_PASSWORD", ".Admin!Green@151k")
    session = SessionLocal()

    try:
        print(
            f"Verifying existence of superadmin account: '{admin_username}' ({admin_email})..."
        )

        # 1. Verify or Create Superadmin User
        existing_admin = (
            session.query(User)
            .filter((User.email == admin_email) | (User.username == admin_username))
            .first()
        )

        if existing_admin:
            admin_user = existing_admin
            print(
                f"⚠️ Superadmin already exists with ID {admin_user.id}; updating its organization and subscription state..."
            )
        else:
            print("Encrypting administrative credential key protocols...")
            hashed_password = hash_password(admin_raw_password)

            print("Constructing superadmin root instance target...")
            admin_user = User(
                username=admin_username,
                email=admin_email,
                first_name=admin_firstname,
                last_name=admin_lastname,
                hashed_password=hashed_password,
                role=UserRole.SUPERADMIN.value,
                is_active=True,
                email_verified_at=func.now(),
            )

            session.add(admin_user)
            session.flush()

        # 2. Verify or Create Organization
        admin_org_name = getattr(settings, "ADMIN_ORG_NAME", "Greenlight Platform")
        admin_org_industry = getattr(settings, "ADMIN_ORG_INDUSTRY", "platform")

        existing_org = (
            session.query(Organization)
            .filter(
                (Organization.owner_id == admin_user.id)
                | (Organization.name == admin_org_name)
            )
            .first()
        )

        if existing_org:
            print(
                f"⚠️ Organization seeding skipped: organization already exists (ID: {existing_org.id})"
            )
            admin_org = existing_org
        else:
            print("Constructing platform organization for the superadmin...")
            admin_org = Organization(
                name=admin_org_name,
                industry=admin_org_industry,
                owner_id=admin_user.id,
                is_verified=True,
            )
            session.add(admin_org)
            session.flush()

        # 3. Establish bidirectional links between User and Org
        if getattr(admin_user, "organization_id", None) != admin_org.id:
            admin_user.organization_id = admin_org.id
            session.add(admin_user)
            session.flush()

        # 4. Handle Wallet Setup (Unified: containing both org_id and user_id)
        # Check if a wallet exists linked to either this user or this organization
        existing_wallet = (
            session.query(Wallet)
            .filter(
                (Wallet.user_id == admin_user.id) | (Wallet.organization_id == admin_org.id)
            )
            .first()
        )

        if existing_wallet:
            print(f"Wallet already exists (ID: {existing_wallet.id}). Verifying relations...")
            # Ensure both relationships are bound to this existing wallet
            updated = False
            if existing_wallet.user_id != admin_user.id:
                existing_wallet.user_id = admin_user.id
                updated = True
            if existing_wallet.organization_id != admin_org.id:
                existing_wallet.organization_id = admin_org.id
                updated = True

            if updated:
                session.add(existing_wallet)
                session.flush()
        else:
            print("Creating single, unified wallet for Superadmin User and Organization...")
            admin_wallet = Wallet(
                user_id=admin_user.id,
                organization_id=admin_org.id,
                currency="gbp"
            )
            session.add(admin_wallet)
            session.flush()

        # 5. Handle Subscription Plans
        default_plan = (
            session.query(SubscriptionPlan)
            .filter(SubscriptionPlan.plan_type == SubscriptionPlanType.PRO)
            .first()
        )

        if not default_plan:
            print(
                "❌ No existing PRO subscription plan found. Skipping subscription creation for the organization."
            )
        else:
            print(
                f"Creating Pro subscription for organization ID {admin_org.id} via shared subscription service..."
            )
            SubscriptionService.create_subscription(
                db=session,
                organization_id=admin_org.id,
                plan_id=default_plan.id,
            )

        session.commit()
        print(
            f"🚀 Success! Superadmin account generated cleanly with User ID: {admin_user.id}"
        )

    except Exception as e:
        session.rollback()
        print(f"❌ Error occurred during data seeder execution lifecycle: {e}")
        sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        sys.exit(1)
    finally:
        session.close()


if __name__ == "__main__":
    seed_superadmin()
