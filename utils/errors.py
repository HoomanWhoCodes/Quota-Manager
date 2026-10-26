from django.http import Http404
from rest_framework import exceptions, status
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

from quotas.exceptions import DomainError

DOMAIN_STATUS = {
    "validation_error": status.HTTP_400_BAD_REQUEST,
    "forbidden": status.HTTP_403_FORBIDDEN,
    "not_found": status.HTTP_404_NOT_FOUND,
    "invalid_state": status.HTTP_409_CONFLICT,
    "quota_exceeded": status.HTTP_409_CONFLICT,
}

# DRF's own errors, mapped to our codes. Order matters: subclasses first.
DRF_CODES = [
    (exceptions.ValidationError, "validation_error"),
    (exceptions.ParseError, "validation_error"),
    (exceptions.NotAuthenticated, "not_authenticated"),
    (exceptions.AuthenticationFailed, "not_authenticated"),
    (exceptions.PermissionDenied, "forbidden"),
    (exceptions.NotFound, "not_found"),
    (Http404, "not_found"),
    (exceptions.MethodNotAllowed, "method_not_allowed"),
    (exceptions.UnsupportedMediaType, "unsupported_media_type"),
    (exceptions.Throttled, "rate_limited"),
]


def error_body(code, message, details=None):
    return {"error": {"code": code, "message": message, "details": details}}


def exception_handler(exc, context):
    if isinstance(exc, DomainError):
        return Response(error_body(exc.code, exc.message, exc.details), status=DOMAIN_STATUS[exc.code])

    response = drf_exception_handler(exc, context)
    if response is None:
        return None

    # Django's Http404 has no default_code, so don't read it unless we must.
    code = next((c for cls, c in DRF_CODES if isinstance(exc, cls)), None) or exc.default_code
    if isinstance(exc, exceptions.ValidationError):
        message, details = "Invalid input.", response.data
    elif code == "not_found":
        message, details = "Not found.", None
    elif code == "not_authenticated" and not isinstance(exc.detail, str):
        message, details = "Invalid or expired token.", None
    else:
        message, details = str(getattr(exc, "detail", exc)), None

    response.data = error_body(code, message, details)
    return response
