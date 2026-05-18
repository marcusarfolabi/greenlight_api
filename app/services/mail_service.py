from fastapi_mail import FastMail, MessageSchema, MessageType
from app.core.config import mail_conf

class MailService:
    
    @staticmethod
    async def send_welcome_email(email: str, name: str, org_name: str):
        message = MessageSchema(
            subject="Welcome to FalconMail",
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

mail_service = MailService()