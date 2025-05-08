from extensions import db
from flask_login import UserMixin
from datetime import datetime

class User(db.Model, UserMixin):
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.now)
    
    @property
    def password(self):
        raise AttributeError('password is not a readable attribute')
        
    @password.setter
    def password(self, password):
        from extensions import bcrypt
        self.password_hash = bcrypt.generate_password_hash(password).decode('utf-8')
    
    def __repr__(self):
        return f'<User {self.username}>'

class Container(db.Model):
    __tablename__ = 'containers'
    
    id = db.Column(db.Integer, primary_key=True)
    container_number = db.Column(db.String(20), unique=True, nullable=False)
    container_type = db.Column(db.String(10), nullable=False)
    loading_port = db.Column(db.String(100))
    final_destination = db.Column(db.String(100))
    opr = db.Column(db.String(100))
    bl_number = db.Column(db.String(50))
    arrival_date = db.Column(db.Date)
    stripping_date = db.Column(db.Date)
    created_at = db.Column(db.DateTime, default=datetime.now)
    
    # Relationships
    statuses = db.relationship('ContainerStatus', backref='container', lazy=True)
    movements = db.relationship('ContainerMovement', backref='container', lazy=True)
    
    def get_current_status(self):
        # Get the most recent status
        return ContainerStatus.query.filter_by(container_id=self.id).order_by(ContainerStatus.date.desc()).first()
    
    def get_current_location(self):
        # Get the most recent location, whether it's on a vessel or at a terminal
        latest_movement = ContainerMovement.query.filter_by(
            container_id=self.id,
            operation_type='load'
        ).order_by(ContainerMovement.operation_date.desc()).first()
        
        if latest_movement:
            latest_discharge = ContainerMovement.query.filter_by(
                container_id=self.id,
                operation_type='discharge',
                vessel_id=latest_movement.vessel_id
            ).order_by(ContainerMovement.operation_date.desc()).first()
            
            if not latest_discharge:
                # Container is still on vessel
                return {
                    'type': 'vessel',
                    'vessel': latest_movement.vessel,
                    'since': latest_movement.operation_date
                }
        
        # If not on a vessel, get the latest status location
        latest_status = self.get_current_status()
        if latest_status:
            return {
                'type': 'terminal',
                'location': latest_status.location,
                'since': latest_status.date
            }
            
        return None
    
    def can_print_delivery_order(self, user_id):
        # Logic to check if a user can print a delivery order for this container
        from models import DeliveryPrint, PrintAuthorization
        
        # Check if there's no previous print - first prints are always allowed
        existing_prints = DeliveryPrint.query.filter_by(container_id=self.id).all()
        if not existing_prints:
            return True
            
        # Check for active authorization
        auth = PrintAuthorization.query.filter_by(
            container_id=self.id,
            user_id=user_id,
            used=False
        ).first()
        
        return auth is not None

class ContainerStatus(db.Model):
    __tablename__ = 'container_statuses'
    
    id = db.Column(db.Integer, primary_key=True)
    container_id = db.Column(db.Integer, db.ForeignKey('containers.id'), nullable=False)
    status = db.Column(db.String(50), nullable=False)
    location = db.Column(db.String(100))
    date = db.Column(db.Date, nullable=False)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.now)

class Vessel(db.Model):
    __tablename__ = 'vessels'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    imo_number = db.Column(db.String(50), nullable=False)
    vessel_type = db.Column(db.String(50))
    capacity_teu = db.Column(db.Integer)
    current_location = db.Column(db.String(100))
    status = db.Column(db.String(50), default='Active')
    created_at = db.Column(db.DateTime, default=datetime.now)
    
    # Relationships
    movements = db.relationship('ContainerMovement', backref='vessel', lazy=True)

class ContainerMovement(db.Model):
    __tablename__ = 'container_movements'
    
    id = db.Column(db.Integer, primary_key=True)
    container_id = db.Column(db.Integer, db.ForeignKey('containers.id'), nullable=False)
    vessel_id = db.Column(db.Integer, db.ForeignKey('vessels.id'), nullable=False)
    operation_type = db.Column(db.String(20), nullable=False)  # load, discharge, etc.
    operation_date = db.Column(db.Date, nullable=False)
    location = db.Column(db.String(100))
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.now)

class DeliveryPrint(db.Model):
    __tablename__ = 'delivery_prints'
    
    id = db.Column(db.Integer, primary_key=True)
    container_id = db.Column(db.Integer, db.ForeignKey('containers.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    authorized_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    print_date = db.Column(db.DateTime, default=datetime.now)
    do_number = db.Column(db.String(20), nullable=True)  # Delivery Order number
    
    # Relationships
    container = db.relationship('Container', backref=db.backref('prints', lazy=True))
    user = db.relationship('User', foreign_keys=[user_id])
    authorized_by = db.relationship('User', foreign_keys=[authorized_by_id])
    
    def __repr__(self):
        return f'<DeliveryPrint {self.id}>'

class PrintAuthorization(db.Model):
    __tablename__ = 'print_authorizations'
    
    id = db.Column(db.Integer, primary_key=True)
    container_id = db.Column(db.Integer, db.ForeignKey('containers.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    authorized_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.now)
    used = db.Column(db.Boolean, default=False)
    
    # Relationships
    container = db.relationship('Container')
    user = db.relationship('User', foreign_keys=[user_id])
    authorized_by = db.relationship('User', foreign_keys=[authorized_by_id])

class PrintAccessRequest(db.Model):
    __tablename__ = 'print_access_requests'
    
    id = db.Column(db.Integer, primary_key=True)
    container_id = db.Column(db.Integer, db.ForeignKey('containers.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    requested_at = db.Column(db.DateTime, default=datetime.now)
    status = db.Column(db.String(20), default='pending')  # pending, approved, rejected
    
    # Relationships
    container = db.relationship('Container')
    user = db.relationship('User')
