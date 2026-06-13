import logging
import os
import secrets
from datetime import datetime, timedelta
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status, Response, Form
from sqlalchemy.orm import Session
from jose import jwt, JWTError

from google.oauth2 import id_token
from google.auth.transport import requests as google_requests

from app.core.config import settings  
from app.core.security import create_access_token, create_refresh_token, get_current_user, verify_password, hash_password
from app.db.session import get_db
from app.schemas.user import AuthContext, ForgotPasswordRequest, GoogleTokenPayload, ResendOTPRequest, ResetPasswordRequest, TokenRefreshRequest, UserCreate, UserResponse, VerifyOTPRequest
from app.services.user_service import UserService           
from app.services.mail_service import mail_service  
from app.core.cache import otp_cache  


router = APIRouter()
logger = logging.getLogger(__name__) 

@router.post("/login")
async def login(
    response: Response,
    username: str = Form(...),   
    password: str = Form(...),   
    db: Session = Depends(get_db)
):
    user = UserService.get_user_by_login(db, username)
    
    if not user or not verify_password(password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username/email or password",
        )

    hasOrg = UserService.user_has_org(db, user.id)
    org_id = UserService.get_user_org_id(db, user.id) if hasOrg else None

    # Explicitly check that org_id is not None before passing it
    hasSub = False
    if org_id is not None:
        hasSub = UserService.user_has_subscription(db, org_id)
    
    token_data = {
        "sub": str(user.id),
        "role": user.role,
        "username": user.username,
        "org_id": org_id,
        "has_subscription": hasSub  # Included in JWT payload if your frontend needs it from token decryption
    }
    
    access_token = create_access_token(data=token_data)
    is_production = os.getenv("ENVIRONMENT") == "production"
    
    response.set_cookie(
        key="auth_token",
        value=access_token,
        httponly=True,
        secure=is_production,
        samesite="lax",        
        domain=".webshoptechnology.us" if is_production else "localhost",
        max_age=21600,
        path="/"
    )
    
    response_data = {
        "user": {
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "role": user.role,
            "hasOrg": hasOrg,
            "org_id": org_id,
            "hasSub": hasSub  # Included in the explicit JSON response payload
        }
    }
    
    if hasOrg:
        subdomain = UserService.user_sub_domain(db, user.id)
        response_data["user"]["subdomain"] = subdomain
    
    response.status_code = 200
    return response_data

@router.post("/refresh-token")
async def refresh_user_token(
    response: Response,
    current_user: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db)
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
        "has_subscription": hasSub
    }

    access_token = create_access_token(token_data)
    is_production = os.getenv("ENVIRONMENT") == "production"
    
    response.set_cookie(
        key="auth_token",
        value=access_token,
        httponly=True,
        secure=is_production,
        samesite="lax",        
        domain=".webshoptechnology.us" if is_production else "localhost",
        max_age=21600,
        path="/"
    )

    return {
        "access_token": access_token,
        "user": {
            "id": db_user.id,
            "username": db_user.username,
            "email": db_user.email,  
            "role": db_user.role,
            "hasOrg": hasOrg,
            "org_id": org_id,
            "hasSub": hasSub
        }
    }


@router.post("/google")
async def auth_google(
    response: Response, 
    payload: GoogleTokenPayload, 
    background_tasks: BackgroundTasks,   
    db: Session = Depends(get_db)
):
    try:
        id_info = id_token.verify_oauth2_token(
            payload.token, 
            google_requests.Request(), 
            settings.GOOGLE_CLIENT_ID
        )
        
        google_id = id_info.get('sub')
        email = id_info.get('email')
        first_name = id_info.get('given_name')
        last_name = id_info.get('family_name')
        
        if not email or not google_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, 
                detail="Google account missing identity parameters."
            )

        user = UserService.get_user_by_google_id(db, google_id)
        
        user = UserService.get_user_by_email(db, email)

        if not user:
            user = UserService.get_user_by_email(db, email)
            if user:
                user = UserService.update_user_social_id(db, user.id, "google_id", google_id)
                logger.info(f"Linked existing account to Google ID for: {email}")
                
        if not user:
            base_username = email.split('@')[0].replace('.', '_')
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
                role="user",
                is_active=True,
                google_id=google_id
            )
            
            user = UserService.create_user(db, new_user_data)
            logger.info(f"Successfully registered new user via Google: {email}")

            user_display_name = new_user_data.first_name or user.username
            background_tasks.add_task(
                mail_service.send_welcome_email,
                email=user.email,
                name=user_display_name,
                org_name=""
            )

        hasOrg = UserService.user_has_org(db, user.id)
        org_id = UserService.get_user_org_id(db, user.id) if hasOrg else None
        
        # Guard against passing None to subscription check
        hasSub = False
        if org_id is not None:
            hasSub = UserService.user_has_subscription(db, org_id)
    
        token_data = {
            "sub": str(user.id),
            "role": user.role,
            "username": user.username,
            "org_id": org_id,
            "has_subscription": hasSub
        }

        # ============ BAKE COOKIES (MATCHES LOGIN ROUTE) ============
        access_token = create_access_token(token_data)
        is_production = os.getenv("ENVIRONMENT") == "production"
        
        response.set_cookie(
            key="auth_token",
            value=access_token,
            httponly=True,
            secure=is_production,
            samesite="lax",        
            domain=".webshoptechnology.us" if is_production else "localhost",
            max_age=21600,
            path="/"
        )

        response_data = {
            "access_token": access_token,
            "refresh_token": create_refresh_token({"sub": str(user.id)}),
            "token_type": "bearer",
            "user": {
                "id": user.id,
                "username": user.username,
                "email": user.email,
                "role": user.role,
                "is_active": user.is_active,
                "created_at": user.created_at.isoformat() if hasattr(user.created_at, "isoformat") else user.created_at,
                "hasOrg": hasOrg,
                "org_id": org_id,
                "hasSub": hasSub
            }
        }

        # Include subdomain if workspace is configured
        if hasOrg:
            response_data["user"]["subdomain"] = UserService.user_sub_domain(db, user.id)

        response.status_code = 200
        return response_data

    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, 
            detail="Invalid Google OAuth token signature or token expired"
        )
        
@router.post("/register", response_model=UserResponse)
async def register(user_data: UserCreate, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
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

    # 3. Schedule welcome communication
    # background_tasks.add_task(
    #     mail_service.send_welcome_email,
    #     email=new_user.email,
    #     name=user_display_name,
    #     org_name=org_name
    # )
    
    otp_code = f"{secrets.randbelow(9000) + 1000}"
    expire = datetime.utcnow() + timedelta(minutes=15)
        
    otp_cache.set_otp(email=new_user.email, otp=otp_code, expires_at=expire)
    # background_tasks.add_task(
    #     mail_service.send_email_confirmation,
    #     email=new_user.email,
    #     name=user_display_name,
    #     otp=otp_code
    # )
    
    return new_user

@router.post("/resend-otp")
async def resend_otp(payload: ResendOTPRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """Resend a new verification code to the user's email."""
    user = UserService.get_user_by_email(db, payload.email)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")

    otp_code = f"{secrets.randbelow(9000) + 1000}"
    expire = datetime.utcnow() + timedelta(minutes=15)
 
    otp_cache.set_otp(email=user.email, otp=otp_code, expires_at=expire)
    background_tasks.add_task(
        mail_service.send_email_confirmation,
        email=user.email,
        name=getattr(user, 'first_name', user.username) or "User",
        otp=otp_code
    )

    return {"detail": "New verification code sent."}

 
@router.post("/forgot-password")
async def forgot_password(payload: ForgotPasswordRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """Check email existence and generate a cryptographically signed recovery token."""
    user = UserService.get_user_by_email(db, payload.email)
     
    if user:
        otp_code = f"{secrets.randbelow(9000) + 1000}"
        expire = datetime.utcnow() + timedelta(minutes=15)
        
        otp_cache.set_otp(email=user.email, otp=otp_code, expires_at=expire)
        
        user_display_name = getattr(user, 'first_name', user.username) or "User"
        background_tasks.add_task(
            mail_service.send_password_reset_email,
            email=user.email,
            name=user_display_name,
            otp=otp_code 
        )
         
    return {"detail": "If the email is registered, a password recovery code has been generated."}

@router.post("/verify-otp")
async def verify_otp(payload: VerifyOTPRequest, db: Session = Depends(get_db)):
    """Checks cache validation accuracy. Destroys entry on match and returns a transient payload modifier token.""" 
    is_valid = otp_cache.verify_and_destroy_otp(email=payload.email, incoming_otp=payload.otp)
    
    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The verification code is incorrect or has expired."
        )
        
    user = UserService.get_user_by_email(db, payload.email)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User target missing.")
        
    change_expiry = datetime.utcnow() + timedelta(minutes=5)
    action_token = jwt.encode(
        {"sub": str(user.id), "exp": change_expiry, "action": "verified_password_reset"},
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM
    )
    
    return {
        "message": "OTP verification completed successfully.",
        "reset_token": action_token
    }

@router.post("/reset-password")
async def reset_password(payload: ResetPasswordRequest, db: Session = Depends(get_db)):
    """Accept the validated verification token payload block and securely update database password entries."""
    try:
        decoded_token = jwt.decode(
            payload.token, 
            settings.JWT_SECRET_KEY, 
            algorithms=[settings.JWT_ALGORITHM]
        )
        
        if decoded_token.get("action") != "verified_password_reset":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, 
                detail="Invalid token validation pathway context intent."
            )
            
        user_id = decoded_token.get("sub")
        user = UserService.get_user(db, user_id=int(user_id if user_id else 0))
        if not user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Target user profile record missing.")
            
        # Complete secure parameter data mutations
        user.hashed_password = hash_password(payload.new_password)
        db.add(user)
        db.commit()
        
        logger.info(f"Password modified successfully for verification subject identifier ID: {user_id}")
        return {"detail": "Password has been successfully updated. You can now use your new credentials to sign in."}
        
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail="The active authorization context signature link has expired."
        )
        
        
@router.post("/logout")
async def logout(response: Response):
    is_production = os.getenv("ENVIRONMENT") == "production"
    
    response.delete_cookie(
        key="auth_token",
        path="/", 
        domain=".webshoptechnology.us" if is_production else "localhost",
    )
    return {"detail": "Successfully logged out and session context revoked."}