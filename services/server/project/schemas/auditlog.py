"""Request schemas for the auditlog API.

Field sets mirror the former ``validate_request`` allowlists; ``extra="forbid"``
reproduces the unknown-key rejection. String bounds sit at/under the DB column
widths, and ``page_size`` is capped to bound result size (a cheap DoS guard).
"""

from pydantic import BaseModel, ConfigDict, Field

_PAGE_SIZE_MAX = 1000


class GetAuditLogs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    page: int | None = Field(default=None, ge=0)
    page_size: int | None = Field(default=None, ge=1, le=_PAGE_SIZE_MAX)
    # \x1e-joined multi-selects / a column list — generous bound, not per-token.
    columns: str | None = Field(default=None, max_length=2048)
    date_from: str | None = Field(default=None, max_length=64)
    date_to: str | None = Field(default=None, max_length=64)
    user_id: str | None = Field(default=None, max_length=128)
    module: str | None = Field(default=None, max_length=1024)
    submodule: str | None = Field(default=None, max_length=1024)
    action: str | None = Field(default=None, max_length=1024)
    get_size: bool = False
    sort_column: str | None = Field(default=None, max_length=64)
    sort_order: str | None = Field(default=None, max_length=8)


class AddAuditLog(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=1, max_length=64)
    action: str = Field(min_length=1, max_length=16)
    module: str = Field(min_length=1, max_length=512)
    submodule: str | None = Field(default=None, max_length=512)
    previous_data: str | None = None  # Text column
    new_data: str | None = None  # Text column
    description: str | None = None  # Text column
    status: str | None = Field(default=None, max_length=16)
    error_codes: str | None = Field(default=None, max_length=16)
    database_involved: str | None = Field(default=None, max_length=255)
