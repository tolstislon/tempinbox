"""Shared response schemas."""

from pydantic import BaseModel


class ErrorResponse(BaseModel):
    """Standard error response body."""

    detail: str
