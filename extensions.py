from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

# Initialize SQLAlchemy
db = SQLAlchemy()

# Function to generate password hash
def generate_password_hash_ext(password):
    return generate_password_hash(password)

# Function to check password hash
def check_password_hash_ext(password_hash, password):
    return check_password_hash(password_hash, password)
