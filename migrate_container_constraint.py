import os
from app import app, db
from sqlalchemy import text

# Function to modify constraints
def migrate_container_constraints():
    with app.app_context():
        try:
            # Get database engine
            engine = db.engine
            
            # Use connection.execute() with text() instead of engine.execute()
            with engine.connect() as connection:
                # PostgreSQL: Drop existing unique constraint and add composite constraint
                connection.execute(text('ALTER TABLE container DROP CONSTRAINT IF EXISTS container_container_number_key;'))
                connection.commit()
                
                connection.execute(text('CREATE UNIQUE INDEX IF NOT EXISTS uix_container_number_bl ON container (container_number, bl_number) WHERE bl_number IS NOT NULL;'))
                connection.commit()
                
                connection.execute(text('CREATE UNIQUE INDEX IF NOT EXISTS uix_container_number_null_bl ON container (container_number) WHERE bl_number IS NULL;'))
                connection.commit()
            
            print("Migration completed successfully!")
            return True
        except Exception as e:
            print(f"Error during migration: {str(e)}")
            return False

if __name__ == '__main__':
    migrate_container_constraints()
