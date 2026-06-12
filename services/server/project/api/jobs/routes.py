from flask import Blueprint, jsonify, make_response, request, current_app
from flask_jwt_extended import jwt_required, get_jwt_identity
from datetime import datetime, timezone
from sqlalchemy import text
from celery.result import AsyncResult
from werkzeug.exceptions import Forbidden, NotFound
import uuid
import os

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
from project.workers.tasks import save_input_task, calculate_task


job = Blueprint('job', __name__)
logger = get_logger(__name__)


@job.route('/add', methods=['POST'], endpoint='add_job')
@jwt_required()
@prevent_multiple_logins_per_user()
@validate_request(allowed_keys=['email', 'module', 'submodule', 'input', 'inputPath', 'dbName'])
def add():
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
        if not email or not module:
            raise ValueError('Missing email or module fields')
        user = User.query.filter_by(email=email).first()
        if not user:
            raise ValueError("Invalid user ID")

        roles_satisfied_module(module, 'execute', action='Enqueue', submodule=submodule)

        job_timeout = int(os.getenv('REDIS_JOB_TIMEOUT', 86400))
        data_job_id = str(uuid.uuid4())

        result = save_input_task.apply_async(
            args=[input, inputPath, job_id, module, submodule, dbName],
            task_id=data_job_id,
            soft_time_limit=job_timeout,
            time_limit=job_timeout + 60,
            kwargs={'job_id': job_id, 'email': email, 'module': module, 'submodule': submodule, 'description': description}
        )

        job_db = Job(job_id, email, module, job_data_id=data_job_id, submodule=submodule, status="created", input="",
                     description=description, added_on=datetime.now(timezone.utc))
        job_hist = JobHistory(job_id, status_from='', status_to="created", action=description, timestamp=datetime.now(timezone.utc))
        db.session.add(job_hist)
        db.session.add(job_db)
        db.session.commit()
        send_notification('nPendingRequests', len(Job.query.filter(Job.status.in_(["pending", "created"])).all()))

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
        log_audit(action='Enqueue', module=module, submodule=submodule, previous_data='', new_data='',
                  description=f'User [$USER] failed to add job. Error: {str(e)}', error_codes='400', database_involved='')
        logger.exception(e)
        return make_response(jsonify({'message': str(e)}), 400)

    except Forbidden as e:
        db.session.rollback()
        log_audit(action='Enqueue', module=module, submodule=submodule, previous_data='', new_data='',
                  description=f'User [$USER] failed to add job. Error: {str(e)}', error_codes='403', database_involved='')
        logger.exception(e)
        return make_response(jsonify({'message': str(e)}), 403)

    except Exception as e:
        db.session.rollback()
        log_audit(action='Enqueue', module=module, submodule=submodule, previous_data='', new_data='',
                  description=f'User [$USER] failed to add job. Error: {str(e)}', error_codes='500', database_involved='')
        logger.exception(e)
        return make_response(jsonify({'message': str(e)}), 500)


@job.route('/run/<string:job_id>', methods=['POST'], endpoint='run_job')
@jwt_required()
@prevent_multiple_logins_per_user()
@validate_request()
def run(job_id):
    job_timeout = int(os.getenv('REDIS_JOB_TIMEOUT', 60 * 60 * 24))

    try:
        job_id = valid_uuid(job_id)
        job_db = Job.query.filter_by(job_id=job_id).first()
        if not job_db:
            log_audit(action='Compute', module='job', submodule='', previous_data='', new_data='',
                      description=f'User [$USER] failed to compute job [{job_id}]. Error: Job not found',
                      error_codes='404', database_involved='jobs')
            return make_response(jsonify({'message': 'Job not found'}), 404)

        roles_satisfied_module(job_db.module, 'write', action='Compute', submodule=job_db.submodule)

        calculate_task.apply_async(
            args=[job_db.to_dict()],
            task_id=job_id,
            soft_time_limit=job_timeout,
            time_limit=job_timeout + 60
        )

        update_job_status(job_db, 'queued')
        job_db.active = False
        job_db.progress = 0
        job_db.end_date = None
        db.session.commit()

        send_notification('nPendingRequests', len(Job.query.filter_by(status='pending').all()))

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
        log_audit(action='Compute', module=job_db.module, submodule=job_db.submodule, previous_data='', new_data='',
                  description=f'User [$USER] failed to start job [{job_db.job_id}]. Error: {str(e)}',
                  error_codes='400', database_involved='jobs, jobHistory', job_id=job_id, job_judged_by=get_jwt_identity())
        logger.exception(e)
        return make_response(jsonify({'message': str(e)}), 400)

    except NameError as e:
        db.session.rollback()
        update_job_status(job_db, 'failed')
        log_audit(action='Compute', module='job', submodule='', previous_data='', new_data='',
                  description=f'User [$USER] failed to start job. Job_id is invalid. Error: {str(e)}',
                  error_codes='404', database_involved='jobs, jobHistory')
        logger.exception(e)
        return make_response(jsonify({'message': str(e)}), 404)

    except Forbidden as e:
        db.session.rollback()
        update_job_status(job_db, 'failed')
        log_audit(action='Compute', module=job_db.module, submodule=job_db.submodule, previous_data='', new_data='',
                  description=f'User [$USER] failed to start job [{job_db.job_id}]. Error: {str(e)}',
                  error_codes='403', database_involved='jobs, jobHistory', job_id=job_id, job_judged_by=get_jwt_identity())
        logger.exception(e)
        return make_response(jsonify({'message': str(e)}), 403)

    except Exception as e:
        db.session.rollback()
        update_job_status(job_db, 'failed')
        log_audit(action='Compute', module=job_db.module, submodule=job_db.submodule, previous_data='', new_data='',
                  description=f'User [$USER] failed to start job [{job_db.job_id}]. Error: {str(e)}',
                  error_codes='500', database_involved='jobs, jobHistory', job_id=job_id, job_judged_by=get_jwt_identity())
        logger.exception(e)
        return make_response(jsonify({'message': str(e)}), 500)

    finally:
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
        job_db = Job.query.filter_by(job_id=job_id).first()
        if not job_db:
            log_audit(action='Cancel', module='job', submodule='', previous_data='', new_data='',
                      description=f'User [$USER] failed to cancel job [{job_id}]. Error: Job not found',
                      error_codes='404', database_involved='jobs', job_id=job_id, job_judged_by=get_jwt_identity())
            return make_response(jsonify({'message': 'Job not found'}), 404)

        roles_satisfied_module(job_db.module, 'write', action='Cancel', submodule=job_db.submodule)

        celery_task_id = job_db.job_data_id if job_db.status == 'created' else job_id
        result = AsyncResult(celery_task_id)
        result.revoke(terminate=True, signal='SIGTERM')

        clear_job_data_from_app_db(job_db.module, job_db.submodule, type='output', db_name=None, job_id=job_db.job_id)

        update_job_status(job_db, 'canceled')
        job_db.active = False
        db.session.commit()

        send_notification('nPendingRequests', len(Job.query.filter_by(status='pending').all()))

        log_audit(action='Cancel', module=job_db.module, submodule=job_db.submodule, previous_data='', new_data='',
                  description=f'User [$USER] canceled job [{job_id}]', error_codes='',
                  database_involved='jobs, jobHistory', job_id=job_id, job_judged_by=get_jwt_identity())
        return make_response(jsonify({'message': 'Job canceled successfully', 'job_id': job_id}), 200)

    except NameError as e:
        db.session.rollback()
        log_audit(action='Cancel', module='job', submodule='', previous_data='', new_data='',
                  description=f'User [$USER] failed to cancel job. Job_id is invalid. Error: {str(e)}',
                  error_codes='404', database_involved='jobs, jobHistory')
        return make_response(jsonify({'message': str(e)}), 404)

    except Exception as e:
        db.session.rollback()
        log_audit(action='Cancel', module=job_db.module, submodule=job_db.submodule, previous_data='', new_data='',
                  description=f'User [$USER] failed to cancel job [{job_id}]. Error: {str(e)}',
                  error_codes='500', database_involved='jobs', job_id=job_id, job_judged_by=get_jwt_identity())
        return make_response(jsonify({'message': str(e)}), 500)


@job.route('/delete/<string:job_id>', methods=['DELETE'], endpoint='delete_job')
@jwt_required()
@prevent_multiple_logins_per_user()
@validate_request()
def delete(job_id):
    try:
        job_id = valid_uuid(job_id)
        job_db = Job.query.filter_by(job_id=job_id).first()
        if not job_db:
            log_audit(action='Delete', module='job', submodule='', previous_data='', new_data='',
                      description=f'User [$USER] failed to delete job [{job_id}]. Error: Job not found',
                      error_codes='404', database_involved='jobs', job_id=job_id, job_judged_by=get_jwt_identity())
            return make_response(jsonify({'message': 'Job not found'}), 404)

        roles_satisfied_module(job_db.module, 'execute', action='Delete', submodule=job_db.submodule)

        celery_task_id = job_db.job_data_id if job_db.status == 'created' else job_id
        result = AsyncResult(celery_task_id)
        if result.state not in ('SUCCESS', 'FAILURE', 'REVOKED'):
            raise Exception(f"Cannot delete job in state: {result.state}")
        result.forget()

        clear_job_data_from_app_db(job_db.module, job_db.submodule, type='input',  db_name=None, job_id=job_db.job_id)
        clear_job_data_from_app_db(job_db.module, job_db.submodule, type='output', db_name=None, job_id=job_db.job_id)
        sftp_cleanup_dir(os.path.join(DATA_STORE, get_job_dir(job_db.job_id, job_db.module, job_db.submodule, '')))
        db.session.delete(job_db)
        db.session.commit()

        send_notification('nPendingRequests', len(Job.query.filter_by(status='pending').all()))

        log_audit(action='Delete', module=job_db.module, submodule=job_db.submodule, previous_data='', new_data='',
                  description=f'User [$USER] deleted job [{job_id}]', error_codes='',
                  database_involved='jobs, jobHistory', job_id=job_id, job_judged_by=get_jwt_identity())
        return make_response(jsonify({'message': 'Job deleted'}), 200)

    except NameError as e:
        db.session.rollback()
        log_audit(action='Delete', module='job', submodule='', previous_data='', new_data='',
                  description=f'User [$USER] failed to delete job. Job_id is invalid. Error: {str(e)}',
                  error_codes='404', database_involved='jobs, jobHistory')
        return make_response(jsonify({'message': str(e)}), 404)

    except Exception as e:
        db.session.rollback()
        log_audit(action='Delete', module=job_db.module, submodule=job_db.submodule, previous_data='', new_data='',
                  description=f'User [$USER] failed to delete job [{job_id}]. Error: {str(e)}',
                  error_codes='500', database_involved='jobs', job_id=job_id, job_judged_by=get_jwt_identity())
        return make_response(jsonify({'message': str(e)}), 500)


@job.route('/get_status/<string:job_id>', methods=['PUT'], endpoint='get_job_status')
@jwt_required()
@prevent_multiple_logins_per_user()
@validate_request()
def get_status(job_id):
    try:
        job_id = valid_uuid(job_id)
        job_db = Job.query.filter_by(job_id=job_id).first()
        if not job_db:
            raise NotFound('Job not found')

        roles_satisfied_module(job_db.module, 'read', action='Retrieve', submodule=job_db.submodule)

        celery_task_id = job_db.job_data_id if job_db.status == 'created' else job_id
        result = AsyncResult(celery_task_id)

        # Map Celery states to the app's status vocabulary
        state_map = {
            'PENDING':  'queued',
            'STARTED':  'started',
            'SUCCESS':  'finished',
            'FAILURE':  'failed',
            'REVOKED':  'canceled',
        }
        celery_state = state_map.get(result.state, result.state.lower())

        if job_db.status in ('started', 'queued') and job_db.status != celery_state:
            job_hist = JobHistory(job_id, status_from=job_db.status, status_to=celery_state,
                                  action='Automated routing', timestamp=datetime.now(timezone.utc))
            db.session.add(job_hist)
            job_db.status = celery_state

        if isinstance(result.info, dict):
            job_db.progress = result.info.get('progress', job_db.progress)

        db.session.commit()

        log_audit(action='Retrieve', module=job_db.module, submodule=job_db.submodule, previous_data='', new_data='',
                  description=f'User [$USER] retrieved status for job [{job_id}]', error_codes='',
                  database_involved='jobs, jobHistory')
        return {'job': job_db.to_dict()}, 200

    except NotFound as e:
        db.session.rollback()
        log_audit(action='Retrieve', module='job', submodule='', previous_data='', new_data='',
                  description=f'User [$USER] failed to retrieve status for job [{job_id}]. Error: {str(e)}',
                  error_codes='404', database_involved='jobs, jobHistory')
        return make_response(jsonify({'message': str(e)}), 404)

    except NameError as e:
        db.session.rollback()
        log_audit(action='Retrieve', module='job', submodule='', previous_data='', new_data='',
                  description=f'User [$USER] failed to retrieve status for job [{job_id}]. Error: {str(e)}',
                  error_codes='404', database_involved='jobs, jobHistory')
        return make_response(jsonify({'message': str(e)}), 404)

    except Exception as e:
        db.session.rollback()
        log_audit(action='Retrieve', module=job_db.module, submodule=job_db.submodule, previous_data='', new_data='',
                  description=f'User [$USER] failed to retrieve status for job [{job_id}]. Error: {str(e)}',
                  error_codes='500', database_involved='jobs')
        return make_response(jsonify({'message': str(e)}), 500)


# ========================= CRUD ==========================
@job.route('/all', methods=['GET'])
@jwt_required()
@prevent_multiple_logins_per_user()
@validate_request()
def get_all_jobs():
    roles_required(*roleSettings.getRoles('job', 'read'), action='Retrieve', module='job', submodule='')
    jobs_list = [job_db.to_dict() for job_db in Job.query.all()]
    log_audit(action='Retrieve', module='job', submodule='', previous_data='', new_data='',
              description=f'User [$USER] retrieved the all jobs', error_codes='', database_involved='jobs')
    return make_response(jsonify(jobs_list), 200)


@job.route('/id/<string:job_id>', methods=['GET'])
@jwt_required()
@prevent_multiple_logins_per_user()
@validate_request()
def get_job_by_id(job_id):
    try:
        job_id = valid_uuid(job_id)
        job_db = Job.query.filter_by(job_id=job_id).first()
        if not job_db:
            log_audit(action='Retrieve', module='job', submodule='', previous_data='', new_data='',
                      description=f'User [$USER] failed to retrieve job [{job_id}]. Error: Job not found',
                      error_codes='404', database_involved='jobs')
            return make_response(jsonify({'message': 'Job not found'}), 404)

        roles_satisfied_module(job_db.module, 'read', action='Retrieve', submodule=job_db.submodule)

        log_audit(action='Retrieve', module='job', submodule='', previous_data='', new_data='',
                  description=f'User [$USER] retrieved job [{job_id}]', error_codes='', database_involved='jobs')
        return make_response(jsonify(job_db.to_dict()), 200)

    except NameError as e:
        log_audit(action='Retrieve', module='job', submodule='', previous_data='', new_data='',
                  description=f'User [$USER] failed to retrieve job. Job_id is invalid. Error: {str(e)}',
                  error_codes='404', database_involved='jobs, jobHistory')
        return make_response(jsonify({'message': str(e)}), 404)

    except Exception as e:
        log_audit(action='Retrieve', module='job', submodule='', previous_data='', new_data='',
                  description=f'User [$USER] failed to retrieve job [{job_id}]. Error: {str(e)}',
                  error_codes='500', database_involved='jobs')
        return make_response(jsonify({'message': str(e)}), 500)


@job.route('/current', methods=['GET'], endpoint='get_current_jobs')
@jwt_required()
@prevent_multiple_logins_per_user()
@validate_request()
def get_current_jobs():
    roles_required(*roleSettings.getRoles('*', 'execute'), action='Retrieve', module='job', submodule='')
    jobs_list = [job_db.to_dict() for job_db in Job.query.filter_by(email=get_jwt_identity()).all()]
    log_audit(action='Retrieve', module='job', submodule='', previous_data='', new_data='',
              description=f'User [$USER] retrieved all his/her jobs', error_codes='', database_involved='jobs')
    return make_response(jsonify(jobs_list), 200)


@job.route('/latest', methods=['POST'], endpoint='get_latest_job')
@jwt_required()
@prevent_multiple_logins_per_user()
@validate_request(allowed_keys=['email', 'module', 'submodule'])
def get_latest_job():
    try:
        data = request.get_json()
        email = data.get('email')
        module = data.get('module')
        submodule = data.get('submodule')

        roles_satisfied_module(module, 'read', action='Retrieve', submodule=submodule)

        email    = None if email    in ["undefined", "null", None] else email
        module   = None if module   in ["undefined", "null", None] else module
        submodule = None if submodule in ["undefined", "null", None] else submodule

        filters = [Job.status == 'finished', Job.active == True]
        if email:    filters.append(Job.email    == email)
        if module:   filters.append(Job.module   == module)
        if submodule: filters.append(Job.submodule == submodule)

        job_db = Job.query.filter(*filters).order_by(Job.end_date.desc()).first()
        data = job_db.to_dict() if job_db else None

        log_audit(action='Retrieve', module=module or '', submodule=submodule or '', previous_data='', new_data='',
                  description=f'User [$USER] retrieved latest job for {module}-{submodule}',
                  error_codes='', database_involved='jobs')
        return make_response(jsonify(data), 200)

    except Exception as e:
        log_audit(action='Retrieve', module='job', submodule='', previous_data='', new_data='',
                  description=f'User [$USER] failed to retrieve latest job. Error: {str(e)}',
                  error_codes='500', database_involved='jobs')
        return make_response(jsonify({'message': str(e)}), 500)
