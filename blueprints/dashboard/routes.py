from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify, current_app
from flask_login import login_required, current_user
from extensions import db
from models import Folder, Document
import os
import uuid
import logging
from werkzeug.utils import secure_filename
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
    
    # Initialize variables for template
    current_folder = None
    folder_path = []
    
    # Get subfolders and documents to display
    if folder_id:
        # If folder_id is provided, get that specific folder
        current_folder = Folder.query.filter_by(id=folder_id, user_id=current_user.id).first_or_404()
        
        # Build folder path for breadcrumb navigation
        temp_folder = current_folder
        while temp_folder.parent_id:
            parent = Folder.query.get(temp_folder.parent_id)
            if parent and parent.user_id == current_user.id:
                folder_path.insert(0, parent)
                temp_folder = parent
            else:
                break
        
        # Get subfolders and documents in current folder
        subfolders = Folder.query.filter_by(parent_id=folder_id, user_id=current_user.id).all()
        documents = current_folder.documents.all()
    else:
        # If no folder_id, show root level folders and documents
        subfolders = Folder.query.filter_by(parent_id=None, user_id=current_user.id).all()
        documents = Document.query.filter_by(folder_id=None, user_id=current_user.id).all()
    
    return render_template('dashboard/records.html', 
                          current_folder=current_folder,
                          folder_path=folder_path,
                          subfolders=subfolders,
                          documents=documents)

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
    
    try:
        # Check if folder_id is specified
        folder_id = request.form.get('folder_id')
        folder = None
        
        if folder_id and folder_id.strip():
            try:
                folder_id = int(folder_id)
                folder = Folder.query.get(folder_id)
                # Verify folder belongs to current user
                if not folder or folder.user_id != current_user.id:
                    response['message'] = 'Invalid folder selected'
                    logger.warning("User %s attempted to upload to invalid folder %s", current_user.id, folder_id)
                    return jsonify(response), 400
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
                    document = Document(
                        user_id=current_user.id,
                        folder_id=folder_id if folder else None,
                        description=request.form.get('description', '')
                    )
                    
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
                        folder_id if folder else "root"
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
                    folder_id if folder else "root"
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
@dashboard.route('/create_folder', methods=['POST'])
@login_required
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
