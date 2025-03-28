/**
 * College ERP System - Main JavaScript File
 * Contains common functions used across the application
 */

document.addEventListener('DOMContentLoaded', function() {
    // Initialize Bootstrap tooltips
    var tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'))
    var tooltipList = tooltipTriggerList.map(function (tooltipTriggerEl) {
        return new bootstrap.Tooltip(tooltipTriggerEl)
    });
    
    // Initialize Bootstrap popovers
    var popoverTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="popover"]'))
    var popoverList = popoverTriggerList.map(function (popoverTriggerEl) {
        return new bootstrap.Popover(popoverTriggerEl)
    });
    
    // Auto-dismiss alerts
    setTimeout(function() {
        var alerts = document.querySelectorAll('.alert:not(.alert-permanent)');
        alerts.forEach(function(alert) {
            var bsAlert = new bootstrap.Alert(alert);
            bsAlert.close();
        });
    }, 5000);
    
    // Format dates
    formatDates();
    
    // Initialize file dropzones
    initializeFileDropzones();
    
    // Initialize data tables
    initializeDataTables();
});

/**
 * Format dates according to data attributes
 */
function formatDates() {
    document.querySelectorAll('.format-date').forEach(function(element) {
        var dateStr = element.getAttribute('data-date');
        var format = element.getAttribute('data-format') || 'default';
        
        if (!dateStr) return;
        
        var date = new Date(dateStr);
        
        if (isNaN(date.getTime())) return;
        
        if (format === 'relative') {
            element.textContent = getRelativeTime(date);
        } else if (format === 'short') {
            element.textContent = date.toLocaleDateString();
        } else if (format === 'long') {
            element.textContent = date.toLocaleDateString() + ' ' + date.toLocaleTimeString();
        }
    });
}

/**
 * Get relative time string (e.g., "2 days ago")
 */
function getRelativeTime(date) {
    var now = new Date();
    var diff = now - date;
    var diffSeconds = Math.floor(diff / 1000);
    var diffMinutes = Math.floor(diffSeconds / 60);
    var diffHours = Math.floor(diffMinutes / 60);
    var diffDays = Math.floor(diffHours / 24);
    var diffMonths = Math.floor(diffDays / 30);
    var diffYears = Math.floor(diffDays / 365);
    
    if (diffSeconds < 60) {
        return diffSeconds + ' second' + (diffSeconds !== 1 ? 's' : '') + ' ago';
    } else if (diffMinutes < 60) {
        return diffMinutes + ' minute' + (diffMinutes !== 1 ? 's' : '') + ' ago';
    } else if (diffHours < 24) {
        return diffHours + ' hour' + (diffHours !== 1 ? 's' : '') + ' ago';
    } else if (diffDays < 30) {
        return diffDays + ' day' + (diffDays !== 1 ? 's' : '') + ' ago';
    } else if (diffMonths < 12) {
        return diffMonths + ' month' + (diffMonths !== 1 ? 's' : '') + ' ago';
    } else {
        return diffYears + ' year' + (diffYears !== 1 ? 's' : '') + ' ago';
    }
}

/**
 * Initialize file dropzones for file uploads
 */
function initializeFileDropzones() {
    var dropzones = document.querySelectorAll('.file-dropzone');
    
    if (dropzones.length === 0) return;
    
    dropzones.forEach(function(dropzone) {
        var input = dropzone.querySelector('input[type="file"]');
        var preview = dropzone.querySelector('.file-preview');
        var labelText = dropzone.querySelector('.dropzone-label-text');
        var originalLabelText = labelText ? labelText.textContent : '';
        
        if (!input || !preview) return;
        
        // Prevent defaults for drag events
        ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(function(eventName) {
            dropzone.addEventListener(eventName, function(e) {
                e.preventDefault();
                e.stopPropagation();
            });
        });
        
        // Highlight dropzone on dragenter/dragover
        ['dragenter', 'dragover'].forEach(function(eventName) {
            dropzone.addEventListener(eventName, function() {
                dropzone.classList.add('highlight');
            });
        });
        
        // Remove highlight on dragleave/drop
        ['dragleave', 'drop'].forEach(function(eventName) {
            dropzone.addEventListener(eventName, function() {
                dropzone.classList.remove('highlight');
            });
        });
        
        // Handle file drops
        dropzone.addEventListener('drop', function(e) {
            input.files = e.dataTransfer.files;
            updateFilePreview(input, preview, labelText, originalLabelText);
            
            // Trigger change event on input
            var event = new Event('change');
            input.dispatchEvent(event);
        });
        
        // Handle file selection via input
        input.addEventListener('change', function() {
            updateFilePreview(input, preview, labelText, originalLabelText);
        });
        
        // Initial preview (if files already selected)
        if (input.files.length) {
            updateFilePreview(input, preview, labelText, originalLabelText);
        }
    });
}

/**
 * Update file preview in dropzone
 */
function updateFilePreview(input, preview, labelText, originalLabelText) {
    // Clear previous preview
    preview.innerHTML = '';
    
    if (input.files && input.files.length > 0) {
        if (labelText) {
            labelText.textContent = input.files.length + ' file' + (input.files.length !== 1 ? 's' : '') + ' selected';
        }
        
        Array.from(input.files).forEach(function(file) {
            var item = document.createElement('div');
            item.className = 'file-item';
            
            // Create file icon based on type
            var icon = document.createElement('i');
            
            if (file.type.match('image.*')) {
                icon.className = 'fas fa-file-image text-info me-2';
            } else if (file.type.match('application/pdf')) {
                icon.className = 'fas fa-file-pdf text-danger me-2';
            } else if (file.type.match('application/msword') || file.type.match('application/vnd.openxmlformats-officedocument.wordprocessingml.*')) {
                icon.className = 'fas fa-file-word text-primary me-2';
            } else if (file.type.match('application/vnd.ms-excel') || file.type.match('application/vnd.openxmlformats-officedocument.spreadsheetml.*')) {
                icon.className = 'fas fa-file-excel text-success me-2';
            } else {
                icon.className = 'fas fa-file text-secondary me-2';
            }
            
            // Create file name and size display
            var nameAndSize = document.createElement('span');
            nameAndSize.textContent = file.name + ' (' + formatFileSize(file.size) + ')';
            
            // Append elements
            item.appendChild(icon);
            item.appendChild(nameAndSize);
            preview.appendChild(item);
            
            // For images, add a thumbnail
            if (file.type.match('image.*')) {
                var reader = new FileReader();
                reader.onload = function(e) {
                    var thumb = document.createElement('div');
                    thumb.className = 'file-thumbnail mt-2';
                    thumb.style.backgroundImage = 'url(' + e.target.result + ')';
                    item.appendChild(thumb);
                }
                reader.readAsDataURL(file);
            }
        });
    } else {
        if (labelText) {
            labelText.textContent = originalLabelText;
        }
    }
}

/**
 * Format file size in human-readable format
 */
function formatFileSize(bytes) {
    if (bytes === 0) return '0 Bytes';
    
    var k = 1024;
    var sizes = ['Bytes', 'KB', 'MB', 'GB', 'TB'];
    var i = Math.floor(Math.log(bytes) / Math.log(k));
    
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
}

/**
 * Initialize DataTables for tables
 */
function initializeDataTables() {
    var tables = document.querySelectorAll('.data-table');
    
    if (tables.length === 0 || typeof $.fn.DataTable === 'undefined') return;
    
    tables.forEach(function(table) {
        $(table).DataTable({
            responsive: true,
            language: {
                search: "_INPUT_",
                searchPlaceholder: "Search...",
                paginate: {
                    previous: '<i class="fas fa-chevron-left"></i>',
                    next: '<i class="fas fa-chevron-right"></i>'
                }
            }
        });
    });
}

/**
 * Toggle password visibility in password fields
 */
function togglePasswordVisibility(inputId, toggleButtonId) {
    var passwordInput = document.getElementById(inputId);
    var toggleButton = document.getElementById(toggleButtonId);
    
    if (!passwordInput || !toggleButton) return;
    
    if (passwordInput.type === 'password') {
        passwordInput.type = 'text';
        toggleButton.innerHTML = '<i class="fas fa-eye-slash"></i>';
    } else {
        passwordInput.type = 'password';
        toggleButton.innerHTML = '<i class="fas fa-eye"></i>';
    }
}

/**
 * Create a confirmation dialog
 */
function confirmAction(message, callback) {
    if (confirm(message)) {
        callback();
    }
}