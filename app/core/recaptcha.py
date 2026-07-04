import httpx
from app.core.config import settings


async def verify_recaptcha(token: str) -> bool:
    """Verify invisible reCAPTCHA v2 token with Google's API."""
    if not token:
        return False

    data = {"secret": getattr(settings, "RECAPTCHA_SECRET_KEY", ""), "response": token}
    try:
        async with httpx.AsyncClient() as client:
            r = await client.post("https://www.google.com/recaptcha/api/siteverify", data=data, timeout=10)
            resp = r.json()
    except Exception:
        return False

    return bool(resp.get("success", False))
