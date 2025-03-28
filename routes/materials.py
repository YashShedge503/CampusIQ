from flask import Blueprint, render_template, redirect, url_for, flash, request, send_file
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
from sqlalchemy.exc import IntegrityError
import os

from app import db
from models import Material, Course
from utils import allowed_file, save_file, get_user_courses

materials_bp = Blueprint('materials', __name__)

@materials_bp.route('/')
@login_required
def index():
    """Display all materials the user has access to."""
    # Get courses based on user role
    courses = get_user_courses(current_user)
    
    # Get filter parameters
    course_id = request.args.get('course_id', type=int)
    search = request.args.get('search', '')
    
    # Base query
    if current_user.is_admin():
        query = Material.query
    elif current_user.is_faculty():
        query = Material.query.join(Course).filter(
            (Course.faculty_id == current_user.id) | 
            (Material.created_by_id == current_user.id)
        )
    else:  # Student
        enrolled_ids = [c.id for c in current_user.enrolled_courses]
        query = Material.query.join(Course).filter(
            Course.id.in_(enrolled_ids),
            Material.is_visible == True
        )
    
    # Apply filters
    if course_id:
        query = query.filter(Material.course_id == course_id)
        
    if search:
        query = query.filter(Material.title.ilike(f'%{search}%'))
    
    # Paginate results
    page = request.args.get('page', 1, type=int)
    per_page = 10
    materials = query.order_by(Material.created_at.desc()).paginate(page=page, per_page=per_page)
    
    return render_template('materials/index.html', 
                          materials=materials,
                          courses=courses,
                          current_course_id=course_id,
                          search=search)

@materials_bp.route('/create', methods=['GET', 'POST'])
@login_required
def create():
    """Create a new course material."""
    # Only faculty and admin can create materials
    if not current_user.is_admin() and not current_user.is_faculty():
        flash('You do not have permission to create materials.', 'danger')
        return redirect(url_for('materials.index'))
    
    if request.method == 'POST':
        title = request.form.get('title')
        description = request.form.get('description')
        course_id = request.form.get('course_id')
        is_visible = True if request.form.get('is_visible') else False
        material_type = request.form.get('material_type')
        
        # Validate input
        if not title or not course_id:
            flash('Title and course are required.', 'danger')
            return redirect(url_for('materials.create'))
        
        # Check if course exists and user has access
        if current_user.is_faculty():
            course = Course.query.filter_by(id=course_id, faculty_id=current_user.id).first()
            if not course:
                flash('You do not have permission to add materials to this course.', 'danger')
                return redirect(url_for('materials.create'))
        else:
            course = Course.query.get_or_404(course_id)
        
        # Handle file upload or URL
        file_path = None
        url = None
        
        if material_type == 'file':
            if 'file' not in request.files:
                flash('No file selected.', 'danger')
                return redirect(url_for('materials.create'))
                
            file = request.files['file']
            
            if file.filename == '':
                flash('No file selected.', 'danger')
                return redirect(url_for('materials.create'))
                
            if not allowed_file(file.filename):
                flash('File type not allowed.', 'danger')
                return redirect(url_for('materials.create'))
                
            file_path = save_file(file, f'materials/{course_id}')
        else:  # URL
            url = request.form.get('url')
            if not url:
                flash('URL is required for web resource materials.', 'danger')
                return redirect(url_for('materials.create'))
        
        # Create new material
        new_material = Material(
            title=title,
            description=description,
            file_path=file_path,
            url=url,
            course_id=course_id,
            created_by_id=current_user.id,
            is_visible=is_visible
        )
        
        try:
            db.session.add(new_material)
            db.session.commit()
            flash(f'Material "{title}" created successfully.', 'success')
            return redirect(url_for('materials.index'))
        except IntegrityError:
            db.session.rollback()
            flash('An error occurred while creating the material.', 'danger')
    
    # Get courses for the form
    if current_user.is_admin():
        courses = Course.query.all()
    else:
        courses = Course.query.filter_by(faculty_id=current_user.id).all()
    
    return render_template('materials/create.html', courses=courses)

@materials_bp.route('/<int:material_id>')
@login_required
def view(material_id):
    """View a specific course material."""
    material = Material.query.get_or_404(material_id)
    
    # Check if user has access to this material
    if not current_user.is_admin():
        if current_user.is_faculty():
            if material.course.faculty_id != current_user.id and material.created_by_id != current_user.id:
                flash('You do not have access to this material.', 'danger')
                return redirect(url_for('materials.index'))
        else:  # Student
            if material.course not in current_user.enrolled_courses or not material.is_visible:
                flash('You do not have access to this material.', 'danger')
                return redirect(url_for('materials.index'))
    
    return render_template('materials/view.html', material=material)

@materials_bp.route('/<int:material_id>/download')
@login_required
def download(material_id):
    """Download a course material file."""
    material = Material.query.get_or_404(material_id)
    
    # Check if user has access to this material
    if not current_user.is_admin():
        if current_user.is_faculty():
            if material.course.faculty_id != current_user.id and material.created_by_id != current_user.id:
                flash('You do not have access to this material.', 'danger')
                return redirect(url_for('materials.index'))
        else:  # Student
            if material.course not in current_user.enrolled_courses or not material.is_visible:
                flash('You do not have access to this material.', 'danger')
                return redirect(url_for('materials.index'))
    
    # Check if material has a file
    if not material.file_path or not os.path.exists(material.file_path):
        flash('This material does not have a downloadable file.', 'warning')
        return redirect(url_for('materials.view', material_id=material_id))
    
    # Get filename from path
    filename = os.path.basename(material.file_path)
    
    # Send the file
    return send_file(material.file_path, as_attachment=True, download_name=filename)

@materials_bp.route('/<int:material_id>/edit', methods=['GET', 'POST'])
@login_required
def edit(material_id):
    """Edit a course material."""
    material = Material.query.get_or_404(material_id)
    
    # Check if user has permission to edit this material
    if not current_user.is_admin():
        if current_user.is_faculty():
            if material.created_by_id != current_user.id and material.course.faculty_id != current_user.id:
                flash('You do not have permission to edit this material.', 'danger')
                return redirect(url_for('materials.index'))
        else:
            flash('You do not have permission to edit materials.', 'danger')
            return redirect(url_for('materials.index'))
    
    if request.method == 'POST':
        title = request.form.get('title')
        description = request.form.get('description')
        course_id = request.form.get('course_id')
        is_visible = True if request.form.get('is_visible') else False
        material_type = request.form.get('material_type')
        
        # Validate input
        if not title or not course_id:
            flash('Title and course are required.', 'danger')
            return redirect(url_for('materials.edit', material_id=material_id))
        
        # Check if course exists and user has access
        if current_user.is_faculty():
            course = Course.query.filter_by(id=course_id, faculty_id=current_user.id).first()
            if not course:
                flash('You do not have permission to add materials to this course.', 'danger')
                return redirect(url_for('materials.edit', material_id=material_id))
        else:
            course = Course.query.get_or_404(course_id)
        
        # Handle file upload or URL
        if material_type == 'file' and 'file' in request.files and request.files['file'].filename:
            file = request.files['file']
            
            if not allowed_file(file.filename):
                flash('File type not allowed.', 'danger')
                return redirect(url_for('materials.edit', material_id=material_id))
            
            # Delete old file if exists
            if material.file_path and os.path.exists(material.file_path):
                try:
                    os.remove(material.file_path)
                except:
                    pass
            
            # Save new file
            material.file_path = save_file(file, f'materials/{course_id}')
            material.url = None
        elif material_type == 'url':
            url = request.form.get('url')
            if not url:
                flash('URL is required for web resource materials.', 'danger')
                return redirect(url_for('materials.edit', material_id=material_id))
            
            # Update URL, clear file path
            material.url = url
            
            # Delete old file if exists
            if material.file_path and os.path.exists(material.file_path):
                try:
                    os.remove(material.file_path)
                except:
                    pass
            
            material.file_path = None
        
        # Update material
        material.title = title
        material.description = description
        material.course_id = course_id
        material.is_visible = is_visible
        
        try:
            db.session.commit()
            flash(f'Material "{title}" updated successfully.', 'success')
            return redirect(url_for('materials.view', material_id=material_id))
        except IntegrityError:
            db.session.rollback()
            flash('An error occurred while updating the material.', 'danger')
    
    # Get courses for the form
    if current_user.is_admin():
        courses = Course.query.all()
    else:
        courses = Course.query.filter_by(faculty_id=current_user.id).all()
    
    return render_template('materials/edit.html', material=material, courses=courses)

@materials_bp.route('/<int:material_id>/delete', methods=['POST'])
@login_required
def delete(material_id):
    """Delete a course material."""
    material = Material.query.get_or_404(material_id)
    
    # Check if user has permission to delete this material
    if not current_user.is_admin():
        if current_user.is_faculty():
            if material.created_by_id != current_user.id and material.course.faculty_id != current_user.id:
                flash('You do not have permission to delete this material.', 'danger')
                return redirect(url_for('materials.index'))
        else:
            flash('You do not have permission to delete materials.', 'danger')
            return redirect(url_for('materials.index'))
    
    # Delete file if exists
    if material.file_path and os.path.exists(material.file_path):
        try:
            os.remove(material.file_path)
        except:
            pass
    
    # Delete material
    try:
        db.session.delete(material)
        db.session.commit()
        flash('Material deleted successfully.', 'success')
    except IntegrityError:
        db.session.rollback()
        flash('An error occurred while deleting the material.', 'danger')
    
    return redirect(url_for('materials.index'))