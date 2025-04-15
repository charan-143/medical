from datetime import datetime
import os
import shutil
import uuid
import hashlib
import bcrypt
from pathlib import Path
from flask import current_app
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

# Import db from extensions to avoid circular imports
from extensions import db

# User loader function is defined in extensions.py


class User(db.Model, UserMixin):
    """User model for authentication and profile information"""
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, index=True, nullable=False)
    email = db.Column(db.String(120), unique=True, index=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    
    # Profile information
    first_name = db.Column(db.String(64))
    last_name = db.Column(db.String(64))
    date_of_birth = db.Column(db.Date)
    phone = db.Column(db.String(20))
    address = db.Column(db.String(256))
    
    # Avatar/profile picture
    avatar = db.Column(db.String(128), default='avatar.png')
    
    # Account management
    is_active = db.Column(db.Boolean, default=True)
    is_admin = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_login = db.Column(db.DateTime)
    
    # Relationships
    folders = db.relationship('Folder', backref='owner', lazy='dynamic', cascade='all, delete-orphan')
    documents = db.relationship('Document', backref='owner', lazy='dynamic', cascade='all, delete-orphan')
    vitals = db.relationship('VitalMeasurement', backref='user', lazy='dynamic', cascade='all, delete-orphan')
    medical_visits = db.relationship('MedicalVisit', backref='patient', lazy='dynamic', cascade='all, delete-orphan')
    conversations = db.relationship('Conversation', backref='user', lazy='dynamic', cascade='all, delete-orphan')
    
    def __init__(self, **kwargs):
        super(User, self).__init__(**kwargs)
    
    def set_password(self, password):
        """Generate password hash using bcrypt"""
        try:
            # Generate a salt and hash the password
            salt = bcrypt.gensalt()
            password_hash = bcrypt.hashpw(password.encode('utf-8'), salt)
            self.password_hash = password_hash.decode('utf-8')
        except Exception as e:
            raise ValueError(f"Error setting password: {str(e)}")
    
    def check_password(self, password):
        """Verify password against stored hash"""
        try:
            return bcrypt.checkpw(password.encode('utf-8'), self.password_hash.encode('utf-8'))
        except Exception as e:
            raise ValueError(f"Error checking password: {str(e)}")
    
    @property
    def full_name(self):
        """Return user's full name or username if not available"""
        if self.first_name and self.last_name:
            return f"{self.first_name} {self.last_name}"
        return self.username
    
    def update_last_login(self):
        """Update last login timestamp"""
        self.last_login = datetime.utcnow()
        db.session.commit()
    
    def __repr__(self):
        return f'<User {self.username}>'


class Folder(db.Model):
    """Folder model for organizing documents"""
    __tablename__ = 'folders'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    parent_id = db.Column(db.Integer, db.ForeignKey('folders.id'), nullable=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    documents = db.relationship('Document', backref='folder', lazy='dynamic', cascade='all, delete-orphan')
    children = db.relationship('Folder', backref=db.backref('parent', remote_side=[id]), lazy='dynamic')
    
    def __repr__(self):
        return f'<Folder {self.name}>'


class Document(db.Model):
    """Document model for storing uploaded files"""
    __tablename__ = 'documents'
    
    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(255), nullable=False, index=True)
    original_filename = db.Column(db.String(255), nullable=False)
    file_type = db.Column(db.String(50), nullable=False, index=True)  # pdf, jpg, etc.
    file_size = db.Column(db.Integer, nullable=False)  # Size in bytes
    file_path = db.Column(db.String(255), nullable=False, index=True)  # Path to the file in static/uploads
    folder_id = db.Column(db.Integer, db.ForeignKey('folders.id'), nullable=True, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    upload_date = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    description = db.Column(db.Text, nullable=True)  # Optional description for the document
    content_hash = db.Column(db.String(64), index=True)  # SHA-256 hash of file content for duplicate detection
    # Constants for file validation
    MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB
    ALLOWED_EXTENSIONS = {'pdf', 'jpg', 'jpeg', 'png', 'gif', 'doc', 'docx', 'xls', 'xlsx'}
    def validate_file_type(self, filename):
        """Validate that the file type is allowed"""
        ext = os.path.splitext(filename)[1].lstrip('.').lower()
        return ext in self.ALLOWED_EXTENSIONS
    
    def validate_file_size(self, file):
        """Validate that the file size is within limits"""
        file.seek(0, os.SEEK_END)
        size = file.tell()
        file.seek(0)  # Reset file pointer to beginning
        return size <= self.MAX_FILE_SIZE
    
    def cleanup_failed_upload(self, file_path):
        """Remove file if upload processing fails"""
        try:
            path = Path(file_path)
            if path.exists():
                path.unlink()
        except Exception as e:
            current_app.logger.error(f"Error cleaning up file {file_path}: {str(e)}")
    
    @staticmethod
    def compute_file_hash(file):
        """Compute SHA-256 hash of file content"""
        sha256_hash = hashlib.sha256()
        # Save current position
        current_position = file.tell()
        # Reset file pointer
        file.seek(0)
        
        # Read and update hash in chunks
        for byte_block in iter(lambda: file.read(4096), b""):
            sha256_hash.update(byte_block)
        
        # Restore file pointer
        file.seek(current_position)
        return sha256_hash.hexdigest()
    
    def check_duplicate_content(self, file_hash):
        """Check if a file with the same content hash already exists for this user in the same folder"""
        existing_doc = Document.query.filter_by(
            user_id=self.user_id,
            content_hash=file_hash,
            folder_id=self.folder_id
        ).first()
        return existing_doc
    
    def get_folder_path(self):
        """Generate the folder path based on folder_id"""
        if not current_app:
            raise RuntimeError("No application context")
            
        base_upload_dir = Path(current_app.root_path) / 'static' / 'uploads'
        if self.folder_id is not None:
            return base_upload_dir / str(self.folder_id)
        return base_upload_dir
    
    def ensure_folder_exists(self):
        """Ensure the upload folder exists and is accessible"""
        folder_path = self.get_folder_path()
        try:
            folder_path.mkdir(parents=True, exist_ok=True)
            return True
        except OSError as e:
            raise OSError(f"Could not create folder structure: {str(e)}")
    
    def save_file(self, file):
        """Save uploaded file and update document properties"""
        # Validate file type and size first
        if not self.validate_file_type(file.filename):
            raise ValueError(f"File type not allowed. Allowed types: {', '.join(self.ALLOWED_EXTENSIONS)}")
        
        if not self.validate_file_size(file):
            raise ValueError(f"File too large. Maximum size is {self.MAX_FILE_SIZE / (1024 * 1024)}MB")
        
        # Compute file hash before saving
        file_hash = self.compute_file_hash(file)
        
        # Check for duplicate content
        existing_doc = self.check_duplicate_content(file_hash)
        if existing_doc:
            raise ValueError(f"A file with identical content already exists: {existing_doc.original_filename}")
        
        # If folder_id is set, validate the folder exists and user has access
        if self.folder_id:
            self.validate_folder_access(self.folder_id)
        
        # Generate a secure filename with UUID to avoid collisions
        filename = secure_filename(file.filename)
        base, ext = os.path.splitext(filename)
        unique_filename = f"{base}_{uuid.uuid4().hex}{ext}"
        
        # Ensure the folder structure exists
        try:
            self.ensure_folder_exists()
        except OSError as e:
            raise OSError(f"Could not create folder structure: {str(e)}")
        
        # Create full path for file storage
        folder_path = self.get_folder_path()
        file_path = folder_path / unique_filename
        
        try:
            # Save the file to disk
            file.save(str(file_path))
            
            # Update document properties
            self.filename = unique_filename
            self.original_filename = file.filename
            self.content_hash = file_hash  # Store the computed hash
            
            # Get file extension and convert to lowercase
            file_ext = Path(file.filename).suffix.lstrip('.').lower()
            self.file_type = file_ext if file_ext else 'unknown'
            
            # Get file size from saved file
            self.file_size = file_path.stat().st_size
            
            # Store the relative path for retrieval
            # Store the relative path for retrieval
            self.file_path = os.path.join('uploads', str(self.folder_id) if self.folder_id else '', unique_filename)
            self.file_path = self.file_path.replace('\\', '/')
            # Ensure filename is set properly
            if not hasattr(self, 'filename') or not self.filename:
                self.filename = unique_filename
            return self
            
        except Exception as e:
            # Clean up any file that may have been partially saved
            self.cleanup_failed_upload(str(file_path))
            raise Exception(f"Error saving file: {str(e)}")
    def get_file_path(self):
        """Return the full path to the document file"""
        if not current_app:
            raise RuntimeError("No application context")
            
        if not self.file_path:
            return None
            
        # Use the stored file_path to determine the actual file location
        return Path(current_app.root_path) / 'static' / self.file_path
        
    def get_url_path(self):
        """Return the URL path for the file"""
        try:
            if not self.file_path:
                return None
                
            # Ensure the file actually exists
            file_path = self.get_file_path()
            if not file_path or not file_path.exists():
                current_app.logger.warning(f"File not found on disk: {self.file_path}")
                return None
                
            # The file path is already relative to static directory, so just prepend '/static/'
            url_path = '/static/' + self.file_path.replace('\\', '/')
            current_app.logger.debug(f"Generated URL path for {self.filename}: {url_path}")
            return url_path
            
        except Exception as e:
            current_app.logger.error(f"Error generating URL path for {self.filename}: {str(e)}")
            return None
    def get_file_info(self):
        """Return a dict of file information for template display"""
        return {
            'id': self.id,
            'filename': self.original_filename or 'Unknown',
            'file_type': self.file_type or 'unknown',
            'file_size': self.file_size or 0,
            'upload_date': self.upload_date.strftime('%Y-%m-%d %H:%M:%S') if self.upload_date else 'Unknown',
            'description': self.description or '',
            'url_path': self.get_url_path() or '#',
            'file_exists': self.get_file_path().exists() if self.get_file_path() else False
        }

    def validate_and_fix_path(self):
        """Validate and fix the file path if needed"""
        try:
            if not self.file_path:
                return False
                
            # Check if file exists
            file_path = self.get_file_path()
            if not file_path or not file_path.exists():
                # Try to find the file in the static/uploads directory
                base_dir = Path(current_app.root_path) / 'static' / 'uploads'
                possible_locations = [
                    base_dir / self.filename,  # Try root uploads directory
                    base_dir / str(self.folder_id) / self.filename if self.folder_id else None  # Try folder
                ]
                
                for location in possible_locations:
                    if location and location.exists():
                        # Update the file_path to match the actual location
                        rel_path = location.relative_to(Path(current_app.root_path) / 'static')
                        self.file_path = str(rel_path).replace('\\', '/')
                        db.session.commit()
                        current_app.logger.info(f"Fixed file path for {self.filename}")
                        return True
                return False
            return True
        except Exception as e:
            current_app.logger.error(f"Error validating file path for {self.filename}: {str(e)}")
            return False
        
    def cleanup_folder(self):
        """Remove empty folder after file deletion"""
        if self.folder_id is None:
            return
            
        try:
            folder_path = self.get_folder_path()
            # Check if folder exists and is empty
            if folder_path.exists() and not any(folder_path.iterdir()):
                folder_path.rmdir()
                current_app.logger.info(f"Removed empty folder: {folder_path}")
        except Exception as e:
            current_app.logger.error(f"Error cleaning up folder {folder_path}: {str(e)}")
        
    def delete_file(self):
        """Delete the file from storage when deleting the document"""
        try:
            file_path = self.get_file_path()
            if file_path and file_path.exists():
                file_path.unlink()
                # After deleting file, check if folder is empty and clean up
                self.cleanup_folder()
                return True
        except Exception as e:
            current_app.logger.error(f"Error deleting file {self.filename}: {str(e)}")
            return False
        return False
    
    def __repr__(self):
        return f'<Document {self.original_filename}>'

    def cleanup(self):
        """Clean up document files explicitly"""
        try:
            if self.file_path:
                file_path = self.get_file_path()
                if file_path and file_path.exists():
                    file_path.unlink()
                    self.cleanup_folder()
                    return True
        except Exception as e:
            current_app.logger.error(f"Error cleaning up document {self.id}: {str(e)}")
        return False
    
    @classmethod
    def cleanup_orphaned_files(cls):
        """Clean up any files that don't have corresponding database records"""
        try:
            if not current_app:
                raise RuntimeError("No application context")
                
            base_dir = Path(current_app.root_path) / 'static' / 'uploads'
            if not base_dir.exists():
                return
            
            # Get all known file paths from database
            known_files = {doc.filename for doc in cls.query.all()}
            
            # Check all files in uploads directory
            for file_path in base_dir.rglob('*'):
                if file_path.is_file() and file_path.name not in known_files:
                    try:
                        file_path.unlink()
                        current_app.logger.info(f"Removed orphaned file: {file_path}")
                    except Exception as e:
                        current_app.logger.error(f"Error removing orphaned file {file_path}: {str(e)}")
            
            # Clean up empty folders
            for folder_path in base_dir.rglob('*'):
                if folder_path.is_dir() and not any(folder_path.iterdir()):
                    try:
                        folder_path.rmdir()
                        current_app.logger.info(f"Removed empty folder: {folder_path}")
                    except Exception as e:
                        current_app.logger.error(f"Error removing empty folder {folder_path}: {str(e)}")
                        
        except Exception as e:
            current_app.logger.error(f"Error during orphaned file cleanup: {str(e)}")

    def validate_folder_access(self, folder_id):
        """Validate that a folder exists and user has access"""
        if folder_id is None:
            return True
            
        folder = Folder.query.get(folder_id)
        if not folder:
            raise ValueError("Specified folder does not exist")
        if folder.user_id != self.user_id:
            raise ValueError("You do not have permission to access this folder")
        return True
    
    def move_to_folder(self, new_folder_id):
        """Move file to a new folder"""
        try:
            # Store old folder ID for recovery in case of failure
            old_folder_id = self.folder_id
            
            # Validate new folder
            self.validate_folder_access(new_folder_id)
            
            # If destination is the same as current, do nothing
            if new_folder_id == old_folder_id:
                return True
                
            # Get current path before changing folder_id
            current_path = self.get_file_path()
            if not current_path or not current_path.exists():
                raise FileNotFoundError(f"Source file not found: {self.filename}")
            
            # Update folder_id to get new path
            self.folder_id = new_folder_id
            
            # Create destination folder if needed
            new_folder_path = self.get_folder_path()
            new_folder_path.mkdir(parents=True, exist_ok=True)
            
            # Define new file path
            new_file_path = new_folder_path / self.filename
            
            # Move the file
            current_path.rename(new_file_path)
            
            # Update file path in database
            rel_path = 'uploads'
            if new_folder_id:
                rel_path = f"{rel_path}/{new_folder_id}"
            self.file_path = f"{rel_path}/{self.filename}"
            
            # Clean up old folder if empty
            if old_folder_id:
                old_folder_path = Path(current_app.root_path) / 'static' / 'uploads' / str(old_folder_id)
                if old_folder_path.exists() and not any(old_folder_path.iterdir()):
                    old_folder_path.rmdir()
                    current_app.logger.info(f"Removed empty folder: {old_folder_path}")
            
            return True
            
        except Exception as e:
            # Restore original folder_id on failure
            self.folder_id = old_folder_id
            current_app.logger.error(f"Error moving file {self.filename}: {str(e)}")
            raise Exception(f"Error moving file: {str(e)}")


class VitalMeasurement(db.Model):
    """Model for storing vital sign measurements"""
    __tablename__ = 'vital_measurements'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    vital_type = db.Column(db.String(50), nullable=False)  # blood_pressure, heart_rate, etc.
    value = db.Column(db.String(50), nullable=False)  # Actual measurement value (e.g., "120/80" for BP)
    unit = db.Column(db.String(20), nullable=False)  # mmHg, bpm, etc.
    status = db.Column(db.String(20), default='normal')  # normal, elevated, etc.
    notes = db.Column(db.Text)
    measured_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    @classmethod
    def get_latest_vitals(cls, user_id, vital_type=None, limit=5):
        """Get the latest vital measurements for a user"""
        query = cls.query.filter_by(user_id=user_id)
        if vital_type:
            query = query.filter_by(vital_type=vital_type)
        return query.order_by(cls.measured_at.desc()).limit(limit).all()
    
    def __repr__(self):
        return f'<VitalMeasurement {self.vital_type}: {self.value} {self.unit}>'


class MedicalVisit(db.Model):
    """Model for storing medical visit information"""
    __tablename__ = 'medical_visits'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    provider = db.Column(db.String(100), nullable=False)  # Doctor/hospital name
    visit_type = db.Column(db.String(50), nullable=False)  # Checkup, consultation, etc.
    diagnosis = db.Column(db.Text)
    notes = db.Column(db.Text)
    visit_date = db.Column(db.DateTime, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    documents = db.relationship('Document', secondary='visit_documents', backref='medical_visits')
    
    def __repr__(self):
        return f'<MedicalVisit {self.visit_type} with {self.provider} on {self.visit_date}>'


# Association table for medical visits and documents
visit_documents = db.Table('visit_documents',
    db.Column('visit_id', db.Integer, db.ForeignKey('medical_visits.id'), primary_key=True),
    db.Column('document_id', db.Integer, db.ForeignKey('documents.id'), primary_key=True)
)


class Conversation(db.Model):
    """Model for storing chat conversations"""
    __tablename__ = 'conversations'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    title = db.Column(db.String(100), default='New Conversation')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    messages = db.relationship('Message', backref='conversation', lazy='dynamic', cascade='all, delete-orphan')
    
    @property
    def message_count(self):
        """Get the number of messages in the conversation"""
        return self.messages.count()
    
    def __repr__(self):
        return f'<Conversation {self.title}>'


class Message(db.Model):
    """Model for storing individual chat messages"""
    __tablename__ = 'messages'
    
    id = db.Column(db.Integer, primary_key=True)
    conversation_id = db.Column(db.Integer, db.ForeignKey('conversations.id'), nullable=False)
    sender = db.Column(db.String(20), nullable=False)  # 'user' or 'ai'
    content = db.Column(db.Text, nullable=False)
    has_attachment = db.Column(db.Boolean, default=False)
    attachment_path = db.Column(db.String(255))
    attachment_type = db.Column(db.String(50))  # image, pdf, audio, etc.
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f'<Message from {self.sender} at {self.created_at}>'

