"""Structured logging setup for the application."""

import logging
import sys


def setup_logging(log_level: str = "INFO") -> None:
    """Configure the root logger with a consistent format."""
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level.upper())

    handler = logging.StreamHandler(sys.stdout)
    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S%z",
    )
    handler.setFormatter(formatter)

    root_logger.handlers.clear()
    root_logger.addHandler(handler)

    # LoggingMiddleware already logs each request; avoid duplicate lines.
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)