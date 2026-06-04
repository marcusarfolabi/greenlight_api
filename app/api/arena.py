import logging
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.core.security import get_current_user
from app.schemas.arena import (
    ArenaCreate,
    ArenaResponse,
    ArenaTokenInfo,
    ArenaTokenUsageLogResponse,
    ArenaUpdate,
    ArenaDetailResponse,
    QuestionResponse,
    TokenUsageResponse,
    AIQuestionGenerationRequest,
)
from app.models.arena import Arena, Question, QuestionOption, ArenaTokenUsageLog
from app.models.player import Player
from app.models.user import User
from app.schemas.user import AuthContext
from app.services.token_service import TokenService
from app.services.ai_question_service import AIQuestionGenerationService

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("", response_model=ArenaResponse)
async def create_arena(
    data: ArenaCreate,
    current_user: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create a new arena with questions"""

    # Get user and organization
    user = db.query(User).filter(User.id == current_user.user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )

    # Check if user has organization
    if not user.owned_organization:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User must have an organization to create arenas",
        )

    org_id = user.owned_organization.id
    org = user.owned_organization

    # Calculate total tokens needed for all questions (only if AI is enabled)
    total_tokens_needed = 0
    if org.use_ai_for_arenas:
        total_tokens_needed = sum(
            TokenService.calculate_question_cost(
                len(q.prompt_text), len(q.options), use_ai_generation=q.is_ai_generated
            )
            for q in data.questions
        )

        # Check token availability
        can_use, error_msg = TokenService.can_use_tokens(db, org_id, total_tokens_needed)
        if not can_use:
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED, detail=error_msg
            )

    # Create arena
    new_arena = Arena(
        arena_name=data.arena_name,
        category=data.category,
        creator_id=current_user.user_id,
        creator_organization_id=org_id,
        is_public=data.is_public,
        ai_tokens_used=0,
    )
    db.add(new_arena)
    db.flush()

    # Create questions and track tokens
    tokens_consumed = 0
    for q in data.questions:
        # Only calculate token cost if AI is enabled for this organization
        token_cost = 0
        if org.use_ai_for_arenas and q.is_ai_generated:
            token_cost = TokenService.calculate_question_cost(
                len(q.prompt_text), len(q.options), use_ai_generation=True
            )

        question = Question(
            arena_id=new_arena.id,
            prompt_text=q.prompt_text,
            time_limit_seconds=q.time_limit_seconds,
            correct_option_index=q.correct_option_index,
            point_value=q.point_value,
            status=q.status or "ready",
            ai_tokens_cost=token_cost,
            is_ai_generated=q.is_ai_generated,
        )
        db.add(question)
        db.flush()

        # Add question options
        for opt_text in q.options:
            db.add(QuestionOption(question_id=question.id, text=opt_text))

        tokens_consumed += token_cost

    # Update arena token usage (only if AI is enabled)
    if org.use_ai_for_arenas:
        new_arena.ai_tokens_used = tokens_consumed

        # Log token usage
        if tokens_consumed > 0:
            TokenService.log_token_usage(
                db=db,
                arena_id=new_arena.id,
                organization_id=org_id,
                tokens_used=tokens_consumed,
                operation="arena_creation",
            )

    db.commit()
    db.refresh(new_arena)

    if org.use_ai_for_arenas:
        logger.info(
            f"Arena {new_arena.id} created by user {current_user.user_id}, consumed {tokens_consumed} tokens"
        )
    else:
        logger.info(
            f"Arena {new_arena.id} created by user {current_user.user_id} (AI usage disabled for organization)"
        )

    return new_arena


@router.post("/generate/questions", response_model=list[QuestionResponse])
async def generate_questions_ai(
    data: AIQuestionGenerationRequest,
    current_user: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Generate questions using AI (preview only, not saved to DB)"""
     
    user = db.query(User).filter(User.id == current_user.user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )

    # Check if user has organization
    if not user.owned_organization:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User must have an organization to generate questions",
        )

    org = user.owned_organization

    # Check if AI is enabled for organization
    if not org.use_ai_for_arenas:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="AI question generation is not enabled for your organization",
        )

    try:
        # Generate questions using AI service
        generated_questions = await AIQuestionGenerationService.generate_questions(
            subject=data.subject,
            num_questions=data.num_questions,
            difficulty=data.difficulty,
            language=data.language,
        )

        # Calculate token cost
        total_tokens = sum(q.ai_tokens_cost for q in generated_questions)

        # Check token availability for preview request
        can_use, error_msg = TokenService.can_use_tokens(db, org.id, total_tokens)
        if not can_use:
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED, detail=error_msg
            )

        logger.info(
            f"Generated {len(generated_questions)} questions for user {current_user.user_id}, tokens: {total_tokens}"
        )

        return generated_questions

    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Question generation failed: {str(e)}",
        )
    except Exception as e:
        logger.error(f"Error generating questions: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to generate questions",
        )


@router.get("", response_model=list[ArenaResponse])
async def list_arenas(
    skip: int = 0,
    limit: int = 10,
    current_user: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List arenas created by the current user"""
    arenas = (
        db.query(Arena)
        .filter(Arena.creator_id == current_user.user_id)
        .offset(skip)
        .limit(limit)
        .all()
    )
    return arenas


@router.get("/{arena_id}", response_model=ArenaDetailResponse)
async def get_arena(
    arena_id: int,
    current_user: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get arena details with token information"""
    arena = db.query(Arena).filter(Arena.id == arena_id).first()

    if not arena:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Arena not found"
        )

    # Check permissions - allow if creator or public
    if arena.creator_id != current_user.user_id and not arena.is_public:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to view this arena",
        )

    # Calculate token info
    ai_generated = db.query(Question).filter(
        Question.arena_id == arena_id, Question.is_ai_generated == True
    ).count()

    # Calculate player stats
    total_players = db.query(Player).filter(Player.arena_id == arena_id).count()
    completed_players = db.query(Player).filter(
        Player.arena_id == arena_id,
        Player.status == "completed"
    ).count()
    completion_rate = (completed_players / total_players * 100) if total_players > 0 else 0.0

    token_info_dict = {
        "ai_tokens_used": arena.ai_tokens_used,
        "total_questions": len(arena.questions),
        "ai_generated_questions": ai_generated,
        "total_players": total_players,
        "completed_players": completed_players,
        "completion_rate": completion_rate,
    }

    # Pass it as a keyword argument correctly
    return ArenaDetailResponse(
        id=arena.id,
        arena_name=arena.arena_name,
        category=arena.category,
        is_public=arena.is_public,
        questions=[QuestionResponse.model_validate(q) for q in arena.questions], # Convert questions too!
        creator_id=arena.creator_id,
        creator_organization_id=arena.creator_organization_id,
        created_at=arena.created_at,
        updated_at=arena.updated_at,
        ai_tokens_used=arena.ai_tokens_used,
        token_info=ArenaTokenInfo(**token_info_dict), # Cast dict to the expected Pydantic model
    )


@router.put("/{arena_id}", response_model=ArenaResponse)
async def update_arena(
    arena_id: int,
    data: ArenaUpdate,
    current_user: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update arena details"""
    arena = db.query(Arena).filter(Arena.id == arena_id).first()

    if not arena:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Arena not found"
        )

    if arena.creator_id != current_user.user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to update this arena",
        )

    # Update fields if provided
    if data.arena_name:
        arena.arena_name = data.arena_name
    if data.category:
        arena.category = data.category
    if data.is_public is not None:
        arena.is_public = data.is_public

    db.commit()
    db.refresh(arena)

    logger.info(f"Arena {arena_id} updated by user {current_user.user_id}")

    return arena


@router.delete("/{arena_id}")
async def delete_arena(
    arena_id: int,
    current_user: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Delete an arena"""
    arena = db.query(Arena).filter(Arena.id == arena_id).first()

    if not arena:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Arena not found"
        )

    if arena.creator_id != current_user.user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to delete this arena",
        )

    db.delete(arena)
    db.commit()

    logger.info(f"Arena {arena_id} deleted by user {current_user.user_id}")

    return {"message": "Arena deleted successfully"}


@router.get("/tokens/usage")
async def get_token_usage(
    current_user: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TokenUsageResponse:
    """Get token usage for current user's organization"""
    user = db.query(User).filter(User.id == current_user.user_id).first()

    if not user or not user.owned_organization:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User must have an organization",
        )

    token_info = TokenService.get_organization_tokens(db, user.owned_organization.id)

    return TokenUsageResponse(**token_info)

@router.get("/tokens/usage/logs")
async def get_token_usage_logs(
    current_user: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[ArenaTokenUsageLogResponse]:
    """Get detailed token usage logs for current user's organization"""
    user = db.query(User).filter(User.id == current_user.user_id).first()

    if not user or not user.owned_organization:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User must have an organization",
        )

    logs = (
        db.query(ArenaTokenUsageLog)
        .filter(ArenaTokenUsageLog.organization_id == user.owned_organization.id)
        .order_by(ArenaTokenUsageLog.created_at.desc())
        .all()
    )

    return [ArenaTokenUsageLogResponse.model_validate(log) for log in logs]