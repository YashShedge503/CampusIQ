from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from functools import wraps
from app import db
from models import User, Course, Assignment, Submission, Grade, Analytics, Role, RoleType
from utils import calculate_course_analytics, calculate_student_analytics, get_course_progression
from ai_services import predict_student_performance

analytics_bp = Blueprint('analytics', __name__)

# Authorization decorators
def admin_or_faculty_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or (not current_user.is_admin() and not current_user.is_faculty()):
            flash("You don't have permission to access the analytics dashboard.", "danger")
            return redirect(url_for('auth.login'))
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
    # Get basic stats
    total_students = User.query.join(Role).filter(Role.name == RoleType.STUDENT).count()
    total_faculty = User.query.join(Role).filter(Role.name == RoleType.FACULTY).count()
    total_courses = Course.query.count()
    total_assignments = Assignment.query.count()
    total_submissions = Submission.query.count()
    
    # Get course completion stats
    courses = Course.query.all()
    course_data = []
    for course in courses:
        course_info = {
            'id': course.id,
            'code': course.code,
            'title': course.title,
            'student_count': len(course.students),
            'assignment_count': len(course.assignments)
        }
        
        # Calculate assignment completion rate
        total_possible_submissions = course_info['student_count'] * course_info['assignment_count']
        if total_possible_submissions > 0:
            actual_submissions = Submission.query.join(Assignment).filter(
                Assignment.course_id == course.id
            ).count()
            course_info['completion_rate'] = (actual_submissions / total_possible_submissions) * 100
        else:
            course_info['completion_rate'] = 0
        
        # Calculate average grade
        grades = Grade.query.join(Submission).join(Assignment).filter(
            Assignment.course_id == course.id
        ).all()
        
        if grades:
            total_score = sum([g.score for g in grades])
            course_info['avg_grade'] = total_score / len(grades)
        else:
            course_info['avg_grade'] = None
            
        course_data.append(course_info)
    
    # Get top performing students
    top_students = db.session.query(
        User, db.func.avg(Grade.score).label('avg_score')
    ).join(Submission, User.id == Submission.student_id
    ).join(Grade, Submission.id == Grade.submission_id
    ).group_by(User.id
    ).order_by(db.desc('avg_score')
    ).limit(10).all()
    
    return render_template('analytics/dashboard.html',
                           is_admin=True,
                           total_students=total_students,
                           total_faculty=total_faculty,
                           total_courses=total_courses,
                           total_assignments=total_assignments,
                           total_submissions=total_submissions,
                           course_data=course_data,
                           top_students=top_students)

@analytics_bp.route('/faculty')
@login_required
@admin_or_faculty_required
def faculty_dashboard():
    """Analytics dashboard for faculty."""
    # Get courses taught by the faculty
    courses = Course.query.filter_by(faculty_id=current_user.id).all()
    
    # Get selected course ID from query params
    course_id = request.args.get('course_id', type=int)
    
    # If no course selected and faculty has courses, select the first one
    if not course_id and courses:
        course_id = courses[0].id
    
    # Get course analytics
    course_analytics = None
    if course_id:
        course = Course.query.get(course_id)
        if course and (current_user.is_admin() or course.faculty_id == current_user.id):
            course_analytics = calculate_course_analytics(course_id)
    
    # Get student progression data if a course is selected
    student_progression = None
    if course_id:
        student_progression = get_course_progression(course_id)
    
    return render_template('analytics/dashboard.html',
                           is_admin=False,
                           courses=courses,
                           selected_course_id=course_id,
                           course_analytics=course_analytics,
                           student_progression=student_progression)

@analytics_bp.route('/student')
@login_required
def student_dashboard():
    """Analytics dashboard for students."""
    if not current_user.is_student():
        flash("Student analytics are only available to student accounts.", "warning")
        return redirect(url_for('analytics.index'))
    
    # Get student analytics data
    analytics_data = calculate_student_analytics(current_user.id)
    
    # Get all enrolled courses for the dropdown
    courses = current_user.enrolled_courses
    
    # Get selected course ID from query params
    course_id = request.args.get('course_id', type=int)
    
    # Get course-specific analytics
    course_specific_data = None
    selected_course = None
    performance_prediction = None
    
    if course_id:
        # Check if student is enrolled in this course
        course = Course.query.get(course_id)
        if course and course in courses:
            selected_course = course
            
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
            
            # Get performance prediction
            if grades_data:
                performance_prediction = predict_student_performance(current_user.id, course_id, grades_data)
            
            # Filter course-specific data
            for course_perf in analytics_data.get('course_performance', []):
                if course_perf['course_id'] == course_id:
                    course_specific_data = course_perf
                    break
    
    return render_template('analytics/student_performance.html',
                           analytics=analytics_data,
                           courses=courses,
                           selected_course_id=course_id,
                           selected_course=selected_course,
                           course_specific_data=course_specific_data,
                           performance_prediction=performance_prediction)

@analytics_bp.route('/api/course/<int:course_id>')
@login_required
@admin_or_faculty_required
def api_course_analytics(course_id):
    """API endpoint to get course analytics data."""
    course = Course.query.get_or_404(course_id)
    
    # Check permission
    if not current_user.is_admin() and course.faculty_id != current_user.id:
        return jsonify({'error': 'You do not have permission to view this course\'s analytics'}), 403
    
    analytics = calculate_course_analytics(course_id)
    return jsonify(analytics)

@analytics_bp.route('/api/student/<int:student_id>')
@login_required
def api_student_analytics(student_id):
    """API endpoint to get student analytics data."""
    # Check permission
    if not current_user.is_admin() and not current_user.is_faculty() and current_user.id != student_id:
        return jsonify({'error': 'You do not have permission to view this student\'s analytics'}), 403
    
    # If faculty, check if student is in one of their courses
    if current_user.is_faculty() and current_user.id != student_id:
        student = User.query.get_or_404(student_id)
        student_in_course = False
        for course in student.enrolled_courses:
            if course.faculty_id == current_user.id:
                student_in_course = True
                break
        
        if not student_in_course:
            return jsonify({'error': 'This student is not enrolled in any of your courses'}), 403
    
    analytics = calculate_student_analytics(student_id)
    return jsonify(analytics)

@analytics_bp.route('/api/predict/<int:course_id>')
@login_required
def api_predict_performance(course_id):
    """API endpoint to predict student performance in a course."""
    course = Course.query.get_or_404(course_id)
    
    # If student, can only predict own performance
    if current_user.is_student():
        student_id = current_user.id
        
        # Check if enrolled in course
        if course not in current_user.enrolled_courses:
            return jsonify({'error': 'You are not enrolled in this course'}), 403
    
    # If faculty, must be teaching this course
    elif current_user.is_faculty() and course.faculty_id != current_user.id:
        return jsonify({'error': 'You are not teaching this course'}), 403
    
    # If admin or faculty, need to specify student_id
    if current_user.is_admin() or current_user.is_faculty():
        student_id = request.args.get('student_id', type=int)
        if not student_id:
            return jsonify({'error': 'Student ID is required'}), 400
    
    # Get grades for this student in this course
    grades_data = []
    submissions = Submission.query.join(Assignment).filter(
        Submission.student_id == student_id,
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
    
    prediction = predict_student_performance(student_id, course_id, grades_data)
    return jsonify(prediction)
