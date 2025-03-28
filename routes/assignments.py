from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify
from flask_login import login_required, current_user
from sqlalchemy.exc import IntegrityError
from datetime import datetime

from app import db
from models import Assignment, Course, Submission, Grade, SubmissionStatus, AssignmentStatus
from utils import get_user_courses
from ai_services import analyze_submission

assignments_bp = Blueprint('assignments', __name__)

@assignments_bp.route('/')
@login_required
def index():
    """Display all assignments the user has access to."""
    # Get courses based on user role
    courses = get_user_courses(current_user)
    
    # Get filter parameters
    course_id = request.args.get('course_id', type=int)
    status = request.args.get('status')
    search = request.args.get('search', '')
    
    # Base query
    if current_user.is_admin():
        query = Assignment.query
    elif current_user.is_faculty():
        query = Assignment.query.join(Course).filter(Course.faculty_id == current_user.id)
    else:  # Student
        enrolled_ids = [c.id for c in current_user.enrolled_courses]
        query = Assignment.query.join(Course).filter(
            Course.id.in_(enrolled_ids),
            Assignment.status == AssignmentStatus.PUBLISHED
        )
    
    # Apply filters
    if course_id:
        query = query.filter(Assignment.course_id == course_id)
        
    if status:
        query = query.filter(Assignment.status == AssignmentStatus[status.upper()])
        
    if search:
        query = query.filter(Assignment.title.ilike(f'%{search}%'))
    
    # Paginate results
    page = request.args.get('page', 1, type=int)
    per_page = 10
    assignments = query.order_by(Assignment.due_date.desc()).paginate(page=page, per_page=per_page)
    
    return render_template('assignments/index.html', 
                          assignments=assignments,
                          courses=courses,
                          current_course_id=course_id,
                          current_status=status,
                          search=search)

@assignments_bp.route('/<int:assignment_id>')
@login_required
def view(assignment_id):
    """View a specific assignment."""
    assignment = Assignment.query.get_or_404(assignment_id)
    
    # Check if user has access to this assignment
    if not current_user.is_admin():
        if current_user.is_faculty() and assignment.course.faculty_id != current_user.id:
            if assignment.course not in current_user.enrolled_courses:
                flash('You do not have access to this assignment.', 'danger')
                return redirect(url_for('assignments.index'))
        
        # If student, can't view draft assignments
        if current_user.is_student() and assignment.status != AssignmentStatus.PUBLISHED:
            flash('This assignment is not published yet.', 'warning')
            return redirect(url_for('assignments.index'))
    
    # Get submission for students
    submission = None
    if current_user.is_student():
        submission = Submission.query.filter_by(
            assignment_id=assignment_id,
            student_id=current_user.id
        ).first()
    
    # Get all submissions for faculty
    submissions = []
    if current_user.is_faculty() or current_user.is_admin():
        submissions = Submission.query.filter_by(assignment_id=assignment_id).all()
    
    return render_template('assignments/view.html', 
                          assignment=assignment,
                          submission=submission,
                          submissions=submissions)

@assignments_bp.route('/<int:assignment_id>/submissions/<int:submission_id>/grade', methods=['GET', 'POST'])
@login_required
def grade(assignment_id, submission_id):
    """Grade a submission for an assignment."""
    # Only faculty or admin can grade
    if not current_user.is_admin() and not current_user.is_faculty():
        flash('You do not have permission to grade submissions.', 'danger')
        return redirect(url_for('assignments.index'))
    
    assignment = Assignment.query.get_or_404(assignment_id)
    submission = Submission.query.get_or_404(submission_id)
    
    # Check if faculty teaches this course
    if current_user.is_faculty() and assignment.course.faculty_id != current_user.id:
        flash('You do not have permission to grade submissions for this course.', 'danger')
        return redirect(url_for('assignments.index'))
    
    # Check if submission is for this assignment
    if submission.assignment_id != assignment_id:
        flash('Invalid submission for this assignment.', 'danger')
        return redirect(url_for('assignments.view', assignment_id=assignment_id))
    
    if request.method == 'POST':
        score = request.form.get('score', type=float)
        feedback = request.form.get('feedback')
        
        # Validate input
        if score is None:
            flash('Score is required.', 'danger')
            return redirect(url_for('assignments.grade', assignment_id=assignment_id, submission_id=submission_id))
        
        if score < 0 or score > assignment.max_score:
            flash(f'Score must be between 0 and {assignment.max_score}.', 'danger')
            return redirect(url_for('assignments.grade', assignment_id=assignment_id, submission_id=submission_id))
        
        # Check if grade already exists
        existing_grade = Grade.query.filter_by(submission_id=submission_id).first()
        
        if existing_grade:
            # Update grade
            existing_grade.score = score
            existing_grade.feedback = feedback
            existing_grade.graded_by = current_user.id
            existing_grade.graded_at = datetime.utcnow()
        else:
            # Create new grade
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
            return redirect(url_for('assignments.view', assignment_id=assignment_id))
        except IntegrityError:
            db.session.rollback()
            flash('An error occurred while grading the submission.', 'danger')
    
    # Get existing grade
    grade = Grade.query.filter_by(submission_id=submission_id).first()
    
    # Get AI analysis if available
    ai_analysis = None
    if submission.content:
        try:
            ai_analysis = analyze_submission(
                submission.content,
                assignment.description
            )
        except Exception as e:
            flash(f'AI analysis error: {str(e)}', 'warning')
    
    return render_template('assignments/grade.html',
                          assignment=assignment,
                          submission=submission,
                          grade=grade,
                          ai_analysis=ai_analysis)

@assignments_bp.route('/api/analyze', methods=['POST'])
@login_required
def api_analyze():
    """API endpoint to analyze a submission text."""
    if not request.is_json:
        return jsonify({'error': 'Request must be JSON'}), 400
    
    data = request.get_json()
    
    submission_text = data.get('submission_text')
    assignment_instructions = data.get('assignment_instructions')
    
    if not submission_text or not assignment_instructions:
        return jsonify({'error': 'Both submission_text and assignment_instructions are required'}), 400
    
    try:
        analysis = analyze_submission(submission_text, assignment_instructions)
        return jsonify(analysis)
    except Exception as e:
        return jsonify({'error': str(e)}), 500