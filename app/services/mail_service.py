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

    @staticmethod
    async def send_subscription_message(email: str, name: str, org_name: str, plan_details: dict):
        message = MessageSchema(
            subject=f"Your {plan_details.get('plan_name')} subscription is active",
            recipients=[email],
            template_body={
                "name": name,
                "org_name": org_name,
                **plan_details,
            },
            subtype=MessageType.html,
        )
        fm = FastMail(mail_conf)
        await fm.send_message(message, template_name="subscription_message.html")

    @staticmethod
    async def send_token_purchase_confirmation(email: str, name: str, org_name: str, tokens_purchased: int, cost: float, currency: str, total_tokens: int):
        message = MessageSchema(
            subject=f"Token Purchase Confirmation - {tokens_purchased:,} tokens",
            recipients=[email],
            template_body={
                "name": name,
                "org_name": org_name,
                "tokens_purchased": f"{tokens_purchased:,}",
                "cost": f"{cost:.2f}",
                "currency": currency,
                "total_tokens": f"{total_tokens:,}",
            },
            subtype=MessageType.html,
        )
        fm = FastMail(mail_conf)
        await fm.send_message(message, template_name="token_purchase_confirmation.html")

    @staticmethod
    async def send_superadmin_payout_notification(
        email: str,
        admin_name: str,
        arena_name: str,
        arena_id: str,
        access_code: str,
        payout_rows: list[dict],
        payout_count: int,
        total_payout: str,
        admin_login_url: str,
    ):
        message = MessageSchema(
            subject=f"Payout details ready - {arena_name}",
            recipients=[email],
            template_body={
                "admin_name": admin_name,
                "arena_name": arena_name,
                "arena_id": arena_id,
                "access_code": access_code,
                "payout_rows": payout_rows,
                "payout_count": payout_count,
                "total_payout": total_payout,
                "admin_login_url": admin_login_url,
            },
            subtype=MessageType.html,
        )
        fm = FastMail(mail_conf)
        await fm.send_message(
            message, template_name="superadmin_payout_notification.html"
        )

mail_service = MailService()
