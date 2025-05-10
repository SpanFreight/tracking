// Bulk container operations for multiple selection and deletion

document.addEventListener('DOMContentLoaded', function() {
    initBulkOperations();
});

function initBulkOperations() {
    const selectAllCheckbox = document.getElementById('select-all-containers');
    const containerCheckboxes = document.querySelectorAll('.container-checkbox');
    const bulkActionControls = document.getElementById('bulk-action-controls');
    const selectedCountSpan = document.getElementById('selected-count');
    const bulkDeleteBtn = document.getElementById('bulk-delete-btn');
    
    // Setup event listeners
    if (selectAllCheckbox) {
        selectAllCheckbox.addEventListener('change', function() {
            containerCheckboxes.forEach(checkbox => {
                checkbox.checked = this.checked;
            });
            updateBulkControls();
        });
    }
    
    containerCheckboxes.forEach(checkbox => {
        checkbox.addEventListener('change', updateBulkControls);
    });
    
    if (bulkDeleteBtn) {
        bulkDeleteBtn.addEventListener('click', confirmAndDeleteSelected);
    }
    
    // Initial update
    updateBulkControls();
}

function updateBulkControls() {
    const selectedCount = document.querySelectorAll('.container-checkbox:checked').length;
    const bulkActionControls = document.getElementById('bulk-action-controls');
    const selectedCountSpan = document.getElementById('selected-count');
    
    if (bulkActionControls) {
        bulkActionControls.style.display = selectedCount > 0 ? 'flex' : 'none';
    }
    
    if (selectedCountSpan) {
        selectedCountSpan.textContent = selectedCount;
    }
}

function confirmAndDeleteSelected() {
    const selectedContainers = document.querySelectorAll('.container-checkbox:checked');
    const containerIds = Array.from(selectedContainers).map(checkbox => parseInt(checkbox.value));
    
    if (containerIds.length === 0) {
        alert('Please select at least one container to delete.');
        return;
    }
    
    if (confirm(`Are you sure you want to delete ${containerIds.length} containers? This action cannot be undone.`)) {
        deleteContainers(containerIds);
    }
}

function deleteContainers(containerIds) {
    // Show loading state
    const bulkDeleteBtn = document.getElementById('bulk-delete-btn');
    const originalText = bulkDeleteBtn.innerHTML;
    bulkDeleteBtn.disabled = true;
    bulkDeleteBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Deleting...';
    
    fetch('/containers/bulk-delete', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({ container_ids: containerIds })
    })
    .then(response => response.json())
    .then(result => {
        if (result.success_count > 0) {
            alert(`Successfully deleted ${result.success_count} containers.`);
            // Reload the page to show the updated container list
            window.location.reload();
        } else {
            alert('No containers were deleted.');
            bulkDeleteBtn.disabled = false;
            bulkDeleteBtn.innerHTML = originalText;
        }
    })
    .catch(error => {
        console.error('Error deleting containers:', error);
        alert('An error occurred while deleting containers.');
        bulkDeleteBtn.disabled = false;
        bulkDeleteBtn.innerHTML = originalText;
    });
}
