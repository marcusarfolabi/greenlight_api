import logging
import secrets
from datetime import datetime, timedelta
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status, Response
from sqlalchemy.orm import Session
from jose import jwt, JWTError

from google.oauth2 import id_token
from google.auth.transport import requests as google_requests

from app.core.config import settings 
from app.core.security import create_access_token, create_refresh_token, verify_password, hash_password
from app.db.session import get_db
from app.models.user import UserRole
from app.schemas.user import ForgotPasswordRequest, GoogleTokenPayload, ResendOTPRequest, ResetPasswordRequest, TokenRefreshRequest, UserCreate, UserResponse, VerifyOTPRequest
from app.services.user_service import UserService           
from app.services.mail_service import mail_service  
from app.core.cache import otp_cache  


router = APIRouter()
logger = logging.getLogger(__name__) 


@router.post("/login")
async def login(username: str, password: str, response: Response, db: Session = Depends(get_db)):
    user = UserService.get_user_by_login(db, username)
    if not user or not verify_password(password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username/email or password",
        )

    token_data = {
        "sub": str(user.id),
        "role": user.role,
        "username": user.username
    }
    access_token = create_access_token(data=token_data)
    
    # Set the secure token as an HttpOnly Cookie
    response.set_cookie(
        key="auth_token",
        value=access_token,
        httponly=True,       # Prevents JavaScript reading the token (Stops Postman exfiltration)
        secure=True,         # Ensures cookie is only sent over HTTPS connections
        samesite="lax",      # Guards against Cross-Site Request Forgery (CSRF)
        max_age=3600,        # Match access token duration (e.g., 1 hour)
        path="/"
    )

    return {
        "user": {
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "role": user.role
        }
    }

 
@router.post("/refresh")
async def refresh_token(payload: TokenRefreshRequest, db: Session = Depends(get_db)):
    """Exchange a valid, unexpired refresh token for a brand new access token."""
    from app.services.user_service import UserService
    try:
        decoded_token = jwt.decode(
            payload.refresh_token, 
            settings.JWT_SECRET_KEY, 
            algorithms=[settings.JWT_ALGORITHM]
        ) 
        if decoded_token.get("type") != "refresh":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, 
                detail="Invalid token type context"
            )
            
        user_id = decoded_token.get("sub")
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, 
                detail="Missing subject token claim"
            )
            
        user = UserService.get_user(db, user_id=int(user_id))
        if not user or not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, 
                detail="User account is deactivated or missing"
            )
            
        # Re-mint access token using existing structural payload logic
        new_access_token = create_access_token({
            "sub": str(user.id),
            "role": user.role,
            "username": user.username,
            "email": user.email,
        })
        
        return {
            "access_token": new_access_token,
            "token_type": "bearer"
        }
        
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, 
            detail="Refresh token signature has expired or is invalid"
        )


@router.post("/google")
async def auth_google(payload: GoogleTokenPayload, db: Session = Depends(get_db)):
    try:
        id_info = id_token.verify_oauth2_token(
            payload.token, 
            google_requests.Request(), 
            settings.GOOGLE_CLIENT_ID
        )

        email = id_info.get('email')
        name = id_info.get('name', 'Google User')
        
        if not email:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, 
                detail="Google account missing email address."
            )

        user = UserService.get_user_by_email(db, email)

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
                first_name=name.split(' ')[0] if name else None,
                last_name=name.split(' ', 1)[1] if name and ' ' in name else None,
                password=secrets.token_urlsafe(16), 
                role="user"
                
            )
            
            user = UserService.create_user(db, new_user_data)
            logger.info(f"Successfully registered new user via Google: {email}")

        token_data = {
            "sub": str(user.id),
            "role": user.role,
            "username": user.username,
            "email": user.email,
        }

        return {
            "access_token": create_access_token(token_data),
            "refresh_token": create_refresh_token({"sub": str(user.id)}),
            "token_type": "bearer",
            "role": user.role,
            "username": user.username,
            "email": user.email,
            "id": user.id,
            "is_active": user.is_active,
            "created_at": user.created_at,
        }

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
            detail="Email already registered",
        )

    if UserService.get_user_by_username(db, user_data.username):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username already taken",
        )

    new_user = UserService.create_user(db, user_data)
    
    user_display_name = user_data.first_name or new_user.username
    org_name = "GreenLight"  

    # 3. Schedule welcome communication
    background_tasks.add_task(
        mail_service.send_welcome_email,
        email=new_user.email,
        name=user_display_name,
        org_name=org_name
    )
    
    otp_code = f"{secrets.randbelow(900000) + 100000}"
    expire = datetime.utcnow() + timedelta(minutes=15)
        
    otp_cache.set_otp(email=new_user.email, otp=otp_code, expires_at=expire)
    background_tasks.add_task(
        mail_service.send_email_confirmation,
        email=new_user.email,
        name=user_display_name,
        otp=otp_code
    )
    
    return new_user

# function to resend the otp afer countdown
@router.post("/resend-otp")
async def resend_otp(payload: ResendOTPRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """Resend a new verification code to the user's email."""
    user = UserService.get_user_by_email(db, payload.email)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")

    otp_code = f"{secrets.randbelow(900000) + 100000}"
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
        otp_code = f"{secrets.randbelow(900000) + 100000}"
        expire = datetime.utcnow() + timedelta(minutes=15)
        
        # 1. Persist the credentials inside our secure runtime tracker storage
        otp_cache.set_otp(email=user.email, otp=otp_code, expires_at=expire)
        
        # 2. Fire the mail worker
        user_display_name = getattr(user, 'first_name', user.username) or "User"
        background_tasks.add_task(
            mail_service.send_password_reset_email,
            email=user.email,
            name=user_display_name,
            otp=otp_code 
        )
        logger.info(f"Password reset OTP sent to background queue for user: {user.email}")
        
    return {"detail": "If the email is registered, a password recovery code has been generated."}

@router.post("/verify-otp")
async def verify_otp(payload: VerifyOTPRequest, db: Session = Depends(get_db)):
    """Checks cache validation accuracy. Destroys entry on match and returns a transient payload modifier token."""
    is_valid = otp_cache.verify_and_destroy_otp(email=payload.email, incoming_otp=payload.otp)
    
    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The verification code entered is incorrect, invalid, or has expired."
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
        
        
@router.post("/auth/logout")
async def logout(response: Response):
    response.delete_cookie(
        key="auth_token",
        path="/",
        domain=None  
    )
    return {"detail": "Successfully logged out and session context revoked."}