from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.api import api_router
from app.db.session import engine  
from app.models.base import Base

load_dotenv(dotenv_path=".env.docker")

Base.metadata.create_all(bind=engine)

app = FastAPI(
    title=settings.PROJECT_NAME,
    description="Host the live arena for gamers, streamers, and esports enthusiasts. Watch live streams, join tournaments, and connect with the gaming community.",
    version="2.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    redirect_slashes=False,
    swagger_ui_parameters={
        "tryItOutEnabled": True,
        "persistAuthorization": True 
    }    
)

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
) 

app.include_router(api_router, prefix="/v1")

@app.get("/")
async def root():
    return {"status": "Greenlight is operational", "environment": "production"}
