import os
import multiprocessing

# Basic configuration
bind = "0.0.0.0:" + os.environ.get("PORT", "8080")
workers = 1  # Use just one worker for small instances
worker_class = "sync"  # Simpler worker type uses less memory
timeout = 120  # Increase timeout to 2 minutes
keepalive = 5
preload_app = False  # Don't preload to save memory

# Memory optimization
worker_tmp_dir = "/dev/shm"  # Use RAM for temporary storage
max_requests = 50  # Restart workers periodically
max_requests_jitter = 10  # Add randomness to prevent all workers restarting at once

# Logging
loglevel = "info"
accesslog = "-"  # Log to stdout
errorlog = "-"   # Log to stderr

# Set memory limits for workers
def post_fork(server, worker):
    try:
        import resource
        # Limit memory to 450MB (most Render.com instances have 512MB)
        resource.setrlimit(resource.RLIMIT_AS, (450 * 1024 * 1024, 450 * 1024 * 1024))
    except:
        pass

# Garbage collect on worker exit
def worker_exit(server, worker):
    import gc
    gc.collect()
