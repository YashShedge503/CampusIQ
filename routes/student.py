from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from functools import wraps
from datetime import datetime, timedelta
from app import db
from models import User, Course, Assignment, Submission, Grade, Material, Schedule, RoleType, AssignmentStatus, SubmissionStatus
from utils import save_file, calculate_student_analytics, get_user_courses, generate_schedule_suggestions
from ai_services import predict_student_performance, generate_assignment_recommendations

student_bp = Blueprint('student', __name__)

# Student authorization decorator
def student_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_student():
            flash("Student area only.", "danger")
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated_function

@student_bp.route('/dashboard')
@login_required
@student_required
def dashboard():
    # Get enrolled courses
    courses = current_user.enrolled_courses
    course_count = len(courses)
    
    # Get upcoming assignments
    upcoming_assignments = Assignment.query.join(Course).join(
        course_students
    ).filter(
        course_students.c.user_id == current_user.id,
        Assignment.due_date > datetime.now(),
        Assignment.due_date <= datetime.now() + timedelta(days=14),
        Assignment.status == AssignmentStatus.PUBLISHED
    ).order_by(Assignment.due_date).limit(5).all()
    
    # Check which assignments have been submitted
    submitted_assignment_ids = [s.assignment_id for s in 
                               Submission.query.filter_by(student_id=current_user.id).all()]
    
    # Get recently graded submissions
    recent_grades = Grade.query.join(Submission).filter(
        Submission.student_id == current_user.id
    ).order_by(Grade.graded_at.desc()).limit(5).all()
    
    # Get upcoming schedule items
    upcoming_schedule = Schedule.query.filter(
        (Schedule.owner_id == current_user.id) |
        (Schedule.course_id.in_([c.id for c in courses])),
        Schedule.start_time > datetime.now(),
        Schedule.start_time <= datetime.now() + timedelta(days=7)
    ).order_by(Schedule.start_time).limit(5).all()
    
    # Get schedule suggestions
    schedule_suggestions = generate_schedule_suggestions(current_user.id)
    
    # Get recent course materials
    recent_materials = Material.query.join(Course).join(
        course_students
    ).filter(
        course_students.c.user_id == current_user.id,
        Material.is_visible == True
    ).order_by(Material.created_at.desc()).limit(5).all()
    
    # Calculate basic performance metrics
    grades = Grade.query.join(Submission).filter(
        Submission.student_id == current_user.id
    ).all()
    
    avg_grade = None
    if grades:
        total_score = sum([g.score for g in grades])
        avg_grade = total_score / len(grades)
    
    return render_template('dashboard/student.html',
                           courses=courses,
                           course_count=course_count,
                           upcoming_assignments=upcoming_assignments,
                           submitted_assignment_ids=submitted_assignment_ids,
                           recent_grades=recent_grades,
                           upcoming_schedule=upcoming_schedule,
                           schedule_suggestions=schedule_suggestions,
                           recent_materials=recent_materials,
                           avg_grade=avg_grade)

@student_bp.route('/courses')
@login_required
@student_required
def courses():
    # Get enrolled courses
    enrolled_courses = current_user.enrolled_courses
    
    # Get available courses for enrollment
    available_courses = Course.query.filter(
        ~Course.id.in_([c.id for c in enrolled_courses]),
        Course.is_active == True
    ).all()
    
    return render_template('student/courses.html',
                           enrolled_courses=enrolled_courses,
                           available_courses=available_courses)

@student_bp.route('/courses/<int:course_id>/enroll', methods=['POST'])
@login_required
@student_required
def enroll_course(course_id):
    course = Course.query.get_or_404(course_id)
    
    # Check if already enrolled
    if course in current_user.enrolled_courses:
        flash('You are already enrolled in this course.', 'warning')
        return redirect(url_for('student.courses'))
    
    # Enroll in the course
    current_user.enrolled_courses.append(course)
    
    try:
        db.session.commit()
        flash(f'Successfully enrolled in {course.code}: {course.title}', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'An error occurred: {str(e)}', 'danger')
    
    return redirect(url_for('student.courses'))

@student_bp.route('/courses/<int:course_id>/unenroll', methods=['POST'])
@login_required
@student_required
def unenroll_course(course_id):
    course = Course.query.get_or_404(course_id)
    
    # Check if enrolled
    if course not in current_user.enrolled_courses:
        flash('You are not enrolled in this course.', 'warning')
        return redirect(url_for('student.courses'))
    
    # Unenroll from the course
    current_user.enrolled_courses.remove(course)
    
    try:
        db.session.commit()
        flash(f'Successfully unenrolled from {course.code}: {course.title}', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'An error occurred: {str(e)}', 'danger')
    
    return redirect(url_for('student.courses'))

@student_bp.route('/assignments')
@login_required
@student_required
def assignments():
    # Get filter parameters
    course_id = request.args.get('course_id', type=int)
    status = request.args.get('status')
    
    # Base query - get assignments from enrolled courses
    query = Assignment.query.join(Course).join(
        course_students
    ).filter(
        course_students.c.user_id == current_user.id,
        Assignment.status == AssignmentStatus.PUBLISHED
    )
    
    # Apply filters
    if course_id:
        query = query.filter(Assignment.course_id == course_id)
    
    # Get all enrolled courses for the filter dropdown
    courses = current_user.enrolled_courses
    
    # Get paginated results
    page = request.args.get('page', 1, type=int)
    per_page = 10
    assignments = query.order_by(Assignment.due_date.desc()).paginate(page=page, per_page=per_page)
    
    # Get IDs of submitted assignments
    submitted_assignment_ids = [s.assignment_id for s in 
                               Submission.query.filter_by(student_id=current_user.id).all()]
    
    return render_template('student/assignments.html', 
                           assignments=assignments,
                           courses=courses,
                           current_course_id=course_id,
                           submitted_assignment_ids=submitted_assignment_ids)

@student_bp.route('/assignments/<int:assignment_id>/submit', methods=['GET', 'POST'])
@login_required
@student_required
def submit_assignment(assignment_id):
    # Get the assignment
    assignment = Assignment.query.join(Course).join(
        course_students
    ).filter(
        Assignment.id == assignment_id,
        course_students.c.user_id == current_user.id,
        Assignment.status == AssignmentStatus.PUBLISHED
    ).first_or_404()
    
    # Check for existing submission
    submission = Submission.query.filter_by(
        assignment_id=assignment_id,
        student_id=current_user.id
    ).first()
    
    if request.method == 'POST':
        content = request.form.get('content')
        file = request.files.get('file')
        
        # Check for required fields
        if not content and not file:
            flash('Please provide either text content or upload a file for your submission.', 'danger')
        else:
            file_path = None
            if file and file.filename:
                # Save the uploaded file
                file_path = save_file(file, f'submissions/{assignment_id}')
                if not file_path:
                    flash('Error uploading file. Please try again.', 'danger')
                    return redirect(url_for('student.submit_assignment', assignment_id=assignment_id))
            
            # Determine submission status
            is_late = datetime.now() > assignment.due_date
            status = SubmissionStatus.LATE if is_late else SubmissionStatus.SUBMITTED
            
            if submission:
                # Update existing submission
                submission.content = content
                if file_path:
                    submission.file_path = file_path
                submission.status = status
                submission.submission_date = datetime.now()
            else:
                # Create new submission
                submission = Submission(
                    assignment_id=assignment_id,
                    student_id=current_user.id,
                    content=content,
                    file_path=file_path,
                    status=status
                )
                db.session.add(submission)
            
            try:
                db.session.commit()
                
                if is_late:
                    flash('Your submission was recorded. Note that it was submitted after the due date.', 'warning')
                else:
                    flash('Assignment submitted successfully!', 'success')
                
                return redirect(url_for('student.assignments'))
            except Exception as e:
                db.session.rollback()
                flash(f'An error occurred: {str(e)}', 'danger')
    
    return render_template('student/submit_assignment.html',
                           assignment=assignment,
                           submission=submission)

@student_bp.route('/submissions')
@login_required
@student_required
def submissions():
    # Get all submissions by the student
    submissions = Submission.query.filter_by(
        student_id=current_user.id
    ).order_by(Submission.submission_date.desc()).all()
    
    return render_template('student/submissions.html', submissions=submissions)

@student_bp.route('/submissions/<int:submission_id>')
@login_required
@student_required
def view_submission(submission_id):
    # Get the submission
    submission = Submission.query.filter_by(
        id=submission_id,
        student_id=current_user.id
    ).first_or_404()
    
    return render_template('student/view_submission.html', submission=submission)

@student_bp.route('/analytics')
@login_required
@student_required
def analytics():
    # Get student analytics data
    analytics_data = calculate_student_analytics(current_user.id)
    
    return render_template('student/analytics.html', analytics=analytics_data)

@student_bp.route('/api/predict_performance', methods=['POST'])
@login_required
@student_required
def api_predict_performance():
    data = request.json
    course_id = data.get('course_id')
    
    if not course_id:
        return jsonify({'error': 'Course ID is required'}), 400
    
    # Get grades for this student in this course
    grades_data = []
    submissions = Submission.query.join(Assignment).filter(
        Submission.student_id == current_user.id,
        Assignment.course_id == course_id
    ).all()
    
    for submission in submissions:
        if submission.grade:
            grades_data.append({
                'assignment_id': submission.assignment_id,
                'score': submission.grade.score,
                'max_score': submission.assignment.max_score,
                'timestamp': submission.grade.graded_at.timestamp()
            })
    
    prediction = predict_student_performance(current_user.id, course_id, grades_data)
    return jsonify(prediction)
