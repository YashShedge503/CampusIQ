from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from functools import wraps
from app import db
from models import User, Course, Assignment, Submission, Grade, AssignmentStatus, SubmissionStatus
from utils import save_file, parse_date
from ai_services import analyze_submission

assignments_bp = Blueprint('assignments', __name__)

@assignments_bp.route('/')
@login_required
def index():
    """Display all assignments the user has access to."""
    # Get filter parameters
    course_id = request.args.get('course_id', type=int)
    status = request.args.get('status')
    
    # Base query - depends on user role
    if current_user.is_admin():
        query = Assignment.query
    elif current_user.is_faculty():
        query = Assignment.query.join(Course).filter(Course.faculty_id == current_user.id)
    else:  # Student
        query = Assignment.query.join(Course).join(
            course_students
        ).filter(
            course_students.c.user_id == current_user.id,
            Assignment.status == AssignmentStatus.PUBLISHED
        )
    
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
    if current_user.is_admin():
        courses = Course.query.all()
    elif current_user.is_faculty():
        courses = Course.query.filter_by(faculty_id=current_user.id).all()
    else:  # Student
        courses = current_user.enrolled_courses
    
    # Get paginated results
    page = request.args.get('page', 1, type=int)
    per_page = 10
    assignments = query.order_by(Assignment.due_date.desc()).paginate(page=page, per_page=per_page)
    
    # For students, get IDs of submitted assignments
    submitted_assignment_ids = []
    if current_user.is_student():
        submitted_assignment_ids = [s.assignment_id for s in 
                                  Submission.query.filter_by(student_id=current_user.id).all()]
    
    return render_template('assignments/index.html', 
                           assignments=assignments,
                           courses=courses,
                           current_course_id=course_id,
                           current_status=status,
                           submitted_assignment_ids=submitted_assignment_ids)

@assignments_bp.route('/<int:assignment_id>')
@login_required
def view(assignment_id):
    """View a specific assignment."""
    # Get the assignment
    assignment = Assignment.query.get_or_404(assignment_id)
    
    # Check permission
    has_permission = False
    if current_user.is_admin():
        has_permission = True
    elif current_user.is_faculty() and assignment.course.faculty_id == current_user.id:
        has_permission = True
    elif current_user.is_student() and assignment.status == AssignmentStatus.PUBLISHED and assignment.course in current_user.enrolled_courses:
        has_permission = True
    
    if not has_permission:
        flash('You do not have permission to view this assignment.', 'danger')
        return redirect(url_for('assignments.index'))
    
    # Get submissions
    submissions = []
    user_submission = None
    
    if current_user.is_admin() or current_user.is_faculty():
        submissions = Submission.query.filter_by(assignment_id=assignment_id).all()
    
    if current_user.is_student():
        user_submission = Submission.query.filter_by(
            assignment_id=assignment_id,
            student_id=current_user.id
        ).first()
    
    return render_template('assignments/view.html',
                           assignment=assignment,
                           submissions=submissions,
                           user_submission=user_submission)

@assignments_bp.route('/<int:assignment_id>/grade/<int:submission_id>', methods=['GET', 'POST'])
@login_required
def grade(assignment_id, submission_id):
    """Grade a submission for an assignment."""
    # Check if user is admin or faculty of the course
    submission = Submission.query.get_or_404(submission_id)
    assignment = Assignment.query.get_or_404(assignment_id)
    
    if not current_user.is_admin() and not (current_user.is_faculty() and assignment.course.faculty_id == current_user.id):
        flash('You do not have permission to grade this submission.', 'danger')
        return redirect(url_for('assignments.view', assignment_id=assignment_id))
    
    # Check if submission belongs to this assignment
    if submission.assignment_id != assignment_id:
        flash('Submission does not belong to this assignment.', 'danger')
        return redirect(url_for('assignments.view', assignment_id=assignment_id))
    
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
                return redirect(url_for('assignments.view', assignment_id=assignment_id))
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
    
    return render_template('assignments/grade.html',
                           assignment=assignment,
                           submission=submission,
                           grade=grade,
                           ai_suggestion=ai_suggestion)

@assignments_bp.route('/api/analyze', methods=['POST'])
@login_required
def api_analyze():
    """API endpoint to analyze a submission text."""
    data = request.json
    if not data or 'submission_text' not in data or 'assignment_instructions' not in data:
        return jsonify({'error': 'Missing required fields'}), 400
    
    analysis = analyze_submission(
        data['submission_text'],
        data['assignment_instructions'],
        data.get('rubric'),
        data.get('reference_answer')
    )
    
    return jsonify(analysis)
