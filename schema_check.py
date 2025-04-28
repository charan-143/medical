#!/usr/bin/env python
"""
Schema Check Script

This script checks the database schema for the Medical Dashboard application
and prints the structure of tables to verify they are correctly set up.
"""

import sys
from typing import List
from sqlalchemy import inspect
from sqlalchemy.engine import Inspector
from sqlalchemy.exc import SQLAlchemyError

try:
    # Import necessary modules
    from app import create_app
    from extensions import db
    from models import Document, Folder, User
    
    # Create Flask app and application context
    app = create_app()
    
    with app.app_context():
        try:
            # Get database inspector
            inspector: Inspector = inspect(db.engine)
            
            # Check if tables exist
            tables: List[str] = inspector.get_table_names()
            print(f"Database tables: {tables}")
            
            if 'documents' not in tables or 'folders' not in tables:
                print("Error: Required tables are missing!")
                sys.exit(1)
            
            # Print Document table schema
            print("\n=== Document Table Schema ===")
            print("Columns:")
            for column in inspector.get_columns('documents'):
                print(f"  - {column['name']}: {column['type']}")
            
            # Print Document table indexes
            print("\nIndexes:")
            for index in inspector.get_indexes('documents'):
                print(f"  - {index['name']}: {index['column_names']}")
            
            # Print Folder table schema
            print("\n=== Folder Table Schema ===")
            print("Columns:")
            for column in inspector.get_columns('folders'):
                print(f"  - {column['name']}: {column['type']}")
            
            # Print Folder table indexes
            print("\nIndexes:")
            for index in inspector.get_indexes('folders'):
                print(f"  - {index['name']}: {index['column_names']}")
            
            # Check specific columns that we need
            doc_columns: List[str] = [col['name'] for col in inspector.get_columns('documents')]
            if 'file_path' not in doc_columns:
                print("\nERROR: 'file_path' column is missing from documents table!")
                sys.exit(1)
            
            # Check for rows in each table
            doc_count: int = Document.query.count()
            folder_count: int = Folder.query.count()
            user_count: int = User.query.count()
            
            print("\n=== Database Statistics ===")
            print(f"Documents: {doc_count}")
            print(f"Folders: {folder_count}")
            print(f"Users: {user_count}")
            
            print("\nSchema check completed successfully!")
            
        except SQLAlchemyError as e:
            print(f"Database error: {str(e)}")
            sys.exit(1)
        except Exception as e:
            print(f"Error: {str(e)}")
            sys.exit(1)

except ImportError as e:
    print(f"Import error: {str(e)}")
    print("Make sure you're running this script from the project root directory.")
    sys.exit(1)
except Exception as e:
    print(f"Unexpected error: {str(e)}")
    sys.exit(1)
