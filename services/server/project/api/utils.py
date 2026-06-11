import os
from flask import request, make_response, jsonify
from dateutil import tz, parser
import pytz
from tzlocal import get_localzone
from datetime import datetime
from functools import wraps
import uuid
import re
import json
import numpy as np
import pandas as pd

from project.logger import get_logger

logger = get_logger(__name__)

SAFE_REQUEST_PASSWORD = os.getenv("SAFE_REQUEST_PASSWORD_REGEX", r'^.{8,20}$')
SAFE_REQUEST_PASSWORD_REGEX = re.compile(SAFE_REQUEST_PASSWORD)
SAFE_REQUEST_VALUE_REGEX = re.compile(r'^[a-zA-Z0-9_\- \x1e\x1f&<>./();:,\$=*#+@|\\\"\'\[\]\{\}"]*$')
DANGEROUS_REQUEST_VALUES = ["###", "+--", "--", "'='", "--+", "DECLARE @", "CAST(", "EXEC(", "process.kill(", "process.exit(", "while("]
DANGEROUS_REQUEST_VALUE_REGEX = re.compile("|".join(map(re.escape, DANGEROUS_REQUEST_VALUES)))
SAFE_HEADER_REGEX = re.compile(r'^[a-zA-Z0-9_\- ./();:,+=*?"]*$')
SQLI_PATTERNS = [
    # Look for UNION followed closely by SELECT (more precise than matching 'union' alone)
    r"(?i)\bunion\b\s+(all\s+)?\bselect\b",
    # Detect SELECT with FROM or WHERE (SQL SELECT usage, less likely to be false positive)
    r"(?i)\bselect\b\s+[\w\*\s,]+\s+(from|where)\b",
    # Look for common dangerous SQL statements only when used with table manipulation or function calls
    r"(?i)\bdrop\s+(table|database)\b",
    r"(?i)\binsert\s+into\b",
    # Detect usage of sleep function with a number (for time-based SQLi)
    r"(?i)\bsleep\s*\(\s*\d+\s*\)",
    # Detect boolean-based injections like AND 1=1 or OR 2=2
    r"(?i)\b(and|or)\b\s+\d+\s*=\s*\d+",
    # Optionally, detect string-based boolean injections like AND 'a'='a'
    r"(?i)\b(and|or)\b\s+'[^']+'\s*=\s*'[^']+'",
]

# Set the local timezone to Singapore
local_tz = tz.gettz('Asia/Singapore')


def valid_date(date, dayfirst=False):
    '''Parse date string to datetime object'''
    if date is None:
        return None

    dt = None
    if isinstance(date, str):
        try:
            # Parse the date string
            dt = parser.parse(date, dayfirst=dayfirst)
        except Exception as e:
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
    except Exception as e:
        return naive_dt


def toJSON(df):
    logger.debug('Converting DataFrame to JSON')

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
                df_copy[col] = df_copy[col].dt.strftime('%Y-%m-%d %H:%M:%S').replace('NaT', None)

        # Convert to dict and then to JSON
        records = df_copy.to_dict(orient='records')
    elif isinstance(df, list):
        records = df
    else:
        raise ValueError(f'Cannot parse to JSON of type {type(df)}')

    # Custom JSON encoder to handle any remaining non-serializable objects
    def json_serializer(obj):
        if pd.isna(obj):
            return None
        elif hasattr(obj, 'isoformat'):  # datetime objects
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
    if boolean != True and boolean != False:
        raise TypeError("Variable must be Boolean")


def valid_uuid(uuid_id):
    try:
        correct_uuid = str(uuid.UUID(str(uuid_id)))
        return correct_uuid
    except Exception:
        e = NameError(f"Invalid uuid")
        logger.exception(e)
        raise e
        # return make_response(jsonify({'message': str(e)}), 404)


def is_empty_df(df):
    if (df is None) or (isinstance(df, pd.DataFrame) and df.empty) or (isinstance(df, dict) and len(df) == 0):
        return True
    return False


def is_suspect_sqli(value):
    return any(re.search(p, value) for p in SQLI_PATTERNS)


def validate_int_id(int_id):
    if isinstance(int_id, str):
        int_id = int(int_id)
    max_uint_64 = 2**32 - 1
    if 0 <= int_id and int_id <= max_uint_64:
        return True
    else:
        return False


def validate_string_length(str_in):
    if isinstance(str_in, str):
        if len(str_in) <= 1024:
            return True
        else:
            # if longer than 1024, return OK if it is JSON, otherwise, return NO
            try:
                json.loads(str_in)  # Attempt to parse JSON
                return True
            except json.JSONDecodeError:
                return False
    else:
        return False


def validate_request_query_string():
    query_string = request.query_string.decode('utf-8')
    if query_string and isinstance(query_string, str):
        if not bool(SAFE_REQUEST_VALUE_REGEX.match(query_string)):
            return False
    return True


def validate_request(allowed_keys=['']):
    def wrapper(fn):
        @wraps(fn)
        def decorator(*args, **kwargs):
            # ensure no garbage info is contained in request
            if request.content_type == 'application/json':
                data = request.get_json()
                for key, value in data.items():
                    if not key in allowed_keys:
                        e = ValueError(f"Invalid key detected in request")
                        logger.exception(e)
                        return make_response(jsonify({'message': str(e)}), 400)
                    if key in ["ldap_connection_id", "page", "page_size"]:
                        if not validate_int_id(value):
                            e = ValueError(f"Invalid value detected in request")
                            logger.exception(e)
                            return make_response(jsonify({'message': str(e)}), 400)
                    elif isinstance(value, str):
                        if key.upper() in ["PASSWORD"]:
                            if not bool(SAFE_REQUEST_PASSWORD_REGEX.match(value)):
                                e = ValueError(f"Value in request has invalid character or format")
                                logger.exception(e)
                                return make_response(jsonify({'message': str(e)}), 400)
                        else:
                            if not bool(SAFE_REQUEST_VALUE_REGEX.match(value)):
                                e = ValueError(f"Invalid value detected in request")
                                logger.exception(e)
                                return make_response(jsonify({'message': str(e)}), 400)
                            elif not validate_string_length(value):
                                e = ValueError(f"Invalid value detected in request")
                                logger.exception(e)
                                return make_response(jsonify({'message': str(e)}), 400)
                            elif bool(DANGEROUS_REQUEST_VALUE_REGEX.search(value)):
                                e = ValueError(f"Invalid value detected in request")
                                logger.exception(e)
                                return make_response(jsonify({'message': str(e)}), 400)
                            elif is_suspect_sqli(value):
                                e = ValueError(f"Possible SQL injection detected in request")
                                logger.exception(e)
                                return make_response(jsonify({'message': str(e)}), 400)

            # check header
            for header, value in request.headers.items():
                if not bool(SAFE_HEADER_REGEX.match(value)):
                    e = ValueError(f"Invalid value detected in header")
                    logger.exception(e)
                    return make_response(jsonify({'message': str(e)}), 400)
                # limit asterisk to certain header names
                elif '*' in value and header not in ["Access-Control-Allow-Origin", "Accept", "Cache-Control"]:
                    e = ValueError(f"Invalid value detected in header")
                    logger.exception(e)
                    return make_response(jsonify({'message': str(e)}), 400)
                # limit question mark to certain header names
                # elif '?' in value and header not in ["Sec-Ch-Ua-Mobile", "If-None-Match", "Referer"]:  # Refer could contain URL with query so may contain "?"
                #     e = ValueError(f"Invalid value detected in header")
                #     logger.exception(e)
                #     return make_response(jsonify({'message': str(e)}), 400)

            return fn(*args, **kwargs)
        return decorator
    return wrapper
