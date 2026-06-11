from flask import make_response, jsonify
from project import db
from project.logger import get_logger

logger = get_logger(__name__)


class ActiveSession(db.Model):
    __tablename__ = 'active_session'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_email = db.Column(db.String(32), nullable=False)
    session_token = db.Column(db.Text, nullable=False)

    def __init__(self, user_email, session_token):
        self.user_email = user_email
        self.session_token = session_token

    def to_dict(self):
        return {
            'id': self.id,
            'user_email': self.user_email,
            'session_token': self.session_token
        }


def get_session_token(email):
    ses = ActiveSession.query.filter_by(user_email=email).first()
    if not ses:
        return None
    return ses.to_dict().get('session_token')


def add_session(email, token):
    ses = ActiveSession.query.filter_by(user_email=email).first()
    if ses:
        ses.session_token = token
    else:
        ses = ActiveSession(user_email=email, session_token=token)
        db.session.add(ses)
    db.session.commit()


def update_session(email, token):
    ses = ActiveSession.query.filter_by(user_email=email).first()
    if not ses:
        e = PermissionError(f"No session found for user {email}")
        logger.exception(e)
        return make_response(jsonify({'message': str(e)}), 401)
    ses.session_token = token
    db.session.commit()


def delete_session(email):
    try:
        result = ActiveSession.query.filter_by(user_email=email).delete()
        db.session.commit()
        return result
    except Exception as e:
        db.session.rollback()
        logger.exception(e)
        return 0
