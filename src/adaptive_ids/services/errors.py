"""Domain errors raised by services and mapped to HTTP responses by the API."""


class ServiceError(Exception):
    status_code = 400

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class InvalidRequest(ServiceError):
    status_code = 400


class NotAuthenticated(ServiceError):
    status_code = 401


class PermissionDenied(ServiceError):
    status_code = 403


class NotFound(ServiceError):
    status_code = 404


class Conflict(ServiceError):
    status_code = 409
