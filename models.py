from datetime import datetime
from flask_login import UserMixin
# Import the db object directly from extensions.py
from extensions import db

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), index=True, unique=True)
    email = db.Column(db.String(120), index=True, unique=True)
    password_hash = db.Column(db.String(128))
    is_admin = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f'<User {self.username}>'
    
    def set_password(self, password):
        from werkzeug.security import generate_password_hash
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        from werkzeug.security import check_password_hash
        return check_password_hash(self.password_hash, password)

class Container(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    container_number = db.Column(db.String(20), unique=True, nullable=False)
    container_type = db.Column(db.String(20), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # New fields
    loading_port = db.Column(db.String(100))
    final_destination = db.Column(db.String(100))
    opr = db.Column(db.String(50))
    arrival_date = db.Column(db.DateTime)
    bl_number = db.Column(db.String(50))
    stripping_date = db.Column(db.DateTime)  # Added field for stripping date
    
    # Relationships
    statuses = db.relationship('ContainerStatus', backref='container', lazy=True, cascade="all, delete-orphan")
    movements = db.relationship('ContainerMovement', backref='container', lazy=True, cascade="all, delete-orphan")
    
    def __repr__(self):
        return f"Container('{self.container_number}', '{self.container_type}')"
    
    def get_current_status(self):
        """Get the most recent status for this container"""
        from sqlalchemy import desc
        # Use created_at instead of date for sorting
        return ContainerStatus.query.filter_by(container_id=self.id).order_by(desc(ContainerStatus.created_at)).first()

    def get_current_location(self):
        """Get the current location of the container (vessel or port)"""
        current_status = self.get_current_status()
        if not current_status:
            return None
        
        # Check if container is on a vessel - use created_at instead of operation_date
        from sqlalchemy import desc
        latest_movement = ContainerMovement.query.filter_by(
            container_id=self.id
        ).order_by(desc(ContainerMovement.created_at)).first()
        
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
        if current_location and current_location['type'] == 'vessel':
            return current_location['vessel']
        return None
        
    def get_last_vessel(self):
        """Get the most recent vessel this container was on (for discharged containers)"""
        # Find the most recent discharge movement
        from sqlalchemy import desc
        latest_discharge = ContainerMovement.query.filter_by(
            container_id=self.id,
            operation_type='discharge'
        ).order_by(desc(ContainerMovement.created_at)).first()
        
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
        from sqlalchemy import desc
        print_history = PrintHistory.query.filter_by(container_id=self.id).order_by(desc(PrintHistory.print_date)).all()
        
        # If no print history, first print is allowed
        if not print_history:
            return True
        
        # If there was a discharge event after the last print, allow printing
        last_print_date = print_history[0].print_date if print_history else None
        
        if last_print_date:
            # Check if the container was loaded and then discharged after the last print
            from sqlalchemy import and_
            load_after_print = ContainerMovement.query.filter(
                and_(
                    ContainerMovement.container_id == self.id,
                    ContainerMovement.operation_type == 'load',
                    ContainerMovement.created_at > last_print_date
                )
            ).first()
            
            discharge_after_load = False
            if load_after_print:
                discharge_after_load = ContainerMovement.query.filter(
                    and_(
                        ContainerMovement.container_id == self.id,
                        ContainerMovement.operation_type == 'discharge',
                        ContainerMovement.created_at > load_after_print.created_at
                    )
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
        from sqlalchemy import desc
        movements = ContainerMovement.query.filter_by(vessel_id=self.id).order_by(
            ContainerMovement.container_id, desc(ContainerMovement.created_at)
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

class PrintAccessRequest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    container_id = db.Column(db.Integer, db.ForeignKey('container.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    requested_at = db.Column(db.DateTime, default=datetime.utcnow)
    status = db.Column(db.String(20), default='pending')  # pending, approved, rejected
    
    # Relationships
    container = db.relationship('Container', backref=db.backref('print_requests', lazy=True))
    user = db.relationship('User', backref=db.backref('print_requests', lazy=True))

class DeliveryCounter(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    counter = db.Column(db.Integer, default=1)
    last_updated = db.Column(db.DateTime, default=datetime.utcnow)

# Class that was causing circular import
class DeliveryPrint(db.Model):
    """Model for tracking delivery order prints"""
    __tablename__ = 'delivery_prints'
    
    id = db.Column(db.Integer, primary_key=True)
    container_id = db.Column(db.Integer, db.ForeignKey('container.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    authorized_by_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    print_date = db.Column(db.DateTime, default=datetime.utcnow)
    do_number = db.Column(db.String(20), nullable=True)  # Delivery Order number
    
    # Relationships
    container = db.relationship('Container', backref=db.backref('delivery_prints', lazy=True))
    user = db.relationship('User', foreign_keys=[user_id])
    authorized_by = db.relationship('User', foreign_keys=[authorized_by_id])
    
    def __repr__(self):
        return f'<DeliveryPrint {self.id}>'
