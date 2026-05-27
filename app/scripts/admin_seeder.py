import os
import sys

# Setup path before imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.core.config import settings
from app.db.session import SessionLocal 
from app.models.user import User, UserRole
from app.models.wallet import Wallet

def mock_hash_password(password: str) -> str:
    """Fallback hashing method. 
    Replace this implementation with your project's security utils function."""
    return f"hashed_{password}"


def seed_superadmin():
    """Seeds the default system superadmin and corresponding operational platform wallet
    using credentials automatically loaded by the application config layer from environment variables."""
    
    admin_username = getattr(settings, "ADMIN_USERNAME", "superadmin")
    admin_email = getattr(settings, "ADMIN_EMAIL", "admin@greenlight.app")
    admin_raw_password = getattr(settings, "ADMIN_PASSWORD", "admin@123")

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
        hashed_password = mock_hash_password(admin_raw_password)

        print("Constructing superadmin root instance target...")
        admin_user = User(
            username=admin_username,
            email=admin_email,
            hashed_password=hashed_password,
            role=UserRole.SUPERADMIN,
            is_active=True
        )
        
        session.add(admin_user)
        session.flush()

        print(f"Initializing standard core system user wallet (Target ID: {admin_user.id})...")
        admin_wallet = Wallet(
            user_id=admin_user.id,
            balance=0,
            currency="usd"
        )
        session.add(admin_wallet)

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