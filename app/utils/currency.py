import logging
import pycountry
from typing import Optional

logger = logging.getLogger(__name__)

def get_currency_by_country_code(country_code: Optional[str]) -> str: 
    logger.debug("get_currency_by_country_code called with country_code: %r", country_code)
    
    if not country_code:
        logger.warning("No country_code provided to helper. Falling back to default 'gbp'.")
        return "gbp" 
        
    try:
        formatted_country = str(country_code).strip().upper()
        logger.debug("Formatted country code to look up: %r", formatted_country)
        
        country = pycountry.countries.get(alpha_2=formatted_country)
        if country:
            logger.debug("Found country object: Name=%r, Numeric=%r", country.name, getattr(country, 'numeric', None))
            
            # Direct attribute fallback comparison loop
            for currency in pycountry.currencies:
                if getattr(currency, "numeric", None) == getattr(country, "numeric", None):
                    detected = currency.alpha_3.lower()
                    logger.info("Successfully matched country %r to currency %r", formatted_country, detected)
                    return detected
            
            logger.warning("Country object found for %r, but no matching currency numeric code found.", formatted_country)
        else:
            logger.warning("pycountry could not find a country matching alpha_2 code: %r", formatted_country)
            
    except Exception as e:
        logger.exception("Exception occurred in get_currency_by_country_code: %s", str(e))
        
    logger.info("Falling back to default 'gbp'")
    return "gbp"