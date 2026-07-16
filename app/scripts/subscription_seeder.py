import os
import sys
import logging

# Setup path before imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import stripe # type: ignore

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.subscription import SubscriptionPlan, SubscriptionPlanType

from dotenv import load_dotenv
load_dotenv(dotenv_path=".env.docker")
load_dotenv(dotenv_path=".env")

logger = logging.getLogger(__name__)

# Configure logging
logging.basicConfig(level=logging.INFO)


def seed_subscription_plans():
    """Seeds the default subscription plans (Free, Standard, Pro) using Stripe."""

    stripe_key = settings.STRIPE_SECRET_KEY
    if not stripe_key:
        print("⚠️  Warning: STRIPE_SECRET_KEY is not configured. Stripe products will be skipped.")
    else:
        stripe.api_key = stripe_key

    session = SessionLocal()

    try:
        print("🔄 Connecting to database...")
        print("📦 Preparing to seed subscription plans...")

        plans_config = [
            {
                "name": "Free",
                "plan_type": SubscriptionPlanType.FREE,
                "description": "Perfect for getting started with interactive quizzes",
                "price": 0.00,
                "currency": "gbp",
                "interval": "month",
                "max_players": 10,
                "max_arenas": 3,
                "max_custom_themes": 1,
                "api_access": False,
                "analytics": False,
                "white_label": False,
                "priority_support": False,
                "ai_tokens": 500,
                "display_order": 1,
            },
            {
                "name": "Standard",
                "plan_type": SubscriptionPlanType.STANDARD,
                "description": "Great for educators and small teams",
                "price": 14.99,
                "currency": "gbp",
                "interval": "month",
                "max_players": 500,
                "max_arenas": 50,
                "max_custom_themes": 10,
                "api_access": True,
                "analytics": True,
                "white_label": False,
                "priority_support": False,
                "ai_tokens": 10000,
                "display_order": 2,
            },
            {
                "name": "Pro",
                "plan_type": SubscriptionPlanType.PRO,
                "description": "For large organizations and enterprises",
                "price": 49.99,
                "currency": "gbp",
                "interval": "month",
                "max_players": None,
                "max_arenas": None,
                "max_custom_themes": None,
                "api_access": True,
                "analytics": True,
                "white_label": True,
                "priority_support": True,
                "ai_tokens": 100000, 
                "display_order": 3,
            },
        ]

        for plan_config in plans_config:
            plan_name = plan_config["name"]
            print(f"\n📋 Processing {plan_name} plan...")

            # Check if plan already exists
            existing_plan = session.query(SubscriptionPlan).filter(
                SubscriptionPlan.plan_type == plan_config["plan_type"]
            ).first()

            if existing_plan:
                print(f"   ⚠️  {plan_name} plan already exists (ID: {existing_plan.id})")
                continue

            # Create Stripe product and price (skip for free plan)
            stripe_product_id = None
            stripe_price_id = None

            if plan_config["price"] > 0:
                if not stripe_key:
                    print(" ⚠️ Skipping Stripe creation (key not configured)")
                else:
                    print(f"   🔗 Creating Stripe product for {plan_name}...")
                    try:
                        product = stripe.Product.create(
                            name=f"Greenlight {plan_name} Plan",
                            description=plan_config["description"],
                            metadata={
                                "plan_type": plan_config["plan_type"],
                                "max_players": plan_config.get("max_players", "unlimited"),
                                "max_arenas": plan_config.get("max_arenas", "unlimited"),
                            },
                        )
                        stripe_product_id = product.id
                        print(f"      ✅ Product created: {stripe_product_id}")

                        print(f"   🔗 Creating Stripe price for {plan_name}...")
                        price = stripe.Price.create(
                            product=stripe_product_id,
                            unit_amount=int(plan_config["price"] * 100),  # Convert to cents
                            currency=plan_config["currency"],
                            recurring={
                                "interval": plan_config["interval"],
                                "interval_count": 1,
                            },
                            metadata={
                                "plan_type": plan_config["plan_type"],
                            },
                        )
                        stripe_price_id = price.id
                        print(f"      ✅ Price created: {stripe_price_id}")

                    except Exception as e:
                        print(f"   ❌ Stripe error: {str(e)}")
                        # Continue without Stripe IDs rather than failing
            else:
                print("   ℹ️  Skipping Stripe creation for Free plan")

            # Create database record
            print(f"   💾 Creating database record for {plan_name}...")
            plan = SubscriptionPlan(
                name=plan_config["name"],
                plan_type=plan_config["plan_type"],
                description=plan_config["description"],
                price=plan_config["price"],
                currency=plan_config["currency"],
                interval=plan_config["interval"],
                stripe_product_id=stripe_product_id,
                stripe_price_id=stripe_price_id,
                max_players=plan_config.get("max_players"),
                max_arenas=plan_config.get("max_arenas"),
                max_custom_themes=plan_config.get("max_custom_themes"),
                api_access=plan_config.get("api_access", False),
                analytics=plan_config.get("analytics", False),
                white_label=plan_config.get("white_label", False),
                priority_support=plan_config.get("priority_support", False),
                ai_tokens=plan_config.get("ai_tokens", 0),
                display_order=plan_config.get("display_order", 0),
                is_active=True,
            )

            session.add(plan)
            session.flush()
            print(f"      ✅ Database record created (ID: {plan.id})")

        session.commit()
        print("\n🎉 Success! All subscription plans have been seeded:")
        print("   ✅ Free Plan - £0/month")
        print("   ✅ Standard Plan - £14.99/month")
        print("   ✅ Pro Plan - £49.99/month")

    except Exception as e:
        session.rollback()
        print(f"\n❌ Error occurred during seeding: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        session.close()


if __name__ == "__main__":
    seed_subscription_plans()
