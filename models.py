from datetime import datetime
import os
import shutil
import uuid
import hashlib
import bcrypt
import json
from pathlib import Path
from flask import current_app
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import google.generativeai as genai

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
    # Note: FolderSummary relationship is defined in the FolderSummary model
    
    def __repr__(self):
        return f'<Folder {self.name}>'



class FolderSummary(db.Model):
    """Model for storing AI-generated summaries of folder contents using Gemini 2.0"""
    __tablename__ = 'folder_summaries'
    
    id = db.Column(db.Integer, primary_key=True)
    folder_id = db.Column(db.Integer, db.ForeignKey('folders.id'), nullable=False, unique=True)
    summary_text = db.Column(db.Text, nullable=True)
    last_updated = db.Column(db.DateTime, default=datetime.utcnow)
    file_hash = db.Column(db.String(128), nullable=True)
    
    # Add minimum time between regenerations (30 minutes)
    REGENERATION_COOLDOWN = 1800  # seconds
    
    # Relationship
    folder = db.relationship('Folder', backref=db.backref('summary', uselist=False, cascade='all, delete-orphan'))
    
    def __repr__(self):
        return f'<FolderSummary for folder_id {self.folder_id}>'
    
    @staticmethod
    def calculate_folder_hash(folder_id):
        """
        Calculate a hash representing the state of all files in a folder.
        This hash changes when files are added, removed, or modified.
        """
        try:
            # Get all documents in the folder
            documents = Document.query.filter_by(folder_id=folder_id).all()
            
            # Sort by filename to ensure consistent order
            documents.sort(key=lambda x: x.filename)
            
            # Create a list of (filename, file_hash, file_size) tuples
            file_data = [(doc.filename, doc.content_hash, doc.file_size) for doc in documents]
            
            # Convert to string and hash
            file_data_str = json.dumps(file_data)
            folder_hash = hashlib.sha256(file_data_str.encode()).hexdigest()
            
            return folder_hash
        except Exception as e:
            current_app.logger.error(f"Error calculating folder hash: {str(e)}")
            return None
    
    @staticmethod
    def needs_update(folder_id, current_hash=None, force_refresh=False):
        """
        Check if the summary needs to be updated based on hash changes and cooldown period.
        
        Args:
            folder_id: The ID of the folder to check
            current_hash: Optional pre-calculated hash
            force_refresh: If True, ignore cooldown period
            
        Returns:
            bool: True if summary needs updating, False otherwise
        """
        try:
            if current_hash is None:
                current_hash = FolderSummary.calculate_folder_hash(folder_id)
                
            if current_hash is None:
                current_app.logger.warning(f"Could not calculate hash for folder {folder_id}")
                return True
                
            summary = FolderSummary.query.filter_by(folder_id=folder_id).first()
            
            # If no summary exists, definitely need update
            if not summary:
                current_app.logger.info(f"No existing summary found for folder {folder_id}")
                return True
                
            # Check if hash has changed
            hash_changed = not summary.file_hash or summary.file_hash.lower() != current_hash.lower()
            
            # If hash unchanged and not forcing refresh, check cooldown period
            if not hash_changed and not force_refresh:
                # Check if enough time has passed since last update
                if summary.last_updated:
                    elapsed = (datetime.utcnow() - summary.last_updated).total_seconds()
                    if elapsed < FolderSummary.REGENERATION_COOLDOWN:
                        current_app.logger.debug(
                            f"Skipping regeneration for folder {folder_id}, "
                            f"last updated {elapsed:.0f} seconds ago"
                        )
                        return False
                        
            if hash_changed:
                current_app.logger.info(
                    f"Hash changed for folder {folder_id}\n"
                    f"Stored hash: {summary.file_hash}\n"
                    f"Current hash: {current_hash}"
                )
            
            return True
            
        except Exception as e:
            current_app.logger.error(f"Error checking if summary needs update: {str(e)}")
            return True
            
    @staticmethod
    def hash_changed(folder_id, current_hash=None):
        """
        Check if the folder hash has changed from the stored hash.
        Returns True if hash has changed or if no summary exists yet.
        
        Deprecated: Use needs_update() instead.
        """
        # Calculate current hash if not provided
        if current_hash is None:
            current_hash = FolderSummary.calculate_folder_hash(folder_id)
            
        # Get existing summary
        summary = FolderSummary.query.filter_by(folder_id=folder_id).first()
        
        # If no summary or hash has changed, return True
        if not summary or summary.file_hash != current_hash:
            return True
            
        return False
    
    @staticmethod
    def generate_summary(folder_id):
        """
        Generate a summary of the folder contents using Gemini 2.0 Flash.
        Uploads all files in the folder directly to the Gemini API as context.
        """
        try:
            # Calculate current folder hash
            current_hash = FolderSummary.calculate_folder_hash(folder_id)
            
            # Check if folder has files
            documents = Document.query.filter_by(folder_id=folder_id).all()
            if not documents:
                return "This folder is empty."
            
            # Get existing summary
            summary = FolderSummary.query.filter_by(folder_id=folder_id).first()
            
            # If hash hasn't changed and we have a summary, return existing summary
            if summary and summary.file_hash == current_hash and summary.summary_text:
                current_app.logger.debug(f"Using cached summary for folder {folder_id}")
                return summary.summary_text
            
            # Initialize Gemini
            api_key = current_app.config.get('GEMINI_API_KEY')
            if not api_key:
                current_app.logger.error("GEMINI_API_KEY not found in configuration")
                return "Unable to generate summary: API key not configured."
            
            genai.configure(api_key=api_key)
            model = genai.GenerativeModel('gemini-1.5-flash')
            
            # Get folder name for context
            folder_obj = Folder.query.get(folder_id)
            folder_name = folder_obj.name if folder_obj else f"Folder #{folder_id}"
            
            # Create initial text prompt
            text_prompt = f"""
            Generate a comprehensive medical analysis of the contents in folder "{folder_name}". I'll provide all medical documents and images as context.
            
            Please analyze all content and structure your response as follows (within 200-300 words):
            
            1. MEDICAL SUMMARY
               - List key medical conditions, diagnoses, and ongoing treatments
               - Highlight any critical or abnormal values from lab reports
               - Note significant findings from imaging studies
               - Identify any urgent medical concerns or red flags
            
            2. CHRONOLOGICAL TIMELINE
               - Document progression of medical events
               - Track changes in vital signs or test results over time
               - Note significant treatment changes or interventions
            
            3. CROSS-DOCUMENT ANALYSIS
               - Correlate findings between different medical reports
               - Compare current results with previous baselines
               - Identify trends or patterns across documents
               - Link related findings from different specialists/visits
            
            4. IMAGE ANALYSIS
               For medical imaging (X-rays, MRI, CT scans, etc.):
               - Describe key anatomical findings
               - Note any abnormalities or significant changes
               - Compare with previous imaging if available
               - Highlight areas requiring follow-up
            
            5. RECOMMENDATIONS & FOLLOW-UP
               - List pending tests or scheduled procedures
               - Document recommended follow-up appointments
               - Note any specific monitoring requirements
               - Highlight preventive care measures
            
            6. TECHNICAL TERMS
               - Define any complex medical terminology used
               - Explain abbreviations and technical measurements
               - Clarify medical jargon in plain language
            
            IMPORTANT: Prioritize clinically significant findings and abnormal results. If critical values or urgent findings are present, highlight these at the beginning of the summary.
            """
            
            # Prepare content parts for the API call - starting with the text prompt
            parts = [text_prompt]
            file_info = []
            
            # Process each document to add as context
            for doc in documents:
                file_path = doc.get_file_path()
                if not file_path or not file_path.exists():
                    current_app.logger.warning(f"File not found: {doc.original_filename}")
                    file_info.append(f"File: {doc.original_filename} (File not found)")
                    continue
                
                file_type = doc.file_type.lower()
                
                try:
                    # For text-based files, read content and add as text
                    if file_type in ['txt', 'md', 'csv', 'json', 'xml', 'html']:
                        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                            content = f.read()
                            # Include file content as text
                            parts.append(f"File: {doc.original_filename}\n\n{content}")
                            file_info.append(f"Text file: {doc.original_filename}")
                    
                    # For PDFs, extract both text and images using pdf_reader.py
                    elif file_type == 'pdf':
                        current_app.logger.info(f"Processing PDF: {doc.original_filename}")
                        
                        # Import PDF utilities
                        from pdf_reader import extract_pdf_content
                        
                        # Extract both text and images
                        pdf_content_result = extract_pdf_content(str(file_path), extract_images=True)
                        
                        if not pdf_content_result['success']:
                            current_app.logger.error(f"Failed to extract PDF content: {pdf_content_result['text_status']}")
                            file_info.append(f"File: {doc.original_filename} (Could not extract PDF content)")
                            continue
                        
                        # Get text content and add it
                        text_content = pdf_content_result['text']
                        if text_content and not text_content.startswith("Error:"):
                            parts.append(f"PDF Text from {doc.original_filename}:\n\n{text_content}")
                            file_info.append(f"PDF text from: {doc.original_filename}")
                        
                        # Get images and add them (up to 15 per file to avoid context limits)
                        images = pdf_content_result['images']
                        if images:
                            current_app.logger.info(f"Found {len(images)} images in PDF: {doc.original_filename}")
                            
                            # Limit to 15 images per file to avoid context limits
                            image_count = min(len(images), 15)
                            for i in range(image_count):
                                img = images[i]
                                if 'data' in img and img['data']:
                                    # Add image as context with page information
                                    image_part = {
                                        'mime_type': f'image/{img["format"]}',
                                        'data': img['data']
                                    }
                                    parts.append(image_part)
                                    file_info.append(f"Image {i+1} from page {img['page_num']} of {doc.original_filename}")
                    
                    # For images, add them directly
                    elif file_type in ['jpg', 'jpeg', 'png', 'gif', 'webp']:
                        with open(file_path, 'rb') as img_file:
                            import base64
                            # Read and encode the image data
                            image_data = base64.b64encode(img_file.read()).decode('utf-8')
                            
                            # Add image as context
                            image_part = {
                                'mime_type': f'image/{file_type}',
                                'data': image_data
                            }
                            parts.append(image_part)
                            file_info.append(f"Image file: {doc.original_filename}")
                    
                    # For other files, just include metadata
                    else:
                        file_info.append(f"File: {doc.original_filename} (Type: {doc.file_type}, Size: {doc.file_size} bytes)")
                
                except Exception as e:
                    current_app.logger.error(f"Error processing file {doc.filename}: {str(e)}")
                    file_info.append(f"File: {doc.original_filename} (Error: {str(e)})")
            
            # Add file info summary to the prompt
            file_info_text = "Files included in this analysis:\n" + "\n".join([f"- {info}" for info in file_info])
            parts.insert(1, file_info_text)  # Insert after the main prompt but before the file contents
            
            current_app.logger.info(f"Sending {len(parts)} content parts to Gemini API for folder {folder_id}")
            
            # Generate summary with all content parts
            try:
                response = model.generate_content(parts)
                summary_text = response.text
                
                # Begin a new transaction (ensure any previous transaction is rolled back)
                db.session.rollback()
                
                try:
                    # First, get the document's content_hash directly for single-document folders
                    document = Document.query.filter_by(folder_id=folder_id).first()
                    if document:
                        current_hash = document.content_hash
                        current_app.logger.info(f"Using document content_hash for folder {folder_id}: {current_hash}")
                    else:
                        current_app.logger.warning(f"No document found for folder {folder_id}, using calculated hash")
                        # Fall back to calculated hash if no document is found
                        current_hash = FolderSummary.calculate_folder_hash(folder_id)
                    
                    # Use SQLAlchemy's merge operation for proper upsert behavior
                    existing_summary = FolderSummary.query.filter_by(folder_id=folder_id).first()
                    
                    if existing_summary:
                        # Update existing record
                        existing_summary.summary_text = summary_text
                        existing_summary.file_hash = current_hash
                        existing_summary.last_updated = datetime.utcnow()
                        current_app.logger.info(f"Updated summary for folder {folder_id} with hash {current_hash}")
                    else:
                        # Create new record
                        new_summary = FolderSummary(
                            folder_id=folder_id,
                            summary_text=summary_text,
                            file_hash=current_hash,
                            last_updated=datetime.utcnow()
                        )
                        db.session.add(new_summary)
                        current_app.logger.info(f"Created new summary for folder {folder_id} with hash {current_hash}")
                    
                    # Commit the changes
                    db.session.commit()
                    return summary_text
                    
                except Exception as db_error:
                    # Rollback on any database error
                    db.session.rollback()
                    current_app.logger.error(f"Database error saving summary: {str(db_error)}")
                    return f"Error saving summary: {str(db_error)}"
                
            except Exception as e:
                # Rollback any pending transaction
                db.session.rollback()
                current_app.logger.error(f"Error generating summary with Gemini: {str(e)}")
                return f"Error generating summary: {str(e)}"
                
        except Exception as e:
            current_app.logger.error(f"Error in generate_summary: {str(e)}")
            return "An error occurred while generating the folder summary."
    
    @staticmethod
    def get_or_generate_summary(folder_id, force_refresh=False):
        """
        Get the existing summary or generate a new one if needed.
        
        Args:
            folder_id: The ID of the folder to summarize
            force_refresh: If True, force regeneration of summary
            
        Returns:
            str: The summary text
        """
        try:
            # Check if folder exists
            folder = Folder.query.get(folder_id)
            if not folder:
                return "Folder not found."
            
            # Calculate current hash
            current_hash = FolderSummary.calculate_folder_hash(folder_id)
            
            # Check if we need to update the summary
            if FolderSummary.needs_update(folder_id, current_hash, force_refresh):
                return FolderSummary.generate_summary(folder_id)
            
            # Get existing summary
            summary = FolderSummary.query.filter_by(folder_id=folder_id).first()
            if summary and summary.summary_text:
                current_app.logger.debug(f"Using cached summary for folder {folder_id}")
                return summary.summary_text
            
            # If we get here, generate a new summary
            return FolderSummary.generate_summary(folder_id)
        
        except Exception as e:
            current_app.logger.error(f"Error in get_or_generate_summary: {str(e)}")
            return "An error occurred while retrieving the folder summary."


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
        if self.folder_id is not None and self.folder_id != 0:
            # Ensure we have a string folder id and create a subfolder
            folder_path = base_upload_dir / str(self.folder_id)
            return folder_path
        return base_upload_dir
    
    def ensure_folder_exists(self):
        """Ensure the upload folder exists and is accessible"""
        folder_path = self.get_folder_path()
        try:
            # Create the folder if it doesn't exist
            folder_path.mkdir(parents=True, exist_ok=True)
            
            # Log successful folder creation/verification
            current_app.logger.debug(f"Ensured folder exists: {folder_path}")
            
            # Check write permissions
            if not os.access(folder_path, os.W_OK):
                raise OSError(f"No write permission to folder: {folder_path}")
                
            return True
        except OSError as e:
            current_app.logger.error(f"Could not create/access folder: {folder_path}, error: {str(e)}")
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
            # Generate a consistent path that matches the actual file location
            if self.folder_id is not None and self.folder_id != 0:
                # If a folder is specified, include it in the path
                rel_path = f"uploads/{self.folder_id}/{unique_filename}"
            else:
                # Otherwise, store directly in uploads folder
                rel_path = f"uploads/{unique_filename}"
                
            # Store the path with forward slashes for consistency
            self.file_path = rel_path
            
            # Ensure filename is set properly
            if not hasattr(self, 'filename') or not self.filename:
                self.filename = unique_filename
                
            # Log the file path for debugging
            current_app.logger.debug(f"File saved at: {file_path}, stored path: {self.file_path}")
            
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
        full_path = Path(current_app.root_path) / 'static' / self.file_path
        
        # Debug log to help troubleshoot path issues
        current_app.logger.debug(f"Full file path for {self.original_filename}: {full_path}")
        
        return full_path
        
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
                current_app.logger.warning(f"No file_path for document {self.id}")
                return False
                
            # Check if file exists at the stored path
            file_path = self.get_file_path()
            if file_path and file_path.exists():
                current_app.logger.debug(f"File found at expected path: {file_path}")
                return True
                
            # If file not found, try to find it in possible locations
            current_app.logger.warning(f"File not found at {file_path}, searching for alternatives")
            base_dir = Path(current_app.root_path) / 'static' / 'uploads'
            
            # Create a list of possible locations to search
            possible_locations = []
            
            # Check in root uploads directory
            possible_locations.append(base_dir / self.filename)
            
            # Check in folder-specific directory if folder_id exists
            if self.folder_id is not None and self.folder_id != 0:
                possible_locations.append(base_dir / str(self.folder_id) / self.filename)
            
            # Log all possible locations we're checking
            current_app.logger.debug(f"Searching for {self.filename} in: {possible_locations}")
            
            # Check each location
            for location in possible_locations:
                if location and location.exists():
                    # Update the file_path to match the actual location
                    rel_path = location.relative_to(Path(current_app.root_path) / 'static')
                    self.file_path = str(rel_path).replace('\\', '/')
                    db.session.commit()
                    current_app.logger.info(f"Fixed file path for {self.filename}: {self.file_path}")
                    return True
                    
            # If we couldn't find the file, log this
            current_app.logger.error(f"Could not find file {self.filename} in any expected location")
            return False
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
    
    def process_pdf_images(self, from_flask_login=True, extract_text=True):
        """
        Process PDF content (text and images) using Gemini 2.0 Flash model.
        
        Args:
            from_flask_login (bool): Whether this method is being called from a Flask route with
                                     flask_login's current_user available
            extract_text (bool): Whether to extract and process text along with images
        
        Returns:
            dict: Dictionary containing:
                - 'success' (bool): Whether the processing was successful
                - 'results' (list): List of dictionaries with processed PDF content results by page
                - 'message' (str): Success or error message
        """
        try:
            # Verify user has access to this document if called from Flask route
            if from_flask_login:
                from flask_login import current_user
                if not current_user or not current_user.is_authenticated or self.user_id != current_user.id:
                    return {
                        'success': False,
                        'results': [],
                        'message': 'Access denied: You do not have permission to process this document'
                    }
            
            # Get file path and verify it exists
            file_path = self.get_file_path()
            if not file_path or not file_path.exists():
                current_app.logger.error(f"File not found or inaccessible: {file_path}")
                return {
                    'success': False,
                    'results': [],
                    'message': 'File not found or inaccessible'
                }
            
            # Check if file is PDF
            if self.file_type.lower() != 'pdf':
                return {
                    'success': False,
                    'results': [],
                    'message': 'File is not a PDF'
                }
            
            # Extract both text and images from PDF
            from pdf_reader import extract_pdf_content, extract_pdf_images, extract_pdf_text
            
            # Determine what to extract based on the extract_text parameter
            if extract_text:
                current_app.logger.info(f"Extracting both text and images from PDF: {self.original_filename}")
                pdf_content_result = extract_pdf_content(str(file_path), extract_images=True)
                
                if not pdf_content_result['success']:
                    current_app.logger.error(f"Failed to extract PDF content: {pdf_content_result['text_status']}")
                    return {
                        'success': False,
                        'results': [],
                        'message': f'Failed to extract PDF content: {pdf_content_result["text_status"]}'
                    }
                
                # Extract text and images from the result
                text_content = pdf_content_result['text']
                images = pdf_content_result['images']
                page_count = pdf_content_result['page_count']
                
                # Log extraction results
                current_app.logger.info(f"Extracted {len(images)} images and {page_count} pages of text from PDF")
                
                # Check if no images were found but text exists
                if not images and not text_content.strip():
                    return {
                        'success': True,
                        'results': [],
                        'message': 'No content found in PDF document'
                    }
            else:
                # Extract only images (original behavior)
                current_app.logger.info(f"Extracting only images from PDF: {self.original_filename}")
                extraction_result = extract_pdf_images(str(file_path))
                
                if not extraction_result['success']:
                    return {
                        'success': False,
                        'results': [],
                        'message': f'Failed to extract images: {extraction_result["message"]}'
                    }
                
                images = extraction_result['images']
                text_content = None
                
                # Get page count for reference
                try:
                    with open(str(file_path), 'rb') as file:
                        pdf_reader = PyPDF2.PdfReader(file)
                        page_count = len(pdf_reader.pages)
                except Exception as e:
                    current_app.logger.error(f"Error getting page count: {str(e)}")
                    page_count = 0
                
                if not images:
                    return {
                        'success': True,
                        'results': [],
                        'message': 'No images found in PDF'
                    }
            
            # Initialize Gemini (using same configuration as FolderSummary)
            api_key = current_app.config.get('GEMINI_API_KEY')
            if not api_key:
                current_app.logger.error("GEMINI_API_KEY not found in configuration")
                return {
                    'success': False,
                    'results': [],
                    'message': 'Gemini API key not configured'
                }
            
            import google.generativeai as genai
            genai.configure(api_key=api_key)
            model = genai.GenerativeModel('gemini-1.5-flash')
            
            # Organize content by page for processing
            page_content = {}
            
            # First, organize images by page
            for img in images:
                page_num = img['page_num']
                if page_num not in page_content:
                    page_content[page_num] = {'images': [], 'text': None}
                page_content[page_num]['images'].append(img)
            
            # If text extraction was enabled, split text by page and add to page_content
            if extract_text and text_content and not text_content.startswith("Error:"):
                # Split the text content by page if possible
                # This is a simplified approach; in reality, you might need a more sophisticated
                # method to accurately split PDF text by page
                try:
                    with open(str(file_path), 'rb') as file:
                        pdf_reader = PyPDF2.PdfReader(file)
                        for page_num in range(len(pdf_reader.pages)):
                            page = pdf_reader.pages[page_num]
                            page_text = page.extract_text()
                            
                            if page_num + 1 not in page_content:
                                page_content[page_num + 1] = {'images': [], 'text': None}
                            
                            page_content[page_num + 1]['text'] = page_text
                except Exception as e:
                    current_app.logger.error(f"Error splitting text by page: {str(e)}")
                    # If splitting fails, use the whole text for all pages with images
                    for page_num in page_content.keys():
                        page_content[page_num]['text'] = text_content
            
            # Process content page by page with Gemini
            results = []
            
            for page_num, content in sorted(page_content.items()):
                try:
                    page_images = content['images']
                    page_text = content['text']
                    
                    # If this page has images
                    if page_images:
                        for img_idx, img_data in enumerate(page_images):
                            try:
                                # Create a context-aware prompt that includes text if available
                                if page_text and page_text.strip():
                                    text_preview = page_text[:1000] + "..." if len(page_text) > 1000 else page_text
                                    prompt = f"""
                                    Analyze this medical image from page {page_num} of the PDF document along with the text from the same page. 
                                    
                                    Text content from page {page_num}:
                                    {text_preview}
                                    
                                    Please provide:
                                    1. Description of what the image shows
                                    2. Any notable findings or abnormalities visible in the image
                                    3. Potential medical significance if applicable
                                    4. How the image relates to the text content on the same page (if relevant)
                                    
                                    Be clear and professional in your analysis, and indicate if the image quality 
                                    is too poor to make conclusive observations.
                                    """
                                else:
                                    # Create prompt for just the image if no text is available
                                    prompt = f"""
                                    Analyze this medical image from page {page_num} of the PDF document. Please provide:
                                    1. Description of what the image shows
                                    2. Any notable findings or abnormalities visible in the image
                                    3. Potential medical significance if applicable
                                    
                                    Be clear and professional in your analysis, and indicate if the image quality 
                                    is too poor to make conclusive observations.
                                    """
                                
                                # Create a multipart message with the prompt and image
                                parts = [prompt]
                                
                                # Create a base64 image part for Gemini
                                image_part = {
                                    'mime_type': f'image/{img_data["format"]}',
                                    'data': img_data['data']
                                }
                                parts.append(image_part)
                                
                                # Process image with Gemini
                                response = model.generate_content(parts)
                                
                                # Add processed result
                                result_item = {
                                    'page_num': page_num,
                                    'image_idx': img_idx,
                                    'image_data': img_data['data'],  # base64 encoded image
                                    'analysis': response.text,
                                    'format': img_data['format'],
                                    'content_type': 'image',
                                    'has_text_context': bool(page_text and page_text.strip())
                                }
                                
                                results.append(result_item)
                                current_app.logger.info(f"Successfully processed image {img_idx+1} from page {page_num}")
                                
                            except Exception as img_err:
                                current_app.logger.error(f"Error processing image {img_idx+1} from page {page_num}: {str(img_err)}")
                                results.append({
                                    'page_num': page_num,
                                    'image_idx': img_idx,
                                    'image_data': img_data['data'],
                                    'analysis': f"Error processing image: {str(img_err)}",
                                    'format': img_data['format'],
                                    'content_type': 'image',
                                    'error': True
                                })
                    
                    # If this page has text but no images, or if there are images but we want to process text separately
                    elif page_text and page_text.strip() and extract_text:
                        try:
                            # Create prompt for text-only analysis
                            text_preview = page_text[:3000] + "..." if len(page_text) > 3000 else page_text
                            prompt = f"""
                            Analyze this medical text from page {page_num} of the PDF document. Please provide:
                            1. Summary of the key information presented
                            2. Any medical findings, diagnoses, or treatments mentioned
                            3. Important medical terminology explained in simple terms
                            
                            Text content from page {page_num}:
                            {text_preview}
                            
                            Be clear and professional in your analysis.
                            """
                            
                            # Process text with Gemini
                            response = model.generate_content(prompt)
                            
                            # Add processed result
                            results.append({
                                'page_num': page_num,
                                'text_preview': text_preview[:100] + "..." if len(text_preview) > 100 else text_preview,
                                'analysis': response.text,
                                'content_type': 'text'
                            })
                            
                            current_app.logger.info(f"Successfully processed text from page {page_num}")
                            
                        except Exception as text_err:
                            current_app.logger.error(f"Error processing text from page {page_num}: {str(text_err)}")
                            results.append({
                                'page_num': page_num,
                                'text_preview': page_text[:100] + "..." if len(page_text) > 100 else page_text,
                                'analysis': f"Error processing text: {str(text_err)}",
                                'content_type': 'text',
                                'error': True
                            })
                
                except Exception as page_err:
                    current_app.logger.error(f"Error processing page {page_num}: {str(page_err)}")
                    results.append({
                        'page_num': page_num,
                        'analysis': f"Error processing page: {str(page_err)}",
                        'content_type': 'error',
                        'error': True
                    })
            
            # Sort results by page number for consistency
            results.sort(key=lambda x: (x['page_num'], x.get('image_idx', 0)))
            
            # Count successful and failed items
            error_count = sum(1 for item in results if item.get('error', False))
            success_count = len(results) - error_count
            
            # Create appropriate message based on results
            if not results:
                message = "No content was processed from the PDF document."
            elif error_count == 0:
                message = f"Successfully processed all {len(results)} items from the PDF document."
            elif success_count == 0:
                message = f"Failed to process any content from the PDF document."
            else:
                message = f"Processed {success_count} items successfully with {error_count} errors."
                
            current_app.logger.info(f"PDF processing complete: {message}")
            
            return {
                'success': True,
                'results': results,
                'message': message,
                'document_name': self.original_filename,
                'page_count': page_count
            }
            
        except Exception as e:
            current_app.logger.error(f"Error in process_pdf_images: {str(e)}", exc_info=True)
            return {
                'success': False,
                'results': [],
                'message': f'Error processing PDF content: {str(e)}'
            }

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

