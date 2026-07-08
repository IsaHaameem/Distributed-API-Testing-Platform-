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


class OrganizationNotFoundError(AppError):
    status_code = 404
    detail = "Organization not found."


class InsufficientPermissionsError(AppError):
    status_code = 403
    detail = "You do not have permission to perform this action."


class UserNotFoundError(AppError):
    status_code = 404
    detail = "No user was found with that email address."


class AlreadyMemberError(AppError):
    status_code = 409
    detail = "This user is already a member of the organization."


class MembershipNotFoundError(AppError):
    status_code = 404
    detail = "This user is not a member of the organization."


class CannotRemoveLastOwnerError(AppError):
    status_code = 409
    detail = "An organization must have at least one owner."


class SlugAlreadyTakenError(AppError):
    status_code = 409
    detail = "This slug is already in use."


class ProjectNotFoundError(AppError):
    status_code = 404
    detail = "Project not found."


class CollectionNotFoundError(AppError):
    status_code = 404
    detail = "Collection not found."


class ApiRequestNotFoundError(AppError):
    status_code = 404
    detail = "API request not found."


class AssertionNotFoundError(AppError):
    status_code = 404
    detail = "Assertion not found."


class EnvironmentVariableNotFoundError(AppError):
    status_code = 404
    detail = "Environment variable not found."


class EnvironmentVariableKeyTakenError(AppError):
    status_code = 409
    detail = "This key is already defined for this project."


class ScheduleNotFoundError(AppError):
    status_code = 404
    detail = "Schedule not found."


class WorkerNotFoundError(AppError):
    status_code = 404
    detail = "Worker not found."