from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify, current_app, send_file, abort, make_response
from flask_login import login_required, current_user
from extensions import db
from models import Folder, Document, FolderSummary
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
        # Check if a specific document is being viewed
        document_id = request.args.get('view_document')
        processed_images = None
        viewing_document = None
        
        if document_id:
            try:
                # Get the document and verify ownership
                document_id = int(document_id)
                viewing_document = Document.query.get(document_id)
                
                if not viewing_document or viewing_document.user_id != current_user.id:
                    flash('Access denied: You do not have permission to view this document', 'error')
                    return redirect(url_for('dashboard.records', folder_id=folder_id))
                
                # If it's a PDF, process its images with Gemini
                if viewing_document.file_type.lower() == 'pdf':
                    current_app.logger.info(f"Processing PDF images for document {document_id}")
                    processing_result = viewing_document.process_pdf_images()
                    
                    if processing_result['success']:
                        processed_images = processing_result['results']
                        if not processed_images:
                            current_app.logger.info(f"No images found in PDF document {document_id}")
                    else:
                        current_app.logger.error(f"Error processing PDF images: {processing_result['message']}")
                        flash(f"Error processing PDF images: {processing_result['message']}", 'warning')
            except Exception as doc_err:
                current_app.logger.error(f"Error processing document {document_id}: {str(doc_err)}", exc_info=True)
                flash('Error processing document', 'error')
        
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
            
            # Get or generate AI summary if we're in a specific folder
            folder_summary = None
            summary_last_updated = None
            
            # Check if auto-generation is requested
            auto_generate = request.args.get('generate_summary', 'false').lower() == 'true'
            
            try:
                # Only process summary if there are documents or forced generation
                if documents or auto_generate:
                    if auto_generate:
                        # Force regeneration of summary
                        current_app.logger.info(f"Forcing regeneration of summary for folder {folder_id}")
                        folder_summary = FolderSummary.generate_summary(folder_id)
                    else:
                        # Get existing summary or generate if needed
                        folder_summary = FolderSummary.get_or_generate_summary(folder_id)
                    
                    # Get the updated summary record
                    summary_record = FolderSummary.query.filter_by(folder_id=folder_id).first()
                    if summary_record:
                        summary_last_updated = summary_record.last_updated
                else:
                    folder_summary = "This folder is empty."
                
                current_app.logger.debug(f"Summary for folder {folder_id}: {folder_summary[:100]}...")
            except Exception as e:
                current_app.logger.error(f"Error getting folder summary: {str(e)}")
                folder_summary = "Error generating summary."
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
            
            # No summary for root folder
            folder_summary = None
            summary_last_updated = None

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
        
        # Validate and fix document paths before creating context
        if documents:
            for doc in documents:
                # Validate and fix paths if needed
                doc.validate_and_fix_path()
                url_path = doc.get_url_path()
                file_exists = doc.get_file_path().exists() if doc.get_file_path() else False
                logger.debug(f"Document {doc.original_filename}: URL={url_path}, exists={file_exists}")

        # Create context dictionary
        context = {
            'current_folder': current_folder,
            'folder_path': folder_path,
            'subfolders': subfolders,
            'documents': documents,
            'folder_summary': folder_summary,
            'summary_last_updated': summary_last_updated,
            'viewing_document': viewing_document,
            'processed_images': processed_images
        }
        
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
        # Use sets to track processed filenames and hashes to prevent duplicates
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
        stripped_parent_id = parent_id.strip() if parent_id else ""
        if stripped_parent_id:
            try:
                parsed_parent_id = int(stripped_parent_id)
            except ValueError:
                logger.warning("Invalid parent folder ID format: %s", stripped_parent_id)
                response['message'] = 'Invalid parent folder ID format'
                return jsonify(response), 400
                
            # After converting to int, check if folder exists and belongs to user
            parent_folder = Folder.query.get(parsed_parent_id)
            if not parent_folder:
                logger.warning("User %s attempted to create folder in non-existent parent folder %s", 
                             current_user.id, parsed_parent_id)
                response['message'] = 'Parent folder not found'
                return jsonify(response), 404
                
            if parent_folder.user_id != current_user.id:
                logger.warning("User %s attempted to create folder in unauthorized parent folder %s", 
                             current_user.id, parsed_parent_id)
                response['message'] = 'You do not have permission to use this parent folder'
                return jsonify(response), 403
                
            # If we get here, the parent folder is valid
            new_folder.parent_id = parsed_parent_id
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
                  current_user.id, folder_name, stripped_parent_id if stripped_parent_id else "None")
        
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
    Secure route to preview a document with support for range requests.
    
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
        file_path = document.get_file_path()
        if not file_path or not file_path.exists():
            logger.error(f"File not found for document {document_id}: {file_path}")
            abort(404)
        
        # Verify the file is within the allowed uploads directory
        uploads_dir = Path(current_app.root_path) / 'static' / 'uploads'
        if not str(file_path.resolve()).startswith(str(uploads_dir.resolve())):
            logger.warning(f"Path traversal attempt detected: {file_path}")
            abort(403)
            
        # Determine content type and previewability
        file_extension = file_path.suffix.lower().lstrip('.')
        allowed_preview_extensions = {'pdf', 'jpg', 'jpeg', 'png', 'gif'}
        
        # Check if file extension is in allowed list
        if file_extension not in allowed_preview_extensions:
            logger.info(f"Non-previewable file type {file_extension} for document {document_id}")
            return jsonify({
                'success': False,
                'message': 'This file type cannot be previewed'
            }), 400
            
        # Use mimetypes library for content type detection
        content_type, encoding = mimetypes.guess_type(str(file_path))
        if not content_type:
            # Fallback to common types if not detected
            extension_to_mime = {
                'pdf': 'application/pdf',
                'jpg': 'image/jpeg',
                'jpeg': 'image/jpeg',
                'png': 'image/png',
                'gif': 'image/gif'
            }
            content_type = extension_to_mime.get(file_extension, 'application/octet-stream')
        
        # Check for range request (important for PDFs)
        range_header = request.headers.get('Range', None)
        
        if range_header:
            # Handle range request for PDFs and large files
            file_size = file_path.stat().st_size
            
            # Parse the range header
            byte_range = range_header.replace('bytes=', '').split('-')
            start_byte = int(byte_range[0]) if byte_range[0] else 0
            
            # Handle open-ended ranges (e.g., "bytes=1000-")
            if len(byte_range) > 1 and byte_range[1]:
                end_byte = min(int(byte_range[1]), file_size - 1)
            else:
                end_byte = file_size - 1
                
            # Calculate the length of the content
            content_length = end_byte - start_byte + 1
            
            # Define a threshold for when to use chunked reading (1MB)
            CHUNKED_THRESHOLD = 1024 * 1024
            
            if content_length > CHUNKED_THRESHOLD:
                # Use chunked reading for large files
                chunk_size = 8192  # 8KB chunks to reduce memory usage
                
                def generate_chunks():
                    with open(file_path, 'rb') as f:
                        f.seek(start_byte)
                        bytes_remaining = content_length
                        while bytes_remaining > 0:
                            chunk = f.read(min(chunk_size, bytes_remaining))
                            if not chunk:
                                break
                            bytes_remaining -= len(chunk)
                            yield chunk
                
                # Create the response with chunked generation
                response = make_response(generate_chunks())
            else:
                # For smaller files, read the whole range at once for better performance
                with open(file_path, 'rb') as f:
                    f.seek(start_byte)
                    data = f.read(content_length)
                
                # Create the response directly with the data
                response = make_response(data)
            response.headers.add('Content-Type', content_type)
            response.headers.add('Accept-Ranges', 'bytes')
            response.headers.add('Content-Range', f'bytes {start_byte}-{end_byte}/{file_size}')
            response.headers.add('Content-Length', str(content_length))
            response.status_code = 206  # Partial Content
            
            # Set security headers
            response.headers['Content-Security-Policy'] = "default-src 'self'"
            response.headers['X-Content-Type-Options'] = 'nosniff'
            
            logger.info(f"Served partial content for document {document_id} ({start_byte}-{end_byte}/{file_size})")
            
        else:
            # Standard request - serve the whole file
            response = make_response(send_file(
                file_path,
                mimetype=content_type,
                as_attachment=False,
                download_name=document.original_filename,
                conditional=True  # Enable conditional responses based on If-Modified-Since
            ))
            
            # Add content disposition header to help browser handle the file
            response.headers.add('Content-Disposition', f'inline; filename="{document.original_filename}"')
            
            # Set security headers
            response.headers['Content-Security-Policy'] = "default-src 'self'"
            response.headers['X-Content-Type-Options'] = 'nosniff'
            
            # Set cache control headers - allow caching for better performance
            # Use ETag for cache validation instead of no-store
            response.headers['Cache-Control'] = 'private, max-age=3600'
            
            # Enable Accept-Ranges for this file
            response.headers['Accept-Ranges'] = 'bytes'
            
            logger.info(f"Successfully served preview for document {document_id} of type {content_type}")
        
        return response
        
    except Exception as e:
        logger.error(f"Error previewing document {document_id}: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'message': 'Error loading preview'
        }), 500

@dashboard.after_request
def after_request(response):
    """Log template context after request"""
    if response.mimetype == 'text/html':
        logger.debug("Template rendered with status: %s", response.status)
    return response


@dashboard.route('/api/process-pdf-images/<int:document_id>', methods=['GET'])
@login_required
def process_pdf_images_api(document_id):
    """
    API endpoint to process PDF content (text and images) using Gemini 2.0 Flash model.
    
    Args:
        document_id: ID of the PDF document to process
        
    Query Parameters:
        extract_text: Whether to extract and analyze text content (default: true)
        
    Returns:
        JSON response containing processing results including:
        - Text and image analysis results organized by page
        - Processing status and metadata
    """
    try:
        start_time = datetime.utcnow()
        
        # Get the document and verify ownership
        document = Document.query.get_or_404(document_id)
        if document.user_id != current_user.id:
            return jsonify({
                'success': False,
                'message': 'Access denied: You do not have permission to process this document'
            }), 403
        
        # Verify document is a PDF
        if document.file_type.lower() != 'pdf':
            return jsonify({
                'success': False,
                'message': 'Invalid file type: Document must be a PDF'
            }), 400
        
        # Get extract_text parameter (default to True)
        extract_text = request.args.get('extract_text', 'true').lower() != 'false'
        
        # Process PDF content using the Document model method
        logger.info(f"Processing PDF content for document {document_id} (extract_text={extract_text})")
        result = document.process_pdf_images(extract_text=extract_text)
        
        # Calculate processing time
        processing_time = (datetime.utcnow() - start_time).total_seconds()
        
        # Add processing metadata if successful
        if result['success']:
            total_items = len(result['results'])
            image_count = sum(1 for item in result.get('results', []) if item.get('content_type') == 'image')
            text_count = sum(1 for item in result.get('results', []) if item.get('content_type') == 'text')
            error_count = sum(1 for item in result.get('results', []) if item.get('error', False))
            
            logger.info(
                f"Successfully processed document {document_id} in {processing_time:.2f}s: "
                f"{total_items} total items ({image_count} images, {text_count} text sections, {error_count} errors)"
            )
            
            # Add processing metadata to the result
            result['processing_time'] = f"{processing_time:.2f}s"
            result['image_count'] = image_count
            result['text_count'] = text_count
            result['error_count'] = error_count
            result['processed_at'] = datetime.utcnow().isoformat()
        else:
            logger.error(f"Failed to process document {document_id}: {result['message']}")
        
        # Return the processing result
        return jsonify(result)
        
    except Exception as e:
        logger.error(f"Error processing PDF content for document {document_id}: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'message': f'Error processing PDF content: {str(e)}'
        }), 500


@dashboard.route('/records/document/<int:document_id>', methods=['GET'])
@login_required
def get_document_info(document_id):
    """
    Get basic information about a document for the frontend
    """
    try:
        # Get the document and verify ownership
        document = Document.query.get_or_404(document_id)
        if document.user_id != current_user.id:
            return jsonify({
                'success': False,
                'message': 'Access denied: You do not have permission to view this document'
            }), 403
        
        # Return basic document info
        return jsonify({
            'success': True,
            'id': document.id,
            'filename': document.original_filename,
            'file_type': document.file_type,
            'file_size': document.file_size,
            'upload_date': document.upload_date.isoformat(),
            'url_path': document.get_url_path()
        })
        
    except Exception as e:
        logger.error(f"Error retrieving document info for document {document_id}: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'message': f'Error retrieving document info: {str(e)}'
        }), 500


@dashboard.route('/regenerate_summary/<int:folder_id>', methods=['POST'])
@login_required
def regenerate_summary(folder_id):
    """
    Force regeneration of AI-generated summary for a folder.
    
    Args:
        folder_id: ID of the folder to regenerate summary for
        
    Returns:
        JSON response containing:
        - success: Boolean indicating if the operation was successful
        - summary: The newly generated summary text
        - last_updated: Timestamp when the summary was generated
        - message: Success or error message
    """
    try:
        # Get the folder and verify ownership
        folder = Folder.query.get_or_404(folder_id)
        if folder.user_id != current_user.id:
            logger.warning(f"User {current_user.id} attempted to regenerate summary for unauthorized folder {folder_id}")
            return jsonify({
                'success': False,
                'message': 'Access denied: You do not have permission to access this folder'
            }), 403
        
        # Check if folder has documents
        documents_count = Document.query.filter_by(folder_id=folder_id).count()
        if documents_count == 0:
            return jsonify({
                'success': True,
                'summary': "This folder is empty.",
                'last_updated': datetime.utcnow().isoformat(),
                'message': 'Folder is empty'
            })
        
        # Force regeneration of the summary
        logger.info(f"Regenerating summary for folder {folder_id} (User: {current_user.id})")
        new_summary = FolderSummary.generate_summary(folder_id)
        
        # Get the updated summary record for the timestamp
        summary_record = FolderSummary.query.filter_by(folder_id=folder_id).first()
        last_updated = summary_record.last_updated if summary_record else datetime.utcnow()
        
        return jsonify({
            'success': True,
            'summary': new_summary,
            'last_updated': last_updated.isoformat(),
            'message': 'Summary regenerated successfully'
        })
        
    except Exception as e:
        logger.error(f"Error regenerating summary for folder {folder_id}: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'message': f'Error regenerating summary: {str(e)}'
        }), 500
