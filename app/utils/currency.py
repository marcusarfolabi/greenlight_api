import logging
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

import pycountry
import requests

logger = logging.getLogger(__name__)

EXCHANGE_RATE_API_URL = "https://open.er-api.com/v6/latest/{base_currency}"

# Stripe currencies that do not use a 2-decimal minor unit.
ZERO_DECIMAL_CURRENCIES = {
    "bif",
    "clp",
    "djf",
    "gnf",
    "jpy",
    "kmf",
    "krw",
    "mga",
    "pyg",
    "rwf",
    "ugx",
    "vnd",
    "vuv",
    "xaf",
    "xof",
    "xpf",
}


def get_currency_by_country_code(country_code: Optional[str]) -> str:
    logger.debug(
        "get_currency_by_country_code called with country_code: %r", country_code
    )

    if not country_code:
        logger.warning(
            "No country_code provided to helper. Falling back to default 'gbp'."
        )
        return "gbp"

    try:
        formatted_country = str(country_code).strip().upper()
        logger.debug("Formatted country code to look up: %r", formatted_country)

        country = pycountry.countries.get(alpha_2=formatted_country)
        if country:
            logger.debug(
                "Found country object: Name=%r, Numeric=%r",
                country.name,
                getattr(country, "numeric", None),
            )

            # Direct attribute fallback comparison loop
            for currency in pycountry.currencies:
                if getattr(currency, "numeric", None) == getattr(
                    country, "numeric", None
                ):
                    detected = currency.alpha_3.lower()
                    logger.info(
                        "Successfully matched country %r to currency %r",
                        formatted_country,
                        detected,
                    )
                    return detected

            logger.warning(
                "Country object found for %r, but no matching currency numeric code found.",
                formatted_country,
            )
        else:
            logger.warning(
                "pycountry could not find a country matching alpha_2 code: %r",
                formatted_country,
            )

    except Exception as e:
        logger.exception(
            "Exception occurred in get_currency_by_country_code: %s", str(e)
        )

    logger.info("Falling back to default 'gbp'")
    return "gbp"


def fetch_exchange_rate(from_currency: str, to_currency: str) -> Decimal:
    """Fetch a live FX rate from a public exchange-rate endpoint."""
    base = (from_currency or "gbp").lower()
    quote = (to_currency or "gbp").lower()

    if base == quote:
        return Decimal("1")

    url = EXCHANGE_RATE_API_URL.format(base_currency=base.upper())
    response = requests.get(url, timeout=5)
    response.raise_for_status()

    payload = response.json()
    rates = payload.get("rates") if isinstance(payload, dict) else None
    if not isinstance(rates, dict):
        raise ValueError("Exchange-rate provider returned an invalid payload")

    rate = rates.get(quote.upper())
    if rate is None:
        raise ValueError(f"No exchange rate available for {base}->{quote}")

    return Decimal(str(rate))


def convert_major_amount(
    amount: Decimal, from_currency: str, to_currency: str
) -> Decimal:
    """Convert a major-unit amount (e.g. 14.99) from one currency to another."""
    rate = fetch_exchange_rate(from_currency, to_currency)
    converted = amount * rate
    return converted.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def to_minor_units(amount_major: Decimal, currency: str) -> int:
    """Convert major units to integer minor units for Stripe."""
    code = (currency or "gbp").lower()
    if code in ZERO_DECIMAL_CURRENCIES:
        return int(amount_major.quantize(Decimal("1"), rounding=ROUND_HALF_UP))

    return int(
        (amount_major * Decimal("100")).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    )


def from_minor_units(amount_minor: int, currency: str) -> Decimal:
    """Convert Stripe minor units back to major units for UI display."""
    code = (currency or "gbp").lower()
    if code in ZERO_DECIMAL_CURRENCIES:
        return Decimal(amount_minor)

    return (Decimal(amount_minor) / Decimal("100")).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
