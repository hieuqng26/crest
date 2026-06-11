import os
import numpy as np
from sqlalchemy import inspect
from sqlalchemy.orm import Session
from project import db
from project.logger import get_logger
from .utils import *
from .config import APP_DB_MODELS


logger = get_logger(__name__)


def create_job_data_tables():
    # get all tables from APP_DB_MODELS
    models = [model for module in APP_DB_MODELS.values() for submodule in module.values() for type in submodule.values() for model in type.values() if model is not None]

    for model in models:
        inspector = inspect(db.engine)
        if model.__tablename__ not in inspector.get_table_names():
            model.__table__.create(db.engine)
            logger.info(f"{model.__tablename__} table created successfully!")
        else:
            logger.info(f"{model.__tablename__} table already exists.")


def drop_job_data_tables():
    # get all tables from APP_DB_MODELS
    models = [model for module in APP_DB_MODELS.values() for submodule in module.values() for type in submodule.values() for model in type.values() if model is not None]

    for model in models:
        inspector = inspect(db.engine)
        if model.__tablename__ in inspector.get_table_names():
            model.__table__.drop(db.engine)
            logger.info(f"{model.__tablename__} table dropped successfully!")
        else:
            logger.warning(f"{model.__tablename__} table does not exist.")


def save_job_to_app_db(df, module, submodule, type, db_name, job_id=None, clear_if_exists=True):
    # Create a new session for this function
    session = Session(bind=db.engine)
    model = None
    logger.info(f"Saving job data to app db for {module} - {submodule} - {type} - {db_name}")

    try:
        model = APP_DB_MODELS[module][submodule][type][db_name]
    except KeyError:
        logger.error(f"Model {module} - {submodule} - {type} - {db_name} not found.")

    if not model:
        session.close()
        return

    df = model.transform_input(df)
    if job_id:
        # remove all records with the same job_id
        if clear_if_exists:
            logger.info(f"Clearing existing data for job_id {job_id} in {model.__tablename__}")
            session.query(model).filter(model.job_id == job_id).delete()
            session.commit()

        # add job_id to the dataframe
        df['job_id'] = job_id

    try:
        df.replace([np.inf, -np.inf], np.nan, inplace=True)
        df.to_sql(
            model.__tablename__,
            con=session.bind,
            if_exists='append',
            index=False,
            chunksize=int(os.getenv('APP_DB_CHUNK_SIZE', 1000))
        )
    except Exception as e:
        logger.exception(f"Error saving data to {model.__tablename__}. {e}")
        session.rollback()
        raise e
    finally:
        session.close()


def clear_job_data_from_app_db(module, submodule, type, db_name=None, job_id=None):
    if not job_id:
        return

    def clear_single_model(module, submodule, type, db_name, job_id):
        model = None
        logger.info(f"Clearing job data from app db for {module} - {submodule} - {type} - {db_name}")

        try:
            model = APP_DB_MODELS[module][submodule][type][db_name]
        except KeyError:
            logger.error(f"Model {module} - {submodule} - {type} - {db_name} not found.")

        if not model:
            return

        try:
            db.session.query(model).filter(model.job_id == job_id).delete()
            db.session.commit()
        except Exception as e:
            logger.exception(f"Error clearing data from {model.__tablename__}. {e}")
            db.session.rollback()
            raise e

    if db_name:
        clear_single_model(module, submodule, type, db_name, job_id)
    else:
        if type not in APP_DB_MODELS[module][submodule]:
            return

        models = APP_DB_MODELS[module][submodule][type]
        for db_name in models.keys():
            clear_single_model(module, submodule, type, db_name, job_id)


def load_job_from_app_db(module, submodule, type, db_name, job_id=None, **kwargs):
    try:
        model = APP_DB_MODELS[module][submodule][type][db_name]
        df = query_app_model(model, job_id, **kwargs)
    except ValueError as e:
        raise e
    except Exception as e:
        logger.exception(f'Fail to load data in application database for {module}-{submodule}-{type}-{db_name}. {str(e)}')
        raise Exception(str(e))
    return df


def load_all_job_from_app_db(module, submodule, type, db_names=None, job_id=None, **kwargs):
    try:
        models = APP_DB_MODELS[module][submodule][type]
        dfs = {}
        if db_names:
            if isinstance(db_names, str):
                db_names = db_names.split('\x1e')
            if isinstance(db_names, list):
                db_names = [db_name.strip() for db_name in db_names]
            models = {db_name: models[db_name] for db_name in db_names if db_name in models}

        if not models:
            raise Exception(f'No models found for {module}-{submodule}-{type}.')

        for db_name, model in models.items():
            if model:
                dfs[db_name] = query_app_model(model, job_id, **kwargs)
    except Exception as e:
        logger.exception(f'Fail to load data in application database for {module}-{submodule}-{type}. {str(e)}')
        raise Exception(str(e))
    return dfs
