import os
import logging
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import DeclarativeBase
from flask_login import LoginManager

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Create a base class for SQLAlchemy models
class Base(DeclarativeBase):
    pass

# Initialize SQLAlchemy
db = SQLAlchemy(model_class=Base)

# Create Flask application
app = Flask(__name__)

# Load configuration
app.config.from_object('config.Config')

# Set secret key from environment variable with fallback
app.secret_key = os.environ.get("SESSION_SECRET", "dev-secret-key-change-in-production")

# Configure database
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get("DATABASE_URL", "sqlite:///erp_system.db")
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
    "pool_recycle": 300,
    "pool_pre_ping": True,
}
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

# Initialize extensions
db.init_app(app)

# Initialize login manager
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'auth.login'
login_manager.login_message_category = 'info'

# Create database tables
with app.app_context():
    # Import models here to avoid circular imports
    from models import User, Role, Course, Assignment, Submission, Grade, Material, Schedule
    db.create_all()
    logger.debug("Database tables created successfully")
    
    # Create default roles if they don't exist
    from models import create_default_roles, create_admin_user
    create_default_roles()
    create_admin_user()

# Import and register blueprints
from routes.auth import auth_bp
from routes.admin import admin_bp
from routes.faculty import faculty_bp
from routes.student import student_bp
from routes.courses import courses_bp
from routes.assignments import assignments_bp
from routes.analytics import analytics_bp
from routes.schedule import schedule_bp
from routes.materials import materials_bp

app.register_blueprint(auth_bp)
app.register_blueprint(admin_bp, url_prefix='/admin')
app.register_blueprint(faculty_bp, url_prefix='/faculty')
app.register_blueprint(student_bp, url_prefix='/student')
app.register_blueprint(courses_bp, url_prefix='/courses')
app.register_blueprint(assignments_bp, url_prefix='/assignments')
app.register_blueprint(analytics_bp, url_prefix='/analytics')
app.register_blueprint(schedule_bp, url_prefix='/schedule')
app.register_blueprint(materials_bp, url_prefix='/materials')

# User loader for Flask-Login
@login_manager.user_loader
def load_user(user_id):
    from models import User
    return User.query.get(int(user_id))

# Basic error handlers
@app.errorhandler(404)
def page_not_found(e):
    return render_template('404.html'), 404

@app.errorhandler(500)
def internal_server_error(e):
    return render_template('500.html'), 500

# Import at the end to avoid circular imports
from flask import render_template
