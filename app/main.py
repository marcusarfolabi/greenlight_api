import os
import logging
from dotenv import load_dotenv
from app.api import api_router
from app.db.session import engine
from app.models import Base
from app.core.config import settings
from sqlalchemy.exc import OperationalError
from sqlalchemy.sql import text
from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.openapi.utils import get_openapi

from app.scripts.admin_seeder import seed_superadmin
from app.scripts.subscription_seeder import seed_subscription_plans

load_dotenv(dotenv_path=".env.docker")
logging.basicConfig(level=logging.INFO)

logger = logging.getLogger(__name__)

security = HTTPBasic()

DEFAULT_CORS_ORIGINS = [
    "http://localhost:3000",
    "http://localhost:3001",
    "https://greenlightquiz.com",
    "https://admin.greenlightquiz.com",
]


def build_cors_origins() -> list[str]:
    configured = [origin.strip() for origin in settings.CORS_ORIGINS if origin and origin.strip()]
    merged = set(DEFAULT_CORS_ORIGINS)
    merged.update(configured)
    merged.discard("*")
    return sorted(merged)

app = FastAPI(
    title=settings.PROJECT_NAME,
    description="Host the live arena for gamers, streamers, and esports enthusiasts. Watch live streams, join tournaments, and connect with the gaming community.",
    version="2.0.0",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
    redirect_slashes=False,
    swagger_ui_parameters={"tryItOutEnabled": True, "persistAuthorization": True},
)


@app.on_event("startup")
async def startup_event():
    logger.info("Initializing database and running seeders...")
    try:
        with engine.begin() as connection:
            table_names = ", ".join([f'"{table.name}"' for table in Base.metadata.sorted_tables])

            if table_names:
                logger.info(f"Force dropping tables: {table_names}")
                connection.execute(text(f"DROP TABLE IF EXISTS {table_names} CASCADE;"))
                logger.info("Database cleanly wiped via raw CASCADE.")
            else:
                logger.info("No tables discovered to drop.")
        Base.metadata.create_all(bind=engine)
        seed_superadmin()
        seed_subscription_plans()
    except OperationalError as e:
        logger.error(
            f"Database connection failed on startup. {e} "
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

    if (
        credentials.username != correct_username
        or credentials.password != correct_password
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized access",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username


@app.get("/docs", include_in_schema=False)
async def get_swagger_documentation(username: str = Depends(get_admin_user)):
    return get_swagger_ui_html(
        openapi_url="/openapi.json",
        title="Green Light Quiz API",
        swagger_ui_parameters={"tryItOutEnabled": True, "persistAuthorization": True},
    )


@app.get("/openapi.json", include_in_schema=False)
async def get_open_api_endpoint(username: str = Depends(get_admin_user)):
    return get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )


app.add_middleware(
    CORSMiddleware,
    allow_origins=build_cors_origins(),
    # Allow root domain and optional subdomains (e.g. app/preview hosts).
    allow_origin_regex=r"^https://([a-z0-9-]+\.)?greenlightquiz\.com$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

logger.info("CORS explicit origins: %s", build_cors_origins())

app.include_router(api_router, prefix="/v1")


@app.get("/")
async def root():
    try:
        with engine.connect():
            return {
                "status": "Greenlight is operational",
                "environment": os.getenv("ENVIRONMENT"),
                "db_status": "connected",
            }
    except Exception as e:
        return {
            "status": "Greenlight is operational",
            "environment": os.getenv("ENVIRONMENT"),
            "db_status": f"connection failed: {str(e)}",
        }
