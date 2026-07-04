import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.core.config import settings
from app.core.security import hash_password
from app.db.session import SessionLocal 
from app.models.user import User, UserRole
from app.models.wallet import Wallet
from app.models.organization import Organization
from app.models.subscription import Subscription, SubscriptionPlan, SubscriptionPlanType


def seed_superadmin():
    """Seeds the default system superadmin and corresponding operational platform wallet
    using credentials automatically loaded by the application config layer from environment variables."""
    
    admin_username = getattr(settings, "ADMIN_USERNAME", "superadmin")
    admin_email = getattr(settings, "ADMIN_EMAIL", "admin@greenlight.app")
    admin_firstname = getattr(settings, "ADMIN_FIRSTNAME", "Moses")
    admin_lastname = getattr(settings, "ADMIN_LASTNAME", "David")
    admin_raw_password = getattr(settings, "ADMIN_PASSWORD", ".Admin!Green@151k")

    print("Connecting to database using application settings configuration...")
    session = SessionLocal()

    try:
        print(f"Verifying existence of superadmin account: '{admin_username}' ({admin_email})...")
        
        existing_admin = session.query(User).filter(
            (User.email == admin_email) | (User.username == admin_username)
        ).first()

        if existing_admin:
            print(f"⚠️ Seeding skipped: Superadmin user already exists with ID {existing_admin.id}")
            return

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
            is_active=True
        )
        
        session.add(admin_user)
        session.flush()

        print(f"Initializing standard core system user wallet (Target ID: {admin_user.id})...")
        admin_wallet = Wallet(
            user_id=admin_user.id, 
            currency="gbp"
        )
        session.add(admin_wallet)

        admin_org_name = getattr(settings, "ADMIN_ORG_NAME", "Greenlight Platform")
        admin_org_subdomain = getattr(settings, "ADMIN_ORG_SUBDOMAIN", "greenlight")
        admin_org_industry = getattr(settings, "ADMIN_ORG_INDUSTRY", "platform")

        print(f"Verifying existence of an organization for superadmin (subdomain: '{admin_org_subdomain}')...")
        existing_org = session.query(Organization).filter(
            (Organization.owner_id == admin_user.id) | (Organization.subdomain == admin_org_subdomain)
        ).first()

        if existing_org:
            print(f"⚠️ Organization seeding skipped: organization already exists (ID: {existing_org.id})")
            admin_org = existing_org
        else:
            print("Constructing platform organization for the superadmin...")
            admin_org = Organization(
                name=admin_org_name,
                subdomain=admin_org_subdomain,
                industry=admin_org_industry,
                owner_id=admin_user.id,
                is_verified=True,
            )
            session.add(admin_org)
            session.flush()

        # Ensure the superadmin user is linked to this organization
        if getattr(admin_user, "organization_id", None) != admin_org.id:
            admin_user.organization_id = admin_org.id
            session.add(admin_user)
            session.flush()

        existing_org_wallet = session.query(Wallet).filter(Wallet.user_id == admin_user.id).first()
        if existing_org_wallet:
            print(f"⚠️ Organization wallet already exists (Wallet ID: {existing_org_wallet.id}). Linking to organization...")
            existing_org_wallet.organization_id = admin_org.id
            session.add(existing_org_wallet) 

        # ===== Attach existing PRO subscription plan to the organization =====
        print("Looking up existing PRO subscription plan...")
        default_plan = session.query(SubscriptionPlan).filter(SubscriptionPlan.plan_type == SubscriptionPlanType.PRO).first()

        if not default_plan:
            print("❌ No existing PRO subscription plan found. Skipping subscription creation for the organization.")
        else:
            print(f"Checking existing subscription for organization ID {admin_org.id}...")
            existing_sub = session.query(Subscription).filter(Subscription.organization_id == admin_org.id).first()

            if existing_sub:
                print(f"⚠️ Subscription seeding skipped: subscription already exists (ID: {existing_sub.id})")
            else:
                print("Creating subscription for the organization using existing PRO plan...")
                org_subscription = Subscription(
                    organization_id=admin_org.id,
                    plan_id=default_plan.id,
                    status="active",
                )
                session.add(org_subscription)

        session.commit()
        print(f"🚀 Success! Superadmin account generated cleanly with User ID: {admin_user.id}")

    except Exception as e:
        session.rollback()
        print(f"❌ Error occurred during data seeder execution lifecycle: {e}")
        sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        sys.exit(1)
    finally:
        session.close()


if __name__ == "__main__":
    seed_superadmin()