# Subscription Seeder Implementation

## Overview

I've created a complete Stripe-based subscription system with three Kahoot!-like pricing tiers:

### Subscription Plans

| Plan         | Price     | Players | Arenas | API | Analytics | White Label | Priority Support |
| ------------ | --------- | ------- | ------ | --- | --------- | ----------- | ---------------- |
| **Free**     | $0/mo     | 10      | 3      | ❌  | ❌        | ❌          | ❌               |
| **Standard** | $14.99/mo | 500     | 50     | ✅  | ✅        | ❌          | ❌               |
| **Pro**      | $49.99/mo | ∞       | ∞      | ✅  | ✅        | ✅          | ✅               |

## Files Created

### 1. **Database Models** (`app/models/subscription.py`)

- `SubscriptionPlan` - Defines available subscription tiers
- `Subscription` - Tracks active subscriptions for organizations
- `SubscriptionPlanType` - Enum with FREE, STANDARD, PRO

### 2. **Seeder Script** (`app/scripts/subscription_seeder.py`)

Creates three subscription plans in Stripe and stores IDs in database:

```bash
cd backend
python app/scripts/subscription_seeder.py
```

**What it does:**

- Creates Stripe products for Standard & Pro plans
- Creates Stripe prices for recurring billing
- Stores product/price IDs in database
- Skips if plans already exist

### 3. **API Schemas** (`app/schemas/subscription.py`)

Type-safe Pydantic models for API requests/responses

### 4. **REST API Endpoints** (`app/api/subscription.py`)

```
GET    /v1/subscriptions/plans                    # List all plans
GET    /v1/subscriptions/plans/{plan_id}         # Get single plan
GET    /v1/subscriptions/organization/{org_id}  # Get org's subscription
POST   /v1/subscriptions/                        # Create subscription
```

## Integration

The subscription system has been integrated into your FastAPI application:

- Models registered with SQLAlchemy
- Router included in API
- Full CORS support

## Running the Seeder

**Prerequisites:**

- Python environment configured
- `STRIPE_SECRET_KEY` set in environment
- PostgreSQL database running

**Command:**

```bash
cd backend
python app/scripts/subscription_seeder.py
```

**Expected Output:**

```
📋 Processing Free plan...
   ℹ️  Skipping Stripe creation for Free plan
   💾 Creating database record for Free...
      ✅ Database record created (ID: 1)

📋 Processing Standard plan...
   🔗 Creating Stripe product for Standard...
      ✅ Product created: prod_xxx
   🔗 Creating Stripe price for Standard...
      ✅ Price created: price_xxx
   💾 Creating database record for Standard...
      ✅ Database record created (ID: 2)

[... Pro plan ...]

🎉 Success! All subscription plans have been seeded:
   ✅ Free Plan - $0/month
   ✅ Standard Plan - $14.99/month
   ✅ Pro Plan - $49.99/month
```

## Next Steps (Optional)

To fully integrate subscriptions, you may want to add:

1. **Webhook Handlers** - Listen to Stripe events

   ```python
   # app/api/webhooks.py
   ```

2. **Subscription Management** - Upgrade/downgrade plans

   ```python
   # Add endpoints to change subscriptions
   ```

3. **Feature Gating** - Check plan limits in your routes

   ```python
   # Verify org has required plan features
   ```

4. **Usage Tracking** - Monitor feature usage
   ```python
   # app/models/usage.py
   ```

## Database Tables Created

- `subscription_plans` - Available plan tiers
- `subscriptions` - Active subscriptions linked to organizations

## Example Usage

**Check if org has API access:**

```python
from app.models import Subscription
from app.db.session import SessionLocal

db = SessionLocal()
subscription = db.query(Subscription).filter(
    Subscription.organization_id == org_id,
    Subscription.status == "active"
).first()

if subscription and subscription.plan.api_access:
    # Allow API access
    pass
```
