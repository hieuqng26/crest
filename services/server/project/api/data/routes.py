import json
import os
import pandas as pd
from flask import Blueprint, jsonify, request, make_response
from flask_jwt_extended import jwt_required

from project.api.utils import validate_request, toJSON
from project.api.auditlog.models import log_audit
from project.db_models import *
from project.api.jobs.utils import load_staging_by_module
from project.api.auth.utils import prevent_multiple_logins_per_user


data = Blueprint('data', __name__)


@data.route('/staging/<string:module>/<string:submodule>', methods=['POST'], endpoint='get_staging_input')
@jwt_required()
@prevent_multiple_logins_per_user()
@validate_request(allowed_keys=['columns', 'dbName', 'filter_columns', 'filter_values',
                                'sort_column', 'sort_order', 'page', 'page_size', 'jobId', 'get_size'])
def get_staging_input(module, submodule):
    try:
        data = request.get_json()
        columns_arg = data.get('columns')
        dbName = data.get('dbName')
        filter_columns = data.get('filter_columns')
        filter_values = data.get('filter_values')
        sort_column = data.get('sort_column')
        sort_order = data.get('sort_order')
        page = data.get('page')
        page_size = data.get('page_size')
        job_id = data.get('jobId')
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

        # query data
        results = load_staging_by_module(module, submodule, columns=columns, filter_columns=filter_columns, filter_values=filter_values,
                                         sort_column=sort_column, sort_order=sort_order, page=page, page_size=page_size, job_id=job_id, dbName=dbName,
                                         get_size=get_size, get_job_id=True)

        output_json = {}
        if isinstance(results, dict):
            for key, result in results.items():
                if result is None:
                    if get_size:
                        output_json[key] = {'data': toJSON(pd.DataFrame()), 'total_size': 0, 'job_id': job_id}
                    else:
                        output_json[key] = {'data': toJSON(pd.DataFrame()), 'job_id': job_id}
                else:
                    if get_size:
                        (df, total_size), job_id = result
                        df = pd.DataFrame() if df is None else df
                        output_json[key] = {'data': toJSON(df), 'total_size': total_size, 'job_id': job_id}
                    else:
                        df, _ = result
                        df = pd.DataFrame() if df is None else df
                        output_json[key] = {'data': toJSON(df), 'job_id': job_id}
        else:
            if results is None:
                output_json = None
            else:
                if get_size:
                    result = results[0]
                    job_id = results[1]
                    df = result[0]
                    total_size = result[1]
                    df = pd.DataFrame() if df is None else df
                    output_json = {'data': toJSON(df), 'total_size': total_size, 'job_id': job_id}
                else:
                    df = pd.DataFrame() if results is None else results
                    output_json = toJSON(df)

        # audit log
        log_audit(
            action='Retrieve',
            module=module,
            submodule=submodule,
            previous_data='',
            new_data='',
            description=f'User [$USER] retrieved staging input data for [{module}-{submodule}]',
            error_codes='',
            database_involved=''
        )
        return make_response(jsonify(output_json), 200)
    except ValueError as e:
        log_audit(
            action='Retrieve',
            module=module,
            submodule=submodule,
            previous_data='',
            new_data='',
            description=f'User [$USER] retrieved staging input data for [{module}-{submodule}]. Error: {str(e)}',
            error_codes='400',
            database_involved=''
        )
        return make_response(jsonify({'message': str(e)}), 400)
    except Exception as e:
        log_audit(
            action='Retrieve',
            module=module,
            submodule=submodule,
            previous_data='',
            new_data='',
            description=f'User [$USER] retrieved staging input data for [{module}-{submodule}]. Error: {str(e)}',
            error_codes='500',
            database_involved=''
        )
        return make_response(jsonify({'message': str(e)}), 500)


@data.route('/market-data/<string:category>', methods=['POST'], endpoint='get_market_data')
@jwt_required()
@prevent_multiple_logins_per_user()
@validate_request(allowed_keys=['filter_columns', 'filter_values'])
def get_market_data(category):
    try:
        # Validate category
        if category not in ['FXVOL', 'IRVOL', 'YIELDCURVE']:
            return make_response(jsonify({'message': 'Invalid category. Must be FXVOL, IRVOL, or YIELDCURVE'}), 400)

        data = request.get_json()
        filter_columns = data.get('filter_columns')
        filter_values = data.get('filter_values')

        # Parse values
        if filter_values is not None:
            filter_values = json.loads(filter_values) if isinstance(filter_values, str) else filter_values

        filter_columns = None if filter_columns in ['undefined', 'null', '', None] else filter_columns.split('\x1e')
        filter_values = None if filter_values in ['undefined', 'null', '', None] else filter_values.split('\x1f')

        # Read CSV file
        csv_path = os.path.join('project/data/db', category, 'data.csv')
        df = pd.read_csv(csv_path)

        # Apply filters
        try:
            if filter_columns and filter_values:
                for i, col in enumerate(filter_columns):
                    filter_val_list = filter_values[i].split('\x1e')
                    df = df[df[col].astype(str).isin(filter_val_list)]
        except Exception as e:
            raise Exception("Invalid filters")

        # filter columns
        if category == 'FXVOL':
            selected_columns = [
                'SubType', 'Name', 'Date',
                'DomesticCurrency', 'ForeignCurrency', 'DomesticCurve', 'ForeignCurve',
                'FXVOLSURFACE', 'ATM', 'Call25', 'Put25', 'Call10', 'Put10',
                'ATMConvention', 'DeltaPremiumConvention'
            ]
        elif category == 'IRVOL':
            selected_columns = [
                'SubType', 'VolType', 'Name', 'Date',
                'DiscountCurve', 'ForecastCurve', 'SwapType', 'SwapFloatFrequency',
                'SwapFixedFrequency', 'Currency', 'Calendar', 'Option Tenor',
                'Underlying Tenor', 'Volatility'
            ]
        elif category == 'YIELDCURVE':
            selected_columns = [
                'Name', 'BaseDiscountingCurve', 'Date',
                'Currency', 'Calendar', 'TICKER', 'TYPE',
                'TENOR', 'RATE', 'FXSpot'
            ]

        df = df[selected_columns]

        # Calculate total size before pagination
        total_size = len(df)

        output_json = {
            'data': toJSON(df),
            'total_size': total_size,
            'columns': list(df.columns)
        }

        # Audit log
        log_audit(
            action='Retrieve',
            module='market_data',
            submodule=category.lower(),
            previous_data='',
            new_data='',
            description=f'User [$USER] retrieved market data for [{category}]',
            error_codes='',
            database_involved=''
        )
        return make_response(jsonify(output_json), 200)

    except Exception as e:
        log_audit(
            action='Retrieve',
            module='market_data',
            submodule=category.lower() if category else 'unknown',
            previous_data='',
            new_data='',
            description=f'User [$USER] retrieved market data for [{category}]. Error: {str(e)}',
            error_codes='500',
            database_involved=''
        )
        return make_response(jsonify({'message': str(e)}), 500)
