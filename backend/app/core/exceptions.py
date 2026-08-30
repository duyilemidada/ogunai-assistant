# backend/app/core/exceptions.py
class OgunAIException(Exception):
    """Base exception for all custom app errors."""
    status_code = 400
    error_code = "OGUNAI_ERROR"
    
    def __init__(self, message: str, details: dict = None):
        self.message = message
        self.details = details or {}
        super().__init__(self.message)

class AuthenticationError(OgunAIException):
    status_code = 401
    error_code = "AUTHENTICATION_ERROR"

class AuthorizationError(OgunAIException):
    status_code = 403
    error_code = "AUTHORIZATION_ERROR"

class NotFoundError(OgunAIException):
    status_code = 404
    error_code = "NOT_FOUND"

class ConflictError(OgunAIException):
    status_code = 409
    error_code = "CONFLICT"