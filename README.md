# Medical Dashboard

A comprehensive web-based medical dashboard application for managing medical records, documents, and facilitating communication between healthcare professionals.

## Features

- **User Authentication**: Secure login and registration system with admin capabilities
- **Document Management**: Upload, store, and organize medical documents and files
- **Dashboard Interface**: Intuitive interface for viewing and managing medical data
- **Real-time Chat**: Communication between healthcare professionals using SocketIO
- **PDF Generation**: Create PDF reports from medical data
- **Folder Organization**: Organize medical documents in a hierarchical folder structure
- **AI Integration**: Integration with Google's Generative AI capabilities
- **Data Security**: CSRF protection and secure password handling with bcrypt

## Technologies Used

- **Backend**: Flask (Python web framework)
- **Database**: SQLAlchemy with SQLite
- **Authentication**: Flask-Login, bcrypt
- **Frontend**: Flask templates, JavaScript
- **Real-time Communication**: Flask-SocketIO, WebSockets
- **Form Handling**: Flask-WTF, WTForms
- **File Handling**: Pillow for image processing, pdfkit for PDF generation
- **Cloud Storage**: AWS integration via boto3
- **AI Capabilities**: Google Generative AI
- **Deployment**: gunicorn server

## Installation

This application requires Python 3.8 or higher.

1. Clone the repository:
   ```
   git clone https://github.com/charan-143/medical.git
   cd medical
   ```

2. Create and activate a virtual environment:
   ```
   python -m venv venv
   # On Windows
   venv\Scripts\activate
   # On macOS/Linux
   source venv/bin/activate
   ```

3. Install the required dependencies:
   ```
   pip install -r requirements.txt
   ```

4. Install wkhtmltopdf (required for PDF generation):
   - **Windows**: Download and install from [wkhtmltopdf.org](https://wkhtmltopdf.org/downloads.html)
   - **macOS**: `brew install wkhtmltopdf`
   - **Linux**: `sudo apt-get install wkhtmltopdf` (Ubuntu/Debian) or equivalent for your distribution
## Setup and Configuration

1. Create a `.env` file in the project root and add the necessary environment variables:
   ```
   FLASK_APP=app.py
   FLASK_ENV=development
   SECRET_KEY=your_secret_key_here
   # Add any other environment variables needed for AWS, Google AI, etc.
   ```

2. Initialize the database:
   ```
   flask db init
   flask db migrate -m "Initial migration"
   flask db upgrade
   ```
   The application will create the database and tables based on the models.

3. Create the initial admin user:
   ```
   flask create-admin
   ```
   This will create an admin user with the default credentials listed below.

3. Default admin credentials:
   - Username: admin
   - Email: admin@example.com
   - Password: admin123

## Usage

1. Start the application:
   ```
   flask run
   ```
   or
   ```
   python app.py
   ```

2. Access the application in your web browser at: `http://127.0.0.1:5000`

3. Log in with the default admin credentials or register a new user.

4. Navigate through the dashboard to upload and manage medical documents, communicate with other users via chat, and utilize the various features of the application.

## Project Structure

- **app.py**: Main application entry point
- **config.py**: Configuration settings for different environments
- **models.py**: Database models and schema definitions
- **extensions.py**: Flask extensions initialization
- **requirements.txt**: Required Python packages
- **blueprints/**: Application modules
  - **auth/**: Authentication-related views and forms
  - **dashboard/**: Main dashboard functionality
  - **chat/**: Real-time chat functionality
- **static/**: Static files (CSS, JS, uploads)
- **templates/**: HTML templates
- **instance/**: Instance-specific files, including the SQLite database
- **migrations/**: Database migration scripts


## Development

### Environment Setup

1. Follow the installation steps above to set up your development environment.
2. Use the development server for local testing:
   ```
   flask run --debug
   ```

### Code Style

- Follow PEP 8 style guidelines for Python code
- Use docstrings to document functions and classes
- Run linting before submitting pull requests:
  ```
  flake8 .
  ```

### Database Migrations

When changing models, create new migrations:
```
flask db migrate -m "Description of changes"
flask db upgrade
```

### Testing

Run the test suite before submitting changes:
```
pytest
```

## License

[MIT License](LICENSE)

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

