from app import app as application

# Simple health check endpoint that responds quickly
@application.route('/health')
def health_check():
    return 'OK', 200

# This file provides a clean entry point for gunicorn
if __name__ == "__main__":
    application.run()
