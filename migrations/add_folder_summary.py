from flask import current_app
import logging
from sqlalchemy import text, inspect
from datetime import datetime

logger = logging.getLogger(__name__)

def create_folder_summaries_table():
    """Create folder_summaries table for storing AI-generated summaries"""
    from extensions import db
    
    try:
        # Check if table already exists to avoid errors
        inspector = inspect(db.engine)
        existing_tables = inspector.get_table_names()
        
        if 'folder_summaries' in existing_tables:
            logger.info("folder_summaries table already exists")
            return
        
        # Create the folder_summaries table
        db.session.execute(text("""
            CREATE TABLE folder_summaries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                folder_id INTEGER NOT NULL UNIQUE,
                summary_text TEXT,
                last_updated DATETIME,
                file_hash VARCHAR(128),
                FOREIGN KEY (folder_id) REFERENCES folders (id) ON DELETE CASCADE
            )
        """))
        db.session.flush()
        
        # Create index for performance
        db.session.execute(text("""
            CREATE INDEX ix_folder_summaries_folder_id ON folder_summaries (folder_id)
        """))
        
        # Set default timestamp for last_updated
        db.session.execute(text("""
            UPDATE folder_summaries SET last_updated = CURRENT_TIMESTAMP
            WHERE last_updated IS NULL
        """))
        
        # Commit the changes
        db.session.commit()
        logger.info("Successfully created folder_summaries table")
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error creating folder_summaries table: {str(e)}")
        raise

def drop_folder_summaries_table():
    """Drop folder_summaries table (rollback)"""
    from extensions import db
    
    try:
        # Check if table exists before attempting to drop
        inspector = inspect(db.engine)
        existing_tables = inspector.get_table_names()
        
        if 'folder_summaries' not in existing_tables:
            logger.info("folder_summaries table does not exist, nothing to drop")
            return
            
        # Drop the table
        db.session.execute(text("DROP TABLE IF EXISTS folder_summaries"))
        db.session.commit()
        logger.info("Successfully dropped folder_summaries table")
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error dropping folder_summaries table: {str(e)}")
        raise

def register_migration_command(app):
    """Register the database migration commands"""
    @app.cli.command('create-folder-summaries')
    def create_folder_summaries_command():
        """Create folder_summaries table for storing AI-generated summaries."""
        try:
            create_folder_summaries_table()
            print("Successfully created folder_summaries table")
        except Exception as e:
            print(f"Error creating folder_summaries table: {e}")
            raise
            
    @app.cli.command('drop-folder-summaries')
    def drop_folder_summaries_command():
        """Drop folder_summaries table (rollback)."""
        try:
            drop_folder_summaries_table()
            print("Successfully dropped folder_summaries table")
        except Exception as e:
            print(f"Error dropping folder_summaries table: {e}")
            raise

