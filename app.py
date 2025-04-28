import os
import logging
from flask import Flask, render_template, session, request, jsonify, Response
from dotenv import load_dotenv
from flask_session import Session
from typing import Optional, Any, Dict

from config import config
from extensions import db, login_manager, socketio, csrf

# Set up logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Load environment variables from .env file
load_dotenv()

def register_cli_commands(app: Flask) -> None:
    """Register Flask CLI commands"""
    try:
        from migrations.add_content_hash import register_migration_command
        register_migration_command(app)

        from migrations.add_folder_summary import register_migration_command as register_folder_summary_command
        register_folder_summary_command(app)

        from migrations.migrate_uploads import migrate_uploads

        @app.cli.command('migrate-uploads')
        def migrate_uploads_command() -> None:
            """Migrate uploaded files to proper structure and remove duplicates."""
            with app.app_context():
                migrate_uploads()
                from models import Document
                Document.cleanup_orphaned_files()
                print("File migration completed. Check the application logs for details.")

        logger.debug("Successfully registered migrate-uploads command")
        logger.debug("Successfully registered folder_summaries commands")
    except Exception as e:
        logger.error(f"Failed to register migrate-uploads command: {str(e)}")

def initialize_upload_directory(app: Flask) -> None:
    """
    Initialize and validate the upload directory with proper permissions.
    Creates the directory if it doesn't exist, sets permissions, and validates write access.
    """
    upload_dir = app.config['UPLOAD_FOLDER']
    logger.info(f"Initializing upload directory: {upload_dir}")
    
    try:
        # Create the main upload directory if it doesn't exist
        os.makedirs(upload_dir, exist_ok=True)
        logger.debug(f"Upload directory exists or was created: {upload_dir}")
        
        # Try setting permissions (may not work on all platforms)
        try:
            # 0o755 = Owner can read/write/execute, others can read/execute
            os.chmod(upload_dir, 0o755)
            logger.debug(f"Permissions set on upload directory: 0o755")
        except Exception as perm_err:
            logger.warning(f"Could not set permissions on upload directory: {str(perm_err)}")
        
        # Validate write access by creating a test file
        test_filename = os.path.join(upload_dir, 'write_test.tmp')
        try:
            with open(test_filename, 'w') as f:
                f.write('test')
            os.remove(test_filename)
            logger.info(f"Successfully verified write permissions to upload directory")
        except Exception as write_err:
            logger.error(f"Cannot write to upload directory: {str(write_err)}")
            raise RuntimeError(f"Upload directory is not writable: {upload_dir}")
        
        # Create common subdirectories that might be needed
        for subdir in ['temp', 'user_folders']:
            subdir_path = os.path.join(upload_dir, subdir)
            os.makedirs(subdir_path, exist_ok=True)
            logger.debug(f"Subdirectory exists or was created: {subdir_path}")
        
        # Show directory stats
        if os.path.exists(upload_dir):
            logger.info(f"Upload directory is ready: {upload_dir}")
            # Count existing files for diagnostics
            file_count = sum([len(files) for r, d, files in os.walk(upload_dir)])
            logger.info(f"Upload directory contains {file_count} files")
    except Exception as e:
        logger.critical(f"Failed to initialize upload directory: {str(e)}")
        # We don't raise the error here to allow the app to start,
        # but upload functionality will likely be broken
        app.config['UPLOAD_ERROR'] = str(e)

def create_app(config_name: Optional[str] = None) -> Flask:
    if config_name is None:
        config_name = os.environ.get('FLASK_CONFIG', 'default')

    app = Flask(__name__)

    @app.template_filter('nl2br')
    def nl2br_filter(text: Optional[str]) -> str:
        if not text:
            return ""
        return text.replace('\n', '<br>')

    app.config.from_object(config[config_name])

    try:
        os.makedirs(app.instance_path, exist_ok=True)
        logger.debug(f"Instance directory: {app.instance_path}")

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

    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///medical_dashboard.db'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['UPLOAD_FOLDER'] = os.path.join(app.root_path, 'static', 'uploads')
    logger.debug(f"Database URI: {app.config['SQLALCHEMY_DATABASE_URI']}")

    app.config['SESSION_TYPE'] = 'filesystem'
    app.config['SESSION_FILE_DIR'] = os.path.join(app.instance_path, 'flask_session')
    app.config['SESSION_PERMANENT'] = True
    app.config['SESSION_USE_SIGNER'] = True
    app.config['SESSION_COOKIE_HTTPONLY'] = True
    app.config['SESSION_COOKIE_SECURE'] = False

    os.makedirs(app.config['SESSION_FILE_DIR'], exist_ok=True)
    logger.debug(f"Session directory: {app.config['SESSION_FILE_DIR']}")
    logger.debug(f"Session configuration: {app.config['SESSION_TYPE']}")

    if not app.config.get('SECRET_KEY'):
        app.config['SECRET_KEY'] = os.urandom(24)
        logger.warning("No SECRET_KEY configured, using a random one for this session")
    else:
        logger.debug("SECRET_KEY is configured")

    # Initialize upload directory with proper validation
    initialize_upload_directory(app)

    session_interface = Session(app)
    logger.debug("Flask-Session initialized")

    @app.before_request
    def session_debugging() -> None:
        if request.endpoint and not request.endpoint.startswith('static'):
            has_session = bool(session)
            csrf_token = csrf._get_csrf_token() if hasattr(csrf, '_get_csrf_token') else None
            logger.debug(f"Request to {request.endpoint}: Session active: {has_session}, CSRF token: {'present' if csrf_token else 'missing'}")
            if request.endpoint not in ['static']:
                session['test_key'] = 'test_value'

    db.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'
    login_manager.login_message_category = 'info'
    socketio.init_app(app)
    csrf.init_app(app)
    logger.debug("CSRF protection initialized")

    register_cli_commands(app)

    csrf.exempt('dashboard.upload_json')
    csrf.exempt('dashboard.create_folder_json')
    csrf.exempt('dashboard.get_folder_name_json')
    csrf.exempt('dashboard.regenerate_summary')

    @app.after_request
    def add_csrf_header(response: Response) -> Response:
        csrf_token = csrf._get_csrf_token()
        response.headers.set('X-CSRFToken', csrf_token)

        if 'text/html' in response.headers.get('Content-Type', ''):
            logger.debug(f"Response has session cookie: {'session' in request.cookies}")
            logger.debug(f"Response status: {response.status_code}, mimetype: {response.mimetype}")
            logger.debug(f"CSRF token in response headers: {csrf_token is not None}")
        
        # Add warning header if upload directory had initialization issues
        if app.config.get('UPLOAD_ERROR'):
            response.headers.set('X-Upload-Error', 'true')
            
        return response

    @app.errorhandler(400)
    def handle_csrf_error(e: Exception) -> Response:
        if 'CSRF' in str(e):
            logger.error(f"CSRF error: {str(e)}")
            logger.debug(f"Request headers: {dict(request.headers)}")
            logger.debug(f"Request method: {request.method}")
            logger.debug(f"Request endpoint: {request.endpoint}")
            logger.debug(f"Session present: {bool(session)}")
            logger.debug(f"Session cookie in request: {'session' in request.cookies}")
            logger.debug(f"Session data: {dict(session)}")
            logger.debug(f"Form data: {dict(request.form)}")
            logger.debug(f"CSRF token in form: {'csrf_token' in request.form}")

            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify(error="CSRF validation failed. Please refresh the page and try again."), 400

            return render_template('errors/400.html', error="CSRF validation failed. Please go back and try again."), 400

        return render_template('errors/400.html'), 400
    
    # Check for upload directory errors and flash a message for admin users
    @app.before_request
    def check_upload_directory_errors() -> None:
        if app.config.get('UPLOAD_ERROR') and hasattr(request, 'endpoint') and request.endpoint \
            and not request.endpoint.startswith('static') and session.get('_user_id'):
            from models import User
            user = User.query.get(session.get('_user_id'))
            if user and user.is_admin and not session.get('upload_error_shown'):
                from flask import flash
                error_msg = app.config.get('UPLOAD_ERROR')
                flash(f'Upload directory error: {error_msg}. File uploads may not work correctly.', 'danger')
                session['upload_error_shown'] = True

    from blueprints.auth.routes import auth as auth_blueprint
    app.register_blueprint(auth_blueprint, url_prefix='/auth')

    from blueprints.dashboard.routes import dashboard as dashboard_blueprint
    app.register_blueprint(dashboard_blueprint, url_prefix='/dashboard')

    from blueprints.chat.routes import chat as chat_blueprint
    app.register_blueprint(chat_blueprint, url_prefix='/chat')

    @app.route('/', endpoint='index')
    def index() -> str:
        return render_template('index.html')

    @app.errorhandler(404)
    def page_not_found(e: Exception) -> Response:
        return render_template('errors/404.html'), 404

    @app.errorhandler(500)
    def internal_server_error(e: Exception) -> Response:
        return render_template('errors/500.html'), 500

    with app.app_context():
        try:
            from models import User

            if os.environ.get('FLASK_RESET_DB') == '1':
                db.drop_all()
                logger.debug("Dropped all database tables")

            db.create_all()
            logger.debug("Successfully created database tables")

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
    if not os.path.exists(os.path.join('instance', 'medical_dashboard.db')):
        os.environ['FLASK_RESET_DB'] = '1'
        if os.path.exists('medical_dashboard.db'):
            os.remove('medical_dashboard.db')

    app = create_app()
    socketio.run(app, debug=app.config['DEBUG'])
