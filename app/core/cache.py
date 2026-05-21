import logging
import json
import os
from datetime import datetime
from typing import Dict, Tuple, Optional

logger = logging.getLogger(__name__)

class OTPCacheManager:
    CACHE_FILE = "/app/cache/otp_cache.json"

    def _load(self) -> Dict[str, Tuple[str, str]]:
        """Loads the cache from the JSON file."""
        if not os.path.exists(self.CACHE_FILE):
            return {}
        try:
            with open(self.CACHE_FILE, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return {}

    def _save(self, data: Dict[str, Tuple[str, str]]) -> None:
        """Saves the cache to the JSON file."""
        with open(self.CACHE_FILE, "w") as f:
            json.dump(data, f)

    def set_otp(self, email: str, otp: str, expires_at: datetime) -> None:
        """Stores or overwrites an OTP linked to an email with a fixed expiration time."""
        data = self._load()
        data[email.lower().strip()] = (otp, expires_at.isoformat())
        self._save(data)
        logger.info(f"Persistent file cache set for identifier: {email.lower().strip()}")

    def verify_and_destroy_otp(self, email: str, incoming_otp: str) -> bool:
        """Checks code validity against an email. Destroys the cache entry on success."""
        data = self._load()
        clean_email = email.lower().strip()
        
        if clean_email not in data:
            return False
            
        stored_otp, expires_at_str = data[clean_email]
        expires_at = datetime.fromisoformat(expires_at_str)
        
        # Check expiration
        if datetime.utcnow() > expires_at:
            del data[clean_email]
            self._save(data)
            logger.warning(f"OTP verification failed: Token for {clean_email} has expired.")
            return False
            
        # Verify match
        if stored_otp == str(incoming_otp).strip():
            del data[clean_email]
            self._save(data)
            logger.info(f"OTP successfully verified and purged from persistent cache: {clean_email}")
            return True
            
        return False

otp_cache = OTPCacheManager()