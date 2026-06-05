import logging
from typing import Optional

from app.core.config import settings

logger = logging.getLogger(__name__)


class TwilioService:
    """Lightweight wrapper around Twilio Client for sending SMS messages.

    This service is optional — if the Twilio SDK is not installed or
    configuration is missing, calls will be logged but will not raise.
    """

    _client = None
    _async_client = None

    @classmethod
    def _get_client(cls):
        if cls._client is not None:
            return cls._client

        try:
            from twilio.rest import Client # type: ignore
        except Exception:
            logger.warning("Twilio SDK not installed; SMS sending disabled")
            return None

        sid = getattr(settings, "TWILIO_ACCOUNT_SID", None)
        token = getattr(settings, "TWILIO_AUTH_TOKEN", None)

        if not sid or not token:
            logger.warning("Twilio credentials not configured; SMS sending disabled")
            return None

        try:
            cls._client = Client(sid, token)
            return cls._client
        except Exception as e:
            logger.exception("Failed to initialize Twilio client: %s", e)
            return None

    @classmethod
    def _get_async_client(cls):
        if cls._async_client is not None:
            return cls._async_client

        try:
            from twilio.http.async_http_client import AsyncTwilioHttpClient
            from twilio.rest import Client
        except Exception:
            logger.info("Twilio async client not available; will fallback")
            return None

        sid = getattr(settings, "TWILIO_ACCOUNT_SID", None)
        token = getattr(settings, "TWILIO_AUTH_TOKEN", None)

        if not sid or not token:
            logger.warning("Twilio credentials not configured; async SMS disabled")
            return None

        try:
            http_client = AsyncTwilioHttpClient()
            cls._async_client = Client(sid, token, http_client=http_client)
            return cls._async_client
        except Exception as e:
            logger.exception("Failed to initialize Twilio async client: %s", e)
            return None

    @classmethod
    def send_sms_arena_access_code(cls, to_number: str, recipient_name: Optional[str], body: str) -> bool:
        """Send an SMS to `to_number` with `body`.

        Returns True if the message was sent (or queued) successfully, False otherwise.
        """
        client = cls._get_client()
        from_number = getattr(settings, "TWILIO_FROM_NUMBER", None)

        if client is None:
            logger.info("SMS not sent (Twilio disabled) to %s: %s", to_number, body)
            return False

        if not from_number:
            logger.warning("TWILIO_FROM_NUMBER not configured; cannot send SMS")
            return False

        try:
            message = client.messages.create(
                body=body,
                from_=from_number,
                to=to_number,
            )
            logger.info("Sent SMS to %s; sid=%s", to_number, getattr(message, "sid", None))
            return True
        except Exception as e:
            logger.exception("Failed to send SMS to %s: %s", to_number, e)
            return False

    @classmethod
    async def send_sms_arena_access_code_async(cls, to_number: str, recipient_name: Optional[str], body: str) -> bool:
        """Asynchronously send an SMS using Twilio's async client when available.

        Falls back to running the synchronous client in a thread if async client isn't available.
        """
        async_client = cls._get_async_client()
        from_number = getattr(settings, "TWILIO_FROM_NUMBER", None)

        if async_client is not None and from_number:
            try:
                message = await async_client.messages.create_async(
                    to=to_number,
                    from_=from_number,
                    body=body,
                )
                logger.info("Sent async SMS to %s; sid=%s", to_number, getattr(message, "sid", None))
                return True
            except Exception as e:
                logger.exception("Failed to send async SMS to %s: %s", to_number, e)
                return False

        # Fallback: use sync client in a thread to avoid blocking event loop
        client = cls._get_client()
        if client is None:
            logger.info("SMS not sent (Twilio disabled) to %s: %s", to_number, body)
            return False

        import asyncio

        def _sync_send():
            try:
                msg = client.messages.create(body=body, from_=from_number, to=to_number)
                return getattr(msg, "sid", None)
            except Exception:
                return None

        try:
            sid = await asyncio.to_thread(_sync_send)
            if sid:
                logger.info("Sent SMS (sync fallback) to %s; sid=%s", to_number, sid)
                return True
            logger.warning("Failed to send SMS (sync fallback) to %s", to_number)
            return False
        except Exception as e:
            logger.exception("Error in SMS fallback send to %s: %s", to_number, e)
            return False


twilio_service = TwilioService()
