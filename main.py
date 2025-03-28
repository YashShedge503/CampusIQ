from flask import Flask, render_template
from flask_login import LoginManager, current_user
from werkzeug.exceptions import NotFound, InternalServerError
from werkzeug.middleware.proxy_fix import ProxyFix
from datetime import datetime

from app import app, db
from models import User, Role, RoleType

# Set up LoginManager
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'auth.login'
login_manager.login_message_category = 'info'

@login_manager.user_loader
def load_user(user_id):
    """Load user by ID."""
    return User.query.get(int(user_id))

# Register error handlers
@app.errorhandler(404)
def page_not_found(e):
    """Handler for 404 errors."""
    return render_template('errors/404.html'), 404

@app.errorhandler(500)
def internal_server_error(e):
    """Handler for 500 errors."""
    return render_template('errors/500.html'), 500

# Make current user role and date available in templates
@app.context_processor
def inject_context():
    """Make user role and current date available in templates."""
    context = {'now': datetime.utcnow()}
    
    if current_user.is_authenticated:
        context['user_role'] = current_user.role.name.value
    else:
        context['user_role'] = None
        
    return context

# Apply proxy fix for Replit
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1)

# Import and register blueprints
from routes.auth import auth_bp
app.register_blueprint(auth_bp, url_prefix='')

from routes.admin import admin_bp
app.register_blueprint(admin_bp, url_prefix='/admin')

from routes.student import student_bp
app.register_blueprint(student_bp, url_prefix='/student')

# Initialize the database
with app.app_context():
    # Create default roles and admin user
    from models import create_default_roles, create_admin_user
    create_default_roles()
    create_admin_user()

# Run the application
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)