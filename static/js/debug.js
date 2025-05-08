// Debug script to identify event handler conflicts

document.addEventListener('DOMContentLoaded', function() {
    console.log('Debug script loaded');
    
    // Monitor all link clicks
    document.addEventListener('click', function(e) {
        // Find the closest A tag
        let target = e.target;
        while (target && target.tagName !== 'A') {
            target = target.parentElement;
        }
        
        if (target) {
            console.log('Link clicked:', target);
            console.log('  href:', target.getAttribute('href'));
            console.log('  id:', target.id);
            console.log('  classes:', target.className);
        }
    }, true); // Use capturing phase
    
    // Add direct event handlers to admin links
    const adminProfileLink = document.querySelector('a[href$="/profile"]');
    if (adminProfileLink) {
        adminProfileLink.onclick = function(e) {
            console.log('Admin profile link clicked, navigating directly');
            window.location.href = this.getAttribute('href');
            e.stopPropagation();
            return false;
        };
    }
    
    // Fix dropdown items with navDirectLink class
    document.querySelectorAll('.dropdown-item.navDirectLink').forEach(link => {
        link.onclick = function(e) {
            console.log('Direct navigation link clicked');
            window.location.href = this.getAttribute('href');
            e.stopPropagation();
            return false;
        };
    });
    
    // Identify all global event listeners on the document
    console.log('Current document event listeners:');
    const events = ['click', 'mousedown', 'mouseup', 'change'];
    events.forEach(event => {
        console.log(`Event type: ${event}`);
        // Note: Unfortunately, it's not possible to list all event listeners in JavaScript
        // This is a placeholder for identifying conflicts
    });
});
