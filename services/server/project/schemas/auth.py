"""Request schemas for the auth API."""

from pydantic import BaseModel, ConfigDict, Field

_EMAIL_MAX = 64
_PASSWORD_MAX = 128


class AuthLogin(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=1, max_length=_EMAIL_MAX)
    password: str = Field(min_length=1, max_length=_PASSWORD_MAX)


class ChangePassword(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_password: str = Field(min_length=1, max_length=_PASSWORD_MAX)
    new_password: str = Field(min_length=1, max_length=_PASSWORD_MAX)
