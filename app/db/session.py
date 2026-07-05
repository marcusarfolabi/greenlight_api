from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.models import Base
from app.core.config import settings

if settings.DATABASE_URL:
    DATABASE_URL = settings.DATABASE_URL
else:
    db_host = settings.DB_HOST or "localhost"
    db_port = settings.DB_PORT or "5432"
    DATABASE_URL = f"postgresql://{settings.POSTGRES_USER}:{settings.POSTGRES_PASSWORD}@{db_host}:{db_port}/{settings.POSTGRES_DB}"
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
