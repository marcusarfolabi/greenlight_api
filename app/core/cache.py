import logging
from datetime import datetime
from typing import Dict, Tuple

logger = logging.getLogger(__name__)

class OTPCacheManager:
    def __init__(self):
        self._cache: Dict[str, Tuple[str, datetime]] = {}

    def set_otp(self, email: str, otp: str, expires_at: datetime) -> None:
        """Stores or overwrites an OTP linked to an email with a fixed expiration time."""
        self._cache[email.lower().strip()] = (otp, expires_at)
        logger.info(f"Local memory cache set for identifier: {email.lower().strip()}")

    def verify_and_destroy_otp(self, email: str, incoming_otp: str) -> bool:
        """Checks code validity against an email. Destroys the cache entry on success."""
        clean_email = email.lower().strip()
        
        if clean_email not in self._cache:
            return False
            
        stored_otp, expires_at = self._cache[clean_email]
        
        if datetime.utcnow() > expires_at:
            del self._cache[clean_email]
            logger.warning(f"OTP verification failed: Token for {clean_email} has expired.")
            return False
            
        if stored_otp == incoming_otp:
            del self._cache[clean_email]
            logger.info(f"OTP successfully verified and purged from memory cache for: {clean_email}")
            return True
            
        return False

otp_cache = OTPCacheManager()