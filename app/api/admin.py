import logging
from typing import Optional
from app.schemas.arena import ArenaResponse
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import desc, func, cast, Integer

from app.db.session import get_db
from app.schemas.user import AuthContext
from app.core.security import require_superadmin
from app.models.user import User
from app.models.arena import Arena
from app.models.player import Player
from app.models.wallet import Wallet, Transaction
from app.models.subscription import Subscription
from app.models.subscription import SubscriptionPlan as Plan
from app.models.organization import Organization
from enum import Enum

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/overview")
async def admin_overview(
    current_user: AuthContext = Depends(require_superadmin),
    db: Session = Depends(get_db),
    org_id: Optional[int] = Query(None, description="Optional organization id to scope the overview"),
):
    """Return aggregated organization-level overview stats for admin dashboard.

    If `org_id` is provided the stats are scoped to that organization. Otherwise
    aggregates across all organizations are returned.
    """

    # If org_id not provided attempt to use the user's owned organization as fallback
    if org_id is None:
        user = db.query(User).filter(User.id == current_user.user_id).first()
        if user and user.owned_organization:
            org_id = user.owned_organization.id

    # Total hosts: per-org -> members count, global -> count of host users
    if org_id:
        total_hosts = db.query(func.count(User.id)).filter(User.organization_id == org_id).scalar() or 0
    else:
        total_hosts = db.query(func.count(User.id)).filter(User.role == "host").scalar() or 0

    # Total arenas
    if org_id:
        total_arenas = db.query(func.count(Arena.id)).filter(Arena.creator_organization_id == org_id).scalar() or 0
    else:
        total_arenas = db.query(func.count(Arena.id)).scalar() or 0

    # Total players
    if org_id:
        total_players = db.query(func.count(Player.id)).filter(Player.organization_id == org_id).scalar() or 0
    else:
        total_players = db.query(func.count(Player.id)).scalar() or 0

    # Live arenas: distinct arenas that have at least one player
    qa = db.query(func.count(func.distinct(Arena.id))).join(Player, Player.arena_id == Arena.id)
    if org_id:
        qa = qa.filter(Arena.creator_organization_id == org_id)
    live_arenas = qa.scalar() or 0

    # Completion rate: average of per-arena completion percentages
    q = db.query(
        Player.arena_id.label("arena_id"),
        func.count(Player.id).label("total"),
        func.sum(cast((Player.status == "completed"), Integer)).label("completed"),
    )
    if org_id:
        q = q.filter(Player.organization_id == org_id)
    rows = q.group_by(Player.arena_id).all()

    completion_rate = 0
    if rows:
        total_rate = 0.0
        for r in rows:
            if r.total and r.total > 0:
                total_rate += (r.completed or 0) / r.total * 100
        completion_rate = round(total_rate / len(rows))

    # Wallet / revenue summary (best-effort)
    if org_id:
        wallet = db.query(Wallet).filter(Wallet.organization_id == org_id).first()
        if wallet:
            wallet_balance = wallet.balance or 0
            currency = wallet.currency
            total_revenue = (
                db.query(func.coalesce(func.sum(Transaction.amount), 0))
                .filter(Transaction.wallet_id == wallet.id, Transaction.amount > 0, Transaction.status == "completed")
                .scalar() or 0
            )
        else:
            wallet_balance = 0
            currency = Wallet.currency.default.arg if hasattr(Wallet.currency, "default") else None
            total_revenue = 0
    else:
        wallet_balance = db.query(func.coalesce(func.sum(Wallet.balance), 0)).scalar() or 0
        currency = Wallet.currency.default.arg if hasattr(Wallet.currency, "default") else None
        total_revenue = (
            db.query(func.coalesce(func.sum(Transaction.amount), 0))
            .filter(Transaction.amount > 0, Transaction.status == "completed")
            .scalar() or 0
        )

    return {
        "org_id": org_id,
        "total_hosts": int(total_hosts),
        "total_arenas": int(total_arenas),
        "total_players": int(total_players),
        "live_arenas": int(live_arenas),
        "completion_rate": int(completion_rate),
        "wallet": {
            "balance": int(wallet_balance),
            "currency": currency,
            "total_revenue": int(total_revenue),
        },
    }

@router.get("/arenas", response_model=list[ArenaResponse])
async def list_all_arenas(
    skip: int = 0,
    limit: int = 10,
    current_user: AuthContext = Depends(require_superadmin),
    db: Session = Depends(get_db),
):
    """List arenas created by the current user"""
    arenas = (
        db.query(Arena)
        .order_by(desc(Arena.updated_at))
        .offset(skip)
        .limit(limit)
        .all()
    )

    results = []
    for a in arenas:
        total_players = db.query(Player).filter(Player.arena_id == a.id).count()
        total_questions = len(a.questions) if a.questions else 0

        results.append({
            "id": a.id,
            "arena_name": a.arena_name,
            "category": a.category,
            "is_public": a.is_public,
            "creator_id": a.creator_id,
            "creator_organization_id": a.creator_organization_id,
            "access_code": a.access_code,
            "created_at": a.created_at,
            "updated_at": a.updated_at,
            "ai_tokens_used": a.ai_tokens_used,
            "total_questions": total_questions,  # Count returned here
            "total_players": total_players,
        })

    return results


# 1. Define the permitted roles for validation and automated Swagger dropdowns
class UserRoleFilter(str, Enum):
    USER = "user"
    HOST = "host"
    SUPERADMIN = "superadmin"

@router.get("/users", response_model=list[dict])
async def list_users_by_role(
    role: Optional[UserRoleFilter] = Query(None, description="Filter users by their account role"),
    skip: int = 0,
    limit: int = 10,
    current_user: AuthContext = Depends(require_superadmin),
    db: Session = Depends(get_db),
):
    """
    List users dynamically filtered by role.
    If no role is provided, it returns all users.
    """
    query = db.query(User)

    # 2. Dynamically apply filters based on query selection
    if role:
        query = query.filter(User.role == role.value)

        # Keep your safety constraint: hosts must belong to an organization
        if role == UserRoleFilter.HOST:
            query = query.filter(User.organization_id.isnot(None))

    # 3. Paginate and execute the query
    users = (
        query.order_by(desc(User.updated_at))
        .offset(skip)
        .limit(limit)
        .all()
    )

    results = []
    for u in users:
        results.append({
            "id": u.id,
            "username": u.username,
            "email": u.email,
            "first_name": u.first_name,
            "last_name": u.last_name,
            "phone_number": u.phone_number,
            "location": u.location,
            "avatar": u.avatar,
            "organization_id": u.organization_id,
            "role": u.role,
            "is_active": u.is_active,
            "created_at": u.created_at,
            "updated_at": u.updated_at,
        })

    return results

# list of organizations who have subscription and are active
@router.get("/subscribers", response_model=list[dict])
async def list_organizations_with_subscription(
    # check the subscription model to get them
    skip: int = 0,
    limit: int = 10,
    current_user: AuthContext = Depends(require_superadmin),
    db: Session = Depends(get_db),
):
    """
    List organizations who have an active subscription.
    """
    # Return organization-level subscription info (joins Subscription and Plan)


    query = (
        db.query(Organization, Subscription, Plan)
        .join(Subscription, Subscription.organization_id == Organization.id)
        .join(Plan, Subscription.plan_id == Plan.id)
        .filter(
            Subscription.status == "active",
            Subscription.current_period_start <= func.now(),
            Subscription.current_period_end >= func.now(),
        )
    )

    rows = (
        query.order_by(desc(Subscription.current_period_end))
        .offset(skip)
        .limit(limit)
        .all()
    )

    results: list[dict] = []
    for org, sub, plan in rows:
        results.append({
            "organization": {
                "id": org.id,
                "name": org.name,
                "industry": org.industry,
                "created_at": org.created_at,
                "updated_at": org.updated_at,
            },
            "subscription": {
                "id": sub.id,
                "status": sub.status,
                "started_at": sub.started_at,
                "current_period_start": sub.current_period_start,
                "current_period_end": sub.current_period_end,
                "stripe_subscription_id": sub.stripe_subscription_id,
                "stripe_customer_id": sub.stripe_customer_id,
            },
            "plan": {
                "id": plan.id,
                "name": plan.name,
                "price": plan.price,
                "currency": plan.currency,
                "interval": plan.interval,
            },
        })

    return results
