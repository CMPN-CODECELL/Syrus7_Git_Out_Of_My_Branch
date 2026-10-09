class InfrastructureException(Exception):
    """Base exception for all infrastructure layer errors (DB, Redis, network)."""
    pass

class DatabaseConnectionException(InfrastructureException):
    """Exception raised when database connection fails."""
    pass

class ExternalServiceException(InfrastructureException):
    """Exception raised when an external API fails."""
    pass
