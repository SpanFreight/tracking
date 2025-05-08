#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Database Reset Tool

This script updates the user table schema to add the 'approved' column
while preserving all existing data.
"""
import os
import sys
import sqlite3
import shutil
from datetime import datetime

def backup_database():
    """Create a backup of the current database file"""
    print("Creating backup of the current database...")
    
    # Get the app directory and database path
    app_dir = os.path.dirname(os.path.abspath(__file__))
    db_path = os.path.join(app_dir, "container_tracking.db")
    
    if not os.path.exists(db_path):
        print("Database not found at: {}".format(db_path))
        return False, None
    
    # Create backup directory if it doesn't exist
    backup_dir = os.path.join(app_dir, "backups")
    os.makedirs(backup_dir, exist_ok=True)
    
    # Create backup filename with timestamp
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_file = os.path.join(backup_dir, 'db_backup_before_schema_update_{}.db'.format(timestamp))
    
    # Copy the database file to create a backup
    shutil.copy2(db_path, backup_file)
    print("Backup created at: {}".format(backup_file))
    
    return True, db_path

def fix_user_table(db_path):
    """Fix the user table by recreating it with the approved column"""
    print("Updating user table schema...")
    
    try:
        # Connect to the database
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Check if the user table exists
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='user'")
        if not cursor.fetchone():
            print("User table doesn't exist. Nothing to update.")
            conn.close()
            return False
        
        # Backup existing users data
        print("Backing up user data...")
        cursor.execute("SELECT * FROM user")
        users = cursor.fetchall()
        
        # Get column names from the existing table
        cursor.execute("PRAGMA table_info(user)")
        columns_info = cursor.fetchall()
        column_names = [column[1] for column in columns_info]
        
        if 'approved' in column_names:
            print("The 'approved' column already exists. No update needed.")
            conn.close()
            return True
            
        print("Found {} users to migrate.".format(len(users)))
        print("Current columns: {}".format(', '.join(column_names)))
        
        # Create a temporary table with the new schema
        print("Creating temporary table with new schema...")
        cursor.execute('''
        CREATE TABLE user_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username VARCHAR(64) UNIQUE,
            email VARCHAR(120) UNIQUE,
            password_hash VARCHAR(128),
            is_admin BOOLEAN DEFAULT 0,
            approved BOOLEAN DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        ''')
        
        # Recreate indexes that were on the original table
        cursor.execute("CREATE INDEX ix_user_new_username ON user_new (username)")
        cursor.execute("CREATE INDEX ix_user_new_email ON user_new (email)")
        
        # Copy data from the old table to the new one
        print("Migrating user data...")
        if users:
            # Build dynamic insert SQL based on available columns
            columns_to_copy = [col for col in column_names if col != 'approved']
            placeholders = ', '.join(['?' for _ in columns_to_copy])
            insert_sql = "INSERT INTO user_new ({}, approved) VALUES ({}, 1)".format(
                ', '.join(columns_to_copy), placeholders)
            
            # Map column indices - only copy what exists in the old table
            column_indices = []
            for col in columns_to_copy:
                column_indices.append(column_names.index(col))
                
            # Insert each user record
            for user in users:
                # Extract only the columns that exist in the original table
                user_values = [user[i] for i in column_indices]
                try:
                    cursor.execute(insert_sql, user_values)
                except Exception as e:
                    print("Error copying user: {}".format(str(e)))
        
        # Drop old table and rename new one
        print("Replacing old user table with updated schema...")
        cursor.execute("DROP TABLE user")
        cursor.execute("ALTER TABLE user_new RENAME TO user")
        
        # Commit changes and close connection
        conn.commit()
        conn.close()
        
        print("User table updated successfully!")
        return True
    
    except Exception as e:
        print("Error updating user table: {}".format(str(e)))
        try:
            conn.rollback()
            conn.close()
        except:
            pass
        return False

def main():
    """Main function to run the database reset"""
    print("\n===== Database Schema Update Tool =====")
    print("This tool will update your database schema to include the 'approved' column in the user table.")
    print("Your existing data will be preserved.\n")
    
    # Ask for confirmation
    confirm = input("Do you want to proceed? (yes/no): ").lower()
    if confirm != 'yes':
        print("Update cancelled.")
        return
    
    # Backup the database
    success, db_path = backup_database()
    if not success:
        print("Failed to backup the database. Aborting.")
        return
    
    # Update the user table
    if fix_user_table(db_path):
        print("\nSUCCESS: Database schema updated successfully!")
        print("\nYou can now start your application.")
    else:
        print("\nERROR: Failed to update the database schema.")
        print("Please restore from backup if needed.")

if __name__ == "__main__":
    main()
