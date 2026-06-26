import logging
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.core.security import get_current_user
from app.schemas.news import NewsResponse
from app.models.news import News
from app.services.news_service import NewsGenerationService

logger = logging.getLogger(__name__)
router = APIRouter()


def _slugify(text: str) -> str:
    import re

    s = (text or "").lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = re.sub(r"-+", "-", s).strip("-")
    ts = str(int(datetime.utcnow().timestamp()))
    return f"{s}-{ts}" if s else ts


@router.get("", response_model=List[NewsResponse])
def list_news(limit: int = 10, slug: Optional[str] = None, db: Session = Depends(get_db)):
    if slug:
        item = db.query(News).filter(News.slug == slug).first()
        if not item:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="News item not found")
        return [item]

    items = db.query(News).order_by(News.published_at.desc().nullslast()).limit(limit).all()
    return items

# get new detail using slug
@router.get("/{slug}", response_model=NewsResponse)
def get_news_detail(slug: str, db: Session = Depends(get_db)):
    item = db.query(News).filter(News.slug == slug).first()
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="News item not found")
    return item

@router.post("/generate", response_model=NewsResponse)
def generate_news(
    topic: Optional[str] = None,
    # current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Trigger generation of a single news post. Requires authentication."""
    try:
        topic_to_use = topic or NewsGenerationService.random_topic()
        news_data = NewsGenerationService.generate_for_topic(topic_to_use)

        slug = _slugify(news_data.title or topic_to_use)

        new_item = News(
            title=news_data.title,
            slug=slug,
            summary=news_data.summary,
            content=news_data.content,
            topic=news_data.topic,
            origin=news_data.origin,
            ai_generated=news_data.ai_generated,
            ai_model=news_data.ai_model,
            ai_tokens_cost=news_data.ai_tokens_cost,
            published_at=datetime.utcnow(),
        )

        db.add(new_item)
        db.commit()
        db.refresh(new_item)

        return new_item
    except Exception as e:
        logger.exception("Failed to generate news: %s", e)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="News generation failed")
