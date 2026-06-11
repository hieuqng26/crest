import pandas as pd
import os
import gc
from sqlalchemy import create_engine, text
from project import db
from .config import ROLES_FILE
from project.sftp import sftp_stream
from project.utils import join_path
from project.logger import get_logger

logger = get_logger(__name__)

DB_MODELS = {}
SKIP_MODELS = []


def get_model_for_file(file_path):
    for model, path in DB_MODELS.items():
        if path == file_path:
            return model
    return None


def load_data_file(model, file_path, engine=None):
    engine = create_engine(db.engine.url) if engine is None else engine
    try:
        sftp_dir = os.getenv('WORKDIR', '.')
        file_path = join_path(sftp_dir, file_path)
        clean_single_table(model)
        file_dir = os.path.dirname(file_path)
        file_name = os.path.basename(file_path)
        with sftp_stream(file_dir, file_name, mode='r') as remote_file:
            df = pd.read_csv(remote_file, skip_blank_lines=True, keep_default_na=False, na_values=['N/A'])
            df = model.transform_input(df)
            df.to_sql(model.__tablename__, con=engine, if_exists='append', index=False)
            del df
            gc.collect()
        return True
    except Exception as e:
        logger.error(f"Error loading {model.__tablename__} from {file_path}: {e}")
        raise


def seed_data():
    engine = create_engine(db.engine.url)
    for model, file in DB_MODELS.items():
        with engine.connect() as connection:
            result = connection.execute(text(f"SELECT TOP 1 1 FROM {model.__tablename__}")).fetchone()
            if model in SKIP_MODELS and result is not None:
                logger.debug(f"Table {model.__tablename__} already has data. Skipping.")
            else:
                try:
                    load_data_file(model, file, engine)
                except Exception as e:
                    logger.error(f"Error seeding {model.__tablename__}. {e}")


def clean_data():
    for model in DB_MODELS.keys():
        clean_single_table(model)


def clean_single_table(model):
    try:
        model.query.delete()
        db.session.commit()
    except Exception:
        db.session.rollback()
    finally:
        db.session.close()
