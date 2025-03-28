// Main JavaScript functionality for the College ERP System

document.addEventListener('DOMContentLoaded', function() {
    // Initialize tooltips
    var tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
    var tooltipList = tooltipTriggerList.map(function (tooltipTriggerEl) {
        return new bootstrap.Tooltip(tooltipTriggerEl);
    });
    
    // Initialize popovers
    var popoverTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="popover"]'));
    var popoverList = popoverTriggerList.map(function (popoverTriggerEl) {
        return new bootstrap.Popover(popoverTriggerEl);
    });
    
    // Auto-dismiss alerts after 5 seconds
    setTimeout(function() {
        var alerts = document.querySelectorAll('.alert:not(.alert-permanent)');
        alerts.forEach(function(alert) {
            var bsAlert = new bootstrap.Alert(alert);
            bsAlert.close();
        });
    }, 5000);
    
    // Add confirmation dialog to delete buttons
    document.querySelectorAll('.btn-delete-confirm').forEach(function(button) {
        button.addEventListener('click', function(e) {
            if (!confirm('Are you sure you want to delete this item? This action cannot be undone.')) {
                e.preventDefault();
            }
        });
    });
    
    // Setup file input customization
    document.querySelectorAll('.custom-file-input').forEach(function(input) {
        input.addEventListener('change', function(e) {
            var fileName = e.target.files[0].name;
            var label = e.target.nextElementSibling;
            label.innerText = fileName;
        });
    });
    
    // Handle form submission with AJAX for analytics requests
    var analyticsForms = document.querySelectorAll('.analytics-form');
    analyticsForms.forEach(function(form) {
        form.addEventListener('submit', function(e) {
            e.preventDefault();
            
            // Show loading spinner
            var resultContainer = document.querySelector(form.dataset.result);
            if (resultContainer) {
                resultContainer.innerHTML = '<div class="spinner-container"><div class="spinner-border text-primary" role="status"><span class="visually-hidden">Loading...</span></div></div>';
            }
            
            // Get form data
            var formData = new FormData(form);
            var url = form.action;
            
            // Send AJAX request
            fetch(url, {
                method: 'POST',
                body: formData,
                headers: {
                    'X-Requested-With': 'XMLHttpRequest'
                }
            })
            .then(response => response.json())
            .then(data => {
                if (resultContainer) {
                    if (data.html) {
                        resultContainer.innerHTML = data.html;
                    } else if (data.error) {
                        resultContainer.innerHTML = `<div class="alert alert-danger">${data.error}</div>`;
                    }
                    
                    // Initialize any charts if needed
                    if (typeof initCharts === 'function' && data.chart_data) {
                        initCharts(data.chart_data);
                    }
                }
            })
            .catch(error => {
                console.error('Error:', error);
                if (resultContainer) {
                    resultContainer.innerHTML = `<div class="alert alert-danger">An error occurred while processing your request. Please try again.</div>`;
                }
            });
        });
    });
    
    // Dynamic form fields for assignments
    var addCriterionBtn = document.getElementById('add-criterion-btn');
    if (addCriterionBtn) {
        addCriterionBtn.addEventListener('click', function() {
            var criteriaContainer = document.getElementById('rubric-criteria');
            var newIndex = criteriaContainer.children.length;
            
            var newCriterion = document.createElement('div');
            newCriterion.className = 'row mb-3 criterion-row';
            newCriterion.innerHTML = `
                <div class="col-md-5">
                    <input type="text" name="criteria[${newIndex}][name]" class="form-control" placeholder="Criterion name" required>
                </div>
                <div class="col-md-5">
                    <input type="number" name="criteria[${newIndex}][weight]" class="form-control" placeholder="Weight" min="1" max="100" required>
                </div>
                <div class="col-md-2">
                    <button type="button" class="btn btn-danger remove-criterion-btn">
                        <i class="fas fa-trash"></i>
                    </button>
                </div>
            `;
            
            criteriaContainer.appendChild(newCriterion);
            
            // Add event listener to the new remove button
            newCriterion.querySelector('.remove-criterion-btn').addEventListener('click', function() {
                criteriaContainer.removeChild(newCriterion);
            });
        });
    }
    
    // Remove criterion button event delegation
    document.addEventListener('click', function(e) {
        if (e.target && e.target.closest('.remove-criterion-btn')) {
            var btn = e.target.closest('.remove-criterion-btn');
            var row = btn.closest('.criterion-row');
            row.parentNode.removeChild(row);
        }
    });
    
    // Initialize date pickers if any
    var datePickers = document.querySelectorAll('.datepicker');
    if (datePickers.length > 0 && typeof flatpickr !== 'undefined') {
        datePickers.forEach(function(picker) {
            flatpickr(picker, {
                enableTime: picker.dataset.enableTime === 'true',
                dateFormat: picker.dataset.enableTime === 'true' ? "Y-m-d H:i" : "Y-m-d"
            });
        });
    }
});

// Analytics chart initialization
function initCharts(chartData) {
    if (!chartData) return;
    
    // Process each chart
    Object.keys(chartData).forEach(function(chartId) {
        var data = chartData[chartId];
        var ctx = document.getElementById(chartId);
        
        if (ctx) {
            // Clear any existing chart
            if (ctx.chart) {
                ctx.chart.destroy();
            }
            
            // Create new chart
            ctx.chart = new Chart(ctx, {
                type: data.type || 'bar',
                data: data.data,
                options: data.options || {
                    responsive: true,
                    maintainAspectRatio: false
                }
            });
        }
    });
}

// AI analysis submission handler
function submitForAnalysis(formId, resultContainerId) {
    var form = document.getElementById(formId);
    var resultContainer = document.getElementById(resultContainerId);
    
    if (form && resultContainer) {
        // Show loading indicator
        resultContainer.innerHTML = `
            <div class="alert alert-info">
                <div class="d-flex align-items-center">
                    <div class="spinner-border spinner-border-sm me-2" role="status">
                        <span class="visually-hidden">Loading...</span>
                    </div>
                    <div>Analyzing submission with AI... This may take a moment.</div>
                </div>
            </div>
        `;
        
        // Get form data
        var formData = new FormData(form);
        
        // Send AJAX request
        fetch(form.action, {
            method: 'POST',
            body: formData,
            headers: {
                'X-Requested-With': 'XMLHttpRequest'
            }
        })
        .then(response => response.json())
        .then(data => {
            if (data.html) {
                resultContainer.innerHTML = data.html;
            } else if (data.error) {
                resultContainer.innerHTML = `<div class="alert alert-danger">${data.error}</div>`;
            } else {
                // Format analysis results
                var html = `
                    <div class="card border-primary mb-4">
                        <div class="card-header bg-primary text-white">
                            <i class="fas fa-robot me-2"></i>AI Analysis Results
                        </div>
                        <div class="card-body">
                            <h5 class="card-title">Overall Score: ${data.score}/100</h5>
                            <div class="progress mb-4">
                                <div class="progress-bar bg-${getScoreClass(data.score)}" role="progressbar" 
                                     style="width: ${data.score}%" aria-valuenow="${data.score}" 
                                     aria-valuemin="0" aria-valuemax="100"></div>
                            </div>
                            <h6>Feedback:</h6>
                            <p>${data.feedback}</p>
                            ${data.strengths ? `
                            <h6 class="text-success">Strengths:</h6>
                            <ul>
                                ${data.strengths.map(s => `<li>${s}</li>`).join('')}
                            </ul>` : ''}
                            ${data.areas_for_improvement ? `
                            <h6 class="text-warning">Areas for Improvement:</h6>
                            <ul>
                                ${data.areas_for_improvement.map(a => `<li>${a}</li>`).join('')}
                            </ul>` : ''}
                        </div>
                        <div class="card-footer bg-light">
                            <small class="text-muted">This analysis was generated by AI and should be reviewed by the instructor.</small>
                        </div>
                    </div>
                `;
                resultContainer.innerHTML = html;
            }
        })
        .catch(error => {
            console.error('Error:', error);
            resultContainer.innerHTML = `<div class="alert alert-danger">An error occurred during analysis. Please try again.</div>`;
        });
    }
}

// Helper function to get appropriate color class based on score
function getScoreClass(score) {
    if (score >= 80) return 'success';
    if (score >= 60) return 'info';
    if (score >= 40) return 'warning';
    return 'danger';
}