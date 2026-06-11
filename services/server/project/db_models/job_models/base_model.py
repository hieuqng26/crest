import os
import sqlalchemy
from sqlalchemy import orm
from project import db


FLOATING_POINT_PRECISION = int(os.getenv('FLOATING_POINT_PRECISION', 14))


class BaseModel(db.Model):
    __abstract__ = True
    LOAD_ALL = False

    pk: orm.Mapped[int] = orm.mapped_column(sqlalchemy.BigInteger, primary_key=True)
    job_id: orm.Mapped[str] = orm.mapped_column(sqlalchemy.String)

    @classmethod
    def column_map(cls):
        return {'pk': cls.pk, 'job_id': cls.job_id}

    @classmethod
    def join(cls, query):
        return query

    @classmethod
    def transform_input(cls, df):
        '''Transform data before saving to the database.'''
        return df

    @classmethod
    def transform_output(cls, df):
        '''Transform data after retrieving from the database.'''
        return df
