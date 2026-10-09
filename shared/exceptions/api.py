class APIException(Exception):
    """Base exception for all API-level errors."""
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code

class BadRequestException(APIException):
    def __init__(self, message: str = "Bad Request"):
        super().__init__(message, status_code=400)

class UnauthorizedException(APIException):
    def __init__(self, message: str = "Unauthorized"):
        super().__init__(message, status_code=401)

class NotFoundException(APIException):
    def __init__(self, message: str = "Resource Not Found"):
        super().__init__(message, status_code=404)
