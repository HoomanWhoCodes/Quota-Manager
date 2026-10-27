from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler


class AppError(Exception):
    """Base for our own errors. Each one knows its code, message and HTTP status."""

    code = "validation_error"
    message = "Invalid input."
    status = 400

    def __init__(self, message=None, details=None):
        self.message = message or self.message
        self.details = details
        super().__init__(self.message)


class IdempotencyKeyMissing(AppError):
    code = "idempotency_key_missing"
    message = "The Idempotency-Key header is required."


class IdempotencyKeyTooLong(AppError):
    message = "The Idempotency-Key header must be at most 255 characters."


class IdempotencyKeyReuse(AppError):
    code = "idempotency_key_reuse"
    message = "This Idempotency-Key was already used with a different request."
    status = 409


CODES = {
    400: "validation_error",
    401: "not_authenticated",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    415: "unsupported_media_type",
    429: "rate_limited",
}


def error_body(code, message, details=None):
    return {"error": {"code": code, "message": message, "details": details}}

# use custom handler to return own error + drf error 
def exception_handler(exc, context):
    if isinstance(exc, AppError):
        return Response(error_body(exc.code, exc.message, exc.details), status=exc.status)

    
    
    response = drf_exception_handler(exc, context)
    if response is None:
        return None  

    if isinstance(exc, ValidationError):
        message, details = "Invalid input.", response.data
    elif response.status_code == 404:
        message, details = "Not found.", None  
    else:
        message, details = str(response.data.get("detail", "")), None

    response.data = error_body(CODES.get(response.status_code, "error"), message, details)
    return response

