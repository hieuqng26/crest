import pandas as pd
from sqlalchemy import create_engine, text
from project import db
from project.logger import get_logger


logger = get_logger(__name__)


def load_from_app_db(data_model):
    try:
        engine = create_engine(db.engine.url, fast_executemany=True)
        query = text(f"SELECT * FROM {data_model.__tablename__}")
        with engine.connect() as connection:
            df = pd.read_sql_query(query, connection)
        df.drop(columns=['id'], inplace=True, errors='ignore')
        df = data_model.transform_output(df)
        df = df.drop_duplicates()
        return df
    except Exception as e:
        # comment out to run on local (test)
        # from project.db_models import DB_MODELS
        # src_file = DB_MODELS[data_model]
        # df = pd.read_csv(src_file)
        # df = df.drop_duplicates()
        # return df
        raise e


def load_macro_data_from_app_db(data_model, countries, risk_type):
    try:
        engine = create_engine(db.engine.url, fast_executemany=True)

        # Handle list parameters for SQL Server
        if isinstance(countries, (list, tuple)):
            # Create placeholders for each country
            country_placeholders = ','.join([f':country_{i}' for i in range(len(countries))])
            query = text(f"SELECT * FROM {data_model.__tablename__} WHERE Region IN ({country_placeholders}) AND Risk = :risk_type")

            # Create parameters dict
            params = {f'country_{i}': country for i, country in enumerate(countries)}
            params['risk_type'] = risk_type
        else:
            # Single country
            query = text(f"SELECT * FROM {data_model.__tablename__} WHERE Region = :countries AND Risk = :risk_type")
            params = {"countries": countries, "risk_type": risk_type}

        with engine.connect() as connection:
            df = pd.read_sql_query(query, connection, params=params)

        df.drop(columns=['id'], inplace=True, errors='ignore')
        df = data_model.transform_output(df)
        df = df.drop_duplicates()
        return df

    except Exception as e:
        logger.error(f"Failed to load macro data: {str(e)}")
        logger.error(f"Countries: {countries}, Risk Type: {risk_type}")
        raise e


def append_to_db(data_model, data, key=None):
    try:
        engine = create_engine(db.engine.url, fast_executemany=True)
        data = data_model.transform_input(data)
        data = data.drop_duplicates()

        if key:
            with engine.connect() as connection:
                # Quote column names to handle special characters
                quoted_keys = [f'"{col}"' for col in key]
                query = text(f"SELECT {', '.join(quoted_keys)} FROM \"{data_model.__tablename__}\"")
                existing_records = pd.read_sql_query(query, connection)

                # Remove rows from `data` that already exist in the table
                data = data[~data[key].apply(tuple, axis=1).isin(existing_records[key].apply(tuple, axis=1))]

        # Append only non-duplicate records
        if not data.empty:
            ids = data[key].apply(lambda row: '_'.join(row.astype(str)), axis=1).tolist()
            logger.debug(f"Appending {len(data)} records to {data_model.__tablename__} table with IDs: {ids}")
            data.to_sql(data_model.__tablename__, con=engine, if_exists='append', index=False)
    except Exception as e:
        raise e
