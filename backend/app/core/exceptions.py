"""Application-level exceptions that map directly to HTTP responses."""


class AppError(Exception):
    """Base class for application errors; the global handler converts these to HTTP responses."""

    status_code: int = 500
    detail: str = "An unexpected error occurred."
    headers: dict[str, str] | None = None

    def __init__(self, detail: str | None = None) -> None:
        if detail is not None:
            self.detail = detail
        super().__init__(self.detail)


class EmailAlreadyRegisteredError(AppError):
    status_code = 409
    detail = "An account with this email already exists."


class InvalidCredentialsError(AppError):
    status_code = 401
    detail = "Incorrect email or password."


class InactiveUserError(AppError):
    status_code = 403
    detail = "This account has been deactivated."


class InvalidTokenError(AppError):
    status_code = 401
    detail = "Could not validate credentials."
    headers = {"WWW-Authenticate": "Bearer"}