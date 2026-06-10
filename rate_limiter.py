"""Rate limiting utilities for the Payroll WhatsApp Automation System.

Implements a thread-safe Token Bucket rate limiter to ensure outbound
WhatsApp API calls respect the platform's rate limits.  Also provides
exponential-backoff helpers for graceful retry logic when the API
returns HTTP 429 (Too Many Requests).
"""

import random
import threading
import time
from typing import Optional


class RateLimiter:
    """Thread-safe rate limiter using the Token Bucket algorithm.

    **How the Token Bucket works**

    A *bucket* starts with a configurable number of *tokens* (the
    ``burst`` parameter).  Each time a caller wants to perform an
    action it must *acquire* a token.  Tokens are replenished at a
    fixed rate (``max_per_second``).

    * If the bucket contains at least one token the caller proceeds
      immediately and the token is consumed.
    * If the bucket is empty the caller sleeps until a token becomes
      available.
    * The bucket never holds more than ``burst`` tokens, preventing
      unbounded bursts after long idle periods.

    This approach provides smooth, predictable throughput while
    allowing short bursts of activity.

    Args:
        max_per_second: Maximum sustained rate (tokens added per
            second).  Defaults to ``1.0``.
        burst: Maximum number of tokens that can accumulate in the
            bucket.  Defaults to ``1``.

    Example::

        limiter = RateLimiter(max_per_second=2.0, burst=5)
        for message in messages:
            limiter.acquire()   # blocks if over rate
            send_message(message)
    """

    def __init__(self, max_per_second: float = 1.0, burst: int = 1) -> None:
        if max_per_second <= 0:
            raise ValueError("max_per_second must be positive")
        if burst < 1:
            raise ValueError("burst must be at least 1")

        self._max_per_second: float = max_per_second
        self._burst: int = burst

        # Current number of available tokens
        self._tokens: float = float(burst)

        # Timestamp of last token refill (monotonic clock)
        self._last_refill: float = time.monotonic()

        # Lock protecting mutable state
        self._lock: threading.Lock = threading.Lock()

    # ------------------------------------------------------------------ #
    #  Public API
    # ------------------------------------------------------------------ #

    def acquire(self) -> None:
        """Block until a token is available, then consume it.

        This method is thread-safe.  Multiple threads may call
        :meth:`acquire` concurrently; each will wait its turn.
        """
        while True:
            with self._lock:
                self._refill()

                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return  # token acquired — proceed

                # Calculate how long until the next token arrives
                deficit: float = 1.0 - self._tokens
                wait_time: float = deficit / self._max_per_second

            # Sleep *outside* the lock so other threads can check too
            time.sleep(wait_time)

    def report_rate_limit(self, retry_after: Optional[float] = None) -> None:
        """Handle an HTTP 429 *Too Many Requests* response.

        When the API signals that we are exceeding its rate limit this
        method drains the bucket and sleeps for an appropriate duration.

        Args:
            retry_after: Value of the ``Retry-After`` header (in
                seconds) returned by the server.  If ``None`` a
                default back-off of ``1 / max_per_second`` is used.
        """
        with self._lock:
            # Drain the bucket so subsequent callers also wait
            self._tokens = 0.0

        sleep_duration: float = (
            retry_after if retry_after is not None
            else 1.0 / self._max_per_second
        )
        time.sleep(max(sleep_duration, 0.0))

    @staticmethod
    def get_backoff_delay(
        attempt: int,
        base_delay: float = 2.0,
        max_delay: float = 60.0,
    ) -> float:
        """Calculate an exponential back-off delay with jitter.

        The formula is::

            delay = min(base_delay × 2^attempt + jitter, max_delay)

        where *jitter* is drawn uniformly from ``[0, 1)`` seconds.

        Args:
            attempt: Zero-based retry attempt number.
            base_delay: Starting delay in seconds before exponential
                growth.
            max_delay: Upper bound on the returned delay.

        Returns:
            The computed delay in seconds (always ≥ 0).
        """
        jitter: float = random.uniform(0.0, 1.0)
        delay: float = base_delay * (2 ** attempt) + jitter
        return min(delay, max_delay)

    # ------------------------------------------------------------------ #
    #  Internal helpers
    # ------------------------------------------------------------------ #

    def _refill(self) -> None:
        """Add tokens based on elapsed time since the last refill.

        Must be called while holding ``self._lock``.
        """
        now: float = time.monotonic()
        elapsed: float = now - self._last_refill
        self._last_refill = now

        self._tokens += elapsed * self._max_per_second
        if self._tokens > self._burst:
            self._tokens = float(self._burst)
