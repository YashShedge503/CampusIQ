from flask import Blueprint, render_template, request, redirect, url_for, flash, send_file
from flask_login import login_required, current_user
from functools import wraps
import os
from app import db
from models import Course, Material
from utils import save_file, get_user_courses

materials_bp = Blueprint('materials', __name__)

@materials_bp.route('/')
@login_required
def index():
    """Display all materials the user has access to."""
    # Get filter parameters
    course_id = request.args.get('course_id', type=int)
    
    # Base query - depends on user role
    if current_user.is_admin():
        query = Material.query
    elif current_user.is_faculty():
        # Faculty can see materials they created and materials for courses they teach
        query = Material.query.filter(
            (Material.created_by_id == current_user.id) |
            (Material.course_id.in_([c.id for c in current_user.taught_courses]))
        )
    else:  # Student
        # Students can only see materials for courses they're enrolled in
        query = Material.query.filter(
            Material.course_id.in_([c.id for c in current_user.enrolled_courses]),
            Material.is_visible == True
        )
    
    # Apply course filter if specified
    if course_id:
        query = query.filter(Material.course_id == course_id)
    
    # Get paginated results
    page = request.args.get('page', 1, type=int)
    per_page = 10
    materials = query.order_by(Material.created_at.desc()).paginate(page=page, per_page=per_page)
    
    # Get all courses for filter dropdown
    courses = get_user_courses(current_user)
    
    return render_template('materials/index.html',
                           materials=materials,
                           courses=courses,
                           current_course_id=course_id)

@materials_bp.route('/create', methods=['GET', 'POST'])
@login_required
def create():
    """Create a new course material."""
    # Only faculty and admins can create materials
    if not current_user.is_admin() and not current_user.is_faculty():
        flash('You do not have permission to create course materials.', 'danger')
        return redirect(url_for('materials.index'))
    
    # Get available courses based on user role
    courses = get_user_courses(current_user)
    
    if request.method == 'POST':
        title = request.form.get('title')
        description = request.form.get('description')
        course_id = request.form.get('course_id')
        file = request.files.get('file')
        url = request.form.get('url')
        is_visible = 'is_visible' in request.form
        
        # Basic validation
        error = None
        if not title or not course_id:
            error = 'Title and course are required.'
        elif not file and not url:
            error = 'Please provide either a file or a URL.'
        
        # Validate course
        course = Course.query.get(course_id)
        if not course:
            error = 'Invalid course selected.'
        elif not current_user.is_admin() and course.faculty_id != current_user.id:
            error = 'You can only add materials to courses you teach.'
        
        if error:
            flash(error, 'danger')
        else:
            # Process file upload if provided
            file_path = None
            if file and file.filename:
                file_path = save_file(file, f'materials/{course_id}')
                if not file_path:
                    flash('Error uploading file. Please try again.', 'danger')
                    return redirect(url_for('materials.create'))
            
            # Create new material
            new_material = Material(
                title=title,
                description=description,
                file_path=file_path,
                url=url if url else None,
                course_id=course_id,
                created_by_id=current_user.id,
                is_visible=is_visible
            )
            
            try:
                db.session.add(new_material)
                db.session.commit()
                flash('Course material created successfully!', 'success')
                return redirect(url_for('materials.index'))
            except Exception as e:
                db.session.rollback()
                flash(f'An error occurred: {str(e)}', 'danger')
    
    # Pre-fill course_id if specified in query params
    preselected_course_id = request.args.get('course_id', type=int)
    
    return render_template('materials/create.html',
                           courses=courses,
                           preselected_course_id=preselected_course_id)

@materials_bp.route('/<int:material_id>')
@login_required
def view(material_id):
    """View a specific course material."""
    # Get the material
    material = Material.query.get_or_404(material_id)
    
    # Check permission
    has_permission = False
    if current_user.is_admin():
        has_permission = True
    elif current_user.is_faculty() and (material.created_by_id == current_user.id or material.course.faculty_id == current_user.id):
        has_permission = True
    elif current_user.is_student() and material.course in current_user.enrolled_courses and material.is_visible:
        has_permission = True
    
    if not has_permission:
        flash('You do not have permission to view this material.', 'danger')
        return redirect(url_for('materials.index'))
    
    return render_template('materials/view.html', material=material)

@materials_bp.route('/<int:material_id>/download')
@login_required
def download(material_id):
    """Download a course material file."""
    # Get the material
    material = Material.query.get_or_404(material_id)
    
    # Check if material has a file
    if not material.file_path:
        flash('This material does not have a downloadable file.', 'warning')
        return redirect(url_for('materials.view', material_id=material_id))
    
    # Check permission
    has_permission = False
    if current_user.is_admin():
        has_permission = True
    elif current_user.is_faculty() and (material.created_by_id == current_user.id or material.course.faculty_id == current_user.id):
        has_permission = True
    elif current_user.is_student() and material.course in current_user.enrolled_courses and material.is_visible:
        has_permission = True
    
    if not has_permission:
        flash('You do not have permission to download this file.', 'danger')
        return redirect(url_for('materials.index'))
    
    # Get the file path
    file_path = os.path.join(os.getcwd(), material.file_path)
    
    # Check if file exists
    if not os.path.exists(file_path):
        flash('The file does not exist or has been moved.', 'danger')
        return redirect(url_for('materials.view', material_id=material_id))
    
    # Get the filename from the path
    filename = os.path.basename(file_path)
    
    # Send the file
    return send_file(file_path, as_attachment=True, download_name=filename)

@materials_bp.route('/<int:material_id>/edit', methods=['GET', 'POST'])
@login_required
def edit(material_id):
    """Edit a course material."""
    # Get the material
    material = Material.query.get_or_404(material_id)
    
    # Check permission
    if not current_user.is_admin() and (material.created_by_id != current_user.id and material.course.faculty_id != current_user.id):
        flash('You do not have permission to edit this material.', 'danger')
        return redirect(url_for('materials.index'))
    
    # Get available courses based on user role
    courses = get_user_courses(current_user)
    
    if request.method == 'POST':
        title = request.form.get('title')
        description = request.form.get('description')
        course_id = request.form.get('course_id')
        file = request.files.get('file')
        url = request.form.get('url')
        is_visible = 'is_visible' in request.form
        
        # Basic validation
        error = None
        if not title or not course_id:
            error = 'Title and course are required.'
        
        # Validate course
        course = Course.query.get(course_id)
        if not course:
            error = 'Invalid course selected.'
        elif not current_user.is_admin() and course.faculty_id != current_user.id:
            error = 'You can only add materials to courses you teach.'
        
        if error:
            flash(error, 'danger')
        else:
            # Process file upload if provided
            if file and file.filename:
                file_path = save_file(file, f'materials/{course_id}')
                if file_path:
                    # If previous file exists, could clean it up here
                    material.file_path = file_path
                else:
                    flash('Error uploading file. The material will be updated without changing the file.', 'warning')
            
            # Update material
            material.title = title
            material.description = description
            material.url = url if url else None
            material.course_id = course_id
            material.is_visible = is_visible
            
            try:
                db.session.commit()
                flash('Course material updated successfully!', 'success')
                return redirect(url_for('materials.view', material_id=material_id))
            except Exception as e:
                db.session.rollback()
                flash(f'An error occurred: {str(e)}', 'danger')
    
    return render_template('materials/edit.html',
                           material=material,
                           courses=courses)

@materials_bp.route('/<int:material_id>/delete', methods=['POST'])
@login_required
def delete(material_id):
    """Delete a course material."""
    # Get the material
    material = Material.query.get_or_404(material_id)
    
    # Check permission
    if not current_user.is_admin() and (material.created_by_id != current_user.id and material.course.faculty_id != current_user.id):
        flash('You do not have permission to delete this material.', 'danger')
        return redirect(url_for('materials.index'))
    
    try:
        # If file exists, could delete it from filesystem here
        db.session.delete(material)
        db.session.commit()
        flash('Course material deleted successfully!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'An error occurred: {str(e)}', 'danger')
    
    return redirect(url_for('materials.index'))
