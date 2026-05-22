

from fastapi import APIRouter

from app.api.auth import router as auth_router
from app.api.users import router as users_router
from app.api.quizzes import router as quizzes_router
from app.api.payouts import router as payouts_router
from app.api.organization import router as organization_router

api_router = APIRouter()

api_router.include_router(organization_router, prefix="/organizations", tags=["Organizations"])
api_router.include_router(quizzes_router, prefix="/quizzes", tags=["Quizzes"])
api_router.include_router(payouts_router, prefix="/payouts", tags=["Payouts"])
api_router.include_router(users_router, prefix="/users", tags=["Users"])
api_router.include_router(auth_router, prefix="/auth", tags=["Auth"])
