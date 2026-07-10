import json
import uuid
from datetime import datetime

import numpy as np
import pandas as pd
import pytz
from dateutil import parser, tz
from flask import request
from tzlocal import get_localzone

from project.logger import get_logger

logger = get_logger(__name__)

# Set the local timezone to Singapore
local_tz = tz.gettz("Asia/Singapore")


def valid_date(date, dayfirst=False):
    """Parse date string to datetime object"""
    if date is None:
        return None

    dt = None
    if isinstance(date, str):
        try:
            # Parse the date string
            dt = parser.parse(date, dayfirst=dayfirst)
        except Exception:
            raise ValueError(f"Invalid date format. Date: {date}.")
    elif isinstance(date, datetime):
        dt = date
    else:
        raise ValueError("Date must be a string or datetime object")

    dt = dt.astimezone(local_tz)
    return dt


def convert_to_local_timezone(naive_dt):
    if naive_dt is None:
        return None

    try:
        local_timezone = get_localzone()
        local_dt = naive_dt.replace(tzinfo=pytz.utc).astimezone(local_timezone)
        return local_dt
    except Exception:
        return naive_dt


def toJSON(df):
    logger.debug("Converting DataFrame to JSON")

    if df is None:
        return None

    if isinstance(df, pd.DataFrame):
        # Create a copy to avoid modifying the original DataFrame
        df_copy = df.copy()

        # Replace NaN values with None
        df_copy = df_copy.replace({np.nan: None})

        # Convert datetime columns to ISO format strings
        for col in df_copy.columns:
            if pd.api.types.is_datetime64_any_dtype(df_copy[col]):
                df_copy[col] = (
                    df_copy[col].dt.strftime("%Y-%m-%d %H:%M:%S").replace("NaT", None)
                )

        # Convert to dict and then to JSON
        records = df_copy.to_dict(orient="records")
    elif isinstance(df, list):
        records = df
    else:
        raise ValueError(f"Cannot parse to JSON of type {type(df)}")

    # Custom JSON encoder to handle any remaining non-serializable objects
    def json_serializer(obj):
        if pd.isna(obj):
            return None
        elif hasattr(obj, "isoformat"):  # datetime objects
            return obj.isoformat()
        elif isinstance(obj, (pd.Timestamp, pd.Timedelta)):
            return str(obj)
        elif isinstance(obj, np.integer):
            return int(obj)
        elif isinstance(obj, np.floating):
            return float(obj)
        elif isinstance(obj, np.ndarray):
            return obj.tolist()
        else:
            return str(obj)

    return json.dumps(records, default=json_serializer)


def convert_level_to_json(level_dict):
    """Convert a level dict with DataFrames to JSON strings."""
    if not level_dict:
        return None
    result = {}
    for key, value in level_dict.items():
        if value is None:
            result[key] = None
        elif isinstance(value, pd.DataFrame):
            result[key] = toJSON(value)
        elif isinstance(value, dict):
            # Recursively convert nested dicts
            result[key] = convert_level_to_json(value)
        else:
            result[key] = value
    return result


def validate_boolean(boolean):
    if boolean is not True and boolean is not False:
        raise TypeError("Variable must be Boolean")


def valid_uuid(uuid_id):
    try:
        correct_uuid = str(uuid.UUID(str(uuid_id)))
        return correct_uuid
    except Exception:
        e = NameError("Invalid uuid")
        logger.exception(e)
        raise e
        # return make_response(jsonify({'message': str(e)}), 404)


def paginate_logs(base_query, id_col, default_limit=1000, max_limit=5000):
    """Cursor-paginate a run-log query for the live log panels.

    Poll requests pass ``after_id`` (the id of the last row the client already
    holds) and only the newer rows are returned — instead of re-sending the whole,
    ever-growing log table every 2s. Without a cursor the initial load returns the
    most recent ``limit`` rows (chronologically ordered), so a long run doesn't ship
    its entire history up front. Rows are always returned oldest→newest so the
    client can append.
    """
    after_id = request.args.get("after_id", type=int)
    limit = request.args.get("limit", type=int) or default_limit
    limit = max(1, min(limit, max_limit))
    if after_id is not None:
        return (
            base_query.filter(id_col > after_id)
            .order_by(id_col.asc())
            .limit(limit)
            .all()
        )
    rows = base_query.order_by(id_col.desc()).limit(limit).all()
    rows.reverse()
    return rows


def is_empty_df(df):
    if (
        (df is None)
        or (isinstance(df, pd.DataFrame) and df.empty)
        or (isinstance(df, dict) and len(df) == 0)
    ):
        return True
    return False
