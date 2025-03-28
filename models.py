from app import db
from flask_login import UserMixin
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
import enum
from sqlalchemy import Enum
import logging

logger = logging.getLogger(__name__)

# Enums for model fields
class RoleType(enum.Enum):
    ADMIN = "admin"
    FACULTY = "faculty"
    STUDENT = "student"

class AssignmentStatus(enum.Enum):
    DRAFT = "draft"
    PUBLISHED = "published"
    CLOSED = "closed"

class SubmissionStatus(enum.Enum):
    SUBMITTED = "submitted"
    LATE = "late"
    GRADED = "graded"
    RETURNED = "returned"

# Association tables for many-to-many relationships
course_students = db.Table('course_students',
    db.Column('course_id', db.Integer, db.ForeignKey('course.id'), primary_key=True),
    db.Column('user_id', db.Integer, db.ForeignKey('user.id'), primary_key=True)
)

# Role model
class Role(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(Enum(RoleType), nullable=False, unique=True)
    description = db.Column(db.String(100))
    
    users = db.relationship('User', backref='role', lazy=True)
    
    def __repr__(self):
        return f'<Role {self.name.value}>'

# User model
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    first_name = db.Column(db.String(50), nullable=False)
    last_name = db.Column(db.String(50), nullable=False)
    role_id = db.Column(db.Integer, db.ForeignKey('role.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    is_active = db.Column(db.Boolean, default=True)
    
    # Relationships
    taught_courses = db.relationship('Course', backref='faculty', lazy=True, 
                                     foreign_keys='Course.faculty_id')
    enrolled_courses = db.relationship('Course', secondary=course_students, 
                                        lazy='subquery', backref=db.backref('students', lazy=True))
    submissions = db.relationship('Submission', backref='student', lazy=True)
    materials = db.relationship('Material', backref='created_by', lazy=True)
    schedules = db.relationship('Schedule', backref='owner', lazy=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)
    
    def is_admin(self):
        return self.role.name == RoleType.ADMIN
    
    def is_faculty(self):
        return self.role.name == RoleType.FACULTY
    
    def is_student(self):
        return self.role.name == RoleType.STUDENT
        
    def get_full_name(self):
        return f"{self.first_name} {self.last_name}"
    
    def __repr__(self):
        return f'<User {self.username}>'

# Course model
class Course(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(20), unique=True, nullable=False)
    title = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    faculty_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    start_date = db.Column(db.Date)
    end_date = db.Column(db.Date)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    is_active = db.Column(db.Boolean, default=True)
    credits = db.Column(db.Integer, default=3)
    
    # Relationships
    assignments = db.relationship('Assignment', backref='course', lazy=True)
    materials = db.relationship('Material', backref='course', lazy=True)
    schedules = db.relationship('Schedule', backref='course', lazy=True)
    
    def __repr__(self):
        return f'<Course {self.code}: {self.title}>'

# Assignment model
class Assignment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    course_id = db.Column(db.Integer, db.ForeignKey('course.id'), nullable=False)
    due_date = db.Column(db.DateTime, nullable=False)
    max_score = db.Column(db.Float, default=100.0)
    weight = db.Column(db.Float, default=1.0)  # Weight of this assignment in the course grade
    status = db.Column(Enum(AssignmentStatus), default=AssignmentStatus.DRAFT)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    submissions = db.relationship('Submission', backref='assignment', lazy=True)
    
    def __repr__(self):
        return f'<Assignment {self.title} for {self.course.code}>'

# Submission model
class Submission(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    assignment_id = db.Column(db.Integer, db.ForeignKey('assignment.id'), nullable=False)
    student_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    content = db.Column(db.Text)
    file_path = db.Column(db.String(255))
    status = db.Column(Enum(SubmissionStatus), default=SubmissionStatus.SUBMITTED)
    submission_date = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    grade = db.relationship('Grade', backref='submission', uselist=False, lazy=True)
    
    def is_late(self):
        return self.submission_date > self.assignment.due_date
    
    def __repr__(self):
        return f'<Submission by {self.student.username} for {self.assignment.title}>'

# Grade model
class Grade(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    submission_id = db.Column(db.Integer, db.ForeignKey('submission.id'), nullable=False, unique=True)
    score = db.Column(db.Float, nullable=False)
    feedback = db.Column(db.Text)
    graded_by = db.Column(db.Integer, db.ForeignKey('user.id'))
    graded_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # AI-related fields
    ai_score = db.Column(db.Float)
    ai_feedback = db.Column(db.Text)
    ai_confidence = db.Column(db.Float)
    
    faculty = db.relationship('User', foreign_keys=[graded_by])
    
    def get_percentage(self):
        """Return the score as a percentage of the maximum score."""
        max_score = self.submission.assignment.max_score
        return (self.score / max_score) * 100 if max_score else 0
    
    def __repr__(self):
        return f'<Grade {self.score} for {self.submission_id}>'

# Course Material model
class Material(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    file_path = db.Column(db.String(255))
    url = db.Column(db.String(255))
    course_id = db.Column(db.Integer, db.ForeignKey('course.id'), nullable=False)
    created_by_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    is_visible = db.Column(db.Boolean, default=True)
    
    def __repr__(self):
        return f'<Material {self.title} for {self.course.code}>'

# Schedule model
class Schedule(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    start_time = db.Column(db.DateTime, nullable=False)
    end_time = db.Column(db.DateTime, nullable=False)
    course_id = db.Column(db.Integer, db.ForeignKey('course.id'))
    owner_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    location = db.Column(db.String(100))
    is_recurring = db.Column(db.Boolean, default=False)
    recurrence_pattern = db.Column(db.String(50))  # e.g., "weekly", "daily", "MWF"
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def __repr__(self):
        return f'<Schedule {self.title} at {self.start_time}>'

# Analytics model for caching computed analytics
class Analytics(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    course_id = db.Column(db.Integer, db.ForeignKey('course.id'))
    metric_name = db.Column(db.String(50), nullable=False)
    metric_value = db.Column(db.Float)
    computed_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    user = db.relationship('User')
    course = db.relationship('Course')
    
    def __repr__(self):
        return f'<Analytics {self.metric_name}={self.metric_value} for user {self.user_id}>'

# Functions to create default data
def create_default_roles():
    """Create default roles if they don't exist."""
    for role_type in RoleType:
        if not Role.query.filter_by(name=role_type).first():
            role = Role(name=role_type, description=f"{role_type.value.capitalize()} role")
            db.session.add(role)
    
    try:
        db.session.commit()
        logger.debug("Default roles created successfully")
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error creating default roles: {e}")

def create_admin_user():
    """Create default admin user if no admin exists."""
    admin_role = Role.query.filter_by(name=RoleType.ADMIN).first()
    if admin_role and not User.query.filter(User.role_id == admin_role.id).first():
        admin = User(
            username="admin",
            email="admin@college.edu",
            first_name="System",
            last_name="Administrator",
            role_id=admin_role.id,
            is_active=True
        )
        admin.set_password("admin123")  # This should be changed immediately
        db.session.add(admin)
        
        try:
            db.session.commit()
            logger.debug("Default admin user created successfully")
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error creating default admin user: {e}")
