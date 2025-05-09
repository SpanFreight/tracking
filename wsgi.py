from app import app as application

# Add a simple health check endpoint
@application.route('/health')
def health_check():
    return 'OK', 200

# This allows the file to be run directly during development
if __name__ == "__main__":
    application.run()
