from app import db
from datetime import datetime

class Container(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    container_number = db.Column(db.String(20), unique=True, nullable=False)
    container_type = db.Column(db.String(20), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationship with ContainerStatus
    statuses = db.relationship('ContainerStatus', backref='container', lazy=True, cascade="all, delete-orphan")
    
    def __repr__(self):
        return f"Container('{self.container_number}', '{self.container_type}')"
    
    def get_current_status(self):
        latest_status = ContainerStatus.query.filter_by(container_id=self.id).order_by(ContainerStatus.date.desc()).first()
        return latest_status

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

# This file simply re-exports the models defined in app.py to avoid circular imports
from app import Container, ContainerStatus
