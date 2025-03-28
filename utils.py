import os
import re
import csv
import uuid
import json
import pandas as pd
from datetime import datetime, timedelta
from werkzeug.utils import secure_filename
from flask import current_app, flash
from models import User, Course, Assignment, Submission, Grade, Material, Schedule, RoleType
from app import db

def allowed_file(filename):
    """Check if a file extension is allowed."""
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in current_app.config['ALLOWED_EXTENSIONS']

def save_file(file, subfolder=''):
    """Save a file to the server with a secure name."""
    if file and allowed_file(file.filename):
        # Create a unique filename
        filename = secure_filename(file.filename)
        unique_filename = f"{uuid.uuid4().hex}_{filename}"
        
        # Create upload directory if it doesn't exist
        upload_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], subfolder)
        os.makedirs(upload_dir, exist_ok=True)
        
        # Save the file
        file_path = os.path.join(upload_dir, unique_filename)
        file.save(file_path)
        
        return file_path
    return None

def parse_date(date_string, default=None):
    """Parse a date string into a datetime object."""
    if not date_string:
        return default
    
    formats = [
        '%Y-%m-%d',           # 2023-01-15
        '%d/%m/%Y',           # 15/01/2023
        '%m/%d/%Y',           # 01/15/2023
        '%Y-%m-%d %H:%M:%S',  # 2023-01-15 14:30:00
        '%d/%m/%Y %H:%M',     # 15/01/2023 14:30
        '%m/%d/%Y %H:%M',     # 01/15/2023 14:30
    ]
    
    for fmt in formats:
        try:
            return datetime.strptime(date_string, fmt)
        except ValueError:
            continue
    
    return default

def get_user_courses(user):
    """Get courses based on user role."""
    if user.is_admin():
        return Course.query.all()
    elif user.is_faculty():
        return Course.query.filter_by(faculty_id=user.id).all()
    else:
        return user.enrolled_courses
        
def calculate_course_analytics(course_id):
    """Calculate analytics for a specific course."""
    analytics = {}
    
    # Get course data
    course = Course.query.get(course_id)
    if not course:
        return analytics
    
    # Get all assignments for the course
    assignments = Assignment.query.filter_by(course_id=course_id).all()
    assignment_count = len(assignments)
    analytics['assignment_count'] = assignment_count
    
    # Calculate average grade for each assignment
    assignment_analytics = []
    overall_avg_score = 0
    total_submissions = 0
    
    for assignment in assignments:
        submissions = Submission.query.filter_by(assignment_id=assignment.id).all()
        submission_count = len(submissions)
        
        # Skip assignments with no submissions
        if submission_count == 0:
            assignment_analytics.append({
                'id': assignment.id,
                'title': assignment.title,
                'submission_count': 0,
                'avg_score': None,
                'max_score': assignment.max_score,
                'late_submissions': 0
            })
            continue
        
        # Calculate statistics
        graded_submissions = [s for s in submissions if s.grade is not None]
        grades = [s.grade.score for s in graded_submissions]
        late_submissions = sum(1 for s in submissions if s.is_late())
        
        avg_score = sum(grades) / len(grades) if grades else None
        
        if avg_score is not None:
            overall_avg_score += sum(grades)
            total_submissions += len(grades)
        
        assignment_analytics.append({
            'id': assignment.id,
            'title': assignment.title,
            'submission_count': submission_count,
            'graded_count': len(graded_submissions),
            'avg_score': avg_score,
            'max_score': assignment.max_score,
            'late_submissions': late_submissions
        })
    
    analytics['assignment_details'] = assignment_analytics
    analytics['overall_avg_score'] = overall_avg_score / total_submissions if total_submissions > 0 else None
    
    # Student performance
    students = course.students
    student_analytics = []
    
    for student in students:
        student_submissions = Submission.query.join(Assignment).filter(
            Submission.student_id == student.id,
            Assignment.course_id == course_id
        ).all()
        
        submission_count = len(student_submissions)
        graded_submissions = [s for s in student_submissions if s.grade is not None]
        
        if graded_submissions:
            avg_grade = sum(s.grade.score for s in graded_submissions) / len(graded_submissions)
        else:
            avg_grade = None
        
        student_analytics.append({
            'id': student.id,
            'name': student.get_full_name(),
            'submission_count': submission_count,
            'assignment_count': assignment_count,
            'completion_rate': (submission_count / assignment_count * 100) if assignment_count > 0 else 0,
            'avg_grade': avg_grade
        })
    
    analytics['student_performance'] = student_analytics
    
    return analytics

def calculate_student_analytics(student_id):
    """Calculate analytics for a specific student."""
    analytics = {}
    
    # Get student
    student = User.query.get(student_id)
    if not student or not student.is_student():
        return analytics
    
    # Get all courses the student is enrolled in
    courses = student.enrolled_courses
    analytics['enrolled_courses'] = [{'id': c.id, 'code': c.code, 'title': c.title} for c in courses]
    
    # Calculate performance per course
    course_performance = []
    overall_grades = []
    
    for course in courses:
        assignments = Assignment.query.filter_by(course_id=course.id).all()
        submissions = Submission.query.join(Assignment).filter(
            Submission.student_id == student_id,
            Assignment.course_id == course.id
        ).all()
        
        submission_count = len(submissions)
        assignment_count = len(assignments)
        completion_rate = (submission_count / assignment_count * 100) if assignment_count > 0 else 0
        
        # Calculate average grade
        graded_submissions = [s for s in submissions if s.grade is not None]
        if graded_submissions:
            grades = [s.grade.score for s in graded_submissions]
            avg_grade = sum(grades) / len(grades)
            overall_grades.extend(grades)
        else:
            avg_grade = None
        
        course_performance.append({
            'course_id': course.id,
            'course_code': course.code,
            'course_title': course.title,
            'assignment_count': assignment_count,
            'submission_count': submission_count,
            'completion_rate': completion_rate,
            'avg_grade': avg_grade
        })
    
    analytics['course_performance'] = course_performance
    analytics['overall_avg_grade'] = sum(overall_grades) / len(overall_grades) if overall_grades else None
    
    # Recent activity
    recent_submissions = Submission.query.filter_by(student_id=student_id).order_by(Submission.submission_date.desc()).limit(10).all()
    analytics['recent_submissions'] = [{
        'id': s.id,
        'assignment_title': s.assignment.title,
        'course_code': s.assignment.course.code,
        'submission_date': s.submission_date,
        'status': s.status.value,
        'is_late': s.is_late(),
        'grade': s.grade.score if s.grade else None
    } for s in recent_submissions]
    
    return analytics

def generate_schedule_suggestions(user_id, start_date=None, end_date=None):
    """Generate schedule suggestions based on user workload and availability."""
    user = User.query.get(user_id)
    if not user:
        return []
    
    # Set default date range if not provided
    if not start_date:
        start_date = datetime.now()
    if not end_date:
        end_date = start_date + timedelta(days=30)
    
    suggestions = []
    
    # For faculty: suggest office hours and grading sessions
    if user.is_faculty():
        courses = Course.query.filter_by(faculty_id=user_id).all()
        
        for course in courses:
            # Suggest office hours
            suggestions.append({
                'type': 'office_hours',
                'title': f"Office Hours for {course.code}",
                'description': f"Weekly office hours for {course.title}",
                'course_id': course.id,
                'suggested_times': [
                    start_date.replace(hour=14, minute=0, second=0, microsecond=0) + timedelta(days=i)
                    for i in range(7) if i != 5 and i != 6  # Weekdays only
                ][:2]  # Limit to 2 suggestions
            })
            
            # Get pending assignments that need grading
            pending_assignments = Assignment.query.filter_by(course_id=course.id).all()
            for assignment in pending_assignments:
                ungraded_count = Submission.query.filter_by(
                    assignment_id=assignment.id
                ).outerjoin(Grade).filter(Grade.id.is_(None)).count()
                
                if ungraded_count > 0:
                    suggestions.append({
                        'type': 'grading_session',
                        'title': f"Grade {assignment.title}",
                        'description': f"Grade {ungraded_count} submissions for {assignment.title}",
                        'course_id': course.id,
                        'assignment_id': assignment.id,
                        'ungraded_count': ungraded_count,
                        'suggested_times': [
                            datetime.now() + timedelta(hours=i*24)
                            for i in range(1, 4)
                        ]
                    })
    
    # For students: suggest study sessions for upcoming assignments
    elif user.is_student():
        # Get upcoming assignments
        upcoming_assignments = Assignment.query.join(Course).join(
            course_students
        ).filter(
            course_students.c.user_id == user_id,
            Assignment.due_date > datetime.now(),
            Assignment.due_date <= datetime.now() + timedelta(days=14)
        ).order_by(Assignment.due_date).all()
        
        for assignment in upcoming_assignments:
            # Check if already submitted
            submission_exists = Submission.query.filter_by(
                assignment_id=assignment.id,
                student_id=user_id
            ).first() is not None
            
            if not submission_exists:
                # Calculate days until due
                days_until_due = (assignment.due_date - datetime.now()).days
                
                # More urgent assignments get more study sessions
                num_sessions = max(1, min(3, 7 // days_until_due)) if days_until_due > 0 else 1
                
                suggestions.append({
                    'type': 'study_session',
                    'title': f"Study for {assignment.title}",
                    'description': f"Study session for {assignment.course.code}: {assignment.title}",
                    'course_id': assignment.course_id,
                    'assignment_id': assignment.id,
                    'due_date': assignment.due_date,
                    'days_until_due': days_until_due,
                    'suggested_times': [
                        datetime.now() + timedelta(days=i*(days_until_due//(num_sessions+1)))
                        for i in range(1, num_sessions+1)
                    ]
                })
    
    return suggestions

def import_users_from_csv(file_path, role_type):
    """Import users from a CSV file."""
    users_added = 0
    errors = []
    
    try:
        # Get the role
        role = db.session.query(Role).filter_by(name=role_type).first()
        if not role:
            return 0, ["Invalid role type"]
        
        # Read the CSV file
        with open(file_path, 'r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    # Check required fields
                    required_fields = ['username', 'email', 'first_name', 'last_name', 'password']
                    if not all(field in row for field in required_fields):
                        errors.append(f"Missing required fields for row: {row}")
                        continue
                    
                    # Check if user already exists
                    existing_user = User.query.filter(
                        (User.username == row['username']) | 
                        (User.email == row['email'])
                    ).first()
                    
                    if existing_user:
                        errors.append(f"User with username {row['username']} or email {row['email']} already exists")
                        continue
                    
                    # Create new user
                    user = User(
                        username=row['username'],
                        email=row['email'],
                        first_name=row['first_name'],
                        last_name=row['last_name'],
                        role_id=role.id,
                        is_active=True
                    )
                    user.set_password(row['password'])
                    
                    db.session.add(user)
                    users_added += 1
                    
                except Exception as e:
                    errors.append(f"Error processing user {row.get('username', 'unknown')}: {str(e)}")
            
            db.session.commit()
            return users_added, errors
            
    except Exception as e:
        db.session.rollback()
        return 0, [f"Error importing users: {str(e)}"]

def get_course_progression(course_id):
    """Get progression data for a course."""
    course = Course.query.get(course_id)
    if not course:
        return None
        
    assignments = Assignment.query.filter_by(course_id=course_id).order_by(Assignment.due_date).all()
    students = course.students
    
    progression_data = []
    
    for student in students:
        student_data = {
            'student_id': student.id,
            'student_name': student.get_full_name(),
            'assignments': []
        }
        
        total_score = 0
        total_weight = 0
        
        for assignment in assignments:
            submission = Submission.query.filter_by(
                assignment_id=assignment.id,
                student_id=student.id
            ).first()
            
            assignment_data = {
                'assignment_id': assignment.id,
                'title': assignment.title,
                'due_date': assignment.due_date,
                'max_score': assignment.max_score,
                'weight': assignment.weight,
                'submitted': submission is not None
            }
            
            if submission and submission.grade:
                assignment_data['score'] = submission.grade.score
                assignment_data['percentage'] = (submission.grade.score / assignment.max_score) * 100
                total_score += submission.grade.score * assignment.weight
                total_weight += assignment.weight
            else:
                assignment_data['score'] = None
                assignment_data['percentage'] = None
            
            student_data['assignments'].append(assignment_data)
        
        # Calculate overall grade
        if total_weight > 0:
            student_data['overall_grade'] = total_score / total_weight
        else:
            student_data['overall_grade'] = None
            
        progression_data.append(student_data)
    
    return progression_data
