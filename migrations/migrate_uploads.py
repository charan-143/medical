from pathlib import Path
import hashlib
import shutil
import os
from flask import current_app
from models import Document, db
import logging

def compute_file_hash(file_path):
    """Compute SHA-256 hash of a file"""
    sha256_hash = hashlib.sha256()
    with open(file_path, 'rb') as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()

def migrate_uploads():
    """Reorganize uploaded files and remove duplicates"""
    logger = current_app.logger
    logger.info("Starting file migration process")
    
    # Get base upload directory
    base_dir = Path(current_app.root_path) / 'static' / 'uploads'
    if not base_dir.exists():
        logger.warning("Upload directory does not exist")
        return
    
    # Dictionary to store file hashes and their corresponding document
    file_hashes = {}
    # Dictionary to store files that need to be moved
    files_to_move = {}
    # List to store duplicates for removal
    duplicates = []
    
    try:
        # First pass: compute hashes and identify duplicates
        logger.info("Computing file hashes and identifying duplicates")
        for doc in Document.query.all():
            current_path = base_dir / doc.filename
            if not current_path.exists():
                logger.warning(f"File not found for document {doc.id}: {doc.filename}")
                continue
            
            # Compute hash of actual file
            file_hash = compute_file_hash(current_path)
            
            # Update the document's hash if it doesn't match
            if doc.content_hash != file_hash:
                doc.content_hash = file_hash
                logger.info(f"Updated hash for document {doc.id}: {doc.filename}")
            
            # If we haven't seen this hash before, store it
            if file_hash not in file_hashes:
                file_hashes[file_hash] = doc
                # Mark file for moving if it's in a folder
                if doc.folder_id:
                    files_to_move[doc.id] = {
                        'source': current_path,
                        'folder_id': doc.folder_id,
                        'doc': doc
                    }
            else:
                # This is a duplicate
                duplicates.append({
                    'path': current_path,
                    'doc': doc,
                    'original_doc': file_hashes[file_hash]
                })
        
        # Second pass: move files to proper folders
        logger.info(f"Moving {len(files_to_move)} files to their folders")
        for file_info in files_to_move.values():
            doc = file_info['doc']
            source = file_info['source']
            folder_path = base_dir / str(doc.folder_id)
            
            # Create folder if it doesn't exist
            folder_path.mkdir(parents=True, exist_ok=True)
            
            # Move file to its proper folder
            target = folder_path / doc.filename
            if source != target and source.exists():  # Only move if paths are different and source exists
                try:
                    shutil.move(str(source), str(target))
                    logger.info(f"Moved file: {source} -> {target}")
                    
                    # Update file path in database
                    doc.file_path = f"uploads/{doc.folder_id}/{doc.filename}"
                except Exception as e:
                    logger.error(f"Error moving file {source} to {target}: {str(e)}")
        
        # Third pass: handle duplicates
        logger.info(f"Processing {len(duplicates)} duplicate files")
        for dup in duplicates:
            original_doc = dup['original_doc']
            duplicate_doc = dup['doc']
            duplicate_path = dup['path']
            
            # Update the duplicate document to point to the original file
            duplicate_doc.content_hash = original_doc.content_hash
            duplicate_doc.filename = original_doc.filename
            duplicate_doc.file_path = original_doc.file_path
            
            logger.info(f"Updated document {duplicate_doc.id} to point to {duplicate_doc.file_path}")
            
            # Remove the duplicate file
            if duplicate_path.exists():
                try:
                    duplicate_path.unlink()
                    logger.info(f"Removed duplicate file: {duplicate_path}")
                except Exception as e:
                    logger.error(f"Error removing duplicate file {duplicate_path}: {str(e)}")
        
        # Commit all changes
        db.session.commit()
        logger.info("Database changes committed successfully")
        
        # Clean up empty folders in the root upload directory
        for item in base_dir.iterdir():
            if item.is_dir() and not any(item.iterdir()):
                try:
                    item.rmdir()
                    logger.info(f"Removed empty folder: {item}")
                except Exception as e:
                    logger.error(f"Error removing empty folder {item}: {str(e)}")
        
        # Log summary
        logger.info(
            f"Migration complete: "
            f"Moved {len(files_to_move)} files to folders, "
            f"Removed {len(duplicates)} duplicates"
        )
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error during migration: {str(e)}")
        raise

# Function is now registered directly in app.py

