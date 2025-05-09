import os
import multiprocessing

# Bind to the port provided by Render
bind = "0.0.0.0:" + os.environ.get("PORT", "8080")

# For render.com basic plan, use a single worker
workers = 1
worker_class = "sync"

# Increase timeout for slower startups
timeout = 120
keepalive = 5

# Memory optimization
worker_tmp_dir = "/dev/shm"
max_requests = 100
max_requests_jitter = 10

# Logging
loglevel = "info"
accesslog = "-"  # Log to stdout
errorlog = "-"   # Log to stderr

# Clean up on worker exit to prevent memory leaks
def worker_exit(server, worker):
    import gc
    gc.collect()
