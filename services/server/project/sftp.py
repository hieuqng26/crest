import paramiko
import pandas as pd
import os
import gc
from datetime import datetime, timezone
from contextlib import contextmanager
import pyarrow as pa
import pyarrow.parquet as pq
import xlsxwriter
from project.logger import get_logger
from project.utils import join_path
from project.db_models.job_models import load_job_from_app_db
from project.db_models.job_models.config import APP_DB_MODELS

logger = get_logger(__name__)


def get_sftp_connection():
    connection = paramiko.SSHClient()
    connection.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    connection.connect(
        hostname=os.getenv("SFTP_HOST", "127.0.0.1"),
        username=os.getenv("SFTP_USER", "crst"),
        password=os.getenv("SFTP_PASSWORD", "supersecret"),
        port=os.getenv("SFTP_PORT", "22")
    )

    return connection


def get_staging_sftp_connection():
    connection = paramiko.SSHClient()
    connection.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    connection.connect(
        hostname=os.getenv("BE_SFTP__HOST", "127.0.0.1"),
        username=os.getenv("BE_SFTP__USER", "crst"),
        password=os.getenv("BE_SFTP__PASSWORD", "supersecret"),
        port=os.getenv("BE_SFTP__PORT", "22")
    )

    return connection


def sftp_put(df, file_dir, file_name, extensions=['parquet', 'csv', 'xlsx']):
    '''
    Save df to parquet from localpath (/var/lib/data/df.parquet)
    to SFTP server's path (/home/admin/upload/var/lib/data/df.parquet)
    '''
    conn = None
    sftp = None
    batch_size = int(os.getenv("JOB_DATA_BATCH_SIZE", 10000))

    try:
        # Open an SFTP connection
        conn = get_sftp_connection()
        sftp = conn.open_sftp()
        root_dir = os.getenv("SFTP_PATH", "./")
        remote_dir = join_path(root_dir, file_dir)

        os.makedirs(file_dir, exist_ok=True)
        for ext in extensions:
            local_path = f"{file_dir}/{file_name}.{ext}"
            remote_path = join_path(remote_dir, f"{file_name}.{ext}")

            # save data to local file
            if df is None:
                df = pd.DataFrame()

            if ext == 'parquet':
                logger.debug(f"Writing to local parquet file: {local_path}")
                write_parquet(df, local_path)
            elif ext == 'csv':
                logger.debug(f"Writing to local CSV file: {local_path}")
                write_csv(df, local_path, batch_size=batch_size)
            elif ext == 'xlsx':
                logger.debug(f"Writing to local Excel file: {local_path}")
                write_xlsx(df, local_path, batch_size=batch_size)

            # Ensure the remote directory exists
            logger.debug(f"Create directory in SFTP with remote directory: {remote_dir}")
            mkdir_recursive(sftp, remote_dir)

            # Securely transfer the file using SFTP
            logger.debug(f"Save file to SFTP at {remote_path}")
            sftp_put_chunked(sftp, local_path, remote_path)

            # Remove the local file after transfer
            os.remove(local_path)

        # close connection
        sftp.close()
        conn.close()
    except Exception as e:
        logger.exception(e)
        raise e
    finally:
        if sftp:
            sftp.close()
        if conn:
            conn.close()


def sftp_get(remote_dir, filename, local_path):
    '''
    Copy file from SFTP server's path (/home/admin/upload/var/lib/data/df.parquet)
    to localpath (/var/lib/data/df.parquet)
    '''
    conn = None
    sftp = None

    try:
        # Open an SFTP connection
        conn = get_sftp_connection()
        sftp = conn.open_sftp()
        root_dir = os.getenv("SFTP_PATH", ".")

        # change to stfp directory
        sftp.chdir(join_path(root_dir, remote_dir))

        # Securely transfer the file using SFTP
        os.makedirs(os.path.dirname(local_path), exist_ok=True)
        sftp.get(filename, local_path)

        # close connection
        sftp.close()
        conn.close()
    except Exception as e:
        raise e
    finally:
        if sftp:
            sftp.close()
        if conn:
            conn.close()


@contextmanager
def staging_sftp_stream(filename, remote_dir='/export', mode='r', bufsize=1024):
    '''
    Context manager for streaming staging SFTP file operations.
    Handles proper closure of resources automatically.

    Parameters:
    - remote_dir: Directory path on SFTP server relative to root_dir
    - filename: Name of the file to open
    - mode: File mode ('r' for read, 'w' for write, 'rb' for binary read, etc.)

    Usage:
    with sftp_stream('/path/to/dir', 'myfile.parquet', 'rb') as remote_file:
        df = pd.read_parquet(remote_file)
        # Process df...
    '''
    conn = None
    sftp = None
    file_obj = None

    try:
        # Open an SFTP connection
        conn = get_staging_sftp_connection()
        sftp = conn.open_sftp()
        root_dir = os.getenv("BE_SFTP__PATH", "./")

        # Construct full remote path
        remote_path = join_path(root_dir, remote_dir, filename)
        logger.debug(f"Opening SFTP file: {remote_path} in mode {mode}")

        # Open the file in specified mode
        file_obj = sftp.open(remote_path, mode, bufsize=bufsize)
        yield file_obj
    finally:
        # Ensure all resources are properly closed, regardless of exceptions
        if file_obj:
            file_obj.close()
        if sftp:
            sftp.close()
        if conn:
            conn.close()


def sftp_get_file_size(remote_dir, filename):
    """Get file size from SFTP server"""
    conn = None
    sftp = None

    try:
        conn = get_sftp_connection()
        sftp = conn.open_sftp()
        root_dir = os.getenv("SFTP_PATH", "./")

        # Construct full remote path
        remote_path = join_path(root_dir, remote_dir, filename)

        # Get file stats and return size
        file_stat = sftp.stat(remote_path)
        return str(file_stat.st_size)
    except Exception as e:
        logger.error(f"Error getting size of {remote_path}: {e}")
        return '0'
    finally:
        if sftp:
            sftp.close()
        if conn:
            conn.close()


def staging_sftp_get_file_size(filename, remote_dir='/export'):
    """Get file size from staging SFTP server"""
    conn = None
    sftp = None

    try:
        conn = get_staging_sftp_connection()
        sftp = conn.open_sftp()
        root_dir = os.getenv("BE_SFTP__PATH", "./")

        # Construct full remote path
        remote_path = join_path(root_dir, remote_dir, filename)

        # Get file stats and return size
        file_stat = sftp.stat(remote_path)
        return str(file_stat.st_size)
    except Exception as e:
        logger.error(f"Error getting size of {remote_path}: {e}")
        return '0'
    finally:
        if sftp:
            sftp.close()
        if conn:
            conn.close()


def sftp_get_file_stats(file_path):
    """Get file stats (exists, size, modification time) from SFTP server.

    Args:
        file_path (str): Path to file relative to SFTP root directory

    Returns:
        dict: Dictionary with 'exists', 'size', and 'date_modified' keys
    """
    conn = None
    sftp = None

    stats = {
        'exists': False,
        'size': None,
        'date_modified': None
    }

    try:
        conn = get_sftp_connection()
        sftp = conn.open_sftp()
        root_dir = os.getenv("SFTP_PATH", "./")

        # Construct full remote path
        remote_path = join_path(root_dir, file_path)

        # Get file stats
        file_attrs = sftp.stat(remote_path)
        stats['exists'] = True
        stats['size'] = file_attrs.st_size
        stats['date_modified'] = file_attrs.st_mtime

        try:
            date_modified = datetime.fromtimestamp(file_attrs.st_mtime, timezone.utc)
        except Exception as e:
            date_modified = stats['date_modified']

        stats['date_modified'] = date_modified

    except FileNotFoundError:
        # File doesn't exist, keep defaults
        pass
    except Exception as e:
        logger.debug(f"Error getting stats for {file_path}: {e}")
        # Keep defaults for any other errors
        pass
    finally:
        if sftp:
            sftp.close()
        if conn:
            conn.close()

    return stats


@contextmanager
def sftp_stream(remote_dir, filename, mode='r', bufsize=1024):
    '''
    Context manager for streaming SFTP file operations.
    Handles proper closure of resources automatically.

    Parameters:
    - remote_dir: Directory path on SFTP server relative to root_dir
    - filename: Name of the file to open
    - mode: File mode ('r' for read, 'w' for write, 'rb' for binary read, etc.)

    Usage:
    with sftp_stream('/path/to/dir', 'myfile.parquet', 'rb') as remote_file:
        df = pd.read_parquet(remote_file)
        # Process df...
    '''
    conn = None
    sftp = None
    file_obj = None

    try:
        # Open an SFTP connection
        conn = get_sftp_connection()
        sftp = conn.open_sftp()
        root_dir = os.getenv("SFTP_PATH", "./")

        # Construct full remote path
        remote_path = join_path(root_dir, remote_dir, filename)
        logger.debug(f"Opening SFTP file: {remote_path} in mode {mode}")

        # Open the file in specified mode
        file_obj = sftp.open(remote_path, mode, bufsize=bufsize)
        yield file_obj
    finally:
        # Ensure all resources are properly closed, regardless of exceptions
        if file_obj:
            file_obj.close()
        if sftp:
            sftp.close()
        if conn:
            conn.close()


def sftp_listdir(local_dir):
    conn = None
    sftp = None

    try:
        # Open an SFTP connection
        conn = get_sftp_connection()
        sftp = conn.open_sftp()
        root_dir = os.getenv("SFTP_PATH", "./")
        remote_dir = local_dir

        files = sftp.listdir(join_path(root_dir, remote_dir))

        # close connection
        sftp.close()
        conn.close()
        return files
    except Exception as e:
        return []
    finally:
        if sftp:
            sftp.close()
        if conn:
            conn.close()


def file_exists_remote(sftp, remote_path):
    """
    Check if a file exists on the remote SFTP server.
    """
    try:
        sftp.stat(remote_path)
        return True
    except IOError:
        return False


def mkdir_recursive(sftp, remote_directory):
    """
    Recursively create directories on the SFTP server.

    Parameters:
    - sftp: The SFTP client object
    - remote_directory: Full path of the directory to create
    """
    # Split the directory path into parts and iterate over them
    dirs = remote_directory.split('/')
    current_path = "."

    for directory in dirs:
        if directory:  # Skip any empty parts
            current_path += f"/{directory}"
            try:
                # Try to list the directory to check if it exists
                sftp.listdir(current_path)
            except IOError as e:
                # logger.exception(f"Fail to create directory {current_path} in SFTP. {e}")
                # Directory doesn't exist, so create it
                sftp.mkdir(current_path)
            except FileNotFoundError as e:
                # logger.exception(f"Fail to create directory {current_path} in SFTP. {e}")
                sftp.mkdir(current_path)


def write_parquet(df, file_path):
    """
    Write a pandas DataFrame to Parquet format.
    """
    try:
        # Ensure the directory exists
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        df.to_parquet(file_path, engine='pyarrow', compression='snappy', index=False)
    except Exception as e:
        logger.error(f"Error writing Parquet file: {e}")
        raise


def write_csv(df, file_path, batch_size=10000):
    """
    Write a pandas DataFrame to Csv in chunks to minimize memory usage.
    """
    try:
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        if len(df) <= batch_size:
            df.to_csv(file_path, index=False)
        else:
            # Write in chunks to avoid high memory usage
            total_rows = len(df)
            with open(file_path, 'w', newline='', encoding='utf-8') as f:
                for start_idx in range(0, total_rows, batch_size):
                    end_idx = min(start_idx + batch_size, total_rows)
                    logger.debug(f"Writing batch {start_idx}-{end_idx} to local CSV file: {file_path}")
                    batch_df = df.iloc[start_idx:end_idx]
                    header = start_idx == 0  # Write header only for the first batch
                    batch_df.to_csv(f, index=False, header=header, mode='a')
    except Exception as e:
        logger.error(f"Error writing CSV file: {e}")
        raise


def write_xlsx(df, file_path, batch_size=10000):
    """
    Write a pandas DataFrame to Excel using true streaming to maintain constant memory usage.
    """
    try:
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        if len(df) <= batch_size:
            # For small DataFrames, use pandas direct method
            df.to_excel(file_path, index=False)
        else:
            # For large DataFrames, use chunked approach
            options = {
                'constant_memory': True,
                'tmpdir': '/tmp',
            }

            # Only enable ZIP64 for large files
            if len(df) > 100000:
                options['use_zip64'] = True
                logger.warning(f"Large file detected ({len(df)} records), enabling ZIP64")

            workbook = xlsxwriter.Workbook(file_path, options)
            worksheet = workbook.add_worksheet()

            total_rows = len(df)
            current_row = 0

            # Write data in chunks
            for start_idx in range(0, total_rows, batch_size):
                end_idx = min(start_idx + batch_size, total_rows)
                logger.debug(f"Writing batch {start_idx}-{end_idx} to Excel file: {file_path}")

                batch_df = df.iloc[start_idx:end_idx].copy()

                # Write header only for first chunk
                if start_idx == 0:
                    # Write column headers
                    for col_idx, col_name in enumerate(batch_df.columns):
                        worksheet.write(current_row, col_idx, col_name)
                    current_row += 1

                # Write data rows
                for idx, row in batch_df.iterrows():
                    for col_idx, value in enumerate(row):
                        # Handle different data types appropriately
                        if pd.isna(value):
                            worksheet.write(current_row, col_idx, '')
                        elif isinstance(value, (int, float)):
                            worksheet.write(current_row, col_idx, value)
                        else:
                            worksheet.write(current_row, col_idx, str(value))
                    current_row += 1

                # Clean up batch immediately
                del batch_df
                gc.collect()

            # Close workbook to finalize the file
            workbook.close()
            logger.debug(f"Successfully wrote {total_rows} rows to {file_path}")

    except Exception as e:
        logger.error(f"Error writing Excel file to {file_path}: {e}")
        raise


def sftp_put_chunked(sftp, local_path, remote_path, chunk_size=8192):
    """
    Transfer a file in chunks to avoid loading entire file into memory
    """
    try:
        with open(local_path, 'rb') as local_file:
            with sftp.open(remote_path, 'wb') as remote_file:
                while True:
                    chunk = local_file.read(chunk_size)
                    if not chunk:
                        break
                    remote_file.write(chunk)
        logger.debug(f"Successfully transferred {local_path} to {remote_path} in chunks")
    except Exception as e:
        logger.error(f"Error during chunked transfer: {e}")
        raise


def sftp_put_from_db(module, submodule, db_type, db_name, job_id, file_dir, file_name, extensions=['parquet', 'csv', 'xlsx']):
    '''
    Read data from database in batches and transfer to SFTP server.
    This approach saves memory by not loading the entire dataset at once.
    '''
    conn = None
    sftp = None
    batch_size = int(os.getenv("JOB_DATA_BATCH_SIZE", 10000))

    try:
        # Open an SFTP connection
        conn = get_sftp_connection()
        sftp = conn.open_sftp()
        root_dir = os.getenv("SFTP_PATH", "./")
        remote_dir = join_path(root_dir, file_dir)

        # Ensure remote directory exists
        logger.debug(f"Create directory in SFTP with remote directory: {remote_dir}")
        mkdir_recursive(sftp, remote_dir)

        # Get total record count for batch processing
        _, total_records = load_job_from_app_db(module, submodule, db_type, db_name, job_id,
                                                page=0, page_size=1, get_size=True)
        total_batches = (total_records + batch_size - 1) // batch_size

        logger.debug(f"Processing {total_records} records in {total_batches} batches for {db_name}")

        os.makedirs(file_dir, exist_ok=True)

        for ext in extensions:
            local_path = f"{file_dir}/{file_name}.{ext}"
            remote_path = join_path(remote_dir, f"{file_name}.{ext}")

            logger.debug(f"Creating {ext.upper()} file: {local_path}")

            if ext == 'parquet':
                write_parquet_from_db(
                    module, submodule, db_type, db_name, job_id,
                    local_path, batch_size, total_batches
                )
            elif ext == 'csv':
                write_csv_from_db(
                    module, submodule, db_type, db_name, job_id,
                    local_path, batch_size, total_batches
                )
            elif ext == 'xlsx':
                write_xlsx_from_db(
                    module, submodule, db_type, db_name, job_id,
                    local_path, batch_size, total_batches
                )

            # Transfer file to SFTP
            logger.debug(f"Transferring {local_path} to SFTP at {remote_path}")
            sftp_put_chunked(sftp, local_path, remote_path)

            # Remove local file after transfer
            os.remove(local_path)
            logger.debug(f"Completed transfer and cleanup for {ext.upper()} file")

        # Close connection
        sftp.close()
        conn.close()

    except Exception as e:
        logger.exception(f"Error in sftp_put_from_db: {e}")
        raise e
    finally:
        if sftp:
            sftp.close()
        if conn:
            conn.close()


def write_parquet_from_db(module, submodule, db_type, db_name, job_id, local_path, batch_size, total_batches):
    try:
        os.makedirs(os.path.dirname(local_path), exist_ok=True)
        parquet_writer = None
        wrote_data = False

        for batch_num in range(total_batches):
            logger.debug(f"Processing parquet batch {batch_num + 1}/{total_batches}")
            batch_df = load_job_from_app_db(
                module, submodule, db_type, db_name,
                job_id=job_id,
                page=batch_num,
                page_size=batch_size
            )
            if batch_df is None or batch_df.empty:
                continue

            table = pa.Table.from_pandas(batch_df, preserve_index=False)
            if parquet_writer is None:
                parquet_writer = pq.ParquetWriter(local_path, table.schema, compression='snappy')
            parquet_writer.write_table(table)
            wrote_data = True
            del batch_df, table
            gc.collect()

        # If no data was written, create an empty file with correct schema
        if not wrote_data:
            # Try to get schema from model if possible, else create empty DataFrame
            table = pa.Table.from_pandas(pd.DataFrame())
            pq.write_table(table, local_path, compression='snappy')

        if parquet_writer:
            parquet_writer.close()
        logger.debug(f"Successfully created parquet file: {local_path}")

    except Exception as e:
        logger.error(f"Error writing parquet from DB batches: {e}")
        raise


def write_csv_from_db(module, submodule, db_type, db_name, job_id, local_path, batch_size, total_batches):
    try:
        os.makedirs(os.path.dirname(local_path), exist_ok=True)
        header_written = False
        wrote_data = False

        with open(local_path, 'w', newline='', encoding='utf-8') as f:
            for batch_num in range(total_batches):
                logger.debug(f"Processing CSV batch {batch_num + 1}/{total_batches}")
                batch_df = load_job_from_app_db(
                    module, submodule, db_type, db_name,
                    job_id=job_id,
                    page=batch_num,
                    page_size=batch_size
                )
                if batch_df is None or batch_df.empty:
                    continue

                write_header = not header_written
                batch_df.to_csv(f, index=False, header=write_header, mode='a')
                header_written = True
                wrote_data = True
                del batch_df
                gc.collect()

            # If no data was written, write empty header
            if not wrote_data:
                model = APP_DB_MODELS[module][submodule][db_type][db_name]
                columns = [col.name for col in model.__table__.columns]
                empty_df = pd.DataFrame(columns=columns)
                empty_df.to_csv(f, index=False)

        logger.debug(f"Successfully created CSV file: {local_path}")

    except Exception as e:
        logger.error(f"Error writing CSV from DB batches: {e}")
        raise


def write_xlsx_from_db(module, submodule, db_type, db_name, job_id, local_path, batch_size, total_batches):
    try:
        os.makedirs(os.path.dirname(local_path), exist_ok=True)
        _, total_records = load_job_from_app_db(module, submodule, db_type, db_name, job_id,
                                                page=0, page_size=1, get_size=True)
        options = {
            'constant_memory': True,
            'tmpdir': '/tmp',
        }
        if total_records > 100000:
            options['use_zip64'] = True
            logger.warning(f"Large Excel file estimated ({total_records} records), enabling ZIP64")

        workbook = xlsxwriter.Workbook(local_path, options)
        worksheet = workbook.add_worksheet()
        current_row = 0
        header_written = False
        wrote_data = False

        for batch_num in range(total_batches):
            logger.debug(f"Processing Excel batch {batch_num + 1}/{total_batches}")
            batch_df = load_job_from_app_db(
                module, submodule, db_type, db_name,
                job_id=job_id,
                page=batch_num,
                page_size=batch_size
            )
            if batch_df is None or batch_df.empty:
                continue

            if not header_written:
                for col_idx, col_name in enumerate(batch_df.columns):
                    worksheet.write(current_row, col_idx, col_name)
                current_row += 1
                header_written = True

            for idx, row in batch_df.iterrows():
                for col_idx, value in enumerate(row):
                    if pd.isna(value):
                        worksheet.write(current_row, col_idx, '')
                    elif isinstance(value, (int, float)):
                        worksheet.write(current_row, col_idx, value)
                    else:
                        worksheet.write(current_row, col_idx, str(value))
                current_row += 1
            wrote_data = True
            del batch_df
            gc.collect()

        # If no data was written, write empty header
        if not wrote_data:
            model = APP_DB_MODELS[module][submodule][db_type][db_name]
            columns = [col.name for col in model.__table__.columns]
            empty_df = pd.DataFrame(columns=columns)
            for col_idx, col_name in enumerate(empty_df.columns):
                worksheet.write(current_row, col_idx, col_name)

        workbook.close()
        logger.debug(f"Successfully created Excel file: {local_path}")

    except Exception as e:
        logger.error(f"Error writing Excel from DB batches: {e}")
        raise


def sftp_cleanup_dir(file_dir):
    """
    Remove all files and directories inside the specified file_dir on the SFTP server.

    Parameters:
    - file_dir: Directory path on the SFTP server to clean up.
    """
    conn = None
    sftp = None

    try:
        # Open an SFTP connection
        conn = get_sftp_connection()
        sftp = conn.open_sftp()
        root_dir = os.getenv("SFTP_PATH", "./")
        remote_dir = join_path(root_dir, file_dir)

        def recursive_delete(sftp, path):
            try:
                # Check if the path is a directory
                for item in sftp.listdir(path):
                    item_path = join_path(path, item)
                    try:
                        if sftp.stat(item_path).st_mode & 0o40000:  # Directory
                            recursive_delete(sftp, item_path)
                        else:  # File
                            sftp.remove(item_path)
                            logger.debug(f"Deleted file: {item_path}")
                    except Exception as e:
                        logger.error(f"Error deleting {item_path}: {e}")
                sftp.rmdir(path)
                logger.debug(f"Deleted directory: {path}")
            except Exception as e:
                logger.error(f"Error accessing {path}: {e}")

        # Start recursive deletion
        recursive_delete(sftp, remote_dir)
        logger.debug(f"Successfully cleaned up directory: {file_dir}")
    except Exception as e:
        logger.error(f"Error cleaning up directory {file_dir}: {e}")
        return
    finally:
        if sftp:
            sftp.close()
        if conn:
            conn.close()
