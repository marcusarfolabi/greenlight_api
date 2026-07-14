import logging
import secrets
from datetime import datetime, timedelta, timezone

import requests
from fastapi import APIRouter, BackgroundTasks, Depends, Form, HTTPException, status
from fastapi.responses import JSONResponse
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from app.core.cache import otp_cache
from app.core.config import settings
from app.core.security import (
    create_access_token,
    create_refresh_token,
    get_current_user,
    hash_password,
    verify_password,
)
from app.db.session import get_db
from app.models.user import PushSubscription
from app.schemas.user import (
    AppleTokenPayload,
    AuthContext,
    ForgotPasswordRequest,
    GoogleTokenPayload,
    LinkedInTokenPayload,
    PushSubscriptionCreate,
    ResendOTPRequest,
    ResetPasswordRequest,
    UserCreate,
    VerifyOTPRequest,
)
from app.services.mail_service import mail_service
from app.services.user_service import UserService

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/login")
async def login(
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    user = UserService.get_user_by_login(db, username)

    if not user or not verify_password(password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username/email or password",
        )

    # debug: log is_active value to diagnose truthiness issues
    logger.debug(
        "Login attempt for %s; is_active=%r",
        user.email,
        getattr(user, "is_active", None),
    )

    if (not bool(getattr(user, "is_active", False))) and (
        getattr(user, "email_verified_at", None) is None
    ):
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content={
                "detail": "User account email is unverified. Click on Forgot Password to receive a verification code.",
                "otp_sent": True,
            },
        )

    hasOrg = UserService.user_has_org(db, user.id)
    org_id = UserService.get_user_org_id(db, user.id) if hasOrg else None

    hasSub = False
    if org_id is not None:
        hasSub = UserService.user_has_subscription(db, org_id)

    token_data = {
        "sub": str(user.id),
        "role": user.role,
        "username": user.username,
        "org_id": org_id,
        "has_subscription": hasSub,
    }

    access_token = create_access_token(data=token_data)
    refresh_token = create_refresh_token(data={"sub": str(user.id)})

    response_data = {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "user": {
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "google_id": user.google_id,
            "linkedin_id": user.linkedin_id,
            "apple_id": user.apple_id,
            "role": user.role,
            "hasOrg": hasOrg,
            "org_id": org_id,
            "hasSub": hasSub,
        },
    }

    if hasOrg:
        subdomain = UserService.user_sub_domain(db, user.id)
        response_data["user"]["subdomain"] = subdomain

    return response_data


@router.post("/refresh-token")
async def refresh_user_token(
    current_user: AuthContext = Depends(get_current_user), db: Session = Depends(get_db)
):
    db_user = UserService.get_user(db, current_user.user_id)
    if not db_user:
        raise HTTPException(status_code=404, detail="User account profile not found.")

    hasOrg = UserService.user_has_org(db, db_user.id)
    org_id = UserService.get_user_org_id(db, db_user.id) if hasOrg else None

    hasSub = False
    if org_id is not None:
        hasSub = UserService.user_has_subscription(db, org_id)

    token_data = {
        "sub": str(db_user.id),
        "role": db_user.role,
        "username": db_user.username,
        "org_id": org_id,
        "has_subscription": hasSub,
    }

    access_token = create_access_token(token_data)

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": {
            "id": db_user.id,
            "username": db_user.username,
            "email": db_user.email,
            "role": db_user.role,
            "hasOrg": hasOrg,
            "org_id": org_id,
            "hasSub": hasSub,
        },
    }


@router.post("/google")
async def auth_google(
    payload: GoogleTokenPayload,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    try:
        id_info = id_token.verify_oauth2_token(
            payload.token, google_requests.Request(), settings.GOOGLE_CLIENT_ID
        )

        google_id = id_info.get("sub")
        email = id_info.get("email")
        first_name = id_info.get("given_name")
        last_name = id_info.get("family_name")

        if not email or not google_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Google account missing identity parameters.",
            )

        user = UserService.get_user_by_google_id(db, google_id)

        if not user:
            user = UserService.get_user_by_email(db, email)
            if user:
                user = UserService.update_user_social_id(
                    db, user.id, "google_id", google_id
                )
                logger.info(f"Linked existing account to Google ID for: {email}")

        if not user:
            base_username = email.split("@")[0].replace(".", "_")
            username = base_username

            counter = 1
            while UserService.get_user_by_username(db, username):
                username = f"{base_username}_{counter}"
                counter += 1

            new_user_data = UserCreate(
                email=email,
                username=username,
                first_name=first_name,
                last_name=last_name,
                password=secrets.token_urlsafe(16),
                role=payload.role or "user",
                is_active=True,
                google_id=google_id,
                location=payload.location,
                country_iso=payload.country_iso,
                accepted_terms=True,
            )

            user = UserService.create_user(db, new_user_data)
            logger.info(f"Successfully registered new user via Google: {email}")

            user_display_name = new_user_data.first_name or user.username
            background_tasks.add_task(
                mail_service.send_welcome_email,
                email=user.email,
                name=user_display_name,
                org_name="",
            )

        hasOrg = UserService.user_has_org(db, user.id)
        org_id = UserService.get_user_org_id(db, user.id) if hasOrg else None

        hasSub = False
        if org_id is not None:
            hasSub = UserService.user_has_subscription(db, org_id)

        token_data = {
            "sub": str(user.id),
            "role": user.role,
            "username": user.username,
            "org_id": org_id,
            "has_subscription": hasSub,
        }

        access_token = create_access_token(token_data)
        refresh_token = create_refresh_token({"sub": str(user.id)})

        response_data = {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "bearer",
            "user": {
                "id": user.id,
                "username": user.username,
                "email": user.email,
                "role": user.role,
                "is_active": user.is_active,
                "created_at": user.created_at.isoformat()
                if hasattr(user.created_at, "isoformat")
                else user.created_at,
                "hasOrg": hasOrg,
                "org_id": org_id,
                "hasSub": hasSub,
                "google_id": user.google_id,
                "linkedin_id": user.linkedin_id,
                "apple_id": user.apple_id,
            },
        }

        if hasOrg:
            response_data["user"]["subdomain"] = UserService.user_sub_domain(
                db, user.id
            )

        return response_data

    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Google OAuth token signature or token expired",
        )


@router.post("/apple")
async def auth_apple(
    payload: AppleTokenPayload,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    try:
        jwks_response = requests.get("https://appleid.apple.com/auth/keys", timeout=10)
        jwks_response.raise_for_status()
        jwks = jwks_response.json()

        header = jwt.get_unverified_header(payload.token)
        key = next(
            (
                item
                for item in jwks.get("keys", [])
                if item.get("kid") == header.get("kid")
            ),
            None,
        )

        if not key:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Unable to verify Apple identity token.",
            )

        claims = jwt.decode(
            payload.token,
            key,
            audience=settings.APPLE_CLIENT_ID,
            algorithms=["RS256"],
        )

        apple_id = claims.get("sub")
        email = claims.get("email")
        first_name = claims.get("given_name")
        last_name = claims.get("family_name")

        if not email or not apple_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Apple account missing identity parameters.",
            )

        user = UserService.get_user_by_apple_id(db, apple_id)

        if not user:
            user = UserService.get_user_by_email(db, email)
            if user:
                user = UserService.update_user_social_id(
                    db, user.id, "apple_id", apple_id
                )
                logger.info(f"Linked existing account to Apple ID for: {email}")

        if not user:
            base_username = email.split("@")[0].replace(".", "_")
            username = base_username

            counter = 1
            while UserService.get_user_by_username(db, username):
                username = f"{base_username}_{counter}"
                counter += 1

            new_user_data = UserCreate(
                email=email,
                username=username,
                first_name=first_name,
                last_name=last_name,
                password=secrets.token_urlsafe(16),
                role=payload.role or "user",
                is_active=True,
                apple_id=apple_id,
                location=payload.location,
                country_iso=payload.country_iso,
                accepted_terms=True,
            )

            user = UserService.create_user(db, new_user_data)
            logger.info(f"Successfully registered new user via Apple: {email}")

            user_display_name = new_user_data.first_name or user.username
            background_tasks.add_task(
                mail_service.send_welcome_email,
                email=user.email,
                name=user_display_name,
                org_name="",
            )

        hasOrg = UserService.user_has_org(db, user.id)
        org_id = UserService.get_user_org_id(db, user.id) if hasOrg else None

        hasSub = False
        if org_id is not None:
            hasSub = UserService.user_has_subscription(db, org_id)

        token_data = {
            "sub": str(user.id),
            "role": user.role,
            "username": user.username,
            "org_id": org_id,
            "has_subscription": hasSub,
        }

        access_token = create_access_token(token_data)
        refresh_token = create_refresh_token({"sub": str(user.id)})

        response_data = {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "bearer",
            "user": {
                "id": user.id,
                "username": user.username,
                "email": user.email,
                "role": user.role,
                "is_active": user.is_active,
                "created_at": user.created_at.isoformat()
                if hasattr(user.created_at, "isoformat")
                else user.created_at,
                "hasOrg": hasOrg,
                "org_id": org_id,
                "hasSub": hasSub,
                "google_id": user.google_id,
                "linkedin_id": user.linkedin_id,
                "apple_id": user.apple_id,
            },
        }

        if hasOrg:
            response_data["user"]["subdomain"] = UserService.user_sub_domain(
                db, user.id
            )

        return response_data

    except (ValueError, jwt.JWTError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Apple identity token signature or token expired",
        )


@router.post("/linkedin")
async def auth_linkedin(
    payload: LinkedInTokenPayload,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    if (
        not settings.LINKEDIN_CLIENT_ID
        or not settings.LINKEDIN_CLIENT_SECRET
        or not settings.LINKEDIN_REDIRECT_URI
    ):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="LinkedIn OAuth is not configured.",
        )

    token_response = requests.post(
        "https://www.linkedin.com/oauth/v2/accessToken",
        data={
            "grant_type": "authorization_code",
            "code": payload.code,
            "redirect_uri": settings.LINKEDIN_REDIRECT_URI,
            "client_id": settings.LINKEDIN_CLIENT_ID,
            "client_secret": settings.LINKEDIN_CLIENT_SECRET,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=10,
    )
    token_response.raise_for_status()
    token_data = token_response.json()
    access_token = token_data.get("access_token")

    if not access_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="LinkedIn token exchange failed.",
        )

    profile_response = requests.get(
        "https://api.linkedin.com/v2/me",
        headers={"Authorization": f"Bearer {access_token}"},
        params={"projection": "(id,localizedFirstName,localizedLastName)"},
        timeout=10,
    )
    profile_response.raise_for_status()
    profile_data = profile_response.json()

    email_response = requests.get(
        "https://api.linkedin.com/v2/emailAddress",
        headers={"Authorization": f"Bearer {access_token}"},
        params={
            "q": "members",
            "projection": "(elements*(handle~))",
        },
        timeout=10,
    )
    email_response.raise_for_status()
    email_data = email_response.json()

    email = email_data.get("elements", [{}])[0].get("handle~", {}).get("emailAddress")
    linkedin_id = profile_data.get("id")
    first_name = profile_data.get("localizedFirstName")
    last_name = profile_data.get("localizedLastName")

    if not email or not linkedin_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="LinkedIn account missing identity parameters.",
        )

    user = UserService.get_user_by_linkedin_id(db, linkedin_id)

    if not user:
        user = UserService.get_user_by_email(db, email)
        if user:
            user = UserService.update_user_social_id(
                db, user.id, "linkedin_id", linkedin_id
            )
            logger.info(f"Linked existing account to LinkedIn ID for: {email}")

    if not user:
        base_username = email.split("@")[0].replace(".", "_")
        username = base_username

        counter = 1
        while UserService.get_user_by_username(db, username):
            username = f"{base_username}_{counter}"
            counter += 1

        new_user_data = UserCreate(
            email=email,
            username=username,
            first_name=first_name,
            last_name=last_name,
            password=secrets.token_urlsafe(16),
            role=payload.role or "user",
            is_active=True,
            linkedin_id=linkedin_id,
            location=payload.location,
            country_iso=payload.country_iso,
            accepted_terms=True,
        )

        user = UserService.create_user(db, new_user_data)
        logger.info(f"Successfully registered new user via LinkedIn: {email}")

        user_display_name = new_user_data.first_name or user.username
        background_tasks.add_task(
            mail_service.send_welcome_email,
            email=user.email,
            name=user_display_name,
            org_name="",
        )

    hasOrg = UserService.user_has_org(db, user.id)
    org_id = UserService.get_user_org_id(db, user.id) if hasOrg else None

    hasSub = False
    if org_id is not None:
        hasSub = UserService.user_has_subscription(db, org_id)

    token_data = {
        "sub": str(user.id),
        "role": user.role,
        "username": user.username,
        "org_id": org_id,
        "has_subscription": hasSub,
    }

    access_token = create_access_token(token_data)
    refresh_token = create_refresh_token({"sub": str(user.id)})

    response_data = {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "user": {
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "role": user.role,
            "is_active": user.is_active,
            "created_at": user.created_at.isoformat()
            if hasattr(user.created_at, "isoformat")
            else user.created_at,
            "hasOrg": hasOrg,
            "org_id": org_id,
            "hasSub": hasSub,
            "google_id": user.google_id,
            "linkedin_id": user.linkedin_id,
            "apple_id": user.apple_id,
        },
    }

    if hasOrg:
        response_data["user"]["subdomain"] = UserService.user_sub_domain(db, user.id)

    return response_data


@router.post("/register")
async def register(
    user_data: UserCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    if UserService.get_user_by_email(db, user_data.email):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered!",
        )

    if UserService.get_user_by_username(db, user_data.username):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username already taken",
        )

    new_user = UserService.create_user(db, user_data)

    user_display_name = user_data.first_name or new_user.username
    org_name = ""

    try:
        background_tasks.add_task(
            mail_service.send_welcome_email,
            email=new_user.email,
            name=user_display_name,
            org_name=org_name,
        )

        otp_code = f"{secrets.randbelow(9000) + 1000}"
        expire = datetime.utcnow() + timedelta(minutes=15)

        otp_cache.set_otp(email=new_user.email, otp=otp_code, expires_at=expire)
        background_tasks.add_task(
            mail_service.send_email_confirmation,
            email=new_user.email,
            name=user_display_name,
            otp=otp_code,
        )
    except Exception as exc:
        # Registration is already persisted at this point; do not fail the API response.
        logger.exception(
            "Post-registration side effects failed for user_id=%s: %s", new_user.id, exc
        )

    return {
        "detail": "Verification code sent to your email!",
        "user_id": new_user.id,
    }


@router.post("/resend-otp")
async def resend_otp(
    payload: ResendOTPRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    user = UserService.get_user_by_email(db, payload.email)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found."
        )

    otp_code = f"{secrets.randbelow(9000) + 1000}"
    expire = datetime.utcnow() + timedelta(minutes=15)

    otp_cache.set_otp(email=user.email, otp=otp_code, expires_at=expire)
    background_tasks.add_task(
        mail_service.send_email_confirmation,
        email=user.email,
        name=getattr(user, "first_name", user.username) or "User",
        otp=otp_code,
    )

    return {"detail": "New verification code sent."}


@router.post("/forgot-password")
async def forgot_password(
    payload: ForgotPasswordRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    user = UserService.get_user_by_email(db, payload.email)

    if user:
        otp_code = f"{secrets.randbelow(9000) + 1000}"
        expire = datetime.utcnow() + timedelta(minutes=15)

        otp_cache.set_otp(email=user.email, otp=otp_code, expires_at=expire)
        logger.info(
            f"Generated OTP for password reset for user: {user.email}, OTP: {otp_code}"
        )

        user_display_name = getattr(user, "first_name", user.username) or "User"
        background_tasks.add_task(
            mail_service.send_password_reset_email,
            email=user.email,
            name=user_display_name,
            otp=otp_code,
        )

    return {
        "detail": "If the email is registered, a password recovery code has been generated."
    }


@router.post("/verify-otp")
async def verify_otp(payload: VerifyOTPRequest, db: Session = Depends(get_db)):
    is_valid = otp_cache.verify_and_destroy_otp(
        email=payload.email, incoming_otp=payload.otp
    )

    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The verification code is incorrect or has expired.",
        )

    user = UserService.get_user_by_email(db, payload.email)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User target missing."
        )

    if not user.is_active:
        user.is_active = True
        user.email_verified_at = datetime.now(timezone.utc)
        db.add(user)
        db.commit()
        db.refresh(user)
        logger.info(
            f"User account activated successfully via registration OTP track: {user.email}"
        )

    change_expiry = datetime.utcnow() + timedelta(minutes=5)
    action_token = jwt.encode(
        {
            "sub": str(user.id),
            "exp": change_expiry,
            "action": "verified_password_reset",
        },
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )

    return {
        "message": "OTP verification completed successfully.",
        "reset_token": action_token,
    }


@router.post("/reset-password")
async def reset_password(payload: ResetPasswordRequest, db: Session = Depends(get_db)):
    try:
        decoded_token = jwt.decode(
            payload.token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM]
        )

        if decoded_token.get("action") != "verified_password_reset":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid token validation pathway context intent.",
            )

        user_id = decoded_token.get("sub")
        user = UserService.get_user(db, user_id=int(user_id if user_id else 0))
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Target user profile record missing.",
            )

        user.hashed_password = hash_password(payload.new_password)
        db.add(user)
        db.commit()

        logger.info(
            f"Password modified successfully for verification subject identifier ID: {user_id}"
        )
        return {
            "detail": "Password has been successfully updated. You can now use your new credentials to sign in."
        }

    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The active authorization context signature link has expired.",
        )


@router.post("/logout")
async def logout():
    """
    Stateless JWT logging out relies on the client destroying the token.
    We simply return a success acknowledgment.
    """
    return {
        "detail": "Successfully logged out. Please clear token context parameters on the client layer."
    }


@router.post("/push-subscriptions")
async def upsert_push_subscription(
    payload: PushSubscriptionCreate,
    current_user: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    existing = None
    if payload.fcm_token:
        existing = (
            db.query(PushSubscription)
            .filter(PushSubscription.fcm_token == payload.fcm_token)
            .first()
        )

    if existing is None:
        # create new
        new = PushSubscription(
            user_id=current_user.user_id,
            fcm_token=payload.fcm_token,
            device_type=payload.device_type,
            device_meta=payload.device_meta,
        )
        db.add(new)
        db.commit()
        db.refresh(new)
        return {"detail": "Push subscription saved.", "id": new.id}

    # update existing
    existing.user_id = current_user.user_id
    existing.device_type = payload.device_type
    existing.device_meta = payload.device_meta
    db.add(existing)
    db.commit()
    db.refresh(existing)

    return {"detail": "Push subscription updated.", "id": existing.id}
