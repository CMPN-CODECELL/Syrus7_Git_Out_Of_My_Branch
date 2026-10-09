"""
021 error taxonomy. Every failure from the broker becomes exactly one of these, so callers
decide behaviour by type, never by parsing strings.

    400 BrokerBadRequestError     bad body / unknown enum / invalid order id     no retry
    401 BrokerAuthError           bad credentials, expired or revoked token      re-login (single flight)
    403 BrokerForbiddenError      account inactive / not a client account        no retry
    404 BrokerNotFoundError       order id not found                             no retry
    421 BrokerWrongClusterError   account belongs to another cluster             no retry
    422 BrokerSafeModeError       order blocked by safe mode                     no retry
    429 BrokerRateLimitedError    rate limit                                     back off (reads only)
    500 BrokerRejectedError       risk rejection on an order action              no retry, show reason
    500/503 BrokerUnavailableError server error / unavailable / non-JSON         retry (reads only)
    --  BrokerTimeoutError        read request timed out                         retry (reads only)
    --  BrokerOutcomeUnknownError order action sent, response lost               NEVER resend; reconcile
"""
from typing import Optional


class BrokerError(Exception):
    retryable: bool = False

    def __init__(self, message: str, *, status: Optional[int] = None, path: str = ""):
        super().__init__(message)
        self.message = message
        self.status = status
        self.path = path

    def user_message(self) -> str:
        return self.message


class BrokerNotConfiguredError(BrokerError):
    """No 021 credentials configured on the server."""


class BrokerBadRequestError(BrokerError):
    pass


class BrokerAuthError(BrokerError):
    pass


class BrokerForbiddenError(BrokerError):
    def user_message(self) -> str:
        return f"021 refused access for this account ({self.message}). Check that the account is active."


class BrokerNotFoundError(BrokerError):
    pass


class BrokerWrongClusterError(BrokerError):
    def user_message(self) -> str:
        return "This 021 account belongs to another cluster. Contact the organisers."


class BrokerSafeModeError(BrokerError):
    def user_message(self) -> str:
        return f"021 safe mode blocked this action: {self.message}"


class BrokerRateLimitedError(BrokerError):
    retryable = True

    def __init__(self, message: str, *, retry_after: Optional[float] = None, **kwargs):
        super().__init__(message, **kwargs)
        self.retry_after = retry_after


class BrokerRejectedError(BrokerError):
    """021 accepted the request but its risk checks rejected it (HTTP 500, success:false)."""

    def user_message(self) -> str:
        return f"021 rejected the order: {self.message}"


class BrokerUnavailableError(BrokerError):
    retryable = True


class BrokerTimeoutError(BrokerError):
    retryable = True


class BrokerOutcomeUnknownError(BrokerError):
    """An order action may or may not have reached 021. Must be reconciled via GET /orders;
    resending could create a duplicate order."""

    def user_message(self) -> str:
        return (
            "The order request was sent but no response came back, so its outcome is unknown. "
            "Kraken will check the order book before anything else is sent."
        )


_STATUS_MAP = {
    400: BrokerBadRequestError,
    401: BrokerAuthError,
    403: BrokerForbiddenError,
    404: BrokerNotFoundError,
    421: BrokerWrongClusterError,
    422: BrokerSafeModeError,
    429: BrokerRateLimitedError,
    503: BrokerUnavailableError,
}


def error_for_status(status: int, message: str, *, path: str, is_order_action: bool) -> BrokerError:
    if status == 500:
        # A 500 with an error text on an order action is a risk rejection, not an outage.
        if is_order_action and message:
            return BrokerRejectedError(message, status=status, path=path)
        return BrokerUnavailableError(message or "021 server error", status=status, path=path)
    cls = _STATUS_MAP.get(status)
    if cls is None:
        cls = BrokerUnavailableError if status >= 500 else BrokerBadRequestError
    return cls(message or f"HTTP {status}", status=status, path=path)
