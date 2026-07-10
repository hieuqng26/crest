"""Request schemas for the users API.

These add structured validation on top of the existing ``validate_request``
input filter (kept as defense-in-depth). Field names mirror the frontend payload
(``registeredOn`` etc.).
"""

from pydantic import BaseModel, ConfigDict, Field


class AddUser(BaseModel):
    model_config = ConfigDict(extra="ignore")

    email: str = Field(min_length=1)
    password: str = Field(min_length=1)
    role: str = Field(min_length=1)
    name: str | None = None
    status: str | None = None
    registeredOn: str | None = None


class UpdateUser(BaseModel):
    """All fields optional — a partial update patches only what's provided."""

    model_config = ConfigDict(extra="ignore")

    email: str | None = None
    password: str | None = None
    role: str | None = None
    name: str | None = None
    status: str | None = None
    registeredOn: str | None = None
