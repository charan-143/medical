from flask import Blueprint, render_template, request, jsonify, current_app
from flask_login import login_required, current_user
from flask_socketio import emit
import google.generativeai as genai
from datetime import datetime
import html
import re
import asyncio
import logging
import os
import base64
import io
from werkzeug.utils import secure_filename
from PIL import Image
import PyPDF2
import mimetypes
from app import socketio
from functools import wraps
chat = Blueprint('chat', __name__, template_folder='templates')

# Dictionary to store conversation history for each user
conversation_history = {}

# Medical context instructions for the AI model
MEDICAL_ASSISTANT_INSTRUCTIONS = """
You are a medical assistant AI. Your role is to:
1. Provide general medical information and educational content
2. Help users understand medical terms and conditions
3. Suggest when users should seek professional medical advice

Important guidelines:
- You CANNOT provide specific medical diagnosis or treatment recommendations
- Always clarify that your responses are for educational purposes only
- Remind users to consult with healthcare professionals for personal medical advice
- Do not prescribe medications or suggest specific treatments
- Be empathetic and professional in all communications
- If you're unsure about something, acknowledge your limitations
- Prioritize user safety and well-being in all interactions
"""

# Initialize Gemini API when the blueprint is registered
def init_gemini_api():
    api_key = current_app.config.get('GEMINI_API_KEY')
    if not api_key:
        logging.error("GEMINI_API_KEY not configured. Chat functionality will not work properly.")
        return False
    
    try:
        genai.configure(api_key=api_key)
        # Set default generation config
        return True
    except Exception as e:
        logging.error(f"Failed to initialize Gemini API: {str(e)}")
        return False

# Helper to sanitize input
def sanitize_input(text):
    if not text or not isinstance(text, str):
        return ""
    # Remove any HTML tags
    text = html.escape(text)
    # Limit length
    return text[:1000]  # Reasonable limit for a chat message

# Function to get or create a conversation for a user
def get_user_conversation(user_id):
    if user_id not in conversation_history:
        # Initialize empty conversation - we'll handle instructions differently
        conversation_history[user_id] = []
    return conversation_history[user_id]

# Utility functions for file processing
def allowed_file(filename):
    """Check if the uploaded file has an allowed extension."""
    ALLOWED_EXTENSIONS = {'pdf', 'png', 'jpg', 'jpeg'}
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def process_image_file(file):
    """Process image file for Gemini model input."""
    try:
        # Open and resize the image if necessary
        image = Image.open(file)
        
        # Convert to bytes
        img_byte_arr = io.BytesIO()
        image.save(img_byte_arr, format=image.format or 'PNG')
        img_bytes = img_byte_arr.getvalue()
        
        # Get MIME type
        mime_type = mimetypes.guess_type(file.filename)[0] or 'image/jpeg'
        
        # Return the processed image data
        return {
            'mime_type': mime_type,
            'data': base64.b64encode(img_bytes).decode('utf-8'),
            'type': 'image'
        }
    except Exception as e:
        logging.error(f"Error processing image: {str(e)}")
        raise

def process_pdf_file(file):
    """Extract text from PDF file for Gemini model."""
    try:
        pdf_reader = PyPDF2.PdfReader(file)
        text_content = ""
        
        # Extract text from all pages
        for page_num in range(len(pdf_reader.pages)):
            page = pdf_reader.pages[page_num]
            page_text = page.extract_text()
            if page_text is not None:
                text_content += page_text + "\n"
        
        return {
            'type': 'text',
            'data': text_content
        }
    except Exception as e:
        logging.error(f"Error processing PDF file: {str(e)}")
        raise

def process_file_for_gemini(file):
    """Process file based on its type for Gemini model input."""
    if not file or not allowed_file(file.filename):
        raise ValueError("Invalid or unsupported file type")
    
    file_extension = file.filename.rsplit('.', 1)[1].lower() if '.' in file.filename else ''
    
    if file_extension in ['png', 'jpg', 'jpeg']:
        return process_image_file(file)
    elif file_extension == 'pdf':
        return process_pdf_file(file)
    else:
        raise ValueError(f"Unsupported file type: {file_extension}")

# Generate response from Gemini
def generate_gemini_response(prompt, user_id, file_content=None):
    try:
        # Get conversation history for this user
        conversation = get_user_conversation(user_id)
        
        # For first message in a new conversation, we'll include instructions in the prompt itself
        is_first_message = len(conversation) == 0
        
        # Prepare message parts
        message_parts = []
        
        # Add text prompt
        message_parts.append(prompt)
        
        # Add file content if provided
        if file_content:
            if file_content['type'] == 'image':
                # For images, add as inline image part
                message_parts.append({
                    "inline_data": {
                        "mime_type": file_content['mime_type'],
                        "data": file_content['data']
                    }
                })
            else:
                # For text (e.g., from PDFs), include in the prompt
                # We limit content length to avoid token limits
                content_preview = file_content['data'][:2000] + "..." if len(file_content['data']) > 2000 else file_content['data']
                message_parts.append("File content:\n" + content_preview)
        
        # Add the user's message to the conversation
        conversation.append({"role": "user", "parts": message_parts})
        
        # Initialize the Gemini model
        model = genai.GenerativeModel(
            model_name="gemini-2.0-flash",
            generation_config={
                "temperature": 0.7,
                "top_p": 0.95,
                "top_k": 40,
                "max_output_tokens": 1024,
            },
            safety_settings=[
                {
                    "category": "HARM_CATEGORY_HATE_SPEECH",
                    "threshold": "BLOCK_MEDIUM_AND_ABOVE"
                },
                {
                    "category": "HARM_CATEGORY_DANGEROUS_CONTENT",
                    "threshold": "BLOCK_MEDIUM_AND_ABOVE"
                },
                {
                    "category": "HARM_CATEGORY_SEXUALLY_EXPLICIT",
                    "threshold": "BLOCK_MEDIUM_AND_ABOVE"
                },
                {
                    "category": "HARM_CATEGORY_HARASSMENT",
                    "threshold": "BLOCK_MEDIUM_AND_ABOVE"
                }
            ]
        )
        
        # Start a chat session
        chat = model.start_chat(history=conversation)
        
        # If this is the first message, include medical instructions
        if is_first_message:
            response = chat.send_message(
                MEDICAL_ASSISTANT_INSTRUCTIONS + "\n\nUser query: " + prompt
            )
        else:
            # For messages with file content, we send the full message parts
            if file_content:
                response = chat.send_message(message_parts)
            else:
                response = chat.send_message(prompt)
        
        # Extract the response text
        response_text = response.text
        
        # Add AI's response to conversation history
        conversation.append({"role": "model", "parts": [response_text]})
        
        # Trim conversation history if it gets too long (keep last 20 messages)
        if len(conversation) > 20:  # Keep last 20 exchanges
            conversation_history[user_id] = conversation[-20:]
        
        return response_text
    
    except Exception as e:
        logging.error(f"Error generating Gemini response: {str(e)}")
        # Return a friendly error message
        return "I'm sorry, I'm having trouble processing your request right now. Please try again in a moment."
@chat.route('/')
@login_required
def index():
    # Main chat interface
    current_time = datetime.now().strftime("%I:%M %p")
    # Initialize Gemini API if needed
    if not hasattr(current_app, '_gemini_initialized'):
        current_app._gemini_initialized = init_gemini_api()
    
    return render_template('chat/index.html', current_time=current_time)
@socketio.on('connect')
def handle_connect():
    # Initialize the API when a user connects if it hasn't been done yet
    if not hasattr(current_app, '_gemini_initialized'):
        current_app._gemini_initialized = init_gemini_api()
    
    if current_user.is_authenticated:
        user_id = str(current_user.id)
        # Initialize user's conversation if it doesn't exist
        if user_id not in conversation_history:
            get_user_conversation(user_id)

@socketio.on('disconnect')
def handle_disconnect():
    # Potential cleanup could happen here
    # For now, we keep conversation history
    pass
@socketio.on('message')
def handle_message(data):
    # Check if Gemini API is initialized
    if not getattr(current_app, '_gemini_initialized', False):
        if not init_gemini_api():
            emit('response', {'data': 'Sorry, the AI service is currently unavailable. Please try again later.'})
            return

    # Input validation
    if not data or not isinstance(data, dict) or 'data' not in data:
        emit('response', {'data': 'Invalid message format. Please try again.'})
        return

    # Get user message
    user_message = data.get('data', '')
    if not user_message or not isinstance(user_message, str) or len(user_message.strip()) == 0:
        emit('response', {'data': 'Please provide a valid message.'})
        return

    # Sanitize input
    sanitized_message = sanitize_input(user_message)
    
    # Get user ID for conversation history
    user_id = str(current_user.id) if current_user.is_authenticated else 'anonymous'
    
    try:
        # Generate response from Gemini API
        response = generate_gemini_response(sanitized_message, user_id)
        
        # Send response back to user
        emit('response', {'data': response})
    
    except Exception as e:
        logging.error(f"Error in chat message handling: {str(e)}")
        emit('response', {'data': 'I apologize, but I encountered an issue processing your message. Please try again.'})
@chat.route('/upload', methods=['POST'])
@login_required
def upload_to_chat():
    """Handle file uploads to the chat and process with Gemini 2.0 flash model"""
    if 'file' not in request.files:
        return jsonify({'success': False, 'error': 'No file provided'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'success': False, 'error': 'No file selected'}), 400
    
    # Ensure filename is secure
    filename = secure_filename(file.filename)
    
    try:
        # Process the file for Gemini model
        processed_file = process_file_for_gemini(file)
        
        # Get user ID for conversation
        user_id = str(current_user.id)
        
        # Store file info
        file_info = {
            'name': filename,
            'type': file.content_type,
            'file_type': processed_file['type']
        }
        
        # Create a prompt based on the file type
        if processed_file['type'] == 'image':
            prompt = f"Please analyze this medical image and provide insights. The image is named '{filename}'."
            file_analysis = generate_gemini_response(prompt, user_id, processed_file)
        else:  # PDF text content
            prompt = f"Please analyze this medical document and provide key insights. The document is named '{filename}'."
            file_analysis = generate_gemini_response(prompt, user_id, processed_file)
        
        return jsonify({
            'success': True, 
            'file': file_info,
            'analysis': file_analysis
        })
        
    except ValueError as ve:
        # Handle validation errors
        return jsonify({'success': False, 'error': str(ve)}), 400
    except Exception as e:
        # Log and handle other errors
        logging.error(f"Error processing file upload: {str(e)}")
        return jsonify({
            'success': False, 
            'error': 'An error occurred while processing your file. Please try again.'
        }), 500

@chat.route('/transcribe', methods=['POST'])
@login_required
def transcribe_audio():
    """Process audio recordings for transcription"""
    if 'audio' not in request.files:
        return jsonify({'success': False, 'error': 'No audio file provided'}), 400
    
    audio_file = request.files['audio']
    
    # For now, return a placeholder response
    # In a future update, this would integrate with a speech-to-text service
    return jsonify({
        'success': True,
        'text': "This is a placeholder for transcribed text. Audio transcription will be implemented in a future update."
    })

# Record when the blueprint was registered
@chat.record
def on_blueprint_registered(state):
    app = state.app
    with app.app_context():
        app._gemini_initialized = init_gemini_api()
        if not app._gemini_initialized:
            app.logger.warning("Gemini API initialization failed. Chat functionality may be limited.")
