from flask import Blueprint, jsonify, make_response, request, current_app
from flask_jwt_extended import jwt_required, get_jwt_identity
from datetime import datetime, timezone, timedelta
from sqlalchemy import text
from rq import Connection, Queue, Retry, Callback
from rq.exceptions import NoSuchJobError
from rq.job import Job as RQJob
from rq.command import send_stop_job_command
from werkzeug.exceptions import Forbidden, NotFound
import redis
import uuid

from project import db, send_notification, DATA_STORE
from project.logger import get_logger
from project.api.roles.roles import roles_required, roles_satisfied_module
import project.api.roles.roles as roleSettings
from project.api.jobs.utils import *
from project.api.jobs.services import *
from project.api.jobs.models import *
from project.api.auditlog.models import log_audit
from project.api.users.models import *
from project.api.auth.utils import prevent_multiple_logins_per_user
from project.api.utils import valid_uuid, validate_request, toJSON, validate_boolean
from project.db_models.job_models import clear_job_data_from_app_db
from project.sftp import sftp_cleanup_dir


job = Blueprint('job', __name__)
logger = get_logger(__name__)


@job.route('/add', methods=['POST'], endpoint='add_job')
@jwt_required()
@prevent_multiple_logins_per_user()
@validate_request(allowed_keys=['email', 'module', 'submodule', 'input', 'inputPath', 'dbName'])
def add():
    # Add job
    # Parse input request
    data = request.get_json()
    email = data.get('email', '')
    module = data.get('module', '')
    submodule = data.get('submodule', '')
    input = data.get('input', {})
    inputPath = data.get('inputPath', '')
    dbName = data.get('dbName', None)
    job_id = str(uuid.uuid4())
    description = f'Calculate {module}-{submodule}'

    try:
        # validate input
        if not email or not module:
            raise ValueError('Missing email or module fields')
        user = User.query.filter_by(email=email).first()
        if not user:  # this is needed because email is a foreign key of Job model to User model
            raise ValueError("Invalid user ID")

        # check roles
        roles_satisfied_module(module, 'execute', action='Enqueue', submodule=submodule)

        # Save input data to db
        with Connection(redis.from_url(current_app.config['REDIS_URL'])):
            q = Queue('data')
            job_timeout = os.getenv('REDIS_JOB_TIMEOUT', '86400')
            kwargs = {'job_id': job_id, 'email': email, 'module': module, 'submodule': submodule, 'description': description}
            data_job_id = str(uuid.uuid4())  # need to be different from job_id. Otherwise, job will be removed when data job is removed
            q.enqueue(save_input, input, inputPath, job_id, module, submodule, dbName,
                      job_timeout=job_timeout, job_id=data_job_id,
                      meta=kwargs,
                      on_success=Callback(add_job_success, timeout=job_timeout),
                      on_failure=Callback(add_job_failure, timeout=job_timeout))

        # send notification for number of pending requests
        job_db = Job(job_id, email, module, job_data_id=data_job_id, submodule=submodule, status="created", input="",
                     description=description, added_on=datetime.now(timezone.utc))
        job_hist = JobHistory(job_id, status_from='', status_to="created", action=description, timestamp=datetime.now(timezone.utc))
        db.session.add(job_hist)
        db.session.add(job_db)
        db.session.commit()
        send_notification('nPendingRequests', len(Job.query.filter(Job.status.in_(["pending", "created"])).all()))

        # audit log
        log_audit(
            action='Enqueue',
            module=module,
            submodule=submodule,
            previous_data='',
            new_data='',
            description=f'User [$USER] added new job {job_id}',
            error_codes='',
            database_involved='jobs, jobHistory'
        )
        return make_response(jsonify({'job_id': job_id}), 201)

    except ValueError as e:
        db.session.rollback()
        log_audit(
            action='Enqueue',
            module=module,
            submodule=submodule,
            previous_data='',
            new_data='',
            description=f'User [$USER] failed to add job. Error: {str(e)}',
            error_codes='400',
            database_involved=''
        )
        logger.exception(e)
        return make_response(jsonify({'message': str(e)}), 400)

    except Forbidden as e:
        db.session.rollback()
        log_audit(
            action='Enqueue',
            module=module,
            submodule=submodule,
            previous_data='',
            new_data='',
            description=f'User [$USER] failed to add job. Error: {str(e)}',
            error_codes='403',
            database_involved=''
        )
        logger.exception(e)
        return make_response(jsonify({'message': str(e)}), 403)

    except Exception as e:
        db.session.rollback()
        log_audit(
            action='Enqueue',
            module=module,
            submodule=submodule,
            previous_data='',
            new_data='',
            description=f'User [$USER] failed to add job. Error: {str(e)}',
            error_codes='500',
            database_involved=''
        )
        logger.exception(e)
        return make_response(jsonify({'message': str(e)}), 500)


@job.route('/run/<string:job_id>', methods=['POST'], endpoint='run_job')
@jwt_required()
@prevent_multiple_logins_per_user()
@validate_request()
def run(job_id):
    job_timeout = os.getenv('REDIS_JOB_TIMEOUT', 60*60*24)
    retry = Retry(max=int(os.getenv('REDIS_JOB_RETRY', 3)))
    result_ttl = int(os.getenv('REDIS_RESULT_TTL', 180))

    try:
        job_id = valid_uuid(job_id)
        job_db = Job.query.filter_by(job_id=job_id).first()
        if not job_db:
            log_audit(
                action='Compute',
                module='job',
                submodule='',
                previous_data='',
                new_data='',
                description=f'User [$USER] failed to compute job [{job_id}]. Error: Job not found',
                error_codes='404',
                database_involved='jobs'
            )
            return make_response(jsonify({'message': 'Job not found'}), 404)

        # check roles
        roles_satisfied_module(job_db.module, 'write', action='Compute', submodule=job_db.submodule)

        # compute job

        if (job_db.module == 'cem') and (job_db.submodule == 'corporate'):
            with Connection(redis.from_url(current_app.config['REDIS_URL'])):
                q = Queue(job_db.module)
                q.enqueue(calculate, job_db,
                          job_timeout=job_timeout, retry=retry, job_id=job_id, result_ttl=result_ttl,
                          on_success=Callback(report_success, timeout=job_timeout),
                          on_failure=Callback(report_failure, timeout=job_timeout))
        else:
            raise ValueError('Module not found.')

        # update job history
        update_job_status(job_db, 'queued')
        job_db.active = False
        job_db.progress = 0
        job_db.end_date = None
        db.session.commit()

        # send notification for number of pending requests
        send_notification('nPendingRequests', len(Job.query.filter_by(status='pending').all()))

        # audit log
        log_audit(
            action='Compute',
            module=job_db.module,
            submodule=job_db.submodule,
            previous_data='',
            new_data='',
            description=f'User [$USER] started job [{job_db.job_id}]',
            error_codes='',
            database_involved='jobs, jobHistory',
            job_id=job_id,
            job_judged_by=get_jwt_identity()
        )
        return make_response(jsonify(job_db.to_dict()), 201)

    except ValueError as e:
        db.session.rollback()
        update_job_status(job_db, 'failed')
        log_audit(
            action='Compute',
            module=job_db.module,
            submodule=job_db.submodule,
            previous_data='',
            new_data='',
            description=f'User [$USER] failed to start job [{job_db.job_id}]. Error: {str(e)}',
            error_codes='400',
            database_involved='jobs, jobHistory',
            job_id=job_id,
            job_judged_by=get_jwt_identity()
        )
        logger.exception(e)
        return make_response(jsonify({'message': str(e)}), 400)

    except NameError as e:
        db.session.rollback()
        update_job_status(job_db, 'failed')
        log_audit(
            action='Compute',
            module='job',
            submodule='',
            previous_data='',
            new_data='',
            description=f'User [$USER] failed to start job. Job_id is invalid. Error: {str(e)}',
            error_codes='404',
            database_involved='jobs, jobHistory',
        )
        logger.exception(e)
        return make_response(jsonify({'message': str(e)}), 404)

    except Forbidden as e:
        db.session.rollback()
        update_job_status(job_db, 'failed')
        log_audit(
            action='Compute',
            module=job_db.module,
            submodule=job_db.submodule,
            previous_data='',
            new_data='',
            description=f'User [$USER] failed to start job [{job_db.job_id}]. Error: {str(e)}',
            error_codes='403',
            database_involved='jobs, jobHistory',
            job_id=job_id,
            job_judged_by=get_jwt_identity()
        )
        logger.exception(e)
        return make_response(jsonify({'message': str(e)}), 403)

    except Exception as e:
        db.session.rollback()
        update_job_status(job_db, 'failed')
        log_audit(
            action='Compute',
            module=job_db.module,
            submodule=job_db.submodule,
            previous_data='',
            new_data='',
            description=f'User [$USER] failed to start job [{job_db.job_id}]. Error: {str(e)}',
            error_codes='500',
            database_involved='jobs, jobHistory',
            job_id=job_id,
            job_judged_by=get_jwt_identity()
        )
        logger.exception(e)
        return make_response(jsonify({'message': str(e)}), 500)

    finally:
        # Update job executor details
        job_db.executed_by = get_jwt_identity()
        job_db.executed_on = datetime.now(timezone.utc)
        db.session.commit()


@job.route('/cancel/<string:job_id>', methods=['POST'], endpoint='cancel_job')
@jwt_required()
@prevent_multiple_logins_per_user()
@validate_request()
def cancel(job_id):
    try:
        job_id = valid_uuid(job_id)
        # Retrieve job details from the database
        job_db = Job.query.filter_by(job_id=job_id).first()
        if not job_db:
            log_audit(
                action='Cancel',
                module='job',
                submodule='',
                previous_data='',
                new_data='',
                description=f'User [$USER] failed to cancel job [{job_id}]. Error: Job not found',
                error_codes='404',
                database_involved='jobs',
                job_id=job_id,
                job_judged_by=get_jwt_identity()
            )
            return make_response(jsonify({'message': 'Job not found'}), 404)

        # check roles
        roles_satisfied_module(job_db.module, 'write', action='Cancel', submodule=job_db.submodule)

        # Connect to Redis and cancel the job
        with Connection(redis.from_url(current_app.config['REDIS_URL'])):
            queue_name = 'cem' if job_db.module in ['bottomup', 'pcaf'] else job_db.module
            queue_job_id = job_id
            if job_db.status == 'created':
                queue_name = 'data'
                queue_job_id = job_db.job_data_id
            q = Queue(queue_name)
            rq_job = RQJob.fetch(queue_job_id, connection=q.connection)
            if rq_job.get_status() in ['queued', 'deferred']:
                rq_job.cancel()
            elif rq_job.get_status() in ['started']:
                send_stop_job_command(q.connection, queue_job_id)
            else:
                raise Exception(f"Job's already {rq_job.get_status()}")

        # Clear database job data
        clear_job_data_from_app_db(job_db.module, job_db.submodule, type='output', db_name=None, job_id=job_db.job_id)

        # update job history
        update_job_status(job_db, 'canceled')
        job_db.active = False
        db.session.commit()

        # send notification for number of pending requests
        send_notification('nPendingRequests', len(Job.query.filter_by(status='pending').all()))

        # audit log
        log_audit(
            action='Cancel',
            module=job_db.module,
            submodule=job_db.submodule,
            previous_data='',
            new_data='',
            description=f'User [$USER] canceled job [{job_id}]',
            error_codes='',
            database_involved='jobs, jobHistory',
            job_id=job_id,
            job_judged_by=get_jwt_identity()
        )
        return make_response(jsonify({'message': 'Job canceled successfully', 'job_id': job_id}), 200)

    except NameError as e:
        db.session.rollback()
        log_audit(
            action='Cancel',
            module='job',
            submodule='',
            previous_data='',
            new_data='',
            description=f'User [$USER] failed to cancel job. Job_id is invalid. Error: {str(e)}',
            error_codes='404',
            database_involved='jobs, jobHistory',
        )
        return make_response(jsonify({'message': str(e)}), 404)

    except NoSuchJobError as e:
        db.session.rollback()
        log_audit(
            action='Cancel',
            module=job_db.module,
            submodule=job_db.submodule,
            previous_data='',
            new_data='',
            description=f'User [$USER] failed to cancel job [{job_id}]. Error: {str(e)}',
            error_codes='404',
            database_involved='jobs',
            job_id=job_id,
            job_judged_by=get_jwt_identity()
        )
        return make_response(jsonify({'message': str(e)}), 404)

    except Exception as e:
        db.session.rollback()
        log_audit(
            action='Cancel',
            module=job_db.module,
            submodule=job_db.submodule,
            previous_data='',
            new_data='',
            description=f'User [$USER] failed to cancel job [{job_id}]. Error: {str(e)}',
            error_codes='500',
            database_involved='jobs',
            job_id=job_id,
            job_judged_by=get_jwt_identity()
        )
        return make_response(jsonify({'message': str(e)}), 500)


@job.route('/delete/<string:job_id>', methods=['DELETE'], endpoint='delete_job')
@jwt_required()
@prevent_multiple_logins_per_user()
@validate_request()
def delete(job_id):
    """Delete job by job_id"""
    try:
        job_id = valid_uuid(job_id)
        job_db = Job.query.filter_by(job_id=job_id).first()
        if not job_db:
            log_audit(
                action='Delete',
                module='job',
                submodule='',
                previous_data='',
                new_data='',
                description=f'User [$USER] failed to delete job [{job_id}]. Error: Job not found',
                error_codes='404',
                database_involved='jobs',
                job_id=job_id,
                job_judged_by=get_jwt_identity()
            )
            return make_response(jsonify({'message': 'Job not found'}), 404)

        # check roles
        roles_satisfied_module(job_db.module, 'execute', action='Delete', submodule=job_db.submodule)

        # if job is in queue, delete it
        try:
            with Connection(redis.from_url(current_app.config['REDIS_URL'])):
                queue_name = 'cem' if job_db.module in ['bottomup', 'pcaf'] else job_db.module
                queue_job_id = job_id
                if job_db.status == 'created':
                    queue_name = 'data'
                    queue_job_id = job_db.job_data_id
                q = Queue(queue_name)
                rq_job = RQJob.fetch(queue_job_id, connection=q.connection)

                if rq_job.get_status() in ['finished', 'failed', 'canceled', 'stopped']:
                    rq_job.delete()
                else:
                    raise Exception(f"Job's already {rq_job.get_status()}")
        # if not job found (is pending), ignore error
        except NoSuchJobError as e:
            pass

        # check if job removed successfully, delete job data
        if not RQJob.exists(queue_job_id, connection=q.connection):
            clear_job_data_from_app_db(job_db.module, job_db.submodule, type='input', db_name=None, job_id=job_db.job_id)
            clear_job_data_from_app_db(job_db.module, job_db.submodule, type='output', db_name=None, job_id=job_db.job_id)
            sftp_cleanup_dir(os.path.join(DATA_STORE, get_job_dir(job_db.job_id, job_db.module, job_db.submodule, '')))
            db.session.delete(job_db)
            db.session.commit()

        # send notification for number of pending requests
        send_notification('nPendingRequests', len(Job.query.filter_by(status='pending').all()))

        # audit log
        log_audit(
            action='Delete',
            module=job_db.module,
            submodule=job_db.submodule,
            previous_data='',
            new_data='',
            description=f'User [$USER] deleted job [{job_id}]',
            error_codes='',
            database_involved='jobs, jobHistory',
            job_id=job_id,
            job_judged_by=get_jwt_identity()
        )
        return make_response(jsonify({'message': 'Job deleted'}), 200)

    except NameError as e:
        db.session.rollback()
        log_audit(
            action='Delete',
            module='job',
            submodule='',
            previous_data='',
            new_data='',
            description=f'User [$USER] failed to delete job. Job_id is invalid. Error: {str(e)}',
            error_codes='404',
            database_involved='jobs, jobHistory',
        )
        return make_response(jsonify({'message': str(e)}), 404)

    except Exception as e:
        db.session.rollback()
        log_audit(
            action='Delete',
            module=job_db.module,
            submodule=job_db.submodule,
            previous_data='',
            new_data='',
            description=f'User [$USER] failed to delete job [{job_id}]. Error: {str(e)}',
            error_codes='500',
            database_involved='jobs',
            job_id=job_id,
            job_judged_by=get_jwt_identity()
        )
        return make_response(jsonify({'message': str(e)}), 500)


@job.route('/get_status/<string:job_id>', methods=['PUT'], endpoint='get_job_status')
@jwt_required()
@prevent_multiple_logins_per_user()
@validate_request()
def get_status(job_id):
    try:
        job_id = valid_uuid(job_id)
        # queue job from db
        job_db = Job.query.filter_by(job_id=job_id).first()
        if not job_db:
            raise NotFound('Job not found')

        # query job from queue
        with Connection(redis.from_url(current_app.config['REDIS_URL'])):
            q = Queue(job_db.module)
            job_rq = RQJob.fetch(job_id, connection=q.connection)

        if job_rq is None:
            raise NotFound('Job not found in queue')

        # check roles
        roles_satisfied_module(job_db.module, 'read', action='Retrieve', submodule=job_db.submodule)

        # update job status and progress if job is queued or started
        job_rq_status = job_rq.get_status()
        if job_db.status in ['started', 'queued']:
            # if status changes, update status
            if job_db.status != job_rq_status:
                job_hist = JobHistory(job_id, status_from=job_db.status, status_to=job_rq_status,
                                      action=f'Automated routing', timestamp=datetime.now(timezone.utc))
                db.session.add(job_hist)
                job_db.status = job_rq_status

            # update progress
            job_db.progress = job_rq.meta.get('progress', 0)

        db.session.commit()

        # audit log
        log_audit(
            action='Retrieve',
            module=job_db.module,
            submodule=job_db.submodule,
            previous_data='',
            new_data='',
            description=f'User [$USER] retrieved status for job [{job_id}]',
            error_codes='',
            database_involved='jobs, jobHistory'
        )
        return {'job': job_db.to_dict()}, 200

    except NotFound as e:
        db.session.rollback()
        log_audit(
            action='Retrieve',
            module='job',
            submodule='',
            previous_data='',
            new_data='',
            description=f'User [$USER] failed to retrieve status for job [{job_id}]. Error: {str(e)}',
            error_codes='404',
            database_involved='jobs, jobHistory'
        )
        return make_response(jsonify({'message': str(e)}), 404)

    except NameError as e:
        db.session.rollback()
        log_audit(
            action='Retrieve',
            module='job',
            submodule='',
            previous_data='',
            new_data='',
            description=f'User [$USER] failed to retrieve status for job [{job_id}]. Error: {str(e)}',
            error_codes='404',
            database_involved='jobs, jobHistory',
        )
        return make_response(jsonify({'message': str(e)}), 404)

    except Exception as e:
        db.session.rollback()
        log_audit(
            action='Retrieve',
            module=job_db.module,
            submodule=job_db.submodule,
            previous_data='',
            new_data='',
            description=f'User [$USER] failed to retrieve status for job [{job_id}]. Error: {str(e)}',
            error_codes='500',
            database_involved='jobs'
        )
        return make_response(jsonify({'message': str(e)}), 500)


# ========================= CRUD ==========================
@job.route('/all', methods=['GET'])
@jwt_required()
@prevent_multiple_logins_per_user()
@validate_request()
def get_all_jobs():
    roles_required(*roleSettings.getRoles('job', 'read'), action='Retrieve', module='job', submodule='')
    """Query all jobs"""
    jobs_list = [job_db.to_dict() for job_db in Job.query.all()]

    # audit log
    log_audit(
        action='Retrieve',
        module='job',
        submodule='',
        previous_data='',
        new_data='',
        description=f'User [$USER] retrieved the all jobs',
        error_codes='',
        database_involved='jobs'
    )
    return make_response(jsonify(jobs_list), 200)


@job.route('/id/<string:job_id>', methods=['GET'])
@jwt_required()
@prevent_multiple_logins_per_user()
@validate_request()
def get_job_by_id(job_id):
    """Query job by job_id"""
    try:
        job_id = valid_uuid(job_id)
        job_db = Job.query.filter_by(job_id=job_id).first()
        if not job_db:
            log_audit(
                action='Retrieve',
                module='job',
                submodule='',
                previous_data='',
                new_data='',
                description=f'User [$USER] failed to retrieve job [{job_id}]. Error: Job not found',
                error_codes='404',
                database_involved='jobs'
            )
            return make_response(jsonify({'message': 'Job not found'}), 404)

        # check roles
        roles_satisfied_module(job_db.module, 'read', action='Retrieve', submodule=job_db.submodule)

        # audit log
        log_audit(
            action='Retrieve',
            module='job',
            submodule='',
            previous_data='',
            new_data='',
            description=f'User [$USER] retrieved job [{job_id}]',
            error_codes='',
            database_involved='jobs'
        )
        return make_response(jsonify(job_db.to_dict()), 200)

    except NameError as e:
        log_audit(
            action='Retrieve',
            module='job',
            submodule='',
            previous_data='',
            new_data='',
            description=f'User [$USER] failed to retrieve job. Job_id is invalid. Error: {str(e)}',
            error_codes='404',
            database_involved='jobs, jobHistory',
        )
        return make_response(jsonify({'message': str(e)}), 404)

    except Exception as e:
        log_audit(
            action='Retrieve',
            module='job',
            submodule='',
            previous_data='',
            new_data='',
            description=f'User [$USER] failed to retrieve job [{job_id}]. Error: {str(e)}',
            error_codes='500',
            database_involved='jobs'
        )
        return make_response(jsonify({'message': str(e)}), 500)


@job.route('/current', methods=['GET'], endpoint='get_current_jobs')
@jwt_required()
@prevent_multiple_logins_per_user()
@validate_request()
def get_current_jobs():
    roles_required(*roleSettings.getRoles('*', 'execute'), action='Retrieve', module='job', submodule='')
    """Query all jobs from current user"""
    jobs_list = [job_db.to_dict() for job_db in Job.query.filter_by(email=get_jwt_identity()).all()]

    # audit log
    log_audit(
        action='Retrieve',
        module='job',
        submodule='',
        previous_data='',
        new_data='',
        description=f'User [$USER] retrieved all his/her jobs',
        error_codes='',
        database_involved='jobs'
    )
    return make_response(jsonify(jobs_list), 200)


@job.route('/latest', methods=['POST'], endpoint='get_latest_job')
@jwt_required()
@prevent_multiple_logins_per_user()
@validate_request(allowed_keys=['email', 'module', 'submodule'])
def get_latest_job():
    """Query latest finished job by user email"""
    try:
        data = request.get_json()
        email = data.get('email')
        module = data.get('module')
        submodule = data.get('submodule')

        # check roles
        roles_satisfied_module(module, 'read', action='Retrieve', submodule=submodule)

        # Convert "undefined" and "null" strings to None
        email = None if email in ["undefined", "null", None] else email
        module = None if module in ["undefined", "null", None] else module
        submodule = None if submodule in ["undefined", "null", None] else submodule

        # Build the filter criteria dynamically
        filters = [Job.status == 'finished', Job.active == True]
        if email:
            filters.append(Job.email == email)
        if module:
            filters.append(Job.module == module)
        if submodule:
            filters.append(Job.submodule == submodule)

        # Apply the filters to the query
        job_db = Job.query.filter(*filters).order_by(Job.end_date.desc()).first()
        data = job_db.to_dict() if job_db else None

        # audit log
        log_audit(
            action='Retrieve',
            module=module if module else '',
            submodule=submodule if submodule else '',
            previous_data='',
            new_data='',
            description=f'User [$USER] retrieved latest job for {module}-{submodule}',
            error_codes='',
            database_involved='jobs'
        )
        return make_response(jsonify(data), 200)

    except Exception as e:
        log_audit(
            action='Retrieve',
            module=module if module else '',
            submodule=submodule if submodule else '',
            previous_data='',
            new_data='',
            description=f'User [$USER] failed to retrieve latest job for {module}-{submodule}',
            error_codes='500',
            database_involved='jobs'
        )
        return make_response(jsonify({'message': str(e)}), 500)


@job.route('/module', methods=['POST'], endpoint='get_jobs_by_modules')
@jwt_required()
@prevent_multiple_logins_per_user()
@validate_request(allowed_keys=['modules', 'columns', 'page', 'page_size', 'filter_columns', 'filter_values',
                                'date_col', 'date_from', 'date_to', 'get_size', 'sort_column', 'sort_order'])
def get_jobs_by_modules():
    """Query all jobs by module(s)"""
    try:
        data = request.get_json()
        modules = data.get('modules', [])
        columns = data.get('columns', None)
        page = data.get('page', None)
        page_size = data.get('page_size', None)
        filter_columns = data.get('filter_columns', None)
        filter_values = data.get('filter_values', None)
        date_from = data.get('date_from', None)
        date_to = data.get('date_to', None)
        get_size = data.get('get_size', False)
        sort_column = data.get('sort_column', None)
        sort_order = data.get('sort_order', 'asc')

        # parse arguments
        if filter_values is not None:
            filter_values = json.loads(filter_values)

        columns = None if columns in ['undefined', 'null', '', None] else columns.split('\x1e')
        page = int(page) if page is not None else None
        page_size = int(page_size) if page_size is not None else None
        filter_columns = None if filter_columns in ['undefined', 'null', '', None] else filter_columns.split('\x1e')
        filter_values = None if filter_values in ['undefined', 'null', '', None] else filter_values.split('\x1f')
        sort_column = None if sort_column in ['undefined', 'null', '', None] else sort_column.split('\x1e')
        sort_order = None if sort_order in ['undefined', 'null', '', None] else sort_order.split('\x1e')

        # check roles - ignoring submodule
        allowedModules = []
        for module in modules:
            # roles_satisfied_module() internally ignores submodule
            if roles_satisfied_module(module, '*', action='Retrieve', exceptionIfNotSatisfied=False):
                moduleWithoutSubmodule = module.split("__")[0]
                allowedModules.append(moduleWithoutSubmodule)
        modules = allowedModules

        # Create the base query
        query = Job.query.filter(Job.module.in_(modules)).distinct()

        # Apply filters
        if filter_columns and filter_values:
            for column, value in zip(filter_columns, filter_values):
                query = query.filter(getattr(Job, column).in_(value.split('\x1e')))

        # Apply filters
        if date_from:
            date_from = valid_date(date_from).date()
            query = query.filter(Job.added_on >= date_from)
        if date_to:
            date_to = valid_date(date_to).date() + timedelta(days=1)
            query = query.filter(Job.added_on < date_to)

        # Sorting
        if (sort_column is not None) and (sort_order is not None):
            for order_by, order_type in zip(sort_column, sort_order):
                # check if order_by is valid column
                if order_by not in Job.__table__.columns:
                    raise ValueError(f"Invalid column name: {order_by}")
                query = query.order_by(text(f'{order_by} {order_type}'))

        # continue to sort on added_on descening
        if sort_column and ('added_on' not in sort_column):
            query = query.order_by(Job.added_on.desc())

        # Get total size before pagination
        total_size = query.count() if get_size else None

        # Apply pagination
        if (page is not None) and (page_size is not None):
            offset = page * page_size
            query = query.limit(page_size).offset(offset)

        # Execute query and convert to DataFrame
        jobs_list = [job_db.to_dict() for job_db in query.all()]
        df = pd.DataFrame(jobs_list)

        if columns is not None and df is not None:
            if not df.empty:
                df = df[columns].drop_duplicates()
                total_size = len(df)

        # Convert Timestamp to string
        for dcol in ['added_on', 'end_date', 'executed_on']:
            if dcol in df.columns:
                df[dcol] = df[dcol].astype('str').replace({'NaT': '', 'None': ''})

        if get_size:
            output_json = {'data': df.to_dict(orient='records'), 'total_size': total_size}
        else:
            output_json = df.to_dict(orient='records')

        # audit log
        modules_str = ','.join(map(str, modules))
        log_audit(
            action='Retrieve',
            module='job',
            submodule='',
            previous_data='',
            new_data='',
            description=f'User [$USER] retrieved latest job for [{modules_str}]',
            error_codes='',
            database_involved='jobs'
        )
        return make_response(jsonify(output_json), 200)

    except Exception as e:
        modules_str = ','.join(map(str, modules))
        log_audit(
            action='Retrieve',
            module=modules_str,
            submodule='',
            previous_data='',
            new_data='',
            description=f'User [$USER] failed to retrieve jobs for modules [{modules_str}]. Error: {str(e)}',
            error_codes='500',
            database_involved='jobs'
        )
        return make_response(jsonify({'message': str(e)}), 500)


@job.route('/update/<string:job_id>', methods=['PUT'])
@jwt_required()
@prevent_multiple_logins_per_user()
@validate_request(allowed_keys=['description', 'status', 'active'])
def update_job(job_id):
    """Update job by job_id"""
    try:
        job_id = valid_uuid(job_id)
        job_db = Job.query.filter_by(job_id=job_id).first()

        if not job_db:
            log_audit(
                action='Update',
                module='job',
                submodule='',
                previous_data='',
                new_data='',
                description=f'User [$USER] failed to update job [{job_id}]. Error: Job not found',
                error_codes='404',
                database_involved='jobs',
                job_id=job_id,
                job_judged_by=get_jwt_identity()
            )
            return make_response(jsonify({'message': 'Job not found'}), 404)

        # check roles
        roles_satisfied_module(job_db.module, 'execute', action='Update', submodule=job_db.submodule)

        data = request.get_json()
        description = data.get('description')
        status = data.get('status')
        active = data.get('active')
        previous_data = {}
        new_data = {}

        # deactivate other active jobs with same module and submodule
        if active:
            active_job = Job.query.filter_by(module=job_db.module, submodule=job_db.submodule, active=True).first()
            if active_job:
                active_job.active = False

        if active is not None and active != job_db.active:
            previous_data['active'] = job_db.active
            new_data['active'] = active
            job_db.active = active

        if description and description != job_db.description:
            previous_data['description'] = job_db.description
            new_data['description'] = description
            job_db.description = description

        if status and status != job_db.status:
            previous_data['status'] = job_db.status
            new_data['status'] = status

            # update job history
            description = f'User [{get_jwt_identity()}] updated status for job {job_id}'
            job_hist = JobHistory(job_id, status_from=job_db.status, status_to=status,
                                  action=description, timestamp=datetime.now(timezone.utc))
            db.session.add(job_hist)

            # update job status
            job_db.status = status

        db.session.commit()

        # send notification for number of pending requests
        send_notification('nPendingRequests', len(Job.query.filter_by(status='pending').all()))

        # audit log
        log_audit(
            action='Update',
            module='job',
            submodule='',
            previous_data=json.dumps(previous_data),
            new_data=json.dumps(new_data),
            description=f'User [$USER] updated job {job_id}',
            error_codes='',
            database_involved='jobs, jobHistory' if (status and status != job_db.status) else 'jobs',
            job_id=job_id,
            job_judged_by=get_jwt_identity()
        )
        return make_response(jsonify(job_db.to_dict()), 200)

    except NameError as e:
        db.session.rollback()
        log_audit(
            action='Update',
            module='job',
            submodule='',
            previous_data='',
            new_data='',
            description=f'User [$USER] failed to update job. Job_id is invalid. Error: {str(e)}',
            error_codes='404',
            database_involved='jobs, jobHistory',
        )
        return make_response(jsonify({'message': str(e)}), 404)

    except Exception as e:
        db.session.rollback()
        log_audit(
            action='Update',
            module='job',
            submodule='',
            previous_data=json.dumps(previous_data),
            new_data=json.dumps(new_data),
            description=f'User [$USER] failed to update job {job_id}. Error: {str(e)}',
            error_codes='500',
            database_involved='jobs',
            job_id=job_id,
            job_judged_by=get_jwt_identity()
        )
        return make_response(jsonify({'message': str(e)}), 500)


@job.route('/history/<string:job_id>', methods=['GET'])
@jwt_required()
@prevent_multiple_logins_per_user()
@validate_request()
def get_job_history(job_id):
    """Query job history by job_id"""
    try:
        job_id = valid_uuid(job_id)
        job_db = Job.query.filter_by(job_id=job_id).first()
        if not job_db:
            log_audit(
                action='Retrieve',
                module='job',
                submodule='',
                previous_data='',
                new_data='',
                description=f'User [$USER] failed to retrieve history for job [{job_id}]. Error: Job not found',
                error_codes='404',
                database_involved='jobs'
            )
            return make_response(jsonify({'message': 'Job not found'}), 404)

        # check roles
        roles_satisfied_module(job_db.module, 'read', action='Retrieve', submodule=job_db.submodule)

        # query job history
        job_hist = [hist.to_dict() for hist in JobHistory.query.filter_by(job_id=job_id).all()]

        # audit log
        log_audit(
            action='Retrieve',
            module='job',
            submodule='',
            previous_data='',
            new_data='',
            description=f'User [$USER] retrieved history for job {job_id}',
            error_codes='',
            database_involved='jobs, jobHistory'
        )
        return make_response(jsonify(job_hist), 200)

    except NameError as e:
        log_audit(
            action='Retrieve',
            module='job',
            submodule='',
            previous_data='',
            new_data='',
            description=f'User [$USER] failed to retrieve job. Job_id is invalid. Error: {str(e)}',
            error_codes='404',
            database_involved='jobs, jobHistory',
        )
        return make_response(jsonify({'message': str(e)}), 404)

    except Exception as e:
        log_audit(
            action='Retrieve',
            module='job',
            submodule='',
            previous_data='',
            new_data='',
            description=f'User [$USER] failed to retrieve history for job {job_id}. Error: {str(e)}',
            error_codes='500',
            database_involved='jobs, jobHistory'
        )
        return make_response(jsonify({'message': str(e)}), 500)


@job.route('/data/<string:job_id>/<string:type>/<string:db_name>', methods=['POST'])
@jwt_required()
@prevent_multiple_logins_per_user()
@validate_request(allowed_keys=['columns', 'filter_columns', 'filter_values', 'sort_column', 'sort_order',
                                'page', 'page_size', 'get_names', 'get_size'])
def get_job_data(job_id, type, db_name):
    '''
    columns examples: 'column1,column2'. '*' to get the size
    filter columns examples: 'column1,column2'
    filter values examples: 'value11,value12|value21,value22' (corresponding to filter_columns)
    '''
    try:
        if not job_id or not type:
            raise ValueError('Missing job_id or type')

        job_id = valid_uuid(job_id)

        job_db = Job.query.filter_by(job_id=job_id).first()
        if not job_db:
            log_audit(
                action='Retrieve',
                module='job',
                submodule='',
                previous_data='',
                new_data='',
                description=f'User [$USER] failed to retrieve data of [{db_name}] for job [{job_id}]. Error: Job not found',
                error_codes='404',
                database_involved='jobs'
            )
            return make_response(jsonify({'message': 'Job not found'}), 404)

        module, submodule = job_db.module, job_db.submodule

        data = request.get_json()
        columns_arg = data.get('columns')
        filter_columns = data.get('filter_columns')
        filter_values = data.get('filter_values')
        sort_column = data.get('sort_column')
        sort_order = data.get('sort_order')
        page = data.get('page')
        page_size = data.get('page_size')
        get_names = data.get('get_names', False)
        validate_boolean(get_names)
        get_size = data.get('get_size', False)

        # parse values
        if filter_values is not None:
            filter_values = json.loads(filter_values)

        page = int(page) if page is not None else None
        page_size = int(page_size) if page_size is not None else None
        columns = None if columns_arg in ['undefined', 'null', '', '*', None] else columns_arg.split('\x1e')
        filter_columns = None if filter_columns in ['undefined', 'null', '', None] else filter_columns.split('\x1e')
        filter_values = None if filter_values in ['undefined', 'null', '', None] else filter_values.split('\x1f')
        sort_column = None if sort_column in ['undefined', 'null', '', None] else sort_column.split('\x1e')
        sort_order = None if sort_order in ['undefined', 'null', '', None] else sort_order.split('\x1e')

        results = get_job_data_helper(job_db, type, db_name, columns=columns, filter_columns=filter_columns, filter_values=filter_values,
                                      sort_column=sort_column, sort_order=sort_order, page=page, page_size=page_size, get_size=get_size, get_names=get_names)

        if get_names:
            output_json = results
        else:
            if isinstance(results, dict):
                if get_size:
                    output_json = {key: {'data': toJSON(df), 'total_size': total_size} for key, (df, total_size) in results.items() if df is not None}
                else:
                    output_json = {key: toJSON(df) for key, df in results.items() if df is not None}
            else:
                if get_size:
                    output_json = {'data': toJSON(results[0]), 'total_size': results[1]} if results is not None else None
                else:
                    output_json = toJSON(results) if results is not None else None

        # audit log
        log_audit(
            action='Retrieve',
            module=module,
            submodule=submodule,
            previous_data='',
            new_data='',
            description=f'User [$USER] retrieved data of [{db_name}] for job [{job_id}]',
            error_codes='',
            database_involved='jobs'
        )
        return make_response(jsonify(output_json), 200)
    except NameError as e:
        log_audit(
            action='Retrieve',
            module='job',
            submodule='',
            previous_data='',
            new_data='',
            description=f'User [$USER] failed to retrieve job. Job_id is invalid. Error: {str(e)}',
            error_codes='404',
            database_involved='jobs, jobHistory',
        )
        return make_response(jsonify({'message': str(e)}), 404)

    except TypeError as e:
        log_audit(
            action='Retrieve',
            module='job',
            submodule='',
            previous_data='',
            new_data='',
            description=f'User [$USER] failed to retrieve job. Input type is invalid. Error: {str(e)}',
            error_codes='404',
            database_involved='jobs, jobHistory',
        )
        return make_response(jsonify({'message': str(e)}), 400)

    except ValueError as e:
        log_audit(
            action='Retrieve',
            module='job',
            submodule='',
            previous_data='',
            new_data='',
            description=f'User [$USER] failed to retrieve data of [{db_name}] for job [{job_id}]. Error: {str(e)}',
            error_codes='400',
            database_involved='jobs'
        )
        return make_response(jsonify({'message': str(e)}), 400)
    except Exception as e:
        log_audit(
            action='Retrieve',
            module='job',
            submodule='',
            previous_data='',
            new_data='',
            description=f'User [$USER] failed to retrieve data of [{db_name}] for job [{job_id}]. Error: {str(e)}',
            error_codes='500',
            database_involved='jobs'
        )
        return make_response(jsonify({'message': str(e)}), 500)
