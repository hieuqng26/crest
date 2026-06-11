import pandas as pd
import hashlib
import json
from sqlalchemy.exc import OperationalError
from sqlalchemy import func
from project.logger import get_logger
from project import db, cache

logger = get_logger(__name__)


def generate_cache_key(*args, **kwargs):
    """Generate a stable cache key from function arguments"""
    # Convert arguments to a stable string representation
    model = args[0] if args else None
    job_id = args[1] if len(args) > 1 else None

    model_name = model.__name__ if hasattr(model, '__name__') else str(model)

    # Create a stable representation of kwargs
    kwargs_str = json.dumps(kwargs, sort_keys=True, default=str)

    # Create cache key
    cache_key = f"query_app_model_{model_name}_{job_id}_{hashlib.sha256(kwargs_str.encode()).hexdigest()[:16]}"

    # Check if key exists in cache and log it
    if cache.get(cache_key) is not None:
        logger.debug(f"Cache HIT for key: {cache_key}")
    else:
        logger.debug(f"Cache MISS for key: {cache_key}")

    return cache_key  # Redis key length limit


def create_cache_key_for_query(model, job_id, **kwargs):
    """Create a deterministic cache key for database queries"""
    model_name = model.__name__ if hasattr(model, '__name__') else str(model)

    # Only include relevant kwargs for caching
    cache_relevant_keys = ['columns', 'filter_columns', 'filter_values',
                           'page', 'page_size', 'sort_column', 'sort_order', 'get_size']

    cache_kwargs = {k: v for k, v in kwargs.items() if k in cache_relevant_keys}
    kwargs_str = json.dumps(cache_kwargs, sort_keys=True, default=str)

    return f"query_{model_name}_{job_id}_{hashlib.sha256(kwargs_str.encode()).hexdigest()[:16]}"


def create_filtered_query_orm(query, column_map, **kwargs):
    filter_columns = kwargs.get('filter_columns', None)
    filter_values = kwargs.get('filter_values', None)
    page = kwargs.get('page', None)
    page_size = kwargs.get('page_size', None)
    sort_column = kwargs.get('sort_column', None)
    sort_order = kwargs.get('sort_order', None)

    # Construct the WHERE clause
    if filter_columns and filter_values:
        for col, val in zip(filter_columns, filter_values):
            if col in column_map:
                column_type = column_map[col].type

                try:
                    # Attempt to convert the value to the column's type
                    if isinstance(val, str) and '\x1e' in val:
                        # Handle multiple values (e.g., for `IN` filters)
                        val_list = val.split('\x1e')
                        converted_values = [convert_value(v, column_type) for v in val_list]
                        query = query.filter(column_map[col].in_(converted_values))
                    else:
                        # Single value conversion
                        if column_type.python_type == str:
                            query = query.filter(column_map[col].ilike(f"%{val}%"))
                        else:
                            converted_value = convert_value(val, column_type)
                            query = query.filter(column_map[col] == converted_value)

                except ValueError as e:
                    logger.warning(f"Invalid value '{val}' for column '{col}': {e}")
                    # Return an empty query if the value is not convertible
                    return query.filter(False)
    # Sorting
    if (sort_column is not None) and (sort_order is not None):
        for col, order in zip(sort_column, sort_order):
            if (col not in column_map) or (col == 'pk'):
                continue
            if order == 'desc':
                query = query.order_by(column_map[col].desc())
            else:
                query = query.order_by(column_map[col])

    # Construct the LIMIT and OFFSET for pagination
    if page is not None and page_size is not None:
        if not page_size > 0:
            raise ValueError("page_size is invalid.")
        query = (
            query
            .order_by(column_map['pk'])
            .offset(page * page_size)
            .limit(page_size)
        )

    return query


def convert_value(value, column_type):
    """
    Convert the value to the appropriate type based on the column type.
    """
    try:
        if column_type.python_type == float and value in ['nan', 'NaN', '']:
            return None

        return column_type.python_type(value)
    except (ValueError, TypeError) as e:
        raise ValueError(f"Cannot convert '{value}' to type {column_type.python_type}. Error: {e}")


def handle_app_exceptions(func):
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except ValueError as e:
            raise e
        except OperationalError as e:
            logger.exception(f'Fail to load data in application database. {str(e.orig)}')
            raise Exception(str(e.orig))
        except Exception as e:
            logger.exception(f'Fail to load data in application database. {str(e)}')
            raise Exception(str(e))
    return wrapper


@cache.cached(timeout=300, make_cache_key=generate_cache_key)
@handle_app_exceptions
def query_app_model(model, job_id, **kwargs):
    # # Generate cache key
    # cache_key = create_cache_key_for_query(model, job_id, **kwargs)

    # # Try to get from cache first
    # cached_result = cache.get(cache_key)
    # if cached_result is not None:
    #     logger.info(f"Cache hit for key: {cache_key}")
    #     return cached_result

    # logger.info(f"Cache miss for key: {cache_key}")

    get_size = kwargs.get('get_size', False)
    load_all = model.LOAD_ALL if hasattr(model, 'LOAD_ALL') else False

    try:
        columns = kwargs.get('columns', None)
        column_map = model.column_map()

        if not job_id:
            job_id = db.session.query(func.max(model.job_id)).scalar()

        # select columns
        if isinstance(columns, str):
            columns = columns.split('\x1e')

        if columns:
            columns = [i.strip() for i in columns]
        else:
            columns = [i for i in column_map.keys() if i != 'pk']

        # add label
        selected_columns = [column_map[col].label(col) for col in columns if col in column_map]

        if 'pk' not in columns:
            selected_columns.append(column_map['pk'])

        # base query
        base_query = (
            db.session.query(
                *selected_columns
            )
            .filter(model.job_id == job_id)
            .distinct()
        )

        base_query = model.join(base_query)

        if not load_all:
            # only apply filters, no pagination or sorting
            count_query = create_filtered_query_orm(base_query, column_map,
                                                    filter_columns=kwargs.get('filter_columns', None),
                                                    filter_values=kwargs.get('filter_values', None))

            # pagination and filters if load_all is False
            query = create_filtered_query_orm(base_query, column_map, **kwargs)

            # query and processing
            total_size = count_query.count()
            results = query.all()

            df = pd.DataFrame(results)
            if len(df) > 0:
                df = model.transform_output(df)
            df.drop(columns=['pk', 'job_id'], errors='ignore', inplace=True)

        # if load_all is True, we need to load all data
        # and apply filters, pagination, and sorting after loading all data
        else:
            # if load_all is True, we need to load all data
            query = base_query
            results = query.all()
            df = pd.DataFrame(results)
            if len(df) > 0:
                df = model.transform_output(df)
            df.drop(columns=['pk', 'job_id'], errors='ignore', inplace=True)

            filter_columns = kwargs.get('filter_columns', None)
            filter_values = kwargs.get('filter_values', None)
            page = kwargs.get('page', None)
            page_size = kwargs.get('page_size', None)
            sort_column = kwargs.get('sort_column', None)
            sort_order = kwargs.get('sort_order', 'asc')

            if filter_columns and filter_values:
                for col, val in zip(filter_columns, filter_values):
                    if col not in df.columns:
                        continue
                    df = df[df[col].isin(val.split('\x1e'))].copy()

            total_size = df.shape[0]

            if (page is not None) and (page_size is not None):
                start = page * page_size
                end = start + page_size
                df = df.iloc[start:end].copy()

            if sort_column:
                df = df.sort_values(by=sort_column, ascending=(sort_order == 'asc')).copy()

        df = df.drop_duplicates()
        result = (df, total_size) if get_size else df
        # cache.set(cache_key, result, timeout=300)  # Cache for 5 minutes

        return result

    except ValueError as e:
        db.session.rollback()
        raise e
    except Exception as e:
        db.session.rollback()
        raise Exception(str(e))
    finally:
        # Ensure session is properly managed
        db.session.close()
