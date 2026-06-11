import os
import json
import uuid
import pandas as pd
import numpy as np
import pyarrow.parquet as pq
from datetime import datetime, timezone
from flask import current_app
from flask_jwt_extended import get_jwt_identity
from werkzeug.exceptions import Conflict, NotFound

from project import db, DATA_STORE
from project.api.jobs.models import *
from project.api.auditlog.models import log_audit
from project.sftp import sftp_get, sftp_listdir, sftp_put_from_db
from project.db_models.job_models import save_job_to_app_db, load_job_from_app_db
from project.db_models.job_models.config import APP_DB_MODELS
from project.logger import get_logger


logger = get_logger(__name__)


def load_staging_by_module(module, submodule, **kwargs):
    if module not in APP_DB_MODELS:
        raise ValueError(f'No data found for {module}')
    if submodule not in APP_DB_MODELS[module]:
        raise ValueError(f'No data found for {module}-{submodule}')

    dfs = {}
    dbName = kwargs.get('dbName', None)
    if dbName:
        if isinstance(dbName, str):
            dbs = dbName.split('\x1e')
        elif isinstance(dbName, list):
            dbs = dbName
        else:
            raise ValueError('Invalid dbName type')
    else:
        dbs = list(APP_DB_MODELS[module][submodule]['input'].keys())

    for db in dbs:
        if db not in APP_DB_MODELS[module][submodule]['input']:
            raise ValueError(f'No data found for {module}-{submodule}-{db}')
        func = APP_DB_MODELS[module][submodule]['input'][db]
        if isinstance(func, tuple):
            # if the function returns a tuple, unpack it
            func_module, func_submodule, fun_type, fun_db_name, columns = func
            kwargs_with_columns = kwargs.copy()
            kwargs_with_columns['columns'] = columns
            res = get_latest_job_data_by_module(func_module, func_submodule, fun_type, fun_db_name, **kwargs_with_columns)
        elif callable(func):
            res = func(**kwargs)
        else:
            raise ValueError(f'Invalid function for {module}-{submodule}-{db}')
        dfs[db] = res

    return dfs


def get_latest_job_data_by_module(module, submodule, type, db_name, **kwargs):
    # Build the filter criteria dynamically
    filters = [Job.status == 'finished', Job.active == True]
    if module:
        filters.append(Job.module == module)
    if submodule:
        filters.append(Job.submodule == submodule)

    job_id = kwargs.get('job_id', None)
    if job_id:
        filters.append(Job.job_id == job_id)

    # Apply the filters to the query
    job_db = Job.query.filter(*filters).order_by(Job.end_date.desc()).first()

    if job_db is None:
        return None

    get_job_id = kwargs.get('get_job_id', False)
    if get_job_id:
        return get_job_data_helper(job_db, type, db_name, **kwargs), job_db.job_id

    return get_job_data_helper(job_db, type, db_name, **kwargs)


def get_job_data_helper(job_db, type, db_name, **kwargs):
    if job_db is None:
        return None

    table_names = get_file_names(job_db, type)
    get_names = kwargs.get('get_names', False)
    get_size = kwargs.get('get_size', False)

    if get_names:
        output = json.dumps(table_names) if table_names else None
    else:
        if db_name in ['undefined', 'null', '', None]:
            results = load_from_db(job_db, type, table_names, **kwargs)
            if results is None:
                return None
            else:
                if get_size:
                    output = {key: (df, total_size) for key, (df, total_size) in results.items() if df is not None}
                else:
                    output = {key: df for key, df in results.items() if df is not None}

        elif isinstance(db_name, list) or (isinstance(db_name, str) and ('\x1e' in db_name)):
            db_name = db_name if isinstance(db_name, list) else db_name.split('\x1e')
            results = load_from_db(job_db, type, db_name, **kwargs)
            if results is None:
                return None
            else:
                if get_size:
                    output = {key: (df, total_size) for key, (df, total_size) in results.items() if df is not None}
                else:
                    output = {key: df for key, df in results.items() if df is not None}

        else:
            output = load_from_db(job_db, type, db_name, **kwargs)

    return output


def save_input(input, inputPath, job_id, module, submodule, dbName):
    try:
        with current_app.app_context():
            input_dir = ''

            if inputPath:
                input_dir = get_job_dir(job_id, module, submodule, 'input')
                save_staging_input(job_id, input_dir, module, submodule, dbName, inputPath=inputPath)
            else:
                if input:  # i.e user upload
                    dfs = read_and_parse_dataframes(input)  # input is passed as JSON
                    input_dir = get_job_dir(job_id, module, submodule, 'input')
                    input_db_full = os.path.join(DATA_STORE, input_dir)
                    save_output(dfs, job_id, input_db_full, module, submodule, db_type='input', json=False)

            return input_dir
    except Exception as e:
        raise Exception(f'Failed to save input data. Error: {str(e)}')


def get_job_dir(job_id, module, submodule, type):
    date = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    # job_dir = os.path.join(DATA_STORE, date, module, submodule, job_id, type)
    job_dir = os.path.join(date, module, submodule, job_id, type)
    return job_dir


def save_staging_input(job_id, job_dir, module, submodule, dbName, inputPath='staging'):
    logger.debug(f'Saving staging data to db')
    try:
        dfs = {}
        if inputPath == 'staging':
            dfs = load_staging_by_module(module, submodule, dbName=dbName)
        else:
            dfs = get_latest_job_data_by_module(module, submodule, 'input', db_name=None)

        if dfs is None:
            raise Exception(f'No data found for {module}-{submodule}')

        if len(dfs) == 0:
            raise Exception(f'No data found for {module}-{submodule}')

        for name, df in dfs.items():
            df = dfs.get(name, pd.DataFrame())
            df = pd.DataFrame() if df is None else df

            # Convert mixed-type columns to strings
            if not df.empty:
                for col in df.columns:
                    if df[col].apply(type).nunique() > 1:
                        df[col] = df[col].astype(str)

            # check if input_db_full exists
            file_dir = os.path.join(DATA_STORE, job_dir)

            # Save to database
            logger.debug(f"Saving input {name} to database for job {job_id}")
            save_job_to_app_db(df, module, submodule, 'input', name, job_id)

            # Save to SFTP
            logger.debug(f"Starting batch SFTP transfer for input {name}")
            sftp_put_from_db(
                module=module,
                submodule=submodule,
                db_type='input',
                db_name=name,
                job_id=job_id,
                file_dir=file_dir,
                file_name=name,
                extensions=['parquet', 'csv', 'xlsx']
            )
    except Exception as e:
        raise e


def save_output(data, job_id, job_dir, module, submodule, db_type='output', json=True):
    try:
        if data is not None:
            if json:
                data = read_and_parse_dataframes(data)
            dataframes = flatten_dict(data)

            for db_name, df in dataframes.items():
                df = clean_dataframe(df)

                # Save to database
                logger.debug(f"Saving {db_name} to database for job {job_id}")
                save_job_to_app_db(df, module, submodule, db_type, db_name, job_id)

        # Save to SFTP
        if not APP_DB_MODELS.get(module, {}).get(submodule, {}).get(db_type, None):
            raise ValueError(f"No output data found for job {job_id} in {module}-{submodule}-{db_type}")

        for db_name, _ in APP_DB_MODELS[module][submodule][db_type].items():
            logger.debug(f"Starting batch SFTP transfer for {db_name}")
            sftp_put_from_db(
                module=module,
                submodule=submodule,
                db_type=db_type,
                db_name=db_name,
                job_id=job_id,
                file_dir=job_dir,
                file_name=db_name,
                extensions=['csv', 'xlsx']
            )
    except Exception as e:
        raise e


def load_single_from_db(module, submodule, type, db_name, job_id, **kwargs):
    '''
    page is 0-indexed
    '''
    try:
        df = load_job_from_app_db(module, submodule, type, db_name, job_id=job_id, **kwargs)
    except ValueError as e:
        raise e
    except Exception as e:
        raise Exception(f'Failed to load data from db. Error: {str(e)}')
    return df


def load_single_from_sftp(job_dir, db_name, **kwargs):
    '''
    page is 0-indexed
    '''
    try:
        columns = kwargs.get('columns', None)
        filter_columns = kwargs.get('filter_columns', None)
        filter_values = kwargs.get('filter_values', None)
        page = kwargs.get('page', None)
        page_size = kwargs.get('page_size', None)

        # need to make job path unique
        token = str(uuid.uuid4())
        filename = f'{db_name}.parquet'
        local_path = os.path.join(job_dir, token, filename)

        # retrieve file from SFTP then read
        sftp_get(job_dir, filename, local_path)

        # check if file is empty
        if columns is not None:
            parquet_file = pq.ParquetFile(local_path)
            avail_columns = [c for c in columns if c in parquet_file.schema.names]
            if len(avail_columns) == 0:
                return None
        else:
            avail_columns = columns

        df = pd.read_parquet(local_path, engine='pyarrow', columns=avail_columns).drop_duplicates()
        os.remove(local_path)

        # apply filters
        if filter_columns and filter_values:
            for col, val in zip(filter_columns, filter_values):
                df = df[df[col].isin(val.split('\x1e'))].copy()

        if (page is not None) and (page_size is not None):
            start = page * page_size
            end = start + page_size
            df = df.iloc[start:end].copy()
    except FileNotFoundError:
        return None
    except Exception as e:
        raise Exception(f'Failed to load data from SFTP. Error: {str(e)}')
    return df


def get_file_names(job_db, type):
    job_dir = job_db.input if type == 'input' else job_db.output
    job_dir = os.path.join(DATA_STORE, job_dir)
    return [f.split('.')[0] for f in sftp_listdir(job_dir) if f.endswith('.csv')]
    # if type == 'input' or (type == 'output' and job_db.output):
    #     return list(APP_DB_MODELS[job_db.module][job_db.submodule][type].keys())
    # return []


def load_from_db(job_db, type, db_name=None, **kwargs):
    try:
        module, submodule, job_id = job_db.module, job_db.submodule, job_db.job_id
        job_dir = job_db.input if type == 'input' else job_db.output
        job_dir = os.path.join(DATA_STORE, job_dir)
        kwargs.pop('job_id', None)

        if isinstance(db_name, str):
            return load_single_from_db(module, submodule, type, db_name, job_id=job_id, **kwargs)

        if isinstance(db_name, list):
            db_list = db_name
        elif db_name is None:
            db_list = get_file_names(job_db, type)
        else:
            raise Exception('Invalid db_name type')

        dfs = {}
        for name in db_list:
            dfs[name] = load_single_from_db(module, submodule, type, name, job_id=job_id, **kwargs)
        return dfs

    except ValueError as e:
        raise e
    except Exception as e:
        raise e


def read_and_parse_dataframes(json_obj):
    """
    Recursively parses a nested JSON object and converts JSON-encoded DataFrames
    into pandas DataFrames.
    """
    logger.debug('Parsing JSON input to dataframes')
    if isinstance(json_obj, str):
        try:
            json_obj = json.loads(json_obj)
        except json.JSONDecodeError:
            return json_obj  # Not a JSON string, return it as-is

    if isinstance(json_obj, dict):
        # Recursively parse dictionaries
        return {key: read_and_parse_dataframes(value) for key, value in json_obj.items()}

    # JSON-like string representing DataFrame
    if isinstance(json_obj, list):
        try:
            return pd.DataFrame(json_obj)
        except ValueError:
            return json_obj  # If not convertible to DataFrame, return the list as-is

    return json_obj


def flatten_dict(d, parent_key='', sep='_'):
    logger.debug('Flattening dataframes dictionary')
    items = []
    for k, v in d.items():
        new_key = f"{parent_key}{sep}{k}" if parent_key else k
        if isinstance(v, dict):
            items.extend(flatten_dict(v, new_key, sep=sep).items())
        else:
            items.append((new_key, v))
    return dict(items)


def save_job_output(job_id, module, submodule, result):
    """Save job output to the database and SFTP."""
    outputpath = get_job_dir(job_id, module, submodule, 'output')
    # remove the first "/" because it is misunderstood as root by code scan
    if outputpath.startswith("/"):
        outputpath = outputpath[1:]

    logger.debug(f'Job [{job_id}] completed successfully. Saving output to {outputpath}')
    outputfull = os.path.join(DATA_STORE, outputpath)
    save_output(result, job_id, outputfull, module, submodule, db_type='output', json=False)
    return outputpath


def report_success(job, connection, result, *args, **kwargs):
    # query job details
    job_id = job.get_id()
    job_db = Job.query.filter_by(job_id=job_id).first()

    if not job_db:
        raise NotFound(f'Job {job_id} not found')

    module = job_db.module
    submodule = job_db.submodule

    try:
        # Save job output to db and SFTP
        outputpath = save_job_output(job_id, module, submodule, result)

        # update job history
        job_hist = JobHistory(job_id, status_from=job_db.status, status_to='finished',
                              action=f'Automated routing', timestamp=datetime.now(timezone.utc))
        db.session.add(job_hist)

        # disable current active job
        active_job = Job.query.filter_by(module=module, submodule=submodule, active=True).first()
        if active_job:
            active_job.active = False

        # update job details
        job_db = Job.query.filter_by(job_id=job_id).first()
        job_db.status = 'finished'
        job_db.progress = 100
        job_db.end_date = datetime.now(timezone.utc)
        job_db.active = True
        job_db.output = outputpath
        db.session.commit()

        # ensure there is only 1 active job per module and submodule
        active = Job.query.filter_by(module=module, submodule=submodule, active=True).all()
        if len(active) > 1:
            raise Exception(f'Multiple active jobs found for {module}-{submodule}')
        if len(active) == 0:
            raise Exception(f'No active jobs found for {module}-{submodule}')

        # audit log
        log_audit(
            action='Compute',
            user_email=job_db.executed_by,
            module=module,
            submodule=submodule,
            previous_data='',
            new_data='',
            description=f'Job [{job_db.job_id}] completed',
            error_codes='',
            database_involved='jobs, jobHistory',
            device_info='Automated routing',
            ip_address='Automated routing',
            api_endpoints='Automated routing'
        )
    except Exception as e:
        db.session.rollback()
        log_audit(
            action='Compute',
            user_email=job_db.executed_by,
            module=module,
            submodule=submodule,
            previous_data='',
            new_data='',
            description=f'Job [{job_db.job_id}] failed with error: {str(e)}',
            error_codes='500',
            database_involved='jobs, jobHistory',
            device_info='Automated routing',
            ip_address='Automated routing',
            api_endpoints='Automated routing'
        )
        logger.exception(e)
        raise e
    return


def report_failure(job, connection, type, value, traceback, *args, **kwargs):
    # query job details
    job_id = job.get_id()
    job_db = Job.query.filter_by(job_id=job_id).first()

    if not job_db:
        raise NotFound(f'Job {job_id} not found')

    try:
        # update job history
        job_hist = JobHistory(job_id, status_from=job_db.status, status_to='failed',
                              action=f'Automated routing', timestamp=datetime.now(timezone.utc), error_message=str(value))
        db.session.add(job_hist)

        # update job details
        job_db.status = 'failed'
        job_db.progress = 100
        job_db.end_date = datetime.now(timezone.utc)
        db.session.commit()

        # audit log
        log_audit(
            action='Compute',
            user_email=job_db.executed_by,
            module=job_db.module,
            submodule=job_db.submodule,
            previous_data='',
            new_data='',
            description=f'Job [{job_db.job_id}] failed with error: {value}',
            error_codes='500',
            database_involved='jobs, jobHistory',
            device_info='Automated routing',
            ip_address='Automated routing',
            api_endpoints='Automated routing'
        )
    except Exception as e:
        db.session.rollback()
        log_audit(
            action='Compute',
            user_email=job_db.executed_by,
            module=job_db.module,
            submodule=job_db.submodule,
            previous_data='',
            new_data='',
            description=f'Job [{job_db.job_id}] failed with error: {str(e)}',
            error_codes='500',
            database_involved='jobs, jobHistory',
            device_info='Automated routing',
            ip_address='Automated routing',
            api_endpoints='Automated routing'
        )
        logger.exception(e)
        raise e
    return


def add_job_success(job, connection, result, *args, **kwargs):
    # parse parameters
    input_dir = result
    status = "pending"
    job_id = job.meta.get('job_id')
    email = job.meta.get('email')
    module = job.meta.get('module')
    submodule = job.meta.get('submodule')
    description = job.meta.get('description')

    try:
        job_db = Job.query.filter_by(job_id=job_id).first()
        if not job_db:
            raise NotFound(f'Job {job_id} not found')

        # update job details and job history
        status_from = job_db.status
        job_db.status = status
        job_db.input = input_dir
        job_hist = JobHistory(job_id, status_from=status_from, status_to=status, action=description, timestamp=datetime.now(timezone.utc))
        db.session.add(job_hist)
        db.session.commit()

        log_audit(
            action='Enqueue',
            user_email=email,
            module=module,
            submodule=submodule,
            previous_data='',
            new_data='',
            description=f'User [$USER] added new job {job_id}',
            error_codes='',
            database_involved='jobs, jobHistory',
            device_info='Automated routing',
            ip_address='Automated routing',
            api_endpoints='Automated routing'
        )
    except NotFound as e:
        db.session.rollback()
        log_audit(
            action='Enqueue',
            user_email=email,
            module=module,
            submodule=submodule,
            previous_data='',
            new_data='',
            description=f'User [$USER] failed to add job. Error: {str(e)}',
            error_codes='404',
            database_involved='jobs, jobHistory',
            device_info='Automated routing',
            ip_address='Automated routing',
            api_endpoints='Automated routing'
        )
        logger.exception(e)
        raise e
    except Conflict as e:
        db.session.rollback()
        log_audit(
            action='Enqueue',
            user_email=email,
            module=module,
            submodule=submodule,
            previous_data='',
            new_data='',
            description=f'User [$USER] failed to add job. Error: {str(e)}',
            error_codes='403',
            database_involved='jobs, jobHistory',
            device_info='Automated routing',
            ip_address='Automated routing',
            api_endpoints='Automated routing'
        )
        logger.exception(e)
        raise e
    except Exception as e:
        db.session.rollback()
        log_audit(
            action='Enqueue',
            user_email=email,
            module=module,
            submodule=submodule,
            previous_data='',
            new_data='',
            description=f'User [$USER] failed to add job. Error: {str(e)}',
            error_codes='500',
            database_involved='jobs, jobHistory',
            device_info='Automated routing',
            ip_address='Automated routing',
            api_endpoints='Automated routing'
        )
        logger.exception(e)
        raise e


def add_job_failure(job, connection, type, value, traceback, *args, **kwargs):
    # parse parameters
    input_dir = ""
    status = "failed"
    job_id = job.meta.get('job_id')
    email = job.meta.get('email')
    module = job.meta.get('module')
    submodule = job.meta.get('submodule')
    description = job.meta.get('description')

    try:
        job_db = Job.query.filter_by(job_id=job_id).first()
        if not job_db:
            raise NotFound(f'Job {job_id} not found')

        # update job details and job history
        status_from = job_db.status
        job_db.status = status
        job_db.input = input_dir
        job_hist = JobHistory(job_id, status_from=status_from, status_to=status, action=description, timestamp=datetime.now(timezone.utc), error_message=str(value))
        db.session.add(job_hist)
        db.session.commit()

        log_audit(
            action='Enqueue',
            user_email=email,
            module=module,
            submodule=submodule,
            previous_data='',
            new_data='',
            description=f'User [$USER] failed to add job. Error: {value}',
            error_codes='500',
            database_involved='',
            device_info='Automated routing',
            ip_address='Automated routing',
            api_endpoints='Automated routing'
        )

    except Conflict as e:
        db.session.rollback()
        log_audit(
            action='Enqueue',
            user_email=email,
            module=module,
            submodule=submodule,
            previous_data='',
            new_data='',
            description=f'User [$USER] failed to add job. Error: {str(e)}',
            error_codes='403',
            database_involved='',
            device_info='Automated routing',
            ip_address='Automated routing',
            api_endpoints='Automated routing'
        )
        logger.exception(e)
        raise e

    except Exception as e:
        db.session.rollback()
        log_audit(
            action='Enqueue',
            user_email=email,
            module=module,
            submodule=submodule,
            previous_data='',
            new_data='',
            description=f'User [$USER] failed to add job. Error: {str(e)}',
            error_codes='500',
            database_involved='',
            device_info='Automated routing',
            ip_address='Automated routing',
            api_endpoints='Automated routing'
        )
        logger.exception(e)
        raise e


def update_job_status(job_db, status):
    try:
        executor = get_jwt_identity()
        job_hist = JobHistory(job_id=job_db.job_id, status_from=job_db.status, status_to=status,
                              action=f'User [{executor}] {status} job [{job_db.job_id}]', timestamp=datetime.now(timezone.utc))
        db.session.add(job_hist)
        job_db.status = status
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        logger.exception(e)


def clean_dataframe(df):
    """
    Clean DataFrame by replacing NaN/Inf values with Excel-compatible values
    """
    if not ((df is None) or df.empty):
        # Convert mixed-type columns to strings
        for col in df.columns:
            if df[col].apply(type).nunique() > 1:
                df[col] = df[col].astype(str)

    df_clean = df.copy()

    # Replace infinite values
    df_clean.replace([np.inf, -np.inf], np.nan, inplace=True)

    # # Fill NaN values with empty strings or appropriate defaults
    # numeric_columns = df_clean.select_dtypes(include=[np.number]).columns
    # df_clean[numeric_columns] = df_clean[numeric_columns].fillna('')

    # # For non-numeric columns
    # non_numeric_columns = df_clean.select_dtypes(exclude=[np.number]).columns
    # df_clean[non_numeric_columns] = df_clean[non_numeric_columns].fillna('')

    return df_clean
