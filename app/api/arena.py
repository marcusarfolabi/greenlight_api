import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status, Body
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
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
from app.models.arena import Arena, Question, ArenaTokenUsageLog
from app.models.player import Player
from app.models.user import User
from app.schemas.user import AuthContext
from app.services.token_service import TokenService
from app.services.ai_question_service import AIQuestionGenerationService
from app.schemas.player import PlayerResponse

router = APIRouter()
logger = logging.getLogger(__name__)

@router.post("", response_model=ArenaResponse)
async def create_arena(
    data: ArenaCreate,
    current_user: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create a new arena with atomic token deduction"""
    
    user = db.query(User).filter(User.id == current_user.user_id).first()
    if not user or not user.owned_organization:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Organization required")

    org = user.owned_organization

    try:
        # 1. Calculate tokens ONLY for AI-generated questions
        total_ai_tokens = sum(
            TokenService.calculate_question_cost(len(q.prompt_text), len(q.options), use_ai_generation=True)
            for q in data.questions if q.is_ai_generated
        )

        # 2. Atomic Debit: Only if AI is enabled and there are costs
        if org.use_ai_for_arenas and total_ai_tokens > 0:
            if not TokenService.deduct_tokens(db, org.id, total_ai_tokens):
                raise HTTPException(status_code=status.HTTP_402_PAYMENT_REQUIRED, detail="Insufficient tokens")

        # 3. Create Arena
        new_arena = Arena(
            arena_name=data.arena_name,
            category=data.category,
            creator_id=current_user.user_id,
            creator_organization_id=org.id,
            is_public=data.is_public,
            ai_tokens_used=total_ai_tokens,
        )
        db.add(new_arena)
        db.flush()

        # 4. Create Questions
        for q in data.questions:
            token_cost = TokenService.calculate_question_cost(len(q.prompt_text), len(q.options), True) if q.is_ai_generated else 0
            
            question = Question(
                arena_id=new_arena.id,
                prompt_text=q.prompt_text,
                time_limit_seconds=q.time_limit_seconds,
                correct_option_index=q.correct_option_index,
                point_value=q.point_value,
                status=q.status or "ready",
                ai_tokens_cost=token_cost,
                is_ai_generated=q.is_ai_generated,
                options_json=[{"text": opt_text} for opt_text in q.options],
            )
            db.add(question)

        db.flush()  # Flush before logging to ensure arena has an ID

        # 5. Log token usage
        if org.use_ai_for_arenas and total_ai_tokens > 0:
            TokenService.log_token_usage(
                db=db,
                arena_id=new_arena.id,
                tokens_used=total_ai_tokens,
                operation="arena_question_creation",
                organization_id=org.id
            )

        db.commit()
        db.refresh(new_arena)
        return new_arena

    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Arena creation failed: {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Transaction failed")
    

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

    # Replace questions if provided
    if getattr(data, "questions", None) is not None:
        # Delete existing questions for the arena
        db.query(Question).filter(Question.arena_id == arena_id).delete(synchronize_session=False)
        db.flush()

        # Resolve user/org for token accounting
        user = db.query(User).filter(User.id == current_user.user_id).first()
        if not user or not user.owned_organization:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Organization required")
        org = user.owned_organization

        # Calculate total AI tokens for the new questions (only count if AI-generated)
        total_ai_tokens = 0
        qs = data.questions or []
        for q in qs:
            token_cost = 0
            if org.use_ai_for_arenas and getattr(q, "is_ai_generated", False):
                token_cost = TokenService.calculate_question_cost(len(q.prompt_text), len(q.options), use_ai_generation=True)
            total_ai_tokens += token_cost

        # Attempt atomic debit of tokens if organization uses AI
        if org.use_ai_for_arenas and total_ai_tokens > 0:
            if not TokenService.deduct_tokens(db, org.id, total_ai_tokens):
                raise HTTPException(status_code=status.HTTP_402_PAYMENT_REQUIRED, detail="Insufficient tokens")

        # Create new question rows and attach computed token costs
        for q in qs:
            token_cost = 0
            if org.use_ai_for_arenas and getattr(q, "is_ai_generated", False):
                token_cost = TokenService.calculate_question_cost(len(q.prompt_text), len(q.options), use_ai_generation=True)

            new_q = Question(
                arena_id=arena.id,
                prompt_text=q.prompt_text,
                time_limit_seconds=q.time_limit_seconds,
                correct_option_index=q.correct_option_index,
                point_value=q.point_value,
                status=q.status or "ready",
                ai_tokens_cost=token_cost,
                is_ai_generated=q.is_ai_generated,
                options_json=[{"text": opt_text} for opt_text in q.options],
            )
            db.add(new_q)

        db.flush()

        # Add consumed tokens to arena's running total (don't overwrite existing)
        if org.use_ai_for_arenas and total_ai_tokens > 0:
            arena.ai_tokens_used = (arena.ai_tokens_used or 0) + total_ai_tokens

            # Log token usage for this update
            TokenService.log_token_usage(
                db=db,
                arena_id=arena.id,
                organization_id=org.id,
                tokens_used=total_ai_tokens,
                operation="arena_question_update",
            )

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

@router.post("/validate-access-code")
async def validate_access_code(
    access_code: str = Body(...),
    player_nickname: str = Body(...),
    db: Session = Depends(get_db),
) -> dict:
    """Validate arena access code for lobby entry"""
    arena = db.query(Arena).filter(Arena.access_code == access_code).first()

    if not arena:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Invalid access code"
        )

    # validate nickname
    if not player_nickname or not player_nickname.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="player_nickname is required")

    # coerce access code to int for storage
    try:
        access_code_int = int(access_code)
    except (TypeError, ValueError):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid access code format")

    # determine organization id from arena
    org_id = getattr(arena, "creator_organization_id", None) or getattr(arena, "organization_id", None)

    # Check if this nickname already exists for the arena (idempotent)
    existing = (
        db.query(Player)
        .filter(Player.arena_id == arena.id, Player.username == player_nickname)
        .first()
    )

    if existing:
        return {
            "arena_id": arena.id,
            "arena_name": arena.arena_name,
            "access_code": arena.access_code,
            "player_id": existing.id,
            "player_username": existing.username,
            "organization_id": existing.organization_id,
            "total_players": db.query(Player).filter(Player.arena_id == arena.id).count(),
        }

    new_player = Player(
        arena_id=arena.id,
        organization_id=org_id,
        arena_access_code=access_code_int,
        username=player_nickname,
        status="joined",
    )

    db.add(new_player)
    try:
        db.commit()
        db.refresh(new_player)
    except IntegrityError:
        # race: another request inserted the same (arena_id, username). Roll back and return existing.
        db.rollback()
        existing = (
            db.query(Player)
            .filter(Player.arena_id == arena.id, Player.username == player_nickname)
            .first()
        )
        if existing:
            return {
                "arena_id": arena.id,
                "arena_name": arena.arena_name,
                "access_code": arena.access_code,
                "player_id": existing.id,
                "player_username": existing.username,
                "organization_id": existing.organization_id,
                "total_players": db.query(Player).filter(Player.arena_id == arena.id).count(),
            }
        # If still not found, re-raise
        raise

    return {
        "arena_id": arena.id,
        "arena_name": arena.arena_name,
        "access_code": arena.access_code,
        "player_id": new_player.id,
        "player_username": new_player.username,
        "organization_id": new_player.organization_id,
        "total_players": db.query(Player).filter(Player.arena_id == arena.id).count(),
    }

@router.get("/organization/players", response_model=list[PlayerResponse])
async def get_organization_players(
    offset: int = 0,
    limit: int = 100,
    search: Optional[str] = None,
    current_user: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[PlayerResponse]:
    """Get list of players across all arenas in the user's organization"""
    user = db.query(User).filter(User.id == current_user.user_id).first()
    if not user or not user.owned_organization:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Organization required")

    org_id = user.owned_organization.id

    # Count players for pagination
    total_players = db.query(Player).filter(Player.organization_id == org_id).count()

    query = (
        db.query(Player, Arena.arena_name)
        .outerjoin(Arena, Player.arena_id == Arena.id)
        .filter(Player.organization_id == org_id)
    )

    if search:
        pattern = f"%{search.lower()}%"
        query = query.filter(
            func.lower(Player.username).like(pattern) | func.lower(Arena.arena_name).like(pattern)
        )

    rows = query.offset(offset).limit(limit).all()

    result: list[PlayerResponse] = []
    for row in rows:
        # row is (Player, arena_name)
        p, arena_name = row
        result.append(
            PlayerResponse.model_validate(
                {
                    "id": p.id,
                    "arena_id": p.arena_id,
                    "organization_id": p.organization_id,
                    "arena_access_code": p.arena_access_code,
                    "username": p.username,
                    "attempt_date": p.attempt_date,
                    "status": p.status,
                    "completed_at": p.completed_at,
                    "score": p.score,
                    "answers_submitted": p.answers_submitted,
                    "correct_answers": p.correct_answers,
                    "rank": getattr(p, "rank", None),
                    "arena_name": arena_name,
                    "total_players": total_players,
                }
            )
        )

    return result

@router.get("/{arena_id}/players", response_model=list[PlayerResponse])
async def get_arena_players(
    arena_id: int,
    offset: int = 0,
    limit: int = 100,
    search: Optional[str] = None,
    db: Session = Depends(get_db),
) -> list[PlayerResponse]:
    """Get list of players in the arena lobby"""
    arena = db.query(Arena).filter(Arena.id == arena_id).first()
    if not arena:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Arena not found")

    # Base query for players in arena
    query = db.query(Player).filter(Player.arena_id == arena_id)
    total_players = query.count()  # Get total count for pagination

    if search:
        # case-insensitive search across player username and arena name
        pattern = f"%{search.lower()}%"
        query = db.query(Player).outerjoin(Arena, Player.arena_id == Arena.id).filter(
            func.lower(Player.username).like(pattern) | func.lower(Arena.arena_name).like(pattern)
        )

    players = query.offset(offset).limit(limit).all()

    result: list[PlayerResponse] = []
    for p in players:
        result.append(
            PlayerResponse.model_validate(
                {
                    "id": p.id,
                    "arena_id": p.arena_id,
                    "organization_id": p.organization_id,
                    "arena_access_code": p.arena_access_code,
                    "username": p.username,
                    "attempt_date": p.attempt_date,
                    "status": p.status,
                    "completed_at": p.completed_at,
                    "score": p.score,
                    "answers_submitted": p.answers_submitted,
                    "correct_answers": p.correct_answers,
                    "rank": getattr(p, "rank", None),
                    "arena_name": getattr(arena, "arena_name", None), 
                    "total_players": total_players,
                }
            )
        )

    return result
    
    