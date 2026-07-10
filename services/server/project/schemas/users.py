"""Request schemas for the users API.

Strict validation (``extra="forbid"`` + length caps) is the replacement for the
former ``validate_request`` regex filter: unknown keys are rejected, and fields
are bounded at or below their DB column widths (``users.email String(64)``,
``password String(128)``, ``name``/``role``/``status`` ``String(32)``). Field
names mirror the frontend payload (``registeredOn``).

The batch endpoints (/add_batch, /updates) keep their own per-row validation —
they return a bespoke ``{"message", "errors": [...]}`` shape the UAM import UI
reads, which a plain schema error wouldn't reproduce.
"""

from pydantic import BaseModel, ConfigDict, Field, field_validator

# bcrypt only consumes the first 72 bytes; the cap here is just an abuse ceiling.
_PASSWORD_MAX = 128
_EMAIL_MAX = 64
_SHORT = 32


def _validate_email(v: str | None) -> str | None:
    if v is None:
        return v
    if "@" not in v or "." not in v.split("@")[-1]:
        raise ValueError("must be a valid email address")
    return v


class AddUser(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=3, max_length=_EMAIL_MAX)
    password: str = Field(min_length=1, max_length=_PASSWORD_MAX)
    role: str = Field(min_length=1, max_length=_SHORT)
    name: str | None = Field(default=None, max_length=_SHORT)
    status: str | None = Field(default=None, max_length=_SHORT)
    registeredOn: str | None = Field(default=None, max_length=_SHORT)

    @field_validator("email")
    @classmethod
    def _email(cls, v):
        return _validate_email(v)


class UpdateUser(BaseModel):
    """All fields optional — a partial update patches only what's provided."""

    model_config = ConfigDict(extra="forbid")

    email: str | None = Field(default=None, min_length=3, max_length=_EMAIL_MAX)
    password: str | None = Field(default=None, max_length=_PASSWORD_MAX)
    role: str | None = Field(default=None, max_length=_SHORT)
    name: str | None = Field(default=None, max_length=_SHORT)
    status: str | None = Field(default=None, max_length=_SHORT)
    registeredOn: str | None = Field(default=None, max_length=_SHORT)

    @field_validator("email")
    @classmethod
    def _email(cls, v):
        return _validate_email(v)
