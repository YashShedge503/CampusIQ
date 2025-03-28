from flask import Blueprint, render_template, redirect, url_for, flash, request, abort, jsonify
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
from sqlalchemy.exc import IntegrityError
from functools import wraps
from datetime import datetime, timedelta
import os
import json

from app import db
from models import User, RoleType, Course, Assignment, Submission, Grade, SubmissionStatus, AssignmentStatus
from utils import allowed_file, save_file, parse_date
from ai_services import analyze_submission, predict_student_performance

faculty_bp = Blueprint('faculty', __name__)

# Faculty required decorator
def faculty_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_faculty():
            abort(403)
        return f(*args, **kwargs)
    return decorated_function

@faculty_bp.route('/dashboard')
@login_required
@faculty_required
def dashboard():
    """Faculty dashboard page."""
    # Get current faculty's courses
    courses = Course.query.filter_by(faculty_id=current_user.id).all()
    
    # Get recent assignments
    assignments = Assignment.query.join(Course).filter(
        Course.faculty_id == current_user.id,
        Assignment.status == AssignmentStatus.PUBLISHED
    ).order_by(Assignment.due_date.desc()).limit(5).all()
    
    # Get recent submissions to grade
    submissions = Submission.query.join(Assignment).join(Course).filter(
        Course.faculty_id == current_user.id,
        Submission.status == SubmissionStatus.SUBMITTED
    ).order_by(Submission.submission_date.desc()).limit(10).all()
    
    # Get course statistics
    course_stats = []
    for course in courses:
        # Get number of students
        student_count = len(course.students)
        
        # Get assignment count
        assignment_count = Assignment.query.filter_by(course_id=course.id).count()
        
        # Get submission statistics
        total_submissions = Submission.query.join(Assignment).filter(
            Assignment.course_id == course.id
        ).count()
        
        graded_submissions = Submission.query.join(Assignment).filter(
            Assignment.course_id == course.id,
            Submission.status.in_([SubmissionStatus.GRADED, SubmissionStatus.RETURNED])
        ).count()
        
        pending_submissions = Submission.query.join(Assignment).filter(
            Assignment.course_id == course.id,
            Submission.status == SubmissionStatus.SUBMITTED
        ).count()
        
        course_stats.append({
            'course': course,
            'student_count': student_count,
            'assignment_count': assignment_count,
            'total_submissions': total_submissions,
            'graded_submissions': graded_submissions,
            'pending_submissions': pending_submissions
        })
    
    # Get upcoming deadlines
    today = datetime.utcnow()
    upcoming_deadlines = Assignment.query.join(Course).filter(
        Course.faculty_id == current_user.id,
        Assignment.due_date > today,
        Assignment.due_date <= today + timedelta(days=7)
    ).order_by(Assignment.due_date).all()
    
    return render_template('faculty/dashboard.html', 
                          courses=courses,
                          assignments=assignments,
                          submissions=submissions,
                          course_stats=course_stats,
                          upcoming_deadlines=upcoming_deadlines)

@faculty_bp.route('/assignments')
@login_required
@faculty_required
def assignments():
    """View all assignments for faculty's courses."""
    # Get filter parameters
    course_id = request.args.get('course_id', type=int)
    status = request.args.get('status')
    search = request.args.get('search', '')
    
    # Filter assignments
    query = Assignment.query.join(Course).filter(Course.faculty_id == current_user.id)
    
    if course_id:
        query = query.filter(Assignment.course_id == course_id)
    
    if status:
        query = query.filter(Assignment.status == AssignmentStatus[status.upper()])
    
    if search:
        query = query.filter(Assignment.title.ilike(f'%{search}%'))
    
    # Get assignments with pagination
    page = request.args.get('page', 1, type=int)
    per_page = 10
    assignments = query.order_by(Assignment.due_date.desc()).paginate(page=page, per_page=per_page)
    
    # Get courses for filter options
    courses = Course.query.filter_by(faculty_id=current_user.id).all()
    
    return render_template('faculty/assignments.html', 
                          assignments=assignments, 
                          courses=courses, 
                          current_course_id=course_id,
                          current_status=status,
                          search=search)

@faculty_bp.route('/assignments/new', methods=['GET', 'POST'])
@login_required
@faculty_required
def new_assignment():
    """Create a new assignment."""
    if request.method == 'POST':
        title = request.form.get('title')
        description = request.form.get('description')
        course_id = request.form.get('course_id')
        due_date_str = request.form.get('due_date')
        max_score = request.form.get('max_score', 100, type=float)
        weight = request.form.get('weight', 1.0, type=float)
        status_str = request.form.get('status', 'DRAFT')
        
        # Parse due date
        due_date = parse_date(due_date_str)
        if not due_date:
            flash('Invalid due date format.', 'danger')
            return redirect(url_for('faculty.new_assignment'))
        
        # Validate input
        if not title or not description or not course_id:
            flash('Title, description, and course are required.', 'danger')
            return redirect(url_for('faculty.new_assignment'))
            
        # Verify course belongs to faculty
        course = Course.query.filter_by(id=course_id, faculty_id=current_user.id).first()
        if not course:
            flash('Invalid course selection.', 'danger')
            return redirect(url_for('faculty.new_assignment'))
        
        # Create new assignment
        status = AssignmentStatus[status_str]
        new_assignment = Assignment(
            title=title,
            description=description,
            course_id=course_id,
            due_date=due_date,
            max_score=max_score,
            weight=weight,
            status=status
        )
        
        try:
            db.session.add(new_assignment)
            db.session.commit()
            flash(f'Assignment "{title}" created successfully.', 'success')
            
            if status == AssignmentStatus.PUBLISHED:
                flash('Assignment published and visible to students.', 'info')
                
            return redirect(url_for('faculty.assignments'))
        except IntegrityError:
            db.session.rollback()
            flash('An error occurred while creating the assignment.', 'danger')
    
    # Get courses for the form
    courses = Course.query.filter_by(faculty_id=current_user.id).all()
    
    return render_template('faculty/new_assignment.html', courses=courses)

@faculty_bp.route('/assignments/<int:assignment_id>/edit', methods=['GET', 'POST'])
@login_required
@faculty_required
def edit_assignment(assignment_id):
    """Edit an existing assignment."""
    # Get the assignment
    assignment = Assignment.query.join(Course).filter(
        Assignment.id == assignment_id,
        Course.faculty_id == current_user.id
    ).first_or_404()
    
    if request.method == 'POST':
        title = request.form.get('title')
        description = request.form.get('description')
        course_id = request.form.get('course_id')
        due_date_str = request.form.get('due_date')
        max_score = request.form.get('max_score', 100, type=float)
        weight = request.form.get('weight', 1.0, type=float)
        status_str = request.form.get('status', 'DRAFT')
        
        # Parse due date
        due_date = parse_date(due_date_str)
        if not due_date:
            flash('Invalid due date format.', 'danger')
            return redirect(url_for('faculty.edit_assignment', assignment_id=assignment_id))
        
        # Validate input
        if not title or not description or not course_id:
            flash('Title, description, and course are required.', 'danger')
            return redirect(url_for('faculty.edit_assignment', assignment_id=assignment_id))
            
        # Verify course belongs to faculty
        course = Course.query.filter_by(id=course_id, faculty_id=current_user.id).first()
        if not course:
            flash('Invalid course selection.', 'danger')
            return redirect(url_for('faculty.edit_assignment', assignment_id=assignment_id))
        
        # Update assignment
        assignment.title = title
        assignment.description = description
        assignment.course_id = course_id
        assignment.due_date = due_date
        assignment.max_score = max_score
        assignment.weight = weight
        assignment.status = AssignmentStatus[status_str]
        
        try:
            db.session.commit()
            flash(f'Assignment "{title}" updated successfully.', 'success')
            
            if assignment.status == AssignmentStatus.PUBLISHED:
                flash('Assignment is now published and visible to students.', 'info')
                
            return redirect(url_for('faculty.assignments'))
        except IntegrityError:
            db.session.rollback()
            flash('An error occurred while updating the assignment.', 'danger')
    
    # Get courses for the form
    courses = Course.query.filter_by(faculty_id=current_user.id).all()
    
    return render_template('faculty/edit_assignment.html', 
                          assignment=assignment, 
                          courses=courses)

@faculty_bp.route('/submissions')
@login_required
@faculty_required
def submissions():
    """View all submissions for faculty's assignments."""
    # Get filter parameters
    course_id = request.args.get('course_id', type=int)
    assignment_id = request.args.get('assignment_id', type=int)
    status = request.args.get('status')
    student_id = request.args.get('student_id', type=int)
    
    # Base query for submissions
    query = Submission.query.join(Assignment).join(Course).filter(
        Course.faculty_id == current_user.id
    )
    
    # Apply filters
    if course_id:
        query = query.filter(Course.id == course_id)
        
        # Get assignments for this course for the dropdown
        assignments = Assignment.query.filter_by(course_id=course_id).all()
    else:
        assignments = []
    
    if assignment_id:
        query = query.filter(Assignment.id == assignment_id)
    
    if status:
        query = query.filter(Submission.status == SubmissionStatus[status.upper()])
    
    if student_id:
        query = query.filter(Submission.student_id == student_id)
    
    # Get submissions with pagination
    page = request.args.get('page', 1, type=int)
    per_page = 10
    submissions = query.order_by(Submission.submission_date.desc()).paginate(page=page, per_page=per_page)
    
    # Get courses for filter options
    courses = Course.query.filter_by(faculty_id=current_user.id).all()
    
    # Get students if a course is selected
    if course_id:
        course = Course.query.get_or_404(course_id)
        students = course.students
    else:
        students = []
    
    return render_template('faculty/submissions.html', 
                          submissions=submissions,
                          courses=courses,
                          assignments=assignments,
                          students=students,
                          current_course_id=course_id,
                          current_assignment_id=assignment_id,
                          current_status=status,
                          current_student_id=student_id)

@faculty_bp.route('/submissions/<int:submission_id>/grade', methods=['GET', 'POST'])
@login_required
@faculty_required
def grade_submission(submission_id):
    """Grade a student submission."""
    # Get the submission
    submission = Submission.query.join(Assignment).join(Course).filter(
        Submission.id == submission_id,
        Course.faculty_id == current_user.id
    ).first_or_404()
    
    # Check if already graded
    existing_grade = Grade.query.filter_by(submission_id=submission_id).first()
    
    if request.method == 'POST':
        score = request.form.get('score', type=float)
        feedback = request.form.get('feedback')
        
        # Validate input
        if score is None:
            flash('Score is required.', 'danger')
            return redirect(url_for('faculty.grade_submission', submission_id=submission_id))
            
        if score < 0 or score > submission.assignment.max_score:
            flash(f'Score must be between 0 and {submission.assignment.max_score}.', 'danger')
            return redirect(url_for('faculty.grade_submission', submission_id=submission_id))
        
        # Create or update grade
        if existing_grade:
            existing_grade.score = score
            existing_grade.feedback = feedback
            existing_grade.graded_by = current_user.id
            existing_grade.graded_at = datetime.utcnow()
        else:
            new_grade = Grade(
                submission_id=submission_id,
                score=score,
                feedback=feedback,
                graded_by=current_user.id
            )
            db.session.add(new_grade)
        
        # Update submission status
        submission.status = SubmissionStatus.GRADED
        
        try:
            db.session.commit()
            flash('Submission graded successfully.', 'success')
            return redirect(url_for('faculty.submissions'))
        except IntegrityError:
            db.session.rollback()
            flash('An error occurred while grading the submission.', 'danger')
    
    # Get AI analysis if available
    ai_analysis = None
    if submission.content:
        try:
            ai_analysis = analyze_submission(
                submission.content, 
                submission.assignment.description
            )
        except Exception as e:
            flash(f'AI analysis error: {str(e)}', 'warning')
            
    return render_template('faculty/grade_submission.html', 
                          submission=submission,
                          existing_grade=existing_grade,
                          ai_analysis=ai_analysis)

@faculty_bp.route('/analytics')
@login_required
@faculty_required
def analytics():
    """Analytics dashboard for faculty."""
    # Get courses taught by this faculty
    courses = Course.query.filter_by(faculty_id=current_user.id).all()
    
    # Get selected course
    course_id = request.args.get('course_id', type=int)
    if course_id:
        course = Course.query.filter_by(id=course_id, faculty_id=current_user.id).first_or_404()
    elif courses:
        course = courses[0]
    else:
        course = None
    
    # Initialize analytics data
    analytics_data = {
        'assignment_completion': None,
        'grade_distribution': None,
        'student_performance': None,
        'submission_timing': None
    }
    
    if course:
        # Get assignments for this course
        assignments = Assignment.query.filter_by(course_id=course.id).all()
        
        # Assignment completion rate
        assignment_data = []
        for assignment in assignments:
            total_students = len(course.students)
            submitted = Submission.query.filter_by(assignment_id=assignment.id).count()
            
            if total_students > 0:
                completion_rate = (submitted / total_students) * 100
            else:
                completion_rate = 0
                
            assignment_data.append({
                'name': assignment.title,
                'completion_rate': completion_rate
            })
        
        analytics_data['assignment_completion'] = assignment_data
        
        # Grade distribution
        grade_distribution = {
            'A': 0,  # 90-100%
            'B': 0,  # 80-89%
            'C': 0,  # 70-79%
            'D': 0,  # 60-69%
            'F': 0   # <60%
        }
        
        grades = Grade.query.join(Submission).join(Assignment).filter(
            Assignment.course_id == course.id
        ).all()
        
        for grade in grades:
            percentage = (grade.score / grade.submission.assignment.max_score) * 100
            
            if percentage >= 90:
                grade_distribution['A'] += 1
            elif percentage >= 80:
                grade_distribution['B'] += 1
            elif percentage >= 70:
                grade_distribution['C'] += 1
            elif percentage >= 60:
                grade_distribution['D'] += 1
            else:
                grade_distribution['F'] += 1
        
        analytics_data['grade_distribution'] = grade_distribution
        
        # Student performance
        student_performance = []
        for student in course.students:
            student_grades = Grade.query.join(Submission).join(Assignment).filter(
                Assignment.course_id == course.id,
                Submission.student_id == student.id
            ).all()
            
            total_score = 0
            total_max = 0
            
            for grade in student_grades:
                total_score += grade.score
                total_max += grade.submission.assignment.max_score
            
            if total_max > 0:
                average_percentage = (total_score / total_max) * 100
            else:
                average_percentage = 0
                
            student_performance.append({
                'name': f"{student.first_name} {student.last_name}",
                'average': average_percentage
            })
        
        analytics_data['student_performance'] = student_performance
        
        # Submission timing analysis
        submission_timing = {
            'early': 0,    # >24 hours before due date
            'ontime': 0,   # <24 hours before due date
            'late': 0      # after due date
        }
        
        submissions = Submission.query.join(Assignment).filter(
            Assignment.course_id == course.id
        ).all()
        
        for submission in submissions:
            time_diff = submission.assignment.due_date - submission.submission_date
            
            if time_diff.total_seconds() > 86400:  # More than 24 hours before
                submission_timing['early'] += 1
            elif time_diff.total_seconds() > 0:    # Before due date but <24 hours
                submission_timing['ontime'] += 1
            else:                                  # After due date
                submission_timing['late'] += 1
        
        analytics_data['submission_timing'] = submission_timing
    
    return render_template('faculty/analytics.html', 
                          courses=courses, 
                          current_course=course,
                          analytics_data=analytics_data)

@faculty_bp.route('/api/analyze-submission', methods=['POST'])
@login_required
@faculty_required
def api_analyze_submission():
    """API endpoint to analyze a submission with AI."""
    if not request.is_json:
        return jsonify({'error': 'Request must be JSON'}), 400
        
    data = request.get_json()
    
    submission_text = data.get('submission_text')
    instructions = data.get('instructions')
    
    if not submission_text or not instructions:
        return jsonify({'error': 'Both submission_text and instructions are required'}), 400
    
    try:
        analysis = analyze_submission(submission_text, instructions)
        return jsonify(analysis)
    except Exception as e:
        return jsonify({'error': str(e)}), 500