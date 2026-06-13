import logging
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.core.security import get_current_user
from app.schemas.arena import (
    ArenaResponse,
    ArenaTokenInfo,
    ArenaDetailResponse,
    QuestionResponse,
)
from app.models.arena import Arena, Question
from app.models.player import Player
from app.schemas.user import AuthContext

router = APIRouter()
logger = logging.getLogger(__name__)

from typing import Optional

@router.get("", response_model=list[ArenaResponse])
async def list_public_arenas(
    skip: int = 0,
    limit: int = 10,
    # Make user dependency optional so public arenas can be fetched unauthenticated if needed
    current_user: Optional[AuthContext] = Depends(get_current_user), 
    db: Session = Depends(get_db),
):
    """List all publicly available arenas for players"""
    # Swap Creator filter to fetch only public games
    arenas = (
        db.query(Arena)
        .filter(Arena.is_public == True)
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
            "total_questions": total_questions,
            "total_players": total_players,
        })

    return results

@router.get("/{arena_id}", response_model=ArenaDetailResponse)
async def get_arena(
    arena_id: int,
    current_user: Optional[AuthContext] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get public arena details (or private if owned by the logged-in user)"""
    arena = db.query(Arena).filter(Arena.id == arena_id).first()

    if not arena:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Arena not found"
        )

    if arena.access_code is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Arena access code is not set",
        )

    # REVISED GUARD LAYER: Allow if it's public. If private, check if current_user matches creator.
    is_owner = current_user and arena.creator_id == current_user.user_id
    
    if not arena.is_public and not is_owner:
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

    return ArenaDetailResponse(
        id=arena.id,
        arena_name=arena.arena_name,
        category=arena.category,
        is_public=arena.is_public,
        access_code=arena.access_code,
        questions=[QuestionResponse.model_validate(q) for q in arena.questions],
        creator_id=arena.creator_id,
        creator_organization_id=arena.creator_organization_id,
        created_at=arena.created_at,
        updated_at=arena.updated_at,
        ai_tokens_used=arena.ai_tokens_used,
        token_info=ArenaTokenInfo(**token_info_dict),
    )