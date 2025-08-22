// common.js - Shared JavaScript functionality for the order system

// This file provides fallback functionality for browsers that don't support the enhanced tablet.js
// The tablet.js file includes more robust implementations of these functions

document.addEventListener('DOMContentLoaded', function() {
    // Check if we're on a tablet by checking if tablet.js has run
    // If tablet.js has been loaded, it will have already set up these functions
    if (window.tabletJsLoaded) {
        return;
    }
    
    // Handle cancel button click - fallback
    const cancelBtn = document.getElementById('cancel-btn');
    if (cancelBtn) {
        cancelBtn.addEventListener('click', function() {
            const url = this.getAttribute('data-url');
            if (url) {
                if (confirm('¿Seguro que deseas cancelar? Los cambios no se guardarán.')) {
                    window.location.href = url;
                }
            }
        });
    }
    
    // Handle quantity updates in cart - fallback
    const quantityInputs = document.querySelectorAll('.quantity-input');
    if (quantityInputs.length > 0) {
        quantityInputs.forEach(input => {
            input.addEventListener('change', function() {
                const index = this.getAttribute('data-index');
                const quantity = this.value;
                
                if (quantity < 1) {
                    this.value = 1;
                    return;
                }
                
                // Make AJAX request to update quantity
                fetch(`/update_quantity/${index}/${quantity}`, {
                    method: 'POST'
                })
                .then(response => response.json())
                .then(data => {
                    if (data.success) {
                        // Reload the page to show updated cart
                        window.location.reload();
                    }
                })
                .catch(error => {
                    console.error('Error updating quantity:', error);
                });
            });
        });
    }
    
    // Handle confirmation dialogs for item removal - fallback
    const removeButtons = document.querySelectorAll('.remove-btn, .item-action.delete');
    if (removeButtons.length > 0) {
        removeButtons.forEach(button => {
            button.addEventListener('click', function(event) {
                if (!confirm('¿Seguro que quieres eliminar este artículo?')) {
                    event.preventDefault();
                }
            });
        });
    }
    
    // Basic form validation - fallback
    const form = document.getElementById('customizationForm');
    if (form) {
        form.addEventListener('submit', function(event) {
            // Check for required fields
            const requiredRadios = form.querySelectorAll('input[type="radio"][required]');
            let invalidForm = false;
            
            requiredRadios.forEach(radio => {
                const name = radio.getAttribute('name');
                const checked = form.querySelector(`input[name="${name}"]:checked`);
                
                if (!checked) {
                    invalidForm = true;
                    const fieldName = name.charAt(0).toUpperCase() + name.slice(1);
                    alert(`Por favor selecciona una opción para ${fieldName}.`);
                }
            });
            
            if (invalidForm) {
                event.preventDefault();
            }
        });
    }
});

// Set a flag indicating common.js has loaded
window.commonJsLoaded = true;