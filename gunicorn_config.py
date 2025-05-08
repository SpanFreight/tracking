import multiprocessing

bind = "0.0.0.0:10000"  # Use port 10000 which Render expects
workers = multiprocessing.cpu_count() * 2 + 1
threads = 2
timeout = 120  # Increase timeout for long-running requests
worker_class = "gthread"
