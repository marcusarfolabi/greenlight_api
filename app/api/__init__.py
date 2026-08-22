from fastapi import APIRouter

from app.api.admin import router as admin_router
from app.api.arena import router as arenas_router
from app.api.arenas_websocket import router as arenas_websocket_router
from app.api.auth import router as auth_router
from app.api.category import router as category_router
from app.api.news import router as news_router
from app.api.organization import router as organization_router
from app.api.payouts import router as payouts_router
from app.api.player import router as players_router
from app.api.subscription import router as subscription_router
from app.api.users import router as users_router

api_router = APIRouter()

api_router.include_router(admin_router, prefix="/admin", tags=["Admin"])
api_router.include_router(players_router, prefix="/players", tags=["Players"])
api_router.include_router(arenas_router, prefix="/arenas", tags=["Arenas"])
api_router.include_router(
    arenas_websocket_router, prefix="/arenas_websocket", tags=["Arenas Websocket"]
)
api_router.include_router(
    subscription_router, prefix="/subscriptions", tags=["Subscriptions"]
)
api_router.include_router(payouts_router, prefix="/payouts", tags=["Payouts"])
api_router.include_router(users_router, prefix="/users", tags=["Users"])
api_router.include_router(
    organization_router, prefix="/organizations", tags=["Organizations"]
)
api_router.include_router(category_router, prefix="/categories", tags=["Categories"])
api_router.include_router(auth_router, prefix="/auth", tags=["Auth"])
api_router.include_router(news_router, prefix="/news", tags=["News"])
