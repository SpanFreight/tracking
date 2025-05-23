from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, send_file
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta  # Add timedelta to the import
import os
import sys  # Add the sys import
import pandas as pd
from werkzeug.utils import secure_filename
import io
import logging
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.urls import url_parse
import flask  # Import flask module to access version information
import sqlalchemy  # Import sqlalchemy module to access version information
from dotenv import load_dotenv
from sqlalchemy.exc import OperationalError
from render_optimizations import optimize_for_render

# Remove the circular import
# from models import DeliveryPrint  <- DELETE THIS LINE

# Load environment variables from .env file
load_dotenv()

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize Flask app
app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'default-dev-key')
database_url = os.environ.get('DATABASE_URL', 'sqlite:///span_freight.db')

# Support Render.com's environment variables for PostgreSQL
if database_url.startswith('postgres://'):
    database_url = database_url.replace('postgres://', 'postgresql://', 1)

app.config['SQLALCHEMY_DATABASE_URI'] = database_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['ALLOWED_EXTENSIONS'] = {'xlsx', 'xls', 'csv'}
app.config['SITE_NAME'] = 'Span Freight'  # Add site name config

# Database configuration - update to handle Render.com environment
if os.environ.get('RENDER_PERSISTENT_STORAGE_PATH'):
    db_path = os.path.join(os.environ.get('RENDER_PERSISTENT_STORAGE_PATH'), 'span_freight.db')
    app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_path}'
    print(f"Using database at: {db_path}")
    
    # Create directories in persistent storage if they don't exist
    uploads_dir = os.path.join(os.environ.get('RENDER_PERSISTENT_STORAGE_PATH'), 'uploads')
    backups_dir = os.path.join(os.environ.get('RENDER_PERSISTENT_STORAGE_PATH'), 'backups')
    
    # Create directories if they don't exist
    os.makedirs(uploads_dir, exist_ok=True)
    os.makedirs(backups_dir, exist_ok=True)
    
    # Update upload folder configuration
    app.config['UPLOAD_FOLDER'] = uploads_dir
    app.config['BACKUPS_DIR'] = backups_dir

# Create upload folder if it doesn't exist
os.makedirs(os.path.join(app.root_path, app.config['UPLOAD_FOLDER']), exist_ok=True)
# Create static folder if it doesn't exist
os.makedirs(os.path.join(app.root_path, 'static', 'img'), exist_ok=True)

# Initialize SQLAlchemy without binding it to app yet
db = SQLAlchemy()
db.init_app(app)

# Initialize Flask-Login after app is created
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message_category = 'info'
login_manager.login_message = 'Please log in to access this page.'  # Add a friendly login message

# Now import models after db is initialized to avoid circular imports
from models import Container, ContainerStatus, Vessel, ContainerMovement, User, PrintHistory, PrintAuthorization, PrintAccessRequest, DeliveryCounter

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# Define models here instead of importing them
class Container(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    container_number = db.Column(db.String(20), nullable=False)  # Remove unique=True constraint
    container_type = db.Column(db.String(20), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # New fields
    loading_port = db.Column(db.String(100))
    final_destination = db.Column(db.String(100))
    opr = db.Column(db.String(50))
    arrival_date = db.Column(db.DateTime)
    bl_number = db.Column(db.String(50))
    stripping_date = db.Column(db.DateTime)  # Added field for stripping date
    
    # Add client relationship
    client_id = db.Column(db.Integer, db.ForeignKey('client.id'), nullable=True)
    
    # Relationship with ContainerStatus
    statuses = db.relationship('ContainerStatus', backref='container', lazy=True, cascade="all, delete-orphan")
    
    # Relationship with ContainerMovement
    movements = db.relationship('ContainerMovement', backref='container', lazy=True, cascade="all, delete-orphan")
    
    # Add composite unique constraint for container_number + bl_number
    __table_args__ = (
        db.UniqueConstraint('container_number', 'bl_number', name='uix_container_number_bl'),
    )
    
    def __repr__(self):
        return f"Container('{self.container_number}', '{self.container_type}')"
    
    def get_current_status(self):
        """Get the most recent status for this container"""
        # Use created_at instead of date for sorting
        latest_status = ContainerStatus.query.filter_by(container_id=self.id).order_by(ContainerStatus.created_at.desc()).first()
        return latest_status

    def get_current_location(self):
        """Get the current location of the container (vessel or port)"""
        current_status = self.get_current_status()
        if not current_status:
            return None
        
        # Check if container is on a vessel - use created_at instead of operation_date
        latest_movement = ContainerMovement.query.filter_by(
            container_id=self.id
        ).order_by(ContainerMovement.created_at.desc()).first()
        
        if not latest_movement:
            return {"type": "port", "location": current_status.location, "since": current_status.date}
        
        if latest_movement.operation_type == 'load':
            vessel = Vessel.query.get(latest_movement.vessel_id)
            return {
                "type": "vessel", 
                "vessel": vessel,
                "since": latest_movement.operation_date,
                "destination": vessel.current_destination
            }
        else:  # discharged
            return {"type": "port", "location": latest_movement.location, "since": latest_movement.operation_date}

    def is_on_departed_vessel(self):
        """Check if the container is on a vessel that has departed"""
        current_location = self.get_current_location()
        if (current_location and current_location['type'] == 'vessel'):
            vessel = current_location['vessel']
            return vessel.status == 'Departed'
        return False

    def get_current_vessel(self):
        """Helper method to directly get the vessel (if any) associated with this container"""
        current_location = self.get_current_location()
        if (current_location and current_location['type'] == 'vessel'):
            return current_location['vessel']
        return None
        
    def get_last_vessel(self):
        """Get the most recent vessel this container was on (for discharged containers)"""
        # Find the most recent discharge movement
        latest_discharge = ContainerMovement.query.filter_by(
            container_id=self.id,
            operation_type='discharge'
        ).order_by(ContainerMovement.created_at.desc()).first()
        
        # If found, return the vessel from that movement
        if latest_discharge:
            return latest_discharge.vessel
        
        return None
    
    def can_print_delivery_order(self, user_id):
        """Check if a user is authorized to print a delivery order for this container"""
        # Only discharged containers can have delivery orders
        latest_status = self.get_current_status()
        if not latest_status or latest_status.status != 'discharged':
            return False
            
        # Admin users can always print
        user = User.query.get(user_id)
        if user and user.is_admin:
            return True
        
        # Check if there's any print history
        print_history = PrintHistory.query.filter_by(container_id=self.id).order_by(PrintHistory.print_date.desc()).all()
        
        # If no print history, first print is allowed
        if not print_history:
            return True
        
        # If there was a discharge event after the last print, allow printing
        last_print_date = print_history[0].print_date if print_history else None
        
        if last_print_date:
            # Check if the container was loaded and then discharged after the last print
            load_after_print = ContainerMovement.query.filter(
                ContainerMovement.container_id == self.id,
                ContainerMovement.operation_type == 'load',
                ContainerMovement.created_at > last_print_date
            ).first()
            
            discharge_after_load = False
            if load_after_print:
                discharge_after_load = ContainerMovement.query.filter(
                    ContainerMovement.container_id == self.id,
                    ContainerMovement.operation_type == 'discharge',
                    ContainerMovement.created_at > load_after_print.created_at
                ).first()
                
            if discharge_after_load:
                return True
        
        # Check if user has a valid authorization
        auth = PrintAuthorization.query.filter_by(
            container_id=self.id,
            user_id=user_id,
            used=False
        ).first()
        
        return auth is not None

class ContainerStatus(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    status = db.Column(db.String(20), nullable=False)  # 'loaded', 'discharged', 'emptied'
    date = db.Column(db.DateTime, nullable=False)
    location = db.Column(db.String(100), nullable=False)
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    # Foreign Key
    container_id = db.Column(db.Integer, db.ForeignKey('container.id'), nullable=False)
    
    def __repr__(self):
        return f"ContainerStatus('{self.status}', '{self.date}')"

class Vessel(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    # Rename the column comment while keeping the technical name for compatibility
    imo_number = db.Column(db.String(20), unique=True, nullable=False)  # Voyage Number
    vessel_type = db.Column(db.String(50), nullable=False)
    capacity_teu = db.Column(db.Integer)  # Twenty-foot Equivalent Units
    current_location = db.Column(db.String(100))
    current_destination = db.Column(db.String(100))
    eta = db.Column(db.DateTime)  # Estimated Time of Arrival
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    status = db.Column(db.String(20), default='En Route')  # 'En Route', 'Arrived', 'Departed'
    # Relationship with ContainerMovement
    container_movements = db.relationship('ContainerMovement', backref='vessel', lazy=True)
    
    def __repr__(self):
        return f"Vessel('{self.name}', Voyage: '{self.imo_number}')"
    
    def get_loaded_containers(self):
        """Get containers currently loaded on this vessel"""
        # Find containers that were loaded but not yet discharged
        loaded_containers = []
        container_ids = set()
        # Get all movements for this vessel ordered by container ID and created_at (newest first)
        movements = ContainerMovement.query.filter_by(vessel_id=self.id).order_by(
            ContainerMovement.container_id, ContainerMovement.created_at.desc()
        ).all()
        for movement in movements:
            # Only check each container once (its most recent movement)
            if movement.container_id not in container_ids:
                container_ids.add(movement.container_id)
                # If the most recent movement is 'load', the container is still on the vessel
                if movement.operation_type == 'load':
                    loaded_containers.append(movement.container)
        return loaded_containers

class ContainerMovement(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    operation_type = db.Column(db.String(20), nullable=False)  # 'load' or 'discharge'
    operation_date = db.Column(db.DateTime, nullable=False)
    location = db.Column(db.String(100), nullable=False)  # Port location
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    # Foreign Keys
    container_id = db.Column(db.Integer, db.ForeignKey('container.id'), nullable=False)
    vessel_id = db.Column(db.Integer, db.ForeignKey('vessel.id'), nullable=False)
    
    def __repr__(self):
        return f"ContainerMovement('{self.operation_type}', '{self.operation_date}')"

# User model for authentication
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), index=True, unique=True)
    email = db.Column(db.String(120), index=True, unique=True)
    password_hash = db.Column(db.String(128))
    is_admin = db.Column(db.Boolean, default=False)  # Make sure this column is defined
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f'<User {self.username}>'
    
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)  # Fix bug: use password_hash instead of password

class PrintHistory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    container_id = db.Column(db.Integer, db.ForeignKey('container.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    print_date = db.Column(db.DateTime, default=datetime.utcnow)
    do_number = db.Column(db.String(20), nullable=False)
    authorized_by_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)  # Nullable for first print
    
    # Relationships
    container = db.relationship('Container', backref=db.backref('print_history', lazy=True))
    user = db.relationship('User', foreign_keys=[user_id])
    authorized_by = db.relationship('User', foreign_keys=[authorized_by_id])

class PrintAuthorization(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    container_id = db.Column(db.Integer, db.ForeignKey('container.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    authorized_by_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    used = db.Column(db.Boolean, default=False)
    
    # Relationships
    container = db.relationship('Container', backref=db.backref('print_authorizations', lazy=True))
    user = db.relationship('User', foreign_keys=[user_id])
    authorized_by = db.relationship('User', foreign_keys=[authorized_by_id])

# Add a new model for print access requests - add this with your other models
class PrintAccessRequest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    container_id = db.Column(db.Integer, db.ForeignKey('container.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    requested_at = db.Column(db.DateTime, default=datetime.utcnow)
    status = db.Column(db.String(20), default='pending')  # pending, approved, rejected
    
    # Relationships
    container = db.relationship('Container', backref=db.backref('print_requests', lazy=True))
    user = db.relationship('User', backref=db.backref('print_requests', lazy=True))

# Add a model for the delivery order counter
class DeliveryCounter(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    counter = db.Column(db.Integer, default=1)
    last_updated = db.Column(db.DateTime, default=datetime.utcnow)

# Add Client model after existing models
class Client(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    phone = db.Column(db.String(20))
    email = db.Column(db.String(100))
    address = db.Column(db.Text)
    contact_person = db.Column(db.String(100))
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationship with Container
    containers = db.relationship('Container', backref='client', lazy=True)
    
    def __repr__(self):
        return f"Client('{self.name}')"
        
    def get_container_count(self):
        """Get count of containers associated with this client"""
        return Container.query.filter_by(client_id=self.id).count()

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']

def map_location_codes(location):
    """Map IATA port codes to human-readable names"""
    location_mapping = {
        'KMYVA': 'Moroni',
        'KMMUT': 'Mutsamudu'
    }
    return location_mapping.get(location, location)

from pagination import Pagination

# Add this before your first route definition, after Flask app is created
@app.template_filter('nl2br')
def nl2br_filter(s):
    """Convert newlines to <br> for HTML display."""
    if not s:
        return ''
    return s.replace('\n', '<br>')

@app.route('/')
@login_required
def index():
    # Automatically update vessel statuses when visiting homepage
    update_vessel_statuses_auto()
    
    # Get location filter from query parameters, default to 'Moroni'
    location_filter = request.args.get('location', 'Moroni')
    # Map location filter if it's a code
    location_filter = map_location_codes(location_filter)
    
    # Get status filter from query parameters
    status_filter = request.args.get('status', '')
    
    # Get sorting parameters from the request
    sort_by = request.args.get('sort', 'arrival_date')  # Changed default to arrival_date
    sort_order = request.args.get('order', 'desc')    # Default to descending order for newest first
    
    # Get search parameter
    search_term = request.args.get('search', '').strip()
    
    # Get page parameter with default value of 1
    page = request.args.get('page', 1, type=int)
    per_page = 25  # Show 25 containers per page
    
    # Start with a base query for all containers
    # If search term provided, filter containers by container number (case insensitive)
    if search_term:
        # Search by container number, type, BL number, vessel name, etc.
        all_containers_query = Container.query.filter(
            db.or_(
                Container.container_number.ilike(f'%{search_term}%'),
                Container.container_type.ilike(f'%{search_term}%'),
                Container.bl_number.ilike(f'%{search_term}%'),
                Container.opr.ilike(f'%{search_term}%')
            )
        )
    else:
        # Special case for sorting by status since it's in a related table
        if sort_by == 'status':
            # We need to create a subquery to get the latest status for each container
            latest_status_subquery = db.session.query(
                ContainerStatus.container_id,
                db.func.max(ContainerStatus.created_at).label('max_date')
            ).group_by(ContainerStatus.container_id).subquery('latest_status')
            
            # Join with the main container table and the latest status
            query = db.session.query(Container, ContainerStatus.status)\
                .outerjoin(latest_status_subquery, Container.id == latest_status_subquery.c.container_id)\
                .outerjoin(ContainerStatus, db.and_(
                    ContainerStatus.container_id == latest_status_subquery.c.container_id,
                    ContainerStatus.created_at == latest_status_subquery.c.max_date
                ))
                
            # Apply sorting
            if sort_order == 'asc':
                query = query.order_by(db.asc(ContainerStatus.status), db.asc(Container.container_number))
            else:
                query = query.order_by(db.desc(ContainerStatus.status), db.desc(Container.container_number))
                
            # Execute the query and extract containers
            all_containers_query = [container for container, _ in query.all()]
        else:
            # For other sort fields, use the standard approach
            if sort_by == 'container_number':
                if sort_order == 'desc':
                    all_containers_query = Container.query.order_by(Container.container_number.desc())
                else:
                    all_containers_query = Container.query.order_by(Container.container_number)
            elif sort_by == 'container_type':
                if sort_order == 'desc':
                    all_containers_query = Container.query.order_by(Container.container_type.desc())
                else:
                    all_containers_query = Container.query.order_by(Container.container_type)
            elif sort_by == 'arrival_date':
                # Sort by arrival_date with special handling for NULL values
                if sort_order == 'desc':
                    # For descending order, put NULL values last (oldest)
                    # Updated syntax: pass tuples directly as positional arguments, not in a list
                    all_containers_query = Container.query.order_by(
                        db.case((Container.arrival_date == None, 2), else_=1),
                        Container.arrival_date.desc()
                    )
                else:
                    # For ascending order, put NULL values first (oldest)
                    # Updated syntax: pass tuples directly as positional arguments, not in a list
                    all_containers_query = Container.query.order_by(
                        db.case((Container.arrival_date == None, 0), else_=1),
                        Container.arrival_date
                    )
            else:  # Default to created_at
                if sort_order == 'desc':
                    all_containers_query = Container.query.order_by(Container.created_at.desc())
                else:
                    all_containers_query = Container.query.order_by(Container.created_at)
                
            # If we didn't special case for status, we need to execute the query
            all_containers_query = all_containers_query.all()
    
    # Further processing of containers (filtering by location, etc.)
    # Get containers that aren't on departed vessels
    all_containers = []
    for container in all_containers_query:
        # Skip containers that are on departed vessels
        if not container.is_on_departed_vessel():
            all_containers.append(container)
    
    # Get all unique locations from container statuses and map them
    locations = set()
    statuses = set()  # Collect all available statuses for the UI
    for container in all_containers:
        status = container.get_current_status()
        if status:
            # Handle location mapping
            if status.location:
                # Map location codes to readable names
                mapped_location = map_location_codes(status.location)
                locations.add(mapped_location)
                # Update the location in the status
                if status.location != mapped_location:
                    status.location = mapped_location
            
            # Add status to the set of available statuses
            if status.status:
                statuses.add(status.status)
    
    # Filter containers if a location is specified
    if location_filter:
        filtered_containers = []
        for container in all_containers:
            current_status = container.get_current_status()
            if current_status:
                # Map the status location
                current_location = map_location_codes(current_status.location)
                if current_location == location_filter:
                    filtered_containers.append(container)
        containers = filtered_containers
    else:
        containers = all_containers
    
    # Filter containers by status if specified
    if status_filter:
        if status_filter == 'other':
            # Filter containers with status OTHER THAN loaded, discharged, emptied, or full
            status_filtered = []
            for container in containers:
                current_status = container.get_current_status()
                if current_status and current_status.status not in ['loaded', 'discharged', 'emptied', 'full', 'full_deliveried']:
                    status_filtered.append(container)
            containers = status_filtered
        elif status_filter == 'full':
            # Special case for full status - include 'full_deliveried' as well
            status_filtered = []
            
            # Get the full type sub-filter
            full_type = request.args.get('full_type', 'all')
            
            for container in containers:
                current_status = container.get_current_status()
                if current_status:
                    if full_type == 'all' and current_status.status in ['full', 'full_deliveried']:
                        status_filtered.append(container)
                    elif full_type == 'full_only' and current_status.status == 'full':
                        status_filtered.append(container)
                    elif full_type == 'full_deliveried' and current_status.status == 'full_deliveried':
                        status_filtered.append(container)
            containers = status_filtered
        else:
            status_filtered = []
            for container in containers:
                current_status = container.get_current_status()
                if current_status and current_status.status == status_filter:
                    status_filtered.append(container)
            containers = status_filtered
    
    # Apply pagination to the filtered containers list
    pagination = Pagination(containers, page, per_page, 'index', 
                           location=location_filter,
                           status=status_filter,  # Pass status filter to pagination for URL preservation
                           full_type=request.args.get('full_type', 'all'),  # Add full_type to pagination
                           sort=sort_by, 
                           order=sort_order,
                           search=search_term)
    containers = pagination.items  # Use the paginated items
    
    # Get vessels for the page
    vessels = Vessel.query.all()
    now = datetime.now()
    
    # Count containers by location (excluding those on departed vessels)
    location_counts = {}
    for location in sorted(locations):
        count = sum(1 for c in all_containers if c.get_current_status() and 
                   map_location_codes(c.get_current_status().location) == location)
        location_counts[location] = count
    
    # Calculate loaded and discharged counts for the selected location or overall
    loaded_count = 0
    discharged_count = 0
    # These counts should be based on the filtered containers (by location)
    for container in containers:
        latest_status = container.get_current_status()
        if latest_status:
            if latest_status.status == 'loaded':
                loaded_count += 1
            elif latest_status.status == 'discharged':
                discharged_count += 1
    
    # Define standard locations
    standard_locations = ['Moroni', 'Mutsamudu']
    
    # Get other locations (any location not in standard_locations)
    other_locations = [loc for loc in sorted(locations) if loc not in standard_locations]
    
    # For each container, pre-fetch its vessel to ensure it's available in templates
    for container in containers:
        # Use the get_current_vessel helper to ensure vessel information is populated
        container.current_vessel = container.get_current_vessel()
    
    # Calculate total statistics for the entire database
    # Get total containers count
    total_container_count = Container.query.count()
    
    # Get total loaded containers count using subquery to find latest status
    latest_status_subquery = db.session.query(
        ContainerStatus.container_id,
        db.func.max(ContainerStatus.created_at).label('max_date')
    ).group_by(ContainerStatus.container_id).subquery()
    
    # Query for loaded containers count
    total_loaded_count = db.session.query(Container)\
        .join(latest_status_subquery, Container.id == latest_status_subquery.c.container_id)\
        .join(ContainerStatus, db.and_(
            ContainerStatus.container_id == latest_status_subquery.c.container_id,
            ContainerStatus.created_at == latest_status_subquery.c.max_date,
            ContainerStatus.status == 'loaded'
        ))\
        .count()
        
    # Query for discharged containers count
    total_discharged_count = db.session.query(Container)\
        .join(latest_status_subquery, Container.id == latest_status_subquery.c.container_id)\
        .join(ContainerStatus, db.and_(
            ContainerStatus.container_id == latest_status_subquery.c.container_id,
            ContainerStatus.created_at == latest_status_subquery.c.max_date,
            ContainerStatus.status == 'discharged'
        ))\
        .count()
    
    # Query for emptied containers count
    total_emptied_count = db.session.query(Container)\
        .join(latest_status_subquery, Container.id == latest_status_subquery.c.container_id)\
        .join(ContainerStatus, db.and_(
            ContainerStatus.container_id == latest_status_subquery.c.container_id,
            ContainerStatus.created_at == latest_status_subquery.c.max_date,
            ContainerStatus.status == 'emptied'
        ))\
        .count()
        
    # Query for full containers count
    total_full_count = db.session.query(Container)\
        .join(latest_status_subquery, Container.id == latest_status_subquery.c.container_id)\
        .join(ContainerStatus, db.and_(
            ContainerStatus.container_id == latest_status_subquery.c.container_id,
            ContainerStatus.created_at == latest_status_subquery.c.max_date,
            ContainerStatus.status == 'full'
        ))\
        .count()
    
    return render_template('index.html', 
                          containers=containers, 
                          vessels=vessels, 
                          now=now,
                          location_filter=location_filter,
                          status_filter=status_filter,  # Pass status filter to template
                          standard_locations=standard_locations,
                          other_locations=other_locations,
                          location_counts=location_counts,
                          statuses=sorted(statuses),  # Pass available statuses to template
                          loaded_count=loaded_count,  # This is for the current filtered view
                          discharged_count=discharged_count,  # This is for the current filtered view
                          sort_by=sort_by,
                          sort_order=sort_order,
                          pagination=pagination,
                          # Add the total counts for the entire database
                          total_container_count=total_container_count,
                          total_loaded_count=total_loaded_count,
                          total_discharged_count=total_discharged_count,
                          total_emptied_count=total_emptied_count,  # Add this line
                          total_full_count=total_full_count)         # Add this line

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    if request.method == 'POST':
        username_or_email = request.form['username']
        password = request.form['password']
        remember_me = 'remember_me' in request.form
        
        # Try to find user by username first
        user = User.query.filter_by(username=username_or_email).first()
        
        # If not found by username, try email
        if user is None:
            user = User.query.filter_by(email=username_or_email).first()
            
        # Check if the user exists and password is correct
        if user is None or not user.check_password(password):
            flash('Invalid username/email or password', 'danger')
            return redirect(url_for('login'))
            
        # Log the user in
        login_user(user, remember=remember_me)
        flash(f'Welcome back, {user.username}!', 'success')
        # Redirect to the page the user was trying to access or index
        next_page = request.args.get('next')
        if not next_page or url_parse(next_page).netloc != '':
            next_page = url_for('index')
        return redirect(next_page)
    return render_template('login.html')

# Logout route
@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out successfully', 'info')
    return redirect(url_for('login'))

# Register route
@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']
        confirm_password = request.form['confirm_password']
        # Check if username or email already exists
        if User.query.filter_by(username=username).first():
            flash('Username already exists. Please choose a different username.', 'danger')
            return redirect(url_for('register'))
        if User.query.filter_by(email=email).first():
            flash('Email already registered. Please use a different email.', 'danger')
            return redirect(url_for('register'))
        # Check if passwords match
        if password != confirm_password:
            flash('Passwords do not match.', 'danger')
            return redirect(url_for('register'))
        # Create new user
        user = User(username=username, email=email)
        user.set_password(password)
        # Make the first registered user an admin
        if User.query.count() == 0:
            user.is_admin = True
        db.session.add(user)
        db.session.commit()
        flash('Registration successful! You can now login.', 'success')
        return redirect(url_for('login'))
    return render_template('register.html')

# Protected routes should use @login_required decorator
@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    # Initialize form errors
    form_errors = {}
    success_message = None
    
    if request.method == 'POST':
        # Determine which form was submitted
        form_type = request.form.get('form_type')
        
        if form_type == 'profile_info':
            # Handle profile information update (username, email)
            username = request.form.get('username', '').strip()
            email = request.form.get('email', '').strip()
            
            # Validate inputs
            if not username:
                form_errors['username'] = 'Username cannot be empty'
            
            if not email:
                form_errors['email'] = 'Email cannot be empty'
            elif '@' not in email:
                form_errors['email'] = 'Please enter a valid email address'
                
            # Check if username or email already exists (but ignore current user)
            if username != current_user.username:
                existing_user = User.query.filter_by(username=username).first()
                if existing_user:
                    form_errors['username'] = 'Username already taken'
                    
            if email != current_user.email:
                existing_email = User.query.filter_by(email=email).first()
                if existing_email:
                    form_errors['email'] = 'Email already registered'
            
            # If no validation errors, update the user
            if not form_errors:
                current_user.username = username
                current_user.email = email
                db.session.commit()
                success_message = 'Profile updated successfully!'
                
        elif form_type == 'change_password':
            # Handle password change
            current_password = request.form.get('current_password', '')
            new_password = request.form.get('new_password', '')
            confirm_password = request.form.get('confirm_password', '')
            
            # Validate inputs
            if not current_password:
                form_errors['current_password'] = 'Please enter your current password'
            elif not current_user.check_password(current_password):
                form_errors['current_password'] = 'Current password is incorrect'
                
            if not new_password:
                form_errors['new_password'] = 'New password cannot be empty'
            elif len(new_password) < 6:
                form_errors['new_password'] = 'Password must be at least 6 characters'
                
            if new_password != confirm_password:
                form_errors['confirm_password'] = 'Passwords do not match'
                
            # If no validation errors, update the password
            if not form_errors:
                current_user.set_password(new_password)
                db.session.commit()
                success_message = 'Password updated successfully!'
    
    return render_template(
        'profile.html', 
        user=current_user, 
        form_errors=form_errors,
        success_message=success_message
    )

# Add this new API endpoint for client autocomplete
@app.route('/api/search-clients/<query>')
@login_required
def search_clients(query):
    """API endpoint to search for clients by partial name"""
    if not query or len(query) < 2:
        return jsonify([])
    
    # Search for clients that match the query string (case-insensitive)
    clients = Client.query.filter(
        Client.name.ilike(f'%{query}%')
    ).limit(10).all()
    
    results = []
    for client in clients:
        results.append({
            'id': client.id,
            'name': client.name,
            'contact_person': client.contact_person or ""
        })
    
    return jsonify(results)

# Modify the add_container route to handle the client name autocomplete
@app.route('/containers/add', methods=['GET', 'POST'])
@login_required
def add_container():
    if request.method == 'POST':
        # Check if it's an Excel import or a single container add
        if 'file' in request.files:
            file = request.files['file']
            if file.filename == '':
                flash('No file selected', 'danger')
                return redirect(request.url)
            if file and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                filepath = os.path.join(app.root_path, app.config['UPLOAD_FOLDER'], filename)
                file.save(filepath)
                try:
                    # Process the Excel file
                    if filename.endswith('.csv'):
                        # Use chunksize for CSV files to process in batches
                        chunk_iterator = pd.read_csv(filepath, chunksize=100)
                        df = next(chunk_iterator)  # Get first chunk for column validation
                    else:
                        # For Excel files, we'll process in batches later
                        df = pd.read_excel(filepath)
                    
                    # Improved error message for missing required columns
                    missing_columns = []
                    required_columns = ['container_number', 'container_type']
                    for col in required_columns:
                        if col not in df.columns:
                            missing_columns.append(col)
                    if missing_columns:
                        error_msg = f"Error: Missing required columns: {', '.join(missing_columns)}. "
                        error_msg += "The Excel file must contain at minimum the columns: container_number, container_type. "
                        flash(error_msg, 'danger')
                        return redirect(request.url)
                    
                    # Process file in batches
                    success_count = 0
                    error_count = 0
                    vessels_not_found = set()
                    clients_created = 0  # Counter for new clients created
                    
                    # Function to process a batch of records
                    def process_batch(batch_df):
                        nonlocal success_count, error_count, vessels_not_found, clients_created
                        container_objects = []
                        
                        try:
                            # Step 1: Create container objects first
                            for _, row in batch_df.iterrows():
                                container_number = str(row['container_number']).strip()
                                container_type = str(row['container_type']).strip()
                                # Skip empty rows
                                if not container_number or not container_type:
                                    continue
                                
                                # Check if BL number exists in the row
                                bl_number = str(row.get('bl_number', '')).strip() if not pd.isna(row.get('bl_number', '')) else None
                                
                                # Check if container already exists
                                existing_container = Container.query.filter_by(container_number=container_number).first()
                                if existing_container:
                                    # Only skip if BL number is missing or same as existing container
                                    if not bl_number:
                                        error_count += 1
                                        logger.info(f"Skipping container {container_number}: already exists and no new BL number provided")
                                        continue
                                    
                                    if existing_container.bl_number and bl_number == existing_container.bl_number:
                                        error_count += 1
                                        logger.info(f"Skipping container {container_number}: already exists with same BL number {bl_number}")
                                        continue
                                    
                                    # Otherwise proceed with adding the container with a different BL
                                    logger.info(f"Adding container {container_number} with different BL number: {bl_number}")
                                    
                                # Handle client association if specified - check for client column case-insensitively
                                client_id = None
                                client_column = next((col for col in row.index if col.lower() == 'client'), None)
                                
                                if client_column and not pd.isna(row[client_column]):
                                    client_name = str(row[client_column]).strip()
                                    if client_name:
                                        # Try to find existing client
                                        client = Client.query.filter(Client.name.ilike(client_name)).first()
                                        if client:
                                            client_id = client.id
                                        else:
                                            # Create new client with this name
                                            new_client = Client(
                                                name=client_name,
                                                created_at=datetime.utcnow()
                                            )
                                            db.session.add(new_client)
                                            db.session.flush()
                                            client_id = new_client.id
                                            clients_created += 1
                                
                                new_container = Container(
                                    container_number=container_number,
                                    container_type=container_type,
                                    loading_port=map_location_codes(str(row.get('loading_port', '')).strip()) if not pd.isna(row.get('loading_port', '')) else None,
                                    final_destination=map_location_codes(str(row.get('final_destination', '')).strip()) if not pd.isna(row.get('final_destination', '')) else None,
                                    opr=str(row.get('opr', '')).strip() if not pd.isna(row.get('opr', '')) else None,
                                    bl_number=bl_number,
                                    client_id=client_id  # Associate with client ID
                                )
                                
                                # Parse dates if provided
                                # Process arrival date
                                if 'arrival_date' in row and not pd.isna(row['arrival_date']):
                                    try:
                                        # Handle different date formats from Excel
                                        if isinstance(row['arrival_date'], datetime):
                                            new_container.arrival_date = row['arrival_date']
                                        elif isinstance(row['arrival_date'], str):
                                            # Try multiple date formats
                                            date_formats = ['%Y-%m-%d', '%d/%m/%Y', '%m/%d/%Y']
                                            for fmt in date_formats:
                                                try:
                                                    new_container.arrival_date = datetime.strptime(row['arrival_date'], fmt)
                                                    break
                                                except ValueError:
                                                    continue
                                        elif isinstance(row['arrival_date'], (int, float)):
                                            # Handle Excel numeric date format
                                            new_container.arrival_date = datetime(1899, 12, 30) + timedelta(days=int(row['arrival_date']))
                                    except Exception as e:
                                        logger.warning(f"Error parsing arrival date for {container_number}: {str(e)}")
                                        
                                # Process stripping date
                                if 'stripping_date' in row and not pd.isna(row['stripping_date']):
                                    try:
                                        # Handle different date formats from Excel
                                        if isinstance(row['stripping_date'], datetime):
                                            new_container.stripping_date = row['stripping_date']
                                        elif isinstance(row['stripping_date'], str):
                                            # Try multiple date formats
                                            date_formats = ['%Y-%m-%d', '%d/%m/%Y', '%m/%d/%Y']
                                            for fmt in date_formats:
                                                try:
                                                    new_container.stripping_date = datetime.strptime(row['stripping_date'], fmt)
                                                    break
                                                except ValueError:
                                                    continue
                                        elif isinstance(row['stripping_date'], (int, float)):
                                            # Handle Excel numeric date format
                                            new_container.stripping_date = datetime(1899, 12, 30) + timedelta(days=int(row['stripping_date']))
                                    except Exception as e:
                                        logger.warning(f"Error parsing stripping date for {container_number}: {str(e)}")
                                
                                db.session.add(new_container)
                                container_objects.append({
                                    'container': new_container,
                                    'row_data': row
                                })
                            
                            # Step 2: Flush to get IDs assigned
                            if container_objects:
                                db.session.flush()
                                
                                # Step 3: Process container relationships with the row data we stored
                                for obj in container_objects:
                                    container = obj['container']
                                    row = obj['row_data']
                                    
                                    # Add status if provided
                                    has_status = all(col in batch_df.columns for col in ['status', 'date', 'location'])
                                    
                                    if has_status and not pd.isna(row.get('status')) and not pd.isna(row.get('date')) and not pd.isna(row.get('location')):
                                        status = str(row['status']).strip().lower()
                                        
                                        # Parse the date
                                        try:
                                            if isinstance(row['date'], pd.Timestamp):
                                                status_date = row['date'].to_pydatetime()
                                            else:
                                                status_date = datetime.strptime(str(row['date']), '%Y-%m-%d')
                                        except Exception as e:
                                            logger.error(f"Error parsing date {row['date']}: {str(e)}")
                                            status_date = datetime.utcnow()
                                        
                                        status_location = map_location_codes(str(row['location']).strip())
                                        # Add notes if available
                                        notes = str(row.get('notes', '')).strip() if not pd.isna(row.get('notes', '')) else None
                                        
                                        container_status = ContainerStatus(
                                            status=status,
                                            date=status_date,
                                            location=status_location,
                                            notes=notes,
                                            container_id=container.id   
                                        )
                                        db.session.add(container_status)
                                        
                                        # Handle vessel information if provided - FIXED VESSEL ASSOCIATION
                                        if status.lower() == 'loaded':
                                            vessel_name = None
                                            voyage_number = None
                                            
                                            # Check if vessel column exists and has a value
                                            if 'vessel' in batch_df.columns and not pd.isna(row.get('vessel')):
                                                vessel_info = str(row['vessel']).strip()
                                                
                                                # Try to extract vessel name and voyage number
                                                # Common format: "VESSEL NAME V1234" where V1234 is the voyage number
                                                if ' V' in vessel_info:
                                                    # Split by " V" and take the voyage part
                                                    parts = vessel_info.split(' V', 1)
                                                    if len(parts) == 2:
                                                        vessel_name = parts[0].strip()
                                                        voyage_number = 'V' + parts[1].strip()
                                                else:
                                                    # No voyage number format, use the whole value as vessel name
                                                    vessel_name = vessel_info
                                                
                                                # Try to find the vessel in database
                                                vessel = None
                                                if vessel_name and voyage_number:
                                                    # Look for exact match on name and IMO/voyage
                                                    vessel = Vessel.query.filter(
                                                        Vessel.name.ilike(vessel_name),
                                                        Vessel.imo_number.ilike(voyage_number)
                                                    ).first()
                                                
                                                if vessel_name and not vessel:
                                                    # Try just by name as fallback
                                                    vessel = Vessel.query.filter(
                                                        Vessel.name.ilike(vessel_name)
                                                    ).first()
                                                    
                                                    if not vessel:
                                                        # Track vessels not found for warning message
                                                        vessels_not_found.add(vessel_info)
                                                    
                                                # Create container movement if vessel is found
                                                if vessel:
                                                    movement = ContainerMovement(
                                                        operation_type='load',
                                                        operation_date=status_date,
                                                        location=status_location,
                                                        notes=f"Automatically created from bulk import: {notes or 'No notes'}",
                                                        container_id=container.id,
                                                        vessel_id=vessel.id
                                                    )
                                                    db.session.add(movement)
                                                    logger.info(f"Created load movement for container {container.container_number} onto vessel {vessel.name}")
                                    
                                    # Step 4: Count successfully added containers and commit
                                    success_count += len(container_objects)
                                    db.session.commit()
                                
                                # Step 5: Clear SQLAlchemy session to free memory
                                db.session.expunge_all()
                                
                        except Exception as e:
                            # Roll back on error and re-raise for outer handler
                            db.session.rollback()
                            logger.error(f"Batch processing error: {str(e)}")
                            raise
                    
                    # Process in batches based on file type
                    if filename.endswith('.csv'):
                        # For CSV we already have the chunk iterator
                        process_batch(df)  # Process first chunk we already loaded
                        
                        # Process remaining chunks
                        for chunk_df in chunk_iterator:
                            process_batch(chunk_df)
                    else:
                        # For Excel, create our own batches
                        total_rows = len(df)
                        batch_size = 100
                        
                        for start_idx in range(0, total_rows, batch_size):
                            end_idx = min(start_idx + batch_size, total_rows)
                            batch_df = df.iloc[start_idx:end_idx]
                            process_batch(batch_df)
                            
                            # Clear memory
                            del batch_df
                            
                            # Force garbage collection on large files
                            if total_rows > 1000:
                                import gc
                                gc.collect()
                                
                    # Determine if status info was imported
                    has_status = all(col in df.columns for col in ['status', 'date', 'location'])
                    status_msg = " Status information was also imported." if has_status else ""
                    client_msg = f" {clients_created} new clients were created." if clients_created > 0 else ""
                    flash(f'Successfully imported {success_count} containers.{status_msg}{client_msg} {error_count} containers were duplicates and skipped.', 'success')
                    
                    if vessels_not_found:
                        flash(f'Warning: Some vessels were not found in the system: {", ".join(vessels_not_found)}. Please add these vessels first.', 'warning')
                        
                except Exception as e:
                    db.session.rollback()
                    flash(f'Error processing file: {str(e)}', 'danger')
                    logger.error(f"File upload error: {str(e)}", exc_info=True)
                
                # Delete the file after processing
                try:
                    os.remove(filepath)
                except Exception as e:
                    logger.error(f"Error removing temporary file: {str(e)}")
                
                return redirect(url_for('index'))
            else:
                flash('File type not allowed. Please upload xlsx, xls or csv files.', 'danger')
                return redirect(request.url)
        else:
            # Enhanced single container add with status information
            container_number = request.form['container_number']
            container_type = request.form['container_type']
            # Get new fields
            loading_port = map_location_codes(request.form.get('loading_port', ''))
            vessel_id = request.form.get('vessel_id')
            final_destination = map_location_codes(request.form.get('final_destination', ''))
            opr = request.form.get('opr', '')
            bl_number = request.form.get('bl_number', '')
            # Parse arrival date if provided
            arrival_date = None
            if request.form.get('arrival_date'):
                arrival_date = datetime.strptime(request.form.get('arrival_date'), '%Y-%m-%d')
                
            # Parse stripping date if provided
            stripping_date = None
            if request.form.get('stripping_date'):
                stripping_date = datetime.strptime(request.form.get('stripping_date'), '%Y-%m-%d')
                
            # Handle client name from autocomplete instead of client_id
            client_id = None
            client_name = request.form.get('client_name', '').strip()
            
            if client_name:
                # Try to find existing client by name (case insensitive)
                client = Client.query.filter(Client.name.ilike(client_name)).first()
                
                if client:
                    # Use existing client
                    client_id = client.id
                    logger.info(f"Using existing client: {client.name} (ID: {client.id})")
                else:
                    # Create new client with this name
                    new_client = Client(
                        name=client_name,
                        created_at=datetime.utcnow()
                    )
                    db.session.add(new_client)
                    db.session.flush()  # Get ID without committing
                    client_id = new_client.id
                    logger.info(f"Created new client: {client_name} (ID: {client_id})")
            
            # Check if container already exists
            existing_container = Container.query.filter_by(container_number=container_number).first()
            if existing_container:
                # Only block if BL number is the same or empty
                if not bl_number:
                    flash('Container already exists! Please provide a different BL number to add it again.', 'danger')
                    return redirect(url_for('add_container'))
                
                if existing_container.bl_number and bl_number == existing_container.bl_number:
                    flash('Container already exists with the same BL number!', 'danger')
                    return redirect(url_for('add_container'))
                
                # If we get here, the container exists but has a different BL number, so we'll add it as a new record
                flash(f'Adding container {container_number} with a new BL number.', 'info')
            
            new_container = Container(
                container_number=container_number,
                container_type=container_type,
                loading_port=loading_port,
                final_destination=final_destination,
                opr=opr,
                arrival_date=arrival_date,
                bl_number=bl_number,
                stripping_date=stripping_date,  # Add stripping date here
                client_id=client_id  # Add client_id here
            )
            db.session.add(new_container)
            db.session.flush()  # Get the container ID without committing
            
            # Add initial status if provided
            if 'status' in request.form and request.form['status'].strip():
                status = request.form['status']
                date = datetime.strptime(request.form['date'], '%Y-%m-%d') if request.form.get('date') else datetime.now()
                location = map_location_codes(request.form['location']) if request.form.get('location') else ''
                notes = request.form.get('notes', '')
                
                # Auto-fill notes based on status
                if status == 'emptied' and not notes:
                    notes = "Empty Container"
                elif status == 'full' and not notes:
                    notes = "Full Container"
                elif status == 'in_transit' and not notes:
                    notes = "In Transit"
                elif status == 'customs_hold' and not notes:
                    notes = "Hold by the Customer"
                elif status == 'ready_for_pickup' and not notes:
                    notes = "Ready for Pickup"
                container_status = ContainerStatus(
                    status=status,
                    date=date,
                    location=location,
                    notes=notes,
                    container_id=new_container.id
                )
                db.session.add(container_status)
                
                # If status is 'emptied', set the container's stripping date if not already set
                if status == 'emptied' and not stripping_date:
                    new_container.stripping_date = date
                    
                # If vessel is selected and status is 'loaded', create a movement record
                if vessel_id and status == 'loaded':
                    vessel = Vessel.query.get(vessel_id)
                    if vessel:
                        movement = ContainerMovement(
                            operation_type='load',
                            operation_date=date,
                            location=location or vessel.current_location or '',
                            notes=notes or f"Loaded onto vessel {vessel.name}",
                            container_id=new_container.id,
                            vessel_id=vessel_id
                        )
                        db.session.add(movement)
            db.session.commit()
            flash('Container added successfully!', 'success')
            return redirect(url_for('index'))
    # Get vessels for the vessel dropdown
    vessels = Vessel.query.all()
    # Get clients for the client dropdown
    clients = Client.query.order_by(Client.name).all()
    return render_template('add_container.html', now=datetime.now(), vessels=vessels, clients=clients)

@app.route('/containers/<int:id>/update_status', methods=['GET', 'POST'])
@login_required
def update_status(id):
    container = Container.query.get_or_404(id)
    # Get the current status to pre-populate the form
    current_status = container.get_current_status()
    # Check if container is currently on a vessel
    current_location = container.get_current_location()
    is_on_vessel = (current_location and current_location['type'] == 'vessel')
    vessel = None
    if is_on_vessel:
        vessel = current_location['vessel']
    if request.method == 'POST':
        active_tab = request.form.get('active_tab', 'status')
        if active_tab == 'details':
            # Update container details
            container.container_number = request.form['container_number']
            container.container_type = request.form['container_type']
            container.loading_port = map_location_codes(request.form.get('loading_port', ''))
            container.final_destination = map_location_codes(request.form.get('final_destination', ''))
            container.opr = request.form.get('opr', '')
            container.bl_number = request.form.get('bl_number', '')
            # Parse arrival date if provided
            if request.form.get('arrival_date'):
                container.arrival_date = datetime.strptime(request.form.get('arrival_date'), '%Y-%m-%d')
            else:
                container.arrival_date = None
            # Parse stripping date if provided
            if request.form.get('stripping_date'):
                container.stripping_date = datetime.strptime(request.form.get('stripping_date'), '%Y-%m-%d')
            else:
                container.stripping_date = None
            
            # Handle client name from autocomplete
            client_name = request.form.get('client_name', '').strip()
            if client_name:
                # Try to find existing client by name (case insensitive)
                client = Client.query.filter(Client.name.ilike(client_name)).first()
                
                if client:
                    # Use existing client
                    container.client_id = client.id
                    logger.info(f"Using existing client: {client.name} (ID: {client.id})")
                else:
                    # Create new client with this name
                    new_client = Client(
                        name=client_name,
                        created_at=datetime.utcnow()
                    )
                    db.session.add(new_client)
                    db.session.flush()  # Get ID without committing
                    container.client_id = new_client.id
                    logger.info(f"Created new client: {client_name} (ID: {container.client_id})")
            else:
                # Clear client association if the field is empty
                container.client_id = None
                
            db.session.commit()
            flash('Container details updated successfully!', 'success')
            return redirect(url_for('container_detail', id=container.id))
        else:
            # Existing status update logic
            status = request.form['status']
            date = datetime.strptime(request.form['date'], '%Y-%m-%d')
            location = map_location_codes(request.form['location'])
            notes = request.form.get('notes', '')
            # Default to using the provided notes
            # Set specific notes for certain status values
            if status == 'emptied' and not notes:
                notes = "Empty Container"
            elif status == 'full' and not notes:
                notes = "Full Container"
            elif status == 'in_transit' and not notes:
                notes = "In Transit"
            elif status == 'customs_hold' and not notes:
                notes = "Hold by the Customer"
            elif status == 'ready_for_pickup' and not notes:
                notes = "Ready for Pickup"
            
            # If container is on a vessel and status is being changed manually,
            # automatically discharge it from the vessel
            if is_on_vessel and status != 'loaded':
                # Create container movement record for discharge
                discharge_movement = ContainerMovement(
                    operation_type='discharge',
                    operation_date=date,
                    location=location,
                    notes=f"Automatically discharged due to status change to '{status}'",
                    container_id=container.id,
                    vessel_id=vessel.id
                )
                db.session.add(discharge_movement)
                # Add extra note about the automatic discharge
                if notes:
                    notes = f"{notes} - Automatically discharged from vessel {vessel.name}"
                else:
                    notes = f"Automatically discharged from vessel {vessel.name}"
            
            new_status = ContainerStatus(
                status=status,
                date=date,
                location=location,
                notes=notes,
                container_id=container.id
            )
            
            # If status is being changed to emptied, set stripping date
            if status == 'emptied':
                container.stripping_date = date
            db.session.add(new_status)
            db.session.commit()
            
            # Notify the user if automatic discharge happened
            if is_on_vessel and status != 'loaded':
                flash(f'Container was automatically discharged from vessel {vessel.name} due to status change.', 'info')
            
            flash('Status updated successfully!', 'success')
            return redirect(url_for('container_detail', id=container.id))
        
    return render_template('update_status.html', container=container, current_status=current_status, now=datetime.now())

@app.route('/container/<int:id>')
@login_required
def container_detail(id):
    container = Container.query.get_or_404(id)
    fresh_status = container.get_current_status()
    location_type = "vessel" if container.get_current_vessel() else "port"
    
    # Add this to fetch all users for the authorization dropdown
    users = []
    if current_user.is_admin:
        users = User.query.all()
    
    # Check if user can print delivery order
    container_can_print = container.can_print_delivery_order(current_user.id)
    
    return render_template(
        'container_detail.html', 
        container=container, 
        fresh_status=fresh_status, 
        location_type=location_type, 
        users=users,  # Pass users to template
        container_can_print=container_can_print
    )

@app.route('/containers/<int:id>/delete', methods=['POST'])
@login_required
def delete_container(id):
    container = Container.query.get_or_404(id)
    container_number = container.container_number
    try:
        # First check for and delete any print history records
        history_count = PrintHistory.query.filter_by(container_id=id).count()
        
        # Also check for and delete any print authorizations or requests
        auth_count = PrintAuthorization.query.filter_by(container_id=id).count()
        request_count = PrintAccessRequest.query.filter_by(container_id=id).count()
        
        # Delete related records before deleting the container itself
        if history_count > 0:
            PrintHistory.query.filter_by(container_id=id).delete()
            logger.info(f"Deleted {history_count} print history records for container {container_number}")
        
        if auth_count > 0:
            PrintAuthorization.query.filter_by(container_id=id).delete()
            
        if request_count > 0:
            PrintAccessRequest.query.filter_by(container_id=id).delete()
            
        # Now delete the container (cascade will delete its statuses and movements too)
        db.session.delete(container)
        db.session.commit()
        
        # Include information about deleted history in the success message
        if history_count > 0:
            flash(f'Container {container_number} and its {history_count} print history records deleted successfully!', 'success')
        else:
            flash(f'Container {container_number} deleted successfully!', 'success')
            
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting container: {str(e)}', 'danger')
    return redirect(url_for('index'))

@app.route('/api/containers')
@login_required  # Protect API endpoints
def api_containers():
    containers = Container.query.all()
    result = []
    for container in containers:
        # Use created_at instead of date
        latest_status = ContainerStatus.query.filter_by(container_id=container.id).order_by(ContainerStatus.created_at.desc()).first()
        
        # Check if container is on a departed vessel
        on_departed_vessel = container.is_on_departed_vessel()
        
        container_data = {
            'id': container.id,
            'container_number': container.container_number,
            'container_type': container.container_type,
            'current_status': latest_status.status if latest_status else 'Unknown',
            'last_updated': latest_status.date.strftime('%Y-%m-%d') if latest_status else 'N/A',
            'location': latest_status.location if latest_status else 'Unknown',
            'on_departed_vessel': on_departed_vessel  # Add this flag
        }
        result.append(container_data)
    return jsonify(result)

@app.route('/download_template')
@login_required
def download_template():
    """Generate and serve an example Excel template for container import"""
    # First try to serve a static template file if it exists
    static_template_path = os.path.join(app.root_path, 'static', 'templates', 'container_import_template.xlsx')
    # If the static template doesn't exist, create it
    if not os.path.exists(static_template_path):
        # Create the directory if it doesn't exist
        os.makedirs(os.path.dirname(static_template_path), exist_ok=True)
        # Create the template
        create_import_template(static_template_path)
        
    # Serve the static template file
    return send_file(
        static_template_path,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name='container_import_template.xlsx'
    )

def create_import_template(output_path=None):
    """Create an Excel template for container import"""
    # Create sample data for the template
    data = {
        'container_number': ['ABCD1234567', 'EFGH9876543', 'IJKL1122334'],
        'container_type': ['20GP', '40HC', '45G1'],  # Using 45G1 as one of the examples
        'loading_port': ['Shanghai', 'Rotterdam', 'Singapore'],
        'final_destination': ['Moroni', 'Mutsamudu', 'Moroni'],
        'opr': ['MSC', 'CMA CGM', 'MAERSK'],
        'arrival_date': [
            (datetime.now() + pd.Timedelta(days=10)).strftime('%Y-%m-%d'), 
            (datetime.now() + pd.Timedelta(days=15)).strftime('%Y-%m-%d'),
            (datetime.now() + pd.Timedelta(days=8)).strftime('%Y-%m-%d')
        ],
        'bl_number': ['BL-12345', 'BL-67890', 'BL-54321'],
        'vessel': ['MSC Monaco', 'CMA CGM Comoros', 'MAERSK Alberta'],
        'stripping_date': [
            (datetime.now() + pd.Timedelta(days=15)).strftime('%Y-%m-%d'), 
            (datetime.now() + pd.Timedelta(days=20)).strftime('%Y-%m-%d'),
            (datetime.now() + pd.Timedelta(days=12)).strftime('%Y-%m-%d')
        ],
        'status': ['loaded', 'discharged', 'full'],
        'date': [
            datetime.now().strftime('%Y-%m-%d'), 
            (datetime.now() - pd.Timedelta(days=5)).strftime('%Y-%m-%d'),
            (datetime.now() - pd.Timedelta(days=10)).strftime('%Y-%m-%d')
        ],
        'location': ['Mutsamudu', 'Mutsamudu', 'Moroni'],
        'client': ['ABC Shipping Ltd', 'XYZ Logistics', 'Global Imports Inc'],  # Added client column
        'notes': ['Refrigerated cargo', 'Handle with care', 'Customs cleared']
    }
    
    # Create DataFrame
    df = pd.DataFrame(data)
    
    # Force the columns to appear in the desired order
    column_order = [
        'container_number', 'container_type', 'loading_port', 'final_destination', 
        'opr', 'arrival_date', 'bl_number', 'vessel', 'stripping_date', 'status', 'date', 
        'location', 'client', 'notes'  # Added client before notes
    ]
    df = df[column_order]

    # If output_path is provided, save directly to that path
    if output_path:
        output = output_path
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            df.to_excel(writer, sheet_name='Containers', index=False)
            
            # Access the workbook and worksheet objects
            workbook = writer.book
            worksheet = writer.sheets['Containers']
            
            # Add some formatting
            header_format = workbook.add_format({
                'bold': True,
                'text_wrap': True,
                'valign': 'top',
                'fg_color': '#D7E4BC',
                'border': 1
            })
            required_format = workbook.add_format({
                'bold': True,
                'bg_color': '#FFEB9C'
            })
            optional_format = workbook.add_format({
                'bold': True,
                'bg_color': '#E0E0E0'
            })
            
            # Write the column headers with the defined format
            for col_num, value in enumerate(df.columns.values):
                if value in ['container_number', 'container_type']:
                    worksheet.write(0, col_num, value, required_format)
                else:
                    worksheet.write(0, col_num, value, optional_format)
            
            # Set column widths
            worksheet.set_column('A:A', 20)  # container_number
            worksheet.set_column('B:B', 15)  # container_type
            worksheet.set_column('C:C', 15)  # loading_port
            worksheet.set_column('D:D', 20)  # final_destination
            worksheet.set_column('E:E', 12)  # opr
            worksheet.set_column('F:F', 15)  # arrival_date
            worksheet.set_column('G:G', 15)  # bl_number
            worksheet.set_column('H:H', 15)  # vessel
            worksheet.set_column('I:I', 15)  # stripping_date
            worksheet.set_column('J:J', 12)  # status
            worksheet.set_column('K:K', 12)  # date
            worksheet.set_column('L:L', 15)  # location
            worksheet.set_column('M:M', 15)  # client
            worksheet.set_column('N:N', 30)  # notes
            
            # Add descriptions on another sheet
            desc_sheet = workbook.add_worksheet('Instructions')
            desc_sheet.write(0, 0, 'Instructions for filling the Container Import Template', workbook.add_format({'bold': True, 'font_size': 14}))
            
            desc_sheet.write(2, 0, '* Required fields', workbook.add_format({'bold': True, 'font_color': 'red'}))
            desc_sheet.write(3, 0, '- Other fields are optional', workbook.add_format({'italic': True}))
            
            field_details = [
                ('container_number *', 'Required. Enter the unique container number (e.g., ABCD1234567)'),
                ('container_type *', 'Required. Enter the container type using codes like 20GP, 40HC, 45G1, 22G1, etc.'),
                ('loading_port', 'Optional. Port where the container is loaded'),
                ('final_destination', 'Optional. Final destination of the container'),
                ('opr', 'Optional. Operator of the container'),
                ('arrival_date', 'Optional. Expected arrival date in format YYYY-MM-DD'),
                ('bl_number', 'Optional. Bill of Lading number'),
                ('vessel', 'Optional. Name of the vessel transporting the container'),
                ('stripping_date', 'Optional. Date when container is expected to be unloaded/stripped in format YYYY-MM-DD. The system automatically sets this to the discharge date when a container is discharged from a vessel.'),
                ('status', 'Optional. Current status of container (loaded, discharged, emptied, full)'),
                ('date', 'Optional. Date of the status in format YYYY-MM-DD'),
                ('location', 'Optional. Location where the container is currently located'),
                ('client', 'Optional. Client name associated with this container. Must match an existing client in the system.'),
                ('notes', 'Optional. Additional notes about the container')
            ]
            
            desc_sheet.write(5, 0, 'Field Descriptions:', workbook.add_format({'bold': True}))
            for idx, (field, desc) in enumerate(field_details):
                desc_sheet.write(6+idx, 0, field, workbook.add_format({'bold': True}))
                desc_sheet.write(6+idx, 1, desc)
            
            desc_sheet.write(18, 0, 'Valid container types:', workbook.add_format({'bold': True}))
            types = [
                ('20GP', '20 foot General Purpose'),
                ('40GP', '40 foot General Purpose'),
                ('40HC', '40 foot High Cube'),
                ('20RF', '20 foot Refrigerated'),
                ('40RF', '40 foot Refrigerated'),
                ('20OT', '20 foot Open Top'),
                ('40OT', '40 foot Open Top'),
                ('20FR', '20 foot Flat Rack'),
                ('40FR', '40 foot Flat Rack'),
                ('45G1', '45 foot General Purpose'),  # Added 45G1
                ('22G1', '22 foot General Purpose')   # Added 22G1
            ]
            for idx, (code, desc) in enumerate(types):
                desc_sheet.write(19+idx, 0, code)
                desc_sheet.write(19+idx, 1, desc)
            
            desc_sheet.write(29, 0, 'Valid status values:', workbook.add_format({'bold': True}))
            statuses = [
                ('loaded', 'Container has been loaded'),
                ('discharged', 'Container has been discharged from vessel'),
                ('emptied', 'Container has been emptied after discharge'),
                ('full', 'Container is full'),
                ('in_transit', 'Container is in transit'),
                ('customs_hold', 'Container is held by customs'),
                ('ready_for_pickup', 'Container is ready for pickup')
            ]
            for idx, (code, desc) in enumerate(statuses):
                desc_sheet.write(30+idx, 0, code)
                desc_sheet.write(30+idx, 1, desc)
            
            # Set column widths for instructions sheet
            desc_sheet.set_column('A:A', 20)
            desc_sheet.set_column('B:B', 50)
        
        return output
    else:
        # Create Excel file in memory for direct response
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            df.to_excel(writer, sheet_name='Containers', index=False)
            
            # Access the workbook and worksheet objects
            workbook = writer.book
            worksheet = writer.sheets['Containers']
            
            # Add some formatting
            header_format = workbook.add_format({
                'bold': True,
                'text_wrap': True,
                'valign': 'top',
                'fg_color': '#D7E4BC',
                'border': 1
            })
            required_format = workbook.add_format({
                'bold': True,
                'bg_color': '#FFEB9C'
            })
            optional_format = workbook.add_format({
                'bold': True,
                'bg_color': '#E0E0E0'
            })
            
            # Write the column headers with the defined format
            for col_num, value in enumerate(df.columns.values):
                if value in ['container_number', 'container_type']:
                    worksheet.write(0, col_num, value, required_format)
                else:
                    worksheet.write(0, col_num, value, optional_format)
            
            # Set column widths
            worksheet.set_column('A:A', 20)  # container_number
            worksheet.set_column('B:B', 15)  # container_type
            worksheet.set_column('C:C', 15)  # loading_port
            worksheet.set_column('D:D', 20)  # final_destination
            worksheet.set_column('E:E', 12)  # opr
            worksheet.set_column('F:F', 15)  # arrival_date
            worksheet.set_column('G:G', 15)  # bl_number
            worksheet.set_column('H:H', 15)  # vessel
            worksheet.set_column('I:I', 15)  # stripping_date
            worksheet.set_column('J:J', 12)  # status
            worksheet.set_column('K:K', 12)  # date
            worksheet.set_column('L:L', 15)  # location
            worksheet.set_column('M:M', 15)  # client
            worksheet.set_column('N:N', 30)  # notes
            
            # Add descriptions on another sheet
            desc_sheet = workbook.add_worksheet('Instructions')
            desc_sheet.write(0, 0, 'Instructions for filling the Container Import Template', workbook.add_format({'bold': True, 'font_size': 14}))
            
            desc_sheet.write(2, 0, '* Required fields', workbook.add_format({'bold': True, 'font_color': 'red'}))
            desc_sheet.write(3, 0, '- Other fields are optional', workbook.add_format({'italic': True}))
            
            field_details = [
                ('container_number *', 'Required. Enter the unique container number (e.g., ABCD1234567)'),
                ('container_type *', 'Required. Enter the container type using codes like 20GP, 40HC, 45G1, 22G1, etc.'),
                ('loading_port', 'Optional. Port where the container is loaded'),
                ('final_destination', 'Optional. Final destination of the container'),
                ('opr', 'Optional. Operator of the container'),
                ('arrival_date', 'Optional. Expected arrival date in format YYYY-MM-DD'),
                ('bl_number', 'Optional. Bill of Lading number'),
                ('vessel', 'Optional. Name of the vessel transporting the container'),
                ('stripping_date', 'Optional. Date when container is expected to be unloaded/stripped in format YYYY-MM-DD. The system automatically sets this to the discharge date when a container is discharged from a vessel.'),
                ('status', 'Optional. Current status of container (loaded, discharged, emptied, full)'),
                ('date', 'Optional. Date of the status in format YYYY-MM-DD'),
                ('location', 'Optional. Location where the container is currently located'),
                ('client', 'Optional. Client name associated with this container. Must match an existing client in the system.'),
                ('notes', 'Optional. Additional notes about the container')
            ]
            
            desc_sheet.write(5, 0, 'Field Descriptions:', workbook.add_format({'bold': True}))
            for idx, (field, desc) in enumerate(field_details):
                desc_sheet.write(6+idx, 0, field, workbook.add_format({'bold': True}))
                desc_sheet.write(6+idx, 1, desc)
            
            desc_sheet.write(18, 0, 'Valid container types:', workbook.add_format({'bold': True}))
            types = [
                ('20GP', '20 foot General Purpose'),
                ('40GP', '40 foot General Purpose'),
                ('40HC', '40 foot High Cube'),
                ('20RF', '20 foot Refrigerated'),
                ('40RF', '40 foot Refrigerated'),
                ('20OT', '20 foot Open Top'),
                ('40OT', '40 foot Open Top'),
                ('20FR', '20 foot Flat Rack'),
                ('40FR', '40 foot Flat Rack'),
                ('45G1', '45 foot General Purpose'),  # Added 45G1
                ('22G1', '22 foot General Purpose')   # Added 22G1
            ]
            for idx, (code, desc) in enumerate(types):
                desc_sheet.write(19+idx, 0, code)
                desc_sheet.write(19+idx, 1, desc)
            
            desc_sheet.write(29, 0, 'Valid status values:', workbook.add_format({'bold': True}))
            statuses = [
                ('loaded', 'Container has been loaded'),
                ('discharged', 'Container has been discharged from vessel'),
                ('emptied', 'Container has been emptied after discharge'),
                ('full', 'Container is full'),
                ('in_transit', 'Container is in transit'),
                ('customs_hold', 'Container is held by customs'),
                ('ready_for_pickup', 'Container is ready for pickup')
            ]
            for idx, (code, desc) in enumerate(statuses):
                desc_sheet.write(30+idx, 0, code)
                desc_sheet.write(30+idx, 1, desc)
            
            # Set column widths for instructions sheet
            desc_sheet.set_column('A:A', 20)
            desc_sheet.set_column('B:B', 50)
        
        return output

# New routes for vessel management
@app.route('/vessels')
@login_required  # Add login_required to vessels list view
def vessels():
    """List all vessels"""
    # Check and update vessel statuses automatically based on ETA
    update_vessel_statuses_auto()
    
    # Get page parameter with default value of 1
    page = request.args.get('page', 1, type=int)
    per_page = 10  # Show 10 vessels per page
    
    # Get sorting parameters from the request
    sort_by = request.args.get('sort', 'created_at')  # Default sort by creation date
    sort_order = request.args.get('order', 'desc')    # Default to descending order
    
    # Search parameter
    search_term = request.args.get('search', '').strip()
    
    # Base query
    vessels_query = Vessel.query
    
    # Apply search if provided
    if search_term:
        vessels_query = vessels_query.filter(
            db.or_(
                Vessel.name.ilike(f'%{search_term}%'),
                Vessel.imo_number.ilike(f'%{search_term}%'),
                Vessel.vessel_type.ilike(f'%{search_term}%'),
                Vessel.current_location.ilike(f'%{search_term}%'),
                Vessel.current_destination.ilike(f'%{search_term}%')
            )
        )
    
    # Apply sorting
    if sort_by == 'name':
        if sort_order == 'desc':
            vessels_query = vessels_query.order_by(Vessel.name.desc())
        else:
            vessels_query = vessels_query.order_by(Vessel.name)
    elif sort_by == 'status':
        if sort_order == 'desc':
            vessels_query = vessels_query.order_by(Vessel.status.desc())
        else:
            vessels_query = vessels_query.order_by(Vessel.status)
    else:  # Default to created_at
        if sort_order == 'desc':
            vessels_query = vessels_query.order_by(Vessel.created_at.desc())
        else:
            vessels_query = vessels_query.order_by(Vessel.created_at)
    
    # Get total vessels for statistics
    total_vessel_count = vessels_query.count()
    
    # Create pagination object
    pagination = Pagination(vessels_query, page, per_page, 'vessels', 
                           sort=sort_by, order=sort_order, search=search_term)
    
    # Get paginated vessels
    vessel_list = pagination.items
    
    return render_template('vessels.html', 
                          vessels=vessel_list, 
                          pagination=pagination,
                          total_vessel_count=total_vessel_count,
                          sort_by=sort_by,
                          sort_order=sort_order)

@app.route('/vessels/add', methods=['GET', 'POST'])
@login_required
def add_vessel():
    """Add a new vessel"""
    if request.method == 'POST':
        name = request.form['name']
        imo_number = request.form['imo_number']  # Field name stays the same for database compatibility
        vessel_type = request.form['vessel_type']
        capacity_teu = request.form['capacity_teu'] or None
        current_location = request.form['current_location']
        current_destination = request.form.get('current_destination', '')
        status = request.form.get('status', 'En Route')  # Default to 'En Route' if not provided
        eta = None
        if request.form.get('eta'):
            eta = datetime.strptime(request.form['eta'], '%Y-%m-%d')
        
        # Check if vessel already exists
        existing_vessel = Vessel.query.filter_by(imo_number=imo_number).first()
        if existing_vessel:
            flash('Vessel with this Voyage Number already exists!', 'danger')  # Updated message
            return redirect(url_for('add_vessel'))
        new_vessel = Vessel(
            name=name,
            imo_number=imo_number,
            vessel_type=vessel_type,
            capacity_teu=capacity_teu,
            current_location=current_location,
            current_destination=current_destination,
            status=status,
            eta=eta   
        )
        db.session.add(new_vessel)
        db.session.commit()
        flash('Vessel added successfully!', 'success')
        return redirect(url_for('vessels'))
        
    return render_template('add_vessel.html')

@app.route('/vessels/<int:id>')
@login_required  # Add login_required to vessel detail view
def vessel_detail(id):
    """Show vessel details"""
    # Check and update vessel status automatically based on ETA
    update_vessel_statuses_auto(vessel_id=id)
    vessel = Vessel.query.get_or_404(id)
    loaded_containers = vessel.get_loaded_containers()
    # Get container movement history for this vessel
    movements = ContainerMovement.query.filter_by(vessel_id=id).order_by(
        ContainerMovement.operation_date.desc()
    ).all()
    return render_template('vessel_detail.html', 
                          vessel=vessel, 
                          loaded_containers=loaded_containers,
                          movements=movements)

@app.route('/vessels/<int:id>/update', methods=['GET', 'POST'])
@login_required
def update_vessel(id):
    """Update vessel information"""
    vessel = Vessel.query.get_or_404(id)
    original_status = vessel.status
    original_location = vessel.current_location
    
    if request.method == 'POST':
        vessel.name = request.form['name']
        vessel.vessel_type = request.form['vessel_type']
        vessel.capacity_teu = request.form['capacity_teu'] or None
        vessel.current_location = request.form['current_location']
        vessel.current_destination = request.form.get('current_destination', '')
        new_status = request.form.get('status', 'En Route')
        
        # Update ETA if provided - do this before status changes
        if request.form.get('eta'):
            vessel.eta = datetime.strptime(request.form['eta'], '%Y-%m-%d')
        else:
            vessel.eta = None
            
        # Handle vessel status change to Arrived from any other status
        if original_status != 'Arrived' and new_status == 'Arrived':
            # Update current location to destination if available
            if vessel.current_destination:
                vessel.current_location = vessel.current_destination
                # Don't replace with "---", just clear the destination since vessel has arrived
                vessel.current_destination = ""
            
            # Update arrival date for all containers on this vessel
            loaded_containers = vessel.get_loaded_containers()
            container_count = 0
            for container in loaded_containers:
                # Always use the current vessel ETA value (which may have just been updated)
                container.arrival_date = vessel.eta or datetime.now()
                container_count += 1
            
            if container_count > 0:
                flash(f'Updated arrival date for {container_count} containers to match vessel arrival date ({vessel.eta or datetime.now()}).', 'info')
        
        # Handle vessel status change from Departed to Arrived (keep existing code)
        if original_status == 'Departed' and new_status == 'Arrived':
            # Update current location to destination if available
            if vessel.current_destination:
                vessel.current_location = vessel.current_destination
                # Don't replace with "---", just clear the destination
                vessel.current_destination = ""
            # Update locations for all containers on this vessel
            loaded_containers = vessel.get_loaded_containers()
            for container in loaded_containers:
                # Create new status record for each container with updated location
                container_status = ContainerStatus(
                    status='loaded',
                    date=datetime.now(),
                    location=vessel.current_location,
                    notes=f"Location updated due to vessel {vessel.name} arrival",
                    container_id=container.id   
                )
                db.session.add(container_status)
                
                # Create a new movement record to track the location change
                movement = ContainerMovement(
                    operation_type='load',  # Keep as 'load' since container is still on vessel
                    operation_date=datetime.now(),
                    location=vessel.current_location,  # Use the new vessel location
                    notes=f"Location updated due to vessel {vessel.name} arrival at destination",
                    container_id=container.id,
                    vessel_id=vessel.id   
                )
                db.session.add(movement)
            flash(f'Vessel status changed from Departed to Arrived. Location and {len(loaded_containers)} containers relocated to {vessel.current_location}.', 'info')
        
        # Set the new vessel status
        vessel.status = new_status
        
        db.session.commit()
        flash('Vessel updated successfully!', 'success')
        return redirect(url_for('vessel_detail', id=vessel.id))
        
    return render_template('update_vessel.html', vessel=vessel)

@app.route('/api/vessel/<int:id>')
@login_required  # Protect API endpoints
def get_vessel_info(id):
    """API endpoint to get vessel information"""
    vessel = Vessel.query.get_or_404(id)
    return jsonify({
        'id': vessel.id,
        'name': vessel.name,
        'current_location': vessel.current_location or '',
        'current_destination': vessel.current_destination or ''
    })

@app.route('/containers/<int:id>/load', methods=['GET', 'POST'])
@login_required
def load_container(id):
    container = Container.query.get_or_404(id)
    vessels = Vessel.query.filter(Vessel.status != 'Departed').all()
    
    if request.method == 'POST':
        vessel_id = request.form.get('vessel_id')
        operation_date = request.form.get('operation_date')
        location = request.form.get('location')
        notes = request.form.get('notes') or f"Loaded onto vessel"
        
        vessel = Vessel.query.get(vessel_id)
        if not vessel:
            flash('Invalid vessel selected', 'danger')
            return redirect(url_for('load_container', id=id))
        
        try:
            # CHANGE: Don't delete print history anymore at all
            # MODIFIED: Only revoke active authorizations but keep print history intact
            
            # Only delete any related print authorizations and requests since they're no longer valid
            # but keep the print history records
            PrintAuthorization.query.filter_by(container_id=id).delete()
            PrintAccessRequest.query.filter_by(container_id=id).delete()
            
            db.session.commit()
            logger.info(f"Revoked authorizations for container {id} as it's being loaded onto vessel, but kept delivery order history")
            
            # Continue with the existing load container logic
            
            # Create a new container movement
            movement = ContainerMovement(
                container_id=container.id,
                vessel_id=vessel.id,
                operation_type='load',
                operation_date=datetime.strptime(operation_date, '%Y-%m-%d'),
                location=location,
                notes=notes
            )
            db.session.add(movement)
            
            # Update container status to 'loaded'
            status = ContainerStatus(
                container_id=container.id,
                status='loaded',
                date=datetime.strptime(operation_date, '%Y-%m-%d'),
                location=location,
                notes=notes
            )
            db.session.add(status)
            db.session.commit()
            
            flash(f'Container successfully loaded onto {vessel.name}. Print authorizations have been revoked but delivery order history is preserved.', 'success')
            return redirect(url_for('container_detail', id=container.id))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Error loading container: {str(e)}', 'danger')
            return redirect(url_for('load_container', id=id))
    
    return render_template('load_container.html', container=container, vessels=vessels, now=datetime.now())

@app.route('/containers/<int:id>/discharge', methods=['GET', 'POST'])
@login_required
def discharge_container(id):
    """Discharge container from a vessel"""
    container = Container.query.get_or_404(id)
    # Find current vessel (if any)
    current_location = container.get_current_location()
    if not current_location or current_location['type'] != 'vessel':
        flash('Container is not currently on a vessel!', 'danger')
        return redirect(url_for('container_detail', id=id))
    
    vessel = current_location['vessel']
    if request.method == 'POST':
        operation_date = datetime.strptime(request.form['operation_date'], '%Y-%m-%d')
        location = request.form['location']
        notes = request.form.get('notes', '')
        # Create container movement record
        movement = ContainerMovement(
            operation_type='discharge',
            operation_date=operation_date,
            location=location,
            notes=notes,
            container_id=container.id,
            vessel_id=vessel.id   
        )
        # Create a new status record to explicitly set the container as discharged
        status = ContainerStatus(
            status='discharged',  # Explicitly set to 'discharged'
            date=operation_date,
            location=location,
            notes=f"Discharged from vessel {vessel.name}" + (f": {notes}" if notes else ""),
            container_id=container.id   
        )
        
        # Remove setting stripping date on discharge - will be set when emptied
        
        db.session.add(movement)
        db.session.add(status)
        try:
            db.session.commit()
            # Force refresh the container from the database to get updated status
            db.session.refresh(container)
            
            # Verify the container status after discharge using direct query to bypass any caching
            latest_status = ContainerStatus.query.filter_by(container_id=container.id).order_by(ContainerStatus.date.desc()).first()
            logger.info(f"After discharge - Latest status directly from DB: {latest_status.status if latest_status else 'None'}")
            # Also check through the container's method
            refreshed_status = container.get_current_status()
            logger.info(f"After discharge - Container status from method: {refreshed_status.status if refreshed_status else 'None'}")
            
            flash(f'Container {container.container_number} discharged from vessel {vessel.name}.', 'success')
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error during discharge operation: {str(e)}")
            flash(f'Error discharging container: {str(e)}', 'danger')
        return redirect(url_for('container_detail', id=container.id))
    
    # Pre-fill the form with the vessel's current location
    return render_template('discharge_container.html', 
                          container=container, 
                          vessel=vessel, 
                          now=datetime.now(),
                          default_location=vessel.current_location or '')

@app.route('/vessels/<int:id>/delete', methods=['POST'])
@login_required
def delete_vessel(id):
    """Delete a vessel"""
    vessel = Vessel.query.get_or_404(id)
    vessel_name = vessel.name
    try:
        # Check if vessel has containers currently loaded
        loaded_containers = vessel.get_loaded_containers()
        
        # Get all movements related to this vessel
        movements = ContainerMovement.query.filter_by(vessel_id=id).all()
        
        # Update status for any containers on this vessel
        for container in loaded_containers:
            # Add a discharged status to indicate container is no longer on the vessel
            status = ContainerStatus(
                status='discharged',
                date=datetime.now(),
                location=vessel.current_location or 'Unknown',
                notes=f"Automatically discharged due to vessel {vessel_name} being deleted",
                container_id=container.id   
            )
            db.session.add(status)
        
        # First delete all container movement records for this vessel
        for movement in movements:
            db.session.delete(movement)
        
        # Then delete the vessel
        db.session.delete(vessel)
        db.session.commit()
        flash(f'Vessel {vessel_name} deleted successfully!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting vessel: {str(e)}', 'danger')
        logger.error(f"Vessel delete error: {str(e)}")
    return redirect(url_for('vessels'))

@app.route('/containers/bulk-load', methods=['POST'])
@login_required
def bulk_load_containers():
    """Endpoint for bulk loading multiple containers onto a vessel"""
    data = request.json
    container_ids = data.get('container_ids', [])
    vessel_id = data.get('vessel_id')
    operation_date = datetime.strptime(data.get('operation_date'), '%Y-%m-%d')
    location = data.get('location')
    notes = data.get('notes', '')
    
    # Validate vessel
    vessel = Vessel.query.get(vessel_id)
    if not vessel:
        return jsonify({'error': 'Invalid vessel selected'}), 400
    # Check if vessel has departed
    if vessel.status == 'Departed':
        return jsonify({'error': 'Cannot load containers onto a departed vessel'}), 400
    
    success_count = 0
    error_messages = []
    skipped_count = 0
    
    for container_id in container_ids:
        try:
            container = Container.query.get(container_id)
            if not container:
                error_messages.append(f"Container ID {container_id} not found")
                continue
            
            # Check container location against vessel location
            current_status = container.get_current_status()
            if not current_status or current_status.location != vessel.current_location:
                skipped_count += 1
                error_messages.append(f"Container {container.container_number} is in a different location than vessel")
                continue
                
            # Create container movement record 
            movement = ContainerMovement(
                operation_type='load',
                operation_date=operation_date,
                location=location,
                notes=notes,
                container_id=container_id,
                vessel_id=vessel_id   
            )
            
            # Update container status
            status = ContainerStatus(
                status='loaded',
                date=operation_date,
                location=location,
                notes=notes,
                container_id=container_id
            )
            
            db.session.add(movement)
            db.session.add(status)
            success_count += 1
            
        except Exception as e:
            error_messages.append(f"Error with container ID {container_id}: {str(e)}")
                
    if success_count > 0:
        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            return jsonify({'error': f"Database error: {str(e)}"}), 500
            
    result = {
        'success_count': success_count,
        'error_count': len(container_ids) - success_count - skipped_count,
        'skipped_count': skipped_count,
        'message': f"Loaded {success_count} containers. Skipped {skipped_count} containers due to location mismatch."
    }
    
    if error_messages:
        result['errors'] = error_messages
    return jsonify(result)

@app.route('/api/container/<int:id>/vessel')
@login_required  # Protect API endpoints
def get_container_vessel_info(id):
    """Get vessel information for a loaded container"""
    container = Container.query.get_or_404(id)
    current_location = container.get_current_location()
    if (current_location and current_location['type'] == 'vessel'):
        vessel = current_location['vessel']
        return jsonify({
            'success': True,
            'vessel_id': vessel.id,
            'vessel_name': vessel.name,
            'vessel_location': vessel.current_location or '',
            'container_id': container.id
        })
    else:
        return jsonify({
            'success': False,
            'error': 'Container is not currently on a vessel'
        }), 400

@app.route('/containers/bulk-discharge', methods=['POST'])
@login_required
def bulk_discharge_containers():
    """Endpoint for bulk discharging multiple containers from a vessel"""
    data = request.json
    container_ids = data.get('container_ids', [])
    vessel_id = data.get('vessel_id')
    operation_date = datetime.strptime(data.get('operation_date'), '%Y-%m-%d')
    location = data.get('location')
    notes = data.get('notes', '')
    
    # Validate vessel
    vessel = Vessel.query.get(vessel_id)
    if not vessel:
        return jsonify({'error': 'Invalid vessel selected'}), 400
    
    success_count = 0
    error_messages = []
    
    for container_id in container_ids:
        try:
            container = Container.query.get(container_id)
            if not container:
                error_messages.append(f"Container ID {container_id} not found")
                continue
            # Create container movement record 
            movement = ContainerMovement(
                operation_type='discharge',
                operation_date=operation_date,
                location=location,
                notes=notes,
                container_id=container_id,
                vessel_id=vessel_id   
            )
            # Update container status
            status = ContainerStatus(
                status='discharged',
                date=operation_date,
                location=location,
                notes=f"Discharged from vessel {vessel.name} (bulk operation)",
                container_id=container_id   
            )
            
            # Remove setting stripping date on discharge - will be set when emptied
            
            db.session.add(movement)
            db.session.add(status)
            success_count += 1
        except Exception as e:
            error_messages.append(f"Error with container ID {container_id}: {str(e)}")
                
    if success_count > 0:
        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            return jsonify({'error': f"Database error: {str(e)}"}), 500
    result = {
        'success_count': success_count,
        'error_count': len(container_ids) - success_count,
        'message': f"Discharged {success_count} containers."
    }
    
    if error_messages:
        result['errors'] = error_messages
    return jsonify(result)

@app.route('/update_vessel_statuses')
@login_required
def update_vessel_statuses():
    """Update vessel statuses based on ETA (manual route)"""
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    # Find vessels with ETAs and update their statuses
    vessels_to_update = Vessel.query.filter(Vessel.eta != None).all()
    updated_count = 0
    for vessel in vessels_to_update:
        if vessel.eta <= today and vessel.status != 'Arrived':
            vessel.status = 'Arrived'
            updated_count += 1
            # If vessel arrives, update location to be the destination
            if vessel.current_destination:
                vessel.current_location = vessel.current_destination
                vessel.current_destination = "---"
            
            # Update arrival date for all containers on this vessel
            loaded_containers = vessel.get_loaded_containers()
            container_count = 0
            for container in loaded_containers:
                container.arrival_date = vessel.eta or today
                container_count += 1
            
            if container_count > 0:
                logger.info(f"Updated arrival date for {container_count} containers to match vessel arrival.")
            
    if updated_count > 0:
        db.session.commit()
        flash(f'Updated status for {updated_count} vessels based on ETA', 'info')
    return redirect(url_for('vessels'))

def update_vessel_statuses_auto(vessel_id=None):
    """Automatically update vessel status based on ETA - can target specific vessel"""
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    updated = False
    try:
        if vessel_id:
            # Update just one vessel if ID is provided
            vessel = Vessel.query.get(vessel_id)
            if vessel and vessel.eta and vessel.eta <= today and vessel.status != 'Arrived':
                vessel.status = 'Arrived'
                # If vessel arrives, update location to be the destination
                if vessel.current_destination:
                    vessel.current_location = vessel.current_destination
                    vessel.current_destination = ""
                
                # Update arrival date for all containers on this vessel
                loaded_containers = vessel.get_loaded_containers()
                for container in loaded_containers:
                    # Use vessel's ETA as the arrival date, not today's date
                    container.arrival_date = vessel.eta
                    logger.info(f"Updated arrival date for container {container.container_number} to match vessel {vessel.name}'s arrival date: {vessel.eta}")
                
                updated = True
        else:
            # Update all vessels otherwise
            vessels = Vessel.query.filter(Vessel.eta != None).all()
            for vessel in vessels:
                if vessel.eta <= today and vessel.status != 'Arrived':
                    vessel.status = 'Arrived'
                    # If vessel arrives, update location to be the destination
                    if vessel.current_destination:
                        vessel.current_location = vessel.current_destination
                        vessel.current_destination = ""
                    
                    # Update arrival date for all containers on this vessel
                    loaded_containers = vessel.get_loaded_containers()
                    container_count = 0
                    for container in loaded_containers:
                        # Use vessel's ETA as the arrival date, not today's date
                        container.arrival_date = vessel.eta
                        container_count += 1
                    
                    if container_count > 0:
                        logger.info(f"Updated arrival date for {container_count} containers on vessel {vessel.name} to {vessel.eta}")
                    
                    updated = True
        
        # Commit if any changes were made
        if updated:
            db.session.commit()
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error auto-updating vessel statuses: {str(e)}")

@app.route('/admin')
@login_required        
def admin_panel():
    """Admin panel for system management"""
    if not current_user.is_admin:
        flash('You do not have permission to access the admin panel.', 'danger')
        return redirect(url_for('index'))
    # Get counts for dashboard
    user_count = User.query.count()
    container_count = Container.query.count()
    vessel_count = Vessel.query.count()
    
    # Get recent activity
    recent_containers = Container.query.order_by(Container.created_at.desc()).limit(5).all()
    recent_statuses = ContainerStatus.query.order_by(ContainerStatus.created_at.desc()).limit(10).all()
    recent_vessels = Vessel.query.order_by(Vessel.created_at.desc()).limit(5).all()
    return render_template('admin/panel.html',
                          user_count=user_count,
                          container_count=container_count,
                          vessel_count=vessel_count,
                          recent_containers=recent_containers,
                          recent_statuses=recent_statuses,
                          recent_vessels=recent_vessels)

@app.route('/admin/users')
@login_required
def admin_users():
    """Admin user management page"""
    if not current_user.is_admin:
        flash('You do not have permission to access the admin panel.', 'danger')
        return redirect(url_for('index'))
    users = User.query.all()
    return render_template('admin/users.html', users=users)

@app.route('/admin/users/create', methods=['GET', 'POST'])
@login_required
def admin_create_user():
    """Admin create user page"""
    if not current_user.is_admin:
        flash('You do not have permission to access the admin panel.', 'danger')
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']
        is_admin = 'is_admin' in request.form
        # Check if username or email already exists
        if User.query.filter_by(username=username).first():
            flash('Username already exists', 'danger')
            return redirect(url_for('admin_create_user'))
        if User.query.filter_by(email=email).first():
            flash('Email already exists', 'danger')
            return redirect(url_for('admin_create_user'))
        # Create new user
        new_user = User(
            username=username,
            email=email,
            is_admin=is_admin,
            created_at=datetime.now()
        )
        new_user.set_password(password)
        db.session.add(new_user)
        db.session.commit()
        flash(f'User {username} created successfully', 'success')
        return redirect(url_for('admin_users'))
    return render_template('admin/create_user.html')

@app.route('/admin/users/<int:id>/update', methods=['GET', 'POST'])
@login_required
def admin_update_user(id):
    """Admin update user page"""
    if not current_user.is_admin:
        flash('You do not have permission to access the admin panel.', 'danger')
        return redirect(url_for('index'))
    
    user = User.query.get_or_404(id)
    
    if request.method == 'POST':
        user.username = request.form['username']
        user.email = request.form['email']
        user.is_admin = 'is_admin' in request.form
        # Only update password if provided
        if request.form.get('password'):
            user.set_password(request.form['password'])
        db.session.commit()
        flash(f'User {user.username} updated successfully', 'success')
        return redirect(url_for('admin_users'))
    return render_template('admin/update_user.html', user=user)

@app.route('/admin/users/<int:id>/delete', methods=['POST'])
@login_required
def admin_delete_user(id):
    """Admin delete user action"""
    if not current_user.is_admin:
        flash('You do not have permission to access the admin panel.', 'danger')
        return redirect(url_for('index'))
    
    user = User.query.get_or_404(id)
    # Prevent deleting the current user
    if user.id == current_user.id:
        flash('You cannot delete your own account', 'danger')
        return redirect(url_for('admin_users'))
    
    db.session.delete(user)
    db.session.commit()
    flash(f'User {user.username} deleted successfully', 'success')
    return redirect(url_for('admin_users'))

@app.route('/admin/system', methods=['GET', 'POST'])
@login_required
def admin_system():
    """Admin system settings and information page"""
    if not current_user.is_admin:
        flash('You do not have permission to access the admin panel.', 'danger')
        return redirect(url_for('index'))
    # Get system information - make sure we have the absolute path
    db_uri = app.config['SQLALCHEMY_DATABASE_URI']
    if db_uri.startswith('sqlite:///'):
        db_path = db_uri.replace('sqlite:///', '')
        # If path is relative, make it absolute
        if not os.path.isabs(db_path):
            db_path = os.path.join(app.root_path, db_path)
    else:
        db_path = "Non-SQLite database"
    
    # Get database size if it exists
    db_size = 'Unknown'
    if os.path.exists(db_path) and os.path.isfile(db_path):
        db_size = f"{os.path.getsize(db_path) / (1024 * 1024):.2f} MB"
    
    # Count records in each table
    user_count = User.query.count()
    container_count = Container.query.count()
    vessel_count = Vessel.query.count()
    status_count = ContainerStatus.query.count()
    movement_count = ContainerMovement.query.count()
    
    # Get app configurations
    system_info = {
        'db_path': db_path,
        'db_size': db_size,
        'debug_mode': app.debug,
        'upload_folder': app.config['UPLOAD_FOLDER'],
        'allowed_file_types': ', '.join(app.config['ALLOWED_EXTENSIONS']),
        'secret_key_set': bool(app.config.get('SECRET_KEY')),
        'table_counts': {
            'users': user_count,
            'containers': container_count,
            'vessels': vessel_count,
            'statuses': status_count,
            'movements': movement_count
        },
        'python_version': sys.version,
        'flask_version': flask.__version__,
        'sqlalchemy_version': sqlalchemy.__version__
    }
    
    if request.method == 'POST':
        action = request.form.get('action')
        
        # Handle reset_delivery_counter action from form submission
        if action == 'reset_delivery_counter':
            try:
                new_value = int(request.form.get('new_value', 1))
                
                if new_value < 1:
                    flash('Invalid value. Counter must be a positive integer.', 'danger')
                    return redirect(url_for('admin_system'))
                
                counter = DeliveryCounter.query.first()
                if not counter:
                    counter = DeliveryCounter(counter=new_value)
                    db.session.add(counter)
                else:
                    counter.counter = new_value
                    counter.last_updated = datetime.utcnow()
                    
                db.session.commit()
                flash(f'Delivery order counter has been reset to {new_value}.', 'success')
            except Exception as e:
                db.session.rollback()
                flash(f'Error resetting counter: {str(e)}', 'danger')
            
            return redirect(url_for('admin_system'))
        
        if action == 'create_backup':
            try:
                # Use app context to ensure proper path resolution
                with app.app_context():
                    # Import locate_database function from fix_db
                    try:
                        from fix_db import locate_database
                        db_path = locate_database()
                    except ImportError:
                        # If function not available, fall back to default path resolution
                        if db_uri.startswith('sqlite:///'):
                            db_path = db_uri.replace('sqlite:///', '')
                            if not os.path.isabs(db_path):
                                db_path = os.path.join(app.root_path, db_path)
                        else:
                            raise ValueError("Only SQLite databases are supported for backup")
                    # Check if database file actually exists at this location
                    if not os.path.exists(db_path) or not os.path.isfile(db_path):
                        # Try the simplest possible path as a last resort
                        fallback_path = 'container_tracking.db'
                        if (os.path.exists(fallback_path)):
                            db_path = os.path.abspath(fallback_path)
                            logger.info(f"Using fallback database path: {db_path}")
                        else:
                            raise FileNotFoundError(f"Database file not found: {db_path}")
                # Create backup directory and copy file
                backup_path = os.path.join(app.root_path, 'backups')
                os.makedirs(backup_path, exist_ok=True)
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                backup_file = os.path.join(backup_path, f'database_backup_{timestamp}.db')
                
                import shutil
                shutil.copy2(db_path, backup_file)
                logger.info(f"Created backup at {backup_file}")
                
                flash(f'Database backup created successfully: {os.path.basename(backup_file)}', 'success')
            except Exception as e:
                flash(f'Error creating backup: {str(e)}', 'danger')
                logger.error(f"Backup error: {str(e)}")
        elif action == 'clear_logs':
            try:
                # Clear log files (example implementation)
                log_dir = os.path.join(app.root_path, 'logs')
                if (os.path.exists(log_dir)):
                    for log_file in os.listdir(log_dir):
                        if log_file.endswith('.log'):
                            os.remove(os.path.join(log_dir, log_file))
                flash('Log files cleared successfully', 'success')
            except Exception as e:
                flash(f'Error clearing logs: {str(e)}', 'danger')
                
        return redirect(url_for('admin_system'))
    
    # Get list of backups
    backup_path = os.path.join(app.root_path, 'backups')
    backups = []
    
    if (os.path.exists(backup_path)):
        for file in os.listdir(backup_path):
            if file.startswith('database_backup_') and file.endswith('.db'):
                file_path = os.path.join(backup_path, file)
                size = os.path.getsize(file_path)
                modified = datetime.fromtimestamp(os.path.getmtime(file_path))
                backups.append({
                    'name': file,
                    'path': file_path,
                    'size': f"{size / (1024 * 1024):.2f} MB",
                    'date': modified.strftime('%Y-%m-%d %H:%M:%S')
                })
    
    # Sort backups by date (newest first)
    backups.sort(key=lambda x: x['name'], reverse=True)
    
    return render_template(
        'admin/system.html',
        system_info=system_info,
        backups=backups
    )

# Add this route to handle the delivery counter reset with a proper API endpoint
@app.route('/api/admin/reset-delivery-counter', methods=['POST'])
@login_required
def admin_reset_delivery_counter():
    if not current_user.is_admin:
        return jsonify({'success': False, 'error': 'Unauthorized access'}), 403
    
    try:
        data = request.json
        new_value = data.get('new_value', 1)  # Default to 1 if no value provided
        
        if not isinstance(new_value, int) or new_value < 1:
            return jsonify({'success': False, 'error': 'Invalid value. Counter must be a positive integer.'}), 400
        
        # Get or create the counter
        counter = DeliveryCounter.query.first()
        if not counter:
            counter = DeliveryCounter(counter=new_value)
            db.session.add(counter)
        else:
            counter.counter = new_value
            counter.last_updated = datetime.utcnow()
            
        db.session.commit()
        
        return jsonify({'success': True, 'counter': counter.counter})
    
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/admin/backup/download/<filename>')
@login_required
def download_backup(filename):
    """Download a database backup file"""
    if not current_user.is_admin:
        flash('You do not have permission to access this resource.', 'danger')
        return redirect(url_for('index'))
    
    backup_path = os.path.join(app.root_path, 'backups')
    # Validate filename to prevent directory traversal attacks
    if '..' in filename or '/' in filename:
        flash('Invalid backup filename.', 'danger')
        return redirect(url_for('admin_system'))
    
    file_path = os.path.join(backup_path, filename)
    if not os.path.exists(file_path):
        flash('Backup file not found.', 'danger')
        return redirect(url_for('admin_system'))
    
    return send_file(
        file_path,
        as_attachment=True,
        download_name=filename
    )

@app.route('/admin/backup/delete/<filename>', methods=['POST'])
@login_required
def delete_backup(filename):
    """Delete a database backup file"""
    if not current_user.is_admin:
        flash('You do not have permission to access this resource.', 'danger')
        return redirect(url_for('index'))
    
    backup_path = os.path.join(app.root_path, 'backups')
    # Validate filename to prevent directory traversal attacks
    if '..' in filename or '/' in filename:
        flash('Invalid backup filename.', 'danger')
        return redirect(url_for('admin_system'))
    
    file_path = os.path.join(backup_path, filename)
    if os.path.exists(file_path):
        os.remove(file_path)
        flash('Backup file deleted successfully.', 'success')
    else:
        flash('Backup file not found.', 'danger')
    return redirect(url_for('admin_system'))

@app.route('/admin/diagnostics')
@login_required
def admin_diagnostics():
    """Admin diagnostic page to troubleshoot system issues"""
    if not current_user.is_admin:
        flash('You do not have permission to access this page.', 'danger')
        return redirect(url_for('index'))
    
    diagnostics = {}
    
    # Get database information
    db_uri = app.config['SQLALCHEMY_DATABASE_URI']
    diagnostics['database_uri'] = db_uri
    if db_uri.startswith('sqlite:///'):
        rel_db_path = db_uri.replace('sqlite:///', '')
        abs_db_path = rel_db_path
        
        # If path is relative, make it absolute
        if not os.path.isabs(rel_db_path):
            abs_db_path = os.path.join(app.root_path, rel_db_path)
        
        diagnostics['relative_db_path'] = rel_db_path
        diagnostics['absolute_db_path'] = abs_db_path    
        diagnostics['db_file_exists'] = os.path.exists(abs_db_path)
        if os.path.exists(abs_db_path):
            diagnostics['db_size'] = f"{os.path.getsize(abs_db_path) / 1024:.2f} KB"
            diagnostics['db_modified'] = datetime.fromtimestamp(os.path.getmtime(abs_db_path)).strftime('%Y-%m-%d %H:%M:%S')
    
    # Check app directories
    app_dir = app.root_path
    diagnostics['app_directory'] = app_dir
    diagnostics['backups_dir'] = os.path.join(app_dir, 'backups')
    diagnostics['backups_dir_exists'] = os.path.exists(diagnostics['backups_dir'])
    diagnostics['uploads_dir'] = os.path.join(app_dir, 'uploads')
    diagnostics['uploads_dir_exists'] = os.path.exists(diagnostics['uploads_dir'])
    
    # Current working directory
    diagnostics['current_working_dir'] = os.getcwd()
    
    # List files in app directory (up to 10)
    try:
        files = os.listdir(app_dir)[:10]
        diagnostics['app_dir_files'] = files
    except Exception as e:
        diagnostics['app_dir_files_error'] = str(e)
    
    return render_template('admin/diagnostics.html', diagnostics=diagnostics)

@app.route('/admin/reset-db', methods=['POST'])
@login_required
def admin_reset_db():
    """Reset the database but keep admin accounts using batched deletion"""
    # Get the confirmation text
    confirm = request.form.get('confirm', '')
    
    if confirm != 'RESET':
        flash('Please type RESET to confirm database reset', 'danger')
        return redirect(url_for('admin_system'))
    
    try:
        # Store the current admin user information
        admin_users = User.query.filter_by(is_admin=True).all()
        admin_data = []
        for admin in admin_users:
            admin_data.append({
                'username': admin.username,
                'email': admin.email,
                'password_hash': admin.password_hash,  # Save the hashed password
                'is_admin': True
            })
        
        flash('Database reset started. This may take some time...', 'info')
        
        # Batch size for deletion
        batch_size = 500
        progress_message = "Deleting data in batches: "
        
        # Delete in correct order to respect foreign keys
        # Start with tables that have foreign key references to other tables
        
        # 1. First delete print history records
        total_deleted = 0
        flash(progress_message + "Print history...", 'info')
        while True:
            ids = db.session.query(PrintHistory.id).limit(batch_size).all()
            if not ids:
                break
            id_list = [id[0] for id in ids]
            PrintHistory.query.filter(PrintHistory.id.in_(id_list)).delete(synchronize_session=False)
            db.session.commit()
            total_deleted += len(id_list)
            logger.info(f"Deleted {total_deleted} print history records")
        
        # 2. Delete print authorizations
        total_deleted = 0
        flash(progress_message + "Print authorizations...", 'info')
        while True:
            ids = db.session.query(PrintAuthorization.id).limit(batch_size).all()
            if not ids:
                break
            id_list = [id[0] for id in ids]
            PrintAuthorization.query.filter(PrintAuthorization.id.in_(id_list)).delete(synchronize_session=False)
            db.session.commit()
            total_deleted += len(id_list)
            logger.info(f"Deleted {total_deleted} print authorizations")
        
        # 3. Delete print access requests
        total_deleted = 0
        flash(progress_message + "Print requests...", 'info')
        while True:
            ids = db.session.query(PrintAccessRequest.id).limit(batch_size).all()
            if not ids:
                break
            id_list = [id[0] for id in ids]
            PrintAccessRequest.query.filter(PrintAccessRequest.id.in_(id_list)).delete(synchronize_session=False)
            db.session.commit()
            total_deleted += len(id_list)
            logger.info(f"Deleted {total_deleted} print access requests")
        
        # 4. Delete container statuses
        total_deleted = 0
        flash(progress_message + "Container statuses...", 'info')
        while True:
            ids = db.session.query(ContainerStatus.id).limit(batch_size).all()
            if not ids:
                break
            id_list = [id[0] for id in ids]
            ContainerStatus.query.filter(ContainerStatus.id.in_(id_list)).delete(synchronize_session=False)
            db.session.commit()
            total_deleted += len(id_list)
            logger.info(f"Deleted {total_deleted} container statuses")
        
        # 5. Delete container movements
        total_deleted = 0
        flash(progress_message + "Container movements...", 'info')
        while True:
            ids = db.session.query(ContainerMovement.id).limit(batch_size).all()
            if not ids:
                break
            id_list = [id[0] for id in ids]
            ContainerMovement.query.filter(ContainerMovement.id.in_(id_list)).delete(synchronize_session=False)
            db.session.commit()
            total_deleted += len(id_list)
            logger.info(f"Deleted {total_deleted} container movements")
        
        # 6. Delete containers
        total_deleted = 0
        flash(progress_message + "Containers...", 'info')
        while True:
            ids = db.session.query(Container.id).limit(batch_size).all()
            if not ids:
                break
            id_list = [id[0] for id in ids]
            Container.query.filter(Container.id.in_(id_list)).delete(synchronize_session=False)
            db.session.commit()
            total_deleted += len(id_list)
            logger.info(f"Deleted {total_deleted} containers")
        
        # 7. Delete clients (add this new deletion step)
        total_deleted = 0
        flash(progress_message + "Clients...", 'info')
        while True:
            ids = db.session.query(Client.id).limit(batch_size).all()
            if not ids:
                break
            id_list = [id[0] for id in ids]
            Client.query.filter(Client.id.in_(id_list)).delete(synchronize_session=False)
            db.session.commit()
            total_deleted += len(id_list)
            logger.info(f"Deleted {total_deleted} clients")
        
        # 8. Delete vessels
        total_deleted = 0
        flash(progress_message + "Vessels...", 'info')
        while True:
            ids = db.session.query(Vessel.id).limit(batch_size).all()
            if not ids:
                break
            id_list = [id[0] for id in ids]
            Vessel.query.filter(Vessel.id.in_(id_list)).delete(synchronize_session=False)
            db.session.commit()
            total_deleted += len(id_list)
            logger.info(f"Deleted {total_deleted} vessels")
        
        # 9. Delete non-admin users
        total_deleted = 0
        flash(progress_message + "Users...", 'info')
        User.query.filter_by(is_admin=False).delete()
        db.session.commit()
        
        # 10. Reset delivery counter
        DeliveryCounter.query.delete()
        db.session.add(DeliveryCounter(counter=1))
        db.session.commit()
        
        # Recreate admin accounts if they were accidentally deleted
        for admin in admin_data:
            existing_admin = User.query.filter_by(username=admin['username']).first()
            if not existing_admin:
                new_admin = User(
                    username=admin['username'],
                    email=admin['email'],
                    password_hash=admin['password_hash'],
                    is_admin=True
                )
                db.session.add(new_admin)
        
        db.session.commit()
        flash('Database has been successfully reset. All data except admin accounts has been deleted.', 'success')
        
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error resetting database: {str(e)}")
        flash(f'Error resetting database: {str(e)}', 'danger')
    
    return redirect(url_for('logout'))

@app.route('/containers/bulk-status-update', methods=['POST'])
@login_required
def bulk_status_update():
    """Endpoint for bulk updating container statuses"""
    data = request.json
    container_ids = data.get('container_ids', [])
    status = data.get('status')
    operation_date = datetime.strptime(data.get('date'), '%Y-%m-%d')
    location = data.get('location')
    notes = data.get('notes', '')
    
    success_count = 0
    error_messages = []
    
    for container_id in container_ids:
        try:
            container = Container.query.get(container_id)
            if not container:
                error_messages.append(f"Container ID {container_id} not found")
                continue
            # Create new status record
            new_status = ContainerStatus(
                status=status,
                date=operation_date,
                location=location,
                notes=notes,
                container_id=container_id
            )
            db.session.add(new_status)
            
            # Set stripping date if status is emptied
            if status == 'emptied':
                container.stripping_date = operation_date
                
            success_count += 1
        except Exception as e:
            error_messages.append(f"Error with container ID {container_id}: {str(e)}")
                
    if success_count > 0:
        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            return jsonify({'error': f"Database error: {str(e)}"}), 500
    result = {
        'success_count': success_count,
        'error_count': len(container_ids) - success_count,
        'message': f"Updated status for {success_count} containers."
    }
    
    if error_messages:
        result['errors'] = error_messages
    return jsonify(result)

@app.route('/api/vessels/available')
@login_required  # Protect API endpoints
def get_available_vessels():
    """Get vessels that are available for loading (not departed)"""
    # Query vessels that haven't departed, order by created_at (most recent first), limit to 5
    vessels = Vessel.query.filter(Vessel.status != 'Departed')\
                         .order_by(Vessel.created_at.desc())\
                         .limit(5)\
                         .all()
    
    result = []
    for vessel in vessels:
        result.append({
            'id': vessel.id,
            'name': vessel.name,
            'imo_number': vessel.imo_number  # We keep field name in API for compatibility
        })
    return jsonify(result)

# Add a new route to recreate the database
@app.route('/admin/recreate-db', methods=['POST'])
@login_required
def recreate_database():
    """Delete and recreate the database with the new schema"""
    if not current_user.is_admin:
        flash('You do not have permission to perform this action.', 'danger')
        return redirect(url_for('index'))
    
    confirmation = request.form.get('confirm')
    if confirmation != 'RECREATE':
        flash('Invalid confirmation. Database recreation aborted.', 'danger')
        return redirect(url_for('admin_system'))
    
    try:
        # Create a backup first
        db_uri = app.config['SQLALCHEMY_DATABASE_URI']
        if db_uri.startswith('sqlite:///'):
            db_path = db_uri.replace('sqlite:///', '')
            # If path is relative, make it absolute
            if not os.path.isabs(db_path):
                db_path = os.path.join(app.root_path, db_path)
            if os.path.exists(db_path):
                # Create backups directory
                backup_path = os.path.join(app.root_path, 'backups')
                os.makedirs(backup_path, exist_ok=True)
                # Create backup with timestamp
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                backup_file = os.path.join(backup_path, f'before_recreate_{timestamp}.db')
                
                import shutil
                shutil.copy2(db_path, backup_file)
                logger.info(f"Created backup at {backup_file}")
                
                # Delete the database file
                os.remove(db_path)
                logger.info(f"Deleted database file: {db_path}")
        
        # Recreate all tables in the database
        with app.app_context():
            db.create_all()
            
            # Create an initial admin user
            if User.query.count() == 0:
                admin_user = User(
                    username='admin',
                    email='admin@example.com',
                    is_admin=True
                )
                admin_user.set_password('admin')  # Default password, should be changed immediately
                db.session.add(admin_user)
                db.session.commit()
                flash('Database has been recreated with a default admin user (username: admin, password: admin). Please change the password immediately.', 'warning')
        
        flash('Database has been successfully deleted and recreated with the new schema!', 'success')
    except Exception as e:
        flash(f'Error recreating database: {str(e)}', 'danger')
        logger.error(f"Database recreation error: {str(e)}")
    
    return redirect(url_for('admin_system'))

# Replace @app.before_first_request with an alternative approach
# When starting the app, ensure the template file exists
# Remove the @app.before_first_request decorator and use a different approach
def initialize_app():
    """Initialize any app resources on startup"""
    # Ensure the template file exists
    static_template_path = os.path.join(app.root_path, 'static', 'templates', 'container_import_template.xlsx')
    if not os.path.exists(static_template_path):
        # Create the directory if it doesn't exist
        os.makedirs(os.path.dirname(static_template_path), exist_ok=True)
        # Create the template
        create_import_template(static_template_path)
        logger.info(f"Created container import template at {static_template_path}")

# Call initialize_app at application startup
with app.app_context():
    initialize_app()

@app.route('/import-guide')
@login_required
def import_guide():
    """View the import guide"""
    return send_file(
        os.path.join(app.root_path, 'static', 'templates', 'import_guide.html')
    )

@app.route('/containers/<int:id>/delivery-order')
@login_required
def delivery_order(id):
    """Generate a delivery order receipt for a discharged container"""
    container = Container.query.get_or_404(id)
    
    # Check if container is discharged
    latest_status = container.get_current_status()
    if not latest_status or latest_status.status != 'discharged':
        flash('Delivery order is only available for discharged containers.', 'warning')
        return redirect(url_for('container_detail', id=id))
    
    # Get discharge information
    discharge_movement = ContainerMovement.query.filter_by(
        container_id=container.id, 
        operation_type='discharge'
    ).order_by(ContainerMovement.operation_date.desc()).first()
    
    vessel = None
    discharge_date = None
    discharge_location = None
    notes = None
    loading_location = None  # New variable to store the origin loading location
    
    if discharge_movement:
        vessel = Vessel.query.get(discharge_movement.vessel_id)
        discharge_date = discharge_movement.operation_date
        discharge_location = discharge_movement.location
        notes = discharge_movement.notes
        
        # Find the loading movement for this container on the same vessel
        # The loading should have happened before the discharge
        load_movement = ContainerMovement.query.filter_by(
            container_id=container.id,
            vessel_id=vessel.id,
            operation_type='load'
        ).filter(ContainerMovement.operation_date < discharge_movement.operation_date).first()
        
        if load_movement:
            loading_location = load_movement.location
        else:
            # Fallback to container's loading port if no load movement found
            loading_location = container.loading_port
    
    return render_template(
        'delivery_order.html',
        container=container,
        vessel=vessel,
        discharge_date=discharge_date,
        discharge_location=discharge_location,
        loading_location=loading_location,  # Pass the loading location to the template
        notes=notes,
        now=datetime.now()
    )

# Add this route to your Flask application
@app.route('/api/container-exists/<container_number>')
def check_container_exists(container_number):
    container = Container.query.filter_by(container_number=container_number).first()
    if container:
        return jsonify({
            'exists': True,
            'container_id': container.id,
            'container_type': container.container_type
        })
    return jsonify({'exists': False})

@app.route('/api/search-containers/<query>')
def search_containers(query):
    """API endpoint to search for containers by partial container number"""
    if not query or len(query) < 2:
        return jsonify([])
    
    # Search for containers that start with the query string (case-insensitive)
    containers = Container.query.filter(
        Container.container_number.ilike(f'{query}%')
    ).limit(10).all()
    
    results = []
    for container in containers:
        results.append({
            'id': container.id,
            'container_number': container.container_number,
            'container_type': container.container_type,
            'bl_number': container.bl_number
        })
    
    return jsonify(results)

@app.route('/admin/print-authorizations')
@login_required
def admin_print_authorizations():
    """Admin page to view and manage delivery order print authorizations"""
    if not current_user.is_admin:
        flash('You do not have permission to access this page.', 'danger')
        return redirect(url_for('index'))
    
    # Get all users for the dropdown
    users = User.query.all()
    
    # Get recent prints
    recent_prints = PrintHistory.query.order_by(PrintHistory.print_date.desc()).limit(50).all()
    
    # Get pending authorizations
    pending_authorizations = PrintAuthorization.query.filter_by(used=False).all()
    
    # Get pending print access requests
    pending_requests = PrintAccessRequest.query.filter_by(status='pending').all()
    
    # Get containers with print history that might need authorization
    blocked_containers = []
    
    return render_template(
        'admin/print_authorizations.html',
        users=users,
        recent_prints=recent_prints,
        pending_authorizations=pending_authorizations,
        pending_requests=pending_requests,
        blocked_containers=blocked_containers
    )

@app.route('/api/container/<int:id>/print-history')
@login_required
def get_container_print_history(id):
    """API endpoint to get the print history of a container's delivery order"""
    container = Container.query.get_or_404(id)
    
    try:
        # If PrintHistory model exists, query it
        if 'PrintHistory' in globals():
            history = PrintHistory.query.filter_by(container_id=id).order_by(PrintHistory.print_date.desc()).all()
            
            result = []
            for item in history:
                result.append({
                    'date': item.print_date.strftime('%Y-%m-%d %H:%M'),
                    'user': item.user.username,
                    'do_number': item.do_number,
                    'authorized_by': item.authorized_by.username if item.authorized_by else None
                })
            
            return jsonify(result)
        else:
            # Return empty list if model doesn't exist yet
            return jsonify([])
    except Exception as e:
        # Log the exception but return an empty list to avoid breaking the UI
        app.logger.error(f"Error fetching print history: {str(e)}")
        return jsonify([])

@app.route('/api/users/list')
@login_required
def get_users_list():
    """API endpoint to get the list of users for authorization forms"""
    if not current_user.is_admin:
        return jsonify([])
    
    users = User.query.all()
    user_list = [{'id': user.id, 'username': user.username} for user in users]
    return jsonify(user_list)

@app.route('/containers/<int:id>/authorize-print', methods=['POST'])
@login_required
def authorize_additional_print(id):
    """Endpoint to authorize additional prints of a delivery order"""
    if not current_user.is_admin:
        flash('Only administrators can authorize additional prints.', 'danger')
        return redirect(url_for('container_detail', id=id))
    
    container = Container.query.get_or_404(id)
    user_id = request.form.get('user_id')
    
    if not user_id:
        flash('No user selected for authorization.', 'danger')
        return redirect(url_for('container_detail', id=id))
    
    user = User.query.get(user_id)
    if not user:
        flash('Selected user not found.', 'danger')
        return redirect(url_for('container_detail', id=id))
    
    # Check if user already has an unused authorization
    existing_auth = PrintAuthorization.query.filter_by(
        container_id=container.id,
        user_id=user.id,
        used=False
    ).first()
    
    if existing_auth:
        flash(f'{user.username} already has an unused authorization for this container.', 'warning')
        return redirect(url_for('container_detail', id=id))
    
    # Create a new print authorization
    auth = PrintAuthorization(
        container_id=container.id,
        user_id=user.id,
        authorized_by_id=current_user.id
    )
    
    try:
        db.session.add(auth)
        db.session.commit()
        flash(f'Successfully authorized {user.username} to print delivery order for container {container.container_number}.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error creating authorization: {str(e)}', 'danger')
    
    return redirect(url_for('container_detail', id=id))

@app.route('/api/verify-print-authorization/<int:container_id>')
@login_required
def verify_print_authorization(container_id):
    """API endpoint to verify if a user is authorized to print a delivery order"""
    container = Container.query.get_or_404(container_id)
    is_authorized = container.can_print_delivery_order(current_user.id)
    
    return jsonify({
        'authorized': is_authorized
    })

@app.route('/api/admin/authorize-print', methods=['POST'])
@login_required
def admin_authorize_print():
    """Admin API endpoint to authorize a user to print a container's delivery order"""
    if not current_user.is_admin:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403
        
    # This would normally update a database record
    # For now, just return success
    return jsonify({'success': True})

@app.route('/api/confirm-delivery-print', methods=['POST'])
@login_required
def confirm_delivery_print():
    try:
        data = request.get_json()
        container_id = data.get('container_id')
        do_number = data.get('do_number')
        
        # Validate required fields
        if not container_id:
            return jsonify({'success': False, 'error': 'Container ID is required'}), 400
            
        if not do_number:
            return jsonify({'success': False, 'error': 'Delivery Order Number is required'}), 400
        
        # Get the container to verify it exists
        container = Container.query.get_or_404(container_id)
        
        # Find active authorization for this user and container, if any
        authorization = PrintAuthorization.query.filter_by(
            container_id=container_id,
            user_id=current_user.id,
            used=False
        ).first()
        
        # Create a new print record
        print_record = PrintHistory(
            container_id=container_id,
            user_id=current_user.id,
            print_date=datetime.utcnow(),
            do_number=do_number,
            # Set authorized_by_id from the authorization if one exists
            authorized_by_id=authorization.authorized_by_id if authorization else None
        )
        
        db.session.add(print_record)
        
        # Mark the authorization as used if one was found
        if authorization:
            authorization.used = True
            logger.info(f"Authorization {authorization.id} marked as used after printing by {current_user.username}")
        
        db.session.commit()
        
        return jsonify({
            'success': True, 
            'do_number': do_number,
            'message': 'Print record created successfully'
        })
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error confirming delivery print: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

# Add API endpoint to get the current counter
@app.route('/api/get-delivery-counter')
@app.route('/api/current-delivery-counter')  # Support both URLs
@login_required
def get_delivery_counter():
    """Get the current delivery order counter value"""
    counter = DeliveryCounter.query.first()
    
    # If no counter exists, create one starting at 1
    if not counter:
        counter = DeliveryCounter(counter=1)
        db.session.add(counter)
        db.session.commit()
    
    return jsonify({'counter': counter.counter})

# Add API endpoint to increment the counter
@app.route('/api/increment-delivery-counter', methods=['POST'])
@login_required
def increment_delivery_counter():
    """Increment the delivery order counter"""
    try:
        counter = DeliveryCounter.query.first()
        
        # If no counter exists, create one starting at 1
        if not counter:
            counter = DeliveryCounter(counter=1)
            db.session.add(counter)
        else:
            # Increment the existing counter
            counter.counter += 1
            counter.last_updated = datetime.utcnow()
            
        db.session.commit()
        
        return jsonify({'success': True, 'counter': counter.counter})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/admin/authorization/<int:id>/revoke', methods=['POST'])
@login_required
def admin_revoke_authorization(id):
    """Admin endpoint to revoke a print authorization"""
    if not current_user.is_admin:
        flash('You do not have permission to perform this action.', 'danger')
        return redirect(url_for('index'))
    
    # Get the authorization by ID
    authorization = PrintAuthorization.query.get_or_404(id)
    
    try:
        # Delete the authorization
        db.session.delete(authorization)
        db.session.commit()
        flash('Authorization successfully revoked.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error revoking authorization: {str(e)}', 'danger')
    
    return redirect(url_for('admin_print_authorizations'))

@app.route('/containers/<int:id>/request-print-access', methods=['POST'])
@login_required
def request_print_access(id):
    """Endpoint for users to request print access for a delivery order"""
    container = Container.query.get_or_404(id)
    
    # Check if there's already a pending request from this user
    existing_request = PrintAccessRequest.query.filter_by(
        container_id=container.id, 
        user_id=current_user.id,
        status='pending'
    ).first()
    
    if existing_request:
        flash('You already have a pending request for this container.', 'warning')
        return redirect(url_for('container_detail', id=id))
    
    # Create new request
    new_request = PrintAccessRequest(
        container_id=container.id,
        user_id=current_user.id
    )
    
    db.session.add(new_request)
    db.session.commit()
    
    flash('Your request for print access has been submitted to administrators.', 'success')
    return redirect(url_for('container_detail', id=id))

@app.route('/admin/print-requests')
@login_required
def admin_print_requests():
    """Admin page to view print access requests"""
    if not current_user.is_admin:
        flash('You do not have permission to access this page.', 'danger')
        return redirect(url_for('index'))
    
    pending_requests = PrintAccessRequest.query.filter_by(status='pending').all()
    
    return render_template('admin/print_requests.html', pending_requests=pending_requests)

@app.route('/admin/print-request/<int:id>/approve', methods=['POST'])
@login_required
def approve_print_request(id):
    """Admin endpoint to approve a print access request"""
    if not current_user.is_admin:
        flash('You do not have permission to perform this action.', 'danger')
        return redirect(url_for('index'))
    
    access_request = PrintAccessRequest.query.get_or_404(id)
    
    # Update the request status
    access_request.status = 'approved'
    
    # Create a print authorization
    authorization = PrintAuthorization(
        container_id=access_request.container_id,
        user_id=access_request.user_id,
        authorized_by_id=current_user.id
    )
    
    db.session.add(authorization)
    db.session.commit()
    
    flash('Print request approved and user has been authorized.', 'success')
    return redirect(url_for('admin_print_authorizations'))

@app.route('/admin/print-request/<int:id>/reject', methods=['POST'])
@login_required
def reject_print_request(id):
    """Admin endpoint to reject a print access request"""
    if not current_user.is_admin:
        flash('You do not have permission to perform this action.', 'danger')
        return redirect(url_for('index'))
    
    access_request = PrintAccessRequest.query.get_or_404(id)
    access_request.status = 'rejected'
    db.session.commit()
    
    flash('Print request has been rejected.', 'success')
    return redirect(url_for('admin_print_authorizations'))

# Add this new API endpoint specifically for delivery order container filtering
@app.route('/api/search-containers-for-delivery/<search_term>')
def search_containers_for_delivery(search_term):
    # Get filter criteria from query parameters
    parent_id = request.args.get('parent_id')
    bl_number = request.args.get('bl_number', '')
    vessel_name = request.args.get('vessel_name', '')
    voyage_number = request.args.get('voyage_number', '')
    
    # Base query - containers with matching container number pattern
    query = Container.query.filter(Container.container_number.like(f'%{search_term}%'))
    
    # Filter by BL number - this is a direct field on the Container model
    if bl_number:
        query = query.filter(Container.bl_number == bl_number)
    
    # For vessel name and voyage number filtering, we need to find matching vessels first
    if vessel_name and voyage_number:
        # Find the vessel with matching name and voyage number
        vessel = Vessel.query.filter(
            Vessel.name == vessel_name,
            Vessel.imo_number == voyage_number
        ).first()
        
        if vessel:
            # Find container IDs that have movements with this vessel
            container_ids = db.session.query(ContainerMovement.container_id).filter(
                ContainerMovement.vessel_id == vessel.id
            ).distinct().subquery()
            
            # Add this as an additional filter to our query
            query = query.filter(Container.id.in_(container_ids))
    
    # Exclude the parent container itself if specified
    if parent_id and parent_id.isdigit():
        query = query.filter(Container.id != int(parent_id))
    
    # Limit for performance
    containers = query.limit(10).all()
    
    # Convert to dict for JSON response
    result = []
    for container in containers:
        result.append({
            'id': container.id,
            'container_number': container.container_number,
            'container_type': container.container_type or 'Unknown',
            'bl_number': container.bl_number or 'N/A'
        })
    
    return jsonify(result)

@app.route('/admin/delivery-orders')
@login_required
def admin_delivery_orders():
    """Admin page to view history of delivery orders printed, grouped by container"""
    if not current_user.is_admin:
        flash('You do not have permission to access this page.', 'danger')
        return redirect(url_for('index'))
    
    # Get date range from query parameters
    start_date_str = request.args.get('start_date')
    end_date_str = request.args.get('end_date')
    
    # Parse dates if provided
    start_date = None
    end_date = None
    
    if start_date_str:
        try:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d')
        except ValueError:
            flash('Invalid start date format', 'warning')
    
    if end_date_str:
        try:
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d')
            # Set end date to end of day for inclusive filtering
            end_date = end_date.replace(hour=23, minute=59, second=59)
        except ValueError:
            flash('Invalid end date format', 'warning')
    
    # Base query for print history - apply date filtering if parameters provided
    print_history_query = PrintHistory.query
    
    if start_date:
        print_history_query = print_history_query.filter(PrintHistory.print_date >= start_date)
    
    if end_date:
        print_history_query = print_history_query.filter(PrintHistory.print_date <= end_date)
    
    # Get distinct container IDs with print history (after date filtering)
    containers_with_prints = print_history_query.with_entities(PrintHistory.container_id).distinct().subquery()
    
    # Get all containers that have print history matching our filters
    # CHANGE: Show ALL containers with print history, regardless of current status
    containers = Container.query.filter(Container.id.in_(containers_with_prints)).all()
    
    # For each container, get its print history (with date filter)
    container_print_data = []
    total_prints = 0
    
    for container in containers:
        # Get print history for this container with date filtering
        prints_query = PrintHistory.query.filter_by(container_id=container.id)
        
        if start_date:
            prints_query = prints_query.filter(PrintHistory.print_date >= start_date)
        
        if end_date:
            prints_query = prints_query.filter(PrintHistory.print_date <= end_date)
        
        prints = prints_query.order_by(PrintHistory.print_date.desc()).all()
        
        # If no prints match our filter after all, skip this container
        if not prints:
            continue
        
        total_prints += len(prints)
        
        # Get vessel information - check if currently on vessel first
        current_location = container.get_current_location()
        if current_location and current_location['type'] == 'vessel':
            vessel = current_location['vessel']
            vessel_name = vessel.name
            voyage_number = vessel.imo_number
        else:
            # If not currently on vessel, check discharge movement
            discharge_movement = ContainerMovement.query.filter_by(
                container_id=container.id, 
                operation_type='discharge'
            ).order_by(ContainerMovement.operation_date.desc()).first()
            
            vessel_name = "Unknown"
            voyage_number = "Unknown"
            if discharge_movement:
                vessel = Vessel.query.get(discharge_movement.vessel_id)
                if vessel:
                    vessel_name = vessel.name
                    voyage_number = vessel.imo_number
        
        container_print_data.append({
            'container': container,
            'print_count': len(prints),  # Only count prints that match our filter
            'first_print': prints[-1] if prints else None,  # Earliest print
            'latest_print': prints[0] if prints else None,  # Most recent print
            'all_prints': prints,  # Only prints that match our filter
            'vessel_name': vessel_name,
            'voyage_number': voyage_number,
            'bl_number': container.bl_number or 'N/A'
        })
    
    # Sort by most recent print date
    container_print_data.sort(
        key=lambda x: x['latest_print'].print_date if x['latest_print'] else datetime.min,
        reverse=True
    )
    
    return render_template(
        'admin/delivery_orders.html',
        container_print_data=container_print_data,
        start_date=start_date_str,
        end_date=end_date_str,
        total_containers=len(container_print_data),
        total_prints=total_prints
    )

@app.route('/admin/backup/create-directory', methods=['POST'])
@login_required
def admin_create_backup_dir():
    """Admin endpoint to create a backup directory"""
    if not current_user.is_admin:
        flash('You do not have permission to perform this action.', 'danger')
        return redirect(url_for('index'))
    
    try:
        # Create backup directory
        backup_path = os.path.join(app.root_path, 'backups')
        os.makedirs(backup_path, exist_ok=True)
        
        # Create a timestamped subdirectory for organized backups
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_subdir = os.path.join(backup_path, f'backup_{timestamp}')
        os.makedirs(backup_subdir, exist_ok=True)
        
        flash(f'Backup directory created successfully: backup_{timestamp}', 'success')
    except Exception as e:
        flash(f'Error creating backup directory: {str(e)}', 'danger')
        
    return redirect(url_for('admin_system'))

# Add this new route for admin reports
@app.route('/admin/reports')
@login_required
def admin_reports():
    """Admin reports dashboard with graphs and analytics"""
    if not current_user.is_admin:
        flash('You do not have permission to access this page.', 'danger')
        return redirect(url_for('index'))
    
    # Get date range from query parameters
    start_date_str = request.args.get('start_date')
    end_date_str = request.args.get('end_date')
    
    # Today's date for default date range
    today = datetime.now().date()
    
    # Parse dates if provided
    start_date = None
    end_date = None
    
    if start_date_str:
        try:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d')
        except ValueError:
            start_date = datetime.now() - timedelta(days=30)
    else:
        # Default to last 30 days
        start_date = datetime.now() - timedelta(days=30)
    
    if end_date_str:
        try:
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d')
            # Set end date to end of day for inclusive filtering
            end_date = end_date.replace(hour=23, minute=59, second=59)
        except ValueError:
            end_date = datetime.now()
    else:
        # Default to today (end of day)
        end_date = datetime.now().replace(hour=23, minute=59, second=59)
    
    # Get basic statistics for the dashboard
    total_container_count = Container.query.count()
    
    # Get latest status subquery (reuse from other queries)
    latest_status_subquery = db.session.query(
        ContainerStatus.container_id,
        db.func.max(ContainerStatus.created_at).label('max_date')
    ).group_by(ContainerStatus.container_id).subquery('latest_status')
    
    # Count containers by status
    status_counts = {}
    for status in ['loaded', 'discharged', 'emptied', 'full']:
        count = db.session.query(Container)\
            .join(latest_status_subquery, Container.id == latest_status_subquery.c.container_id)\
            .join(ContainerStatus, db.and_(
                ContainerStatus.container_id == latest_status_subquery.c.container_id,
                ContainerStatus.created_at == latest_status_subquery.c.max_date,
                ContainerStatus.status == status
            ))\
            .count()
        status_counts[status] = count
    
    # Add client statistics
    client_count = Client.query.count()
    
    # Get clients with their container counts (with date filter)
    clients_with_containers = []
    for client in Client.query.all():
        if start_date and end_date:
            # Count containers created within date range
            container_count = Container.query.filter(
                Container.client_id == client.id,
                Container.created_at >= start_date,
                Container.created_at <= end_date
            ).count()
        else:
            # Count all containers
            container_count = Container.query.filter_by(client_id=client.id).count()
            
        if (container_count > 0):  # Only include clients with containers
            clients_with_containers.append({
                'id': client.id,
                'name': client.name,
                'contact_person': client.contact_person,
                'container_count': container_count
            })
    
    # Sort clients by container count (descending)
    clients_with_containers.sort(key=lambda x: x['container_count'], reverse=True)
    
    # Take top 10 clients
    top_clients = clients_with_containers[:10]
    
    # ========= LOADING PORT STATISTICS =========
    
    # Aggregate containers by loading port (with date filter)
    loading_port_stats = []
    loading_port_counts = {}
    
    # Use date filter for container query
    container_query = Container.query
    if start_date and end_date:
        container_query = container_query.filter(
            Container.created_at >= start_date,
            Container.created_at <= end_date
        )
    
    for container in container_query.all():
        if container.loading_port:
            port_name = container.loading_port
            if port_name in loading_port_counts:
                loading_port_counts[port_name] += 1
            else:
                loading_port_counts[port_name] = 1
    
    # Calculate total containers with loading port info
    total_with_loading_port = sum(loading_port_counts.values())
    
    # Format data for template
    for port_name, count in loading_port_counts.items():
        percentage = (count / total_with_loading_port * 100) if total_with_loading_port > 0 else 0
        loading_port_stats.append({
            'name': port_name,
            'count': count,
            'percentage': percentage,
            'total': total_with_loading_port
        })
    
    # Sort by count (descending)
    loading_port_stats.sort(key=lambda x: x['count'], reverse=True)
    
    # ========= VESSEL OPERATIONS STATISTICS WITH DATE FILTER =========
    
    # Prepare vessel operation statistics
    vessel_stats = []
    active_vessels = Vessel.query.all()
    
    for vessel in active_vessels:
        # Get all load movements for this vessel with date filter
        load_movements_query = ContainerMovement.query.filter_by(
            vessel_id=vessel.id,
            operation_type='load'
        )
        
        if start_date and end_date:
            load_movements_query = load_movements_query.filter(
                ContainerMovement.operation_date >= start_date,
                ContainerMovement.operation_date <= end_date
            )
            
        load_movements = load_movements_query.all()
        
        # Get all discharge movements for this vessel with date filter
        discharge_movements_query = ContainerMovement.query.filter_by(
            vessel_id=vessel.id,
            operation_type='discharge'
        )
        
        if start_date and end_date:
            discharge_movements_query = discharge_movements_query.filter(
                ContainerMovement.operation_date >= start_date,
                ContainerMovement.operation_date <= end_date
            )
            
        discharge_movements = discharge_movements_query.all()
        
        # Count unique container IDs for load operations
        loaded_container_ids = set(movement.container_id for movement in load_movements)
        total_loaded = len(loaded_container_ids)
        
        # Count unique container IDs for discharge operations
        discharged_container_ids = set(movement.container_id for movement in discharge_movements)
        discharged = len(discharged_container_ids)
        
        # Calculate remaining containers (still on vessel)
        remaining = vessel.get_loaded_containers()
        remaining_count = len(remaining)
        
        # Get loading ports distribution
        loading_ports = {}
        for movement in load_movements:
            port = movement.location
            if port in loading_ports:
                loading_ports[port] += 1
            else:
                loading_ports[port] = 1
        
        # Only add vessels with activity
        if total_loaded > 0 or discharged > 0:
            vessel_stats.append({
                'id': vessel.id,
                'name': vessel.name,
                'voyage': vessel.imo_number,
                'total_loaded': total_loaded,
                'discharged': discharged,
                'remaining': remaining_count,
                'loading_ports': loading_ports
            })
    
    # Sort vessels by total loaded (descending)
    vessel_stats.sort(key=lambda x: x['total_loaded'], reverse=True)
    
    # ========= MORONI IMPORT/EXPORT STATISTICS =========
    
    # Calculate TEU values based on container type
    def calculate_teu(container_type):
        if container_type.startswith('20'):
            return 1.0
        elif container_type.startswith('40') or container_type.startswith('45'):
            return 2.0
        elif container_type.startswith('22'):
            return 1.1  # 22' containers are sometimes counted as 1.1 TEU
        else:
            return 1.0  # Default to 1 TEU for unknown types
    
    # Get all container movements for Moroni
    moroni_movements_query = ContainerMovement.query.filter(
        db.or_(
            ContainerMovement.location == 'Moroni',
            ContainerMovement.location.ilike('%moroni%')
        )
    )
    
    if start_date and end_date:
        moroni_movements_query = moroni_movements_query.filter(
            ContainerMovement.operation_date >= start_date,
            ContainerMovement.operation_date <= end_date
        )
    
    moroni_movements = moroni_movements_query.all()
    
    # Group by container type and operation (import/export)
    container_types = {}  # Will store stats by container type
    
    for movement in moroni_movements:
        # Get the container associated with this movement
        container = Container.query.get(movement.container_id)
        if not container:
            continue
            
        container_type = container.container_type
        
        # Initialize counter for this container type if not exists
        if container_type not in container_types:
            container_types[container_type] = {
                'type': container_type,
                'imported': 0,
                'exported': 0,
                'teu_imported': 0,
                'teu_exported': 0
            }
        
        # Count imports (discharge operations) and exports (load operations)
        teu = calculate_teu(container_type)
        
        if movement.operation_type == 'discharge':
            # Discharged at Moroni = imported
            container_types[container_type]['imported'] += 1
            container_types[container_type]['teu_imported'] += teu
        elif movement.operation_type == 'load':
            # Loaded at Moroni = exported
            container_types[container_type]['exported'] += 1
            container_types[container_type]['teu_exported'] += teu
    
    # Calculate balance for each container type
    moroni_stats = {'types': [], 'total_imported': 0, 'total_exported': 0, 
                   'total_teu_imported': 0, 'total_teu_exported': 0}
    
    for container_type, stats in container_types.items():
        # Calculate balance (imported - exported)
        stats['balance'] = stats['imported'] - stats['exported']
        
        # Add to totals
        moroni_stats['total_imported'] += stats['imported']
        moroni_stats['total_exported'] += stats['exported']
        moroni_stats['total_teu_imported'] += stats['teu_imported']
        moroni_stats['total_teu_exported'] += stats['teu_exported']
        
        # Add to types list
        moroni_stats['types'].append(stats)
    
    # Calculate overall balance
    moroni_stats['total_balance'] = moroni_stats['total_imported'] - moroni_stats['total_exported']
    
    # Sort container types by total volume (imported + exported)
    moroni_stats['types'].sort(key=lambda x: x['imported'] + x['exported'], reverse=True)
    
    return render_template('admin/reports.html',
                          total_container_count=total_container_count,
                          status_counts=status_counts,
                          client_count=client_count,
                          top_clients=top_clients,
                          vessel_stats=vessel_stats,
                          loading_port_stats=loading_port_stats,
                          moroni_stats=moroni_stats,
                          today=today,
                          timedelta=timedelta)

# Add API endpoints to feed chart data
@app.route('/api/reports/container-status')
@login_required
def container_status_data():
    """API endpoint to get container status distribution data"""
    if not current_user.is_admin:
        return jsonify({'error': 'Unauthorized'}), 403
    
    # Get latest status subquery
    latest_status_subquery = db.session.query(
        ContainerStatus.container_id,
        db.func.max(ContainerStatus.created_at).label('max_date')
    ).group_by(ContainerStatus.container_id).subquery('latest_status')
    
    # Get container counts by status
    status_data = db.session.query(
        ContainerStatus.status,
        db.func.count(Container.id)
    ).join(latest_status_subquery, ContainerStatus.container_id == latest_status_subquery.c.container_id)\
     .filter(ContainerStatus.created_at == latest_status_subquery.c.max_date)\
     .join(Container, Container.id == ContainerStatus.container_id)\
     .group_by(ContainerStatus.status)\
     .all()
    
    # Define a mapping of status to color to ensure consistency
    status_colors = {
        'loaded': '#28a745',    # green for loaded
        'discharged': '#ffc107', # yellow for discharged
        'emptied': '#17a2b8',    # blue for emptied
        'full': '#7952B3',       # purple for full
        'in_transit': '#fd7e14',  # orange for in_transit
        'customs_hold': '#dc3545', # red for customs_hold
        'ready_for_pickup': '#20c997' # teal for ready_for_pickup
    }
    
    # Default color for any status not in our mapping
    default_color = '#6c757d'  # gray for other statuses
    
    # Prepare the data with matching colors for each status
    labels = [status for status, _ in status_data]
    data_values = [count for _, count in status_data]
    colors = [status_colors.get(status.lower(), default_color) for status, _ in status_data]
    
    data = {
        'labels': labels,
        'data': data_values,
        'backgroundColor': colors
    }
    
    return jsonify(data)

@app.route('/api/reports/container-movements')
@login_required
def container_movement_data():
    """API endpoint to get container movement data over time"""
    if not current_user.is_admin:
        return jsonify({'error': 'Unauthorized'}), 403
    
    days = int(request.args.get('days', 30))
    
    # Get movement data for the last X days
    start_date = datetime.now() - timedelta(days=days)
    
    # Get data grouped by date and operation type
    movement_data = db.session.query(
        db.func.date(ContainerMovement.operation_date),
        ContainerMovement.operation_type,
        db.func.count()
    ).filter(ContainerMovement.operation_date >= start_date)\
     .group_by(db.func.date(ContainerMovement.operation_date), ContainerMovement.operation_type)\
     .order_by(db.func.date(ContainerMovement.operation_date))\
     .all()
    
    # Process the data for Chart.js
    dates = sorted(list(set(date for date, _, _ in movement_data)))
    
    # Prepare data structure
    chart_data = {
        'labels': [date.strftime('%Y-%m-%d') for date in dates],
        'datasets': [
            {
                'label': 'Load',
                'data': [],
                'backgroundColor': 'rgba(40, 167, 69, 0.6)',  # green
                'borderColor': '#28a745',
                'borderWidth': 1
            },
            {
                'label': 'Discharge',
                'data': [],
                'backgroundColor': 'rgba(255, 193, 7, 0.6)',  # yellow
                'borderColor': '#ffc107',
                'borderWidth': 1
            }
        ]
    }
    
    # Fill in the data arrays
    for date in dates:
        # Find load count for this date
        load_record = next((rec for rec in movement_data if rec[0] == date and rec[1] == 'load'), None)
        load_count = load_record[2] if load_record else 0
        chart_data['datasets'][0]['data'].append(load_count)
        
        # Find discharge count for this date
        discharge_record = next((rec for rec in movement_data if rec[0] == date and rec[1] == 'discharge'), None)
        discharge_count = discharge_record[2] if discharge_record else 0
        chart_data['datasets'][1]['data'].append(discharge_count)
    
    return jsonify(chart_data)

@app.route('/download/client-template')
@login_required
def download_client_template():
    """Generate and download a CSV template for client import"""
    # Create a CSV in memory
    from io import StringIO
    import csv
    
    output = StringIO()
    writer = csv.writer(output)
    
    # Write the header row
    writer.writerow(['Name', 'Phone', 'Email', 'Address', 'Contact Person', 'Notes'])
    
    # Add a few sample rows
    writer.writerow(['ABC Shipping', '+123456789', 'contact@abcshipping.com', '123 Main St, City', 'John Doe', 'Major client'])
    writer.writerow(['XYZ Logistics', '+987654321', 'info@xyzlogistics.com', '456 Port Ave, Harbor', 'Jane Smith', 'New client'])
    writer.writerow(['', '', '', '', '', ''])
    
    # Reset the pointer to the beginning of the StringIO object
    output.seek(0)
    
    # Create a Flask response with CSV file
    response = make_response(output.getvalue())
    response.headers['Content-Disposition'] = 'attachment; filename=client_template.csv'
    response.headers['Content-Type'] = 'text/csv'
    return response

@app.route('/download/container-template')
@login_required
def download_container_template():
    """Generate and download a CSV template for bulk container upload"""
    # Create a CSV in memory
    output = StringIO()
    writer = csv.writer(output)
    
    # Write the header row with CLIENT prominently displayed
    writer.writerow(['Container Number', 'Size/Type', 'P/Loading', 'Vessel', 'Final Dest', 'OPR', 
                    'Status', 'Arrival Date', 'Stripping date', 'Days', 'BL NUMBER', 'CLIENT', 'Notes'])
    
    # Add multiple sample rows with different client examples
    writer.writerow(['ABCD1234567', '20GP', 'Shanghai', 'MSC Bonita V123', 'Moroni', 'MSC', 
                    'discharged', '2023-06-15', '2023-06-20', '5', 'BL123456', 'ABC Shipping Ltd', 'Fragile cargo'])
    writer.writerow(['WXYZ9876543', '40HC', 'Rotterdam', 'CMA CGM V456', 'Mutsamudu', 'CMA', 
                    'loaded', '2023-06-22', '', '', 'BL789012', 'XYZ Logistics', 'Refrigerated'])
    writer.writerow(['PQRS5432109', '20RF', 'Dubai', 'Maersk Line V789', 'Moroni', 'MAERSK', 
                    'full', '2023-06-25', '2023-07-01', '6', 'BL345678', 'Global Imports Inc', 'Priority'])
    
    # Reset the pointer to the beginning of the StringIO object
    output.seek(0)
    
    # Create a Flask response with CSV file
    response = make_response(output.getvalue())
    response.headers['Content-Disposition'] = 'attachment; filename=container_template.csv'
    response.headers['Content-Type'] = 'text/csv'
    return response

# Add client routes below existing routes but before the main app.run() line

@app.route('/clients')
@login_required
def clients():
    """Display list of all clients"""
    # Get sorting parameters from the request
    sort_by = request.args.get('sort', 'name')  # Default sort by name
    sort_order = request.args.get('order', 'asc')    # Default to ascending order for names
    
    # Get search parameter
    search_term = request.args.get('search', '').strip()
    
    # Get page parameter with default value of 1
    page = request.args.get('page', 1, type=int)
    per_page = 20  # Show 20 clients per page
    
    # Base query
    clients_query = Client.query
    
    # Apply search if provided
    if search_term:
        clients_query = clients_query.filter(
            db.or_(
                Client.name.ilike(f'%{search_term}%'),
                Client.contact_person.ilike(f'%{search_term}%'),
                Client.email.ilike(f'%{search_term}%')
            )
        )
    
    # Apply sorting
    if sort_by == 'name':
        if sort_order == 'desc':
            clients_query = clients_query.order_by(Client.name.desc())
        else:
            clients_query = clients_query.order_by(Client.name)
    elif sort_by == 'containers':
        # More complex sorting by container count
        # SQLAlchemy doesn't directly support this kind of sorting
        # Instead, get all clients and sort in Python
        all_clients = clients_query.all()
        for client in all_clients:
            client.container_count = client.get_container_count()
        
        all_clients.sort(key=lambda c: c.container_count, 
                        reverse=(sort_order == 'desc'))
        
        # Create pagination manually
        from pagination import Pagination
        total_count = len(all_clients)
        start = (page - 1) * per_page
        end = min(start + per_page, total_count)
        
        client_list = all_clients[start:end]
        # Fix: Update pagination initialization to match expected parameters
        pagination = Pagination(client_list, page, per_page, 'clients', 
                               sort=sort_by, order=sort_order, search=search_term)
        
        return render_template('clients.html',
                            clients=client_list,
                            pagination=pagination,
                            sort_by=sort_by,
                            sort_order=sort_order)
    elif sort_by == 'created_at':
        if sort_order == 'desc':
            clients_query = clients_query.order_by(Client.created_at.desc())
        else:
            clients_query = clients_query.order_by(Client.created_at)
    else:  # Default fallback
        clients_query = clients_query.order_by(Client.name)
    
    # Create pagination
    from pagination import Pagination
    count = clients_query.count()
    clients = clients_query.offset((page - 1) * per_page).limit(per_page).all()
    # Fix: Update pagination initialization to match expected parameters
    pagination = Pagination(clients, page, per_page, 'clients', 
                           sort=sort_by, order=sort_order, search=search_term)
    
    return render_template('clients.html',
                        clients=clients,
                        pagination=pagination,
                        sort_by=sort_by,
                        sort_order=sort_order)

@app.route('/clients/add', methods=['GET', 'POST'])
@login_required
def add_client():
    """Add a new client"""
    if request.method == 'POST':
        # Extract client data from form
        name = request.form['name'].strip()
        phone = request.form.get('phone', '').strip()
        email = request.form.get('email', '').strip()
        address = request.form.get('address', '').strip()
        contact_person = request.form.get('contact_person', '').strip()
        notes = request.form.get('notes', '').strip()
        
        # Validate required fields
        if not name:
            flash('Client name is required', 'danger')
            return redirect(url_for('add_client'))
        
        # Check if client with same name already exists
        existing_client = Client.query.filter(Client.name.ilike(name)).first()
        if existing_client:
            flash(f'A client with the name "{name}" already exists', 'danger')
            return redirect(url_for('add_client'))
        
        # Create new client
        client = Client(
            name=name,
            phone=phone,
            email=email,
            address=address,
            contact_person=contact_person,
            notes=notes,
            created_at=datetime.utcnow()
        )
        
        db.session.add(client)
        db.session.commit()
        flash(f'Client "{name}" added successfully', 'success')
        return redirect(url_for('clients'))
        
    return render_template('add_client.html')

@app.route('/clients/<int:id>')
@login_required
def client_detail(id):
    """Show client details and associated containers"""
    client = Client.query.get_or_404(id)
    
    # Get containers associated with this client
    containers = Container.query.filter_by(client_id=id).all()
    
    return render_template('client_detail.html',
                         client=client,
                         containers=containers)

@app.route('/clients/<int:id>/edit', methods=['GET', 'POST'])
@login_required
def edit_client(id):
    """Edit client details"""
    client = Client.query.get_or_404(id)
    
    if request.method == 'POST':
        client.name = request.form['name'].strip()
        client.phone = request.form.get('phone', '').strip()
        client.email = request.form.get('email', '').strip()
        client.address = request.form.get('address', '').strip()
        client.contact_person = request.form.get('contact_person', '').strip()
        client.notes = request.form.get('notes', '').strip()
        
        db.session.commit()
        flash(f'Client "{client.name}" updated successfully', 'success')
        return redirect(url_for('client_detail', id=client.id))
    
    return render_template('edit_client.html', client=client)

@app.route('/clients/<int:id>/delete', methods=['POST'])
@login_required
def delete_client(id):
    """Delete a client"""
    client = Client.query.get_or_404(id)
    name = client.name
    
    # Check if client has associated containers
    container_count = Container.query.filter_by(client_id=id).count()
    if container_count > 0:
        flash(f'Cannot delete client "{name}" because it has {container_count} associated containers', 'danger')
        return redirect(url_for('client_detail', id=id))
    
    try:
        db.session.delete(client)
        db.session.commit()
        flash(f'Client "{name}" deleted successfully', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting client: {str(e)}', 'danger')
        
    return redirect(url_for('clients'))

# ...existing code...

@app.route('/api/container-check/<container_number>')
def check_container_details(container_number):
    """Check if a container exists and return its BL number for validation"""
    container = Container.query.filter_by(container_number=container_number).first()
    if container:
        return jsonify({
            'exists': True,
            'container_id': container.id,
            'bl_number': container.bl_number,
            'container_type': container.container_type
        })
    return jsonify({'exists': False})

@app.route('/api/container/<int:id>/location')
@login_required
def get_container_location(id):
    """Get the current location of a container"""
    container = Container.query.get_or_404(id)
    current_status = container.get_current_status()
    
    if (current_status and current_status.location):
        return jsonify({
            'success': True,
            'location': current_status.location
        })
    else:
        return jsonify({
            'success': False,
            'error': 'No location found for this container'
        })

if __name__ == '__main__':
    with app.app_context():
        db.create_all()  # This will create any missing tables including User
    app.run(debug=True)