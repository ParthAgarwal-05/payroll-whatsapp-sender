"""WhatsApp Cloud API integration module.

Handles sending WhatsApp messages via the Meta WhatsApp Cloud API.
Supports dynamic template-based messaging with configurable retry logic.

Security:
    The access token is NEVER logged or written to any output.
"""

import json
import logging
import os
import time
from pathlib import Path

import requests

from logger_config import setup_logger, get_app_dir, mask_pii


class WhatsAppSender:
    """Client for sending WhatsApp messages via Meta Cloud API.

    This class wraps the WhatsApp Business Cloud API, providing methods to
    build template payloads, send messages with retry logic, and validate
    API credentials.

    Attributes:
        api_url: The fully-qualified endpoint URL for sending messages.
        template_name: Default template name (overridable per-call).
        template_language: BCP-47 language code for the template.
    """

    # Non-retriable HTTP status codes (client errors that won't change on retry)
    NON_RETRIABLE_CODES: set[int] = {400, 401, 403, 404}
    # Retriable HTTP status codes
    RETRIABLE_CODES: set[int] = {429, 500, 502, 503, 504}

    def __init__(self) -> None:
        """Initialise the WhatsApp sender from environment variables.

        Environment variables:
            ACCESS_TOKEN (required): Meta API bearer token.
            PHONE_NUMBER_ID (required): WhatsApp Business phone-number ID.
            TEMPLATE_NAME: Default template name (can be overridden per call).
            TEMPLATE_LANGUAGE: BCP-47 language code (default ``'en'``).
            API_VERSION: Graph API version (default ``'v25.0'``).

        Raises:
            ValueError: If ACCESS_TOKEN or PHONE_NUMBER_ID is not set.
        """
        self.logger: logging.Logger = setup_logger(__name__)

        # --- Required credentials ------------------------------------------------
        self._access_token: str = os.getenv("ACCESS_TOKEN", "")
        self._phone_number_id: str = os.getenv("PHONE_NUMBER_ID", "")

        if not self._access_token:
            raise ValueError(
                "ACCESS_TOKEN environment variable is required but not set."
            )
        if not self._phone_number_id:
            raise ValueError(
                "PHONE_NUMBER_ID environment variable is required but not set."
            )

        # --- Optional configuration -----------------------------------------------
        self.template_name: str = os.getenv("TEMPLATE_NAME", "")
        self.template_language: str = os.getenv("TEMPLATE_LANGUAGE", "en")
        api_version: str = os.getenv("API_VERSION", "v25.0")

        # --- Derived attributes ---------------------------------------------------
        self.api_url: str = (
            f"https://graph.facebook.com/{api_version}/"
            f"{self._phone_number_id}/messages"
        )
        self._headers: dict[str, str] = {
            "Authorization": f"Bearer {self._access_token}",
            "Content-Type": "application/json",
        }

        # Rate limiting
        rate_limit = float(os.getenv('RATE_LIMIT_MPS', '1.0'))
        from rate_limiter import RateLimiter
        self._rate_limiter = RateLimiter(max_per_second=rate_limit)

        self.logger.info(
            "WhatsAppSender initialised – API URL: %s, "
            "Template: %s, Language: %s",
            self.api_url,
            self.template_name or "(none)",
            self.template_language,
        )

    # ------------------------------------------------------------------
    # Template mapping
    # ------------------------------------------------------------------

    def load_template_mapping(
        self, template_name: str, mapping_path: str | None = None
    ) -> dict:
        """Load the parameter mapping for a specific template from the JSON file.

        The mapping file contains a top-level dictionary keyed by template
        name.  Each value is a mapping of parameter-name → column-name.

        Args:
            template_name: Name of the template whose mapping should be
                loaded (must exist as a key in the JSON file).
            mapping_path: Absolute or relative path to the JSON mapping file.
                Defaults to ``templates/template_mapping.json`` relative to
                the application directory.

        Returns:
            A ``dict`` mapping parameter names to spreadsheet column names.

        Raises:
            ValueError: If the mapping file cannot be read, is malformed,
                or does not contain the requested template.
        """
        if mapping_path is None:
            resolved_path = get_app_dir() / 'templates' / 'template_mapping.json'
        else:
            resolved_path = Path(mapping_path)

        try:
            with open(resolved_path, "r", encoding="utf-8") as fh:
                all_mappings: dict = json.load(fh)
        except FileNotFoundError:
            self.logger.error(
                "Template mapping file not found: %s", resolved_path
            )
            raise ValueError(
                f"Template mapping file not found: {resolved_path}"
            )
        except json.JSONDecodeError as exc:
            self.logger.error(
                "Failed to parse template mapping file %s: %s",
                resolved_path,
                exc,
            )
            raise ValueError(
                f"Invalid JSON in template mapping file: {exc}"
            ) from exc

        if not isinstance(all_mappings, dict):
            raise ValueError("Template mapping file must contain a JSON object")

        if template_name not in all_mappings:
            available = ", ".join(sorted(all_mappings.keys())) or "(none)"
            raise ValueError(
                f"Template '{template_name}' not found in mapping file.\n"
                f"Available templates: {available}"
            )

        mapping = all_mappings[template_name]
        if not isinstance(mapping, dict) or not mapping:
            raise ValueError(
                f"Mapping for template '{template_name}' is empty or "
                f"not a valid object."
            )

        self.logger.info(
            "Loaded mapping for template '%s' from %s (%d parameter(s))",
            template_name,
            resolved_path,
            len(mapping),
        )
        return mapping

    # ------------------------------------------------------------------
    # Payload construction
    # ------------------------------------------------------------------

    def build_template_payload(
        self,
        phone: str,
        template_name: str,
        row_data: dict,
        mapping: dict,
    ) -> dict:
        """Build a WhatsApp Cloud API template-message payload.

        Parameters are constructed **dynamically** by iterating over the
        ``mapping`` dictionary.  Each mapping key represents a logical
        parameter name and its value is the column name used to look up
        the actual data in ``row_data``.

        Args:
            phone: Recipient phone number in E.164 format (e.g. ``'919876543210'``).
            template_name: Name of the approved WhatsApp template.
            row_data: Dictionary of column-name → value for the current row.
            mapping: Ordered mapping of parameter-name → column-name.

        Returns:
            A ``dict`` ready to be serialised to JSON and sent to the API.
        """
        parameters: list[dict[str, str]] = []
        missing_vars: list[str] = []

        for param_key, column_name in mapping.items():
            if column_name not in row_data:
                missing_vars.append(column_name)

            value = row_data.get(column_name, "")
            parameters.append({
                "type": "text",
                "parameter_name": param_key,
                "text": str(value)
            })

        if missing_vars:
            self.logger.warning(
                "Missing data in row for columns %s (phone: %s)",
                missing_vars,
                phone,
            )

        payload: dict = {
            "messaging_product": "whatsapp",
            "to": phone,
            "type": "template",
            "template": {
                "name": template_name,
                "language": {"code": self.template_language},
                "components": [
                    {
                        "type": "body",
                        "parameters": parameters,
                    }
                ],
            },
        }

        self.logger.debug(
            "Built template payload for phone=%s, template=%s, "
            "parameter_count=%d. Parameters generated: %s",
            phone,
            template_name,
            len(parameters),
            [p["parameter_name"] for p in parameters]
        )
        return payload

    # ------------------------------------------------------------------
    # Message sending
    # ------------------------------------------------------------------

    def send_message(
        self,
        phone: str,
        template_name: str,
        row_data: dict,
        mapping: dict,
    ) -> dict:
        """Send a single WhatsApp template message.

        Args:
            phone: Recipient phone number in E.164 format.
            template_name: Name of the approved WhatsApp template.
            row_data: Dictionary of column-name → value for the current row.
            mapping: Ordered mapping of parameter-name → column-name.

        Returns:
            A ``dict`` with keys:
                - ``success`` (``bool``): Whether the message was accepted.
                - ``message_id`` (``str``): The WhatsApp message ID on success.
                - ``error`` (``str``): Error description on failure.
        """
        payload = self.build_template_payload(
            phone, template_name, row_data, mapping
        )

        # Log the request with PII masking — no full payload at INFO level
        self.logger.info(
            'Sending WhatsApp message – URL: %s, Phone: %s, Template: %s, ParamCount: %d',
            self.api_url, phone, template_name, len(mapping),
        )
        self.logger.debug('Full payload: %s', mask_pii(json.dumps(payload)))

        try:
            response = requests.post(
                self.api_url,
                headers=self._headers,
                json=payload,
                timeout=30,
            )

            self.logger.info(
                'Response – Status: %d for phone %s',
                response.status_code, phone,
            )
            self.logger.debug('Response body: %s', response.text)

            if response.status_code in (200, 201):
                response_data = response.json()
                message_id = (
                    response_data.get("messages", [{}])[0].get("id", "")
                )
                return {
                    "success": True,
                    "message_id": message_id,
                    "error": "",
                    "retry_after": None,
                }

            # Non-success HTTP status
            try:
                error_data = response.json()
                error_message = (
                    error_data.get("error", {}).get("message", response.text)
                )
            except (ValueError, KeyError):
                error_message = response.text

            # Extract Retry-After header for 429 responses
            retry_after = None
            if response.status_code == 429:
                retry_after_str = response.headers.get('Retry-After')
                if retry_after_str:
                    try:
                        retry_after = float(retry_after_str)
                    except ValueError:
                        pass

            return {
                "success": False,
                "message_id": "",
                "error": f"HTTP {response.status_code}: {error_message}",
                "retry_after": retry_after,
            }

        except requests.exceptions.RequestException as exc:
            self.logger.error(
                "Request failed for phone=%s: %s", phone, exc
            )
            return {
                "success": False,
                "message_id": "",
                "error": str(exc),
                "retry_after": None,
            }

    # ------------------------------------------------------------------
    # Retry wrapper
    # ------------------------------------------------------------------

    def send_with_retry(
        self,
        phone: str,
        template_name: str,
        row_data: dict,
        mapping: dict,
        max_retries: int = 3,
        retry_delay: float = 2.0,
    ) -> dict:
        """Send a WhatsApp message with automatic retry on failure.

        Retries up to ``max_retries`` times with exponential back-off.
        Non-retriable HTTP errors (400, 401, 403, 404) cause an
        immediate return without further retries.  HTTP 429 responses
        are reported to the rate limiter for adaptive throttling.

        Args:
            phone: Recipient phone number in E.164 format.
            template_name: Name of the approved WhatsApp template.
            row_data: Dictionary of column-name → value for the current row.
            mapping: Ordered mapping of parameter-name → column-name.
            max_retries: Maximum number of send attempts (default ``3``).
            retry_delay: Base seconds for exponential back-off (default ``2.0``).

        Returns:
            The result ``dict`` from the last :meth:`send_message` attempt.
        """
        from rate_limiter import RateLimiter

        result: dict = {}

        for attempt in range(1, max_retries + 1):
            self.logger.info(
                'Attempt %d/%d – sending message to %s',
                attempt, max_retries, phone,
            )

            # Rate limiting — block until allowed
            self._rate_limiter.acquire()

            result = self.send_message(phone, template_name, row_data, mapping)

            if result.get('success'):
                self.logger.info(
                    'Message sent successfully on attempt %d to %s '
                    '(message_id=%s)',
                    attempt, phone, result.get('message_id', ''),
                )
                return result

            error = result.get('error', '')

            # Check for HTTP 429 (rate limited)
            if 'HTTP 429' in error:
                # Try to extract Retry-After
                retry_after = result.get('retry_after')
                self._rate_limiter.report_rate_limit(retry_after)
                self.logger.warning(
                    'Rate limited on attempt %d/%d for %s, backing off',
                    attempt, max_retries, phone,
                )
                if attempt < max_retries:
                    continue

            # Check for non-retriable errors
            is_non_retriable = any(
                f'HTTP {code}' in error
                for code in self.NON_RETRIABLE_CODES
            )
            if is_non_retriable:
                self.logger.error(
                    'Non-retriable error for %s: %s — skipping retries',
                    phone, error,
                )
                return result

            self.logger.warning(
                'Attempt %d/%d failed for %s: %s',
                attempt, max_retries, phone, error,
            )

            if attempt < max_retries:
                delay = RateLimiter.get_backoff_delay(
                    attempt, base_delay=retry_delay,
                )
                self.logger.info('Retrying in %.1f seconds…', delay)
                time.sleep(delay)

        self.logger.error(
            'All %d attempts exhausted for phone=%s. Last error: %s',
            max_retries, phone, result.get('error', 'unknown error'),
        )
        return result

    # ------------------------------------------------------------------
    # Template mapping validation
    # ------------------------------------------------------------------

    def validate_template_mapping_data(
        self, mapping: dict, sample_row: dict | None = None
    ) -> tuple[bool, str]:
        """Validate the template mapping structure and optionally against sample data.

        Args:
            mapping: The template-to-column mapping dict.
            sample_row: Optional sample row from Excel data to check column existence.

        Returns:
            (is_valid, error_message) tuple.
        """
        from validation import validate_template_mapping, validate_mapping_against_data

        # Validate mapping structure
        is_valid, msg = validate_template_mapping(mapping)
        if not is_valid:
            return False, msg

        # Validate against sample data if provided
        if sample_row is not None:
            all_present, missing = validate_mapping_against_data(mapping, sample_row)
            if not all_present:
                return False, f"Missing Excel columns: {', '.join(missing)}"

        return True, 'Valid'

    # ------------------------------------------------------------------
    # Credential validation
    # ------------------------------------------------------------------

    def validate_credentials(self) -> tuple[bool, str]:
        """Verify that the configured API credentials are valid.

        Makes a lightweight GET request to the phone-number endpoint on
        the Graph API to confirm the token and phone-number ID are
        accepted.

        Returns:
            A tuple ``(is_valid, message)`` where *is_valid* is ``True``
            when the credentials check passes and *message* provides
            additional detail.
        """
        api_version = os.getenv("API_VERSION", "v25.0")
        validation_url = (
            f"https://graph.facebook.com/{api_version}/"
            f"{self._phone_number_id}"
        )

        self.logger.info(
            "Validating credentials against %s", validation_url
        )

        try:
            response = requests.get(
                validation_url,
                headers=self._headers,
                timeout=30,
            )

            self.logger.info(
                "Validation response – Status: %d, Body: %s",
                response.status_code,
                response.text,
            )

            if response.status_code == 200:
                return True, "Valid"

            try:
                error_data = response.json()
                error_message = (
                    error_data.get("error", {}).get("message", response.text)
                )
            except (ValueError, KeyError):
                error_message = response.text

            return False, f"HTTP {response.status_code}: {error_message}"

        except requests.exceptions.RequestException as exc:
            self.logger.error("Credential validation failed: %s", exc)
            return False, str(exc)
