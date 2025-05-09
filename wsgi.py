from app import app

# Simple health check endpoint that responds quickly
@app.route('/health')
def health_check():
    return 'OK', 200

if __name__ == "__main__":
    app.run()
