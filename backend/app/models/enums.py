"""Shared enum types used across ORM models."""

import enum


class OrganizationRole(str, enum.Enum):
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"


class HttpMethod(str, enum.Enum):
    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    PATCH = "PATCH"
    DELETE = "DELETE"
    HEAD = "HEAD"
    OPTIONS = "OPTIONS"


class AssertionType(str, enum.Enum):
    STATUS_CODE_EQUALS = "status_code_equals"
    JSON_PATH_EQUALS = "json_path_equals"
    JSON_PATH_EXISTS = "json_path_exists"
    RESPONSE_TIME_BELOW = "response_time_below"
    HEADER_EQUALS = "header_equals"


class TestRunStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TestRunType(str, enum.Enum):
    MANUAL = "manual"
    SCHEDULED = "scheduled"


class TestTaskStatus(str, enum.Enum):
    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    RETRYING = "retrying"


class WorkerStatus(str, enum.Enum):
    ONLINE = "online"
    OFFLINE = "offline"
    DRAINING = "draining"


class LogLevel(str, enum.Enum):
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"