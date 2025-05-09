from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
import logging
import os

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configure SQLAlchemy with optimized settings for render.com
db = SQLAlchemy(engine_options={
    'pool_size': 5,  # Reduce from default to save memory
    'max_overflow': 10,
    'pool_timeout': 30,
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
    
    # Set memory-saving options
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['TEMPLATES_AUTO_RELOAD'] = False
    app.config['PRESERVE_CONTEXT_ON_EXCEPTION'] = False
    app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max upload
    
    # Set SQLAlchemy options for better memory usage
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        'pool_size': 5,
        'max_overflow': 10,
        'pool_recycle': 1800,
        'pool_pre_ping': True
    }
    
    return app
