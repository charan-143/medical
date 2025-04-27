/**
 * Folder Summary Regeneration Functionality
 * 
 * This file handles the functionality for regenerating AI-generated folder summaries.
 */

// Add marked.js for Markdown parsing
const markedScript = document.createElement('script');
markedScript.src = 'https://cdn.jsdelivr.net/npm/marked/marked.min.js';
document.head.appendChild(markedScript);

// Add DOMPurify for HTML sanitization
const purifyScript = document.createElement('script');
purifyScript.src = 'https://cdnjs.cloudflare.com/ajax/libs/dompurify/3.0.6/purify.min.js';
document.head.appendChild(purifyScript);

// Format timestamp function for the summary
function formatTimestamp(dateString) {
    if (!dateString) return '';
    const date = new Date(dateString);
    return date.toLocaleString();
}

// Function to safely parse and render markdown
function renderMarkdown(markdownText) {
    try {
        // Wait for marked.js to be loaded
        if (typeof marked === 'undefined') {
            console.warn('Marked.js not loaded yet, falling back to plain text');
            return markdownText.replace(/\n/g, '<br>');
        }

        // Configure marked options for security and features
        marked.setOptions({
            headerIds: false, // Disable automatic header IDs
            mangle: false, // Disable mangling
            breaks: true, // Enable line breaks
            gfm: true, // Enable GitHub Flavored Markdown
            pedantic: false,
            sanitize: true, // Basic sanitization (though we'll use DOMPurify too)
        });

        // Parse markdown to HTML
        let html = marked.parse(markdownText);

        // Additional sanitization with DOMPurify if available
        if (typeof DOMPurify !== 'undefined') {
            html = DOMPurify.sanitize(html, {
                ALLOWED_TAGS: [
                    'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
                    'p', 'br', 'b', 'i', 'strong', 'em',
                    'ul', 'ol', 'li', 'code', 'pre',
                    'table', 'thead', 'tbody', 'tr', 'th', 'td',
                    'blockquote', 'hr', 'a'
                ],
                ALLOWED_ATTR: ['href', 'target', 'class']
            });
        }

        return html;
    } catch (error) {
        console.error('Error rendering markdown:', error);
        // Fallback to basic HTML escaping
        return markdownText
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/\n/g, '<br>');
    }
}

// Summary regeneration functionality
document.addEventListener('DOMContentLoaded', function() {
    const regenerateBtn = document.getElementById('regenerateSummaryBtn');
    const summaryContent = document.getElementById('summaryContent');
    const summaryLoading = document.getElementById('summaryLoading');
    const summaryError = document.getElementById('summaryError');
    const summaryText = document.getElementById('summaryText');
    const summaryTimestamp = document.getElementById('summaryTimestamp');
    const errorMessage = document.getElementById('errorMessage');
    
    if (regenerateBtn) {
        regenerateBtn.addEventListener('click', function() {
            const folderId = this.getAttribute('data-folder-id');
            if (!folderId) {
                showSummaryError('No folder ID specified');
                return;
            }
            
            // Show loading state
            if (summaryContent) summaryContent.classList.add('d-none');
            if (summaryLoading) summaryLoading.classList.remove('d-none');
            if (summaryError) summaryError.classList.add('d-none');
            
            // Disable the button during regeneration
            regenerateBtn.disabled = true;
            regenerateBtn.innerHTML = '<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span> Generating...';
            
            // Make the AJAX request
            fetch(`/dashboard/regenerate_summary/${folderId}`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': document.querySelector('input[name="csrf_token"]')?.value
                }
            })
            .then(response => {
                if (!response.ok) {
                    throw new Error(`Server returned ${response.status}: ${response.statusText}`);
                }
                return response.json();
            })
            .then(data => {
                if (data.success) {
                    // Update the summary content with markdown rendering
                    if (summaryText) {
                        // Render markdown content
                        const renderedContent = renderMarkdown(data.summary);
                        summaryText.innerHTML = renderedContent;
                    }
                    
                    // Update the timestamp
                    if (summaryTimestamp) {
                        summaryTimestamp.textContent = `Last updated: ${formatTimestamp(data.last_updated)}`;
                    }
                    
                    // Show success message
                    showMessage('Summary regenerated successfully', 'success');
                    
                    // Show the content
                    if (summaryContent) summaryContent.classList.remove('d-none');
                } else {
                    throw new Error(data.message || 'Failed to regenerate summary');
                }
            })
            .catch(error => {
                showSummaryError(error.message);
                console.error('Error regenerating summary:', error);
            })
            .finally(() => {
                // Hide loading state and restore button
                if (summaryLoading) summaryLoading.classList.add('d-none');
                regenerateBtn.disabled = false;
                regenerateBtn.innerHTML = '<i class="fas fa-sync-alt me-1"></i> Regenerate';
            });
        });
    }
    
    // Helper function to show error message
    function showSummaryError(message) {
        if (summaryError && errorMessage) {
            // Render error message as markdown
            errorMessage.innerHTML = renderMarkdown(`## Error\n\n${message}`);
            summaryError.classList.remove('d-none');
        }
        
        if (summaryContent) {
            if (summaryText && summaryText.innerHTML.trim()) {
                // If we have existing content, show it alongside the error
                summaryContent.classList.remove('d-none');
            } else {
                // Otherwise, hide the empty content div
                summaryContent.classList.add('d-none');
            }
        }
    }
    
    // Helper function to show toast message - if not defined globally
    if (typeof showMessage !== 'function') {
        window.showMessage = function(message, type = 'info') {
            const alertDiv = document.createElement('div');
            alertDiv.className = `alert alert-${type} alert-dismissible fade show position-fixed top-0 end-0 m-3`;
            alertDiv.style.zIndex = '9999';
            alertDiv.innerHTML = `
                ${message}
                <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
            `;
            document.body.appendChild(alertDiv);
            setTimeout(() => alertDiv.remove(), 5000);
        };
    }
});

