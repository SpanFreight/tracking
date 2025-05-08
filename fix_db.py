import os
import sqlite3
import sys
from app import app, db, User, Container, ContainerStatus, Vessel, ContainerMovement
from datetime import datetime, timedelta

def locate_database():
    """Find the actual database file location"""
    print("\nDEBUG: Trying to locate database file...")
    
    # Get path from SQLAlchemy URI
    db_uri = app.config['SQLALCHEMY_DATABASE_URI']
    print(f"Database URI: {db_uri}")
    
    if db_uri.startswith('sqlite:///'):
        rel_path = db_uri.replace('sqlite:///', '')
        print(f"Relative path from URI: {rel_path}")
        
        # Check if it's an absolute path already
        if os.path.isabs(rel_path):
            abs_path = rel_path
            print(f"Path is already absolute: {abs_path}")
        else:
            # Try different base directories
            possible_paths = [
                # Flask app root directory
                os.path.join(app.root_path, rel_path),
                
                # Current working directory
                os.path.join(os.getcwd(), rel_path),
                
                # Parent of current directory
                os.path.join(os.path.dirname(os.getcwd()), rel_path),
                
                # Instance folder if defined
                os.path.join(app.instance_path, rel_path) if hasattr(app, 'instance_path') else None
            ]
            
            for path in filter(None, possible_paths):
                print(f"Checking: {path}")
                if os.path.exists(path):
                    abs_path = path
                    print(f"Found database at: {abs_path}")
                    return abs_path
            
            # If not found in common locations
            print("Database not found in common locations")
            abs_path = os.path.join(app.root_path, rel_path)
    else:
        print("Not a SQLite database URI")
        return None
    
    # Check if file exists
    if os.path.exists(abs_path):
        print(f"Database file exists: {abs_path}")
        print(f"File size: {os.path.getsize(abs_path) / 1024:.2f} KB")
    else:
        print(f"Database file does NOT exist at: {abs_path}")
        # Maybe it hasn't been created yet - check parent directory
        parent_dir = os.path.dirname(abs_path)
        print(f"Checking parent directory: {parent_dir}")
        if os.path.exists(parent_dir):
            print(f"Parent directory exists. Files in directory:")
            try:
                for filename in os.listdir(parent_dir):
                    if filename.endswith('.db'):
                        print(f"  - {filename}")
            except Exception as e:
                print(f"Error listing directory: {str(e)}")
        else:
            print("Parent directory does not exist")
    
    return abs_path

def reset_database():
    """Delete the existing database and create a new one with all features"""
    print("Completely resetting the database...")
    
    try:
        # Get database path
        if 'sqlite:///' in app.config['SQLALCHEMY_DATABASE_URI']:
            db_path = app.config['SQLALCHEMY_DATABASE_URI'].replace('sqlite:///', '')
            # Make path absolute if it's not already
            if not os.path.isabs(db_path):
                db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), db_path)
            
            print(f"Database located at: {db_path}")
            
            # Delete the database file if it exists
            if os.path.exists(db_path):
                print(f"Deleting existing database at {db_path}")
                os.remove(db_path)
                print("Database file deleted")
                
            # Special case: also check for journal and shm files
            for ext in ['-journal', '-shm', '-wal']:
                extra_file = f"{db_path}{ext}"
                if os.path.exists(extra_file):
                    print(f"Removing extra database file: {extra_file}")
                    os.remove(extra_file)
            
            # Use SQLAlchemy to create all tables
            print("Creating new database with all tables...")
            with app.app_context():
                db.drop_all()  # Make sure all tables are dropped
                db.create_all()  # Create all tables fresh
                
                # Create admin user
                print("Creating default admin user...")
                admin = User(
                    username='admin',
                    email='admin@spanfreight.com',
                    is_admin=True,
                    created_at=datetime.now()
                )
                admin.set_password('admin123')
                db.session.add(admin)
                db.session.flush()
                
                # Test query to make sure user was created successfully
                test_user = User.query.filter_by(username='admin').first()
                if not test_user:
                    print("ERROR: Failed to create admin user. Database schema issue detected.")
                    db.session.rollback()
                    return False
                
                # Create regular user
                regular_user = User(
                    username='user',
                    email='user@spanfreight.com',
                    is_admin=False,
                    created_at=datetime.now()
                )
                regular_user.set_password('user123')
                db.session.add(regular_user)
                
                # Add sample vessels
                print("Adding sample vessels...")
                vessels = [
                    {
                        'name': 'MSC Monaco',
                        'imo_number': 'IMO9726890',
                        'vessel_type': 'Container Ship',
                        'capacity_teu': 14000,
                        'current_location': 'Moroni',
                        'current_destination': 'Mutsamudu',
                        'status': 'En Route',
                        'eta': datetime.now() + timedelta(days=2)
                    },
                    {
                        'name': 'Maersk Alberta',
                        'imo_number': 'IMO9312999',
                        'vessel_type': 'Container Ship',
                        'capacity_teu': 9000,
                        'current_location': 'Mutsamudu',
                        'current_destination': 'Mombasa',
                        'status': 'Arrived',
                        'eta': datetime.now() - timedelta(days=1)
                    },
                    {
                        'name': 'CMA CGM Comoros',
                        'imo_number': 'IMO9778543',
                        'vessel_type': 'Container Ship',
                        'capacity_teu': 5000,
                        'current_location': 'Dar es Salaam',
                        'current_destination': 'Moroni',
                        'status': 'Departed',
                        'eta': datetime.now() + timedelta(days=3)
                    }
                ]
                
                vessel_objects = {}
                for vessel_data in vessels:
                    vessel = Vessel(**vessel_data)
                    db.session.add(vessel)
                    # Store for later use with containers
                    vessel_objects[vessel_data['name']] = vessel
                
                # Flush to get vessel IDs
                db.session.flush()
                
                # Add sample containers
                print("Adding sample containers...")
                container_data = [
                    {
                        'container_number': 'MSCU1234567',
                        'container_type': '20GP',
                        'location': 'Moroni',
                        'status': 'loaded',
                        'vessel': 'MSC Monaco'
                    },
                    {
                        'container_number': 'CMAU7654321',
                        'container_type': '40HC',
                        'location': 'Mutsamudu',
                        'status': 'discharged'
                    },
                    {
                        'container_number': 'MAEU5678901',
                        'container_type': '40GP',
                        'location': 'Moroni',
                        'status': 'emptied'
                    },
                    {
                        'container_number': 'TCNU1122334',
                        'container_type': '20RF',
                        'location': 'Mutsamudu',
                        'status': 'customs_hold'
                    },
                    {
                        'container_number': 'APLU5566778',
                        'container_type': '40RF',
                        'location': 'Moroni',
                        'status': 'in_transit'
                    },
                    {
                        'container_number': 'HLXU8877665',
                        'container_type': '40HC',
                        'location': 'Moroni',
                        'status': 'ready_for_pickup'
                    }
                ]
                
                # Create containers and their statuses
                for c_data in container_data:
                    # Create container
                    container = Container(
                        container_number=c_data['container_number'],
                        container_type=c_data['container_type'],
                        created_at=datetime.now() - timedelta(days=15)
                    )
                    db.session.add(container)
                    db.session.flush()  # Get container ID
                    
                    # Create status
                    status_date = datetime.now() - timedelta(days=5)
                    status = ContainerStatus(
                        status=c_data['status'],
                        date=status_date,
                        location=c_data['location'],
                        notes=f"Sample {c_data['status']} container",
                        container_id=container.id,
                        created_at=status_date
                    )
                    db.session.add(status)
                    
                    # If container should be on a vessel, create movement
                    if 'vessel' in c_data:
                        vessel = vessel_objects.get(c_data['vessel'])
                        if vessel:
                            movement = ContainerMovement(
                                operation_type='load',
                                operation_date=status_date,
                                location=c_data['location'],
                                notes=f"Loaded onto {c_data['vessel']}",
                                container_id=container.id,
                                vessel_id=vessel.id,
                                created_at=status_date
                            )
                            db.session.add(movement)
                
                # Create a container with multiple statuses and movements for history
                multi_container = Container(
                    container_number='HLXU1234567',
                    container_type='40GP',
                    created_at=datetime.now() - timedelta(days=30)
                )
                db.session.add(multi_container)
                db.session.flush()
                
                # Add status history
                status_dates = [
                    datetime.now() - timedelta(days=25),  # Initial empty status
                    datetime.now() - timedelta(days=20),  # Loaded
                    datetime.now() - timedelta(days=15),  # In transit
                    datetime.now() - timedelta(days=10),  # Arrived
                    datetime.now() - timedelta(days=5),   # Discharged
                ]
                
                status_types = ['emptied', 'loaded', 'in_transit', 'loaded', 'discharged']
                status_locations = ['Moroni', 'Moroni', 'At Sea', 'Mutsamudu', 'Mutsamudu']
                status_notes = [
                    'Empty container ready for loading',
                    'Loaded with cargo',
                    'In transit to destination',
                    'Arrived at destination',
                    'Discharged at destination port'
                ]
                
                for i in range(5):
                    status = ContainerStatus(
                        status=status_types[i],
                        date=status_dates[i],
                        location=status_locations[i],
                        notes=status_notes[i],
                        container_id=multi_container.id,
                        created_at=status_dates[i]
                    )
                    db.session.add(status)
                
                # Add movements for this container
                vessel1 = vessel_objects.get('MSC Monaco')
                if vessel1:
                    # Load movement
                    load_movement = ContainerMovement(
                        operation_type='load',
                        operation_date=status_dates[1],  # Same as loaded status
                        location='Moroni',
                        notes='Loaded for shipment to Mutsamudu',
                        container_id=multi_container.id,
                        vessel_id=vessel1.id,
                        created_at=status_dates[1]
                    )
                    db.session.add(load_movement)
                    
                    # Discharge movement
                    discharge_movement = ContainerMovement(
                        operation_type='discharge',
                        operation_date=status_dates[4],  # Same as discharged status
                        location='Mutsamudu',
                        notes='Discharged at destination',
                        container_id=multi_container.id,
                        vessel_id=vessel1.id,
                        created_at=status_dates[4]
                    )
                    db.session.add(discharge_movement)
                
                # Commit all changes
                db.session.commit()
                
                print("\nDatabase created successfully with sample data!")
                print("\nDefault users created:")
                print("Admin User:")
                print("  Username: admin")
                print("  Password: admin123")
                print("  Email: admin@spanfreight.com")
                
                print("\nRegular User:")
                print("  Username: user")
                print("  Password: user123")
                print("  Email: user@spanfreight.com")
                
                return True
                
    except Exception as e:
        print(f"ERROR during database reset: {str(e)}")
        print(f"Error type: {type(e).__name__}")
        return False

def reset_database_clean():
    """Reset the database but preserve admin users"""
    print("Starting database reset (preserving admin users)...")
    
    # First locate the database
    db_path = locate_database()
    
    try:
        # Backup admin users first
        admin_users = []
        with app.app_context():
            for user in User.query.filter_by(is_admin=True).all():
                admin_users.append({
                    'username': user.username,
                    'email': user.email,
                    'password_hash': user.password_hash,
                    'is_admin': True,
                    'created_at': user.created_at
                })
            print(f"Backed up {len(admin_users)} admin users")
            
            # Drop all tables and create fresh ones
            db.drop_all()
            db.create_all()
            print("Recreated all tables")
            
            # Restore admin users
            for admin in admin_users:
                user = User(
                    username=admin['username'],
                    email=admin['email'],
                    password_hash=admin['password_hash'],
                    is_admin=True,
                    created_at=admin['created_at']
                )
                db.session.add(user)
            
            # Commit changes
            db.session.commit()
            print(f"Restored {len(admin_users)} admin users")
            
            print("Database reset completed successfully!")
            return True
            
    except Exception as e:
        print(f"Error during database reset: {str(e)}")
        return False

if __name__ == "__main__":
    # Add option to choose between regular reset with sample data or clean reset
    print("Database Reset Options:")
    print("1. Reset with sample data (containers, vessels, users)")
    print("2. Reset with clean database (no sample data)")
    
    try:
        choice = input("Enter your choice (1 or 2): ")
        
        if choice == '1':
            print("WARNING: This will DELETE the ENTIRE database and create a new one with sample data.")
        else:
            print("WARNING: This will DELETE the ENTIRE database and create a new one with NO sample data.")
        
        print("ALL EXISTING DATA WILL BE LOST!")
        confirm = input("Are you sure you want to continue? (y/n): ")
        
        if confirm.lower() == 'y':
            if choice == '1':
                if reset_database():
                    print("\nDatabase reset completed successfully with sample data!")
                else:
                    print("\nFailed to reset database")
            else:
                if reset_database_clean():
                    print("\nDatabase reset completed successfully with NO sample data!")
                else:
                    print("\nFailed to reset database")
        else:
            print("\nOperation cancelled")
    except Exception as e:
        print(f"Error: {str(e)}")
