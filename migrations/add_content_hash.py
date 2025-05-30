from flask import Flask, current_app
import logging
from sqlalchemy import text, inspect
from sqlalchemy.engine import Inspector
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

def add_content_hash_column() -> None:
    """Add content_hash column to documents table."""
    from extensions import db  # Assuming `db` is an instance of SQLAlchemy

    try:
        # Check if column already exists to avoid errors
        inspector: Inspector = inspect(db.engine)
        existing_columns: list[str] = [col['name'] for col in inspector.get_columns('documents')]

        if 'content_hash' in existing_columns:
            logger.info("content_hash column already exists")
            return

        # Execute the ALTER TABLE command
        db.session.execute(
            text("ALTER TABLE documents ADD COLUMN content_hash VARCHAR(64)")
        )
        db.session.flush()

        # Create index
        db.session.execute(
            text("CREATE INDEX IF NOT EXISTS ix_documents_content_hash ON documents (content_hash)")
        )

        # Commit the changes
        db.session.commit()
        logger.info("Successfully added content_hash column to documents table")

    except Exception as e:
        db.session.rollback()
        logger.error(f"Error adding content_hash column: {str(e)}")
        raise

def register_migration_command(app: Flask) -> None:
    """Register the database migration command."""
    @app.cli.command('add-content-hash')
    def add_content_hash_command() -> None:
        """Add content_hash column to documents table."""
        try:
            add_content_hash_column()
            print("Successfully added content_hash column to documents table")
        except Exception as e:
            print(f"Error adding content_hash column: {e}")
            raise
