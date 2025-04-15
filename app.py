import os
import logging
from flask import Flask, render_template
from dotenv import load_dotenv

from config import config
from extensions import db, login_manager, socketio, csrf

# Set up logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Load environment variables from .env file
load_dotenv()

def register_cli_commands(app):
    """Register Flask CLI commands"""
    try:
        # Register add-content-hash command
        from migrations.add_content_hash import register_migration_command
        register_migration_command(app)

        # Register migrate-uploads command
        from migrations.migrate_uploads import migrate_uploads
        
        @app.cli.command('migrate-uploads')
        def migrate_uploads_command():
            """Migrate uploaded files to proper structure and remove duplicates."""
            with app.app_context():
                migrate_uploads()
                # Cleanup orphaned files after migration
                from models import Document
                Document.cleanup_orphaned_files()
                print("File migration completed. Check the application logs for details.")
                
        logger.debug("Successfully registered migrate-uploads command")
    except Exception as e:
        logger.error(f"Failed to register migrate-uploads command: {str(e)}")

def create_app(config_name=None):
    if config_name is None:
        config_name = os.environ.get('FLASK_CONFIG', 'default')
    
    app = Flask(__name__)
    
    # First load the config to get any base settings
    app.config.from_object(config[config_name])
    
    # Ensure the instance folder exists and is writable
    try:
        os.makedirs(app.instance_path, exist_ok=True)
        logger.debug(f"Instance directory: {app.instance_path}")
        
        # Test write permissions
        test_file = os.path.join(app.instance_path, 'test_write')
        try:
            with open(test_file, 'w') as f:
                f.write('test')
            os.remove(test_file)
            logger.debug(f"Successfully verified write permissions to {app.instance_path}")
        except Exception as e:
            logger.error(f"Cannot write to instance directory: {str(e)}")
            raise
    except Exception as e:
        logger.error(f"Error with instance directory: {str(e)}")
        raise

    # Configure database with relative path
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///medical_dashboard.db'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['UPLOAD_FOLDER'] = os.path.join(app.root_path, 'static', 'uploads')
    logger.debug(f"Database URI: {app.config['SQLALCHEMY_DATABASE_URI']}")
    
    # Ensure upload folder exists
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    
    # Initialize extensions with app
    db.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'
    login_manager.login_message_category = 'info'
    socketio.init_app(app)
    # Setup CSRF protection
    csrf.init_app(app)
    
    # Register CLI commands
    register_cli_commands(app)
    
    # Exempt file upload and folder APIs from CSRF protection
    csrf.exempt('dashboard.upload_json')
    csrf.exempt('dashboard.create_folder_json')
    csrf.exempt('dashboard.get_folder_name_json')
    
    @app.after_request
    def add_csrf_header(response):
        response.headers.set('X-CSRFToken', csrf._get_csrf_token())
        return response
    
    # Register blueprints
    from blueprints.auth.routes import auth as auth_blueprint
    app.register_blueprint(auth_blueprint, url_prefix='/auth')
    
    from blueprints.dashboard.routes import dashboard as dashboard_blueprint
    app.register_blueprint(dashboard_blueprint, url_prefix='/dashboard')
    
    from blueprints.chat.routes import chat as chat_blueprint
    app.register_blueprint(chat_blueprint, url_prefix='/chat')
    
    # Route for home page
    @app.route('/')
    def index():
        return render_template('index.html')
    
    # Error handlers
    @app.errorhandler(404)
    def page_not_found(e):
        return render_template('errors/404.html'), 404

    @app.errorhandler(500)
    def internal_server_error(e):
        return render_template('errors/500.html'), 500
    # Create database tables
    with app.app_context():
        try:
            # Import models here to avoid circular imports
            from models import User
            
            if os.environ.get('FLASK_RESET_DB') == '1':
                # Only drop tables if explicitly requested via environment variable
                db.drop_all()
                logger.debug("Dropped all database tables")
            
            # Create all tables with updated schema
            db.create_all()
            logger.debug("Successfully created database tables")
            
            # Create a test admin user if no users exist
            if User.query.count() == 0:
                admin_user = User(
                    username="admin",
                    email="admin@example.com",
                    is_admin=True
                )
                admin_user.set_password("admin123")
                db.session.add(admin_user)
                db.session.commit()
                logger.debug("Created default admin user")
        except Exception as e:
            logger.error(f"Error creating database tables: {str(e)}")
            raise
    
    return app

if __name__ == '__main__':
    # Set environment variable to rebuild database on first run
    if not os.path.exists(os.path.join('instance', 'medical_dashboard.db')):
        os.environ['FLASK_RESET_DB'] = '1'
        # Also delete any old file that might exist in the wrong location
        if os.path.exists('medical_dashboard.db'):
            os.remove('medical_dashboard.db')
    
    app = create_app()
    socketio.run(app, debug=app.config['DEBUG'])

