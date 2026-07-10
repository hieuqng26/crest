from datetime import timedelta

import pandas as pd
from flask import Blueprint, jsonify, request
from pydantic import ValidationError

from project.api.auditlog.models import AuditLog, log_audit
from project.api.auth.decorators import require_perm
from project.api.helpers import validation_message
from project.api.utils import valid_date
from project.logger import get_logger
from project.schemas.auditlog import AddAuditLog, GetAuditLogs

auditlog = Blueprint("auditlog", __name__)
logger = get_logger(__name__)


@auditlog.post("/all", endpoint="get_all_logs")
@require_perm("auditlog:read")
def get_all_logs():
    """Query all logs"""
    try:
        f = GetAuditLogs.model_validate(request.get_json(silent=True) or {})
    except ValidationError as e:
        return jsonify({"message": validation_message(e)}), 400

    page = f.page
    page_size = f.page_size
    columns = f.columns
    date_from = f.date_from
    date_to = f.date_to
    user_id = f.user_id
    module = f.module
    submodule = f.submodule
    action = f.action
    get_size = f.get_size
    sort_column = f.sort_column
    sort_order = f.sort_order

    try:
        columns = (
            None
            if columns in ["undefined", "null", "", None]
            else columns.split("\x1e")
        )
        module = (
            None if module in ["undefined", "null", "", None] else module.split("\x1e")
        )
        submodule = (
            None
            if submodule in ["undefined", "null", "", None]
            else submodule.split("\x1e")
        )
        action = (
            None if action in ["undefined", "null", "", None] else action.split("\x1e")
        )

        column_map = AuditLog.column_map()

        query = AuditLog.query

        # Apply filters
        if date_from:
            date_from = valid_date(date_from).date()
            query = query.filter(AuditLog.timestamp >= date_from)
        if date_to:
            date_to = valid_date(date_to).date() + timedelta(days=1)
            query = query.filter(AuditLog.timestamp < date_to)
        if user_id:
            query = query.filter(AuditLog.user_email == user_id)
        if module:
            query = query.filter(AuditLog.module.in_(module))
        if submodule:
            query = query.filter(AuditLog.submodule.in_(submodule))
        if action:
            query = query.filter(AuditLog.action.in_(action))

        # order — use the mapped Column object and a whitelisted direction so
        # neither sort_column nor sort_order is ever interpolated into raw SQL.
        if sort_column in column_map:
            col = column_map[sort_column]
            descending = str(sort_order).lower() == "desc"
            query = query.order_by(col.desc() if descending else col.asc())

        if sort_column != "timestamp":
            query = query.order_by(
                AuditLog.timestamp.desc()
            )  # sort by timestamp by default

        # Get total count if requested
        if get_size:
            total_count = query.count()
            return jsonify(total_count), 200

        # Apply pagination
        if page is not None and page_size is not None:
            query = query.offset(page * page_size).limit(page_size)

        # Execute query and convert to DataFrame
        log_list = [log.to_dict() for log in query.all()]
        log_df = pd.DataFrame(log_list)

        if columns is not None:
            log_df = log_df[columns].drop_duplicates()

        # Convert Timestamp to string
        for dcol in [
            "timestamp",
            "event_timestamp",
            "log_creation_timestamp",
            "login_time",
            "logout_time",
        ]:
            if dcol in log_df.columns:
                log_df[dcol] = (
                    log_df[dcol].astype("str").replace({"NaT": "", "None": ""})
                )

        output_json = log_df.to_dict(orient="records")

        return jsonify(output_json), 200
    except Exception:
        logger.exception("Failed to query audit logs")
        return jsonify({"message": "Failed to query audit logs"}), 500


@auditlog.get("/email/<string:email>", endpoint="get_logs_by_user")
@require_perm("auditlog:read")
def get_logs_by_user(email):
    """Query all jobs by email"""
    log_list = [
        log.to_dict() for log in AuditLog.query.filter_by(user_email=email).all()
    ]

    # audit log
    log_audit(
        action="Retrieve",
        module="log",
        submodule="",
        previous_data="",
        new_data="",
        description=f"User [$USER] retrieved all logs from user [{email}]",
        error_codes="",
        database_involved="audit_logs",
    )
    return jsonify(log_list), 200


@auditlog.post("/add")
@require_perm("auditlog:read")
def add_log():
    """Record an audit entry from an explicit request body."""
    try:
        body = AddAuditLog.model_validate(request.get_json(silent=True) or {})
    except ValidationError as e:
        return jsonify({"message": validation_message(e)}), 400

    log = log_audit(
        action=body.action,
        user_email=body.email,
        module=body.module,
        submodule=body.submodule,
        previous_data=body.previous_data,
        new_data=body.new_data,
        description=body.description,
        error_codes=body.error_codes,
        database_involved=body.database_involved,
    )

    return jsonify(log), 201
