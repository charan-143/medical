from flask import Flask
from dotenv import load_dotenv
import os

load_dotenv()

app = Flask(__name__)
app.config.from_object('config.Config')

print("Environment variable:", os.environ.get('GEMINI_API_KEY'))
print("App config:", app.config.get('GEMINI_API_KEY'))

