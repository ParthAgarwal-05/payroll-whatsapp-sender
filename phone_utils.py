"""Phone number normalisation utilities for the Payroll WhatsApp Automation System.

Uses Google's ``phonenumbers`` library to parse, validate, and format
phone numbers into a canonical form suitable for the WhatsApp Cloud API
(E.164 without the leading ``+``).
"""

import re

import phonenumbers
from phonenumbers import NumberParseException, PhoneNumberFormat

# Default region for parsing phone numbers that lack a country code.
# Can be overridden at call sites or by setting the DEFAULT_REGION
# environment variable.
DEFAULT_REGION: str = "IN"

# Characters to strip before parsing
_STRIP_PATTERN: re.Pattern[str] = re.compile(r"[\s\-\(\)]+")

# Keep only digits (used as fallback on parse failure)
_DIGITS_ONLY: re.Pattern[str] = re.compile(r"\D")


def normalize_phone(
    phone: str,
    default_region: str = DEFAULT_REGION,
) -> tuple[str, bool, str]:
    """Parse, validate, and normalise a phone number to E.164.

    Processing steps:

    1. Strip whitespace, hyphens, and parentheses.
    2. Parse with ``phonenumbers`` using *default_region* when no
       country code is present.
    3. Validate with ``phonenumbers.is_valid_number()``.
    4. Format to E.164 and strip the leading ``+``.

    Args:
        phone: Raw phone number string (e.g. ``"+91 98765 43210"``,
            ``"09876543210"``, ``"9876543210"``).
        default_region: ISO 3166-1 alpha-2 region code used when the
            number does not include a country calling code.  Defaults
            to :data:`DEFAULT_REGION` (``'IN'``).

    Returns:
        A three-element tuple:

        * **normalized** – The formatted number *without* a leading
          ``+`` (e.g. ``"919876543210"``).  On failure this is the
          digit-only version of the input.
        * **is_valid** – ``True`` if the number is a valid subscriber
          number for its detected region.
        * **error** – An empty string on success, or a human-readable
          error description on failure.

    Examples::

        >>> normalize_phone("+91 98765 43210")
        ('919876543210', True, '')

        >>> normalize_phone("0000", default_region='US')
        ('0000', False, 'Phone number appears invalid for region US')
    """
    if not phone or not phone.strip():
        return ("", False, "Phone number is empty")

    # Step 1 — clean common formatting characters
    cleaned: str = _STRIP_PATTERN.sub("", phone.strip())

    # Step 2 — parse
    try:
        parsed = phonenumbers.parse(cleaned, default_region)
    except NumberParseException as exc:
        digits_only = _DIGITS_ONLY.sub("", cleaned)
        return (digits_only, False, f"Failed to parse phone number: {exc}")

    # Step 3 — format to E.164 (includes '+')
    formatted: str = phonenumbers.format_number(
        parsed, PhoneNumberFormat.E164
    )
    # Remove the leading '+'
    normalized: str = formatted.lstrip("+")

    # Step 4 — validate
    if not phonenumbers.is_valid_number(parsed):
        region_code = (
            phonenumbers.region_code_for_number(parsed) or default_region
        )
        return (
            normalized,
            False,
            f"Phone number appears invalid for region {region_code}",
        )

    return (normalized, True, "")


def get_supported_regions() -> list[str]:
    """Return a sorted list of supported ISO 3166-1 alpha-2 region codes.

    These are the region codes recognised by the ``phonenumbers``
    library and can be passed as *default_region* to
    :func:`normalize_phone`.

    Returns:
        Sorted list of region code strings (e.g.
        ``['AD', 'AE', ..., 'ZW']``).
    """
    return sorted(phonenumbers.supported_regions())
