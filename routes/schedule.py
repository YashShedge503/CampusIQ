from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify
from flask_login import login_required, current_user
from sqlalchemy.exc import IntegrityError
from datetime import datetime, timedelta

from app import db
from models import Schedule, Course
from utils import parse_date, get_user_courses
from ai_services import optimize_schedule

schedule_bp = Blueprint('schedule', __name__)

@schedule_bp.route('/')
@login_required
def index():
    """View schedule calendar."""
    # Get courses based on user role
    courses = get_user_courses(current_user)
    
    # Get filter parameters
    course_id = request.args.get('course_id', type=int)
    start_date_str = request.args.get('start_date')
    end_date_str = request.args.get('end_date')
    
    # Parse dates
    today = datetime.utcnow().date()
    start_date = parse_date(start_date_str, default=today - timedelta(days=today.weekday()))  # Default to start of current week
    end_date = parse_date(end_date_str, default=start_date + timedelta(days=30))  # Default to 30 days from start
    
    # Base query
    if current_user.is_admin():
        query = Schedule.query
    elif current_user.is_faculty():
        query = Schedule.query.filter(
            ((Schedule.course_id.is_(None)) & (Schedule.owner_id == current_user.id)) |
            ((Schedule.course_id.isnot(None)) & (Course.faculty_id == current_user.id))
        ).outerjoin(Course)
    else:  # Student
        enrolled_ids = [c.id for c in current_user.enrolled_courses]
        query = Schedule.query.filter(
            ((Schedule.course_id.is_(None)) & (Schedule.owner_id == current_user.id)) |
            ((Schedule.course_id.isnot(None)) & (Schedule.course_id.in_(enrolled_ids)))
        )
    
    # Apply filters
    if course_id:
        query = query.filter(Schedule.course_id == course_id)
    
    # Filter by date range
    query = query.filter(
        ((Schedule.start_time >= start_date) & (Schedule.start_time <= end_date)) |
        ((Schedule.end_time >= start_date) & (Schedule.end_time <= end_date))
    )
    
    # Get schedules
    schedules = query.order_by(Schedule.start_time).all()
    
    # Format for calendar
    calendar_events = []
    for schedule in schedules:
        # Determine color based on type
        if schedule.course_id:
            color = '#3788d8'  # Blue for course events
        elif schedule.owner_id == current_user.id:
            color = '#28a745'  # Green for personal events
        else:
            color = '#6c757d'  # Gray for other events
        
        calendar_events.append({
            'id': schedule.id,
            'title': schedule.title,
            'start': schedule.start_time.isoformat(),
            'end': schedule.end_time.isoformat(),
            'description': schedule.description,
            'location': schedule.location,
            'color': color,
            'course_id': schedule.course_id,
            'allDay': (schedule.end_time - schedule.start_time) >= timedelta(hours=23)
        })
    
    return render_template('schedule/index.html',
                          courses=courses,
                          current_course_id=course_id,
                          start_date=start_date,
                          end_date=end_date,
                          calendar_events=calendar_events)

@schedule_bp.route('/create', methods=['GET', 'POST'])
@login_required
def create():
    """Create a new schedule item."""
    if request.method == 'POST':
        title = request.form.get('title')
        description = request.form.get('description')
        start_time_str = request.form.get('start_time')
        end_time_str = request.form.get('end_time')
        location = request.form.get('location')
        course_id = request.form.get('course_id')
        is_recurring = True if request.form.get('is_recurring') else False
        recurrence_pattern = request.form.get('recurrence_pattern')
        
        # Validate input
        if not title or not start_time_str or not end_time_str:
            flash('Title, start time, and end time are required.', 'danger')
            return redirect(url_for('schedule.create'))
        
        # Parse times
        start_time = parse_date(start_time_str)
        end_time = parse_date(end_time_str)
        
        if not start_time or not end_time:
            flash('Invalid date/time format.', 'danger')
            return redirect(url_for('schedule.create'))
        
        if start_time >= end_time:
            flash('End time must be after start time.', 'danger')
            return redirect(url_for('schedule.create'))
        
        # Validate course if selected
        if course_id:
            # Check if user has access to this course
            if current_user.is_faculty():
                course = Course.query.filter_by(id=course_id, faculty_id=current_user.id).first()
                if not course:
                    flash('You do not have permission to create events for this course.', 'danger')
                    return redirect(url_for('schedule.create'))
            elif current_user.is_student():
                course = Course.query.filter_by(id=course_id).first()
                if not course or course not in current_user.enrolled_courses:
                    flash('You do not have permission to create events for this course.', 'danger')
                    return redirect(url_for('schedule.create'))
        
        # Create schedule
        new_schedule = Schedule(
            title=title,
            description=description,
            start_time=start_time,
            end_time=end_time,
            location=location,
            course_id=course_id,
            owner_id=current_user.id,
            is_recurring=is_recurring,
            recurrence_pattern=recurrence_pattern
        )
        
        try:
            db.session.add(new_schedule)
            db.session.commit()
            flash(f'Schedule "{title}" created successfully.', 'success')
            return redirect(url_for('schedule.index'))
        except IntegrityError:
            db.session.rollback()
            flash('An error occurred while creating the schedule.', 'danger')
    
    # Get courses for the form
    if current_user.is_admin():
        courses = Course.query.all()
    elif current_user.is_faculty():
        courses = Course.query.filter_by(faculty_id=current_user.id).all()
    else:
        courses = current_user.enrolled_courses
    
    return render_template('schedule/create.html', courses=courses)

@schedule_bp.route('/<int:schedule_id>/edit', methods=['GET', 'POST'])
@login_required
def edit(schedule_id):
    """Edit a schedule item."""
    schedule = Schedule.query.get_or_404(schedule_id)
    
    # Check if user has permission to edit this schedule
    if not current_user.is_admin():
        if schedule.owner_id != current_user.id:
            if current_user.is_faculty():
                if not schedule.course_id or schedule.course.faculty_id != current_user.id:
                    flash('You do not have permission to edit this schedule.', 'danger')
                    return redirect(url_for('schedule.index'))
            else:  # Student
                flash('You do not have permission to edit this schedule.', 'danger')
                return redirect(url_for('schedule.index'))
    
    if request.method == 'POST':
        title = request.form.get('title')
        description = request.form.get('description')
        start_time_str = request.form.get('start_time')
        end_time_str = request.form.get('end_time')
        location = request.form.get('location')
        course_id = request.form.get('course_id')
        is_recurring = True if request.form.get('is_recurring') else False
        recurrence_pattern = request.form.get('recurrence_pattern')
        
        # Validate input
        if not title or not start_time_str or not end_time_str:
            flash('Title, start time, and end time are required.', 'danger')
            return redirect(url_for('schedule.edit', schedule_id=schedule_id))
        
        # Parse times
        start_time = parse_date(start_time_str)
        end_time = parse_date(end_time_str)
        
        if not start_time or not end_time:
            flash('Invalid date/time format.', 'danger')
            return redirect(url_for('schedule.edit', schedule_id=schedule_id))
        
        if start_time >= end_time:
            flash('End time must be after start time.', 'danger')
            return redirect(url_for('schedule.edit', schedule_id=schedule_id))
        
        # Validate course if selected
        if course_id:
            # Check if user has access to this course
            if current_user.is_faculty():
                course = Course.query.filter_by(id=course_id, faculty_id=current_user.id).first()
                if not course:
                    flash('You do not have permission to create events for this course.', 'danger')
                    return redirect(url_for('schedule.edit', schedule_id=schedule_id))
            elif current_user.is_student():
                course = Course.query.filter_by(id=course_id).first()
                if not course or course not in current_user.enrolled_courses:
                    flash('You do not have permission to create events for this course.', 'danger')
                    return redirect(url_for('schedule.edit', schedule_id=schedule_id))
        
        # Update schedule
        schedule.title = title
        schedule.description = description
        schedule.start_time = start_time
        schedule.end_time = end_time
        schedule.location = location
        schedule.course_id = course_id
        schedule.is_recurring = is_recurring
        schedule.recurrence_pattern = recurrence_pattern
        
        try:
            db.session.commit()
            flash(f'Schedule "{title}" updated successfully.', 'success')
            return redirect(url_for('schedule.index'))
        except IntegrityError:
            db.session.rollback()
            flash('An error occurred while updating the schedule.', 'danger')
    
    # Get courses for the form
    if current_user.is_admin():
        courses = Course.query.all()
    elif current_user.is_faculty():
        courses = Course.query.filter_by(faculty_id=current_user.id).all()
    else:
        courses = current_user.enrolled_courses
    
    return render_template('schedule/edit.html', schedule=schedule, courses=courses)

@schedule_bp.route('/<int:schedule_id>/delete', methods=['POST'])
@login_required
def delete(schedule_id):
    """Delete a schedule item."""
    schedule = Schedule.query.get_or_404(schedule_id)
    
    # Check if user has permission to delete this schedule
    if not current_user.is_admin():
        if schedule.owner_id != current_user.id:
            if current_user.is_faculty():
                if not schedule.course_id or schedule.course.faculty_id != current_user.id:
                    flash('You do not have permission to delete this schedule.', 'danger')
                    return redirect(url_for('schedule.index'))
            else:  # Student
                flash('You do not have permission to delete this schedule.', 'danger')
                return redirect(url_for('schedule.index'))
    
    title = schedule.title
    
    try:
        db.session.delete(schedule)
        db.session.commit()
        flash(f'Schedule "{title}" deleted successfully.', 'success')
    except IntegrityError:
        db.session.rollback()
        flash('An error occurred while deleting the schedule.', 'danger')
    
    return redirect(url_for('schedule.index'))

@schedule_bp.route('/api/optimize-schedule', methods=['POST'])
@login_required
def api_optimize_schedule():
    """API endpoint to optimize schedule."""
    if not request.is_json:
        return jsonify({'error': 'Request must be JSON'}), 400
    
    data = request.get_json()
    
    events = data.get('events', [])
    constraints = data.get('constraints', {})
    preferences = data.get('preferences', {})
    
    if not events:
        return jsonify({'error': 'Events are required'}), 400
    
    try:
        optimized_schedule = optimize_schedule(events, constraints, preferences)
        return jsonify(optimized_schedule)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@schedule_bp.route('/api/get-suggestions', methods=['GET'])
@login_required
def api_get_suggestions():
    """API endpoint to get schedule suggestions."""
    # Get filter parameters
    start_date_str = request.args.get('start_date')
    end_date_str = request.args.get('end_date')
    
    # Parse dates
    today = datetime.utcnow().date()
    start_date = parse_date(start_date_str, default=today)
    end_date = parse_date(end_date_str, default=start_date + timedelta(days=7))
    
    try:
        from utils import generate_schedule_suggestions
        suggestions = generate_schedule_suggestions(current_user.id, start_date, end_date)
        return jsonify(suggestions)
    except Exception as e:
        return jsonify({'error': str(e)}), 500