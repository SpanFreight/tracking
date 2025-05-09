from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
import logging
import os

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configure SQLAlchemy with optimized settings for render.com
db = SQLAlchemy(engine_options={
    'pool_size': 10,  # Reduce from default to save memory
    'max_overflow': 20,
    'pool_timeout': 30,  # Faster timeout for connection acquisition
    'pool_recycle': 1800,  # Recycle connections every 30 minutes
    'pool_pre_ping': True  # Check connection validity before using it
})

# Function to generate password hash
def generate_password_hash_ext(password):
    return generate_password_hash(password)

# Function to check password hash
def check_password_hash_ext(password_hash, password):
    return check_password_hash(password_hash, password)

# Configuration function to help with render.com deployment
def configure_app_for_render(app):
    """Apply render.com specific configurations to the app"""
    # Log that we're configuring for Render
    logger.info("Configuring application for Render.com environment")
    
    # Set memory limits for gunicorn workers
    if 'RENDER' in os.environ:
        # Allow up to 512MB for memory-intensive operations
        app.config['MAX_CONTENT_LENGTH'] = 512 * 1024 * 1024
        
        # Disable some memory-intensive features when on render.com
        app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
        
        # Set smaller chunk size for file operations
        app.config['UPLOAD_CHUNK_SIZE'] = 4096  # 4KB chunks
        
        # Set shorter timeouts for external services
        app.config['SERVICE_TIMEOUT'] = 25  # 25 seconds timeout
        
        # Add reasonable pagination limits
        app.config['DEFAULT_PAGE_SIZE'] = 25
        app.config['MAX_PAGE_SIZE'] = 100
        
        logger.info("Render.com configuration applied")
    
    return app
