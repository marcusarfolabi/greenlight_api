import os
import logging
from dotenv import load_dotenv
from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.openapi.docs import get_swagger_ui_html 
from fastapi.openapi.utils import get_openapi


load_dotenv(dotenv_path=".env.docker") 

from app.api import api_router
from app.db.session import engine
from app.models import Base
from app.models.user import User
from app.models.organization import Organization
from app.models.arena import Arena, Question, QuestionOption
from app.models.wallet import Wallet, Transaction
from app.core.config import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

_registered_models = [User, Organization, Arena, Question, QuestionOption, Wallet, Transaction]

print(f"DEBUG: Registering {len(_registered_models)} models with metadata...")

Base.metadata.create_all(bind=engine)

security = HTTPBasic()
 
def get_admin_user(credentials: HTTPBasicCredentials = Depends(security)):
    correct_username = "admin_prod" 
    correct_password = os.getenv("ADMIN_PASS")
    
    if not correct_password:
        logger.error("❌ CRITICAL: ADMIN_PASS environment variable is NOT SET")
    
    if credentials.username != correct_username or credentials.password != correct_password:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized access",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username

app = FastAPI(
    title=settings.PROJECT_NAME,
    description="Host the live arena for gamers, streamers, and esports enthusiasts. Watch live streams, join tournaments, and connect with the gaming community.",
    version="2.0.0",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,

    redirect_slashes=False,
    swagger_ui_parameters={
        "tryItOutEnabled": True,
        "persistAuthorization": True
    }
)

@app.get("/docs", include_in_schema=False)
async def get_swagger_documentation(
    username: str = Depends(get_admin_user)
):
    return get_swagger_ui_html(
        openapi_url="/openapi.json",
        title="Falcon Omni-Connect API",
        swagger_ui_parameters={
            "tryItOutEnabled": True,
            "persistAuthorization": True
        }
    )


@app.get("/openapi.json", include_in_schema=False)
async def get_open_api_endpoint(
    username: str = Depends(get_admin_user)
):
    return get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )

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
    try:
        with engine.connect() as conn:
            return {
                "status": "Greenlight is operational", 
                "environment": "production",
                "db_status": "connected"
            }
    except Exception as e:
        return {
            "status": "Greenlight is operational", 
            "environment": "production",
            "db_status": f"connection failed: {str(e)}"
        }
