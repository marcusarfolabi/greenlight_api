import logging
import uuid

from app.models.arena import Arena
from app.models.organization import ArenaPayoutReport
from app.models.player import Player, PlayerBankingProfile
from app.models.user import User
from app.services.mail_service import MailService
from app.services.twilio_service import TwilioService
from fastapi import (
    APIRouter,
)
from sqlalchemy import func
from sqlalchemy.orm import Session

router = APIRouter()
logger = logging.getLogger(__name__)

# Upload limits
MAX_UPLOAD_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB
MAX_PDF_PAGES = 50


def _new_players_session_id() -> str:
    return str(uuid.uuid4())


def _ensure_arena_session_id(db: Session, arena: Arena) -> str:
    if arena.players_session_id:
        return arena.players_session_id

    arena.players_session_id = _new_players_session_id()
    db.add(arena)
    db.flush()
    return arena.players_session_id


def _players_for_arena_session_query(db: Session, arena: Arena):
    query = db.query(Player).filter(Player.arena_id == arena.id)
    if arena.players_session_id:
        query = query.filter(Player.session_id == arena.players_session_id)
    return query


async def _bg_send_sms(
    to: str, recipient_name: str | None, body: str, arena_access_code: int
):
    try:
        ok = await TwilioService.send_sms_arena_access_code_async(
            to, recipient_name, body
        )
        if ok:
            logger.info(
                "Queued SMS sent to %s for arena access code %s", to, arena_access_code
            )
        else:
            logger.warning(
                "Queued SMS failed to send to %s for arena access code %s",
                to,
                arena_access_code,
            )
    except Exception:
        logger.exception(
            "Error sending queued SMS to %s for arena access code %s",
            to,
            arena_access_code,
        )


async def _bg_send_email(
    to: str,
    recipient_name: str | None,
    subject: str,
    body: str,
    arena_details: dict,
    org_name: str | None,
):
    try:
        await MailService.send_email_arena_access_code(
            to, recipient_name or "Participant", subject, body, arena_details, org_name
        )
        logger.info(
            "Queued email sent to %s for arena %s", to, arena_details.get("arena_name")
        )
    except Exception:
        logger.exception(
            "Error sending queued email to %s for arena %s",
            to,
            arena_details.get("arena_name"),
        )


def _username_seed_from_player_name(player_name: str | None) -> str:
    if not player_name:
        return "player"
    normalized = "".join(
        c if (c.isalnum() or c in {"_", ".", "-"}) else "_"
        for c in player_name.strip().lower()
    )
    normalized = "_".join(part for part in normalized.split("_") if part)
    return (normalized or "player")[:40]


def _generate_unique_username(db: Session, seed: str) -> str:
    candidate = seed[:50] or "player"
    counter = 1
    while db.query(User).filter(User.username == candidate).first():
        suffix = f"_{counter}"
        candidate = f"{seed[: max(1, 50 - len(suffix))]}{suffix}"
        counter += 1
    return candidate


def _mask_account_number(account_number: str | None) -> str:
    if not account_number:
        return "-"
    value = account_number.strip()
    if len(value) <= 4:
        return value
    return f"{'*' * (len(value) - 4)}{value[-4:]}"


async def _notify_superadmins_payout_ready(arena: Arena, db: Session) -> None:
    payout_rows_raw = (
        db.query(ArenaPayoutReport, PlayerBankingProfile)
        .outerjoin(
            PlayerBankingProfile,
            PlayerBankingProfile.player_id == ArenaPayoutReport.player_id,
        )
        .filter(
            ArenaPayoutReport.arena_id == arena.id,
            ArenaPayoutReport.payout_amount_cents > 0,
            ArenaPayoutReport.payout_status == "pending",
        )
        .order_by(ArenaPayoutReport.final_rank.asc())
        .all()
    )

    if not payout_rows_raw:
        return

    payout_rows: list[dict] = []
    total_payout_cents = 0
    for report, profile in payout_rows_raw:
        payout_cents = int(report.payout_amount_cents or 0)
        total_payout_cents += payout_cents
        payout_rows.append(
            {
                "rank": report.final_rank,
                "username": report.username,
                "payout_amount": f"GBP {(payout_cents / 100):.2f}",
                "account_holder_name": (
                    profile.account_holder_name if profile else "Not provided"
                ),
                "email": profile.email if profile else "Not provided",
                "phone_number": (
                    profile.phone_number
                    if profile and profile.phone_number
                    else "Not provided"
                ),
                "bank_name_or_code": (
                    profile.bank_code
                    if profile and profile.bank_code
                    else "Not provided"
                ),
                "masked_account_number": _mask_account_number(
                    profile.account_number if profile else None
                ),
            }
        )

    superadmins = db.query(User).filter(func.lower(User.role) == "superadmin").all()
    if not superadmins:
        logger.warning(
            "No superadmin users found for payout notification on arena %s", arena.id
        )
        return

    for admin in superadmins:
        try:
            await MailService.send_superadmin_payout_notification(
                email=admin.email,
                admin_name=admin.first_name or admin.username or "Admin",
                arena_name=arena.arena_name,
                arena_id=arena.id,
                access_code=str(arena.access_code),
                payout_rows=payout_rows,
                payout_count=len(payout_rows),
                total_payout=f"GBP {(total_payout_cents / 100):.2f}",
                admin_login_url="https://admin.greenlightquiz.com/login",
            )
        except Exception:
            logger.exception(
                "Failed sending superadmin payout notification for arena %s to %s",
                arena.id,
                admin.email,
            )
