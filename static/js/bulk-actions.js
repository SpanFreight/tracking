// Bulk container management functionality

document.addEventListener('DOMContentLoaded', function() {
    // Elements for bulk operations
    const selectAllCheckbox = document.getElementById('select-all-containers');
    const bulkActionControls = document.getElementById('bulk-action-controls');
    const containerCheckboxes = document.querySelectorAll('.container-checkbox');
    const bulkDeleteButton = document.getElementById('bulk-delete-button');
    const selectedCountSpan = document.getElementById('selected-count');
    
    // Initialize bulk action UI
    initBulkActions();
    
    function initBulkActions() {
        // Update UI when individual checkboxes are clicked
        containerCheckboxes.forEach(checkbox => {
            checkbox.addEventListener('change', updateBulkActionUI);
        });
        
        // Handle "Select All" functionality
        if (selectAllCheckbox) {
            selectAllCheckbox.addEventListener('change', function() {
                const isChecked = this.checked;
                containerCheckboxes.forEach(cb => {
                    cb.checked = isChecked;
                });
                updateBulkActionUI();
            });
        }
        
        // Setup delete button handler
        if (bulkDeleteButton) {
            bulkDeleteButton.addEventListener('click', deleteSelectedContainers);
        }
        
        // Initial UI update
        updateBulkActionUI();
    }
    
    function updateBulkActionUI() {
        const selectedCount = getSelectedContainerCount();
        
        // Show/hide bulk action controls based on selection
        if (bulkActionControls) {
            bulkActionControls.style.display = selectedCount > 0 ? 'block' : 'none';
        }
        
        // Update selected count
        if (selectedCountSpan) {
            selectedCountSpan.textContent = selectedCount;
        }
    }
    
    function getSelectedContainerCount() {
        return document.querySelectorAll('.container-checkbox:checked').length;
    }
    
    function getSelectedContainerIds() {
        const selected = [];
        document.querySelectorAll('.container-checkbox:checked').forEach(cb => {
            selected.push(parseInt(cb.value, 10));
        });
        return selected;
    }
    
    function deleteSelectedContainers() {
        const containerIds = getSelectedContainerIds();
        
        if (containerIds.length === 0) {
            alert('Please select at least one container to delete');
            return;
        }
        
        if (!confirm(`Are you sure you want to delete ${containerIds.length} selected containers?`)) {
            return;
        }
        
        // Show loading state
        bulkDeleteButton.disabled = true;
        bulkDeleteButton.textContent = 'Deleting...';
        
        // Send delete request to the API
        fetch('/containers/bulk-delete', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCSRFToken() // Implement this function to get your CSRF token
            },
            body: JSON.stringify({
                container_ids: containerIds
            })
        })
        .then(response => response.json())
        .then(data => {
            if (data.success_count > 0) {
                alert(`Successfully deleted ${data.success_count} containers`);
                // Refresh the page to show updated container list
                window.location.reload();
            } else {
                alert('No containers were deleted');
                // Reset button state
                bulkDeleteButton.disabled = false;
                bulkDeleteButton.textContent = 'Delete Selected';
            }
        })
        .catch(error => {
            console.error('Error:', error);
            alert('An error occurred while deleting containers');
            // Reset button state
            bulkDeleteButton.disabled = false;
            bulkDeleteButton.textContent = 'Delete Selected';
        });
    }
    
    // Helper function to get CSRF token from meta tag
    function getCSRFToken() {
        const tokenElement = document.querySelector('meta[name="csrf-token"]');
        return tokenElement ? tokenElement.getAttribute('content') : '';
    }
});
