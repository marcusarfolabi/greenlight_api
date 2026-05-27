"""
Token usage tracking for AI operations
"""
import logging
from typing import Optional
from sqlalchemy.orm import Session

from app.models.subscription import Subscription
from app.core.config import settings

logger = logging.getLogger(__name__)


class TokenService:
    """Service for managing AI token operations"""

    @staticmethod
    def get_organization_tokens(db: Session, organization_id: int) -> dict:
        """Get token information for an organization"""
        subscription = db.query(Subscription).filter(
            Subscription.organization_id == organization_id,
            Subscription.status == "active"
        ).first()

        if not subscription:
            return {
                "total_tokens": 0,
                "used_tokens": 0,
                "remaining_tokens": 0,
                "plan_name": "None",
                "has_tokens": False
            }

        # Get token usage from arenas
        from app.models.arena import Arena

        total_used = db.query(Arena).filter(
            Arena.creator_organization_id == organization_id
        ).with_entities(
            db.func.sum(Arena.ai_tokens_used).label("total")
        ).scalar() or 0

        remaining = subscription.plan.ai_tokens - total_used

        return {
            "total_tokens": subscription.plan.ai_tokens,
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
        """Check if organization has enough tokens"""
        token_info = TokenService.get_organization_tokens(db, organization_id)

        if not token_info["has_tokens"]:
            return False, "No active subscription with AI tokens"

        if token_info["remaining_tokens"] < tokens_required:
            return False, f"Insufficient tokens. Required: {tokens_required}, Available: {token_info['remaining_tokens']}"

        return True, None

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
        arena_id: int,
        tokens_used: int,
        operation: str = "question_generation"
    ) -> None:
        """Log token usage for auditing"""
        from app.models.arena import ArenaTokenUsageLog

        usage_log = ArenaTokenUsageLog(
            arena_id=arena_id,
            tokens_used=tokens_used,
            operation=operation
        )
        db.add(usage_log)
        db.commit()
        logger.info(f"Logged {tokens_used} tokens for arena {arena_id} ({operation})")
