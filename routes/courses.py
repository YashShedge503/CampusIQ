from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from datetime import datetime
from app import db
from models import User, Course, Role, RoleType
from utils import parse_date, get_user_courses, get_course_progression

courses_bp = Blueprint('courses', __name__)

@courses_bp.route('/')
@login_required
def index():
    # Get courses based on user role
    courses = get_user_courses(current_user)
    
    return render_template('courses/index.html', courses=courses)

@courses_bp.route('/<int:course_id>')
@login_required
def view(course_id):
    # Get the course
    course = Course.query.get_or_404(course_id)
    
    # Check permission
    if not current_user.is_admin():
        if current_user.is_faculty() and course.faculty_id != current_user.id:
            flash('You do not have permission to view this course.', 'danger')
            return redirect(url_for('courses.index'))
        elif current_user.is_student() and course not in current_user.enrolled_courses:
            flash('You are not enrolled in this course.', 'danger')
            return redirect(url_for('courses.index'))
    
    # Get assignments for this course
    assignments = course.assignments
    
    # Get materials for this course
    materials = course.materials
    
    # Get students enrolled in this course (for faculty/admin)
    students = course.students if current_user.is_admin() or current_user.is_faculty() else []
    
    # Get course progression data for faculty
    progression_data = None
    if current_user.is_faculty() and course.faculty_id == current_user.id:
        progression_data = get_course_progression(course_id)
    
    return render_template('courses/view.html',
                           course=course,
                           assignments=assignments,
                           materials=materials,
                           students=students,
                           progression_data=progression_data)

@courses_bp.route('/create', methods=['GET', 'POST'])
@login_required
def create():
    # Only admins and faculty can create courses
    if not current_user.is_admin() and not current_user.is_faculty():
        flash('You do not have permission to create courses.', 'danger')
        return redirect(url_for('courses.index'))
    
    # For admin, get all faculty members
    faculty_list = []
    if current_user.is_admin():
        faculty_role = Role.query.filter_by(name=RoleType.FACULTY).first()
        faculty_list = User.query.filter_by(role_id=faculty_role.id).all()
    
    if request.method == 'POST':
        code = request.form.get('code')
        title = request.form.get('title')
        description = request.form.get('description')
        faculty_id = request.form.get('faculty_id') if current_user.is_admin() else current_user.id
        start_date_str = request.form.get('start_date')
        end_date_str = request.form.get('end_date')
        credits = request.form.get('credits', 3)
        
        # Basic validation
        error = None
        if not code or not title:
            error = 'Course code and title are required.'
        elif Course.query.filter_by(code=code).first():
            error = 'Course code already exists.'
        
        # Parse dates
        start_date = parse_date(start_date_str)
        end_date = parse_date(end_date_str)
        
        if start_date and end_date and start_date > end_date:
            error = 'End date must be after start date.'
        
        if error:
            flash(error, 'danger')
        else:
            # Create new course
            new_course = Course(
                code=code,
                title=title,
                description=description,
                faculty_id=faculty_id,
                start_date=start_date,
                end_date=end_date,
                credits=int(credits),
                is_active=True
            )
            
            try:
                db.session.add(new_course)
                db.session.commit()
                flash('Course created successfully!', 'success')
                return redirect(url_for('courses.view', course_id=new_course.id))
            except Exception as e:
                db.session.rollback()
                flash(f'An error occurred: {str(e)}', 'danger')
    
    return render_template('courses/create.html', faculty_list=faculty_list)

@courses_bp.route('/<int:course_id>/edit', methods=['GET', 'POST'])
@login_required
def edit(course_id):
    # Get the course
    course = Course.query.get_or_404(course_id)
    
    # Check permission
    if not current_user.is_admin() and (not current_user.is_faculty() or course.faculty_id != current_user.id):
        flash('You do not have permission to edit this course.', 'danger')
        return redirect(url_for('courses.index'))
    
    # For admin, get all faculty members
    faculty_list = []
    if current_user.is_admin():
        faculty_role = Role.query.filter_by(name=RoleType.FACULTY).first()
        faculty_list = User.query.filter_by(role_id=faculty_role.id).all()
    
    if request.method == 'POST':
        code = request.form.get('code')
        title = request.form.get('title')
        description = request.form.get('description')
        faculty_id = request.form.get('faculty_id') if current_user.is_admin() else course.faculty_id
        start_date_str = request.form.get('start_date')
        end_date_str = request.form.get('end_date')
        credits = request.form.get('credits', 3)
        is_active = 'is_active' in request.form
        
        # Basic validation
        error = None
        if not code or not title:
            error = 'Course code and title are required.'
        elif code != course.code and Course.query.filter_by(code=code).first():
            error = 'Course code already exists.'
        
        # Parse dates
        start_date = parse_date(start_date_str)
        end_date = parse_date(end_date_str)
        
        if start_date and end_date and start_date > end_date:
            error = 'End date must be after start date.'
        
        if error:
            flash(error, 'danger')
        else:
            # Update course
            course.code = code
            course.title = title
            course.description = description
            course.faculty_id = faculty_id
            course.start_date = start_date
            course.end_date = end_date
            course.credits = int(credits)
            course.is_active = is_active
            
            try:
                db.session.commit()
                flash('Course updated successfully!', 'success')
                return redirect(url_for('courses.view', course_id=course.id))
            except Exception as e:
                db.session.rollback()
                flash(f'An error occurred: {str(e)}', 'danger')
    
    return render_template('courses/edit.html', course=course, faculty_list=faculty_list)

@courses_bp.route('/<int:course_id>/students')
@login_required
def students(course_id):
    # Get the course
    course = Course.query.get_or_404(course_id)
    
    # Check permission
    if not current_user.is_admin() and (not current_user.is_faculty() or course.faculty_id != current_user.id):
        flash('You do not have permission to view course students.', 'danger')
        return redirect(url_for('courses.index'))
    
    # Get students enrolled in this course
    students = course.students
    
    return render_template('courses/students.html', course=course, students=students)

@courses_bp.route('/<int:course_id>/manage_students', methods=['GET', 'POST'])
@login_required
def manage_students(course_id):
    # Get the course
    course = Course.query.get_or_404(course_id)
    
    # Check permission
    if not current_user.is_admin() and (not current_user.is_faculty() or course.faculty_id != current_user.id):
        flash('You do not have permission to manage course students.', 'danger')
        return redirect(url_for('courses.index'))
    
    if request.method == 'POST':
        action = request.form.get('action')
        student_id = request.form.get('student_id')
        
        if not action or not student_id:
            flash('Invalid request.', 'danger')
            return redirect(url_for('courses.manage_students', course_id=course_id))
        
        student = User.query.get(student_id)
        if not student or not student.is_student():
            flash('Invalid student.', 'danger')
            return redirect(url_for('courses.manage_students', course_id=course_id))
        
        if action == 'add':
            if student in course.students:
                flash(f'{student.get_full_name()} is already enrolled in this course.', 'warning')
            else:
                course.students.append(student)
                flash(f'{student.get_full_name()} was successfully enrolled in the course.', 'success')
        
        elif action == 'remove':
            if student not in course.students:
                flash(f'{student.get_full_name()} is not enrolled in this course.', 'warning')
            else:
                course.students.remove(student)
                flash(f'{student.get_full_name()} was successfully removed from the course.', 'success')
        
        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            flash(f'An error occurred: {str(e)}', 'danger')
        
        return redirect(url_for('courses.manage_students', course_id=course_id))
    
    # Get all students
    student_role = Role.query.filter_by(name=RoleType.STUDENT).first()
    all_students = User.query.filter_by(role_id=student_role.id).all()
    
    # Get enrolled students
    enrolled_students = course.students
    
    # Get unenrolled students
    unenrolled_students = [s for s in all_students if s not in enrolled_students]
    
    return render_template('courses/manage_students.html',
                           course=course,
                           enrolled_students=enrolled_students,
                           unenrolled_students=unenrolled_students)
