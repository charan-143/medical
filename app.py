import os
import logging
from flask import Flask, render_template, session, request, jsonify
from dotenv import load_dotenv
from flask_session import Session

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
        raise

    # Configure database with relative path
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///medical_dashboard.db'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['UPLOAD_FOLDER'] = os.path.join(app.root_path, 'static', 'uploads')
    logger.debug(f"Database URI: {app.config['SQLALCHEMY_DATABASE_URI']}")
    
    # Explicit session configuration
    app.config['SESSION_TYPE'] = 'filesystem'
    app.config['SESSION_FILE_DIR'] = os.path.join(app.instance_path, 'flask_session')
    app.config['SESSION_PERMANENT'] = True
    app.config['SESSION_USE_SIGNER'] = True
    app.config['SESSION_COOKIE_HTTPONLY'] = True
    app.config['SESSION_COOKIE_SECURE'] = False  # Set to True in production
    
    # Ensure session directory exists
    os.makedirs(app.config['SESSION_FILE_DIR'], exist_ok=True)
    logger.debug(f"Session directory: {app.config['SESSION_FILE_DIR']}")
    logger.debug(f"Session configuration: {app.config['SESSION_TYPE']}")
    
    # Verify SECRET_KEY is set (required for sessions and CSRF)
    if not app.config.get('SECRET_KEY'):
        app.config['SECRET_KEY'] = os.urandom(24)
        logger.warning("No SECRET_KEY configured, using a random one for this session")
    else:
        logger.debug("SECRET_KEY is configured")
    logger.debug(f"Database URI: {app.config['SQLALCHEMY_DATABASE_URI']}")
    
    # Ensure upload folder exists
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    
    # Initialize Flask-Session first (before CSRF protection)
    session_interface = Session(app)
    logger.debug("Flask-Session initialized")
    
    # Add session debugging
    @app.before_request
    def session_debugging():
        if request.endpoint and not request.endpoint.startswith('static'):
            # Log session details for debugging
            has_session = bool(session)
            csrf_token = csrf._get_csrf_token() if hasattr(csrf, '_get_csrf_token') else None
            logger.debug(f"Request to {request.endpoint}: Session active: {has_session}, CSRF token: {'present' if csrf_token else 'missing'}")
            # Set a test value in session to ensure it's working
            if request.endpoint not in ['static']:
                session['test_key'] = 'test_value'
    
    # Initialize other extensions with app
    db.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'
    login_manager.login_message_category = 'info'
    socketio.init_app(app)
    
    # Setup CSRF protection after session is initialized
    csrf.init_app(app)
    logger.debug("CSRF protection initialized")
    
    # Register CLI commands
    register_cli_commands(app)
    
    # Exempt file upload and folder APIs from CSRF protection
    csrf.exempt('dashboard.upload_json')
    csrf.exempt('dashboard.create_folder_json')
    csrf.exempt('dashboard.get_folder_name_json')
    
    @app.after_request
    def add_csrf_header(response):
        # Add CSRF token to header and ensure session cookie is set
        csrf_token = csrf._get_csrf_token()
        response.headers.set('X-CSRFToken', csrf_token)
        
        # Debug response cookies
        if 'text/html' in response.headers.get('Content-Type', ''):
            logger.debug(f"Response has session cookie: {'session' in request.cookies}")
            logger.debug(f"Response status: {response.status_code}, mimetype: {response.mimetype}")
            logger.debug(f"CSRF token in response headers: {csrf_token is not None}")
            
        return response
    
    # CSRF error handler
    @app.errorhandler(400)
    def handle_csrf_error(e):
        if 'CSRF' in str(e):
            logger.error(f"CSRF error: {str(e)}")
            # Log request details for debugging
            logger.debug(f"Request headers: {dict(request.headers)}")
            logger.debug(f"Request method: {request.method}")
            logger.debug(f"Request endpoint: {request.endpoint}")
            logger.debug(f"Session present: {bool(session)}")
            logger.debug(f"Session cookie in request: {'session' in request.cookies}")
            logger.debug(f"Session data: {dict(session)}")
            logger.debug(f"Form data: {dict(request.form)}")
            logger.debug(f"CSRF token in form: {'csrf_token' in request.form}")
            
            # For AJAX requests, return JSON
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify(error="CSRF validation failed. Please refresh the page and try again."), 400
            
            # For regular requests, render error page
            return render_template('errors/400.html', error="CSRF validation failed. Please go back and try again."), 400
        
        # Handle other 400 errors
        return render_template('errors/400.html'), 400
    
    # Register blueprints
    from blueprints.auth.routes import auth as auth_blueprint
    app.register_blueprint(auth_blueprint, url_prefix='/auth')
    
    from blueprints.dashboard.routes import dashboard as dashboard_blueprint
    app.register_blueprint(dashboard_blueprint, url_prefix='/dashboard')
    
    from blueprints.chat.routes import chat as chat_blueprint
    app.register_blueprint(chat_blueprint, url_prefix='/chat')
    
    # Route for home page
    @app.route('/', endpoint='index')
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

