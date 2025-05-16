from flask import Flask
from flask_sqlalchemy import SQLAlchemy
import os
import codecs
from sqlalchemy import text  # Add this import for text() function

# Initialize minimal Flask app for migration
app = Flask(__name__)

# Get database URL from environment
db_url = os.environ.get('DATABASE_URL', 'sqlite:///span_freight.db')

# Decode escaped characters in the URL
db_url = codecs.decode(db_url, 'unicode_escape')

# Support Render.com's environment variables for PostgreSQL
if db_url.startswith('postgres://'):
    db_url = db_url.replace('postgres://', 'postgresql://', 1)

# Configure the app with the unescaped URL
app.config['SQLALCHEMY_DATABASE_URI'] = db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Print the URL for debugging (without credentials)
safe_url = db_url
if '@' in safe_url:
    # Hide credentials in logs
    parts = safe_url.split('@')
    credentials = parts[0].split('://')
    safe_url = f"{credentials[0]}://****:****@{parts[1]}"
print(f"Using database URL: {safe_url}")

db = SQLAlchemy(app)

def add_client_id_to_container():
    """Add client_id column to container table"""
    print("Starting migration: Adding client_id column to container table...")
    
    with app.app_context():
        try:
            # Check if we're using SQLite or PostgreSQL
            uri = app.config['SQLALCHEMY_DATABASE_URI']
            if uri.startswith('postgresql'):
                # PostgreSQL migration - first check if column exists
                result = db.session.execute(
                    text("SELECT column_name FROM information_schema.columns WHERE table_name='container' AND column_name='client_id'")
                )
                if not result.fetchone():
                    print("Column client_id does not exist, adding it...")
                    db.session.execute(text('ALTER TABLE container ADD COLUMN client_id INTEGER'))
                    db.session.execute(text('ALTER TABLE container ADD CONSTRAINT fk_container_client_id FOREIGN KEY (client_id) REFERENCES client(id)'))
                else:
                    print("Column client_id already exists, skipping.")
            else:
                # SQLite migration (simplified as SQLite has limited ALTER TABLE support)
                # Check if column exists first
                result = db.session.execute(text("PRAGMA table_info(container)"))
                columns = [row[1] for row in result.fetchall()]
                if 'client_id' not in columns:
                    print("Column client_id does not exist, adding it...")
                    db.session.execute(text('ALTER TABLE container ADD COLUMN client_id INTEGER REFERENCES client(id)'))
                else:
                    print("Column client_id already exists, skipping.")
            
            db.session.commit()
            print("Migration successful: client_id column added to container table (or already existed)")
        except Exception as e:
            db.session.rollback()
            print(f"Migration failed: {str(e)}")
            raise

if __name__ == '__main__':
    add_client_id_to_container()
    print("Migration script completed.")
