from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_bcrypt import Bcrypt

# Initialize extensions without binding them to app
db = SQLAlchemy()
login_manager = LoginManager()
login_manager.login_view = 'login'
bcrypt = Bcrypt()
