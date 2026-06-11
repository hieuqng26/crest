from project import db


class DBBaseModel(db.Model):
    __abstract__ = True

    @staticmethod
    def transform_input(df):
        return df

    @staticmethod
    def transform_output(df):
        return df
