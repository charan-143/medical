// Main JavaScript file for Medical Dashboard
document.addEventListener('DOMContentLoaded', function() {
    // Reference sidebar and content for potential future functionality
    const sidebar = document.getElementById('sidebar');
    const content = document.getElementById('content');
    
    // Initialize Bootstrap tooltips
    var tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
    var tooltipList = tooltipTriggerList.map(function (tooltipTriggerEl) {
        return new bootstrap.Tooltip(tooltipTriggerEl);
    });
    
    // Initialize Bootstrap popovers
    var popoverTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="popover"]'));
    var popoverList = popoverTriggerList.map(function (popoverTriggerEl) {
        return new bootstrap.Popover(popoverTriggerEl);
    });
    
    // File upload handling
    const fileInput = document.getElementById('recordFile');
    const filePreview = document.getElementById('filePreview');
    
    if (fileInput) {
        fileInput.addEventListener('change', function() {
            const fileName = this.files[0]?.name;
            const label = document.querySelector('label[for="recordFile"]');
            if (label) {
                label.textContent = fileName || 'Choose file';
            }
            
            // If preview exists, show file preview
            if (filePreview) {
                filePreview.innerHTML = '';
                const files = this.files;
                
                for (let i = 0; i < files.length; i++) {
                    const file = files[i];
                    const fileItem = document.createElement('div');
                    fileItem.classList.add('file-preview-item');
                    
                    const fileName = document.createElement('p');
                    fileName.textContent = file.name;
                    
                    fileItem.appendChild(fileName);
                    filePreview.appendChild(fileItem);
                }
            }
        });
    }
    
    // Initialize charts if they exist
    initializeCharts();
});

// Function to initialize charts
function initializeCharts() {
    // Check if Chart.js is loaded and if the chart containers exist
    if (typeof Chart !== 'undefined') {
        // Blood Pressure Chart
        const bpChartElem = document.getElementById('bloodPressureChart');
        if (bpChartElem) {
            const bpChart = new Chart(bpChartElem, {
                type: 'line',
                data: {
                    labels: ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun'],
                    datasets: [{
                        label: 'Systolic',
                        data: [120, 118, 125, 119, 122, 118],
                        borderColor: 'rgba(255, 99, 132, 1)',
                        backgroundColor: 'rgba(255, 99, 132, 0.2)',
                        tension: 0.3
                    },
                    {
                        label: 'Diastolic',
                        data: [80, 78, 83, 79, 80, 77],
                        borderColor: 'rgba(54, 162, 235, 1)',
                        backgroundColor: 'rgba(54, 162, 235, 0.2)',
                        tension: 0.3
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    scales: {
                        y: {
                            beginAtZero: false,
                            min: 60,
                            title: {
                                display: true,
                                text: 'mmHg'
                            }
                        }
                    }
                }
            });
        }
        
        // Heart Rate Chart
        const hrChartElem = document.getElementById('heartRateChart');
        if (hrChartElem) {
            const hrChart = new Chart(hrChartElem, {
                type: 'line',
                data: {
                    labels: ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun'],
                    datasets: [{
                        label: 'Heart Rate',
                        data: [72, 75, 70, 74, 68, 72],
                        borderColor: 'rgba(75, 192, 192, 1)',
                        backgroundColor: 'rgba(75, 192, 192, 0.2)',
                        tension: 0.3
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    scales: {
                        y: {
                            beginAtZero: false,
                            min: 50,
                            title: {
                                display: true,
                                text: 'BPM'
                            }
                        }
                    }
                }
            });
        }
        
        // Blood Sugar Chart
        const bsChartElem = document.getElementById('bloodSugarChart');
        if (bsChartElem) {
            const bsChart = new Chart(bsChartElem, {
                type: 'line',
                data: {
                    labels: ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun'],
                    datasets: [{
                        label: 'Blood Sugar',
                        data: [95, 105, 92, 98, 90, 94],
                        borderColor: 'rgba(153, 102, 255, 1)',
                        backgroundColor: 'rgba(153, 102, 255, 0.2)',
                        tension: 0.3
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    scales: {
                        y: {
                            beginAtZero: false,
                            min: 70,
                            title: {
                                display: true,
                                text: 'mg/dL'
                            }
                        }
                    }
                }
            });
        }
    }
}
