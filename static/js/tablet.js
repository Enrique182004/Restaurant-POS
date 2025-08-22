// tablet.js - Enhanced interactions for tablet/touch interface

document.addEventListener('DOMContentLoaded', function() {
    // Initialize ingredient counter
    updateIngredientCounter();
    
    // Set up ingredient checkboxes with limit enforcement
    setupIngredientLimit();
    
    // Set up option card selection visual feedback - FIXED to preserve selection
    setupOptionCardSelection();
    
    // Set up cancel button with reliable behavior
    setupCancelButton();
    
    // Set up form validation
    setupFormValidation();
    
    // Handle touch feedback on buttons
    setupButtonFeedback();
    
    // Set up cash payment calculation if we're on that page
    setupCashPaymentCalculation();
    
    // Set up cart quantity controls if we're on the cart page
    setupCartQuantityControls();
    
    // Set a flag to indicate tablet.js has been loaded
    // This prevents common.js from duplicating event handlers
    window.tabletJsLoaded = true;
    
    // Ensure text selection is enabled
    ensureTextSelection();
});

// Make sure text selection is enabled
function ensureTextSelection() {
    // Add a style element to ensure text selection is enabled
    const style = document.createElement('style');
    style.textContent = `
        * {
            user-select: auto !important;
            -webkit-user-select: auto !important;
            -moz-user-select: auto !important;
            -ms-user-select: auto !important;
        }
        
        input, label, button {
            pointer-events: auto !important;
        }
    `;
    document.head.appendChild(style);
}

// Update the ingredient counter based on selected ingredients
function updateIngredientCounter() {
    const ingredientCheckboxes = document.querySelectorAll('.ingredient-checkbox');
    const counterElement = document.getElementById('selected-count');
    
    if (!counterElement || ingredientCheckboxes.length === 0) return;
    
    // Determine max ingredients based on page context
    let MAX_INGREDIENTS = 6; // Default for rice ball
    
    // Check if we're on the sushi page
    if (document.querySelector('.preparation-options')) {
        MAX_INGREDIENTS = 3; // Sushi has max 3 ingredients
    }
    
    let selectedCount = 0;
    ingredientCheckboxes.forEach(checkbox => {
        if (checkbox.checked) {
            selectedCount++;
        }
    });
    
    counterElement.textContent = selectedCount;
    
    // Update the color based on the count
    if (selectedCount > MAX_INGREDIENTS) {
        counterElement.style.color = '#e74c3c'; // Red for over limit
    } else if (selectedCount === MAX_INGREDIENTS) {
        counterElement.style.color = '#f39c12'; // Orange for at limit
    } else {
        counterElement.style.color = '#2ecc71'; // Green for under limit
    }
}

// Set up ingredient selection with maximum limit
function setupIngredientLimit() {
    const ingredientCheckboxes = document.querySelectorAll('.ingredient-checkbox');
    if (ingredientCheckboxes.length === 0) return;
    
    // Determine max ingredients based on page context
    let MAX_INGREDIENTS = 6; // Default for rice ball
    let errorMessage = 'Solo puedes seleccionar hasta 6 ingredientes.';
    
    // Check if we're on the sushi page
    if (document.querySelector('.preparation-options')) {
        MAX_INGREDIENTS = 3; // Sushi has max 3 ingredients
        errorMessage = 'Solo puedes seleccionar hasta 3 ingredientes para el sushi.';
    }
    
    ingredientCheckboxes.forEach(checkbox => {
        checkbox.addEventListener('change', function() {
            const selectedCount = document.querySelectorAll('.ingredient-checkbox:checked').length;
            
            if (selectedCount > MAX_INGREDIENTS && this.checked) {
                // Alert the user about the limit
                alert(errorMessage);
                
                // Uncheck the most recently checked box
                this.checked = false;
                
                // Update the visual selection state
                const card = this.closest('.option-card');
                if (card) {
                    card.classList.remove('selected');
                }
            }
            
            // Update selected count display
            updateIngredientCounter();
        });
    });
}

// Set up option card selection visual feedback - FIXED to preserve selection
// Function to handle option card selection visual feedback - FIXED to preserve selection
function setupOptionCardSelection() {
    // Handle checkbox options (base, ingredients, toppings)
    const checkboxCards = document.querySelectorAll('.option-card');
    checkboxCards.forEach(card => {
        // Get the checkbox input
        const checkbox = card.querySelector('input[type="checkbox"]');
        if (!checkbox) return;
        
        // Set initial visual state
        if (checkbox.checked) {
            card.classList.add('selected');
        }
        
        // Add click handler to the card (excluding the input itself)
        card.addEventListener('click', function(event) {
            // If the click was directly on the input or label, don't interfere
            if (event.target === checkbox || 
                event.target.tagName === 'LABEL' || 
                event.target.closest('label')) {
                return;
            }
            
            // Toggle checkbox state
            checkbox.checked = !checkbox.checked;
            
            // Update visual selection
            this.classList.toggle('selected', checkbox.checked);
            
            // If this is an ingredient checkbox, handle limits
            if (checkbox.classList.contains('ingredient-checkbox')) {
                // Determine max ingredients based on page context
                let MAX_INGREDIENTS = 6; // Default for rice ball
                let errorMessage = 'Solo puedes seleccionar hasta 6 ingredientes.';
                
                // Check if we're on the sushi page
                if (document.querySelector('.preparation-options')) {
                    MAX_INGREDIENTS = 3; // Sushi has max 3 ingredients
                    errorMessage = 'Solo puedes seleccionar hasta 3 ingredientes para el sushi.';
                }
                
                const selectedCount = document.querySelectorAll('.ingredient-checkbox:checked').length;
                if (selectedCount > MAX_INGREDIENTS && checkbox.checked) {
                    checkbox.checked = false;
                    this.classList.remove('selected');
                    alert(errorMessage);
                }
                
                updateIngredientCounter();
            }
            
            // Dispatch change event to trigger any other listeners
            const changeEvent = new Event('change', { bubbles: true });
            checkbox.dispatchEvent(changeEvent);
        });
    });
    
    // Handle radio options (style, prepared, sauce)
    const radioCards = document.querySelectorAll('.option-card');
    radioCards.forEach(card => {
        // Get the radio input
        const radio = card.querySelector('input[type="radio"]');
        if (!radio) return;
        
        // Set initial visual state
        if (radio.checked) {
            card.classList.add('selected');
        }
        
        // Add click handler to the card (excluding the input itself)
        card.addEventListener('click', function(event) {
            // If the click was directly on the input or label, don't interfere
            if (event.target === radio || 
                event.target.tagName === 'LABEL' || 
                event.target.closest('label')) {
                return;
            }
            
            // Set radio as checked
            radio.checked = true;
            
            // Update visual selection for all radios in the same group
            const name = radio.getAttribute('name');
            document.querySelectorAll(`input[name="${name}"]`).forEach(r => {
                const c = r.closest('.option-card');
                if (c) {
                    c.classList.remove('selected');
                }
            });
            this.classList.add('selected');
            
            // For sushi preparation, update the hidden sauce field if needed
            if (name === 'prepared') {
                const sauceField = document.getElementById('sauce_field');
                if (sauceField) {
                    sauceField.value = radio.value;
                    console.log('Updated sauce field from card click:', radio.value);
                }
            }
            
            // Dispatch change event to trigger any other listeners
            const changeEvent = new Event('change', { bubbles: true });
            radio.dispatchEvent(changeEvent);
        });
    });
}

// Set up cancel button with reliable behavior
function setupCancelButton() {
    const cancelBtn = document.getElementById('cancel-btn');
    
    if (cancelBtn) {
        cancelBtn.addEventListener('click', function() {
            const url = this.getAttribute('data-url');
            
            if (url) {
                // Simple redirect without confirmation for better UX on touch devices
                window.location.href = url;
            } else {
                console.error('No URL provided for cancel button');
                // Fallback to home page if no URL
                window.location.href = '/';
            }
        });
    }
}

// Set up form validation
function setupFormValidation() {
    const form = document.getElementById('customizationForm');
    
    if (!form) return;
    
    form.addEventListener('submit', function(event) {
        // Determine what type of item we're customizing
        const isRiceBall = document.querySelector('.option-card input[value="Fría"]') !== null;
        const isSushi = document.querySelector('.preparation-options') !== null;
        const isBoneless = !isRiceBall && !isSushi;
        
        // Common validations for style and sauce
        if (!isBoneless) {
            // Check if style is selected for both Rice Ball and Sushi
            const styleSelected = document.querySelector('input[name="style"]:checked');
            if (!styleSelected) {
                event.preventDefault();
                if (isSushi) {
                    alert('Por favor selecciona si deseas tu sushi Frío o Empanizado.');
                } else {
                    alert('Por favor selecciona si deseas tu bola de arroz Fría o Empanizada.');
                }
                return false;
            }
        }
        
        // Sauce validation for Rice Ball and Boneless
        if (!isSushi) {
            const sauceSelected = document.querySelector('input[name="sauce"]:checked');
            if (!sauceSelected) {
                event.preventDefault();
                alert('Por favor selecciona una salsa.');
                return false;
            }
        }
        
        // Sushi-specific validations
        if (isSushi) {
            // Check prepared option
            const preparedSelected = document.querySelector('input[name="prepared"]:checked');
            if (!preparedSelected) {
                event.preventDefault();
                alert('Por favor selecciona una opción de preparado.');
                return false;
            }
            
            // Make sure sauce field gets updated from prepared
            const sauceField = document.getElementById('sauce_field');
            if (sauceField && preparedSelected) {
                sauceField.value = preparedSelected.value;
            }
            
            // Check ingredient count
            const MAX_INGREDIENTS = 3;
            const selectedIngredients = document.querySelectorAll('.ingredient-checkbox:checked').length;
            if (selectedIngredients > MAX_INGREDIENTS) {
                event.preventDefault();
                alert(`Solo puedes seleccionar hasta ${MAX_INGREDIENTS} ingredientes para el sushi.`);
                return false;
            }
        }
        
        // Rice Ball specific validations
        if (isRiceBall) {
            // Check ingredient count
            const MAX_INGREDIENTS = 6;
            const selectedIngredients = document.querySelectorAll('.ingredient-checkbox:checked').length;
            if (selectedIngredients > MAX_INGREDIENTS) {
                event.preventDefault();
                alert(`Solo puedes seleccionar hasta ${MAX_INGREDIENTS} ingredientes.`);
                return false;
            }
        }
    });
}

// Handle button feedback for touch interactions
function setupButtonFeedback() {
    const buttons = document.querySelectorAll('.action-button, .quantity-btn, .quick-amount-btn, .calc-btn');
    
    buttons.forEach(button => {
        // Add visual feedback on touch
        button.addEventListener('touchstart', function() {
            this.style.opacity = '0.8';
        });
        
        button.addEventListener('touchend', function() {
            this.style.opacity = '1';
        });
    });
}

// Set up cash payment calculation if we're on that page
function setupCashPaymentCalculation() {
    const calculateChangeBtn = document.getElementById('calculate-change-btn');
    if (!calculateChangeBtn) return;
    
    // Attach event listener to calculate button
    calculateChangeBtn.addEventListener('click', calculateChange);
    
    // Set up quick amount buttons
    const quickAmountBtns = document.querySelectorAll('.quick-amount-btn');
    quickAmountBtns.forEach(btn => {
        btn.addEventListener('click', function() {
            const amount = this.getAttribute('data-amount');
            const amountInput = document.getElementById('amount-given');
            if (amountInput) {
                amountInput.value = amount;
                // Calculate change automatically
                calculateChange();
            }
        });
    });
    
    // Set up calculator buttons
    const calculatorBtns = document.querySelectorAll('.calc-btn:not(.clear-btn)');
    calculatorBtns.forEach(btn => {
        btn.addEventListener('click', function() {
            const value = this.getAttribute('data-value');
            const amountInput = document.getElementById('amount-given');
            
            if (!amountInput) return;
            
            // Focus on input if not already focused
            if (document.activeElement !== amountInput) {
                amountInput.focus();
            }
            
            // Get current value and cursor position
            const currentValue = amountInput.value;
            const selectionStart = amountInput.selectionStart || currentValue.length;
            const selectionEnd = amountInput.selectionEnd || currentValue.length;
            
            // Insert the number at cursor position
            if (selectionStart === selectionEnd) {
                amountInput.value = currentValue.substring(0, selectionStart) + 
                                    value + 
                                    currentValue.substring(selectionEnd);
                
                // Move cursor after inserted text
                amountInput.selectionStart = selectionStart + value.length;
                amountInput.selectionEnd = selectionStart + value.length;
            } else {
                // Replace selected text
                amountInput.value = currentValue.substring(0, selectionStart) + 
                                    value + 
                                    currentValue.substring(selectionEnd);
                
                // Move cursor after inserted text
                amountInput.selectionStart = selectionStart + value.length;
                amountInput.selectionEnd = selectionStart + value.length;
            }
        });
    });
    
    // Set up clear button
    const clearBtn = document.querySelector('.clear-btn');
    if (clearBtn) {
        clearBtn.addEventListener('click', function() {
            const amountInput = document.getElementById('amount-given');
            const changeDueElement = document.getElementById('change-due');
            const printTicketBtn = document.getElementById('print-ticket');
            
            if (amountInput) {
                amountInput.value = '';
                amountInput.focus();
            }
            
            if (changeDueElement) {
                changeDueElement.textContent = '$0.00';
            }
            
            if (printTicketBtn) {
                printTicketBtn.style.display = 'none';
            }
        });
    }
    
    // Set up auto-calculate on input change
    const amountInput = document.getElementById('amount-given');
    if (amountInput) {
        amountInput.addEventListener('input', function() {
            const totalAmount = parseFloat(document.getElementById('total-amount').textContent.replace('$', ''));
            const amountGiven = parseFloat(this.value);
            const changeDueElement = document.getElementById('change-due');
            const printTicketBtn = document.getElementById('print-ticket');
            
            if (!isNaN(amountGiven) && amountGiven >= totalAmount) {
                calculateChange();
            } else {
                if (changeDueElement) {
                    changeDueElement.textContent = '$0.00';
                }
                if (printTicketBtn) {
                    printTicketBtn.style.display = 'none';
                }
            }
        });
    }
}

// Function to calculate change in cash payment
function calculateChange() {
    const totalAmountElement = document.getElementById('total-amount');
    const amountInput = document.getElementById('amount-given');
    const changeDueElement = document.getElementById('change-due');
    const printTicketBtn = document.getElementById('print-ticket');
    
    if (!totalAmountElement || !amountInput || !changeDueElement) return;
    
    const totalAmount = parseFloat(totalAmountElement.textContent.replace('$', ''));
    const amountGiven = parseFloat(amountInput.value);
    
    if (isNaN(amountGiven)) {
        changeDueElement.textContent = '$0.00';
        changeDueElement.style.color = '#e74c3c';
        alert('Por favor ingresa un monto válido');
        return;
    }
    
    if (amountGiven < totalAmount) {
        changeDueElement.textContent = '$0.00';
        changeDueElement.style.color = '#e74c3c';
        alert('El monto ingresado es insuficiente');
        return;
    }
    
    const change = amountGiven - totalAmount;
    changeDueElement.textContent = `$${change.toFixed(2)}`;
    changeDueElement.style.color = '#2b8a3e';
    
    // Show print ticket button
    if (printTicketBtn) {
        printTicketBtn.style.display = 'block';
        // Update href to include payment info
        const currentHref = printTicketBtn.getAttribute('href');
        const baseHref = currentHref.split('?')[0]; // Get the base URL without query parameters
        const newHref = `${baseHref}?payment_method=cash&amount_paid=${amountGiven}`;
        printTicketBtn.setAttribute('href', newHref);
    }
    
    // Vibrate device if supported (tactile feedback)
    if (navigator.vibrate) {
        navigator.vibrate(50);
    }
}

// Set up cart quantity controls
function setupCartQuantityControls() {
    const plusBtns = document.querySelectorAll('.quantity-btn.plus');
    const minusBtns = document.querySelectorAll('.quantity-btn.minus');
    
    if (plusBtns.length === 0 && minusBtns.length === 0) return; // Not on cart page
    
    plusBtns.forEach(btn => {
        btn.addEventListener('click', function() {
            const index = this.getAttribute('data-index');
            const input = document.querySelector(`.quantity-input[data-index="${index}"]`);
            if (!input) return;
            
            let value = parseInt(input.value);
            if (isNaN(value)) value = 1;
            
            // Increment value
            input.value = value + 1;
            
            // Update quantity on server
            updateQuantity(index, input.value);
        });
    });
    
    minusBtns.forEach(btn => {
        btn.addEventListener('click', function() {
            const index = this.getAttribute('data-index');
            const input = document.querySelector(`.quantity-input[data-index="${index}"]`);
            if (!input) return;
            
            let value = parseInt(input.value);
            if (isNaN(value)) value = 1;
            
            // Only decrement if > 1
            if (value > 1) {
                input.value = value - 1;
                
                // Update quantity on server
                updateQuantity(index, input.value);
            }
        });
    });
    
    // Handle manual input
    const quantityInputs = document.querySelectorAll('.quantity-input');
    quantityInputs.forEach(input => {
        input.addEventListener('change', function() {
            const index = this.getAttribute('data-index');
            let value = parseInt(this.value);
            
            // Ensure minimum of 1
            if (value < 1 || isNaN(value)) {
                value = 1;
                this.value = 1;
            }
            
            // Update quantity on server
            updateQuantity(index, value);
        });
    });
    
    // Add confirmation for delete buttons
    const deleteButtons = document.querySelectorAll('.item-action.delete');
    deleteButtons.forEach(button => {
        button.addEventListener('click', function(event) {
            if (!confirm('¿Seguro que quieres eliminar este artículo?')) {
                event.preventDefault();
            }
        });
    });
}

// Function to update quantity on server
function updateQuantity(index, quantity) {
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
}