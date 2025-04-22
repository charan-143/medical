from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify, current_app, send_file, abort, make_response
from flask_login import login_required, current_user
from extensions import db
from models import Folder, Document
import os
import uuid
import logging
import mimetypes
from pathlib import Path
from werkzeug.utils import secure_filename, safe_join
from datetime import datetime
from sqlalchemy.exc import SQLAlchemyError

# Set up logging
logger = logging.getLogger(__name__)

dashboard = Blueprint('dashboard', __name__, template_folder='templates')

@dashboard.route('/')
@login_required
def index():
    # Main dashboard view with vitals, recent visits, etc.
    return render_template('dashboard/index.html')

@dashboard.route('/overview')
@login_required
def overview():
    # Overview page with medical scans, visits, vitals charts
    return render_template('dashboard/overview.html')

@dashboard.route('/records')
@dashboard.route('/records/<int:folder_id>')
@login_required
def records(folder_id=None):
    """Display medical records organized in folders"""
    try:
        # Get subfolders and documents to display
        if folder_id:
            # If folder_id is provided, get that specific folder
            current_folder = Folder.query.filter_by(
                id=folder_id, 
                user_id=current_user.id
            ).first_or_404()
            
            subfolders = Folder.query.filter_by(
                parent_id=folder_id, 
                user_id=current_user.id
            ).order_by(Folder.name).all()
            
            documents = Document.query.filter_by(
                folder_id=folder_id, 
                user_id=current_user.id
            ).order_by(Document.upload_date.desc()).all()
            
            # Debug logging
            current_app.logger.debug(f"Current folder: {current_folder.name} (ID: {folder_id})")
        else:
            current_folder = None
            subfolders = Folder.query.filter_by(
                parent_id=None, 
                user_id=current_user.id
            ).order_by(Folder.name).all()
            
            documents = Document.query.filter_by(
                folder_id=None, 
                user_id=current_user.id
            ).order_by(Document.upload_date.desc()).all()
            
            current_app.logger.debug("Displaying root folder")

        # Debug logging for subfolders and documents
        current_app.logger.debug(f"Found {len(subfolders)} subfolders:")
        for folder in subfolders:
            current_app.logger.debug(f"  - {folder.name} (ID: {folder.id})")
            
        current_app.logger.debug(f"Found {len(documents)} documents:")
        for doc in documents:
            info = doc.get_file_info()
            current_app.logger.debug(
                f"  - {info['filename']} "
                f"(Path: {info['url_path']}, "
                f"Type: {info['file_type']}, "
                f"Exists: {info['file_exists']})"
            )
            
        # Build folder path for breadcrumb navigation
        folder_path = []
        temp_folder = current_folder
        while temp_folder and temp_folder.parent_id:
            parent = Folder.query.get(temp_folder.parent_id)
            if parent and parent.user_id == current_user.id:
                folder_path.insert(0, parent)
                temp_folder = parent
            else:
                break

        current_app.logger.debug("Template context:")
        current_app.logger.debug(f"  Current folder: {current_folder.name if current_folder else 'Root'}")
        current_app.logger.debug(f"  Folder path: {[f.name for f in folder_path]}")
        current_app.logger.debug(f"  Subfolders count: {len(subfolders)}")
        current_app.logger.debug(f"  Documents count: {len(documents)}")
        
        # Create context dictionary
        context = {
            'current_folder': current_folder,
            'folder_path': folder_path,
            'subfolders': subfolders,
            'documents': documents
        }
        
        # Validate and fix document paths before rendering
        if documents:
            for doc in documents:
                # Validate and fix paths if needed
                doc.validate_and_fix_path()
                url_path = doc.get_url_path()
                file_exists = doc.get_file_path().exists() if doc.get_file_path() else False
                logger.debug(f"Document {doc.original_filename}: URL={url_path}, exists={file_exists}")
        
        return render_template('dashboard/records.html', **context)
                          
    except Exception as e:
        logger.error(f"Error in records view: {str(e)}", exc_info=True)
        flash('Error loading records. Please try again.', 'error')
        return redirect(url_for('dashboard.index'))

@dashboard.route('/upload', methods=['GET', 'POST'])
@login_required
def upload():
    """Handle file upload(s) to the user's records"""
    if request.method == 'POST':
        # Check if folder_id is specified
        folder_id = request.form.get('folder_id')
        folder = None
        
        if folder_id:
            try:
                folder_id = int(folder_id)
                folder = Folder.query.get(folder_id)
                # Verify folder belongs to current user
                if not folder or folder.user_id != current_user.id:
                    flash('Invalid folder selected', 'error')
                    return redirect(url_for('dashboard.records'))
            except ValueError:
                flash('Invalid folder ID', 'error')
                return redirect(url_for('dashboard.records'))
        
        # Check if the post request has the file part
        if 'file' not in request.files:
            flash('No file part in the request', 'error')
            return redirect(request.referrer or url_for('dashboard.records'))
        
        file = request.files['file']
        
        if file.filename == '':
            flash('No file selected', 'error')
            return redirect(request.referrer or url_for('dashboard.records'))
        
        try:
            # Create a new document
            document = Document(
                user_id=current_user.id,
                folder_id=folder_id if folder else None,
                description=request.form.get('description', '')
            )
            
            # Save the file and update document properties
            document.save_file(file)
            
            # Add to database
            db.session.add(document)
            db.session.commit()
            
            flash(f'File "{document.original_filename}" uploaded successfully', 'success')
        except Exception as e:
            db.session.rollback()
            flash(f'Error uploading file: {str(e)}', 'error')
        
        # Return to the records view
        return redirect(url_for('dashboard.records', folder_id=folder_id))
    
    # For GET requests, render the upload form
    return render_template('dashboard/upload.html')

@dashboard.route('/upload_json', methods=['POST'])
@login_required
def upload_json():
    """AJAX endpoint for file upload with JSON response"""
    response = {
        'success': False,
        'message': '',
        'files': []
    }
    
    # Debug information
    logger.info("Upload request received from user %s", current_user.id)
    logger.debug("Files in request: %s", request.files)
    logger.debug("Form data: %s", request.form)
    logger.debug("Form data keys: %s", list(request.form.keys()))
    
    try:
    
        # Check if folder_id is specified
        folder_id = request.form.get('folder_id', '')
        folder = None
        validated_folder_id = None  # This will hold the validated folder ID
        
        logger.debug("Raw folder_id from form: %r", folder_id)
        
        # Check for various empty/null values that could be sent from frontend
        if folder_id and folder_id.strip() and folder_id.lower() not in ('null', 'undefined', '0', 'none'):
            try:
                validated_folder_id = int(folder_id)
                logger.debug("Converted folder_id to integer: %d", validated_folder_id)
                
                # If folder_id is 0, treat as None (root folder)
                if validated_folder_id == 0:
                    logger.debug("Folder ID is 0, treating as root folder (None)")
                    validated_folder_id = None
                else:
                    # Only query the database if we have a positive folder ID
                    folder = Folder.query.get(validated_folder_id)
                    logger.debug("Queried folder from database: %s", folder)
                    
                    # Verify folder belongs to current user
                    if not folder:
                        response['message'] = 'Folder not found'
                        logger.warning("Folder not found: %s", validated_folder_id)
                        return jsonify(response), 400
                    if folder.user_id != current_user.id:
                        response['message'] = 'Invalid folder selected'
                        logger.warning("User %s attempted to upload to invalid folder %s", current_user.id, validated_folder_id)
                        return jsonify(response), 400
                    
                    # Ensure the physical folder exists
                    folder_path = Path(current_app.root_path) / 'static' / 'uploads' / str(validated_folder_id)
                    logger.info("Ensuring folder exists: %s", folder_path)
                    try:
                        folder_path.mkdir(parents=True, exist_ok=True)
                    except Exception as e:
                        logger.error("Failed to create folder directory: %s", str(e))
                        response['message'] = 'Failed to create folder directory'
                        return jsonify(response), 500
            except ValueError:
                response['message'] = 'Invalid folder ID format'
                response['message'] = 'Invalid folder ID format'
                logger.warning("Invalid folder ID format: %s", folder_id)
                return jsonify(response), 400
        # Check if the post request has the file part
        if 'files[]' not in request.files:
            response['message'] = 'No file part in the request'
            logger.warning("No file part in the upload request")
            return jsonify(response), 400
        
        files = request.files.getlist('files[]')
        
        if not files or all(file.filename == '' for file in files):
            response['message'] = 'No files selected'
            logger.warning("No files selected in the upload request")
            return jsonify(response), 400
        
        # Track uploads for response
        uploaded_files = []
        # Use a set to track processed filenames and prevent duplicates
        # Use a set to track processed filenames and prevent duplicates
        processed_files = set()
        processed_hashes = set()
        
        for file in files:
            if file and file.filename:
                # Skip if we've already processed this file by name
                if file.filename in processed_files:
                    logger.info("Skipping duplicate filename: %s", file.filename)
                    continue
                
                # Compute file hash to check for content duplicates
                try:
                    file_hash = Document.compute_file_hash(file)
                    if file_hash in processed_hashes:
                        logger.info("Skipping duplicate content for file: %s", file.filename)
                        continue
                    processed_hashes.add(file_hash)
                except Exception as e:
                    logger.warning("Error computing hash for file %s: %s", file.filename, str(e))
                    # Continue without hash check if there's an error
                try:
                    # Create a new document
                    # Create a new document
                    logger.debug("Creating document with folder_id=%r", validated_folder_id)
                    document = Document(
                        user_id=current_user.id,
                        folder_id=validated_folder_id,  # Use our validated folder_id
                        description=request.form.get('description', '')
                    )
                    
                    # Log the folder info before saving
                    if validated_folder_id:
                        logger.debug("Using folder: %s (ID: %s)", 
                                    folder.name if folder else "Unknown", 
                                    validated_folder_id)
                    # Save the file and update document properties using validation
                    document.save_file(file)
                    
                    # Add to database
                    db.session.add(document)
                    
                    # Mark file as processed to prevent duplicates
                    processed_files.add(file.filename)
                    processed_hashes.add(document.content_hash)
                    
                    # Add to response
                    uploaded_files.append({
                        'name': document.original_filename,
                        'size': document.file_size,
                        'type': document.file_type,
                        'id': document.id,
                        'url': document.get_url_path()
                    })
                    
                    logger.info(
                        "Successfully processed file %s for user %s in folder %s",
                        file.filename,
                        current_user.id,
                        validated_folder_id if validated_folder_id else "root"
                    )
                    
                    # Additional debug information about file path
                    logger.debug(
                        "File saved with path: %s, folder_id: %s", 
                        document.file_path, 
                        document.folder_id
                    )
                except ValueError as e:
                    # Validation error
                    logger.warning("File validation error: %s", str(e))
                    response['message'] = str(e)
                    return jsonify(response), 400
                except Exception as e:
                    # If any file fails, rollback and return error
                    db.session.rollback()
                    logger.error("Error uploading file %s: %s", file.filename, str(e), exc_info=True)
                    response['message'] = f'Error uploading {file.filename}: {str(e)}'
                    return jsonify(response), 500
        
        # Commit all successful uploads
        # Commit all successful uploads
        if uploaded_files:
            try:
                db.session.commit()
                response['success'] = True
                response['files'] = uploaded_files
                response['message'] = f'{len(uploaded_files)} files uploaded successfully'
                
                # Log success
                logger.info(
                    "User %s successfully uploaded %d files to folder %s", 
                    current_user.id, 
                    len(uploaded_files), 
                    validated_folder_id if validated_folder_id else "root"
                )
                
                return jsonify(response), 200
            except SQLAlchemyError as e:
                db.session.rollback()
                logger.error("Database error saving uploads: %s", str(e), exc_info=True)
                response['message'] = f'Database error: {str(e)}'
                return jsonify(response), 500
        else:
            response['message'] = 'No files were uploaded'
            return jsonify(response), 400
    except Exception as e:
        logger.error("Unexpected error in upload_json: %s", str(e), exc_info=True)
        response['message'] = f'Server error: {str(e)}'
        return jsonify(response), 500


@dashboard.route('/get_folder_name_json')
@login_required
def get_folder_name_json():
    """Get folder name by ID"""
    try:
        folder_id = request.args.get('folder_id')
        
        if not folder_id:
            logger.warning("No folder ID provided in get_folder_name_json request")
            return jsonify({
                'success': False,
                'message': 'No folder ID provided'
            }), 400
        
        try:
            folder_id = int(folder_id)
        except ValueError:
            logger.warning("Invalid folder ID format: %s", folder_id)
            return jsonify({
                'success': False,
                'message': 'Invalid folder ID format'
            }), 400
            
        folder = Folder.query.get(folder_id)
        
        if not folder:
            logger.warning("Folder not found: %s", folder_id)
            return jsonify({
                'success': False,
                'message': 'Folder not found'
            }), 404
            
        if folder.user_id != current_user.id:
            logger.warning("User %s attempted to access unauthorized folder %s", current_user.id, folder_id)
            return jsonify({
                'success': False,
                'message': 'You do not have permission to access this folder'
            }), 403
        
        # Get the folder path for better context
        folder_path = []
        current = folder
        while current.parent_id is not None:
            parent = Folder.query.get(current.parent_id)
            if parent:
                folder_path.insert(0, {'id': parent.id, 'name': parent.name})
                current = parent
            else:
                break
        
        return jsonify({
            'success': True,
            'folder_name': folder.name,
            'folder_id': folder.id,
            'parent_id': folder.parent_id,
            'folder_path': folder_path,
            'created_at': folder.created_at.isoformat()
        })
    except SQLAlchemyError as e:
        logger.error("Database error in get_folder_name_json: %s", str(e), exc_info=True)
        return jsonify({
            'success': False,
            'message': f'Database error: {str(e)}'
        }), 500
    except Exception as e:
        logger.error("Unexpected error in get_folder_name_json: %s", str(e), exc_info=True)
        return jsonify({
            'success': False,
            'message': f'Server error: {str(e)}'
        }), 500
    
@dashboard.route('/create_folder_json', methods=['POST'])
@login_required
def create_folder_json():
    """Create a new folder and return JSON response"""
    response = {
        'success': False,
        'message': '',
        'folder_id': None
    }
    
    try:
        # Log the form data for debugging
        logger.debug("Create folder form data: %s", request.form)
        
        folder_name = request.form.get('folder_name')
        parent_id = request.form.get('parent_id')
        
        if not folder_name:
            logger.warning("No folder name provided in create_folder_json request by user %s", current_user.id)
            response['message'] = 'Folder name is required'
            return jsonify(response), 400
            
        # Create new folder
        new_folder = Folder(
            name=folder_name,
            user_id=current_user.id
        )
        
        # If parent_id is provided, set the parent folder
        if parent_id and parent_id.strip():
            try:
                parent_id = int(parent_id)
                parent_folder = Folder.query.get(parent_id)
                if parent_folder and parent_folder.user_id == current_user.id:
                    new_folder.parent_id = parent_id
                else:
                    logger.warning("User %s attempted to create folder in invalid parent folder %s", 
                                 current_user.id, parent_id)
                    response['message'] = 'Invalid parent folder'
                    return jsonify(response), 400
            except ValueError:
                logger.warning("Invalid parent folder ID format: %s", parent_id)
                response['message'] = 'Invalid parent folder ID'
                return jsonify(response), 400
        
        # Save to database
        db.session.add(new_folder)
        db.session.commit()
        
        # Create the physical folder if it doesn't exist
        folder_path = Path(current_app.root_path) / 'static' / 'uploads' / str(new_folder.id)
        logger.info("Creating physical folder: %s", folder_path)
        
        try:
            folder_path.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            logger.error("Failed to create physical folder: %s", str(e))
            # Continue anyway as the database record was created
        
        # Log success
        logger.info("User %s created folder '%s' with parent_id %s", 
                  current_user.id, folder_name, parent_id if parent_id and parent_id.strip() else "None")
        
        response['success'] = True
        response['message'] = f'Folder "{folder_name}" created successfully'
        response['folder_id'] = new_folder.id
        return jsonify(response)
        
    except SQLAlchemyError as e:
        db.session.rollback()
        logger.error("Database error in create_folder_json: %s", str(e), exc_info=True)
        response['message'] = f'Database error: {str(e)}'
        return jsonify(response), 500
    except Exception as e:
        db.session.rollback()
        logger.error("Unexpected error in create_folder_json: %s", str(e), exc_info=True)
        response['message'] = f'Server error: {str(e)}'
        return jsonify(response), 500

# Utility functions for file handling
def get_secure_file_path(document):
    """
    Securely construct and validate the file path for a document.
    
    Args:
        document: Document model instance
        
    Returns:
        Path object if valid, None if invalid
    """
    try:
        # Get the base upload folder from config
        upload_folder = current_app.config['UPLOAD_FOLDER']
        
        # Use the document's stored path to construct the full path
        file_path = Path(safe_join(upload_folder, document.stored_filename))
        
        # Validate the path is within the upload folder
        if not str(file_path.resolve()).startswith(str(Path(upload_folder).resolve())):
            logger.warning(f"Attempted path traversal for document {document.id}")
            return None
            
        return file_path
    except Exception as e:
        logger.error(f"Error constructing file path for document {document.id}: {str(e)}")
        return None

def get_content_type(file_path):
    """
    Determine the content type of a file based on its extension.
    
    Args:
        file_path: Path object for the file
        
    Returns:
        tuple of (content_type, is_previewable)
    """
    try:
        # Map file extensions to MIME types
        extension_map = {
            '.jpg': 'image/jpeg',
            '.jpeg': 'image/jpeg',
            '.png': 'image/png',
            '.gif': 'image/gif',
            '.pdf': 'application/pdf',
            '.doc': 'application/msword',
            '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            '.xls': 'application/vnd.ms-excel',
            '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        }
        
        # Get the file extension
        ext = file_path.suffix.lower()
        
        # Try to get content type from our map first
        content_type = extension_map.get(ext)
        
        # If not found, use mimetypes module as fallback
        if not content_type:
            content_type, _ = mimetypes.guess_type(str(file_path))
            
        # If still not found, use default binary type
        if not content_type:
            content_type = 'application/octet-stream'
        
        # Determine if the file type is previewable
        is_previewable = ext in ['.jpg', '.jpeg', '.png', '.gif', '.pdf', '.doc', '.docx', '.xls', '.xlsx']
        
        return content_type, is_previewable
    except Exception as e:
        logger.error(f"Error determining content type for {file_path}: {str(e)}")
        return 'application/octet-stream', False

@dashboard.route('/preview/<int:document_id>')
@login_required
def preview_document(document_id):
    """
    Secure route to preview a document.
    
    Args:
        document_id: ID of the document to preview
        
    Returns:
        File response with appropriate headers for preview
    """
    try:
        # Get the document and verify ownership
        document = Document.query.get_or_404(document_id)
        if document.user_id != current_user.id:
            logger.warning(f"User {current_user.id} attempted to access unauthorized document {document_id}")
            abort(403)
        
        # Get and validate file path
        file_path = get_secure_file_path(document)
        if not file_path or not file_path.exists():
            logger.error(f"File not found for document {document_id}")
            abort(404)
        
        # Determine content type and previewability
        content_type, is_previewable = get_content_type(file_path)
        
        if not is_previewable:
            logger.info(f"Non-previewable file type {content_type} for document {document_id}")
            return jsonify({
                'success': False,
                'message': 'This file type cannot be previewed'
            }), 400
        
        # Prepare response with appropriate headers
        response = make_response(send_file(
            file_path,
            mimetype=content_type,
            as_attachment=False,
            download_name=document.original_filename
        ))
        
        # Set security headers
        response.headers['Content-Security-Policy'] = "default-src 'self'"
        response.headers['X-Content-Type-Options'] = 'nosniff'
        
        # Set cache control headers
        response.headers['Cache-Control'] = 'no-store, must-revalidate'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
        
        # Log successful preview
        logger.info(f"Successfully served preview for document {document_id} of type {content_type}")
        
        return response
        
    except Exception as e:
        logger.error(f"Error previewing document {document_id}: {str(e)}", exc_info=True)
        abort(500)

@dashboard.after_request
def after_request(response):
    """Log template context after request"""
    if response.mimetype == 'text/html':
        logger.debug("Template rendered with status: %s", response.status)
    return response

@dashboard.route('/create_folder', methods=['POST'])
def create_folder():
    """Create a new folder in the records system"""
    try:
        folder_name = request.form.get('folder_name')
        parent_id = request.form.get('parent_id')
        
        if not folder_name:
            flash('Folder name is required', 'error')
            return redirect(url_for('dashboard.records'))
            
        # Create new folder
        new_folder = Folder(
            name=folder_name,
            user_id=current_user.id
        )
        
        # If parent_id is provided, set the parent folder
        if parent_id:
            try:
                parent_id = int(parent_id)
                parent_folder = Folder.query.get(parent_id)
                if parent_folder and parent_folder.user_id == current_user.id:
                    new_folder.parent_id = parent_id
                else:
                    flash('Invalid parent folder', 'error')
                    return redirect(url_for('dashboard.records'))
            except ValueError:
                flash('Invalid parent folder ID', 'error')
                return redirect(url_for('dashboard.records'))
        
        # Save to database
        db.session.add(new_folder)
        db.session.commit()
        
        flash(f'Folder "{folder_name}" created successfully', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error creating folder: {str(e)}', 'error')
    
    return redirect(url_for('dashboard.records'))
