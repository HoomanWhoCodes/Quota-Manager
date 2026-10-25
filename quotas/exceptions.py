class DomainError(Exception):
    code = "error"
    message = "Something went wrong."

    def __init__(self, message=None, details=None):
        self.message = message or self.message
        self.details = details
        super().__init__(self.message)


class InvalidInput(DomainError):
    code = "validation_error"
    message = "Invalid input."


class NotFound(DomainError):
    code = "not_found"
    message = "Not found."


class Forbidden(DomainError):
    code = "forbidden"
    message = "You are not allowed to do this."


class InvalidState(DomainError):
    code = "invalid_state"
    message = "This action is not allowed in the current state."


class QuotaExceeded(DomainError):
    code = "quota_exceeded"
    message = "Not enough quota left for this request."
