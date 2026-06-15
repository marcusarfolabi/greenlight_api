import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status, Body, File, Form, UploadFile, BackgroundTasks, WebSocket, WebSocketDisconnect
import asyncio
import json
from datetime import datetime
from sqlalchemy import desc, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
import io
import csv
from PyPDF2 import PdfReader # type: ignore
import stripe

from app.models.player import PlayerAnswerScore
from app.db.session import get_db
from app.core.security import get_current_user
from app.models.organization import ArenaPayoutReport
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
from app.services.upload_service import parse_questions_file
from app.schemas.player import PlayerResponse, LobbyResponse, LobbyPlayer, PlayerScoreboardResponse
from app.services.mail_service import MailService
from app.services.twilio_service import TwilioService
from app.services.ws_manager import ws_manager
from app.core.security import decode_token

logger = logging.getLogger(__name__)

router = APIRouter()
logger = logging.getLogger(__name__)

# Upload limits
MAX_UPLOAD_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB
MAX_PDF_PAGES = 50


async def _bg_send_sms(to: str, recipient_name: Optional[str], body: str, arena_access_code: int):
    try:
        ok = await TwilioService.send_sms_arena_access_code_async(to, recipient_name, body)
        if ok:
            logger.info("Queued SMS sent to %s for arena access code %s", to, arena_access_code)
        else:
            logger.warning("Queued SMS failed to send to %s for arena access code %s", to, arena_access_code)
    except Exception:
        logger.exception("Error sending queued SMS to %s for arena access code %s", to, arena_access_code)


async def _bg_send_email(to: str, recipient_name: Optional[str], subject: str, body: str, arena_details: dict, org_name: Optional[str]):
    try:
        await MailService.send_email_arena_access_code(to, recipient_name or "Participant", subject, body, arena_details, org_name)
        logger.info("Queued email sent to %s for arena %s", to, arena_details.get("arena_name"))
    except Exception:
        logger.exception("Error sending queued email to %s for arena %s", to, arena_details.get("arena_name"))

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
                type=q.type,
                correct_answers=q.correct_answers,
                correct_answer_string=q.correct_answer_string,
            )
            db.add(question)

        db.flush()  # Flush before logging to ensure arena has an ID

        # 5. Log token usage
        if org.use_ai_for_arenas and total_ai_tokens > 0:
            TokenService.log_token_usage(
                db=db,
                arena_id=new_arena.id,
                tokens_used=total_ai_tokens,
                operation=new_arena.arena_name,
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

    # Validate access_code is set
    if arena.access_code is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Arena access code is not set",
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
        access_code=arena.access_code,
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
    """Update arena details with PATCH-style question merging (no deletes with foreign keys)"""
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

    # Update base fields if provided
    if data.arena_name:
        arena.arena_name = data.arena_name
    if data.category:
        arena.category = data.category
    if data.is_public is not None:
        arena.is_public = data.is_public

    # Merge questions if provided (PUT style: Sync exactly what frontend sends)
    if getattr(data, "questions", None) is not None:
        # Resolve user/org for token accounting
        user = db.query(User).filter(User.id == current_user.user_id).first()
        if not user or not user.owned_organization:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Organization required")
        org = user.owned_organization

        qs = data.questions or []
        incoming_question_ids = set()  # Track which existing questions are in the update
        new_ai_tokens = 0  # Only count tokens for truly new questions

        # Process incoming questions: update existing, insert new
        for q in qs:
            q_id = getattr(q, "id", None)
            
            # Check if this question ID exists in the database for this arena
            if q_id:
                existing_q = db.query(Question).filter(
                    Question.id == q_id,
                    Question.arena_id == arena_id
                ).first()
                
                if existing_q:
                    incoming_question_ids.add(q_id)
                    existing_q.prompt_text = q.prompt_text
                    existing_q.time_limit_seconds = q.time_limit_seconds
                    existing_q.point_value = q.point_value
                    existing_q.status = q.status or "ready"
                    existing_q.options_json = [{"text": opt_text} for opt_text in q.options]
                    
                    existing_q.type = getattr(q, "type", "multiple_choice")
                    existing_q.correct_option_index = q.correct_option_index
                    existing_q.correct_answer_string = getattr(q, "correct_answer_string", None)
                    existing_q.correct_answers = getattr(q, "correct_answers", [])
                    
                    logger.info(f"Updated existing question {q_id} in arena {arena_id}")
                    continue
            
            # This is a new question (no ID or ID doesn't exist in DB)
            token_cost = 0
            if org.use_ai_for_arenas and getattr(q, "is_ai_generated", False):
                token_cost = TokenService.calculate_question_cost(
                    len(q.prompt_text), 
                    len(q.options), 
                    use_ai_generation=True
                )
                new_ai_tokens += token_cost

            new_q = Question(
                arena_id=arena.id,
                prompt_text=q.prompt_text,
                time_limit_seconds=q.time_limit_seconds,
                point_value=q.point_value,
                status=q.status or "ready",
                ai_tokens_cost=token_cost,
                is_ai_generated=getattr(q, "is_ai_generated", False),
                options_json=[{"text": opt_text} for opt_text in q.options],
                type=getattr(q, "type", "multiple_choice"),
                correct_option_index=q.correct_option_index,
                correct_answer_string=getattr(q, "correct_answer_string", None),
                correct_answers=getattr(q, "correct_answers", []),
            )
            db.add(new_q)
            db.flush()  # <-- Force SQLAlchemy to generate a real database ID for this new question!
            incoming_question_ids.add(new_q.id)  # <-- Add the fresh ID to the safe list so it won't be deleted!

        # Deduct tokens only for NEW AI-generated questions
        if org.use_ai_for_arenas and new_ai_tokens > 0:
            if not TokenService.deduct_tokens(db, org.id, new_ai_tokens):
                raise HTTPException(status_code=status.HTTP_402_PAYMENT_REQUIRED, detail="Insufficient tokens")

        # --- FIX 3: SAFE PURGE OMITTED QUESTIONS WITH BOUNDS ---
        # Now incoming_question_ids contains both updated AND newly created IDs
        delete_query = db.query(Question).filter(Question.arena_id == arena_id)
        if incoming_question_ids:
            delete_query = delete_query.filter(~Question.id.in_(incoming_question_ids))
            
        questions_to_delete = delete_query.all()
        
        for q_to_delete in questions_to_delete: 
            logger.info(f"Removing question {q_to_delete.id} to match frontend state sync")
            db.delete(q_to_delete)

        db.flush()
        
        # Deduct tokens only for NEW AI-generated questions
        if org.use_ai_for_arenas and new_ai_tokens > 0:
            if not TokenService.deduct_tokens(db, org.id, new_ai_tokens):
                raise HTTPException(status_code=status.HTTP_402_PAYMENT_REQUIRED, detail="Insufficient tokens")

        db.flush()
 
        # --- FIX 3: SAFE PURGE OMITTED QUESTIONS WITH BOUNDS ---
        # Only query with .in_ if incoming_question_ids has elements
        delete_query = db.query(Question).filter(Question.arena_id == arena_id)
        if incoming_question_ids:
            delete_query = delete_query.filter(~Question.id.in_(incoming_question_ids))
            
        questions_to_delete = delete_query.all()
        
        for q_to_delete in questions_to_delete: 
            logger.info(f"Removing question {q_to_delete.id} to match frontend state sync")
            db.delete(q_to_delete)

        db.flush()

        if org.use_ai_for_arenas and new_ai_tokens > 0:
            arena.ai_tokens_used = (arena.ai_tokens_used or 0) + new_ai_tokens

            # Log token usage for this update
            TokenService.log_token_usage(
                db=db,
                arena_id=arena.id,
                organization_id=org.id,
                tokens_used=new_ai_tokens,
                operation= arena.arena_name,
            )
            
    db.commit()
    db.refresh(arena)

    logger.info(f"Arena {arena_id} updated by host {current_user.user_id}")

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
        .limit(10)
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
    try:
        access_code_int = int(access_code)
    except (TypeError, ValueError):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid access code format")

    arena = db.query(Arena).filter(Arena.access_code == access_code_int).first()

    if not arena:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Invalid access code"
        )

    # validate nickname
    if not player_nickname or not player_nickname.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="player_nickname is required")

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
        
    if org_id:
        allowed, error_message = TokenService.can_add_players(
            db=db, 
            organization_id=org_id, 
            additional_players=1
        )
        if not allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, 
                detail=error_message or "Organization plan player limit exceeded."
            )
            
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

    response_payload = {
        "arena_id": arena.id,
        "arena_name": arena.arena_name,
        "access_code": arena.access_code,
        "player_id": new_player.id,
        "player_username": new_player.username,
        "organization_id": new_player.organization_id,
        "total_players": db.query(Player).filter(Player.arena_id == arena.id).count(),
    }

    # Broadcast lobby update to connected websocket clients (fire-and-forget)
    try:
        players = db.query(Player).filter(Player.arena_id == arena.id).all()
        players_list = [{"id": p.id, "username": p.username} for p in players]
        payload = {
            "type": "lobby_update",
            "payload": {
                "players": players_list,
                "total_players": len(players_list),
                "lobby_waiting_time": 30,
                "arena_name": arena.arena_name,
                "arena_access_code": arena.access_code,
            },
        }
        asyncio.create_task(ws_manager.broadcast(str(arena.access_code), payload))
    except Exception:
        logger.exception("Failed to broadcast lobby update")

    return response_payload

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


@router.post("/questions/upload")
async def upload_questions_preview(
    file: UploadFile | None = File(None),
    preview: bool = Form(True),
    use_ai: bool = Form(False),
    current_user: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Preview-only upload for creating questions before an arena exists."""
    if not file:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No file provided")

    try:
        contents = await file.read()
        if len(contents) > MAX_UPLOAD_SIZE_BYTES:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="File too large")

        # ✅ FIX: Safe strict string fallback for the filename parameter
        safe_filename = file.filename or "unknown_file"

        # ✅ FIX: Route the parsing correctly based on whether use_ai is flagged
        if use_ai:
            try:
                text = ""
                if safe_filename.lower().endswith('.docx'):
                    from app.services.upload_service import _extract_text_from_docx
                    text = _extract_text_from_docx(contents)
                elif safe_filename.lower().endswith('.pdf'):
                    try:
                        from app.services.upload_service import _extract_text_from_pdf
                        text = _extract_text_from_pdf(contents)
                    except Exception:
                        text = ""
                    if not text or len(text.strip()) < 80:
                        try:
                            from app.services.upload_service import _ocr_pdf_with_tesseract
                            text = _ocr_pdf_with_tesseract(contents)
                        except Exception:
                            text = ""
                else:
                    try:
                        text = contents.decode('utf-8')
                    except Exception:
                        text = contents.decode('latin-1', errors='ignore')

                from app.core.config import settings
                from app.services.upload_service import ai_parse_text_to_questions
                parsed, errors = ai_parse_text_to_questions(text, settings.GEMINI_API_KEY)
            except Exception as e:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"AI parse failed: {e}")
        else:
            # Use the normal file parser function without passing the unsupported 'use_ai' arg
            parsed, errors = parse_questions_file(contents, safe_filename)

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to parse uploaded file for preview: %s", e)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Failed to parse file")

    # Build sample
    sample = []
    for q in parsed[:10]:
        try:
            sample.append({
                "prompt_text": q.prompt_text,
                "options": q.options,
                "correct_option_index": q.correct_option_index,
            })
        except Exception:
            sample.append({
                "prompt_text": getattr(q, 'prompt_text', ''),
                "options": getattr(q, 'options', []),
                "correct_option_index": getattr(q, 'correct_option_index', 0),
            })

    # Token estimate using current user's organization
    total_ai_tokens = 0
    try:
        user = db.query(User).filter(User.id == current_user.user_id).first()
        org = user.owned_organization if user else None
        for q in parsed:
            if getattr(q, 'is_ai_generated', False):
                total_ai_tokens += TokenService.calculate_question_cost(len(q.prompt_text), len(q.options), use_ai_generation=True)

        token_info = {
            "token_estimate": total_ai_tokens,
            "can_use": True,
            "message": None,
        }

        if total_ai_tokens > 0:
            if not org:
                token_info["can_use"] = False
                token_info["message"] = "Organization required for AI token billing"
            elif not org.use_ai_for_arenas:
                token_info["can_use"] = False
                token_info["message"] = "AI parsing is not enabled for your organization"
            else:
                can_use, msg = TokenService.can_use_tokens(db, org.id, total_ai_tokens)
                token_info["can_use"] = can_use
                token_info["message"] = msg
    except Exception:
        token_info = {"token_estimate": 0, "can_use": False, "message": "Failed to calculate token estimate"}

    return {"parsed_count": len(parsed), "sample": sample, "errors": errors[:50], "token_info": token_info}



@router.post("/{arena_id}/questions/upload")
async def upload_questions(
    arena_id: int,
    file: UploadFile | None = File(None),
    preview: bool = Form(False),
    use_ai: bool = Form(False),
    current_user: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Upload questions for an arena (CSV or JSON). If `preview=true` returns parsed summary without saving."""
    arena = db.query(Arena).filter(Arena.id == arena_id).first()
    if not arena:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Arena not found")

    # Only creator can upload questions
    if arena.creator_id != current_user.user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to upload questions for this arena")

    if not file:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No file provided")

    # ✅ FIX: Extract a guaranteed strict string fallback right away
    safe_filename = file.filename or "unknown_file"

    try:
        content = await file.read()
        # Enforce file size limit
        if len(content) > MAX_UPLOAD_SIZE_BYTES:
            raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=f"File too large ({len(content)} bytes). Max allowed size is {MAX_UPLOAD_SIZE_BYTES} bytes")

        # If PDF, check page count before heavy processing
        if safe_filename.lower().endswith('.pdf'):
            try:
                reader = PdfReader(io.BytesIO(content))
                num_pages = len(reader.pages)
                if num_pages > MAX_PDF_PAGES:
                    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"PDF has {num_pages} pages which exceeds the maximum allowed {MAX_PDF_PAGES} pages")
            except HTTPException:
                raise
            except Exception:
                # If PyPDF2 fails, continue and let parse_questions_file handle extraction/OCR
                pass
        parsed, errors = [], [] 

        if use_ai:
            # Extract or decode text for AI parsing
            try:
                # For docx/pdf we rely on upload_service extractors; otherwise decode bytes
                text = None
                if safe_filename.lower().endswith('.docx'):
                    from app.services.upload_service import _extract_text_from_docx
                    text = _extract_text_from_docx(content)
                elif safe_filename.lower().endswith('.pdf'):
                    # try selectable text first
                    try:
                        from app.services.upload_service import _extract_text_from_pdf
                        text = _extract_text_from_pdf(content)
                    except Exception:
                        text = ""
                    if not text or len(text.strip()) < 80:
                        # try OCR via tesseract or google vision
                        try:
                            from app.services.upload_service import _ocr_pdf_with_tesseract
                            text = _ocr_pdf_with_tesseract(content)
                        except Exception:
                            try:
                                from app.services.upload_service import _ocr_with_google_vision
                                text = _ocr_with_google_vision(content)
                            except Exception:
                                text = ""
                else:
                    try:
                        text = content.decode('utf-8')
                    except Exception:
                        try:
                            text = content.decode('latin-1')
                        except Exception:
                            text = ''

                from app.core.config import settings
                from app.services.upload_service import ai_parse_text_to_questions
                parsed, errors = ai_parse_text_to_questions(text, settings.GEMINI_API_KEY)
            except Exception as e:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"AI parse failed: {e}")
        else:
            # ✅ FIX: Passed safe_filename instead of file.filename
            parsed, errors = parse_questions_file(content, safe_filename)
            
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Failed to parse file: {str(e)}")

    if preview:
        # return a small sample of parsed items for frontend preview
        sample = []
        for q in parsed[:10]:
            try:
                # pydantic model -> dict
                sample.append(q.model_dump() if hasattr(q, 'model_dump') else dict(q))
            except Exception:
                sample.append({
                    "prompt_text": getattr(q, 'prompt_text', ''),
                    "options": getattr(q, 'options', []),
                    "correct_option_index": getattr(q, 'correct_option_index', 0),
                })
        # Calculate AI token estimate for parsed items
        total_ai_tokens = 0
        try:
            user = db.query(User).filter(User.id == current_user.user_id).first()
            org = user.owned_organization if user else None
            for q in parsed:
                if getattr(q, 'is_ai_generated', False):
                    total_ai_tokens += TokenService.calculate_question_cost(len(q.prompt_text), len(q.options), use_ai_generation=True)

            token_info = {
                "token_estimate": total_ai_tokens,
                "can_use": True,
                "message": None,
            }

            if total_ai_tokens > 0:
                if not org:
                    token_info["can_use"] = False
                    token_info["message"] = "Organization required for AI token billing"
                elif not org.use_ai_for_arenas:
                    token_info["can_use"] = False
                    token_info["message"] = "AI parsing is not enabled for your organization"
                else:
                    can_use, msg = TokenService.can_use_tokens(db, org.id, total_ai_tokens)
                    token_info["can_use"] = can_use
                    token_info["message"] = msg
        except Exception:
            token_info = {"token_estimate": 0, "can_use": False, "message": "Failed to calculate token estimate"}

        return {"parsed_count": len(parsed), "sample": sample, "errors": errors[:50], "token_info": token_info}
    
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
    
@router.post("/{arena_id}/participants/message")
async def send_participants_message(
    arena_id: int,
    background_tasks: BackgroundTasks,
    channel: str = Form(...),
    file: Optional[UploadFile] = File(None),  # Expecting uploaded file
    contacts: Optional[str] = Form(None),  # Newline or comma separated contacts
    message: str = Form(...),
    db: Session = Depends(get_db),
):
    """Upload participants via file or pasted contacts and send messages (SMS/Email)"""
    arena = db.query(Arena).filter(Arena.id == arena_id).first()
    if not arena:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Arena not found")
    # get the arena organization name for email personalization
    org_name = None
    if arena.creator_organization_id:
        org = db.query(User.owned_organization.property.mapper.class_).filter_by(id=arena.creator_organization_id).first()
        if org:
            org_name = org.name
            
    # Validate channel
    if channel not in ["sms", "email"]:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid channel")

    contacts_list = []
    if file:
        try:
            content = await file.read()
            decoded_file = io.StringIO(content.decode("utf-8"))
            reader = csv.DictReader(decoded_file)
            for row in reader:
                name = row.get("name")
                email = row.get("email")
                phone = row.get("phone")
                if channel == "sms" and phone:
                    contacts_list.append({"name": name, "phone": phone})
                elif channel == "email" and email:
                    contacts_list.append({"name": name, "email": email})
        except Exception as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Failed to process file: {str(e)}")

    if contacts:
        raw_contacts = [c.strip() for c in contacts.replace(",", "\n").split("\n") if c.strip()]
        for c in raw_contacts:
            if channel == "sms":
                contacts_list.append({"phone": c})
            elif channel == "email":
                contacts_list.append({"email": c})

    if not contacts_list:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No valid contacts provided")

    # Queue send tasks in background to avoid long request time for large lists
    queued = 0
    for contact in contacts_list:
        target = contact.get("phone") or contact.get("email")
        recipient_name = contact.get("name") or "Participant"
        payload_message = f"{message} Join here: https://greenlight.webshoptechnology.us/arena/{arena.id} with access code {arena.access_code}"

        if channel == "sms":
            # ✅ FIX: Forced access code to integer fallback to clear 'int | None' mismatch error
            background_tasks.add_task(_bg_send_sms, target, recipient_name, payload_message, int(arena.access_code or 0))
            queued += 1
        elif channel == "email":
            background_tasks.add_task(_bg_send_email, target, recipient_name, "You're invited to join an arena!", payload_message, {"arena_name": arena.arena_name, "access_code": arena.access_code}, org_name)
            queued += 1

    return {"total": len(contacts_list), "queued": queued, "message": "messages queued for background delivery"}

@router.get("/lobby/{access_code}", response_model=LobbyResponse)
async def get_lobby_info(
    access_code: str,
    db: Session = Depends(get_db),
) -> LobbyResponse:
    """Get lobby info for a given access code"""
    try:
        access_code_int = int(access_code)
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid access code"
        )

    arena = db.query(Arena).filter(Arena.access_code == access_code_int).first()

    if not arena:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Invalid access code"
        )

    # return a lobby summary with all participants currently in the arena
    players = db.query(Player).filter(Player.arena_id == arena.id).all()
    players_list = []
    for p in players:
        players_list.append({
            "id": p.id,
            "username": p.username,
            "joined_at": p.attempt_date.isoformat() if p.attempt_date else None,
        })

    total_players = len(players_list)

    return LobbyResponse.model_validate(
        {
            "players": players_list,
            "total_players": total_players,
            "lobby_waiting_time": 30,
            "arena_name": arena.arena_name,
            "arena_access_code": arena.access_code,
            "host_id": getattr(arena, "creator_id", None),
            
        }
    )

@router.post("/{arena_id}/start-countdown")
async def start_arena_countdown(
    arena_id: int,
    countdown_seconds: int = Body(default=30, embed=True),
    current_user: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Host endpoint to start countdown for an arena.
    This broadcasts countdown to all connected WebSocket clients for this arena.
    """
    arena = db.query(Arena).filter(Arena.id == arena_id).first()

    if not arena:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Arena not found"
        )

    # Verify host authorization
    if arena.creator_id != current_user.user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the arena host can start the countdown",
        )

    # Validate countdown duration
    if countdown_seconds < 5 or countdown_seconds > 300:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Countdown must be between 5 and 300 seconds",
        )

    # Get the access code for this arena and validate it's not None
    if arena.access_code is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Arena access code is not set",
        )
    access_code = str(arena.access_code)

    # Define the broadcast function
    async def _countdown_broadcast(ac: str, remaining: int):
        await ws_manager.broadcast(ac, {"type": "countdown", "payload": {"countdown": remaining}})

    active_connections = ws_manager.connection_count(access_code)

    # Start the countdown (this will broadcast countdown messages and game_start when done)
    started = ws_manager.start_countdown(access_code, countdown_seconds, _countdown_broadcast)

    logger.info(
        "Countdown request for arena %s by user %s with %s seconds access_code=%s active_connections=%s started=%s",
        arena_id,
        current_user.user_id,
        countdown_seconds,
        access_code,
        active_connections,
        started,
    )

    return {
        "message": "Countdown started" if started else "Countdown already running",
        "arena_id": arena_id,
        "access_code": access_code,
        "countdown_seconds": countdown_seconds,
        "active_connections": active_connections,
        "started": started,
    }


@router.get("/{arena_id}/scoreboard", response_model=list[PlayerScoreboardResponse])
async def get_arena_scoreboard_endpoint(
    arena_id: int,
    db: Session = Depends(get_db),
):
    """Get live scoreboard for arena with player rankings"""
    return get_arena_scoreboard(arena_id, db)


def get_arena_scoreboard(
    arena_id: int,
    db: Session,
):
    """Helper function to calculate scoreboard for an arena with all player scores ranked"""
    from app.models.player import PlayerAnswerScore
    
    arena = db.query(Arena).filter(Arena.id == arena_id).first()
    if not arena:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Arena not found"
        )
    
    # Get all players for this arena with their scores aggregated
    players = db.query(Player).filter(Player.arena_id == arena_id).all()
    
    scoreboard_data = []
    for player in players:
        # Get all answers for this player in this arena
        answers = db.query(PlayerAnswerScore).filter(
            PlayerAnswerScore.player_id == player.id,
            PlayerAnswerScore.arena_id == arena_id
        ).all()
        
        total_score = sum(a.points_earned for a in answers)
        correct_count = sum(1 for a in answers if a.is_correct)
        total_answers = len(answers)
        accuracy = (correct_count / total_answers * 100) if total_answers > 0 else 0
        last_answered = max([a.answered_at for a in answers], default=None) if answers else None
        
        scoreboard_data.append({
            "player_id": player.id,
            "username": player.username,
            "total_score": total_score,
            "answers_correct": correct_count,
            "answers_total": total_answers,
            "accuracy_percentage": round(accuracy, 2),
            "last_answered_at": last_answered,
            "rank": None,  # Will be set after sorting
        })
    
    # Sort by total score descending, then by accuracy descending, then by answer time ascending
    scoreboard_data.sort(
        key=lambda x: (-x["total_score"], -x["accuracy_percentage"], x["last_answered_at"] or datetime.max),
    )
    
    # Add ranks after sorting
    for idx, entry in enumerate(scoreboard_data, 1):
        entry["rank"] = idx
    
    # Convert to response models
    return [PlayerScoreboardResponse.model_validate(entry) for entry in scoreboard_data]


async def close_arena_and_build_payout_ledger(arena_id: int, db: Session):
    # 1. Fetch all active participants who completed or played in the arena
    players = db.query(Player).filter(
        Player.arena_id == arena_id,
        Player.status == "completed"
    ).all()
    
    if not players:
        return

    # 2. Sort players logically by score descending (Break ties using correct answers)
    # Higher scores first; if scores are equal, player with more correct answers wins
    sorted_players = sorted(
        players, 
        key=lambda p: (p.score or 0, p.correct_answers or 0), 
        reverse=True
    )

    # 3. Define your prize pool matrix structure (Example calculation model)
    # Top 1 gets 50%, Top 2 gets 30%, Top 3 gets 20% of a $50 pool (calculated in cents)
    prize_pool_cents = 5000 
    payout_distribution = {1: int(prize_pool_cents * 0.50), 2: int(prize_pool_cents * 0.30), 3: int(prize_pool_cents * 0.20)}

    # 4. Generate the payout records
    for index, player in enumerate(sorted_players, start=1):
        current_rank = index
        
        # Update operational data inside the core Player model row
        player.rank = current_rank
        
        # Determine if this rank receives cash from your prize matrix
        payout_reward = payout_distribution.get(current_rank, 0)
        
        # Inject structural transaction ledger entry
        payout_entry = ArenaPayoutReport(
            arena_id=arena_id,
            player_id=player.id,
            username=player.username or f"Player_{player.id}",
            final_score=player.score or 0,
            final_rank=current_rank,
            payout_amount_cents=payout_reward,
            payout_status="pending" if payout_reward > 0 else "skipped" # Skip processing if they won $0
        )
        db.add(payout_entry)
        
    db.commit()
    


def process_automated_stripe_payouts(db: Session):
    """
    Processes all pending arena payout ledger rows using Stripe Transfers 
    by resolving recipient routing tokens via PlayerBankingProfile.
    """
    pending_payouts = db.query(ArenaPayoutReport).filter(
        ArenaPayoutReport.payout_status == "pending",
        ArenaPayoutReport.payout_amount_cents > 0
    ).all()

    for payout in pending_payouts:
        try:
            payout.payout_status = "processing"
            db.commit()

            banking_profile = payout.player.banking_profile if payout.player else None
            
            if not banking_profile:
                payout.payout_status = "failed"
                payout.payout_error_message = "Player banking profile details are missing entirely."
                db.commit()
                continue

            destination_id = banking_profile.external_recipient_id
            
            if not destination_id:
                payout.payout_status = "failed"
                payout.payout_error_message = "Missing a valid Stripe connected account destination token."
                db.commit()
                continue

            # ✅ FIX: Every single dictionary value cast to strict string for Stripe Type invariance
            transfer = stripe.Transfer.create(
                amount=payout.payout_amount_cents,
                currency="usd",
                destination=destination_id, 
                metadata={
                    "arena_id": str(payout.arena_id),
                    "player_id": str(payout.player_id),
                    "player_username": str(payout.username or ""),
                    "rank": str(payout.final_rank)
                }
            )

            # ✅ FIX: Mapped to 'transfer_reference' to match your schema column definitions
            payout.transfer_reference = transfer.id  
            payout.payout_status = "paid"
            payout.processed_at = datetime.utcnow()
            payout.payout_error_message = None  

        except Exception as stripe_err:
            db.rollback()
            payout.payout_status = "failed"
            payout.payout_error_message = str(stripe_err)
            logger.exception(f"Stripe API execution failed on payout row ID {payout.id}: {stripe_err}")
            
        db.commit()
        
        
# router.websocket("/ws/lobby/{access_code}")
# async def lobby_websocket(websocket: WebSocket, access_code: str):
#     """WebSocket endpoint for real-time lobby updates and shared countdown."""
#     await websocket.accept()
#     await ws_manager.connect(str(access_code), websocket)
    
#     player_info: dict = {"player_id": 0, "player_name": "", "arena_id": 0}

#     try:
#         from app.db.session import get_db as _get_db
#         db_gen = _get_db()
#         db = next(db_gen)
        
#         try:
#             try:
#                 access_code_int = int(access_code)
#             except (TypeError, ValueError):
#                 await websocket.send_json({
#                     "type": "join_rejected",
#                     "payload": {"reason": "invalid_access_code"}
#                 })
#                 await websocket.close(code=1008)
#                 return

#             arena = db.query(Arena).filter(Arena.access_code == access_code_int).first()
#             if not arena:
#                 await websocket.accept()
#                 await websocket.send_json({
#                     "type": "join_rejected",
#                     "payload": {"reason": "invalid_access_code"}
#                 })
#                 await websocket.close(code=1008)
#                 return
            
#             # =========================================================================
#             # DYNAMIC SUBSCRIPTION COUPLING CHECK FOR NEW WAITING ROOM RECONNECTIONS
#             # =========================================================================
#             org_id = getattr(arena, "creator_organization_id", None) or getattr(arena, "organization_id", None)
#             if org_id:
#                 # We count active players currently linked inside this specific arena right now
#                 current_lobby_count = db.query(Player).filter(Player.arena_id == arena.id).count()
                
#                 allowed, error_message = TokenService.can_add_players(
#                     db=db, 
#                     organization_id=org_id, 
#                     additional_players=1
#                 )
                
#                 # If the subscription limit is breached, reject the pipeline handshake explicitly
#                 if not allowed:
#                     await websocket.accept()
#                     await websocket.send_json({
#                         "type": "join_rejected",
#                         "payload": {"reason": "lobby_full", "detail": error_message}
#                     })
#                     await websocket.close(code=1008)
#                     return

#             # =========================================================================
#             # If all subscription checks pass, accept the client into the global memory manager
#             # =========================================================================
#             await websocket.accept()
#             await ws_manager.connect(str(access_code), websocket)
            
#             player_info["arena_id"] = arena.id

#             # Fetch players based on arena ID
#             players = db.query(Player).filter(Player.arena_id == arena.id).all()
#             players_list = [{"id": p.id, "username": p.username} for p in players]
            
#             payload = {
#                 "type": "lobby_update",
#                 "payload": {
#                     "players": players_list,
#                     "total_players": len(players_list),
#                     "lobby_waiting_time": 30,
#                     "arena_name": arena.arena_name,
#                     "arena_access_code": arena.access_code,
#                 },
#             }
            
#             # Send snapshot to all clients for this access code
#             await ws_manager.broadcast(str(arena.access_code), payload)

#             async def _countdown_broadcast(ac, remaining):
#                 await ws_manager.broadcast(ac, {"type": "countdown", "payload": {"countdown": remaining}})

#             # Listen for incoming messages
#             while True:
#                 data = await websocket.receive_json()
#                 msg_type = data.get("type")
                
#                 if msg_type == "register_player":
#                     try:
#                         msg_payload = data.get("payload", {})
#                         player_name = msg_payload.get("player_name")
                        
#                         if player_name:
#                             player = db.query(Player).filter(
#                                 Player.arena_id == arena.id,
#                                 Player.username == player_name
#                             ).first()
                            
#                             if player:
#                                 player_info["player_id"] = player.id
#                                 player_info["player_name"] = player_name
#                                 logger.info(f"Player {player_name} (ID: {player.id}) registered in arena {arena.id}")
#                     except Exception:
#                         logger.exception("Error handling player registration")
                
#                 elif msg_type == "host_ready":
#                     try:
#                         seconds = int(data.get("seconds", 15))
#                         ws_manager.start_countdown(str(arena.access_code), seconds, _countdown_broadcast)
#                     except Exception:
#                         logger.exception("Error handling host_ready message")
                
#                 elif msg_type == "question_display":
#                     try:
#                         await ws_manager.broadcast(str(arena.access_code), {
#                             "type": "question_display",
#                             "payload": data.get("payload", {})
#                         })
#                     except Exception:
#                         logger.exception("Error broadcasting question")
                
#                 elif msg_type == "player_answer":
#                     try:
#                         from app.models.player import PlayerAnswerScore
#                         from app.models.arena import Question
                        
#                         msg_payload = data.get("payload", {})
#                         question_id = msg_payload.get("question_id")
#                         answer_selected = msg_payload.get("answer_selected")
#                         is_correct = msg_payload.get("is_correct")
#                         time_taken = msg_payload.get("time_taken", 0)
#                         question_time_limit = msg_payload.get("question_time_limit", 0)
#                         max_points = msg_payload.get("max_points", 0)
                        
#                         points_earned = PlayerAnswerScore.calculate_score(
#                             time_taken=time_taken,
#                             question_time_limit=question_time_limit,
#                             max_points=max_points,
#                             is_correct=is_correct
#                         )
                        
#                         if player_info["player_id"] and player_info["arena_id"]:
#                             answer_score = PlayerAnswerScore(
#                                 player_id=player_info["player_id"],
#                                 arena_id=player_info["arena_id"],
#                                 question_id=question_id,
#                                 answer_selected=answer_selected,
#                                 is_correct=is_correct,
#                                 time_taken=time_taken,
#                                 question_time_limit=question_time_limit,
#                                 points_earned=points_earned,
#                                 max_points=max_points,
#                             )
#                             db.add(answer_score)
#                             db.commit()
#                             logger.info(f"Saved answer for player {player_info['player_name']} on Q{question_id}: {points_earned} points")
                        
#                         await ws_manager.broadcast(str(arena.access_code), {
#                             "type": "player_score_update",
#                             "payload": {
#                                 "question_id": question_id,
#                                 "player_name": player_info["player_name"],
#                                 "answer_selected": answer_selected,
#                                 "is_correct": is_correct,
#                                 "time_taken": time_taken,
#                                 "points_earned": points_earned,
#                             }
#                         })
#                     except Exception:
#                         logger.exception("Error processing player answer")
                
#                 elif msg_type == "hide_question":
#                     try:
#                         await ws_manager.broadcast(str(arena.access_code), {
#                             "type": "hide_question",
#                             "payload": {}
#                         })
#                     except Exception:
#                         logger.exception("Error hiding question")
                
#                 elif msg_type == "question_timeout":
#                     try:
#                         scoreboard = get_arena_scoreboard(arena.id, db)
#                         await ws_manager.broadcast(str(arena.access_code), {
#                             "type": "scoreboard_update",
#                             "payload": {
#                                 "scoreboard": [entry.model_dump() for entry in scoreboard]
#                             }
#                         })
#                     except Exception:
#                         logger.exception("Error broadcasting scoreboard on timeout")

#                 elif msg_type == "end_game" or msg_type == "game_over":
#                     try:
#                         await close_arena_and_build_payout_ledger(arena_id=arena.id, db=db)
#                         final_scoreboard = db.query(Player).filter(
#                             Player.arena_id == arena.id
#                         ).order_by(Player.rank.asc()).all()

#                         await ws_manager.broadcast(str(arena.access_code), {
#                             "type": "arena_concluded",
#                             "payload": {
#                                 "message": "Game over! Financial payout ledger generated.",
#                                 "scoreboard": [
#                                     {
#                                         "username": p.username,
#                                         "score": p.score,
#                                         "rank": p.rank,
#                                         "status": "completed"
#                                     } for p in final_scoreboard
#                                 ]
#                             }
#                         })
#                     except Exception as e:
#                         logger.exception(f"Critical payout calculation failure on arena {arena.id}: {e}")
#                         await websocket.send_json({
#                             "type": "error",
#                             "payload": {"detail": "Failed to safely compute and finalize game ranks."}
#                         })
#         finally:
#             try:
#                 next(db_gen, None)
#             except StopIteration:
#                 pass

#     except WebSocketDisconnect:
#         ws_manager.disconnect(str(access_code), websocket)
#     except Exception:
#         ws_manager.disconnect(str(access_code), websocket)
#         try:
#             await websocket.close()
#         except Exception:
#             pass

@router.websocket("/ws/lobby/{access_code}")
async def lobby_websocket(websocket: WebSocket, access_code: str):
    """WebSocket endpoint for real-time lobby updates and shared countdown."""
    
    # Accept the connection 
    await websocket.accept()
    await ws_manager.connect(str(access_code), websocket)

    player_info: dict = {"player_id": 0, "player_name": "", "arena_id": 0}

    try:
        from app.db.session import get_db as _get_db
        db_gen = _get_db()
        db = next(db_gen)
        
        try:
            arena = db.query(Arena).filter(Arena.access_code == access_code).first()
            if not arena:
                await websocket.close(code=1008)
                return
            
            player_info["arena_id"] = arena.id

            # Fetch players based on arena ID
            players = db.query(Player).filter(Player.arena_id == arena.id).all()
            players_list = [{"id": p.id, "username": p.username} for p in players]
            
            payload = {
                "type": "lobby_update",
                "payload": {
                    "players": players_list,
                    "total_players": len(players_list),
                    "lobby_waiting_time": 30,
                    "arena_name": arena.arena_name,
                    "arena_access_code": arena.access_code,
                },
            }
            
            await ws_manager.broadcast(str(arena.access_code), payload)

            async def _countdown_broadcast(ac, remaining):
                await ws_manager.broadcast(ac, {"type": "countdown", "payload": {"countdown": remaining}})

            # Listen for incoming messages
            while True:
                data = await websocket.receive_json()
                msg_type = data.get("type")
                
                if msg_type == "register_player":
                    try:
                        payload = data.get("payload", {})
                        player_name = payload.get("player_name")
                        
                        if player_name:
                            player = db.query(Player).filter(
                                Player.arena_id == arena.id,
                                Player.username == player_name
                            ).first()
                            
                            if player:
                                player_info["player_id"] = player.id
                                player_info["player_name"] = player_name
                                logger.info(f"Player {player_name} (ID: {player.id}) registered in arena {arena.id}")
                    except Exception:
                        logger.exception("Error handling player registration")
                
                elif msg_type == "host_ready":
                    try:
                        seconds = int(data.get("seconds", 30))
                        ws_manager.start_countdown(str(arena.access_code), seconds, _countdown_broadcast)
                    except Exception:
                        logger.exception("Error handling host_ready message")
                
                elif msg_type == "question_display":
                    try:
                        await ws_manager.broadcast(str(arena.access_code), {
                            "type": "question_display",
                            "payload": data.get("payload", {})
                        })
                    except Exception:
                        logger.exception("Error broadcasting question")
                
                elif msg_type == "player_answer":
                    try:
                        
                        
                        payload = data.get("payload", {})
                        question_id = payload.get("question_id")
                        answer_selected = payload.get("answer_selected")
                        is_correct = payload.get("is_correct")
                        time_taken = payload.get("time_taken", 0)
                        question_time_limit = payload.get("question_time_limit", 0)
                        max_points = payload.get("max_points", 0)
                        
                        points_earned = PlayerAnswerScore.calculate_score(
                            time_taken=time_taken,
                            question_time_limit=question_time_limit,
                            max_points=max_points,
                            is_correct=is_correct
                        )
                        
                        # Save answer to database if player is registered
                        if player_info["player_id"] and player_info["arena_id"]:
                            answer_score = PlayerAnswerScore(
                                player_id=player_info["player_id"],
                                arena_id=player_info["arena_id"],
                                question_id=question_id,
                                answer_selected=answer_selected,
                                is_correct=is_correct,
                                time_taken=time_taken,
                                question_time_limit=question_time_limit,
                                points_earned=points_earned,
                                max_points=max_points,
                            )
                            db.add(answer_score)
                            db.commit()
                            logger.info(f"Saved answer for player {player_info['player_name']} on Q{question_id}: {points_earned} points")
                        
                        await ws_manager.broadcast(str(arena.access_code), {
                            "type": "player_score_update",
                            "payload": {
                                "question_id": question_id,
                                "player_name": player_info["player_name"],
                                "answer_selected": answer_selected,
                                "is_correct": is_correct,
                                "time_taken": time_taken,
                                "points_earned": points_earned,
                            }
                        })
                        
                        logger.info(f"Player {player_info['player_name']} answered Q{question_id} correctly={is_correct} in {time_taken}s, earned {points_earned} points")
                    except Exception:
                        logger.exception("Error processing player answer")
                
                elif msg_type == "hide_question":
                    # Hide question from all connected clients
                    try:
                        await ws_manager.broadcast(str(arena.access_code), {
                            "type": "hide_question",
                            "payload": {}
                        })
                    except Exception:
                        logger.exception("Error hiding question")
                
                elif msg_type == "question_timeout":
                    try:
                        scoreboard = get_arena_scoreboard(arena.id, db)
                        await ws_manager.broadcast(str(arena.access_code), {
                            "type": "scoreboard_update",
                            "payload": {
                                "scoreboard": [entry.model_dump() for entry in scoreboard]
                            }
                        })
                        logger.info(f"Broadcasted scoreboard for arena {arena.id} due to question timeout")
                    except Exception:
                        logger.exception("Error broadcasting scoreboard on timeout")

                elif msg_type == "end_game" or msg_type == "game_over":
                    try:
                        await close_arena_and_build_payout_ledger(arena_id=arena.id, db=db)
                        final_scoreboard = db.query(Player).filter(
                            Player.arena_id == arena.id
                        ).order_by(Player.rank.asc()).all()

                        await ws_manager.broadcast(str(arena.access_code), {
                            "type": "arena_concluded",
                            "payload": {
                                "message": "Game over! Financial payout ledger generated.",
                                "scoreboard": [
                                    {
                                        "username": p.username,
                                        "score": p.score,
                                        "rank": p.rank,
                                        "status": "completed"
                                    } for p in final_scoreboard
                                ]
                            }
                        })
                    except Exception as e:
                        logger.exception(f"Critical payout calculation failure on arena {arena.id}: {e}")
                        
        finally:
            try:
                next(db_gen, None)
            except StopIteration:
                pass

    except WebSocketDisconnect:
        ws_manager.disconnect(str(access_code), websocket)
    except Exception:
        ws_manager.disconnect(str(access_code), websocket)
        try:
            await websocket.close()
        except Exception:
            pass