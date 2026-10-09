class NotificationDomainError(Exception):
    """Base exception for notification domain errors."""
    pass


class AlertRuleNotFoundError(NotificationDomainError):
    """Raised when an alert rule is requested but not found."""
    pass


class InvalidAlertConditionError(NotificationDomainError):
    """Raised when an alert condition parameters are invalid."""
    pass


class NotificationDeliveryError(NotificationDomainError):
    """Raised when notification delivery fails at channel level."""
    pass
