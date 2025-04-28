from flask import (
    Blueprint, render_template, redirect, url_for, flash, request, jsonify, 
    current_app, send_file, abort, make_response
)
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
from typing import Optional, List, Dict, Tuple, Union

# Set up logging
logger = logging.getLogger(__name__)

dashboard = Blueprint('dashboard', __name__, template_folder='templates')

@dashboard.route('/')
@login_required
def index() -> str:
    return render_template('dashboard/index.html')

@dashboard.route('/overview')
@login_required
def overview() -> str:
    return render_template('dashboard/overview.html')

@dashboard.route('/records')
@dashboard.route('/records/<int:folder_id>')
@login_required
def records(folder_id: Optional[int] = None) -> str:
    try:
        document_id = request.args.get('view_document')
        processed_images: Optional[List[Dict]] = None
        viewing_document: Optional[Document] = None

        if document_id:
            try:
                document_id = int(document_id)
                viewing_document = Document.query.get(document_id)
                if not viewing_document or viewing_document.user_id != current_user.id:
                    flash('Access denied: You do not have permission to view this document', 'error')
                    return redirect(url_for('dashboard.records', folder_id=folder_id))
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

        if folder_id:
            current_folder = Folder.query.filter_by(id=folder_id, user_id=current_user.id).first_or_404()
            subfolders = Folder.query.filter_by(parent_id=folder_id, user_id=current_user.id).order_by(Folder.name).all()
            documents = Document.query.filter_by(folder_id=folder_id, user_id=current_user.id).order_by(Document.upload_date.desc()).all()
            folder_summary, summary_last_updated = _get_folder_summary(folder_id, documents)
        else:
            current_folder = None
            subfolders = Folder.query.filter_by(parent_id=None, user_id=current_user.id).order_by(Folder.name).all()
            documents = Document.query.filter_by(folder_id=None, user_id=current_user.id).order_by(Document.upload_date.desc()).all()
            folder_summary, summary_last_updated = None, None

        folder_path = _build_folder_path(current_folder)
        _validate_and_fix_document_paths(documents)

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

def _get_folder_summary(folder_id: int, documents: List[Document]) -> Tuple[Optional[str], Optional[datetime]]:
    folder_summary: Optional[str] = None
    summary_last_updated: Optional[datetime] = None
    auto_generate = request.args.get('generate_summary', 'false').lower() == 'true'
    try:
        if documents or auto_generate:
            if auto_generate:
                current_app.logger.info(f"Forcing regeneration of summary for folder {folder_id}")
                folder_summary = FolderSummary.generate_summary(folder_id)
            else:
                folder_summary = FolderSummary.get_or_generate_summary(folder_id)
            summary_record = FolderSummary.query.filter_by(folder_id=folder_id).first()
            if summary_record:
                summary_last_updated = summary_record.last_updated
        else:
            folder_summary = "This folder is empty."
    except Exception as e:
        current_app.logger.error(f"Error getting folder summary: {str(e)}")
        folder_summary = "Error generating summary."
    return folder_summary, summary_last_updated

def _build_folder_path(current_folder: Optional[Folder]) -> List[Folder]:
    folder_path: List[Folder] = []
    temp_folder = current_folder
    while temp_folder and temp_folder.parent_id:
        parent = Folder.query.get(temp_folder.parent_id)
        if parent and parent.user_id == current_user.id:
            folder_path.insert(0, parent)
            temp_folder = parent
        else:
            break
    return folder_path

def _validate_and_fix_document_paths(documents: List[Document]) -> None:
    for doc in documents:
        doc.validate_and_fix_path()
        url_path = doc.get_url_path()
        file_exists = doc.get_file_path().exists() if doc.get_file_path() else False
        logger.debug(f"Document {doc.original_filename}: URL={url_path}, exists={file_exists}")

@dashboard.route('/upload', methods=['GET', 'POST'])
@login_required
def upload() -> Union[str, 'Response']:
    # Check if this is an AJAX request
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    
    if request.method == 'POST':
        # Folder creation request (from AJAX)
        folder_name = request.form.get('folder_name')
        if is_ajax and folder_name and not request.files:
            try:
                # Create a new folder
                folder = Folder(
                    name=folder_name,
                    user_id=current_user.id,
                    parent_id=request.form.get('parent_id')
                )
                db.session.add(folder)
                db.session.commit()
                
                return jsonify({
                    'success': True,
                    'folder_id': folder.id,
                    'message': f'Folder "{folder_name}" created successfully'
                })
            except Exception as e:
                db.session.rollback()
                return jsonify({
                    'success': False,
                    'message': f'Error creating folder: {str(e)}'
                }), 500
        
        # Process file uploads
        folder_id = request.form.get('folder_id')
        folder = None
        if folder_id:
            try:
                folder_id = int(folder_id)
                folder = Folder.query.get(folder_id)
                if not folder or folder.user_id != current_user.id:
                    if is_ajax:
                        return jsonify({
                            'success': False,
                            'message': 'Invalid folder selected'
                        }), 400
                    else:
                        flash('Invalid folder selected', 'error')
                        return redirect(url_for('dashboard.records'))
            except ValueError:
                if is_ajax:
                    return jsonify({
                        'success': False,
                        'message': 'Invalid folder ID'
                    }), 400
                else:
                    flash('Invalid folder ID', 'error')
                    return redirect(url_for('dashboard.records'))

        # Handle multiple file uploads from AJAX request
        if is_ajax and 'files[]' in request.files:
            uploaded_files = request.files.getlist('files[]')
            if not uploaded_files:
                return jsonify({
                    'success': False,
                    'message': 'No files were uploaded'
                }), 400
                
            uploaded_count = 0
            error_messages = []
            description = request.form.get('description', '')
            
            for file in uploaded_files:
                if file.filename == '':
                    continue
                    
                try:
                    document = Document(
                        user_id=current_user.id,
                        folder_id=folder_id if folder else None,
                        description=description
                    )
                    document.save_file(file)
                    db.session.add(document)
                    uploaded_count += 1
                except Exception as e:
                    error_messages.append(f"Error with '{file.filename}': {str(e)}")
                    logger.error(f"Upload error for file '{file.filename}': {str(e)}")
            
            if uploaded_count > 0:
                try:
                    db.session.commit()
                    message = f"Successfully uploaded {uploaded_count} file(s)"
                    if error_messages:
                        message += f" with {len(error_messages)} error(s)"
                    
                    return jsonify({
                        'success': True,
                        'message': message,
                        'upload_count': uploaded_count,
                        'errors': error_messages
                    })
                except Exception as e:
                    db.session.rollback()
                    return jsonify({
                        'success': False,
                        'message': f'Error saving uploads: {str(e)}',
                        'errors': [str(e)] + error_messages
                    }), 500
            else:
                return jsonify({
                    'success': False,
                    'message': 'No files were successfully uploaded',
                    'errors': error_messages
                }), 400
        
        # Handle regular form submission (single file)
        elif 'file' in request.files:
            file = request.files['file']
            if file.filename == '':
                flash('No file selected', 'error')
                return redirect(request.referrer or url_for('dashboard.records'))

            try:
                document = Document(
                    user_id=current_user.id,
                    folder_id=folder_id if folder else None,
                    description=request.form.get('description', '')
                )
                document.save_file(file)
                db.session.add(document)
                db.session.commit()
                flash(f'File "{document.original_filename}" uploaded successfully', 'success')
            except Exception as e:
                db.session.rollback()
                flash(f'Error uploading file: {str(e)}', 'error')

            return redirect(url_for('dashboard.records', folder_id=folder_id))
        else:
            if is_ajax:
                return jsonify({
                    'success': False,
                    'message': 'No file part in the request'
                }), 400
            else:
                flash('No file part in the request', 'error')
                return redirect(request.referrer or url_for('dashboard.records'))
    return render_template('dashboard/upload.html')

# Other routes and utility functions remain unchanged, with type annotations added where applicable.
