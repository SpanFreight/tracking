# Span Freight Container Tracking System

A web application for tracking container shipments, managing vessels, and monitoring logistics operations.

## Database Management

### Resetting the Database

To reset the database and populate it with sample data:

```bash
python reset_db.py
```

This will delete any existing database and create a new one with:
- Admin user (username: admin, password: admin)
- Regular user (username: user, password: user)
- Sample vessels
- Sample containers with various statuses

### Creating an Admin User

```bash
python create_admin.py <username> <email> <password>
```

Example:
```bash
python create_admin.py manager manager@example.com secure_password
```

### Checking Database Status

To see the current database status:

```bash
python db_status.py
```

## Running the Application

```bash
python app.py
```

The application will be available at http://127.0.0.1:5000/

## Default Login Credentials

After resetting the database:

- Admin User:
  - Username: admin
  - Password: admin

- Regular User:
  - Username: user
  - Password: user

## Deployment on Render.com

This application is configured to be deployed on Render.com with a PostgreSQL database.

### Setup Instructions

1. Create a new Web Service on Render.com
   - Connect your Git repository
   - Use the following settings:
     - Build Command: `pip install -r requirements.txt`
     - Start Command: `gunicorn wsgi:app -c gunicorn_config.py`
   - Add environment variables in the Render dashboard:
     - `SECRET_KEY`: Your secret key
     - `DATABASE_URL`: Your PostgreSQL connection string
     - `FLASK_ENV`: production

2. Create a persistent storage disk
   - In your web service settings, add a disk
   - Set mount path to `/data`
   - Set size as needed (minimum 1 GB recommended)

### Database Setup

When first deployed, the application will create all necessary database tables automatically.

To manually reset the database, visit the admin panel and use the "System Settings" page.

## Local Development

To run locally:

1. Install dependencies: `pip install -r requirements.txt`
2. Create a `.env` file with environment variables
3. Run the app: `python run.py`
# tracking
# tracking
# tracking
# tracking
# tracking
# tracking
# tracking
# tracking
# tracking
# tracking
# tracking
# tracking
# tracking
# tracking
# tracking
# tracking
# tracking
# tracking
# tracking
# tracking
# tracking
# tracking
# tracking
# tracking
# tracking
# tracking
# tracking
# tracking
# tracking
# tracking
# tracking
