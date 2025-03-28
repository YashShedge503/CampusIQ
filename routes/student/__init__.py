from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from functools import wraps
from datetime import datetime, timedelta

from app import db
from models import User, Course, Assignment, Submission, Grade

student_bp = Blueprint('student_bp', __name__)

# Student required decorator
def student_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_student():
            flash('You do not have permission to access this page.', 'danger')
            return redirect(url_for('auth.index'))
        return f(*args, **kwargs)
    return decorated_function

@student_bp.route('/dashboard')
@login_required
@student_required
def dashboard():
    """Student dashboard page."""
    # Get enrolled courses
    courses = current_user.enrolled_courses
    
    # Get recent assignments
    recent_assignments = Assignment.query.join(Course).\
        filter(Course.id.in_([c.id for c in courses])).\
        order_by(Assignment.due_date.desc()).\
        limit(5).all()
    
    # Get recent submissions
    recent_submissions = Submission.query.filter_by(student_id=current_user.id).\
        order_by(Submission.submission_date.desc()).\
        limit(5).all()
    
    # Get upcoming assignments (due in the next 7 days)
    now = datetime.utcnow()
    next_week = now + timedelta(days=7)
    
    upcoming_assignments = Assignment.query.join(Course).\
        filter(Course.id.in_([c.id for c in courses])).\
        filter(Assignment.due_date > now, Assignment.due_date <= next_week).\
        order_by(Assignment.due_date).all()
    
    # Get grade statistics
    grades = Grade.query.join(Submission).filter(Submission.student_id == current_user.id).all()
    
    grade_stats = {
        'total': len(grades),
        'average': 0,
        'highest': 0,
        'lowest': 100
    }
    
    if grades:
        total_score_percentage = 0
        for grade in grades:
            percentage = (grade.score / grade.submission.assignment.max_score) * 100
            total_score_percentage += percentage
            
            if percentage > grade_stats['highest']:
                grade_stats['highest'] = percentage
                
            if percentage < grade_stats['lowest']:
                grade_stats['lowest'] = percentage
            
        grade_stats['average'] = total_score_percentage / len(grades)
    else:
        grade_stats['lowest'] = 0
    
    return render_template('student/dashboard.html',
                          courses=courses,
                          recent_assignments=recent_assignments,
                          recent_submissions=recent_submissions,
                          upcoming_assignments=upcoming_assignments,
                          grade_stats=grade_stats)

@student_bp.route('/assignments')
@login_required
@student_required
def assignments():
    """View all assignments for student's courses."""
    # Get enrolled courses
    courses = current_user.enrolled_courses
    course_ids = [c.id for c in courses]
    
    # Get filter parameters
    course_id = request.args.get('course_id', type=int)
    status = request.args.get('status')
    
    # Base query
    query = Assignment.query.join(Course).filter(Course.id.in_(course_ids))
    
    # Apply filters
    if course_id:
        query = query.filter(Assignment.course_id == course_id)
        
    if status == 'upcoming':
        query = query.filter(Assignment.due_date > datetime.utcnow())
    elif status == 'past':
        query = query.filter(Assignment.due_date <= datetime.utcnow())
    
    # Get assignments
    assignments = query.order_by(Assignment.due_date.desc()).all()
    
    # Get submission status for each assignment
    for assignment in assignments:
        submission = Submission.query.filter_by(
            assignment_id=assignment.id,
            student_id=current_user.id
        ).first()
        
        assignment.submission_status = submission.status.value if submission else 'Not Submitted'
        assignment.submission = submission
    
    return render_template('student/assignments.html',
                          assignments=assignments,
                          courses=courses,
                          current_course_id=course_id,
                          current_status=status)

@student_bp.route('/submissions')
@login_required
@student_required
def submissions():
    """View all submissions by the student."""
    # Get filter parameters
    course_id = request.args.get('course_id', type=int)
    status = request.args.get('status')
    
    # Base query
    query = Submission.query.filter_by(student_id=current_user.id)
    
    # Apply filters
    if course_id:
        query = query.join(Assignment).filter(Assignment.course_id == course_id)
        
    if status:
        query = query.filter(Submission.status == status)
    
    # Get submissions
    submissions = query.order_by(Submission.submission_date.desc()).all()
    
    # Get courses for filter
    courses = current_user.enrolled_courses
    
    # Get status options for filter
    from models import SubmissionStatus
    status_options = [status.value for status in SubmissionStatus]
    
    return render_template('student/submissions.html',
                          submissions=submissions,
                          courses=courses,
                          status_options=status_options,
                          current_course_id=course_id,
                          current_status=status)

@student_bp.route('/grades')
@login_required
@student_required
def grades():
    """View all grades for the student."""
    # Get enrolled courses
    courses = current_user.enrolled_courses
    
    # Get filter parameters
    course_id = request.args.get('course_id', type=int)
    
    # Base query
    query = Grade.query.join(Submission).filter(Submission.student_id == current_user.id)
    
    # Apply filters
    if course_id:
        query = query.join(Assignment).filter(Assignment.course_id == course_id)
    
    # Get grades
    grades = query.order_by(Grade.graded_at.desc()).all()
    
    # Get grade statistics by course
    course_stats = {}
    
    for course in courses:
        course_grades = Grade.query.join(Submission).join(Assignment).filter(
            Submission.student_id == current_user.id,
            Assignment.course_id == course.id
        ).all()
        
        stats = {
            'total': len(course_grades),
            'average': 0,
            'highest': 0,
            'lowest': 100 if course_grades else 0
        }
        
        if course_grades:
            total_score_percentage = 0
            for grade in course_grades:
                percentage = (grade.score / grade.submission.assignment.max_score) * 100
                total_score_percentage += percentage
                
                if percentage > stats['highest']:
                    stats['highest'] = percentage
                    
                if percentage < stats['lowest']:
                    stats['lowest'] = percentage
                
            stats['average'] = total_score_percentage / len(course_grades)
        
        course_stats[course.id] = stats
    
    return render_template('student/grades.html',
                          grades=grades,
                          courses=courses,
                          course_stats=course_stats,
                          current_course_id=course_id)