from datetime import datetime, timezone
from project import db
from project.api.utils import convert_to_local_timezone


class Job(db.Model):
    __tablename__ = 'jobs'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    job_id = db.Column(db.String(64), unique=True, nullable=False)
    email = db.Column(db.String(64), db.ForeignKey('users.email'), nullable=False)
    module = db.Column(db.String(512), nullable=False)
    job_data_id = db.Column(db.String(64), unique=True, nullable=True)
    submodule = db.Column(db.String(512), nullable=False)
    added_on = db.Column(db.DateTime, nullable=False, default=datetime.now(timezone.utc))
    executed_by = db.Column(db.String(64), nullable=True)
    executed_on = db.Column(db.DateTime, nullable=True)
    end_date = db.Column(db.DateTime, nullable=True)
    status = db.Column(db.String(16), nullable=False)
    active = db.Column(db.Boolean, nullable=False)
    progress = db.Column(db.Integer, nullable=False, default=0)
    input = db.Column(db.Text, nullable=True)
    output = db.Column(db.Text, nullable=True)
    description = db.Column(db.Text, nullable=True)

    # relationships
    history = db.relationship('JobHistory', backref='job', cascade="all, delete", lazy=True)

    def __init__(self, job_id, email, module, job_data_id='', submodule='', added_on=datetime.now(timezone.utc), executed_by='', executed_on=None,
                 end_date=None, status='created', active=False, progress=0, input='', output='', description=''):
        self.job_id = job_id
        self.email = email
        self.module = module
        self.job_data_id = job_data_id
        self.submodule = submodule
        self.added_on = added_on
        self.executed_by = executed_by
        self.executed_on = executed_on
        self.end_date = datetime.now(timezone.utc) if output else end_date
        self.status = 'finished' if output else status
        self.active = active
        self.progress = 100 if output else progress
        self.input = input
        self.output = output
        self.description = description

    def to_dict(self):
        return dict(
            id=self.id,
            job_id=self.job_id,
            email=self.email,
            module=self.module,
            job_data_id=self.job_data_id,
            submodule=self.submodule,
            added_on=convert_to_local_timezone(self.added_on),
            executed_by=self.executed_by,
            executed_on=convert_to_local_timezone(self.executed_on),
            end_date=convert_to_local_timezone(self.end_date),
            status=self.status,
            active=self.active,
            progress=self.progress,
            input=self.input,
            output=self.output,
            description=self.description,
        )


class JobHistory(db.Model):
    __tablename__ = 'jobHistory'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    job_id = db.Column(db.String(64), db.ForeignKey('jobs.job_id'), nullable=False)
    action = db.Column(db.String(255), nullable=True)
    status_from = db.Column(db.String(16), nullable=False)
    status_to = db.Column(db.String(16), nullable=False)
    timestamp = db.Column(db.DateTime, nullable=False, default=datetime.now(timezone.utc))
    error_message = db.Column(db.Text, nullable=True)

    def __init__(self, job_id, action='', status_from='', status_to='', timestamp=datetime.now(timezone.utc), error_message=''):
        self.job_id = job_id
        self.action = action
        self.timestamp = timestamp
        self.status_from = status_from
        self.status_to = status_to
        self.error_message = error_message

    def to_dict(self):
        return dict(
            id=self.id,
            job_id=self.job_id,
            action=self.action,
            status_from=self.status_from,
            status_to=self.status_to,
            timestamp=convert_to_local_timezone(self.timestamp),
            error_message=self.error_message
        )
