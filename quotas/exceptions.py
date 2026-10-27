from utils.errors import AppError


class InvalidInput(AppError):
    pass


class Forbidden(AppError):
    code = "forbidden"
    message = "You are not allowed to do this."
    status = 403


class NotFound(AppError):
    code = "not_found"
    message = "Not found."
    status = 404


class InvalidState(AppError):
    code = "invalid_state"
    message = "This action is not allowed in the current state."
    status = 409


class QuotaExceeded(AppError):
    code = "quota_exceeded"
    message = "Not enough quota left for this request."
    status = 409
