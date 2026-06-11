"""
Root WSGI config
"""

import os
import gc
from dotenv import load_dotenv

load_dotenv()

bind = ['0.0.0.0:5000']

# Optimal number of workers based on CPU cores
workers = 5  # Adjust based on (2 x CPUs) + 1

# Use asynchronous worker class
worker_class = 'gevent'

# Increase threads for concurrency
threads = 4

# Logging
accesslog = "/var/log/gunicorn/access.log"
errorlog = "/var/log/gunicorn/error.log"

# Restart workers periodically to prevent memory leaks
max_requests = 1000
max_requests_jitter = 100

# Timeouts
timeout = 60
graceful_timeout = 60

# Preload the application
preload_app = True


def pre_request(worker, req):
    gc.disable()


def post_request(worker, req, environ, resp):
    gc.enable()
    gc.collect()
