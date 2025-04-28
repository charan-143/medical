from flask import Flask
from dotenv import load_dotenv
import os

# Load environment variables from a .env file
load_dotenv()

# Initialize Flask application
app: Flask = Flask(__name__)
app.config.from_object('config.Config')

# Print environment variable and app configuration
print("Environment variable:", os.environ.get('GEMINI_API_KEY'))
print("App config:", app.config.get('GEMINI_API_KEY'))
