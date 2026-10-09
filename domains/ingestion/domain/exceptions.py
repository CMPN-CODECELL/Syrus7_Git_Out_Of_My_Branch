"""
File Overview: Custom domain exceptions for Ingestion context.
"""

from shared.exceptions.domain import DomainException

class IngestionDomainException(DomainException):
    """Base exception class for the Ingestion domain."""
    pass

class InvalidSymbolException(IngestionDomainException):
    """Raised when a ticker symbol is invalid."""
    pass
