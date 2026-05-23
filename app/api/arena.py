from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.core.security import get_current_user
from app.schemas.arena import ArenaCreate, ArenaResponse
from app.models.arena import Arena, Question, QuestionOption
from app.schemas.user import AuthContext

router = APIRouter()

@router.post("/", response_model=ArenaResponse)
async def create_arena(data: ArenaCreate, current_user: AuthContext = Depends(get_current_user), db: Session = Depends(get_db)): 
    new_arena = Arena(title=data.arena_name, creator_id=current_user.user_id, is_public=data.is_public)
    db.add(new_arena)
    db.flush() 

    for q in data.questions:
        question = Question(
            arena_id=new_arena.id, 
            prompt_text=q.prompt_text,
            time_limit_seconds=q.time_limit_seconds,
            correct_option_index=q.correct_option_index,
            point_value=q.point_value
        )
        db.add(question)
        db.flush()
        
        for opt_text in q.options:
            db.add(QuestionOption(question_id=question.id, text=opt_text))
            
    db.commit()
    return new_arena

@router.get("/")
async def list_quizzes(db: Session = Depends(get_db)):
    """List all quizzes."""
    # TODO: Implement list quizzes
    pass

@router.get("/{quiz_id}")
async def get_quiz(quiz_id: int, db: Session = Depends(get_db)):
    """Get quiz by ID."""
    # TODO: Implement get quiz
    pass

@router.put("/{quiz_id}")
async def update_quiz(quiz_id: int, current_user_id: int = Depends(get_current_user), db: Session = Depends(get_db)):
    """Update quiz."""
    # TODO: Implement update quiz
    pass

@router.delete("/{quiz_id}")
async def delete_quiz(quiz_id: int, current_user_id: int = Depends(get_current_user), db: Session = Depends(get_db)):
    """Delete quiz."""
    # TODO: Implement delete quiz
    pass
