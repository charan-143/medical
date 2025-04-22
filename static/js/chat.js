// Chat functionality for Medical Dashboard

document.addEventListener('DOMContentLoaded', function() {
    // Check if we're on the chat page
    const chatContainer = document.querySelector('.chat-container');
    if (!chatContainer) return;
    
    // Socket.IO setup
    const socket = io();
    
    // DOM Elements
    const chatForm = document.getElementById('chatForm');
    const chatInput = document.getElementById('chatInput');
    const chatMessages = document.querySelector('.chat-messages');
    const fileUploadBtn = document.getElementById('fileUploadBtn');
    const fileInput = document.getElementById('chatFileUpload');
    const micButton = document.getElementById('micButton');
    
    // Voice recording variables
    let mediaRecorder;
    let audioChunks = [];
    let isRecording = false;
    
    // Connect to socket
    socket.on('connect', () => {
        console.log('Connected to chat server');
        // Connection message removed
    });
    
    // Disconnect from socket
    socket.on('disconnect', () => {
        console.log('Disconnected from chat server');
        // Connection message removed
    });
    
    // Receive message
    socket.on('response', (data) => {
        addMessage(data.data, 'ai');
        // Scroll to bottom of chat
        chatMessages.scrollTop = chatMessages.scrollHeight;
    });
    
    // Send message on form submit
    if (chatForm) {
        chatForm.addEventListener('submit', function(e) {
            e.preventDefault();
            
            const message = chatInput.value.trim();
            if (message) {
                // Add user message to chat
                addMessage(message, 'user');
                
                // Send message to server
                socket.emit('message', { data: message });
                
                // Clear input
                chatInput.value = '';
                
                // Scroll to bottom of chat
                chatMessages.scrollTop = chatMessages.scrollHeight;
            }
        });
    }
    
    // File upload button click
    if (fileUploadBtn && fileInput) {
        fileUploadBtn.addEventListener('click', function(e) {
            fileInput.click();
        });
        
        fileInput.addEventListener('change', function(e) {
            if (fileInput.files.length > 0) {
                handleFileUpload(fileInput.files[0]);
            }
        });
    }
    
    // Microphone button click
    if (micButton) {
        micButton.addEventListener('click', function() {
            if (!isRecording) {
                startRecording();
            } else {
                stopRecording();
            }
        });
    }
    
    // Function to add a message to the chat
    function addMessage(message, sender) {
        const messageDiv = document.createElement('div');
        messageDiv.className = `message message-${sender}`;
        
        // Add avatar
        const avatarDiv = document.createElement('div');
        avatarDiv.className = 'message-avatar';
        if (sender === 'ai') {
            avatarDiv.innerHTML = '<i class="fas fa-robot"></i>';
        } else {
            avatarDiv.innerHTML = '<i class="fas fa-user"></i>';
        }
        messageDiv.appendChild(avatarDiv);
        
        // Content wrapper
        const contentWrapper = document.createElement('div');
        contentWrapper.className = 'message-content-wrapper';
        
        const contentDiv = document.createElement('div');
        contentDiv.className = 'message-content';
        contentDiv.textContent = message;
        
        contentWrapper.appendChild(contentDiv);
        
        const timestamp = document.createElement('span');
        timestamp.className = 'message-timestamp';
        const now = new Date();
        timestamp.textContent = now.toLocaleTimeString();
        contentWrapper.appendChild(timestamp);
        
        messageDiv.appendChild(contentWrapper);
        
        chatMessages.appendChild(messageDiv);
        chatMessages.scrollTop = chatMessages.scrollHeight;
    }
});
