"""
Token usage tracking for AI operations
"""
import logging
from typing import Optional, Union
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.arena import Arena
from app.models.user import User
from app.models.subscription import Subscription
from app.core.config import settings
from app.models.organization import Organization

logger = logging.getLogger(__name__)


class TokenService:
    """Service for managing AI token operations"""

    @staticmethod
    def get_organization_tokens(db: Session, organization_id: int) -> dict:
        """Get token information for an organization based on current subscription cycle"""
        
        organization = db.query(Organization).filter(Organization.id == organization_id).first()
        if not organization:
            return {
                "total_tokens": 0, "used_tokens": 0, "remaining_tokens": 0,
                "plan_name": "None", "plan_type": "None", "has_tokens": False
            }

        subscription = db.query(Subscription).filter(
            Subscription.organization_id == organization_id,
            Subscription.status == "active"
        ).first()

        if not subscription:
            return {
                "total_tokens": 0, "used_tokens": 0, "remaining_tokens": 0,
                "plan_name": "None", "plan_type": "None", "has_tokens": False
            }

        from app.models.arena import Arena, ArenaTokenUsageLog 
        cycle_start = subscription.current_period_start
 
        total_used_in_arenas = db.query(Arena).filter(
            Arena.creator_organization_id == organization_id,
            Arena.created_at >= cycle_start  
        ).with_entities(
            func.sum(Arena.ai_tokens_used).label("total")
        ).scalar() or 0

        preview_used = db.query(func.coalesce(func.sum(ArenaTokenUsageLog.tokens_used), 0)).filter(
            ArenaTokenUsageLog.organization_id == organization_id,
            ArenaTokenUsageLog.operation == "ai_question_generation_preview",
            ArenaTokenUsageLog.created_at >= cycle_start  
        ).scalar() or 0

        total_used = total_used_in_arenas + preview_used
        
        total_pool = organization.capped_tokens or subscription.plan.ai_tokens
        remaining = total_pool - total_used

        return {
            "total_tokens": total_pool,
            "used_tokens": total_used,
            "remaining_tokens": max(0, remaining),
            "plan_name": subscription.plan.name,
            "plan_type": subscription.plan.plan_type,
            "has_tokens": remaining > 0
        }
        
    @staticmethod
    def can_use_tokens(
        db: Session,
        organization_id: int,
        tokens_required: int
    ) -> tuple[bool, Optional[str]]:
        """Check if organization has enough tokens for an incoming request"""
        token_info = TokenService.get_organization_tokens(db, organization_id) 
        if token_info["plan_name"] == "None" or token_info["total_tokens"] == 0:
            return False, "No active subscription with AI tokens found."

        if token_info["remaining_tokens"] < tokens_required:
            return False, (
                f"Insufficient tokens. Required: {tokens_required}, "
                f"Available: {token_info['remaining_tokens']}"
            )

        return True, None

    @staticmethod
    def deduct_tokens(db: Session, org_id: int, amount: int) -> bool:
        """
        Atomically deducts tokens. Returns False if insufficient funds or account missing.
        """
        org = db.query(Organization).filter(Organization.id == org_id).with_for_update().first()
        
        if not org:
            logger.warning(f"Deduction failed: Organization {org_id} not found.")
            return False
            
        current_balance = org.capped_tokens if org.capped_tokens is not None else 0
        
        if current_balance < amount:
            logger.warning(
                f"Deduction failed for org {org_id}: "
                f"Required {amount}, available {current_balance}."
            )
            return False
            
        org.capped_tokens = current_balance - amount
        db.add(org)
        
        try:
            db.commit()
            return True
        except Exception as e:
            db.rollback()
            logger.error(f"Failed to commit token deduction for org {org_id}: {str(e)}")
            return False
    
    @staticmethod
    def calculate_question_cost(
        prompt_length: int,
        num_options: int,
        use_ai_generation: bool = True
    ) -> int:
        """
        Calculate token cost for a question
        
        Base cost: 50 tokens per question
        Additional: 1 token per 100 characters in prompt
        Additional: 10 tokens per option
        """
        if not use_ai_generation:
            return 0

        base_cost = 50
        prompt_cost = max(1, prompt_length // 100)
        options_cost = num_options * 10

        return base_cost + prompt_cost + options_cost

    @staticmethod
    def log_token_usage(
        db: Session,
        arena_id: Optional[str], # Keeps support for your UUID string
        tokens_used: int,
        operation: str = "question_generation",
        organization_id: Optional[int] = None,
    ) -> None:
        """Log token usage for auditing and dynamic balance tracking"""
        from app.models.arena import Arena, ArenaTokenUsageLog

        # 1. Self-healing logic: If organization_id is missing but arena_id exists, look it up
        if not organization_id and arena_id:
            arena = db.query(Arena).filter(Arena.id == arena_id).first()
            if arena:
                organization_id = arena.creator_organization_id

        # 2. Prevent creating completely orphaned usage logs that ruin accounting
        if not organization_id:
            logger.error(
                f"Failed to log token usage: No organization_id provided or found "
                f"for arena_id {arena_id}."
            )
            return

        try:
            usage_log = ArenaTokenUsageLog(
                arena_id=arena_id,
                organization_id=organization_id,
                tokens_used=tokens_used,
                operation=operation,
            )
            db.add(usage_log)
            db.commit()
            
            logger.info(
                f"Logged {tokens_used} tokens for org {organization_id}, "
                f"arena {arena_id} ({operation})"
            )
        except Exception as e:
            db.rollback()
            logger.error(f"Failed to commit token usage log: {str(e)}")
            
    @staticmethod
    def can_create_arena(db: Session, organization_id: int) -> tuple[bool, Optional[str]]:
        """Check if organization can create a new arena based on subscription limits"""
        subscription = db.query(Subscription).filter(
            Subscription.organization_id == organization_id,
            Subscription.status == "active"
        ).first()

        if not subscription:
            return False, "No active subscription"

        arena_count = db.query(Arena).filter(
            Arena.creator_organization_id == organization_id
        ).count()

        if subscription.plan.max_arenas is not None and arena_count >= subscription.plan.max_arenas:
            return False, f"Arena limit reached. Max allowed: {subscription.plan.max_arenas}"

        return True, None
    
    # determine if the organization can add more players according to their subscription plan
    @staticmethod
    def can_add_players(db: Session, organization_id: int, additional_players: int) -> tuple[bool, Optional[str]]:
        """Check if organization can add more players based on subscription limits"""
        subscription = db.query(Subscription).filter(
            Subscription.organization_id == organization_id,
            Subscription.status == "active"
        ).first()

        if not subscription:
            return False, "No active subscription"

        current_player_count = db.query(User).filter(
            User.organization_id == organization_id
        ).count()

        if subscription.plan.max_players is not None and (current_player_count + additional_players) > subscription.plan.max_players:
            return False, f"Player limit reached. Max allowed: {subscription.plan.max_players}"

        return True, None
