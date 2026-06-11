from datetime import datetime, timezone
import os
from flask_jwt_extended import get_jwt_identity
from flask import request
from user_agents import parse
import uuid

from project import db
from project.api.users.models import User
from project.logger import get_logger

logger = get_logger(__name__)


class AuditLog(db.Model):
    __tablename__ = 'audit_logs'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    log_id = db.Column(db.String(64), nullable=False)
    user_email = db.Column(db.String(32), nullable=False)
    role = db.Column(db.String(32), nullable=True)  # needs to be nullalbe for migration to add this column to the previous table
    action = db.Column(db.String(16), nullable=False)
    module = db.Column(db.String(512), nullable=True)
    submodule = db.Column(db.String(512), nullable=True)
    timestamp = db.Column(db.DateTime(timezone=True), nullable=False, default=datetime.now(timezone.utc))
    status = db.Column(db.String(16), nullable=True)
    previous_data = db.Column(db.Text, nullable=True)
    new_data = db.Column(db.Text, nullable=True)
    ip_address = db.Column(db.String(45), nullable=True)
    ip_address2 = db.Column(db.String(45), nullable=True)
    ip_address3 = db.Column(db.String(45), nullable=True)
    description = db.Column(db.Text, nullable=True)
    device_info = db.Column(db.JSON, nullable=True)
    affected_records = db.Column(db.Text, nullable=True)
    change_reason = db.Column(db.Text, nullable=True)
    event_timestamp = db.Column(db.DateTime(timezone=True), nullable=False, default=datetime.now(timezone.utc))
    log_creation_timestamp = db.Column(db.DateTime(timezone=True), nullable=False, default=datetime.now(timezone.utc))
    session_id = db.Column(db.String(255), nullable=True)
    login_time = db.Column(db.DateTime(timezone=True), nullable=False, default=datetime.now(timezone.utc))
    logout_time = db.Column(db.DateTime(timezone=True), nullable=True)
    login_type = db.Column(db.String(16), nullable=True)
    error_codes = db.Column(db.String(16), nullable=True)
    authorization_check = db.Column(db.Boolean, nullable=True)
    application_version = db.Column(db.String(16), nullable=True)
    api_endpoints = db.Column(db.Text, nullable=True)
    database_involved = db.Column(db.String(255), nullable=True)
    job_id = db.Column(db.String(64), nullable=True)
    job_judged_by = db.Column(db.String(32), nullable=True)
    comments = db.Column(db.Text, nullable=True)

    def __init__(self, log_id, user_email, role, action, module, submodule='', previous_data='', new_data='',
                 timestamp=datetime.now(timezone.utc), ip_address='', ip_address2='', ip_address3='', description='', status='', device_info=None,
                 session_id=None, affected_records=None, change_reason=None, event_timestamp=None, log_creation_timestamp=None,
                 login_time=None, logout_time=None, login_type=None, error_codes=None, authorization_check=None, application_version=None,
                 api_endpoints=None, database_involved=None, job_id=None, job_judged_by=None, comments=None):
        self.log_id = log_id
        self.user_email = user_email
        self.role = role
        self.action = action
        self.module = module
        self.submodule = submodule
        self.timestamp = timestamp
        self.previous_data = previous_data
        self.new_data = new_data
        self.ip_address = ip_address
        self.ip_address2 = ip_address2
        self.ip_address3 = ip_address3
        self.description = description
        self.status = status
        self.device_info = device_info
        self.session_id = session_id
        self.affected_records = affected_records
        self.change_reason = change_reason
        self.event_timestamp = event_timestamp
        self.log_creation_timestamp = log_creation_timestamp
        self.login_time = login_time
        self.logout_time = logout_time
        self.login_type = login_type
        self.error_codes = error_codes
        self.authorization_check = authorization_check
        self.application_version = application_version
        self.api_endpoints = api_endpoints
        self.database_involved = database_involved
        self.job_id = job_id
        self.job_judged_by = job_judged_by
        self.comments = comments

    def to_dict(self):
        return dict(
            log_id=self.log_id,
            user_email=self.user_email,
            role=self.role,
            action=self.action,
            module=self.module,
            submodule=self.submodule,
            timestamp=self.timestamp,
            previous_data=self.previous_data,
            new_data=self.new_data,
            ip_address=self.ip_address,
            ip_address2=self.ip_address2,
            ip_address3=self.ip_address3,
            description=self.description,
            status=self.status,
            device_info=self.device_info,
            session_id=self.session_id,
            affected_records=self.affected_records,
            change_reason=self.change_reason,
            event_timestamp=self.event_timestamp,
            log_creation_timestamp=self.log_creation_timestamp,
            login_time=self.login_time,
            logout_time=self.logout_time,
            login_type=self.login_type,
            error_codes=self.error_codes,
            authorization_check=self.authorization_check,
            application_version=self.application_version,
            api_endpoints=self.api_endpoints,
            database_involved=self.database_involved,
            job_id=self.job_id,
            job_judged_by=self.job_judged_by,
            comments=self.comments
        )

    @classmethod
    def column_map(cls):
        return {
            'log_id': cls.log_id,
            'user_email': cls.user_email,
            'role': cls.role,
            'action': cls.action,
            'module': cls.module,
            'submodule': cls.submodule,
            'timestamp': cls.timestamp,
            'previous_data': cls.previous_data,
            'new_data': cls.new_data,
            'ip_address': cls.ip_address,
            'ip_address2': cls.ip_address2,
            'ip_address3': cls.ip_address3,
            'description': cls.description,
            'status': cls.status,
            'device_info': cls.device_info,
            'session_id': cls.session_id,
            'affected_records': cls.affected_records,
            'change_reason': cls.change_reason,
            'event_timestamp': cls.event_timestamp,
            'log_creation_timestamp': cls.log_creation_timestamp,
            'login_time': cls.login_time,
            'logout_time': cls.logout_time,
            'login_type': cls.login_type,
            'error_codes': cls.error_codes,
            'authorization_check': cls.authorization_check,
            'application_version': cls.application_version,
            'api_endpoints': cls.api_endpoints,
            'database_involved': cls.database_involved,
            'job_id': cls.job_id,
            'job_judged_by': cls.job_judged_by,
            'comments': cls.comments
        }


def log_audit(action, module='', submodule='', previous_data='', new_data='', description='',
              user_email=None, error_codes='', database_involved='', api_endpoints=None, device_info=None, ip_address=None, ip_address2=None, ip_address3=None,
              job_id='', job_judged_by='', application_version=os.getenv('APPLICATION_VERSION')):
    # user is either passed as an argument or extracted from the JWT token
    user_email = get_jwt_identity() if user_email is None else user_email
    user = User.query.filter_by(email=user_email).first()
    description = description.replace('$USER', user_email)
    device_info = get_device_info() if device_info is None else device_info
    api_endpoints = request.url if api_endpoints is None else api_endpoints
    ip_address_header_field = os.getenv('IP_ADDERSS_HEADER_FIELD', '')
    ip_address_value = request.headers.getlist(ip_address_header_field)[0] if (ip_address is None and request.headers.getlist(ip_address_header_field)) else ip_address
    ip_address2 = ip_address if ip_address2 is None else ip_address2
    ip_address2_value = ip_address_value if ip_address2 is None else ip_address2
    ip_address2_value = request.access_route[-1] if (ip_address2 is None and request.access_route) else ip_address2
    ip_address3 = ip_address if ip_address3 is None else ip_address3
    ip_address3_value = ip_address_value if ip_address3 is None else ip_address3
    ip_address3_value = request.remote_addr if ip_address3 is None else ip_address3

    status = 'failed' if error_codes else 'success'

    audit_log = AuditLog(
        log_id=str(uuid.uuid4()),
        device_info=device_info,
        api_endpoints=api_endpoints,
        timestamp=datetime.now(timezone.utc),
        application_version=application_version,
        ip_address=ip_address_value,
        ip_address2=ip_address2_value,
        ip_address3=ip_address3_value,
        user_email=user_email,
        role=user.role if user else '',
        action=action,
        module=module,
        submodule=submodule,
        previous_data=previous_data,
        new_data=new_data,
        status=status,
        description=description,
        error_codes=error_codes,
        database_involved=database_involved,
        session_id=user.last_session if user else None,
        login_time=user.last_login if user else None,
        logout_time=user.last_logout if user else None,
        login_type=user.last_login_type if user else "Failed",
        job_id=job_id,
        job_judged_by=job_judged_by
    )
    db.session.add(audit_log)
    db.session.commit()

    # send log to logstash
    logger.info(audit_log.to_dict())
    return audit_log.to_dict()


def get_device_info():
    # Get user-agent string and parse it
    user_agent_string = request.headers.get('User-Agent')
    user_agent = parse(user_agent_string)
    return {
        'browser': user_agent.browser.family,
        'browser_version': user_agent.browser.version_string,
        'os': user_agent.os.family,
        'os_version': user_agent.os.version_string,
        'device': user_agent.device.family,
        'device_brand': user_agent.device.brand,
        'device_model': user_agent.device.model
    }


def get_session_id():
    # Get the session cookie directly from the request object
    session_cookie = request.cookies.get('session')

    # Extract the session ID (everything before the '.')
    session_id = session_cookie.split('.')[0] if session_cookie else None

    return f"Session ID: {session_id}"
