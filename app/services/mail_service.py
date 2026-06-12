from typing import Optional
from fastapi_mail import FastMail, MessageSchema, MessageType
from app.core.config import mail_conf

class MailService:
    
    @staticmethod
    async def send_welcome_email(email: str, name: str, org_name: str):
        message = MessageSchema(
            subject="Welcome to Green Light Quiz!",
            recipients=[email],
            template_body={"name": name, "org_name": org_name},
            subtype=MessageType.html
        )
        fm = FastMail(mail_conf)
        await fm.send_message(message, template_name="welcome_email.html")
        
    @staticmethod
    async def send_password_reset_email(email: str, name: str, otp: str):
        message = MessageSchema(
            subject=f"Password Reset Request - {otp}",
            recipients=[email],
            template_body={"name": name, "otp": otp},
            subtype=MessageType.html
        )
        fm = FastMail(mail_conf)
        await fm.send_message(message, template_name="password_reset_email.html")
        
    @staticmethod
    async def send_email_confirmation(email: str, name: str, otp: str):
        message = MessageSchema(
            subject=f"Email Confirmation - {otp}",
            recipients=[email],
            template_body={"name": name, "otp": otp},
            subtype=MessageType.html
        )
        fm = FastMail(mail_conf)
        await fm.send_message(message, template_name="email_confirmation.html")
    
    @staticmethod
    async def send_email_arena_access_code(email: str, name: str, subject: str, body: str, arena_details: dict, org_name: Optional[str] = None):
        message = MessageSchema(
            subject=f"{subject} - {arena_details.get('arena_name')}",
            recipients=[email],
            template_body={
                "name": name,
                "body": body,
                "arena_name": arena_details.get("arena_name"),
                "access_code": arena_details.get("access_code"),
                "org_name": org_name or "",
            },
            subtype=MessageType.html,
        )
        fm = FastMail(mail_conf)
        await fm.send_message(message, template_name="arena_access_code.html")

mail_service = MailService()