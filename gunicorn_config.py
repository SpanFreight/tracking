import os
import multiprocessing

# Basic configuration
bind = "0.0.0.0:" + os.environ.get("PORT", "8080")
workers = 1  # Use just one worker for small instances
worker_class = "sync"  # Simpler worker type uses less memory
timeout = 120  # Increase timeout to 2 minutes to allow for slower startup
keepalive = 5
preload_app = False  # Don't preload app to save memory during startup

# Memory optimization
worker_tmp_dir = "/dev/shm"  # Use RAM for temporary files
max_requests = 100  # Restart workers after handling this many requests
max_requests_jitter = 10  # Add randomness to prevent all workers restarting at once

# Logging
loglevel = "warning"  # Only log warnings and errors to reduce I/O
accesslog = "-"  # Log to stdout
errorlog = "-"   # Log to stderr
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s"'

# Hook to set memory limits
def post_fork(server, worker):
    """Configure worker after fork"""
    try:
        import resource
        # Limit memory to 450MB
        resource.setrlimit(resource.RLIMIT_AS, (450 * 1024 * 1024, 450 * 1024 * 1024))
        print(f"Memory limit set for worker {worker.pid}")
    except Exception as e:
        print(f"Failed to set memory limit: {str(e)}")

# Hook to clean up on exit
def worker_exit(server, worker):
    """Clean up on worker exit"""
    import gc
    gc.collect()
    print(f"Worker {worker.pid} exiting, garbage collected")
