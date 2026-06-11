import os
import paramiko
from project.db_models import DB_MODELS
from project.utils import join_path


SFTP_HOST = 'localhost'
SFTP_PORT = 522
SFTP_USER = 'admin'
SFTP_PASSWORD = 'Ey123!'
SFTP_PATH = 'upload/'
WORKDIR = '/home/app/'


def get_stfp_connection():
    connection = paramiko.SSHClient()
    connection.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    connection.connect(
        hostname=SFTP_HOST,
        username=SFTP_USER,
        password=SFTP_PASSWORD,
        port=SFTP_PORT
    )
    return connection


def mkdir_recursive(sftp, remote_directory):
    """
    Recursively create directories on the SFTP server.

    Parameters:
    - sftp: The SFTP client object
    - remote_directory: Full path of the directory to create
    """
    # Split the directory path into parts and iterate over them
    dirs = remote_directory.split('/')
    current_path = ""

    for directory in dirs:
        if directory:  # Skip any empty parts
            current_path = join_path(current_path, directory)
            try:
                # Try to list the directory to check if it exists
                sftp.listdir(current_path)
            except IOError:
                # Directory doesn't exist, so create it
                sftp.mkdir(current_path)


def sftp_put(df, local_path):
    # Open an SFTP connection
    conn = get_stfp_connection()
    sftp = conn.open_sftp()
    root_dir = SFTP_PATH
    remote_dir = os.path.dirname(local_path)
    remote_filename = os.path.basename(local_path)

    # Ensure the remote directory exists
    remote_directory = join_path(root_dir, remote_dir)
    mkdir_recursive(sftp, remote_directory)
    sftp.chdir(remote_directory)

    sftp.put(df, remote_filename)

    # close connection
    sftp.close()
    conn.close()


if __name__ == '__main__':
    for _, file in DB_MODELS.items():
        print(f"Seeding {file} to SFTP server")
        path = join_path(WORKDIR, file)
        sftp_put(file, path)

    # test the SFTP connection and file upload
    # from tempfile import TemporaryDirectory
    # conn = get_stfp_connection()
    # sftp = conn.open_sftp()
    # sftp.chdir(SFTP_PATH)
    # with TemporaryDirectory() as directory:
    #     with open(f'{directory}/test.xlsx', 'wb+') as file:
    #         file.seek((500 * 1024 * 1024) - 1)
    #         file.write(b'\0')

    #     sftp.put(f'{directory}/test.xlsx', './test3.xlsx')
