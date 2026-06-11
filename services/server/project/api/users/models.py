import re
from uuid import uuid4
from datetime import datetime, timezone

from project import db, bcrypt
from project.api.utils import valid_date


def get_uuid():
    return uuid4().hex


class User(db.Model):
    __tablename__ = 'users'

    id = db.Column(db.String(64), primary_key=True, unique=True, default=get_uuid)
    email = db.Column(db.String(64), unique=True, nullable=False)
    password = db.Column(db.String(128), nullable=False)
    name = db.Column(db.String(32), nullable=False)
    registered_on = db.Column(db.DateTime(timezone=True), nullable=False, default=datetime.now(timezone.utc))
    status = db.Column(db.String(16), nullable=False)
    role = db.Column(db.String(32), nullable=False)
    last_login = db.Column(db.DateTime(timezone=True), nullable=True)
    last_logout = db.Column(db.DateTime(timezone=True), nullable=True)
    last_session = db.Column(db.String(255), nullable=True)
    last_login_type = db.Column(db.String(16), nullable=True)

    def __init__(self, email, password, role, name=None, status="active", registered_on=datetime.now(timezone.utc),
                 last_login=None, last_logout=None):
        self.email = email
        self.password = bcrypt.generate_password_hash(password).decode('utf-8')
        self.role = role
        self.name = name if name else email
        self.status = status
        self.registered_on = valid_date(registered_on)
        self.last_login = valid_date(last_login) if last_login else None
        self.last_logout = valid_date(last_logout) if last_logout else None

    @classmethod
    def authenticate(cls, email, password):
        if not email or not isinstance(email, str) or not password or not isinstance(password, str):
            raise ValueError('User name or password is empty')

        email = email.strip()
        password = password.strip()

        # validation on email - only alphanumeric, underscore, hyphen, and atmark
        if (len(email) > 64) or not bool(re.match(r'^[a-zA-Z0-9_\-@]+$', email)):
            raise ValueError('User name is not in a valid format')

        user = cls.query.filter_by(email=email).first()
        if not user or not bcrypt.check_password_hash(user.password, password) or user.status != 'active':
            return None

        # update user login time
        user.last_login = datetime.now(timezone.utc)
        user.last_logout = None
        user.last_session = str(uuid4())
        user.last_login_type = "Success"
        db.session.commit()

        return user

    def to_dict(self):
        return dict(
            id=self.id,
            email=self.email,
            name=self.name,
            registered_on=self.registered_on,
            status=self.status,
            role=self.role,
            last_login=self.last_login,
            last_logout=self.last_logout,
            last_session=self.last_session,
            last_login_type=self.last_login_type
        )
