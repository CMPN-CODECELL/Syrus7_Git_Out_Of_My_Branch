"""
File Overview: Custom domain exceptions for Analytics context.
"""

class AnalyticsDomainException(Exception):
    """Base exception class for the Analytics domain."""
    pass

class InvalidSentimentScoreException(AnalyticsDomainException):
    """Raised when a sentiment score is invalid or out of range."""
    pass
