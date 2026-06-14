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
from app.core.config import settings
from sqlalchemy.exc import OperationalError
from app.scripts.admin_seeder import seed_superadmin
from app.scripts.subscription_seeder import seed_subscription_plans

logging.basicConfig(level=logging.INFO)

logger = logging.getLogger(__name__)

security = HTTPBasic()

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

@app.on_event("startup")
async def startup_event():
    logger.info("Initializing database and running seeders...")
    try:
        Base.metadata.drop_all(bind=engine) #temporary testing
        Base.metadata.create_all(bind=engine)
        seed_superadmin()
        seed_subscription_plans()
        # logger.info("Database initialization and seeding complete.")
    except OperationalError as e:
        logger.error(
            "Database connection failed on startup. "
            "Check DB_HOST/DB_PORT/POSTGRES_* settings and whether the database is reachable."
        )
        raise
    except Exception as e:
        logger.error(f"Startup seeding failed: {e}")
        raise


def get_admin_user(credentials: HTTPBasicCredentials = Depends(security)):
    correct_username = os.getenv("API_ADMIN_USERNAME")
    correct_password = os.getenv("API_ADMIN_PASSWORD")
    
    if not correct_password:
        logger.error("❌ CRITICAL: API_ADMIN_PASSWORD environment variable is NOT SET")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        )
    if not correct_username:
        logger.error("❌ CRITICAL: API_ADMIN_USERNAME environment variable is NOT SET")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        )
    
    if credentials.username != correct_username or credentials.password != correct_password:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized access",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username


@app.get("/docs", include_in_schema=False)
async def get_swagger_documentation(
    username: str = Depends(get_admin_user)
):
    return get_swagger_ui_html(
        openapi_url="/openapi.json",
        title="Green Light Quiz API",
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
    # allow_origins=settings.CORS_ORIGINS,
    allow_origins=["http://localhost:3000", "https://greenlight.webshoptechnology.us"],  
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
) 

app.include_router(api_router, prefix="/api/v1")

@app.get("/")
async def root():
    try:
        with engine.connect() as conn:
            return {
                "status": "Greenlight is operational", 
                "environment": os.getenv("ENVIRONMENT"),
                "db_status": "connected"
            }
    except Exception as e:
        return {
            "status": "Greenlight is operational", 
            "environment": os.getenv("ENVIRONMENT"),
            "db_status": f"connection failed: {str(e)}"
        }
