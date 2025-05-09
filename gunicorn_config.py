import os
import multiprocessing

# Set basic gunicorn configurations
bind = "0.0.0.0:" + os.environ.get("PORT", "8080")
workers = 1  # Start with just 1 worker to minimize memory usage
worker_class = "sync"  # simpler worker class uses less memory
worker_connections = 1000
timeout = 60  # increase worker timeout to 60 seconds
keepalive = 2

# Reduce memory footprint
worker_tmp_dir = "/dev/shm"  # Use memory instead of disk for temp storage
max_requests = 100  # Restart workers after handling this many requests
max_requests_jitter = 10  # Add randomness to the restart interval

# Logging
accesslog = "-"
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s"'
errorlog = "-"
loglevel = "info"

def on_starting(server):
    """Log when server starts up"""
    print("Starting up Gunicorn server...")
    
def post_fork(server, worker):
    """Set memory limits after fork"""
    import resource
    # Set soft and hard limits to 512MB
    try:
        resource.setrlimit(resource.RLIMIT_AS, (536870912, 536870912))  # 512MB
        print(f"Memory limit set to 512MB for worker {worker.pid}")
    except Exception as e:
        print(f"Failed to set memory limit: {str(e)}")
