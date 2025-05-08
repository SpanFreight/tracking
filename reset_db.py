#!/usr/bin/env python
"""
Clean Database Reset Script

This script completely resets the database without adding any sample data.
It creates empty tables with the correct schema.
"""
import os
import sqlite3
import shutil
from datetime import datetime

def reset_database(backup=True):
    """Reset the database with empty tables"""
    print("Starting database reset...")
    
    # Get the app directory and database path
    app_dir = os.path.dirname(os.path.abspath(__file__))
    db_path = os.path.join(app_dir, "container_tracking.db")
    
    # Create backup if requested and database exists
    if backup and os.path.exists(db_path) and os.path.isfile(db_path):  # Changed to use os.path.isfile instead of os.path.isfile
        print("Creating backup before reset...")
        backup_dir = os.path.join(app_dir, "backups")
        os.makedirs(backup_dir, exist_ok=True)
        
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_file = os.path.join(backup_dir, 'db_backup_before_reset_{}.db'.format(timestamp))
        
        try:
            shutil.copy2(db_path, backup_file)
            print("Created backup at: {}".format(backup_file))
        except Exception as e:
            print("Warning: Could not create backup: {}".format(str(e)))
    
    # Delete existing database if it exists
    if os.path.exists(db_path):
        try:
            os.remove(db_path)
            print("Deleted existing database.")
        except Exception as e:
            print("Error deleting database: {}".format(str(e)))
            return False
    
    # Create new database with empty tables
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        print("Creating tables with correct schema...")
        
        # Create User table with approved column
        print("Creating user table...")
        cursor.execute('''
        CREATE TABLE user (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username VARCHAR(64) UNIQUE,
            email VARCHAR(120) UNIQUE,
            password_hash VARCHAR(128),
            is_admin BOOLEAN DEFAULT 0,
            approved BOOLEAN DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        ''')
        
        cursor.execute("CREATE INDEX ix_user_username ON user (username)")
        cursor.execute("CREATE INDEX ix_user_email ON user (email)")
        
        # Create Container table
        print("Creating container table...")
        cursor.execute('''
        CREATE TABLE container (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            container_number VARCHAR(20) UNIQUE NOT NULL,
            container_type VARCHAR(20) NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        ''')
        
        # Create ContainerStatus table
        print("Creating container_status table...")
        cursor.execute('''
        CREATE TABLE container_status (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            status VARCHAR(20) NOT NULL,
            date TIMESTAMP NOT NULL,
            location VARCHAR(100) NOT NULL,
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            container_id INTEGER NOT NULL,
            FOREIGN KEY (container_id) REFERENCES container (id)
        )
        ''')
        
        # Create Vessel table
        print("Creating vessel table...")
        cursor.execute('''
        CREATE TABLE vessel (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name VARCHAR(100) NOT NULL,
            imo_number VARCHAR(20) UNIQUE NOT NULL,
            vessel_type VARCHAR(50) NOT NULL,
            capacity_teu INTEGER,
            current_location VARCHAR(100),
            current_destination VARCHAR(100),
            eta TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            status VARCHAR(20) DEFAULT 'En Route'
        )
        ''')
        
        # Create ContainerMovement table
        print("Creating container_movement table...")
        cursor.execute('''
        CREATE TABLE container_movement (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            operation_type VARCHAR(20) NOT NULL,
            operation_date TIMESTAMP NOT NULL,
            location VARCHAR(100) NOT NULL,
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            container_id INTEGER NOT NULL,
            vessel_id INTEGER NOT NULL,
            FOREIGN KEY (container_id) REFERENCES container (id),
            FOREIGN KEY (vessel_id) REFERENCES vessel (id)
        )
        ''')
        
        conn.commit()
        conn.close()
        
        print("\nDatabase reset completed successfully. All tables are empty.")
        return True
        
    except Exception as e:
        print("Error creating database: {}".format(str(e)))
        return False

# Add a function specifically for admin page reset to ensure no sample data
def admin_reset_database():
    """
    Reset database from admin interface without creating any sample data
    or default users - this creates a completely empty database
    """
    print("Starting complete database reset from admin interface...")
    return reset_database(backup=True)

if __name__ == "__main__":
    print("WARNING! This will DELETE your existing database and create a new empty one.")
    print("ALL YOUR DATA WILL BE LOST!")
    
    try:
        confirm = raw_input("Type 'YES' (all caps) to proceed: ")
    except NameError:
        confirm = input("Type 'YES' (all caps) to proceed: ")
    
    if confirm == "YES":
        if reset_database():
            print("Database reset completed successfully!")
            print("You will need to create a new admin user when you first start the application.")
        else:
            print("Error resetting database.")
    else:
        print("Operation cancelled.")
