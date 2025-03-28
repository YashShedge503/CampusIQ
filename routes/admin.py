from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app
from flask_login import login_required, current_user
from werkzeug.security import generate_password_hash
from sqlalchemy.exc import IntegrityError
from functools import wraps
import os
import csv
from io import TextIOWrapper

from app import db
from models import User, Role, RoleType, Course

admin_bp = Blueprint('admin_bp', __name__)

# Admin required decorator
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin():
            flash('You do not have permission to access this page.', 'danger')
            return redirect(url_for('auth.index'))
        return f(*args, **kwargs)
    return decorated_function

@admin_bp.route('/dashboard')
@login_required
@admin_required
def dashboard():
    """Admin dashboard page."""
    # Get user statistics
    total_users = User.query.count()
    admin_count = User.query.join(Role).filter(Role.name == RoleType.ADMIN).count()
    faculty_count = User.query.join(Role).filter(Role.name == RoleType.FACULTY).count()
    student_count = User.query.join(Role).filter(Role.name == RoleType.STUDENT).count()
    
    # Get course statistics
    total_courses = Course.query.count()
    active_courses = Course.query.filter_by(is_active=True).count()
    
    # Get recent users
    recent_users = User.query.order_by(User.created_at.desc()).limit(5).all()
    
    # Get recent courses
    recent_courses = Course.query.order_by(Course.created_at.desc()).limit(5).all()
    
    return render_template('admin/dashboard.html',
                          total_users=total_users,
                          admin_count=admin_count,
                          faculty_count=faculty_count,
                          student_count=student_count,
                          total_courses=total_courses,
                          active_courses=active_courses,
                          recent_users=recent_users,
                          recent_courses=recent_courses)

@admin_bp.route('/users')
@login_required
@admin_required
def users():
    """List all users."""
    # Get filter parameters
    role_filter = request.args.get('role')
    status_filter = request.args.get('status')
    search_query = request.args.get('q')
    
    # Base query
    query = User.query
    
    # Apply filters
    if role_filter:
        query = query.join(Role).filter(Role.name == role_filter)
        
    if status_filter:
        if status_filter == 'active':
            query = query.filter(User.is_active == True)
        elif status_filter == 'inactive':
            query = query.filter(User.is_active == False)
            
    if search_query:
        query = query.filter(
            (User.username.ilike(f'%{search_query}%')) |
            (User.email.ilike(f'%{search_query}%')) |
            (User.first_name.ilike(f'%{search_query}%')) |
            (User.last_name.ilike(f'%{search_query}%'))
        )
    
    # Get page parameter and paginate
    page = request.args.get('page', 1, type=int)
    per_page = current_app.config.get('ITEMS_PER_PAGE', 10)
    pagination = query.order_by(User.username).paginate(page=page, per_page=per_page, error_out=False)
    users = pagination.items
    
    # Get all roles for filter dropdown
    roles = Role.query.all()
    
    return render_template('admin/users.html',
                          users=users,
                          pagination=pagination,
                          roles=roles,
                          current_role=role_filter,
                          current_status=status_filter,
                          search_query=search_query)

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
        role_id = request.form.get('role_id', type=int)
        is_active = 'is_active' in request.form
        
        # Validate input
        if not username or not email or not password or not first_name or not last_name or not role_id:
            flash('All fields are required.', 'danger')
            return redirect(url_for('admin_bp.new_user'))
        
        # Create new user
        new_user = User(
            username=username,
            email=email,
            first_name=first_name,
            last_name=last_name,
            role_id=role_id,
            is_active=is_active
        )
        new_user.set_password(password)
        
        try:
            db.session.add(new_user)
            db.session.commit()
            flash(f'User {username} created successfully.', 'success')
            return redirect(url_for('admin_bp.users'))
        except IntegrityError:
            db.session.rollback()
            flash('Username or email already exists.', 'danger')
    
    # Get all roles for the form
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
        first_name = request.form.get('first_name')
        last_name = request.form.get('last_name')
        role_id = request.form.get('role_id', type=int)
        is_active = 'is_active' in request.form
        new_password = request.form.get('new_password')
        
        # Validate input
        if not username or not email or not first_name or not last_name or not role_id:
            flash('Username, email, first name, last name, and role are required.', 'danger')
            return redirect(url_for('admin_bp.edit_user', user_id=user_id))
        
        # Check if username changed and if it's already taken
        if username != user.username:
            user_with_username = User.query.filter_by(username=username).first()
            if user_with_username and user_with_username.id != user_id:
                flash('Username already in use.', 'danger')
                return redirect(url_for('admin_bp.edit_user', user_id=user_id))
        
        # Check if email changed and if it's already taken
        if email != user.email:
            user_with_email = User.query.filter_by(email=email).first()
            if user_with_email and user_with_email.id != user_id:
                flash('Email already in use.', 'danger')
                return redirect(url_for('admin_bp.edit_user', user_id=user_id))
        
        # Update user
        user.username = username
        user.email = email
        user.first_name = first_name
        user.last_name = last_name
        user.role_id = role_id
        user.is_active = is_active
        
        # Update password if provided
        if new_password:
            user.set_password(new_password)
        
        try:
            db.session.commit()
            flash(f'User {username} updated successfully.', 'success')
            return redirect(url_for('admin_bp.users'))
        except IntegrityError:
            db.session.rollback()
            flash('An error occurred while updating the user.', 'danger')
    
    # Get all roles for the form
    roles = Role.query.all()
    return render_template('admin/edit_user.html', user=user, roles=roles)

@admin_bp.route('/users/<int:user_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_user(user_id):
    """Delete a user."""
    user = User.query.get_or_404(user_id)
    
    # Prevent deleting yourself
    if user.id == current_user.id:
        flash('You cannot delete your own account.', 'danger')
        return redirect(url_for('admin_bp.users'))
    
    # Get username for flash message
    username = user.username
    
    try:
        db.session.delete(user)
        db.session.commit()
        flash(f'User {username} deleted successfully.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting user: {str(e)}', 'danger')
    
    return redirect(url_for('admin_bp.users'))

@admin_bp.route('/users/import', methods=['GET', 'POST'])
@login_required
@admin_required
def import_users():
    """Import users from CSV file."""
    if request.method == 'POST':
        # Check if file was submitted
        if 'csv_file' not in request.files:
            flash('No file selected.', 'danger')
            return redirect(url_for('admin_bp.import_users'))
            
        file = request.files['csv_file']
        
        # Check if file is empty
        if file.filename == '':
            flash('No file selected.', 'danger')
            return redirect(url_for('admin_bp.import_users'))
        
        # Check file extension
        if not file.filename.endswith('.csv'):
            flash('File must be a CSV.', 'danger')
            return redirect(url_for('admin_bp.import_users'))
        
        # Get role type
        role_type = request.form.get('role_type')
        
        try:
            role_enum = RoleType(role_type)
        except ValueError:
            flash('Invalid role selected.', 'danger')
            return redirect(url_for('admin_bp.import_users'))
        
        # Get role
        role = Role.query.filter_by(name=role_enum).first()
        if not role:
            flash('Role does not exist.', 'danger')
            return redirect(url_for('admin_bp.import_users'))
        
        # Process CSV file
        csv_file = TextIOWrapper(file, encoding='utf-8')
        csv_reader = csv.DictReader(csv_file)
        
        required_fields = ['username', 'email', 'password', 'first_name', 'last_name']
        
        # Check CSV headers
        headers = csv_reader.fieldnames
        if not all(field in headers for field in required_fields):
            flash(f'CSV file must contain the following columns: {", ".join(required_fields)}', 'danger')
            return redirect(url_for('admin_bp.import_users'))
        
        # Import users
        success_count = 0
        error_count = 0
        
        for row in csv_reader:
            # Check if all required fields are present and not empty
            if not all(row.get(field) for field in required_fields):
                error_count += 1
                continue
            
            # Check if user already exists
            if User.query.filter((User.username == row['username']) | (User.email == row['email'])).first():
                error_count += 1
                continue
            
            # Create new user
            new_user = User(
                username=row['username'],
                email=row['email'],
                first_name=row['first_name'],
                last_name=row['last_name'],
                role_id=role.id,
                is_active=True
            )
            new_user.set_password(row['password'])
            
            try:
                db.session.add(new_user)
                db.session.commit()
                success_count += 1
            except:
                db.session.rollback()
                error_count += 1
        
        if success_count > 0:
            flash(f'Successfully imported {success_count} users.', 'success')
        
        if error_count > 0:
            flash(f'Failed to import {error_count} users due to errors or duplicate entries.', 'warning')
        
        return redirect(url_for('admin_bp.users'))
    
    return render_template('admin/import_users.html')

@admin_bp.route('/courses')
@login_required
@admin_required
def courses():
    """Manage courses."""
    # Get filter parameters
    faculty_filter = request.args.get('faculty_id', type=int)
    status_filter = request.args.get('status')
    search_query = request.args.get('q')
    
    # Base query
    query = Course.query
    
    # Apply filters
    if faculty_filter:
        query = query.filter(Course.faculty_id == faculty_filter)
        
    if status_filter:
        if status_filter == 'active':
            query = query.filter(Course.is_active == True)
        elif status_filter == 'inactive':
            query = query.filter(Course.is_active == False)
            
    if search_query:
        query = query.filter(
            (Course.code.ilike(f'%{search_query}%')) |
            (Course.title.ilike(f'%{search_query}%'))
        )
    
    # Get page parameter and paginate
    page = request.args.get('page', 1, type=int)
    per_page = current_app.config.get('ITEMS_PER_PAGE', 10)
    pagination = query.order_by(Course.code).paginate(page=page, per_page=per_page, error_out=False)
    courses = pagination.items
    
    # Get faculty members for filter dropdown
    faculty_role = Role.query.filter_by(name=RoleType.FACULTY).first()
    faculty_members = User.query.filter_by(role_id=faculty_role.id).all() if faculty_role else []
    
    return render_template('admin/courses.html',
                          courses=courses,
                          pagination=pagination,
                          faculty_members=faculty_members,
                          current_faculty=faculty_filter,
                          current_status=status_filter,
                          search_query=search_query)

@admin_bp.route('/system')
@login_required
@admin_required
def system():
    """System information and settings."""
    # Get application configuration
    config = {
        'DEBUG': current_app.config.get('DEBUG', False),
        'TESTING': current_app.config.get('TESTING', False),
        'SQLALCHEMY_DATABASE_URI': current_app.config.get('SQLALCHEMY_DATABASE_URI', 'Not set'),
        'UPLOAD_FOLDER': current_app.config.get('UPLOAD_FOLDER', 'Not set'),
        'MAX_CONTENT_LENGTH': current_app.config.get('MAX_CONTENT_LENGTH', 0),
        'ALLOWED_EXTENSIONS': current_app.config.get('ALLOWED_EXTENSIONS', []),
        'AI_SERVICE_ENABLED': current_app.config.get('AI_SERVICE_ENABLED', False),
    }
    
    # Get database statistics
    db_stats = {
        'users': User.query.count(),
        'roles': Role.query.count(),
        'courses': Course.query.count(),
    }
    
    return render_template('admin/system.html',
                          config=config,
                          db_stats=db_stats)