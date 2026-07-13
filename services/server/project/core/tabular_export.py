"""Encode a pandas DataFrame to downloadable csv/xlsx bytes.

Shared by the async export worker (``project.workers.export``) so that turning a
result DataFrame into a file is one place, transport-agnostic (no Flask). The
route streams the bytes the worker stored in MinIO; nothing here touches HTTP.

``openpyxl`` (xlsx writer) is already a dependency (used to read uploaded xlsx
datasets); ``to_csv`` uses ``utf-8-sig`` so Excel opens UTF-8 CSVs correctly.
"""

import io

import pandas as pd

from project.exceptions import BadRequestError

CSV = "csv"
XLSX = "xlsx"
FORMATS = (CSV, XLSX)

_CSV_MIME = "text/csv"
_XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def mimetype_for(fmt: str) -> str:
    if fmt == CSV:
        return _CSV_MIME
    if fmt == XLSX:
        return _XLSX_MIME
    raise BadRequestError(f"Unsupported export format: {fmt!r}")


def dataframe_to_bytes(df: pd.DataFrame, fmt: str) -> tuple[bytes, str]:
    """Serialise ``df`` to ``(bytes, mimetype)`` for ``fmt`` in {csv, xlsx}.

    Raises ``BadRequestError`` for an unknown format.
    """
    if fmt == CSV:
        return df.to_csv(index=False).encode("utf-8-sig"), _CSV_MIME
    if fmt == XLSX:
        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine="openpyxl") as writer:
            df.to_excel(writer, index=False, sheet_name="Sheet1")
        return buf.getvalue(), _XLSX_MIME
    raise BadRequestError(f"Unsupported export format: {fmt!r}")
