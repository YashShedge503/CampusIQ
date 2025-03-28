from flask import Blueprint, render_template, redirect, url_for, flash, request, session
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy.exc import IntegrityError

from app import db
from models import User, Role, RoleType
from utils import allowed_file, save_file

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/')
def index():
    """Homepage route."""
    return render_template('index.html')

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    """User login route."""
    if current_user.is_authenticated:
        return redirect(url_for('auth.index'))
        
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        remember = True if request.form.get('remember') else False
        
        user = User.query.filter_by(username=username).first()
        
        # Check if user exists and password is correct
        if not user or not user.check_password(password):
            flash('Please check your login details and try again.', 'danger')
            return render_template('auth/login.html')
            
        # Check if user is active
        if not user.is_active:
            flash('Your account is inactive. Please contact an administrator.', 'warning')
            return render_template('auth/login.html')
            
        # Log in the user
        login_user(user, remember=remember)
        
        # Redirect to appropriate dashboard based on role
        if user.is_admin():
            return redirect(url_for('admin.dashboard'))
        elif user.is_faculty():
            return redirect(url_for('faculty.dashboard'))
        elif user.is_student():
            return redirect(url_for('student.dashboard'))
        
        # Default redirect
        return redirect(url_for('auth.index'))
        
    return render_template('auth/login.html')

@auth_bp.route('/logout')
@login_required
def logout():
    """User logout route."""
    logout_user()
    flash('You have been logged out successfully.', 'success')
    return redirect(url_for('auth.login'))

@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    """User registration route."""
    if current_user.is_authenticated:
        return redirect(url_for('auth.index'))
        
    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')
        first_name = request.form.get('first_name')
        last_name = request.form.get('last_name')
        role_type = RoleType.STUDENT  # Default to student role for self-registration
        
        # Basic validation
        if not username or not email or not password or not first_name or not last_name:
            flash('All fields are required.', 'danger')
            return render_template('auth/register.html')
            
        if password != confirm_password:
            flash('Passwords do not match.', 'danger')
            return render_template('auth/register.html')
            
        # Check if username or email already exists
        if User.query.filter_by(username=username).first():
            flash('Username already exists.', 'danger')
            return render_template('auth/register.html')
            
        if User.query.filter_by(email=email).first():
            flash('Email already exists.', 'danger')
            return render_template('auth/register.html')
        
        # Get the role
        student_role = Role.query.filter_by(name=role_type).first()
        if not student_role:
            flash('Error creating account. Please contact an administrator.', 'danger')
            return render_template('auth/register.html')
            
        # Create the user
        new_user = User(
            username=username,
            email=email,
            password_hash=generate_password_hash(password),
            first_name=first_name,
            last_name=last_name,
            role_id=student_role.id
        )
        
        try:
            db.session.add(new_user)
            db.session.commit()
            flash('Registration successful! You can now login.', 'success')
            return redirect(url_for('auth.login'))
        except IntegrityError:
            db.session.rollback()
            flash('An error occurred while registering your account.', 'danger')
            
    return render_template('auth/register.html')

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
        # Update basic info
        current_user.first_name = request.form.get('first_name', current_user.first_name)
        current_user.last_name = request.form.get('last_name', current_user.last_name)
        current_user.email = request.form.get('email', current_user.email)
        
        # Update password if provided
        current_password = request.form.get('current_password')
        new_password = request.form.get('new_password')
        confirm_password = request.form.get('confirm_password')
        
        if current_password and new_password:
            if not current_user.check_password(current_password):
                flash('Current password is incorrect.', 'danger')
                return render_template('auth/edit_profile.html')
                
            if new_password != confirm_password:
                flash('New passwords do not match.', 'danger')
                return render_template('auth/edit_profile.html')
                
            current_user.password_hash = generate_password_hash(new_password)
            flash('Password updated successfully.', 'success')
        
        try:
            db.session.commit()
            flash('Profile updated successfully.', 'success')
            return redirect(url_for('auth.profile'))
        except IntegrityError:
            db.session.rollback()
            flash('An error occurred while updating your profile.', 'danger')
            
    return render_template('auth/edit_profile.html')