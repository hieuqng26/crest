from flask import Blueprint, jsonify, make_response, request
from flask_jwt_extended import jwt_required
import pandas as pd
from sqlalchemy import text
from datetime import timedelta
from project.api.utils import validate_request, valid_date
from project.api.auditlog.models import AuditLog
from project.api.auditlog.models import log_audit
from project.api.auth.utils import prevent_multiple_logins_per_user

auditlog = Blueprint('auditlog', __name__)


@auditlog.route('/all', methods=['POST'], endpoint='get_all_logs')
@jwt_required()
@prevent_multiple_logins_per_user()
@validate_request(allowed_keys=['page', 'page_size', 'columns', 'date_from', 'date_to', 'user_id',
                                'module', 'submodule', 'action', 'get_size', 'sort_column', 'sort_order'])
def get_all_logs():
    """Query all logs"""
    try:
        data = request.get_json()
        page = data.get('page', None)
        page_size = data.get('page_size', None)
        columns = data.get('columns')
        date_from = data.get('date_from', None)
        date_to = data.get('date_to', None)
        user_id = data.get('user_id', None)
        module = data.get('module', None)
        submodule = data.get('submodule', None)
        action = data.get('action', None)
        get_size = data.get('get_size', False)
        sort_column = data.get('sort_column', None)
        sort_order = data.get('sort_order', None)

        columns = None if columns in ['undefined', 'null', '', None] else columns.split('\x1e')
        module = None if module in ['undefined', 'null', '', None] else module.split('\x1e')
        submodule = None if submodule in ['undefined', 'null', '', None] else submodule.split('\x1e')
        action = None if action in ['undefined', 'null', '', None] else action.split('\x1e')

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

        # order
        if (sort_column in column_map):
            query = query.order_by(text(f'{sort_column} {sort_order}'))

        if (sort_column != 'timestamp'):
            query = query.order_by(AuditLog.timestamp.desc())  # sort by timestamp by default

        # Get total count if requested
        if get_size:
            total_count = query.count()
            return make_response(jsonify(total_count), 200)

        # Apply pagination
        if page is not None and page_size is not None:
            query = query.offset(page * page_size).limit(page_size)

        # Execute query and convert to DataFrame
        log_list = [log.to_dict() for log in query.all()]
        log_df = pd.DataFrame(log_list)

        if columns is not None:
            log_df = log_df[columns].drop_duplicates()

        # Convert Timestamp to string
        for dcol in ['timestamp', 'event_timestamp', 'log_creation_timestamp', 'login_time', 'logout_time']:
            if dcol in log_df.columns:
                log_df[dcol] = log_df[dcol].astype('str').replace({'NaT': '', 'None': ''})

        output_json = log_df.to_dict(orient='records')

        return make_response(jsonify(output_json), 200)
    except Exception as e:
        return make_response(jsonify({'message': str(e)}), 500)


@auditlog.route('/email/<string:email>', methods=['GET'], endpoint='get_logs_by_user')
@jwt_required()
@prevent_multiple_logins_per_user()
@validate_request()
def get_logs_by_user(email):
    """Query all jobs by email"""
    log_list = [log.to_dict() for log in AuditLog.query.filter_by(user_email=email).all()]

    # audit log
    log_audit(
        action='Retrieve',
        module='log',
        submodule='',
        previous_data='',
        new_data='',
        description=f'User [$USER] retrieved all logs from user [{email}]',
        error_codes='',
        database_involved='audit_logs'
    )
    return make_response(jsonify(log_list), 200)


@auditlog.route('/add', methods=['POST'])
@jwt_required()
@prevent_multiple_logins_per_user()
@validate_request(allowed_keys=['email', 'action', 'module', 'submodule', 'previous_data', 'new_data', 'description', 'status', 'error_codes', 'database_involved'])
def add_log():
    """Add user"""
    data = request.get_json()
    user_email = data.get('email')
    action = data.get('action')
    module = data.get('module')
    submodule = data.get('submodule')
    previous_data = data.get('previous_data')
    new_data = data.get('new_data')
    description = data.get('description')
    status = data.get('status')
    error_codes = data.get('error_codes')
    database_involved = data.get('database_involved')

    if not user_email or not action or not module:
        return make_response(jsonify({'error': 'Invalid input'}), 400)

    log = log_audit(action=action, user_email=user_email, module=module, submodule=submodule,
                    previous_data=previous_data, new_data=new_data, description=description,
                    error_codes=error_codes, database_involved=database_involved)

    return make_response(jsonify(log), 201)
