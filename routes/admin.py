from flask import Blueprint, render_template, redirect, url_for, flash, request, abort
from flask_login import login_required, current_user
from werkzeug.security import generate_password_hash
from sqlalchemy.exc import IntegrityError
from functools import wraps
import os
import csv

from app import db
from models import User, Role, RoleType, Course
from utils import allowed_file, save_file, import_users_from_csv

admin_bp = Blueprint('admin', __name__)

# Admin required decorator
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin():
            abort(403)
        return f(*args, **kwargs)
    return decorated_function

@admin_bp.route('/dashboard')
@login_required
@admin_required
def dashboard():
    """Admin dashboard page."""
    # Get counts for the dashboard
    total_users = User.query.count()
    total_students = User.query.join(Role).filter(Role.name == RoleType.STUDENT).count()
    total_faculty = User.query.join(Role).filter(Role.name == RoleType.FACULTY).count()
    total_courses = Course.query.count()
    
    # Get recent users
    recent_users = User.query.order_by(User.created_at.desc()).limit(5).all()
    
    # Get active courses
    active_courses = Course.query.filter_by(is_active=True).order_by(Course.start_date.desc()).limit(5).all()
    
    return render_template('admin/dashboard.html', 
                           total_users=total_users,
                           total_students=total_students,
                           total_faculty=total_faculty,
                           total_courses=total_courses,
                           recent_users=recent_users,
                           active_courses=active_courses)

@admin_bp.route('/users')
@login_required
@admin_required
def users():
    """List all users."""
    page = request.args.get('page', 1, type=int)
    per_page = 10
    
    # Filter by role if specified
    role_filter = request.args.get('role')
    if role_filter and role_filter.upper() in [r.name.name for r in Role.query.all()]:
        users = User.query.join(Role).filter(Role.name == RoleType[role_filter.upper()])
    else:
        users = User.query
    
    # Search by name or email if specified
    search = request.args.get('search', '')
    if search:
        users = users.filter((User.username.ilike(f'%{search}%')) | 
                            (User.email.ilike(f'%{search}%')) |
                            (User.first_name.ilike(f'%{search}%')) |
                            (User.last_name.ilike(f'%{search}%')))
    
    # Paginate results
    users = users.order_by(User.created_at.desc()).paginate(page=page, per_page=per_page)
    
    # Get roles for the dropdown
    roles = Role.query.all()
    
    return render_template('admin/users.html', users=users, roles=roles, search=search, role_filter=role_filter)

@admin_bp.route('/users/new', methods=['GET', 'POST'])
@login_required
@admin_required
def new_user():
    """Create a new user."""
    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        password = request.form.get('password')
        first_name = request.form.get('first_name')
        last_name = request.form.get('last_name')
        role_id = request.form.get('role_id')
        is_active = True if request.form.get('is_active') else False
        
        # Basic validation
        if not username or not email or not password or not first_name or not last_name or not role_id:
            flash('All fields are required.', 'danger')
            return redirect(url_for('admin.new_user'))
            
        # Check if username or email already exists
        if User.query.filter_by(username=username).first():
            flash('Username already exists.', 'danger')
            return redirect(url_for('admin.new_user'))
            
        if User.query.filter_by(email=email).first():
            flash('Email already exists.', 'danger')
            return redirect(url_for('admin.new_user'))
        
        # Create the user
        new_user = User(
            username=username,
            email=email,
            password_hash=generate_password_hash(password),
            first_name=first_name,
            last_name=last_name,
            role_id=role_id,
            is_active=is_active
        )
        
        try:
            db.session.add(new_user)
            db.session.commit()
            flash(f'User {username} created successfully.', 'success')
            return redirect(url_for('admin.users'))
        except IntegrityError:
            db.session.rollback()
            flash('An error occurred while creating the user.', 'danger')
    
    # Get roles for the form
    roles = Role.query.all()
    
    return render_template('admin/new_user.html', roles=roles)

@admin_bp.route('/users/<int:user_id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_user(user_id):
    """Edit a user."""
    user = User.query.get_or_404(user_id)
    
    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        password = request.form.get('password')
        first_name = request.form.get('first_name')
        last_name = request.form.get('last_name')
        role_id = request.form.get('role_id')
        is_active = True if request.form.get('is_active') else False
        
        # Basic validation
        if not username or not email or not first_name or not last_name or not role_id:
            flash('All fields except password are required.', 'danger')
            return redirect(url_for('admin.edit_user', user_id=user_id))
            
        # Check if username or email already exists (excluding current user)
        username_exists = User.query.filter(User.username == username, User.id != user_id).first()
        if username_exists:
            flash('Username already exists.', 'danger')
            return redirect(url_for('admin.edit_user', user_id=user_id))
            
        email_exists = User.query.filter(User.email == email, User.id != user_id).first()
        if email_exists:
            flash('Email already exists.', 'danger')
            return redirect(url_for('admin.edit_user', user_id=user_id))
        
        # Update the user
        user.username = username
        user.email = email
        user.first_name = first_name
        user.last_name = last_name
        user.role_id = role_id
        user.is_active = is_active
        
        # Only update password if provided
        if password:
            user.password_hash = generate_password_hash(password)
        
        try:
            db.session.commit()
            flash(f'User {username} updated successfully.', 'success')
            return redirect(url_for('admin.users'))
        except IntegrityError:
            db.session.rollback()
            flash('An error occurred while updating the user.', 'danger')
    
    # Get roles for the form
    roles = Role.query.all()
    
    return render_template('admin/edit_user.html', user=user, roles=roles)

@admin_bp.route('/users/<int:user_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_user(user_id):
    """Delete a user."""
    user = User.query.get_or_404(user_id)
    
    # Prevent deleting own account
    if user.id == current_user.id:
        flash('You cannot delete your own account.', 'danger')
        return redirect(url_for('admin.users'))
    
    username = user.username
    
    try:
        db.session.delete(user)
        db.session.commit()
        flash(f'User {username} deleted successfully.', 'success')
    except:
        db.session.rollback()
        flash(f'An error occurred while deleting user {username}.', 'danger')
    
    return redirect(url_for('admin.users'))

@admin_bp.route('/users/import', methods=['GET', 'POST'])
@login_required
@admin_required
def import_users():
    """Import users from CSV file."""
    if request.method == 'POST':
        role_type = request.form.get('role_type')
        
        # Check if role type is valid
        if not role_type or role_type not in [r.name.name for r in Role.query.all()]:
            flash('Invalid role type.', 'danger')
            return redirect(url_for('admin.import_users'))
        
        # Check if file was provided
        if 'file' not in request.files:
            flash('No file provided.', 'danger')
            return redirect(url_for('admin.import_users'))
        
        file = request.files['file']
        
        # Check if file is empty
        if file.filename == '':
            flash('No file selected.', 'danger')
            return redirect(url_for('admin.import_users'))
        
        # Check if file is a CSV
        if not file.filename.endswith('.csv'):
            flash('File must be a CSV.', 'danger')
            return redirect(url_for('admin.import_users'))
        
        # Save the file temporarily
        file_path = save_file(file, 'temp')
        
        # Import the users
        try:
            count = import_users_from_csv(file_path, RoleType[role_type])
            flash(f'Successfully imported {count} users.', 'success')
            
            # Delete the temporary file
            os.remove(file_path)
            
            return redirect(url_for('admin.users'))
        except Exception as e:
            flash(f'Error importing users: {str(e)}', 'danger')
            
            # Delete the temporary file
            if os.path.exists(file_path):
                os.remove(file_path)
    
    # Get roles for the form
    roles = Role.query.all()
    
    return render_template('admin/import_users.html', roles=roles)

@admin_bp.route('/courses')
@login_required
@admin_required
def courses():
    """Manage courses."""
    page = request.args.get('page', 1, type=int)
    per_page = 10
    
    # Filter by active status if specified
    active_filter = request.args.get('active')
    if active_filter:
        is_active = active_filter == 'true'
        courses = Course.query.filter_by(is_active=is_active)
    else:
        courses = Course.query
    
    # Search by code or title if specified
    search = request.args.get('search', '')
    if search:
        courses = courses.filter((Course.code.ilike(f'%{search}%')) | 
                                (Course.title.ilike(f'%{search}%')))
    
    # Paginate results
    courses = courses.order_by(Course.created_at.desc()).paginate(page=page, per_page=per_page)
    
    return render_template('admin/courses.html', courses=courses, search=search, active_filter=active_filter)

@admin_bp.route('/system')
@login_required
@admin_required
def system():
    """System information and settings."""
    return render_template('admin/system.html')