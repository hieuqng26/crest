import logging
# import psutil
import os
# import logstash


def get_logger(name):
    """Get a logger with the given name, configured to use Logstash."""
    logger = logging.getLogger(name)

    # Only add handler if logger doesn't have one yet
    if not logger.handlers:
        handler = logging.StreamHandler()
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)
        # Prevent propagation to root logger (which may have its own handler)
        logger.propagate = False

    return logger


# def get_memory_usage():
#     """Get current memory usage in MB"""
#     process = psutil.Process(os.getpid())
#     memory_info = process.memory_info()
#     return {
#         'rss': memory_info.rss / 1024 / 1024,  # Resident Set Size in MB
#         'vms': memory_info.vms / 1024 / 1024,  # Virtual Memory Size in MB
#         'percent': process.memory_percent()
#     }


# def log_memory_step(step_name, logger=None):
#     """Log memory usage for a specific step"""
#     memory = get_memory_usage()
#     if logger:
#         logger.info(f"Memory usage at [{step_name}]: RSS={memory['rss']:.1f}MB, VMS={memory['vms']:.1f}MB, Percent={memory['percent']:.1f}%")
#     else:
#         print(f"Memory usage at [{step_name}]: RSS={memory['rss']:.1f}MB, VMS={memory['vms']:.1f}MB, Percent={memory['percent']:.1f}%")
#     return memory
