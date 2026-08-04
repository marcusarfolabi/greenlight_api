import logging

from fastapi import APIRouter, Depends, Query
from sqlalchemy import desc, func
from sqlalchemy.orm import Session

from app.core.security import require_superadmin
from app.db.session import get_db
from app.models.arena import Arena
from app.models.organization import Organization
from app.models.player import Player
from app.models.subscription import Subscription
from app.models.subscription import SubscriptionPlan as Plan
from app.models.user import User, UserRole
from app.models.wallet import Transaction, TransactionType, Wallet
from app.schemas.user import AuthContext

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/overview")
async def admin_overview(
    current_user: AuthContext = Depends(require_superadmin),
    db: Session = Depends(get_db),
    org_id: int | None = Query(
        None, description="Optional organization id to scope the overview"
    ),
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
        total_hosts = (
            db.query(func.count(User.id)).filter(User.role == "host").scalar() or 0
        )
    else:
        total_hosts = (
            db.query(func.count(User.id))
            .filter(User.organization_id == org_id)
            .scalar()
            or 0
        )

    # Total arenas
    if org_id:
        total_arenas = db.query(func.count(Arena.id)).scalar() or 0
    else:
        total_arenas = (
            db.query(func.count(Arena.id))
            .filter(Arena.creator_organization_id == org_id)
            .scalar()
            or 0
        )

    # Total players
    if org_id:
        total_players = db.query(func.count(Player.id)).scalar() or 0
    else:
        total_players = (
            db.query(func.count(Player.id))
            .filter(Player.organization_id == org_id)
            .scalar()
            or 0
        )

    # Live arenas: distinct arenas that have at least one player
    qa = db.query(func.count(func.distinct(Arena.id))).join(
        Player, Player.arena_id == Arena.id
    )
    if org_id:
        qa = qa.filter(Arena.creator_organization_id == org_id)
    live_arenas = qa.scalar() or 0

    return {
        "org_id": org_id,
        "total_hosts": int(total_hosts),
        "total_arenas": int(total_arenas),
        "total_players": int(total_players),
        "live_arenas": int(live_arenas),
    }


@router.get("/arenas")
async def list_all_arenas(
    skip: int = 0,
    limit: int = 10,
    current_user: AuthContext = Depends(require_superadmin),
    db: Session = Depends(get_db),
):
    """List arenas created by the current user"""
    arenas = (
        db.query(Arena).order_by(desc(Arena.updated_at)).offset(skip).limit(limit).all()
    )

    results = []
    for a in arenas:
        total_players = db.query(Player).filter(Player.arena_id == a.id).count()
        total_questions = len(a.questions) if a.questions else 0

        results.append(
            {
                "id": a.id,
                "arena_name": a.arena_name,
                "is_public": a.is_public,
                "creator_id": a.creator_id,
                "creator_organization_id": a.creator_organization_id,
                "access_code": a.access_code,
                "created_at": a.created_at,
                "updated_at": a.updated_at,
                "ai_tokens_used": a.ai_tokens_used,
                "total_questions": total_questions,  # Count returned here
                "total_players": total_players,
            }
        )

    return results


@router.get("/users", response_model=list[dict])
async def list_users_by_role(
    role: UserRole | None = Query(
        None, description="Filter users by their account role"
    ),
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
        if role == UserRole.HOST:
            query = query.filter(User.organization_id.isnot(None))

    # 3. Paginate and execute the query
    users = query.order_by(desc(User.updated_at)).offset(skip).limit(limit).all()

    results = []
    for u in users:
        results.append(
            {
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
            }
        )

    return results


# get the detail of a user by id
@router.get("/users/{user_id}", response_model=dict)
async def get_user_detail(
    user_id: int,
    current_user: AuthContext = Depends(require_superadmin),
    db: Session = Depends(get_db),
):
    """
    Return detailed information for a user. Hosts receive organization, subscription,
    arenas, players, and revenue details. Non-host users receive player-related
    activity details such as joined arenas and scores.
    """
    user = db.query(User).filter(User.id == user_id).first()

    if not user:
        return {"error": "User not found"}

    base_payload = {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "phone_number": user.phone_number,
        "location": user.location,
        "avatar": user.avatar,
        "organization_id": user.organization_id,
        "role": user.role,
        "is_active": user.is_active,
        "created_at": user.created_at,
        "updated_at": user.updated_at,
    }

    if user.role == "host":
        organization = None
        if user.organization_id is not None:
            organization = (
                db.query(Organization)
                .filter(Organization.id == user.organization_id)
                .first()
            )
        elif user.owned_organization:
            organization = user.owned_organization

        subscription = None
        if organization is not None:
            subscription = (
                db.query(Subscription)
                .join(Plan, Subscription.plan_id == Plan.id)
                .filter(Subscription.organization_id == organization.id)
                .order_by(desc(Subscription.created_at))
                .first()
            )

        arenas = []
        players = []
        wallet = None
        transactions = []

        if organization is not None:
            arenas = (
                db.query(Arena)
                .filter(Arena.creator_organization_id == organization.id)
                .order_by(desc(Arena.updated_at))
                .all()
            )
            players = (
                db.query(Player)
                .filter(Player.organization_id == organization.id)
                .order_by(desc(Player.attempt_date))
                .all()
            )
            wallet = (
                db.query(Wallet)
                .filter(Wallet.organization_id == organization.id)
                .first()
            )
            transactions = (
                db.query(Transaction)
                .join(Wallet, Transaction.wallet_id == Wallet.id)
                .filter(Wallet.organization_id == organization.id)
                .order_by(desc(Transaction.created_at))
                .limit(20)
                .all()
            )

        return {
            **base_payload,
            "organization": {
                "id": organization.id,
                "name": organization.name,
                "industry": organization.industry,
                "is_verified": organization.is_verified,
                "created_at": organization.created_at,
                "updated_at": organization.updated_at,
            }
            if organization
            else None,
            "subscription": {
                "id": subscription.id,
                "status": subscription.status,
                "plan_id": subscription.plan_id,
                "plan_name": subscription.plan.name if subscription.plan else None,
                "started_at": subscription.started_at,
                "current_period_start": subscription.current_period_start,
                "current_period_end": subscription.current_period_end,
            }
            if subscription
            else None,
            "arenas": [
                {
                    "id": arena.id,
                    "arena_name": arena.arena_name,
                    "is_public": arena.is_public,
                    "access_code": arena.access_code,
                    "created_at": arena.created_at,
                    "updated_at": arena.updated_at,
                    "total_questions": len(arena.questions) if arena.questions else 0,
                    "total_players": db.query(Player)
                    .filter(Player.arena_id == arena.id)
                    .count(),
                }
                for arena in arenas
            ],
            "players": [
                {
                    "id": player.id,
                    "username": player.username,
                    "arena_id": player.arena_id,
                    "status": player.status,
                    "score": player.score,
                    "answers_submitted": player.answers_submitted,
                    "correct_answers": player.correct_answers,
                    "rank": player.rank,
                    "attempt_date": player.attempt_date,
                    "completed_at": player.completed_at,
                }
                for player in players
            ],
            "revenue": {
                "balance": wallet.balance if wallet else 0,
                "pending_balance": wallet.pending_balance if wallet else 0,
                "currency": wallet.currency if wallet else None,
                "transactions": [
                    {
                        "id": transaction.id,
                        "amount": transaction.amount,
                        "type": transaction.type.value
                        if hasattr(transaction.type, "value")
                        else transaction.type,
                        "status": transaction.status,
                        "description": transaction.description,
                        "created_at": transaction.created_at,
                    }
                    for transaction in transactions
                ],
            },
        }

    player_accounts = (
        db.query(Player)
        .filter(
            (Player.username == user.username)
            | (Player.username == user.email)
            | (Player.username == (user.first_name or ""))
        )
        .order_by(desc(Player.attempt_date))
        .all()
    )

    if not player_accounts and user.organization_id is not None:
        player_accounts = (
            db.query(Player)
            .filter(Player.organization_id == user.organization_id)
            .order_by(desc(Player.attempt_date))
            .all()
        )

    return {
        **base_payload,
        "player_profile": {
            "player_accounts": [
                {
                    "id": player.id,
                    "arena_id": player.arena_id,
                    "organization_id": player.organization_id,
                    "status": player.status,
                    "score": player.score,
                    "answers_submitted": player.answers_submitted,
                    "correct_answers": player.correct_answers,
                    "rank": player.rank,
                    "attempt_date": player.attempt_date,
                    "completed_at": player.completed_at,
                }
                for player in player_accounts
            ],
            "total_arenas_played": len(player_accounts),
            "completed_arenas": sum(
                1 for player in player_accounts if player.status == "completed"
            ),
            "total_score": sum(player.score or 0 for player in player_accounts),
            "last_attempt": (
                max((player.attempt_date for player in player_accounts), default=None)
            ),
        },
    }


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
        results.append(
            {
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
            }
        )

    return results


# list transactions generation by organization with pagination
@router.get("/revenue", response_model=list[dict])
async def list_revenue_by_organization(
    skip: int = 0,
    limit: int = 10,
    current_user: AuthContext = Depends(require_superadmin),
    db: Session = Depends(get_db),
):
    """
    List organization-level money movement with pagination.

    Each item includes the organization summary plus a detailed transaction ledger
    so admins can see how funds are flowing in and out.
    """
    organizations = (
        db.query(Organization)
        .order_by(desc(Organization.created_at))
        .offset(skip)
        .limit(limit)
        .all()
    )

    results: list[dict] = []

    for org in organizations:
        wallet = db.query(Wallet).filter(Wallet.organization_id == org.id).first()

        transactions = []
        incoming_total = 0
        outgoing_total = 0
        net_total = 0

        if wallet:
            wallet_transactions = (
                db.query(Transaction)
                .filter(Transaction.wallet_id == wallet.id)
                .order_by(desc(Transaction.created_at))
                .all()
            )

            for tx in wallet_transactions:
                amount = int(tx.amount or 0)
                if amount > 0:
                    incoming_total += amount
                elif amount < 0:
                    outgoing_total += abs(amount)

                net_total += amount

                tx_type = (
                    tx.type.value if isinstance(tx.type, TransactionType) else tx.type
                )
                transactions.append(
                    {
                        "id": tx.id,
                        "amount": amount,
                        "type": tx_type,
                        "status": tx.status,
                        "description": tx.description,
                        "stripe_reference": tx.stripe_reference,
                        "created_at": tx.created_at,
                    }
                )

        results.append(
            {
                "organization_id": org.id,
                "organization_name": org.name,
                "industry": org.industry,
                "currency": wallet.currency if wallet else "gbp",
                "current_balance": wallet.balance if wallet else 0,
                "pending_balance": wallet.pending_balance if wallet else 0,
                "total_incoming": incoming_total,
                "total_outgoing": outgoing_total,
                "net_amount": net_total,
                "transaction_count": len(transactions),
                "last_transaction_at": transactions[0]["created_at"]
                if transactions
                else None,
                "transactions": transactions,
            }
        )

    return results
