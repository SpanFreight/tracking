from app import app, db
from app import PrintHistory, PrintAuthorization

# Create print history tables
with app.app_context():
    try:
        db.create_all()
        print("Successfully created print history tables")
    except Exception as e:
        print(f"Error creating print history tables: {e}")
