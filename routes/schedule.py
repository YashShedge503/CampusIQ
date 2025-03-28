from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from datetime import datetime, timedelta
from app import db
from models import Schedule, Course
from utils import parse_date, get_user_courses, generate_schedule_suggestions
from ai_services import optimize_schedule

schedule_bp = Blueprint('schedule', __name__)

@schedule_bp.route('/')
@login_required
def index():
    """View schedule calendar."""
    # Get filter parameters
    view_type = request.args.get('view', 'week')  # week, month, or day
    date_str = request.args.get('date')
    course_id = request.args.get('course_id', type=int)
    
    # Parse date if provided, otherwise use today
    if date_str:
        selected_date = parse_date(date_str, default=datetime.now())
    else:
        selected_date = datetime.now()
    
    # Calculate date range based on view type
    if view_type == 'day':
        start_date = selected_date.replace(hour=0, minute=0, second=0, microsecond=0)
        end_date = start_date + timedelta(days=1)
    elif view_type == 'month':
        start_date = selected_date.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        if start_date.month == 12:
            end_date = datetime(start_date.year+1, 1, 1)
        else:
            end_date = datetime(start_date.year, start_date.month+1, 1)
    else:  # week is default
        # Start from Monday of the current week
        start_date = selected_date - timedelta(days=selected_date.weekday())
        start_date = start_date.replace(hour=0, minute=0, second=0, microsecond=0)
        end_date = start_date + timedelta(days=7)
    
    # Build query for events
    query = Schedule.query.filter(
        Schedule.start_time >= start_date,
        Schedule.start_time < end_date
    )
    
    # Filter by ownership or access
    if current_user.is_admin():
        # Admins can see all events
        pass
    elif current_user.is_faculty():
        # Faculty can see their own events and events for courses they teach
        query = query.filter(
            (Schedule.owner_id == current_user.id) |
            (Schedule.course_id.in_([c.id for c in current_user.taught_courses]))
        )
    else:  # Student
        # Students can see their own events and events for courses they're enrolled in
        query = query.filter(
            (Schedule.owner_id == current_user.id) |
            (Schedule.course_id.in_([c.id for c in current_user.enrolled_courses]))
        )
    
    # Filter by course if specified
    if course_id:
        query = query.filter(Schedule.course_id == course_id)
    
    # Get schedule items
    schedule_items = query.order_by(Schedule.start_time).all()
    
    # Get all available courses for filter
    courses = get_user_courses(current_user)
    
    # Get schedule suggestions
    suggestions = generate_schedule_suggestions(current_user.id)
    
    return render_template('schedule/index.html',
                           schedule_items=schedule_items,
                           courses=courses,
                           selected_date=selected_date,
                           view_type=view_type,
                           current_course_id=course_id,
                           date_range={
                               'start': start_date,
                               'end': end_date
                           },
                           suggestions=suggestions)

@schedule_bp.route('/create', methods=['GET', 'POST'])
@login_required
def create():
    """Create a new schedule item."""
    # Get courses for dropdown
    courses = get_user_courses(current_user)
    
    if request.method == 'POST':
        title = request.form.get('title')
        description = request.form.get('description')
        start_time_str = request.form.get('start_time')
        end_time_str = request.form.get('end_time')
        course_id = request.form.get('course_id')
        location = request.form.get('location')
        is_recurring = 'is_recurring' in request.form
        recurrence_pattern = request.form.get('recurrence_pattern')
        
        # Basic validation
        error = None
        if not title or not start_time_str or not end_time_str:
            error = 'Title, start time, and end time are required.'
        
        # Parse dates
        start_time = parse_date(start_time_str)
        end_time = parse_date(end_time_str)
        
        if not start_time or not end_time:
            error = 'Invalid date/time format.'
        elif start_time >= end_time:
            error = 'End time must be after start time.'
        
        if error:
            flash(error, 'danger')
        else:
            # Create new schedule item
            new_schedule = Schedule(
                title=title,
                description=description,
                start_time=start_time,
                end_time=end_time,
                course_id=course_id if course_id else None,
                owner_id=current_user.id,
                location=location,
                is_recurring=is_recurring,
                recurrence_pattern=recurrence_pattern if is_recurring else None
            )
            
            try:
                db.session.add(new_schedule)
                db.session.commit()
                flash('Schedule item created successfully!', 'success')
                return redirect(url_for('schedule.index'))
            except Exception as e:
                db.session.rollback()
                flash(f'An error occurred: {str(e)}', 'danger')
    
    # Pre-fill course_id if specified in query params
    preselected_course_id = request.args.get('course_id', type=int)
    
    return render_template('schedule/create.html',
                           courses=courses,
                           preselected_course_id=preselected_course_id)

@schedule_bp.route('/<int:schedule_id>/edit', methods=['GET', 'POST'])
@login_required
def edit(schedule_id):
    """Edit a schedule item."""
    # Get the schedule item
    schedule_item = Schedule.query.get_or_404(schedule_id)
    
    # Check permission
    if not current_user.is_admin() and schedule_item.owner_id != current_user.id:
        flash('You do not have permission to edit this schedule item.', 'danger')
        return redirect(url_for('schedule.index'))
    
    # Get courses for dropdown
    courses = get_user_courses(current_user)
    
    if request.method == 'POST':
        title = request.form.get('title')
        description = request.form.get('description')
        start_time_str = request.form.get('start_time')
        end_time_str = request.form.get('end_time')
        course_id = request.form.get('course_id')
        location = request.form.get('location')
        is_recurring = 'is_recurring' in request.form
        recurrence_pattern = request.form.get('recurrence_pattern')
        
        # Basic validation
        error = None
        if not title or not start_time_str or not end_time_str:
            error = 'Title, start time, and end time are required.'
        
        # Parse dates
        start_time = parse_date(start_time_str)
        end_time = parse_date(end_time_str)
        
        if not start_time or not end_time:
            error = 'Invalid date/time format.'
        elif start_time >= end_time:
            error = 'End time must be after start time.'
        
        if error:
            flash(error, 'danger')
        else:
            # Update schedule item
            schedule_item.title = title
            schedule_item.description = description
            schedule_item.start_time = start_time
            schedule_item.end_time = end_time
            schedule_item.course_id = course_id if course_id else None
            schedule_item.location = location
            schedule_item.is_recurring = is_recurring
            schedule_item.recurrence_pattern = recurrence_pattern if is_recurring else None
            
            try:
                db.session.commit()
                flash('Schedule item updated successfully!', 'success')
                return redirect(url_for('schedule.index'))
            except Exception as e:
                db.session.rollback()
                flash(f'An error occurred: {str(e)}', 'danger')
    
    return render_template('schedule/edit.html',
                           schedule_item=schedule_item,
                           courses=courses)

@schedule_bp.route('/<int:schedule_id>/delete', methods=['POST'])
@login_required
def delete(schedule_id):
    """Delete a schedule item."""
    # Get the schedule item
    schedule_item = Schedule.query.get_or_404(schedule_id)
    
    # Check permission
    if not current_user.is_admin() and schedule_item.owner_id != current_user.id:
        flash('You do not have permission to delete this schedule item.', 'danger')
        return redirect(url_for('schedule.index'))
    
    try:
        db.session.delete(schedule_item)
        db.session.commit()
        flash('Schedule item deleted successfully!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'An error occurred: {str(e)}', 'danger')
    
    return redirect(url_for('schedule.index'))

@schedule_bp.route('/api/optimize', methods=['POST'])
@login_required
def api_optimize_schedule():
    """API endpoint to optimize schedule."""
    data = request.json
    
    if not data or 'events' not in data:
        return jsonify({'error': 'Missing required fields'}), 400
    
    events = data['events']
    constraints = data.get('constraints', {})
    preferences = data.get('preferences', {})
    
    optimized_schedule = optimize_schedule(events, constraints, preferences)
    
    return jsonify({
        'schedule': optimized_schedule
    })

@schedule_bp.route('/api/suggestions')
@login_required
def api_get_suggestions():
    """API endpoint to get schedule suggestions."""
    suggestions = generate_schedule_suggestions(current_user.id)
    return jsonify(suggestions)
