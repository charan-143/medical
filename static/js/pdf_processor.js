/**
 * PDF Processor - JavaScript module for handling PDF image processing with Gemini AI
 * 
 * Features:
 * - Dynamic loading of PDF processing results
 * - Image viewer/gallery functionality
 * - Loading states during processing
 * - Error handling and retries
 */

class PDFProcessor {

    /**
     * Utility function to escape HTML special characters
     * @param {string} str - The string to escape
     * @returns {string} - The escaped string
     */
    escapeHTML(str) {
        return str.replace(/[&<>"']/g, (char) => {
            const escapeMap = {
                '&': '&amp;',
                '<': '&lt;',
                '>': '&gt;',
                '"': '&quot;',
                "'": '&#39;'
            };
            return escapeMap[char];
        });
    }
    constructor() {
        // Configuration
        this.config = {
            processingEndpoint: '/api/process-pdf-images',
            maxRetries: 2,
            loadingTimeout: 30000 // 30 seconds timeout
        };
        
        // State
        this.state = {
            isProcessing: false,
            currentDocumentId: null,
            retryCount: 0,
            processingTimer: null,
            imageGalleryIndex: 0
        };
        
        // Initialize
        this.init();
    }
    
    /**
     * Initialize the PDF processor
     */
    init() {
        // Add event listeners when viewing a document
        this.attachEventListeners();
        
        // Check if we're currently viewing a document with the view_document parameter
        this.checkCurrentDocument();
        
        // Setup UI components
        this.setupImageGallery();
    }
    
    /**
     * Attach event listeners to document elements
     */
    attachEventListeners() {
        // Process PDF button click
        document.addEventListener('click', (e) => {
            if (e.target.matches('#process-pdf-btn')) {
                e.preventDefault();
                const documentId = e.target.dataset.documentId;
                this.processPDFImages(documentId);
            }
            
            // Image gallery navigation
            if (e.target.matches('.gallery-nav-btn') || e.target.closest('.gallery-nav-btn')) {
                e.preventDefault();
                const btn = e.target.matches('.gallery-nav-btn') ? e.target : e.target.closest('.gallery-nav-btn');
                const direction = btn.dataset.direction;
                this.navigateGallery(direction);
            }
            
            // Image click for fullscreen view
            if (e.target.matches('.result-image')) {
                this.openImageViewer(e.target);
            }
        });
        
        // Retry button click
        document.addEventListener('click', (e) => {
            if (e.target.matches('.retry-processing-btn')) {
                e.preventDefault();
                const documentId = e.target.dataset.documentId;
                this.retryProcessing(documentId);
            }
        });
    }
    
    /**
     * Check if we're currently viewing a document
     */
    checkCurrentDocument() {
        const urlParams = new URLSearchParams(window.location.search);
        const viewDocumentId = urlParams.get('view_document');
        
        if (viewDocumentId && document.querySelector('#pdf-viewer')) {
            // Auto-process the PDF if it's being viewed
            this.checkProcessingStatus(viewDocumentId);
        }
    }
    
    /**
     * Check if the PDF has already been processed or needs processing
     */
    checkProcessingStatus(documentId) {
        const processingContainer = document.querySelector('#pdf-processing-container');
        
        if (!processingContainer) return;
        
        // If the container has results already, don't reprocess
        if (processingContainer.querySelector('.processing-results')) {
            return;
        }
        
        // If the file is a PDF, show the process button
        const fileType = processingContainer.dataset.fileType;
        if (fileType && fileType.toLowerCase() === 'pdf') {
            this.showProcessButton(documentId);
        }
    }
    
    /**
     * Show the button to process PDF images
     */
    showProcessButton(documentId) {
        const processingContainer = document.querySelector('#pdf-processing-container');
        
        if (!processingContainer) return;
        
        processingContainer.innerHTML = `
            <div class="pdf-processing-prompt text-center p-4">
                <p>Would you like to analyze this PDF for images using Gemini 2.0 Flash?</p>
                <button id="process-pdf-btn" class="btn btn-primary" data-document-id="${this.escapeHTML(documentId)}">
                    <i class="fas fa-brain"></i> Analyze PDF Images
                </button>
            </div>
        `;
    }
    
    /**
     * Process images from a PDF document
     */
    processPDFImages(documentId) {
        if (this.state.isProcessing) return;
        
        this.state.isProcessing = true;
        this.state.currentDocumentId = documentId;
        this.state.retryCount = 0;
        
        // Show loading state
        this.showLoadingState();
        
        // Set timeout for processing
        this.state.processingTimer = setTimeout(() => {
            this.handleProcessingTimeout();
        }, this.config.loadingTimeout);
        
        // Make the API request
        fetch(`${this.config.processingEndpoint}/${documentId}`)
            .then(response => {
                if (!response.ok) {
                    throw new Error(`Status: ${response.status}`);
                }
                return response.json();
            })
            .then(data => {
                this.handleProcessingSuccess(data);
            })
            .catch(error => {
                this.handleProcessingError(error);
            })
            .finally(() => {
                clearTimeout(this.state.processingTimer);
                this.state.isProcessing = false;
                this.hideLoadingState();
            });
    }
    
    /**
     * Handle successful processing response
     */
    handleProcessingSuccess(data) {
        if (!data.success) {
            this.showErrorMessage(data.message || 'Error processing PDF');
            return;
        }
        
        const processingContainer = document.querySelector('#pdf-processing-container');
        
        if (!processingContainer) return;
        
        // Check if any images were found
        if (!data.results || data.results.length === 0) {
            processingContainer.innerHTML = `
                <div class="alert alert-info">
                    <i class="fas fa-info-circle"></i> No images were found in this PDF document.
                </div>
            `;
            return;
        }
        
        // Display the results
        this.displayProcessingResults(data.results);
    }
    
    /**
     * Display the processing results in the container
     */
    displayProcessingResults(results) {
        const processingContainer = document.querySelector('#pdf-processing-container');
        
        if (!processingContainer) return;
        
        // Create results container
        const resultsHtml = `
            <div class="processing-results">
                <h4 class="mb-3">
                    <i class="fas fa-image"></i> Gemini 2.0 Flash Image Analysis
                    <small class="text-muted">(${results.length} images found)</small>
                </h4>
                
                <div id="image-gallery-container" class="mt-4">
                    <div class="image-gallery-controls d-flex justify-content-between mb-3">
                        <button class="btn btn-outline-secondary gallery-nav-btn" data-direction="prev" disabled>
                            <i class="fas fa-chevron-left"></i> Previous
                        </button>
                        <span class="gallery-counter">Image 1 of ${results.length}</span>
                        <button class="btn btn-outline-secondary gallery-nav-btn" data-direction="next" ${results.length > 1 ? '' : 'disabled'}>
                            Next <i class="fas fa-chevron-right"></i>
                        </button>
                    </div>
                    
                    <div id="image-gallery-slides"></div>
                </div>
            </div>
        `;
        
        processingContainer.innerHTML = resultsHtml;
        
        // Add the image slides
        const slidesContainer = document.getElementById('image-gallery-slides');
        
        results.forEach((result, index) => {
            const slide = document.createElement('div');
            slide.className = `image-slide ${index === 0 ? 'active' : 'hidden'}`;
            slide.dataset.index = index;
            
            slide.innerHTML = `
                <div class="card">
                    <div class="card-header">
                        <h5 class="mb-0">Image from page ${result.page_num}</h5>
                    </div>
                    <div class="card-body">
                        <div class="row">
                            <div class="col-md-6 text-center mb-3">
                                <img src="data:image/${result.format};base64,${result.image_data}" 
                                     class="result-image img-fluid" 
                                     alt="Image from page ${result.page_num}"
                                     data-page="${result.page_num}"
                                     data-index="${index}">
                            </div>
                            <div class="col-md-6">
                                <h5>AI Analysis:</h5>
                                <div class="analysis-content">
                                    ${result.error ? 
                                      `<div class="alert alert-warning">${result.analysis}</div>` : 
                                      `<div class="analysis-text">${this.formatAnalysisText(result.analysis)}</div>`
                                    }
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            `;
            
            slidesContainer.appendChild(slide);
        });
        
        // Set initial state
        this.state.imageGalleryIndex = 0;
        this.updateGalleryControls();
    }
    
    /**
     * Format analysis text with proper styling
     */
    formatAnalysisText(text) {
        if (!text) return '';
        
        // Replace newlines with <br> tags
        let formattedText = text.replace(/\n/g, '<br>');
        
        // Make numbered points bold
        formattedText = formattedText.replace(/(\d+\.\s)([^<]+)/g, '<strong>$1</strong>$2');
        
        return formattedText;
    }
    
    /**
     * Set up the image gallery functionality
     */
    setupImageGallery() {
        // Create image viewer modal if it doesn't exist
        if (!document.getElementById('image-viewer-modal')) {
            const modal = document.createElement('div');
            modal.className = 'modal fade';
            modal.id = 'image-viewer-modal';
            modal.setAttribute('tabindex', '-1');
            modal.setAttribute('role', 'dialog');
            modal.setAttribute('aria-hidden', 'true');
            
            modal.innerHTML = `
                <div class="modal-dialog modal-dialog-centered modal-lg">
                    <div class="modal-content">
                        <div class="modal-header">
                            <h5 class="modal-title">Image Viewer</h5>
                            <button type="button" class="close" data-dismiss="modal" aria-label="Close">
                                <span aria-hidden="true">&times;</span>
                            </button>
                        </div>
                        <div class="modal-body text-center">
                            <img id="viewer-image" class="img-fluid" src="" alt="Full size image">
                        </div>
                    </div>
                </div>
            `;
            
            document.body.appendChild(modal);
        }
    }
    
    /**
     * Navigate through the image gallery
     */
    navigateGallery(direction) {
        const totalImages = document.querySelectorAll('.image-slide').length;
        
        if (totalImages <= 1) return;
        
        // Update index based on direction
        if (direction === 'next') {
            this.state.imageGalleryIndex = (this.state.imageGalleryIndex + 1) % totalImages;
        } else if (direction === 'prev') {
            this.state.imageGalleryIndex = (this.state.imageGalleryIndex - 1 + totalImages) % totalImages;
        }
        
        // Update visible slide
        const slides = document.querySelectorAll('.image-slide');
        slides.forEach(slide => {
            slide.classList.add('hidden');
            slide.classList.remove('active');
        });
        
        const activeSlide = document.querySelector(`.image-slide[data-index="${this.state.imageGalleryIndex}"]`);
        if (activeSlide) {
            activeSlide.classList.remove('hidden');
            activeSlide.classList.add('active');
        }
        
        // Update controls
        this.updateGalleryControls();
    }
    
    /**
     * Update gallery control buttons and counter
     */
    updateGalleryControls() {
        const totalImages = document.querySelectorAll('.image-slide').length;
        const counter = document.querySelector('.gallery-counter');
        const prevBtn = document.querySelector('.gallery-nav-btn[data-direction="prev"]');
        const nextBtn = document.querySelector('.gallery-nav-btn[data-direction="next"]');
        
        if (!counter || !prevBtn || !nextBtn) return;
        
        // Update counter
        counter.textContent = `Image ${this.state.imageGalleryIndex + 1} of ${totalImages}`;
        
        // Update buttons
        prevBtn.disabled = totalImages <= 1 || this.state.imageGalleryIndex === 0;
        nextBtn.disabled = totalImages <= 1 || this.state.imageGalleryIndex === totalImages - 1;
    }
    
    /**
     * Open image viewer modal
     */
    openImageViewer(imageElement) {
        const modal = document.getElementById('image-viewer-modal');
        const viewerImage = document.getElementById('viewer-image');
        
        if (!modal || !viewerImage) return;
        
        // Set image source and show modal
        viewerImage.src = imageElement.src;
        viewerImage.alt = imageElement.alt;
        
        // Use Bootstrap's modal functionality
        $(modal).modal('show');
    }
    
    /**
     * Retry processing after an error
     */
    retryProcessing(documentId) {
        if (this.state.retryCount >= this.config.maxRetries) {
            this.showErrorMessage('Maximum retry attempts reached. Please try again later.');
            return;
        }
        
        this.state.retryCount++;
        this.processPDFImages(documentId);
    }
    
    /**
     * Handle processing timeout
     */
    handleProcessingTimeout() {
        this.hideLoadingState();
        this.state.isProcessing = false;
        
        const processingContainer = document.querySelector('#pdf-processing-container');
        
        if (!processingContainer) return;
        
        processingContainer.innerHTML = `
            <div class="alert alert-warning">
                <p><i class="fas fa-exclamation-triangle"></i> Processing timeout - this might be due to a large PDF file or high server load.</p>
                <button class="btn btn-primary retry-processing-btn" data-document-id="${this.state.currentDocumentId}">
                    <i class="fas fa-sync"></i> Retry Processing
                </button>
            </div>
        `;
    }
    
    /**
     * Handle processing error
     */
    handleProcessingError(error) {
        console.error('PDF processing error:', error);
        
        const processingContainer = document.querySelector('#pdf-processing-container');
        
        if (!processingContainer) return;
        
        processingContainer.innerHTML = `
            <div class="alert alert-danger">
                <p><i class="fas fa-exclamation-circle"></i> Error processing PDF: ${error.message}</p>
                <button class="btn btn-primary retry-processing-btn" data-document-id="${this.state.currentDocumentId}">
                    <i class="fas fa-sync"></i> Retry Processing
                </button>
            </div>
        `;
    }
    
    /**
     * Show error message to user
     */
    showErrorMessage(message) {
        const processingContainer = document.querySelector('#pdf-processing-container');
        
        if (!processingContainer) return;
        
        processingContainer.innerHTML = `
            <div class="alert alert-danger">
                <p><i class="fas fa-exclamation-circle"></i> ${message}</p>
                ${this.state.currentDocumentId ? `
                    <button class="btn btn-primary retry-processing-btn" data-document-id="${this.state.currentDocumentId}">
                        <i class="fas fa-sync"></i> Retry Processing
                    </button>
                ` : ''}
            </div>
        `;
    }
    
    /**
     * Show loading state during processing
     */
    showLoadingState() {
        const processingContainer = document.querySelector('#pdf-processing-container');
        
        if (!processingContainer) return;
        
        processingContainer.innerHTML = `
            <div class="text-center p-4">
                <div class="spinner-border text-primary mb-3" role="status">
                    <span class="sr-only">Processing...</span>
                </div>
                <p class="mb-0">Analyzing PDF images with Gemini 2.0 Flash...</p>
                <small class="text-muted">This may take a few moments depending on the file size</small>
            </div>
        `;
    }
    
    /**
     * Hide loading state
     */
    hideLoadingState() {
        clearTimeout(this.state.processingTimer);
        this.state.processingTimer = null;
    }
}

// Initialize the PDF processor when document is ready
document.addEventListener('DOMContentLoaded', () => {
    window.pdfProcessor = new PDFProcessor();
});
