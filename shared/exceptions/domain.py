class DomainException(Exception):
    """Base exception for all domain business rules violations."""
    pass

class EntityNotFoundException(DomainException):
    """Exception raised when a domain entity is not found."""
    pass

class BusinessRuleValidationException(DomainException):
    """Exception raised when a domain business rule is violated."""
    pass
