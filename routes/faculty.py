from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from functools import wraps
from datetime import datetime, timedelta
from app import db
from models import User, Course, Assignment, Submission, Grade, Material, Schedule, RoleType, AssignmentStatus, SubmissionStatus
from utils import save_file, parse_date, calculate_course_analytics, generate_schedule_suggestions
from ai_services import analyze_submission

faculty_bp = Blueprint('faculty', __name__)

# Faculty authorization decorator
def faculty_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_faculty():
            flash("Faculty area only.", "danger")
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated_function

@faculty_bp.route('/dashboard')
@login_required
@faculty_required
def dashboard():
    # Get courses taught by the faculty member
    courses = Course.query.filter_by(faculty_id=current_user.id).all()
    course_count = len(courses)
    
    # Get student counts across all courses
    student_counts = {}
    total_students = 0
    for course in courses:
        student_count = len(course.students)
        student_counts[course.id] = student_count
        total_students += student_count
    
    # Get recent assignments
    recent_assignments = Assignment.query.join(Course).filter(
        Course.faculty_id == current_user.id
    ).order_by(Assignment.created_at.desc()).limit(5).all()
    
    # Get pending submissions that need grading
    pending_submissions = Submission.query.join(Assignment).join(Course).filter(
        Course.faculty_id == current_user.id,
        Submission.status == SubmissionStatus.SUBMITTED
    ).order_by(Submission.submission_date.desc()).limit(10).all()
    
    # Get upcoming deadlines
    upcoming_deadlines = Assignment.query.join(Course).filter(
        Course.faculty_id == current_user.id,
        Assignment.due_date > datetime.now(),
        Assignment.due_date <= datetime.now() + timedelta(days=14)
    ).order_by(Assignment.due_date).limit(5).all()
    
    # Get upcoming schedule items
    upcoming_schedule = Schedule.query.filter(
        Schedule.owner_id == current_user.id,
        Schedule.start_time > datetime.now(),
        Schedule.start_time <= datetime.now() + timedelta(days=7)
    ).order_by(Schedule.start_time).limit(5).all()
    
    # Get schedule suggestions
    schedule_suggestions = generate_schedule_suggestions(current_user.id)
    
    return render_template('dashboard/faculty.html',
                           courses=courses,
                           course_count=course_count,
                           student_counts=student_counts,
                           total_students=total_students,
                           recent_assignments=recent_assignments,
                           pending_submissions=pending_submissions,
                           upcoming_deadlines=upcoming_deadlines,
                           upcoming_schedule=upcoming_schedule,
                           schedule_suggestions=schedule_suggestions)

@faculty_bp.route('/assignments')
@login_required
@faculty_required
def assignments():
    # Get filter parameters
    course_id = request.args.get('course_id', type=int)
    status = request.args.get('status')
    
    # Base query
    query = Assignment.query.join(Course).filter(Course.faculty_id == current_user.id)
    
    # Apply filters
    if course_id:
        query = query.filter(Assignment.course_id == course_id)
    
    if status:
        try:
            status_enum = AssignmentStatus[status.upper()]
            query = query.filter(Assignment.status == status_enum)
        except (KeyError, ValueError):
            # Invalid status, ignore this filter
            pass
    
    # Get all courses for the filter dropdown
    courses = Course.query.filter_by(faculty_id=current_user.id).all()
    
    # Get paginated results
    page = request.args.get('page', 1, type=int)
    per_page = 10
    assignments = query.order_by(Assignment.due_date.desc()).paginate(page=page, per_page=per_page)
    
    return render_template('faculty/assignments.html', 
                           assignments=assignments,
                           courses=courses,
                           current_course_id=course_id,
                           current_status=status)

@faculty_bp.route('/assignments/new', methods=['GET', 'POST'])
@login_required
@faculty_required
def new_assignment():
    # Get all courses taught by the faculty
    courses = Course.query.filter_by(faculty_id=current_user.id).all()
    
    if request.method == 'POST':
        title = request.form.get('title')
        description = request.form.get('description')
        course_id = request.form.get('course_id')
        due_date_str = request.form.get('due_date')
        max_score = request.form.get('max_score')
        weight = request.form.get('weight')
        status = request.form.get('status')
        
        # Basic validation
        error = None
        if not title or not course_id or not due_date_str or not max_score:
            error = 'Required fields cannot be empty.'
        
        # Parse due date
        due_date = parse_date(due_date_str)
        if not due_date:
            error = 'Invalid due date format.'
        
        # Validate course
        course = Course.query.get(course_id)
        if not course or course.faculty_id != current_user.id:
            error = 'Invalid course selected.'
        
        if error:
            flash(error, 'danger')
        else:
            # Get assignment status
            try:
                status_enum = AssignmentStatus[status.upper()]
            except (KeyError, ValueError):
                status_enum = AssignmentStatus.DRAFT
            
            # Create new assignment
            new_assignment = Assignment(
                title=title,
                description=description,
                course_id=course_id,
                due_date=due_date,
                max_score=float(max_score),
                weight=float(weight) if weight else 1.0,
                status=status_enum
            )
            
            try:
                db.session.add(new_assignment)
                db.session.commit()
                flash('Assignment created successfully!', 'success')
                return redirect(url_for('faculty.assignments'))
            except Exception as e:
                db.session.rollback()
                flash(f'An error occurred: {str(e)}', 'danger')
    
    return render_template('faculty/new_assignment.html', courses=courses)

@faculty_bp.route('/assignments/<int:assignment_id>/edit', methods=['GET', 'POST'])
@login_required
@faculty_required
def edit_assignment(assignment_id):
    assignment = Assignment.query.join(Course).filter(
        Assignment.id == assignment_id,
        Course.faculty_id == current_user.id
    ).first_or_404()
    
    courses = Course.query.filter_by(faculty_id=current_user.id).all()
    
    if request.method == 'POST':
        title = request.form.get('title')
        description = request.form.get('description')
        course_id = request.form.get('course_id')
        due_date_str = request.form.get('due_date')
        max_score = request.form.get('max_score')
        weight = request.form.get('weight')
        status = request.form.get('status')
        
        # Basic validation
        error = None
        if not title or not course_id or not due_date_str or not max_score:
            error = 'Required fields cannot be empty.'
        
        # Parse due date
        due_date = parse_date(due_date_str)
        if not due_date:
            error = 'Invalid due date format.'
        
        # Validate course
        course = Course.query.get(course_id)
        if not course or course.faculty_id != current_user.id:
            error = 'Invalid course selected.'
        
        if error:
            flash(error, 'danger')
        else:
            # Get assignment status
            try:
                status_enum = AssignmentStatus[status.upper()]
            except (KeyError, ValueError):
                status_enum = AssignmentStatus.DRAFT
            
            # Update assignment
            assignment.title = title
            assignment.description = description
            assignment.course_id = course_id
            assignment.due_date = due_date
            assignment.max_score = float(max_score)
            assignment.weight = float(weight) if weight else 1.0
            assignment.status = status_enum
            
            try:
                db.session.commit()
                flash('Assignment updated successfully!', 'success')
                return redirect(url_for('faculty.assignments'))
            except Exception as e:
                db.session.rollback()
                flash(f'An error occurred: {str(e)}', 'danger')
    
    return render_template('faculty/edit_assignment.html', 
                           assignment=assignment,
                           courses=courses)

@faculty_bp.route('/submissions')
@login_required
@faculty_required
def submissions():
    # Get filter parameters
    assignment_id = request.args.get('assignment_id', type=int)
    status = request.args.get('status')
    
    # Base query
    query = Submission.query.join(Assignment).join(Course).filter(Course.faculty_id == current_user.id)
    
    # Apply filters
    if assignment_id:
        query = query.filter(Submission.assignment_id == assignment_id)
    
    if status:
        try:
            status_enum = SubmissionStatus[status.upper()]
            query = query.filter(Submission.status == status_enum)
        except (KeyError, ValueError):
            # Invalid status, ignore this filter
            pass
    
    # Get all assignments for the filter dropdown
    assignments = Assignment.query.join(Course).filter(Course.faculty_id == current_user.id).all()
    
    # Get paginated results
    page = request.args.get('page', 1, type=int)
    per_page = 10
    submissions = query.order_by(Submission.submission_date.desc()).paginate(page=page, per_page=per_page)
    
    return render_template('faculty/submissions.html', 
                           submissions=submissions,
                           assignments=assignments,
                           current_assignment_id=assignment_id,
                           current_status=status)

@faculty_bp.route('/submissions/<int:submission_id>/grade', methods=['GET', 'POST'])
@login_required
@faculty_required
def grade_submission(submission_id):
    submission = Submission.query.join(Assignment).join(Course).filter(
        Submission.id == submission_id,
        Course.faculty_id == current_user.id
    ).first_or_404()
    
    # Check if already graded
    grade = Grade.query.filter_by(submission_id=submission_id).first()
    
    if request.method == 'POST':
        score = request.form.get('score')
        feedback = request.form.get('feedback')
        use_ai_suggestion = 'use_ai_suggestion' in request.form
        
        # Basic validation
        error = None
        if not score:
            error = 'Score is required.'
        
        if error:
            flash(error, 'danger')
        else:
            if grade:
                # Update existing grade
                grade.score = float(score)
                grade.feedback = feedback
                grade.graded_by = current_user.id
                grade.graded_at = datetime.now()
            else:
                # Create new grade
                grade = Grade(
                    submission_id=submission_id,
                    score=float(score),
                    feedback=feedback,
                    graded_by=current_user.id
                )
                db.session.add(grade)
            
            # Update submission status
            submission.status = SubmissionStatus.GRADED
            
            try:
                db.session.commit()
                flash('Submission graded successfully!', 'success')
                return redirect(url_for('faculty.submissions'))
            except Exception as e:
                db.session.rollback()
                flash(f'An error occurred: {str(e)}', 'danger')
    
    # Generate AI suggestions if not already available
    ai_suggestion = None
    if grade and grade.ai_score is not None:
        ai_suggestion = {
            'score': grade.ai_score,
            'feedback': grade.ai_feedback,
            'confidence': grade.ai_confidence
        }
    else:
        # Get assignment instructions for context
        assignment = submission.assignment
        
        if submission.content:
            # Analyze the submission content
            analysis = analyze_submission(
                submission.content,
                assignment.description
            )
            
            if analysis and analysis['score_recommendation'] is not None:
                ai_suggestion = {
                    'score': analysis['score_recommendation'],
                    'feedback': analysis['feedback'],
                    'confidence': analysis['confidence'],
                    'key_points': analysis.get('key_points', []),
                    'improvement_areas': analysis.get('improvement_areas', [])
                }
                
                # Store AI suggestion in database
                if grade:
                    grade.ai_score = analysis['score_recommendation']
                    grade.ai_feedback = analysis['feedback']
                    grade.ai_confidence = analysis['confidence']
                    db.session.commit()
    
    return render_template('faculty/grade_submission.html', 
                           submission=submission,
                           grade=grade,
                           ai_suggestion=ai_suggestion)

@faculty_bp.route('/analytics')
@login_required
@faculty_required
def analytics():
    # Get courses taught by the faculty
    courses = Course.query.filter_by(faculty_id=current_user.id).all()
    
    # Get selected course ID from query params
    course_id = request.args.get('course_id', type=int)
    
    course_analytics = None
    if course_id:
        course = Course.query.get(course_id)
        if course and course.faculty_id == current_user.id:
            course_analytics = calculate_course_analytics(course_id)
    
    return render_template('faculty/analytics.html',
                           courses=courses,
                           selected_course_id=course_id,
                           course_analytics=course_analytics)

@faculty_bp.route('/api/analyze_submission', methods=['POST'])
@login_required
@faculty_required
def api_analyze_submission():
    data = request.json
    submission_text = data.get('submission_text')
    assignment_instructions = data.get('assignment_instructions')
    
    if not submission_text or not assignment_instructions:
        return jsonify({'error': 'Missing required fields'}), 400
    
    analysis = analyze_submission(submission_text, assignment_instructions)
    return jsonify(analysis)
