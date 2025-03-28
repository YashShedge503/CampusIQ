from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import check_password_hash, generate_password_hash
from sqlalchemy.exc import IntegrityError

from app import db
from models import User, Role, RoleType

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/')
def index():
    """Homepage route."""
    return render_template('index.html')

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    """User login route."""
    # Redirect if user is already logged in
    if current_user.is_authenticated:
        return redirect(url_for('auth.index'))
    
    # Handle POST request (form submission)
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        remember = 'remember' in request.form
        
        # Validate input
        if not username or not password:
            flash('Username and password are required.', 'danger')
            return redirect(url_for('auth.login'))
        
        # Check if user exists
        user = User.query.filter_by(username=username).first()
        
        # Validate credentials
        if not user or not user.check_password(password):
            flash('Invalid username or password.', 'danger')
            return redirect(url_for('auth.login'))
        
        # Check if account is active
        if not user.is_active:
            flash('Your account has been disabled. Please contact an administrator.', 'danger')
            return redirect(url_for('auth.login'))
        
        # Log the user in
        login_user(user, remember=remember)
        
        # Redirect to appropriate dashboard based on role
        if user.is_admin():
            return redirect(url_for('admin_bp.dashboard'))
        elif user.is_faculty():
            return redirect(url_for('faculty.dashboard'))
        elif user.is_student():
            return redirect(url_for('student_bp.dashboard'))
        else:
            return redirect(url_for('auth.index'))
    
    # Handle GET request (display login form)
    return render_template('auth/login.html')

@auth_bp.route('/logout')
@login_required
def logout():
    """User logout route."""
    logout_user()
    flash('You have been logged out successfully.', 'success')
    return redirect(url_for('auth.index'))

@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    """User registration route."""
    # Redirect if user is already logged in
    if current_user.is_authenticated:
        return redirect(url_for('auth.index'))
    
    # Get all available roles (except admin)
    roles = Role.query.filter(Role.name != RoleType.ADMIN).all()
    
    # Handle POST request (form submission)
    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')
        first_name = request.form.get('first_name')
        last_name = request.form.get('last_name')
        role_id = request.form.get('role_id', type=int)
        
        # Validate input
        if not username or not email or not password or not confirm_password or not first_name or not last_name or not role_id:
            flash('All fields are required.', 'danger')
            return render_template('auth/register.html', roles=roles)
        
        # Check if passwords match
        if password != confirm_password:
            flash('Passwords do not match.', 'danger')
            return render_template('auth/register.html', roles=roles)
        
        # Check if username or email already exists
        if User.query.filter_by(username=username).first():
            flash('Username already exists.', 'danger')
            return render_template('auth/register.html', roles=roles)
        
        if User.query.filter_by(email=email).first():
            flash('Email already exists.', 'danger')
            return render_template('auth/register.html', roles=roles)
        
        # Get role
        role = Role.query.get(role_id)
        if not role or role.name == RoleType.ADMIN:
            flash('Invalid role selected.', 'danger')
            return render_template('auth/register.html', roles=roles)
        
        # Create user
        new_user = User(
            username=username,
            email=email,
            first_name=first_name,
            last_name=last_name,
            role_id=role_id,
            is_active=True
        )
        new_user.set_password(password)
        
        try:
            db.session.add(new_user)
            db.session.commit()
            flash('Registration successful! You can now log in.', 'success')
            return redirect(url_for('auth.login'))
        except IntegrityError:
            db.session.rollback()
            flash('An error occurred during registration. Please try again.', 'danger')
    
    # Handle GET request (display registration form)
    return render_template('auth/register.html', roles=roles)

@auth_bp.route('/profile')
@login_required
def profile():
    """User profile page."""
    return render_template('auth/profile.html')

@auth_bp.route('/profile/edit', methods=['GET', 'POST'])
@login_required
def edit_profile():
    """Edit user profile."""
    if request.method == 'POST':
        email = request.form.get('email')
        first_name = request.form.get('first_name')
        last_name = request.form.get('last_name')
        current_password = request.form.get('current_password')
        new_password = request.form.get('new_password')
        confirm_password = request.form.get('confirm_password')
        
        # Validate required fields
        if not email or not first_name or not last_name:
            flash('Email, first name, and last name are required.', 'danger')
            return redirect(url_for('auth.edit_profile'))
        
        # Check if email has changed and is already taken
        if email != current_user.email and User.query.filter_by(email=email).first():
            flash('Email already in use by another account.', 'danger')
            return redirect(url_for('auth.edit_profile'))
        
        # Update basic information
        current_user.email = email
        current_user.first_name = first_name
        current_user.last_name = last_name
        
        # Password change (if requested)
        if current_password and new_password and confirm_password:
            # Check if current password is correct
            if not current_user.check_password(current_password):
                flash('Current password is incorrect.', 'danger')
                return redirect(url_for('auth.edit_profile'))
            
            # Check if new passwords match
            if new_password != confirm_password:
                flash('New passwords do not match.', 'danger')
                return redirect(url_for('auth.edit_profile'))
            
            # Update password
            current_user.set_password(new_password)
            flash('Password updated successfully.', 'success')
        
        try:
            db.session.commit()
            flash('Profile updated successfully.', 'success')
            return redirect(url_for('auth.profile'))
        except IntegrityError:
            db.session.rollback()
            flash('An error occurred while updating your profile.', 'danger')
    
    return render_template('auth/edit_profile.html')