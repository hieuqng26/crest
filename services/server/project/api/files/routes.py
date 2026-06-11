import pandas as pd
import os
import gc
import io
from flask import Blueprint, Response, request, jsonify, make_response, stream_with_context
from flask_jwt_extended import jwt_required
from werkzeug.utils import secure_filename

from project import DATA_STORE
from project.api.auditlog.models import log_audit
from project.api.auth.utils import prevent_multiple_logins_per_user
from project.api.utils import validate_request, toJSON
from project.sftp import sftp_stream, sftp_get_file_size, staging_sftp_stream, staging_sftp_get_file_size
from project.logger import get_logger

from .utils import *
files = Blueprint('files', __name__)


logger = get_logger(__name__)


@files.route('/upload_input_data/<string:module>/<string:submodule>', methods=['POST'], endpoint='upload_input_data')
@jwt_required()
@prevent_multiple_logins_per_user()
@validate_request(allowed_keys=['file'])
def upload_input_data(module, submodule):
    try:
        if 'file' not in request.files:
            raise Exception('No file found in request')
        file = request.files['file']
        filename = secure_filename(file.filename)

        if filename.endswith('.xlsx'):
            df = pd.read_excel(file, keep_default_na=False, na_values=['N/A'])
        elif filename.endswith('.csv'):
            # df = pl.read_csv(file, infer_schema_length=None).to_pandas()
            df = pd.read_csv(file, skip_blank_lines=True, keep_default_na=False, na_values=['N/A'])
        else:
            raise Exception('Invalid file format. Only .xlsx and .csv files are allowed')

        # replace inf or -inf with NaN
        df.replace([float('inf'), float('-inf')], pd.NA, inplace=True)

        df = toJSON(df)
        response = make_response(jsonify(df), 200)

        # audit log
        log_audit(
            action='Upload',
            module='file',
            submodule='Input',
            previous_data='',
            new_data='',
            description=f'User [$USER] uploaded file {filename}',
            error_codes='',
            database_involved=''
        )

        # Clear memory
        del df
        gc.collect()

        return response

    except Exception as e:
        log_audit(
            action='Upload',
            module='file',
            submodule='Input',
            previous_data='',
            new_data='',
            description=f'User [$USER] failed to upload file {filename}. Error: {str(e)}',
            error_codes='500',
            database_involved=''
        )
        return make_response(jsonify({'message': str(e)}), 500)


@files.route('/download', methods=['POST'], endpoint='download_file')
@jwt_required()
@prevent_multiple_logins_per_user()
@validate_request(allowed_keys=['jobId', 'module', 'submodule', 'type', 'dbName', 'fileType', 'downloadFileName', 'isStaging'])
def download_file():
    """
    API to generate download URL and let browser handle the download
    """
    try:
        res = request.get_json()
        jobId = res.get('jobId')
        module = res.get('module')
        submodule = res.get('submodule')
        is_staging = res.get('isStaging', False)
        type = res.get('type')
        dbName = res.get('dbName')
        file_type = res.get('fileType', 'xlsx')
        download_file_name = res.get('downloadFileName', dbName)

        jobId = None if jobId in ["undefined", "null", None] else jobId
        type = None if type in ["undefined", "null", None] else type
        dbName = None if dbName in ["undefined", "null", None] else dbName

        if not jobId or not dbName or not type:
            raise ValueError('File not found')

        # Generate a temporary download token
        download_token = create_download_token(jobId, module, submodule, is_staging, type, dbName,
                                               file_type, download_file_name)

        # Return the download URL instead of streaming
        download_url = f"/files/direct_download?token={download_token}"

        log_audit(
            action='Retrieve',
            module='file',
            submodule='download',
            previous_data='',
            new_data='',
            description=f'User [$USER] requested download for {dbName}.',
            error_codes='',
            database_involved=''
        )

        return jsonify({
            "download_url": download_url,
            "filename": f"{download_file_name}.{file_type}",
            "message": "Download URL generated successfully"
        }), 200

    except ValueError as e:
        log_audit(
            action='Retrieve',
            module='file',
            submodule='download',
            previous_data='',
            new_data='',
            description=f'User [$USER] failed to request download for {dbName}. Error: {str(e)}',
            error_codes='400',
            database_involved=''
        )
        return jsonify({"message": str(e)}), 400
    except Exception as e:
        log_audit(
            action='Retrieve',
            module='file',
            submodule='download',
            previous_data='',
            new_data='',
            description=f'User [$USER] failed to request download for {dbName}. Error: {str(e)}',
            error_codes='500',
            database_involved=''
        )
        return jsonify({"message": str(e)}), 500


@files.route('/upload_portfolio_data/<string:module>/<string:submodule>', methods=['POST'], endpoint='upload_portfolio_data')
@jwt_required()
@prevent_multiple_logins_per_user()
def upload_portfolio_data(module, submodule):
    """
    Upload and process portfolio data from Excel file with multiple sheets
    """
    try:
        # Check if file is present in request
        if 'file' not in request.files:
            log_audit(
                action='Upload',
                module='files',
                submodule='portfolio',
                previous_data='',
                new_data='',
                description=f'User [$USER] failed to upload portfolio data. Error: No file provided',
                error_codes='400',
                database_involved=''
            )
            return jsonify({"message": "No file provided"}), 400

        file = request.files['file']

        if file.filename == '':
            log_audit(
                action='Upload',
                module='files',
                submodule='portfolio',
                previous_data='',
                new_data='',
                description=f'User [$USER] failed to upload portfolio data. Error: No file selected',
                error_codes='400',
                database_involved=''
            )
            return jsonify({"message": "No file selected"}), 400

        # Validate file type
        allowed_extensions = {'.xlsx'}
        file_ext = os.path.splitext(file.filename)[1].lower()

        if file_ext not in allowed_extensions:
            log_audit(
                action='Upload',
                module='files',
                submodule='portfolio',
                previous_data='',
                new_data='',
                description=f'User [$USER] failed to upload portfolio data. Error: Invalid file type {file_ext}',
                error_codes='400',
                database_involved=''
            )
            return jsonify({"message": f"Invalid file type. Only Excel files (.xlsx) are allowed"}), 400

        portfolio_data = {}

        # Read the Excel file with all sheets
        file_stream = io.BytesIO(file.read())
        excel_file = pd.ExcelFile(file_stream)

        for sheet_name in excel_file.sheet_names:
            try:
                # Read each sheet as a DataFrame
                df = pd.read_excel(file_stream, sheet_name=sheet_name)
                df.replace([float('inf'), float('-inf')], pd.NA, inplace=True)
                df = toJSON(df)
                portfolio_data[sheet_name] = df

            except Exception as sheet_error:
                logger.warning(f"Failed to process sheet '{sheet_name}': {str(sheet_error)}")
                continue

        if not portfolio_data:
            log_audit(
                action='Upload',
                module='files',
                submodule='portfolio',
                previous_data='',
                new_data='',
                description=f'User [$USER] failed to upload portfolio data. Error: No valid sheets found',
                error_codes='400',
                database_involved=''
            )
            return jsonify({"message": "No valid data sheets found in the Excel file"}), 400

        # Log successful upload
        log_audit(
            action='Upload',
            module='files',
            submodule='portfolio',
            previous_data='',
            new_data='',
            description=f'User [$USER] successfully uploaded portfolio data with {len(portfolio_data)} sheets',
            error_codes='',
            database_involved=''
        )

        return jsonify(portfolio_data), 200

    except Exception as e:
        log_audit(
            action='Upload',
            module='files',
            submodule='portfolio',
            previous_data='',
            new_data='',
            description=f'User [$USER] failed to upload portfolio data. Error: {str(e)}',
            error_codes='500',
            database_involved=''
        )
        return jsonify({"message": str(e)}), 500


@files.route('/ore/upload_scenario_config', methods=['POST'], endpoint='upload_scenario_config')
@jwt_required()
@prevent_multiple_logins_per_user()
def upload_scenario_config():
    """
    Upload and parse scenario config Excel file.

    Expected: FormData with 'file' containing .xlsx file
    Returns: Parsed scenario configuration as JSON
    """
    try:
        # Check if file is present
        if 'file' not in request.files:
            return make_response(jsonify({'message': 'No file provided'}), 400)

        file = request.files['file']

        if not file or file.filename == '':
            return make_response(jsonify({'message': 'No file selected'}), 400)

        # Validate file extension
        if not file.filename.endswith('.xlsx'):
            return make_response(
                jsonify({'message': 'Invalid file format. Only .xlsx files are supported'}),
                400
            )

        # Parse Excel file
        scenario_config = parse_scenario_excel(file)

        # Validate scenario config structure
        # is_valid, errors = validate_scenario_config(scenario_config)
        # if not is_valid:
        #     return make_response(
        #         jsonify({'message': f'Invalid scenario config: {"; ".join(errors)}'}),
        #         400
        #     )

        # Audit log
        log_audit(
            action='Upload',
            module='pricing',
            submodule='scenario_config',
            previous_data='',
            new_data='',
            description=f'User [$USER] uploaded scenario config file: {file.filename}',
            error_codes='',
            database_involved=''
        )

        return make_response(jsonify(scenario_config), 200)

    except ValueError as e:
        logger.error(f"Validation error in scenario config upload: {str(e)}")
        log_audit(
            action='Upload',
            module='pricing',
            submodule='scenario_config',
            previous_data='',
            new_data='',
            description=f'User [$USER] failed to upload scenario config. Error: {str(e)}',
            error_codes='400',
            database_involved=''
        )
        return make_response(jsonify({'message': str(e)}), 400)
    except Exception as e:
        logger.error(f"Error in scenario config upload: {str(e)}")
        log_audit(
            action='Upload',
            module='pricing',
            submodule='scenario_config',
            previous_data='',
            new_data='',
            description=f'User [$USER] failed to upload scenario config. Error: {str(e)}',
            error_codes='500',
            database_involved=''
        )
        return make_response(jsonify({'message': str(e)}), 500)


# @files.route('/direct_download', methods=['GET'], endpoint='direct_download')
# def direct_download():
#     """
#     Direct download endpoint that browser can access
#     """
#     try:
#         token = request.args.get('token')
#         if not token:
#             raise ValueError('Download token is required')

#         # Verify and decode the token
#         download_info = verify_download_token(token)
#         if not download_info:
#             raise ValueError('Invalid or expired download token')

#         jobId = download_info['jobId']
#         module = download_info['module']
#         submodule = download_info['submodule']
#         is_staging = download_info['is_staging']
#         type = download_info['type']
#         dbName = download_info['dbName']
#         file_type = download_info['file_type']
#         download_file_name = download_info['download_file_name']

#         # Stream the file directly
#         chunk_size = int(os.getenv('DOWNLOAD_CHUNK_SIZE', 1024*1024))
#         mimetype = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' if file_type == 'xlsx' else 'text/csv'

#         # Get job details
#         file_dir = '/.'
#         if is_staging:
#             model = STAGING_DB_TABLES[module][submodule]['input'][dbName]

#             if isinstance(model, tuple):
#                 _, _, _type, _db_name = model
#                 job_db = Job.query.filter(Job.job_id == jobId).first()
#                 if not job_db:
#                     raise ValueError(f'No job found for {jobId}')

#                 file_dir = job_db.input if _type == 'input' else job_db.output
#                 file_dir = os.path.join(DATA_STORE, file_dir)
#                 file_name = _db_name
#                 is_staging = False
#             else:
#                 file_name = f"{jobId}-{model.__filename__}"
#         else:
#             job_db = Job.query.filter(Job.job_id == jobId).first()
#             if not job_db:
#                 raise ValueError(f'No job found for {jobId}')

#             file_dir = job_db.input if type == 'input' else job_db.output
#             file_dir = os.path.join(DATA_STORE, file_dir)
#             file_name = dbName

#         filename = f"{file_name}.{file_type}"
#         filesize = None
#         try:
#             if is_staging:
#                 filesize = staging_sftp_get_file_size(filename)
#             else:
#                 filesize = sftp_get_file_size(file_dir, filename)
#         except Exception as e:
#             pass

#         def generate():
#             bufsize = int(os.getenv('DOWNLOAD_BUFFER_SIZE', 1024))
#             if is_staging:
#                 with staging_sftp_stream(filename, mode='rb', bufsize=bufsize) as remote_file:
#                     while chunk := remote_file.read(chunk_size):
#                         yield chunk
#             else:
#                 with sftp_stream(file_dir, filename, mode='rb', bufsize=bufsize) as remote_file:
#                     while chunk := remote_file.read(chunk_size):
#                         yield chunk

#         response = Response(
#             stream_with_context(generate()),
#             mimetype=mimetype,
#             headers={
#                 'Content-Disposition': f'attachment; filename="{download_file_name}.{file_type}"',
#                 'Cache-Control': 'no-cache'
#             }
#         )

#         if filesize:
#             response.headers['Content-Length'] = str(filesize)

#         return response

#     except Exception as e:
#         return jsonify({"message": str(e)}), 500
