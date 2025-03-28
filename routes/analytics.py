from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify
from flask_login import login_required, current_user
from sqlalchemy.exc import IntegrityError
from functools import wraps
from datetime import datetime, timedelta

from app import db
from models import User, Course, Assignment, Submission, Grade, RoleType, Analytics
from utils import get_user_courses, calculate_course_analytics, calculate_student_analytics
from ai_services import predict_student_performance

analytics_bp = Blueprint('analytics', __name__)

# Admin or faculty required decorator
def admin_or_faculty_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or (not current_user.is_admin() and not current_user.is_faculty()):
            flash('You do not have permission to access this page.', 'danger')
            return redirect(url_for('auth.index'))
        return f(*args, **kwargs)
    return decorated_function

@analytics_bp.route('/')
@login_required
def index():
    """Analytics dashboard - redirects based on user role."""
    if current_user.is_admin():
        return redirect(url_for('analytics.admin_dashboard'))
    elif current_user.is_faculty():
        return redirect(url_for('analytics.faculty_dashboard'))
    else:  # Student
        return redirect(url_for('analytics.student_dashboard'))

@analytics_bp.route('/admin')
@login_required
@admin_or_faculty_required
def admin_dashboard():
    """Analytics dashboard for admins."""
    # Get system-wide statistics
    total_users = User.query.count()
    total_faculty = User.query.join(User.role).filter(User.role.has(name=RoleType.FACULTY)).count()
    total_students = User.query.join(User.role).filter(User.role.has(name=RoleType.STUDENT)).count()
    total_courses = Course.query.count()
    total_assignments = Assignment.query.count()
    total_submissions = Submission.query.count()
    
    # Get active courses
    active_courses = Course.query.filter_by(is_active=True).count()
    
    # Get user registration trends
    today = datetime.utcnow()
    month_ago = today - timedelta(days=30)
    
    new_users = User.query.filter(User.created_at >= month_ago).count()
    
    # Get course activity
    course_activity = db.session.query(
        Course.id, Course.code, Course.title,
        db.func.count(Submission.id).label('submission_count')
    ).outerjoin(Assignment, Assignment.course_id == Course.id).outerjoin(
        Submission, Submission.assignment_id == Assignment.id
    ).group_by(Course.id).order_by(db.desc('submission_count')).limit(5).all()
    
    # Get faculty with most active courses
    faculty_activity = db.session.query(
        User.id, User.first_name, User.last_name,
        db.func.count(Course.id).label('course_count')
    ).join(Course, Course.faculty_id == User.id).group_by(User.id).order_by(db.desc('course_count')).limit(5).all()
    
    # Get assignment completion rates
    completion_rates = db.session.query(
        Course.id, Course.code,
        db.func.count(Assignment.id).label('total_assignments'),
        db.func.count(Submission.id).label('total_submissions')
    ).join(Assignment, Assignment.course_id == Course.id).outerjoin(
        Submission, Submission.assignment_id == Assignment.id
    ).group_by(Course.id).all()
    
    # Calculate completion percentages
    course_completion = []
    for rate in completion_rates:
        # Skip courses with no assignments
        if rate.total_assignments == 0:
            continue
            
        # Get number of students in course
        course = Course.query.get(rate.id)
        student_count = len(course.students)
        
        if student_count > 0 and rate.total_assignments > 0:
            # Potential total submissions if all students submitted all assignments
            potential_submissions = student_count * rate.total_assignments
            
            # Actual percentage
            percentage = (rate.total_submissions / potential_submissions) * 100
            
            course_completion.append({
                'course_code': rate.code,
                'completion_rate': percentage
            })
    
    # Sort by completion rate descending
    course_completion.sort(key=lambda x: x['completion_rate'], reverse=True)
    course_completion = course_completion[:5]  # Get top 5
    
    return render_template('analytics/admin_dashboard.html',
                          total_users=total_users,
                          total_faculty=total_faculty,
                          total_students=total_students,
                          total_courses=total_courses,
                          total_assignments=total_assignments,
                          total_submissions=total_submissions,
                          active_courses=active_courses,
                          new_users=new_users,
                          course_activity=course_activity,
                          faculty_activity=faculty_activity,
                          course_completion=course_completion)

@analytics_bp.route('/faculty')
@login_required
@admin_or_faculty_required
def faculty_dashboard():
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
        'assignment_stats': None,
        'grade_distribution': None,
        'student_performance': None,
        'submission_timing': None
    }
    
    if course:
        # Get assignments for this course
        assignments = Assignment.query.filter_by(course_id=course.id).all()
        
        # Get students for this course
        students = course.students
        
        # Assignment statistics
        assignment_stats = []
        for assignment in assignments:
            total_students = len(students)
            submissions = Submission.query.filter_by(assignment_id=assignment.id).count()
            graded = Submission.query.filter_by(
                assignment_id=assignment.id,
                status='GRADED'
            ).count()
            
            if total_students > 0:
                submission_rate = (submissions / total_students) * 100
            else:
                submission_rate = 0
                
            assignment_stats.append({
                'assignment': assignment.title,
                'submission_rate': submission_rate,
                'graded_count': graded,
                'total_submissions': submissions
            })
        
        analytics_data['assignment_stats'] = assignment_stats
        
        # Grade distribution
        grades = Grade.query.join(Submission).join(Assignment).filter(
            Assignment.course_id == course.id
        ).all()
        
        grade_distribution = {
            'A': 0,  # 90-100%
            'B': 0,  # 80-89%
            'C': 0,  # 70-79%
            'D': 0,  # 60-69%
            'F': 0   # <60%
        }
        
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
        for student in students:
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
    
    return render_template('analytics/faculty_dashboard.html',
                          courses=courses,
                          current_course=course,
                          analytics_data=analytics_data)

@analytics_bp.route('/student')
@login_required
def student_dashboard():
    """Analytics dashboard for students."""
    # Get enrolled courses
    courses = current_user.enrolled_courses
    
    # Get selected course
    course_id = request.args.get('course_id', type=int)
    if course_id:
        course = Course.query.get_or_404(course_id)
        if course not in courses:
            flash('You are not enrolled in this course.', 'danger')
            return redirect(url_for('analytics.student_dashboard'))
    elif courses:
        course = courses[0]
    else:
        course = None
    
    # Initialize analytics data
    analytics_data = {
        'grades': None,
        'performance_trend': None,
        'course_comparison': None,
        'time_management': None
    }
    
    if course:
        # Get grades for this course
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
        
        # Performance trend (all assignments in chronological order)
        trend_data = []
        
        assignments = Assignment.query.filter_by(
            course_id=course.id,
            status='PUBLISHED'
        ).order_by(Assignment.due_date).all()
        
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
        
        # Course comparison (compare performance across all courses)
        comparison_data = []
        
        for enrolled_course in courses:
            course_grades = Grade.query.join(Submission).join(Assignment).filter(
                Assignment.course_id == enrolled_course.id,
                Submission.student_id == current_user.id
            ).all()
            
            total_score = 0
            total_max = 0
            
            for grade in course_grades:
                total_score += grade.score
                total_max += grade.submission.assignment.max_score
            
            if total_max > 0:
                average_percentage = (total_score / total_max) * 100
            else:
                average_percentage = 0
                
            comparison_data.append({
                'course': enrolled_course.code,
                'average': average_percentage
            })
        
        analytics_data['course_comparison'] = comparison_data
        
        # Time management analysis
        time_management = {
            'early': 0,    # >24 hours before due date
            'ontime': 0,   # <24 hours before due date
            'late': 0      # after due date
        }
        
        submissions = Submission.query.join(Assignment).filter(
            Assignment.course_id == course.id,
            Submission.student_id == current_user.id
        ).all()
        
        for submission in submissions:
            time_diff = submission.assignment.due_date - submission.submission_date
            
            if time_diff.total_seconds() > 86400:  # More than 24 hours before
                time_management['early'] += 1
            elif time_diff.total_seconds() > 0:    # Before due date but <24 hours
                time_management['ontime'] += 1
            else:                                  # After due date
                time_management['late'] += 1
        
        analytics_data['time_management'] = time_management
    
    return render_template('analytics/student_dashboard.html',
                          courses=courses,
                          current_course=course,
                          analytics_data=analytics_data)

@analytics_bp.route('/api/course/<int:course_id>')
@login_required
def api_course_analytics(course_id):
    """API endpoint to get course analytics data."""
    course = Course.query.get_or_404(course_id)
    
    # Check if user has access to this course
    if not current_user.is_admin():
        if current_user.is_faculty():
            if course.faculty_id != current_user.id:
                return jsonify({'error': 'You do not have access to this course'}), 403
        else:  # Student
            if course not in current_user.enrolled_courses:
                return jsonify({'error': 'You are not enrolled in this course'}), 403
    
    try:
        analytics_data = calculate_course_analytics(course_id)
        return jsonify(analytics_data)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@analytics_bp.route('/api/student/<int:student_id>')
@login_required
def api_student_analytics(student_id):
    """API endpoint to get student analytics data."""
    student = User.query.get_or_404(student_id)
    
    # Check permissions
    if not current_user.is_admin() and not current_user.is_faculty() and current_user.id != student_id:
        return jsonify({'error': 'You do not have permission to view this data'}), 403
    
    try:
        analytics_data = calculate_student_analytics(student_id)
        return jsonify(analytics_data)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@analytics_bp.route('/api/predict/<int:course_id>', methods=['POST'])
@login_required
def api_predict_performance(course_id):
    """API endpoint to predict student performance in a course."""
    course = Course.query.get_or_404(course_id)
    
    # Check permissions
    if not current_user.is_admin() and not current_user.is_faculty() and course not in current_user.enrolled_courses:
        return jsonify({'error': 'You do not have permission to access this data'}), 403
    
    if not request.is_json:
        return jsonify({'error': 'Request must be JSON'}), 400
        
    data = request.get_json()
    
    student_id = data.get('student_id')
    
    if not student_id:
        return jsonify({'error': 'Student ID is required'}), 400
    
    # Check if student exists and user has permission to view data
    student = User.query.get_or_404(student_id)
    
    if not current_user.is_admin() and not current_user.is_faculty() and current_user.id != student_id:
        return jsonify({'error': 'You do not have permission to access this data'}), 403
    
    # Get grades data
    grades = Grade.query.join(Submission).join(Assignment).filter(
        Assignment.course_id == course_id,
        Submission.student_id == student_id
    ).all()
    
    grade_data = []
    for grade in grades:
        assignment = grade.submission.assignment
        grade_data.append({
            'assignment_id': assignment.id,
            'assignment_title': assignment.title,
            'score': grade.score,
            'max_score': assignment.max_score,
            'percentage': (grade.score / assignment.max_score) * 100,
            'weight': assignment.weight
        })
    
    try:
        prediction_data = predict_student_performance(student_id, course_id, {'grades': grade_data})
        return jsonify(prediction_data)
    except Exception as e:
        return jsonify({'error': str(e)}), 500