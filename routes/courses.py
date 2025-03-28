from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from werkzeug.security import generate_password_hash
from sqlalchemy.exc import IntegrityError
from functools import wraps
from datetime import datetime

from app import db
from models import Course, User, RoleType
from utils import allowed_file, save_file, parse_date

courses_bp = Blueprint('courses', __name__)

@courses_bp.route('/')
@login_required
def index():
    """List all courses."""
    # Get filter and search parameters
    search = request.args.get('search', '')
    
    # Base query
    query = Course.query.filter_by(is_active=True)
    
    # Apply filters
    if search:
        query = query.filter((Course.code.ilike(f'%{search}%')) | 
                            (Course.title.ilike(f'%{search}%')))
    
    # Paginate results
    page = request.args.get('page', 1, type=int)
    per_page = 10
    courses = query.order_by(Course.code).paginate(page=page, per_page=per_page)
    
    return render_template('courses/index.html', 
                          courses=courses, 
                          search=search)

@courses_bp.route('/<int:course_id>')
@login_required
def view(course_id):
    """View a specific course."""
    course = Course.query.get_or_404(course_id)
    
    # Check if user has access to this course
    if not current_user.is_admin():
        if current_user.is_faculty() and course.faculty_id != current_user.id:
            if course not in current_user.enrolled_courses:
                flash('You do not have access to this course.', 'danger')
                return redirect(url_for('courses.index'))
    
    return render_template('courses/view.html', course=course)

@courses_bp.route('/create', methods=['GET', 'POST'])
@login_required
def create():
    """Create a new course."""
    # Only admin can create courses
    if not current_user.is_admin():
        flash('You do not have permission to create courses.', 'danger')
        return redirect(url_for('courses.index'))
    
    if request.method == 'POST':
        code = request.form.get('code')
        title = request.form.get('title')
        description = request.form.get('description')
        faculty_id = request.form.get('faculty_id')
        start_date_str = request.form.get('start_date')
        end_date_str = request.form.get('end_date')
        credits = request.form.get('credits', 3, type=int)
        is_active = True if request.form.get('is_active') else False
        
        # Parse dates
        start_date = parse_date(start_date_str)
        end_date = parse_date(end_date_str)
        
        # Validate input
        if not code or not title:
            flash('Course code and title are required.', 'danger')
            return redirect(url_for('courses.create'))
        
        # Check if course code already exists
        if Course.query.filter_by(code=code).first():
            flash('Course code already exists.', 'danger')
            return redirect(url_for('courses.create'))
        
        # Create new course
        new_course = Course(
            code=code,
            title=title,
            description=description,
            faculty_id=faculty_id,
            start_date=start_date,
            end_date=end_date,
            credits=credits,
            is_active=is_active
        )
        
        try:
            db.session.add(new_course)
            db.session.commit()
            flash(f'Course {code}: {title} created successfully.', 'success')
            return redirect(url_for('courses.index'))
        except IntegrityError:
            db.session.rollback()
            flash('An error occurred while creating the course.', 'danger')
    
    # Get faculty members for the form
    faculty_members = User.query.join(User.role).filter(User.role.has(name=RoleType.FACULTY)).all()
    
    return render_template('courses/create.html', faculty_members=faculty_members)

@courses_bp.route('/<int:course_id>/edit', methods=['GET', 'POST'])
@login_required
def edit(course_id):
    """Edit a course."""
    # Only admin can edit courses
    if not current_user.is_admin():
        flash('You do not have permission to edit courses.', 'danger')
        return redirect(url_for('courses.index'))
    
    course = Course.query.get_or_404(course_id)
    
    if request.method == 'POST':
        code = request.form.get('code')
        title = request.form.get('title')
        description = request.form.get('description')
        faculty_id = request.form.get('faculty_id')
        start_date_str = request.form.get('start_date')
        end_date_str = request.form.get('end_date')
        credits = request.form.get('credits', 3, type=int)
        is_active = True if request.form.get('is_active') else False
        
        # Parse dates
        start_date = parse_date(start_date_str)
        end_date = parse_date(end_date_str)
        
        # Validate input
        if not code or not title:
            flash('Course code and title are required.', 'danger')
            return redirect(url_for('courses.edit', course_id=course_id))
        
        # Check if course code already exists (excluding current course)
        code_exists = Course.query.filter(Course.code == code, Course.id != course_id).first()
        if code_exists:
            flash('Course code already exists.', 'danger')
            return redirect(url_for('courses.edit', course_id=course_id))
        
        # Update course
        course.code = code
        course.title = title
        course.description = description
        course.faculty_id = faculty_id
        course.start_date = start_date
        course.end_date = end_date
        course.credits = credits
        course.is_active = is_active
        
        try:
            db.session.commit()
            flash(f'Course {code}: {title} updated successfully.', 'success')
            return redirect(url_for('courses.view', course_id=course_id))
        except IntegrityError:
            db.session.rollback()
            flash('An error occurred while updating the course.', 'danger')
    
    # Get faculty members for the form
    faculty_members = User.query.join(User.role).filter(User.role.has(name=RoleType.FACULTY)).all()
    
    return render_template('courses/edit.html', course=course, faculty_members=faculty_members)

@courses_bp.route('/<int:course_id>/students')
@login_required
def students(course_id):
    """View students enrolled in a course."""
    course = Course.query.get_or_404(course_id)
    
    # Check if user has access to this course
    if not current_user.is_admin():
        if current_user.is_faculty() and course.faculty_id != current_user.id:
            flash('You do not have access to this course.', 'danger')
            return redirect(url_for('courses.index'))
    
    return render_template('courses/students.html', course=course)

@courses_bp.route('/<int:course_id>/manage-students', methods=['GET', 'POST'])
@login_required
def manage_students(course_id):
    """Manage students enrolled in a course."""
    # Only admin or course faculty can manage students
    course = Course.query.get_or_404(course_id)
    
    if not current_user.is_admin() and (current_user.is_faculty() and course.faculty_id != current_user.id):
        flash('You do not have permission to manage students for this course.', 'danger')
        return redirect(url_for('courses.index'))
    
    if request.method == 'POST':
        action = request.form.get('action')
        student_id = request.form.get('student_id')
        
        if not action or not student_id:
            flash('Invalid request.', 'danger')
            return redirect(url_for('courses.manage_students', course_id=course_id))
        
        # Get the student
        student = User.query.get_or_404(student_id)
        
        if action == 'add':
            # Add student to course
            if student not in course.students:
                course.students.append(student)
                try:
                    db.session.commit()
                    flash(f'{student.get_full_name()} added to the course.', 'success')
                except IntegrityError:
                    db.session.rollback()
                    flash('An error occurred while adding the student.', 'danger')
            else:
                flash(f'{student.get_full_name()} is already enrolled in this course.', 'warning')
        
        elif action == 'remove':
            # Remove student from course
            if student in course.students:
                course.students.remove(student)
                try:
                    db.session.commit()
                    flash(f'{student.get_full_name()} removed from the course.', 'success')
                except IntegrityError:
                    db.session.rollback()
                    flash('An error occurred while removing the student.', 'danger')
            else:
                flash(f'{student.get_full_name()} is not enrolled in this course.', 'warning')
    
    # Get all students
    students = User.query.join(User.role).filter(User.role.has(name=RoleType.STUDENT)).all()
    
    # Get enrolled student IDs
    enrolled_ids = [student.id for student in course.students]
    
    return render_template('courses/manage_students.html', 
                          course=course, 
                          students=students, 
                          enrolled_ids=enrolled_ids)