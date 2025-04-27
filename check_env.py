import os
from dotenv import load_dotenv

load_dotenv()
api_key = os.getenv('GEMINI_API_KEY')
print(f'GEMINI_API_KEY is {"set" if api_key else "not set"}')
print(f'Value: {api_key}')

