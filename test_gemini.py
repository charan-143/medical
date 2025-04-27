import google.generativeai as genai
import os
from dotenv import load_dotenv

load_dotenv()

api_key = os.getenv('GEMINI_API_KEY')
print(f"Testing Gemini API initialization with key: {'*' * len(api_key)}")

try:
    genai.configure(api_key=api_key)
    
    # Try both available models
    for model_name in ['gemini-pro', 'gemini-1.0-pro']:
        print(f"\nTesting with model: {model_name}")
        try:
            model = genai.GenerativeModel(model_name)
            response = model.generate_content('Hello, are you working?')
            print("API Test Response:", response.text)
            print("API initialization successful!")
        except Exception as e:
            print(f"Failed with model {model_name}:", str(e))

except Exception as e:
    print("API configuration failed with error:", str(e))

