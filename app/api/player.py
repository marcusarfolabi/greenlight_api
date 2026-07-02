import logging
from datetime import datetime 
from typing import Optional
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
from app.models.player import Player, PlayerAnswerScore
from app.schemas.user import AuthContext
from app.schemas.player import PlayerScoreboardResponse

router = APIRouter()
logger = logging.getLogger(__name__)


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
    arena_id: str,
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
 
@router.get("/scoreboard", response_model=list[PlayerScoreboardResponse])
async def get_my_arena_scoreboard_endpoint(
    db: Session = Depends(get_db),
    current_user: AuthContext = Depends(get_current_user),
):
    """Get the live scoreboard for the authenticated user's current arena"""
    return get_player_arena_scoreboard(current_user.user_id, db)


def get_player_arena_scoreboard(
    user_id: int,
    db: Session,
):
    """
    Helper function to find a player's arena based on their authenticated user ID,
    then calculate the ranked scoreboard for that arena.
    """

    # 1. Look up the player to find what arena they are assigned to
    # Adjust filtering if your Player model links to users via another attribute name (e.g., user_id)
    player_record = db.query(Player).filter(Player.id == user_id).first() 
    if not player_record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, 
            detail="Player profile not found for authenticated user."
        )
    
    arena_id = player_record.arena_id
    if not arena_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Player is not currently registered to any active arena."
        )

    # 2. Verify the Arena exists
    arena = db.query(Arena).filter(Arena.id == arena_id).first()
    if not arena:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Arena not found"
        )
    
    # 3. Get all players for this arena with their scores aggregated
    players = db.query(Player).filter(Player.arena_id == arena_id).all()
    
    scoreboard_data = []
    for p in players:
        # Get all answers for this player in this arena
        answers = db.query(PlayerAnswerScore).filter(
            PlayerAnswerScore.player_id == p.id,
            PlayerAnswerScore.arena_id == arena_id
        ).all()
        
        total_score = sum(a.points_earned for a in answers)
        correct_count = sum(1 for a in answers if a.is_correct)
        total_answers = len(answers)
        accuracy = (correct_count / total_answers * 100) if total_answers > 0 else 0
        last_answered = max([a.answered_at for a in answers], default=None) if answers else None
        
        scoreboard_data.append({
            "player_id": p.id,
            "username": p.username,
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