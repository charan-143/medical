from flask import Blueprint, render_template, redirect, url_for, flash, request, session
from flask_login import login_user, logout_user, current_user, login_required
from .models import User, db
from .forms import LoginForm, RegisterForm
from flask_wtf.csrf import generate_csrf
import logging

# Setup logging
logger = logging.getLogger(__name__)

auth = Blueprint('auth', __name__, template_folder='templates')

@auth.route('/login', methods=['GET', 'POST'])
def login():
    # Debug session state at start of request
    session_active = bool(session)
    logger.debug(f"Login route - Session active at start: {session_active}")
    logger.debug(f"Session data at start: {dict(session) if session_active else 'No session'}")
    
    # Generate a new CSRF token - this ensures a token is in the session
    csrf_token = generate_csrf()
    logger.debug(f"Generated CSRF token (length: {len(csrf_token)})")
    
    # Check if session was updated
    session_after = bool(session)
    logger.debug(f"Session active after token generation: {session_after}")
    
    # Set a test value in session to ensure it's working
    session['test_login_view'] = 'active'
    
    if current_user.is_authenticated:
        logger.debug("User already authenticated, redirecting to index")
        return redirect(url_for('index'))
    
    form = LoginForm()
    
    # Log CSRF token details from form
    if hasattr(form, 'csrf_token'):
        logger.debug(f"Form has CSRF token field: {hasattr(form.csrf_token, 'current_token')}")
        if hasattr(form.csrf_token, 'current_token'):
            logger.debug(f"Form CSRF token is present: {bool(form.csrf_token.current_token)}")
    
    # Log form data and validation for debugging
    if request.method == 'POST':
        logger.info(f"Login attempt for email: {request.form.get('email', 'not provided')}")
        logger.debug(f"POST request headers: {dict(request.headers)}")
        logger.debug(f"POST form data keys: {list(request.form.keys())}")
        logger.debug(f"CSRF token in form: {'csrf_token' in request.form}")
        
        if 'csrf_token' in request.form:
            form_token = request.form.get('csrf_token')
            logger.debug(f"Form CSRF token length: {len(form_token)}")
            # Don't log the actual token for security reasons
        
    if form.validate_on_submit():
        logger.info("Form validated successfully")
        user = User.query.filter_by(email=form.email.data).first()
        
        if user and user.check_password(form.password.data):
            login_user(user, remember=form.remember.data)
            next_page = request.args.get('next')
            
            # Debug session after login
            logger.debug(f"User {user.email} logged in - Session active: {bool(session)}")
            logger.debug("Setting authenticated user session marker")
            session['user_authenticated'] = True
            
            logger.info(f"User {user.email} logged in successfully, redirecting to {next_page or 'index'}")
            return redirect(next_page or url_for('index'))
        
        logger.warning(f"Failed login attempt for email: {form.email.data}")
        flash('Invalid email or password', 'danger')
    elif request.method == 'POST':
        # Log validation errors in detail
        logger.warning(f"Form validation failed: {form.errors}")
        
        # Special handling for CSRF errors
        if 'csrf_token' in form.errors:
            logger.error("CSRF validation failed during form validation")
            logger.debug(f"Session contains csrf_token: {'csrf_token' in session}")
            if 'csrf_token' in session:
                logger.debug(f"Session token length: {len(session['csrf_token'])}")
            flash('CSRF validation failed. Please try again.', 'danger')
        else:
            flash('Please correct the errors in the form', 'danger')
    
    # Debug session before rendering template
    logger.debug(f"Before rendering template - Session active: {bool(session)}")
    if session:
        logger.debug(f"Session keys: {list(session.keys())}")
    
    return render_template('auth/login.html', form=form)

@auth.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    
    # Debug logging for GET requests
    if request.method == 'GET':
        logger.debug("GET request to registration form")
    
    form = RegisterForm()
    
    # Debug logging for form creation
    logger.debug(f"RegisterForm created, has CSRF token field: {'csrf_token' in form._fields}")
    if 'csrf_token' in form._fields:
        logger.debug(f"CSRF token value exists: {bool(form.csrf_token.current_token)}")
        # Do not log the actual token value for security reasons
    
    # Log registration attempts for debugging
    if request.method == 'POST':
        logger.info(f"Registration attempt for email: {request.form.get('email', 'not provided')}")
        logger.debug(f"Form data: {request.form}")
        logger.debug(f"CSRF Token present: {'csrf_token' in request.form}")
        if 'csrf_token' in request.form:
            logger.debug(f"CSRF Token value length: {len(request.form.get('csrf_token', ''))}")
    
    if form.validate_on_submit():
        logger.info("Registration form validated successfully")
        
        # Create a new user
        user = User(
            username=form.username.data,
            email=form.email.data
        )
        user.set_password(form.password.data)
        
        # Save to database
        db.session.add(user)
        db.session.commit()
        
        logger.info(f"User {user.email} registered successfully")
        flash('Registration successful! You can now log in.', 'success')
        return redirect(url_for('auth.login'))
    elif request.method == 'POST':
        # Log validation errors
        logger.warning(f"Registration form validation failed: {form.errors}")
        
        # If CSRF validation is the issue, log more detailed information
        if 'csrf_token' in form.errors:
            logger.error("CSRF validation failed")
            logger.debug(f"Request headers: {dict(request.headers)}")
            logger.debug(f"Request method: {request.method}")
            logger.debug(f"Request endpoint: {request.endpoint}")
            try:
                logger.debug(f"Session contains CSRF token: {'csrf_token' in session}")
            except Exception as e:
                logger.error(f"Error accessing session: {str(e)}")
            # Don't log the actual token values for security reasons
            # Add specific flash for CSRF errors
            flash('Form validation failed. Please try again.', 'danger')
        else:
            flash('Please correct the errors in the form', 'danger')
    
    # Log final form status before rendering
    logger.debug(f"Form before rendering - CSRF token field exists: {'csrf_token' in form._fields}")
    logger.debug(f"Form has errors: {bool(form.errors)}")
    if form.errors:
        logger.debug(f"Form error fields: {list(form.errors.keys())}")
    
    try:
        # Log DEBUG info about CSRF token in GET requests
        if request.method == 'GET':
            form_html = str(form.csrf_token)
            logger.debug(f"CSRF token HTML output starts with: {form_html[:50]}...")
        
        # Return rendered template directly
        return render_template('auth/register.html', form=form)
    except Exception as e:
        # Handle template rendering errors
        logger.error(f"Error rendering registration template: {str(e)}")
        flash('An error occurred while processing your request', 'danger')
        return redirect(url_for('index'))

@auth.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'success')
    return redirect(url_for('index'))

@auth.route('/profile')
@login_required
def profile():
    return render_template('auth/profile.html')
