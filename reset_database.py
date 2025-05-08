import os
import sys
import shutil
from datetime import datetime

# First make sure we can import from the application
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Now import from the app
from app import app, db, User

def reset_database():
    """
    Drop all tables and recreate the database from scratch
    """
    # First, make a backup of the current database
    app_root = app.root_path
    db_path = os.path.join(app_root, "container_tracking.db")
    
    if os.path.exists(db_path):
        # Create backup directory if it doesn't exist
        backup_dir = os.path.join(app_root, 'backups')
        os.makedirs(backup_dir, exist_ok=True)
        
        # Create backup with timestamp
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_file = os.path.join(backup_dir, f'db_before_reset_{timestamp}.db')
        
        # Copy database file to backup
        shutil.copy2(db_path, backup_file)
        print(f"Backup created at: {backup_file}")
    
    # Drop all tables and recreate the database
    with app.app_context():
        db.drop_all()  # This drops all tables
        db.create_all()  # This recreates them from the models
        print("Dropped and recreated all database tables")
        
        # Create an initial admin user
        admin = User(
            username='admin',
            email='admin@example.com',
            is_admin=True,
            created_at=datetime.now()
        )
        admin.set_password('admin')  # You should change this password immediately after login
        db.session.add(admin)
        db.session.commit()
        print("Created admin user (username: admin, password: admin)")
        
        print("Database reset completed successfully.")

if __name__ == '__main__':
    confirm = input("This will delete ALL data in the database. Are you sure? (type 'YES' to confirm): ")
    if confirm == 'YES':
        reset_database()
    else:
        print("Database reset cancelled.")
