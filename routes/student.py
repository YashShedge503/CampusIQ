from flask import Blueprint, render_template, redirect, url_for, flash, request, abort, jsonify
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
from sqlalchemy.exc import IntegrityError
from functools import wraps
from datetime import datetime
import os

from app import db
from models import User, RoleType, Course, Assignment, Submission, Grade, SubmissionStatus, AssignmentStatus
from utils import allowed_file, save_file, parse_date
from ai_services import predict_student_performance, generate_assignment_recommendations

student_bp = Blueprint('student', __name__)

# Student required decorator
def student_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_student():
            abort(403)
        return f(*args, **kwargs)
    return decorated_function

@student_bp.route('/dashboard')
@login_required
@student_required
def dashboard():
    """Student dashboard page."""
    # Get enrolled courses
    courses = current_user.enrolled_courses
    
    # Get upcoming assignments
    upcoming_assignments = Assignment.query.join(Course).filter(
        Course.id.in_([c.id for c in courses]),
        Assignment.due_date > datetime.utcnow(),
        Assignment.status == AssignmentStatus.PUBLISHED
    ).order_by(Assignment.due_date).limit(5).all()
    
    # Get recent submissions
    recent_submissions = Submission.query.filter_by(
        student_id=current_user.id
    ).order_by(Submission.submission_date.desc()).limit(5).all()
    
    # Get recent grades
    recent_grades = Grade.query.join(Submission).filter(
        Submission.student_id == current_user.id
    ).order_by(Grade.graded_at.desc()).limit(5).all()
    
    # Get course progress
    course_progress = []
    for course in courses:
        assignments = Assignment.query.filter_by(
            course_id=course.id,
            status=AssignmentStatus.PUBLISHED
        ).all()
        
        total = len(assignments)
        completed = Submission.query.join(Assignment).filter(
            Assignment.course_id == course.id,
            Submission.student_id == current_user.id
        ).count()
        
        if total > 0:
            progress_percentage = (completed / total) * 100
        else:
            progress_percentage = 0
            
        course_progress.append({
            'course': course,
            'progress': progress_percentage,
            'completed': completed,
            'total': total
        })
    
    # Get personalized recommendations
    recommendations = generate_assignment_recommendations(
        current_user.id,
        None,  # No specific course
        {'recent_submissions': recent_submissions, 'recent_grades': recent_grades},
        {'enrolled_courses': courses}
    )
    
    return render_template('student/dashboard.html',
                          courses=courses,
                          upcoming_assignments=upcoming_assignments,
                          recent_submissions=recent_submissions,
                          recent_grades=recent_grades,
                          course_progress=course_progress,
                          recommendations=recommendations)

@student_bp.route('/courses')
@login_required
@student_required
def courses():
    """View all courses available to the student."""
    # Get filter and search parameters
    search = request.args.get('search', '')
    
    # Get enrolled courses
    enrolled_courses = current_user.enrolled_courses
    enrolled_ids = [c.id for c in enrolled_courses]
    
    # Get available courses for enrollment
    query = Course.query.filter_by(is_active=True)
    
    if search:
        query = query.filter((Course.code.ilike(f'%{search}%')) | 
                            (Course.title.ilike(f'%{search}%')))
    
    # Paginate results
    page = request.args.get('page', 1, type=int)
    per_page = 10
    available_courses = query.order_by(Course.code).paginate(page=page, per_page=per_page)
    
    return render_template('student/courses.html',
                          enrolled_courses=enrolled_courses,
                          available_courses=available_courses,
                          enrolled_ids=enrolled_ids,
                          search=search)

@student_bp.route('/courses/<int:course_id>/enroll', methods=['POST'])
@login_required
@student_required
def enroll_course(course_id):
    """Enroll in a course."""
    course = Course.query.filter_by(id=course_id, is_active=True).first_or_404()
    
    # Check if already enrolled
    if course in current_user.enrolled_courses:
        flash(f'You are already enrolled in {course.code}: {course.title}.', 'info')
        return redirect(url_for('student.courses'))
    
    # Enroll
    current_user.enrolled_courses.append(course)
    
    try:
        db.session.commit()
        flash(f'Successfully enrolled in {course.code}: {course.title}.', 'success')
    except IntegrityError:
        db.session.rollback()
        flash('An error occurred while enrolling in the course.', 'danger')
    
    return redirect(url_for('student.courses'))

@student_bp.route('/courses/<int:course_id>/unenroll', methods=['POST'])
@login_required
@student_required
def unenroll_course(course_id):
    """Unenroll from a course."""
    course = Course.query.get_or_404(course_id)
    
    # Check if enrolled
    if course not in current_user.enrolled_courses:
        flash(f'You are not enrolled in {course.code}: {course.title}.', 'info')
        return redirect(url_for('student.courses'))
    
    # Check if student has submissions
    submission_count = Submission.query.join(Assignment).filter(
        Assignment.course_id == course_id,
        Submission.student_id == current_user.id
    ).count()
    
    if submission_count > 0:
        flash('You cannot unenroll from this course because you have already submitted assignments.', 'warning')
        return redirect(url_for('student.courses'))
    
    # Unenroll
    current_user.enrolled_courses.remove(course)
    
    try:
        db.session.commit()
        flash(f'Successfully unenrolled from {course.code}: {course.title}.', 'success')
    except IntegrityError:
        db.session.rollback()
        flash('An error occurred while unenrolling from the course.', 'danger')
    
    return redirect(url_for('student.courses'))

@student_bp.route('/assignments')
@login_required
@student_required
def assignments():
    """View all assignments for enrolled courses."""
    # Get filter parameters
    course_id = request.args.get('course_id', type=int)
    status = request.args.get('status')
    search = request.args.get('search', '')
    
    # Get enrolled courses
    enrolled_courses = current_user.enrolled_courses
    enrolled_ids = [c.id for c in enrolled_courses]
    
    # Base query for assignments
    query = Assignment.query.join(Course).filter(
        Course.id.in_(enrolled_ids),
        Assignment.status == AssignmentStatus.PUBLISHED
    )
    
    # Apply filters
    if course_id:
        query = query.filter(Course.id == course_id)
    
    if search:
        query = query.filter(Assignment.title.ilike(f'%{search}%'))
    
    # Get submissions for each assignment
    assignments_with_status = []
    
    # Get assignments with pagination
    page = request.args.get('page', 1, type=int)
    per_page = 10
    assignments = query.order_by(Assignment.due_date.desc()).paginate(page=page, per_page=per_page)
    
    for assignment in assignments.items:
        # Check if student has already submitted
        submission = Submission.query.filter_by(
            assignment_id=assignment.id,
            student_id=current_user.id
        ).first()
        
        if submission:
            # If submitted and graded
            if submission.status in [SubmissionStatus.GRADED, SubmissionStatus.RETURNED]:
                status = "Graded"
                grade = Grade.query.filter_by(submission_id=submission.id).first()
                grade_value = grade.score if grade else None
            # If submitted but not graded
            else:
                status = "Submitted"
                grade_value = None
        # If not submitted
        else:
            # If past due date
            if assignment.due_date < datetime.utcnow():
                status = "Overdue"
            else:
                status = "Pending"
            grade_value = None
        
        assignments_with_status.append({
            'assignment': assignment,
            'status': status,
            'grade': grade_value,
            'submission': submission
        })
    
    return render_template('student/assignments.html',
                          assignments=assignments,
                          assignments_with_status=assignments_with_status,
                          enrolled_courses=enrolled_courses,
                          current_course_id=course_id,
                          search=search)

@student_bp.route('/assignments/<int:assignment_id>/submit', methods=['GET', 'POST'])
@login_required
@student_required
def submit_assignment(assignment_id):
    """Submit an assignment."""
    # Get the assignment
    assignment = Assignment.query.filter_by(
        id=assignment_id,
        status=AssignmentStatus.PUBLISHED
    ).first_or_404()
    
    # Check if student is enrolled in the course
    if assignment.course not in current_user.enrolled_courses:
        flash('You are not enrolled in this course.', 'danger')
        return redirect(url_for('student.assignments'))
    
    # Check if student has already submitted
    existing_submission = Submission.query.filter_by(
        assignment_id=assignment_id,
        student_id=current_user.id
    ).first()
    
    if request.method == 'POST':
        content = request.form.get('content')
        file = request.files.get('file')
        
        # Validate submission
        if not content and not file:
            flash('You must provide either text content or a file.', 'danger')
            return redirect(url_for('student.submit_assignment', assignment_id=assignment_id))
        
        # Process file if provided
        file_path = None
        if file and file.filename:
            if not allowed_file(file.filename):
                flash('File type not allowed.', 'danger')
                return redirect(url_for('student.submit_assignment', assignment_id=assignment_id))
            
            file_path = save_file(file, f'assignments/{assignment_id}')
        
        # Create or update submission
        if existing_submission:
            existing_submission.content = content
            if file_path:
                # Delete old file if exists
                if existing_submission.file_path and os.path.exists(existing_submission.file_path):
                    try:
                        os.remove(existing_submission.file_path)
                    except:
                        pass
                existing_submission.file_path = file_path
            existing_submission.submission_date = datetime.utcnow()
            
            # Check if late
            if datetime.utcnow() > assignment.due_date:
                existing_submission.status = SubmissionStatus.LATE
            else:
                existing_submission.status = SubmissionStatus.SUBMITTED
        else:
            # Create new submission
            new_submission = Submission(
                assignment_id=assignment_id,
                student_id=current_user.id,
                content=content,
                file_path=file_path,
                submission_date=datetime.utcnow()
            )
            
            # Check if late
            if datetime.utcnow() > assignment.due_date:
                new_submission.status = SubmissionStatus.LATE
            
            db.session.add(new_submission)
        
        try:
            db.session.commit()
            flash('Assignment submitted successfully.', 'success')
            return redirect(url_for('student.assignments'))
        except IntegrityError:
            db.session.rollback()
            flash('An error occurred while submitting the assignment.', 'danger')
    
    return render_template('student/submit_assignment.html',
                          assignment=assignment,
                          existing_submission=existing_submission)

@student_bp.route('/submissions')
@login_required
@student_required
def submissions():
    """View all submissions made by the student."""
    # Get filter parameters
    course_id = request.args.get('course_id', type=int)
    status = request.args.get('status')
    
    # Base query for submissions
    query = Submission.query.join(Assignment).join(Course).filter(
        Submission.student_id == current_user.id
    )
    
    # Apply filters
    if course_id:
        query = query.filter(Course.id == course_id)
    
    if status:
        query = query.filter(Submission.status == SubmissionStatus[status.upper()])
    
    # Get submissions with pagination
    page = request.args.get('page', 1, type=int)
    per_page = 10
    submissions = query.order_by(Submission.submission_date.desc()).paginate(page=page, per_page=per_page)
    
    # Get enrolled courses for filter
    enrolled_courses = current_user.enrolled_courses
    
    return render_template('student/submissions.html',
                          submissions=submissions,
                          enrolled_courses=enrolled_courses,
                          current_course_id=course_id,
                          current_status=status)

@student_bp.route('/submissions/<int:submission_id>')
@login_required
@student_required
def view_submission(submission_id):
    """View a specific submission."""
    # Get the submission
    submission = Submission.query.filter_by(
        id=submission_id,
        student_id=current_user.id
    ).first_or_404()
    
    # Get grade if available
    grade = Grade.query.filter_by(submission_id=submission_id).first()
    
    return render_template('student/view_submission.html',
                          submission=submission,
                          grade=grade)

@student_bp.route('/analytics')
@login_required
@student_required
def analytics():
    """Student analytics dashboard."""
    # Get enrolled courses
    enrolled_courses = current_user.enrolled_courses
    
    # Get selected course
    course_id = request.args.get('course_id', type=int)
    if course_id:
        course = Course.query.get_or_404(course_id)
        if course not in enrolled_courses:
            flash('You are not enrolled in this course.', 'danger')
            return redirect(url_for('student.analytics'))
    elif enrolled_courses:
        course = enrolled_courses[0]
    else:
        course = None
    
    # Initialize analytics data
    analytics_data = {
        'grades': None,
        'performance_trend': None,
        'predictions': None,
        'recommendations': None
    }
    
    if course:
        # Get grades for the course
        grades = Grade.query.join(Submission).join(Assignment).filter(
            Assignment.course_id == course.id,
            Submission.student_id == current_user.id
        ).all()
        
        # Format grade data
        grade_data = []
        for grade in grades:
            assignment = grade.submission.assignment
            percentage = (grade.score / assignment.max_score) * 100
            grade_data.append({
                'assignment': assignment.title,
                'score': grade.score,
                'max_score': assignment.max_score,
                'percentage': percentage
            })
        
        analytics_data['grades'] = grade_data
        
        # Get performance trend data (all assignments in chronological order)
        assignments = Assignment.query.filter_by(
            course_id=course.id,
            status=AssignmentStatus.PUBLISHED
        ).order_by(Assignment.due_date).all()
        
        trend_data = []
        for assignment in assignments:
            submission = Submission.query.filter_by(
                assignment_id=assignment.id,
                student_id=current_user.id
            ).first()
            
            if submission:
                grade = Grade.query.filter_by(submission_id=submission.id).first()
                if grade:
                    percentage = (grade.score / assignment.max_score) * 100
                    trend_data.append({
                        'assignment': assignment.title,
                        'date': assignment.due_date.strftime('%Y-%m-%d'),
                        'percentage': percentage
                    })
        
        analytics_data['performance_trend'] = trend_data
        
        # Get performance predictions
        try:
            prediction_data = predict_student_performance(
                current_user.id,
                course.id,
                {'grades': grade_data}
            )
            analytics_data['predictions'] = prediction_data
        except Exception as e:
            flash(f'Error generating predictions: {str(e)}', 'warning')
        
        # Get personalized recommendations
        try:
            recommendations = generate_assignment_recommendations(
                current_user.id,
                course.id,
                {'grades': grade_data, 'trend_data': trend_data},
                {'course': course}
            )
            analytics_data['recommendations'] = recommendations
        except Exception as e:
            flash(f'Error generating recommendations: {str(e)}', 'warning')
    
    return render_template('student/analytics.html',
                          enrolled_courses=enrolled_courses,
                          current_course=course,
                          analytics_data=analytics_data)

@student_bp.route('/api/predict-performance', methods=['POST'])
@login_required
@student_required
def api_predict_performance():
    """API endpoint to predict student performance."""
    if not request.is_json:
        return jsonify({'error': 'Request must be JSON'}), 400
        
    data = request.get_json()
    
    course_id = data.get('course_id')
    
    if not course_id:
        return jsonify({'error': 'Course ID is required'}), 400
    
    # Check if student is enrolled in the course
    course = Course.query.get_or_404(course_id)
    if course not in current_user.enrolled_courses:
        return jsonify({'error': 'You are not enrolled in this course'}), 403
    
    # Get grade data for the course
    grades = Grade.query.join(Submission).join(Assignment).filter(
        Assignment.course_id == course_id,
        Submission.student_id == current_user.id
    ).all()
    
    grade_data = []
    for grade in grades:
        assignment = grade.submission.assignment
        percentage = (grade.score / assignment.max_score) * 100
        grade_data.append({
            'assignment': assignment.title,
            'score': grade.score,
            'max_score': assignment.max_score,
            'percentage': percentage
        })
    
    try:
        prediction_data = predict_student_performance(
            current_user.id,
            course_id,
            {'grades': grade_data}
        )
        return jsonify(prediction_data)
    except Exception as e:
        return jsonify({'error': str(e)}), 500