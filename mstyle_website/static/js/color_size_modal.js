// Color and Size Modal Functionality
let currentProduct = {
    id: null,
    name: '',
    price: '',
    image: '',
    selectedColor: null,
    selectedSize: null,
    quantity: 1
};

// Store variant stock data
let variantStockData = {};

// Fetch variant stock from backend
function fetchVariantStock(productId, productVariations, productSizes) {
    console.log(`Fetching variant stock for product ID: ${productId}`);
    return fetch(`/api/product/${productId}/variant-stock`)
        .then(response => response.json())
        .then(data => {
            console.log('Variant stock API response:', data);
            if (data.success) {
                variantStockData = {};
                // Store stock data in a map for quick lookup
                data.variants.forEach(variant => {
                    const key = `${variant.color}|${variant.size}`;
                    variantStockData[key] = variant.stock_quantity || 0;
                    console.log(`  - ${variant.color} / ${variant.size}: ${variant.stock_quantity} units`);
                });
                console.log('✓ Variant stock data loaded successfully:', variantStockData);
                
                // Continue with modal setup
                continueModalSetup(productVariations, productSizes);
            } else {
                console.warn('⚠ Failed to load variant stock, continuing without stock data');
                continueModalSetup(productVariations, productSizes);
            }
        })
        .catch(error => {
            console.error('❌ Error fetching variant stock:', error);
            continueModalSetup(productVariations, productSizes);
        });
}

// Open the color and size selection modal
function openColorSizeModal(productId, productName, productPrice, productImage, productVariations, productSizes) {
    // Check if user is logged in
    if (typeof isUserLoggedIn !== 'undefined' && !isUserLoggedIn) {
        showLoginFirstModal();
        return;
    }
    
    console.log('Opening modal for product:', productId, productName, productPrice, productImage, productVariations, productSizes);
    console.log('Product variations received:', productVariations);
    console.log('Product sizes received:', productSizes);
    
    // Handle None or undefined values
    if (productVariations === 'None' || productVariations === 'undefined' || productVariations === null) {
        productVariations = '';
    }
    if (productSizes === 'None' || productSizes === 'undefined' || productSizes === null) {
        productSizes = '';
    }
    
    currentProduct.id = productId;
    currentProduct.name = productName;
    currentProduct.price = productPrice;
    currentProduct.image = productImage;

    // Reset selections
    currentProduct.selectedColor = null;
    currentProduct.selectedSize = null;
    currentProduct.quantity = 1;
    
    // Fetch variant stock data
    fetchVariantStock(productId, productVariations, productSizes);
}

// Continue modal setup after fetching stock data
function continueModalSetup(productVariations, productSizes) {
    // Update modal content
    document.getElementById('modalProductName').textContent = currentProduct.name;
    document.getElementById('modalProductPrice').textContent = '₱ ' + parseFloat(currentProduct.price).toFixed(2);

    // Handle product image - get first image if multiple images are provided
    const productImages = currentProduct.image ? currentProduct.image.split(',') : [];
    const firstImage = productImages.length > 0 ? productImages[0].trim() : '';
    if (firstImage) {
        document.getElementById('modalProductImage').src = `/static/images/uploads/${firstImage}`;
    }

    document.getElementById('quantity').value = 1;

    // Reset selection displays
    document.getElementById('selectedColor').textContent = 'Please select a color';
    document.getElementById('selectedSize').textContent = 'Please select a size';

    // Store variations and sizes in data attributes for later refresh
    const colorOptionsContainer = document.getElementById('colorOptions');
    if (colorOptionsContainer) {
        colorOptionsContainer.setAttribute('data-variations', productVariations);
    }
    
    const sizeOptionsContainer = document.querySelector('.size-options');
    if (sizeOptionsContainer) {
        sizeOptionsContainer.setAttribute('data-sizes', productSizes);
    }

    // Generate dynamic color options based on product variations
    generateColorOptions(productVariations);

    // Generate dynamic size options based on product sizes
    generateSizeOptions(productSizes);

    // Clear previous selections for sizes and colors
    document.querySelectorAll('.size-option').forEach(option => {
        option.classList.remove('selected');
    });
    document.querySelectorAll('.color-option').forEach(option => {
        option.classList.remove('selected');
    });

    // Show Add to Cart button and hide Buy Now button
    document.getElementById('addToCartBtn').style.display = 'inline-block';
    document.getElementById('buyNowBtn').style.display = 'none';

    // Show modal
    document.getElementById('colorSizeModal').style.display = 'block';
    document.body.style.overflow = 'hidden'; // Prevent background scrolling
}

// Close the modal
function closeColorSizeModal() {
    document.getElementById('colorSizeModal').style.display = 'none';
    document.body.style.overflow = 'auto'; // Restore scrolling
}

// Generate color options dynamically based on product variations
function generateColorOptions(variations) {
    console.log('generateColorOptions called with:', variations);
    console.log('Current product image:', currentProduct.image);
    const colorOptionsContainer = document.getElementById('colorOptions');
    colorOptionsContainer.innerHTML = ''; // Clear existing options

    if (!variations || variations === '' || variations === 'None' || variations === 'undefined') {
        console.log('No variations provided, showing message');
        colorOptionsContainer.innerHTML = '<p class="no-colors">No color variations available for this product</p>';
        // Auto-select a default color
        currentProduct.selectedColor = 'Default';
        document.getElementById('selectedColor').textContent = 'Default';
        document.getElementById('selectedColor').style.color = '#d4af37';
        document.getElementById('selectedColor').style.fontWeight = 'bold';
        updateAddToCartButton();
        return;
    }

    // Split variations by comma and clean up
    const colors = variations.split(',').map(color => color.trim()).filter(color => color && color !== 'None');
    console.log('Colors parsed:', colors);
    console.log('Product images available:', currentProduct.image ? currentProduct.image.split(',') : []);
    
    if (colors.length === 0) {
        console.log('No valid colors after parsing, showing message');
        colorOptionsContainer.innerHTML = '<p class="no-colors">No color variations available for this product</p>';
        // Auto-select a default color
        currentProduct.selectedColor = 'Default';
        document.getElementById('selectedColor').textContent = 'Default';
        document.getElementById('selectedColor').style.color = '#d4af37';
        document.getElementById('selectedColor').style.fontWeight = 'bold';
        updateAddToCartButton();
        return;
    }

    // Get all sizes for stock checking
    const sizeOptionsContainer = document.querySelector('.size-options');
    const productSizes = sizeOptionsContainer ? sizeOptionsContainer.getAttribute('data-sizes') : null;
    const allSizes = productSizes ? productSizes.split(',').map(s => s.trim()).filter(s => s && s !== 'None') : [];

    colors.forEach((color, index) => {
        const colorDiv = document.createElement('div');
        colorDiv.className = 'color-option-container';

        // Check if all sizes are out of stock for THIS SPECIFIC color
        let allSizesOutOfStock = false;
        if (allSizes.length > 0) {
            console.log(`Checking stock for color: ${color}`);
            allSizesOutOfStock = allSizes.every(size => {
                const stockKey = `${color}|${size}`;
                const stock = variantStockData[stockKey] || 0;
                console.log(`  - ${color}/${size}: ${stock} units (${stock <= 0 ? 'OUT OF STOCK' : 'Available'})`);
                return stock <= 0;
            });
        }

        console.log(`➜ Color: ${color}, All sizes out of stock: ${allSizesOutOfStock}`);

        const colorOption = document.createElement('div');
        colorOption.className = 'color-option';
        colorOption.setAttribute('data-color', color);
        
        if (allSizesOutOfStock) {
            colorOption.classList.add('out-of-stock');
            colorOption.title = `${color} - All sizes out of stock`;
            console.log(`✗ Color ${color} - ALL SIZES OUT OF STOCK`);
        } else {
            colorOption.title = color;
        }

        // Try to show image first, fallback to colored rectangle
        const colorImage = document.createElement('img');
        colorImage.className = 'color-image';
        colorImage.src = getColorImagePath(color);
        colorImage.alt = color;

        // Create fallback colored rectangle (hidden initially)
        const colorDisplay = document.createElement('div');
        colorDisplay.className = 'color-fallback';
        colorDisplay.style.backgroundColor = getColorCode(color);
        colorDisplay.style.display = 'none'; // Hidden until image fails

        // Add color name to fallback display
        const colorText = document.createElement('span');
        colorText.className = 'color-fallback-text';
        colorText.textContent = color;

        // Use appropriate text color for contrast
        if (isLightColor(color)) {
            colorText.style.color = '#2c3e50';
            colorText.style.textShadow = '1px 1px 2px rgba(255, 255, 255, 0.8)';
            colorText.style.background = 'rgba(255, 255, 255, 0.4)';
        } else {
            colorText.style.color = 'white';
            colorText.style.textShadow = '1px 1px 2px rgba(0, 0, 0, 0.8)';
            colorText.style.background = 'rgba(0, 0, 0, 0.3)';
        }

        colorDisplay.appendChild(colorText);

        // Handle image load failure
        colorImage.onerror = function () {
            console.log(`Failed to load color image for ${color}:`, this.src);
            // Hide the failed image and show colored rectangle
            this.style.display = 'none';
            colorDisplay.style.display = 'flex';
        };

        // Handle successful image load
        colorImage.onload = function () {
            console.log(`Successfully loaded color image for ${color}:`, this.src);
            // Image loaded successfully, keep it visible
            colorDisplay.style.display = 'none';
        };

        // Create color name overlay for images
        const colorNameOverlay = document.createElement('div');
        colorNameOverlay.className = 'color-name-overlay';
        colorNameOverlay.textContent = color;

        // Add both image and fallback to option
        colorOption.appendChild(colorImage);
        colorOption.appendChild(colorDisplay);
        colorOption.appendChild(colorNameOverlay);

        // Add click event listener with enhanced visual feedback
        colorOption.addEventListener('click', function () {
            // Prevent selection if all sizes are out of stock
            if (allSizesOutOfStock) {
                alert(`Sorry, ${color} is currently out of stock in all sizes.`);
                return;
            }
            
            // Prevent multiple rapid clicks
            if (this.classList.contains('loading')) return;

            // Add loading state with visual feedback
            this.classList.add('loading');
            const loadingSpinner = document.createElement('div');
            loadingSpinner.className = 'color-loading-spinner';
            loadingSpinner.innerHTML = '<i class="fas fa-spinner fa-spin"></i>';
            this.appendChild(loadingSpinner);

            // Add ripple effect
            createRippleEffect(this, event);

            // Remove previous selection with fade out animation
            document.querySelectorAll('.color-option').forEach(opt => {
                if (opt !== this) {
                    opt.classList.remove('selected');
                    opt.style.transform = 'scale(1)';
                    opt.style.boxShadow = '';
                }
            });

            // Add selection to clicked option with enhanced animation
            setTimeout(() => {
                this.classList.add('selected');
                this.style.transform = 'scale(1.05)';
                this.style.boxShadow = '0 8px 25px rgba(212, 175, 55, 0.4)';

                currentProduct.selectedColor = this.getAttribute('data-color');

                // Update selection text with animation
                const selectedColorElement = document.getElementById('selectedColor');
                selectedColorElement.style.opacity = '0';
                setTimeout(() => {
                    selectedColorElement.textContent = `Selected: ${currentProduct.selectedColor}`;
                    selectedColorElement.style.opacity = '1';
                    selectedColorElement.style.color = '#d4af37';
                    selectedColorElement.style.fontWeight = 'bold';
                }, 150);

                // Log the selected color and matching image for debugging
                const matchingImage = findColorMatchingImage(currentProduct.selectedColor, currentProduct.image);
                console.log(`Color selected: ${currentProduct.selectedColor}, Matching image: ${matchingImage}`);

                // Update the modal product image with enhanced loading feedback
                updateModalImageWithFeedback(matchingImage);

                // Remove loading state
                this.classList.remove('loading');
                if (loadingSpinner.parentNode) {
                    loadingSpinner.remove();
                }

                // Refresh size options to show stock status for selected color
                const sizeOptionsContainer = document.querySelector('.size-options');
                const productSizes = sizeOptionsContainer ? sizeOptionsContainer.getAttribute('data-sizes') : null;
                if (productSizes) {
                    console.log('Refreshing sizes for color:', currentProduct.selectedColor);
                    generateSizeOptions(productSizes);
                }

                updateAddToCartButton();
            }, 200);
        });

        colorDiv.appendChild(colorOption);
        colorOptionsContainer.appendChild(colorDiv);
    });
}

// Generate size options dynamically based on product sizes
function generateSizeOptions(sizes) {
    console.log('generateSizeOptions called with:', sizes);
    const sizeOptionsContainer = document.querySelector('.size-options');
    if (!sizeOptionsContainer) {
        console.error('Size options container not found');
        return;
    }
    sizeOptionsContainer.innerHTML = ''; // Clear existing options

    if (!sizes || !sizes.trim() || sizes === 'None' || sizes === 'undefined') {
        console.log('No sizes provided, auto-selecting default');
        sizeOptionsContainer.innerHTML = '<p class="no-sizes">No sizes available for this product</p>';
        // Auto-select a default size
        currentProduct.selectedSize = 'One Size';
        document.getElementById('selectedSize').textContent = 'One Size';
        document.getElementById('selectedSize').style.color = '#d4af37';
        document.getElementById('selectedSize').style.fontWeight = 'bold';
        updateAddToCartButton();
        return;
    }

    // Split sizes by comma and clean up
    const sizeArray = sizes.split(',').map(size => size.trim()).filter(size => size && size !== 'None');
    console.log('Sizes parsed:', sizeArray);

    if (sizeArray.length === 0) {
        console.log('No valid sizes after parsing, auto-selecting default');
        sizeOptionsContainer.innerHTML = '<p class="no-sizes">No sizes available for this product</p>';
        // Auto-select a default size
        currentProduct.selectedSize = 'One Size';
        document.getElementById('selectedSize').textContent = 'One Size';
        document.getElementById('selectedSize').style.color = '#d4af37';
        document.getElementById('selectedSize').style.fontWeight = 'bold';
        updateAddToCartButton();
        return;
    }

    sizeArray.forEach((size, index) => {
        const sizeDiv = document.createElement('div');
        sizeDiv.className = 'size-option';
        sizeDiv.setAttribute('data-size', size);
        
        // Check stock for this size with current selected color
        const stockKey = `${currentProduct.selectedColor || ''}|${size}`;
        const stock = variantStockData[stockKey] || 0;
        const isOutOfStock = currentProduct.selectedColor && stock <= 0;
        
        console.log(`Size: ${size}, Color: ${currentProduct.selectedColor}, Stock Key: ${stockKey}, Stock: ${stock}, Out of Stock: ${isOutOfStock}`);
        
        sizeDiv.textContent = size;
        
        // Add out of stock styling
        if (isOutOfStock) {
            sizeDiv.classList.add('out-of-stock');
            sizeDiv.title = `Size ${size} - Out of Stock for ${currentProduct.selectedColor}`;
            console.log(`✗ Size ${size} is OUT OF STOCK for color ${currentProduct.selectedColor}`);
        } else {
            sizeDiv.title = `Size ${size}`;
            if (currentProduct.selectedColor) {
                console.log(`✓ Size ${size} is AVAILABLE for color ${currentProduct.selectedColor} (${stock} in stock)`);
            }
        }

        // Add click event listener
        sizeDiv.addEventListener('click', function () {
            // Prevent selection if out of stock
            if (isOutOfStock) {
                alert(`Sorry, size ${size} is currently out of stock for ${currentProduct.selectedColor}.`);
                return;
            }
            
            // Remove previous selection
            document.querySelectorAll('.size-option').forEach(opt => {
                opt.classList.remove('selected');
            });

            // Add selection to clicked option
            this.classList.add('selected');
            currentProduct.selectedSize = this.getAttribute('data-size');

            // Update selection text
            const selectedSizeElement = document.getElementById('selectedSize');
            selectedSizeElement.textContent = `Selected: ${currentProduct.selectedSize}`;
            selectedSizeElement.style.color = '#d4af37';
            selectedSizeElement.style.fontWeight = 'bold';

            console.log(`Size selected: ${currentProduct.selectedSize}`);
            
            updateAddToCartButton();
        });

        sizeOptionsContainer.appendChild(sizeDiv);
    });
}

// Helper function to get color image path
function getColorImagePath(colorName) {
    // Try to get color-specific product image first
    const productImages = currentProduct.image ? currentProduct.image.split(',') : [];
    const colorLower = colorName.toLowerCase().trim();
    const colorVariations = [
        colorLower,
        colorLower.replace(' ', '_'),
        colorLower.replace(' ', '-'),
        colorLower.replace(/\s+/g, '')
    ];

    // Look for image that contains any variation of the color name
    for (let img of productImages) {
        const imgName = img.trim().toLowerCase();
        for (let variation of colorVariations) {
            if (imgName.includes(variation)) {
                return `/static/images/uploads/${img.trim()}`;
            }
        }
    }

    // If no color-specific image found, try the first product image as fallback
    if (productImages.length > 0 && productImages[0].trim()) {
        return `/static/images/uploads/${productImages[0].trim()}`;
    }

    // Try generic color images with different extensions
    const extensions = ['.jpg', '.jpeg', '.png', '.webp'];
    for (let ext of extensions) {
        // Try different naming conventions
        const paths = [
            `/static/images/colors/${colorLower.replace(' ', '_')}${ext}`,
            `/static/images/colors/${colorLower.replace(' ', '-')}${ext}`,
            `/static/images/colors/${colorLower.replace(/\s+/g, '')}${ext}`
        ];

        // Return first path (will trigger onerror if not found)
        return paths[0];
    }

    // Final fallback
    return `/static/images/colors/${colorLower.replace(' ', '_')}.jpg`;
}

// Helper function to get color codes (fallback)
function getColorCode(colorName) {
    const colorMap = {
        'red': '#dc3545',
        'blue': '#0d6efd',
        'green': '#198754',
        'black': '#212529',
        'white': '#f8f9fa',
        'gray': '#6c757d',
        'grey': '#6c757d',
        'yellow': '#ffc107',
        'orange': '#fd7e14',
        'purple': '#6f42c1',
        'pink': '#d63384',
        'brown': '#8b4513',
        'navy': '#000080',
        'maroon': '#800000',
        'beige': '#f5f5dc',
        'coral': '#ff7f50',
        'gold': '#ffd700',
        'silver': '#c0c0c0',
        'lime': '#32cd32',
        'teal': '#008080',
        'indigo': '#4b0082',
        'violet': '#8a2be2',
        'cyan': '#00ffff',
        'magenta': '#ff00ff',
        // Additional common colors
        'dark blue': '#1e3a8a',
        'light blue': '#60a5fa',
        'dark green': '#166534',
        'light green': '#86efac',
        'dark red': '#991b1b',
        'light pink': '#f9a8d4',
        'cream': '#fef3c7',
        'tan': '#d2b48c',
        'olive': '#84cc16',
        'mint': '#6ee7b7',
        'lavender': '#c4b5fd',
        'peach': '#fed7aa',
        'turquoise': '#2dd4bf',
        'burgundy': '#881337',
        'khaki': '#a3a3a3'
    };

    const lowerColor = colorName.toLowerCase().trim();
    return colorMap[lowerColor] || '#6c757d';
}

// Helper function to determine if we need dark text on light background
function isLightColor(colorName) {
    const lightColors = [
        'white', 'yellow', 'beige', 'lime', 'cyan', 'silver', 'gold', 'coral',
        'cream', 'light blue', 'light green', 'light pink', 'peach', 'mint',
        'lavender', 'khaki'
    ];
    return lightColors.includes(colorName.toLowerCase().trim());
}

// Helper function to find the best matching image for a selected color
function findColorMatchingImage(selectedColor, allImages) {
    if (!allImages || !selectedColor) {
        return allImages ? allImages.split(',')[0].trim() : '';
    }

    const images = allImages.split(',').map(img => img.trim());
    const colorLower = selectedColor.toLowerCase().trim();

    // Create more comprehensive color variations for matching
    const colorVariations = [
        colorLower,
        colorLower.replace(' ', '_'),
        colorLower.replace(' ', '-'),
        colorLower.replace(/\s+/g, ''),
        colorLower.replace(' ', ''),
        // Add common color abbreviations
        getColorAbbreviation(colorLower)
    ].filter(Boolean); // Remove any empty strings

    console.log(`Looking for color "${selectedColor}" in images:`, images);
    console.log('Color variations to match:', colorVariations);

    // Look for exact matches first (highest priority)
    for (let img of images) {
        const imgName = img.toLowerCase();
        for (let variation of colorVariations) {
            if (imgName === variation + '.jpg' || imgName === variation + '.jpeg' ||
                imgName === variation + '.png' || imgName === variation + '.webp') {
                console.log(`Found exact match: ${img} for color ${selectedColor}`);
                return img;
            }
        }
    }

    // Look for images that contain the color name (partial matches)
    for (let img of images) {
        const imgName = img.toLowerCase();
        for (let variation of colorVariations) {
            if (imgName.includes(variation)) {
                console.log(`Found partial match: ${img} for color ${selectedColor}`);
                return img;
            }
        }
    }

    // Look for images with color at the beginning of filename
    for (let img of images) {
        const imgName = img.toLowerCase();
        for (let variation of colorVariations) {
            if (imgName.startsWith(variation)) {
                console.log(`Found prefix match: ${img} for color ${selectedColor}`);
                return img;
            }
        }
    }

    // Look for images with color at the end of filename (before extension)
    for (let img of images) {
        const imgNameWithoutExt = img.toLowerCase().replace(/\.(jpg|jpeg|png|webp)$/i, '');
        for (let variation of colorVariations) {
            if (imgNameWithoutExt.endsWith(variation)) {
                console.log(`Found suffix match: ${img} for color ${selectedColor}`);
                return img;
            }
        }
    }

    console.log(`No color-specific image found for ${selectedColor}, using first image:`, images[0]);
    // If no color-specific image found, return the first image
    return images[0] || '';
}

// Helper function to get common color abbreviations
function getColorAbbreviation(colorName) {
    const abbreviations = {
        'black': 'blk',
        'white': 'wht',
        'blue': 'blu',
        'red': 'rd',
        'green': 'grn',
        'yellow': 'ylw',
        'orange': 'org',
        'purple': 'prp',
        'pink': 'pnk',
        'brown': 'brn',
        'gray': 'gry',
        'grey': 'gry',
        'navy': 'nvy',
        'maroon': 'mrn',
        'beige': 'bge',
        'gold': 'gld',
        'silver': 'slv'
    };
    return abbreviations[colorName] || '';
}

// Enhanced image update function with better visual feedback
function updateModalImageWithFeedback(matchingImage) {
    if (!matchingImage) return;

    const modalImage = document.getElementById('modalProductImage');
    if (!modalImage) return;

    // Create loading overlay
    const imageContainer = modalImage.parentElement;
    const loadingOverlay = document.createElement('div');
    loadingOverlay.className = 'image-loading-overlay';
    loadingOverlay.innerHTML = `
        <div class="image-loading-content">
            <i class="fas fa-spinner fa-spin"></i>
            <span>Loading image...</span>
        </div>
    `;
    imageContainer.style.position = 'relative';
    imageContainer.appendChild(loadingOverlay);

    // Add smooth transition and fade effect
    modalImage.style.transition = 'all 0.4s cubic-bezier(0.4, 0, 0.2, 1)';
    modalImage.style.opacity = '0.3';
    modalImage.style.transform = 'scale(0.95)';
    modalImage.style.filter = 'blur(2px)';

    // Preload the new image
    const newImage = new Image();
    newImage.onload = function () {
        setTimeout(() => {
            // Update the source and apply enhanced styling
            modalImage.src = `/static/images/uploads/${matchingImage}`;
            modalImage.style.opacity = '1';
            modalImage.style.transform = 'scale(1)';
            modalImage.style.filter = 'none';
            modalImage.style.border = '3px solid #d4af37';
            modalImage.style.borderRadius = '12px';
            modalImage.style.boxShadow = '0 10px 30px rgba(212, 175, 55, 0.3)';

            // Remove loading overlay with fade out
            loadingOverlay.style.opacity = '0';
            setTimeout(() => {
                if (loadingOverlay.parentNode) {
                    loadingOverlay.remove();
                }
            }, 300);

            // Add success pulse effect
            modalImage.style.animation = 'imagePulse 0.6s ease-out';
            setTimeout(() => {
                modalImage.style.animation = '';
            }, 600);
        }, 300);
    };

    newImage.onerror = function () {
        // Handle error case
        modalImage.style.opacity = '1';
        modalImage.style.transform = 'scale(1)';
        modalImage.style.filter = 'none';
        if (loadingOverlay.parentNode) {
            loadingOverlay.remove();
        }
        console.error('Failed to load image:', matchingImage);
    };

    newImage.src = `/static/images/uploads/${matchingImage}`;
}

// Create ripple effect for color selection
function createRippleEffect(element, event) {
    const ripple = document.createElement('div');
    ripple.className = 'color-ripple';

    const rect = element.getBoundingClientRect();
    const size = Math.max(rect.width, rect.height);
    const x = event.clientX - rect.left - size / 2;
    const y = event.clientY - rect.top - size / 2;

    ripple.style.width = ripple.style.height = size + 'px';
    ripple.style.left = x + 'px';
    ripple.style.top = y + 'px';

    element.appendChild(ripple);

    // Remove ripple after animation
    setTimeout(() => {
        if (ripple.parentNode) {
            ripple.remove();
        }
    }, 600);
}

// Handle size and other selections
document.addEventListener('DOMContentLoaded', function () {
    // Quantity input event listener
    document.getElementById('quantity').addEventListener('change', function () {
        let quantity = parseInt(this.value);
        if (quantity < 1) {
            quantity = 1;
            this.value = 1;
        }
        if (quantity > 10) {
            quantity = 10;
            this.value = 10;
        }
        currentProduct.quantity = quantity;
    });

    // Close modal when clicking outside
    document.getElementById('colorSizeModal').addEventListener('click', function (e) {
        if (e.target === this) {
            closeColorSizeModal();
        }
    });

    // Close modal with Escape key
    document.addEventListener('keydown', function (e) {
        if (e.key === 'Escape') {
            closeColorSizeModal();
        }
    });
});

// Update the button states with enhanced visual feedback
function updateAddToCartButton() {
    const addToCartBtn = document.getElementById('addToCartBtn');
    const buyNowBtn = document.getElementById('buyNowBtn');

    // Check if both color and size are selected (including auto-selected defaults)
    const hasColor = currentProduct.selectedColor && currentProduct.selectedColor !== '';
    const hasSize = currentProduct.selectedSize && currentProduct.selectedSize !== '';

    if (hasColor && hasSize) {
        // Enable buttons with enhanced feedback
        if (addToCartBtn) {
            addToCartBtn.disabled = false;
            addToCartBtn.classList.add('enabled');
            addToCartBtn.textContent = 'Add to Cart';

            // Add success animation
            setTimeout(() => {
                addToCartBtn.classList.remove('enabled');
            }, 500);
        }
        if (buyNowBtn) {
            buyNowBtn.disabled = false;
            buyNowBtn.classList.add('enabled');
            buyNowBtn.textContent = 'Buy Now';

            // Add success animation
            setTimeout(() => {
                buyNowBtn.classList.remove('enabled');
            }, 500);
        }

        // Show completion feedback only if not auto-selected
        if (currentProduct.selectedColor !== 'Default' || currentProduct.selectedSize !== 'One Size') {
            showSelectionComplete();
        }
    } else {
        // Disable buttons
        if (addToCartBtn) {
            addToCartBtn.disabled = true;
            addToCartBtn.classList.remove('enabled');
            addToCartBtn.textContent = 'Select Color & Size';
        }
        if (buyNowBtn) {
            buyNowBtn.disabled = true;
            buyNowBtn.classList.remove('enabled');
            buyNowBtn.textContent = 'Select Color & Size';
        }
    }
}

// Show selection completion feedback
function showSelectionComplete() {
    // Create a subtle success indicator
    const modalBody = document.querySelector('.modal-body');
    if (!modalBody) return;

    const completionIndicator = document.createElement('div');
    completionIndicator.className = 'selection-complete-indicator';
    completionIndicator.innerHTML = `
        <i class="fas fa-check-circle"></i>
        <span>Ready to add to cart!</span>
    `;
    completionIndicator.style.cssText = `
        position: absolute;
        top: 10px;
        right: 10px;
        background: linear-gradient(135deg, #27ae60, #2ecc71);
        color: white;
        padding: 8px 12px;
        border-radius: 20px;
        font-size: 0.8rem;
        font-weight: 600;
        display: flex;
        align-items: center;
        gap: 6px;
        z-index: 100;
        box-shadow: 0 4px 12px rgba(39, 174, 96, 0.3);
        animation: slideInFromRight 0.4s ease-out;
        pointer-events: none;
    `;

    modalBody.style.position = 'relative';
    modalBody.appendChild(completionIndicator);

    // Remove after 2 seconds
    setTimeout(() => {
        if (completionIndicator.parentNode) {
            completionIndicator.style.animation = 'slideOutToRight 0.3s ease-in';
            setTimeout(() => {
                if (completionIndicator.parentNode) {
                    completionIndicator.remove();
                }
            }, 300);
        }
    }, 2000);
}

// Quantity control functions
function increaseQuantity() {
    const quantityInput = document.getElementById('quantity');
    let currentQuantity = parseInt(quantityInput.value);
    if (currentQuantity < 10) {
        quantityInput.value = currentQuantity + 1;
        currentProduct.quantity = currentQuantity + 1;
    }
}

function decreaseQuantity() {
    const quantityInput = document.getElementById('quantity');
    let currentQuantity = parseInt(quantityInput.value);
    if (currentQuantity > 1) {
        quantityInput.value = currentQuantity - 1;
        currentProduct.quantity = currentQuantity - 1;
    }
}

// Confirm add to cart with selected options
function confirmAddToCart() {
    // Check if color and size are selected (including auto-selected defaults)
    if (!currentProduct.selectedColor || currentProduct.selectedColor === '' || 
        !currentProduct.selectedSize || currentProduct.selectedSize === '') {
        alert('Please select both color and size before adding to cart.');
        return;
    }

    // Find the best matching image for the selected color
    const selectedImage = findColorMatchingImage(currentProduct.selectedColor, currentProduct.image);

    // Send data to backend to save in database
    addToCartDatabase(
        currentProduct.id,
        currentProduct.name,
        currentProduct.price,
        currentProduct.selectedColor,
        currentProduct.selectedSize,
        currentProduct.quantity,
        selectedImage // Pass the specific color-matching image
    );
}

// Add to cart function that sends data to backend database
function addToCartDatabase(productId, productName, productPrice, color, size, quantity, selectedImage) {
    // Prepare data to send to backend
    const cartData = {
        product_id: productId,
        product_name: productName,
        product_price: productPrice,
        product_variation: color,
        size: size,
        quantity: quantity,
        product_image: selectedImage // This is now the color-specific image
    };

    // Send POST request to backend
    fetch('/add-to-cart', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify(cartData)
    })
        .then(response => response.json())
        .then(data => {
            console.log('Add to cart response:', data);
            if (data.success) {
                // Close modal
                closeColorSizeModal();

                // Show success message
                const successMessage = data.message || 'Item added to cart successfully!';
                showSuccessMessage(successMessage);

                // Also show a brief alert as backup (optional - can be removed if styled message works well)
                // alert(successMessage);

                // Update cart count if needed
                updateCartCount();
            } else if (data.cartFull) {
                alert(data.error || 'Cart is full! Maximum 20 items allowed.');
            } else {
                alert(data.error || 'Failed to add item to cart. Please try again.');
            }
        })
        .catch(error => {
            console.error('Error adding to cart:', error);
            alert('Failed to add item to cart. Please try again.');
        });
}

// Show success message using modal
function showSuccessMessage(message = 'Item added to cart successfully!') {
    // Use the success cart modal instead of notification
    if (typeof showSuccessCartModal === 'function') {
        showSuccessCartModal();
    } else {
        console.error('showSuccessCartModal function not found');
    }
    
    // Log for debugging
    console.log('Success message shown:', message);
}

// Update cart count by fetching from backend
function updateCartCount() {
    // Check if global updateCartCount exists (from header)
    if (typeof window.updateCartCount === 'function' && window.updateCartCount !== updateCartCount) {
        window.updateCartCount();
        return;
    }

    // Fallback: Fetch cart count from backend
    fetch('/api/cart-count')
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                const count = data.count || 0;
                
                // Update cart badge (homepg_header.html)
                const cartBadge = document.getElementById('cartBadge');
                if (cartBadge) {
                    cartBadge.textContent = count;
                    cartBadge.style.display = count > 0 ? 'flex' : 'none';
                }
                
                // Update cart count element (other headers)
                const cartCountElement = document.querySelector('.cart-count');
                if (cartCountElement) {
                    cartCountElement.textContent = count;
                }
            }
        })
        .catch(error => {
            console.error('Error fetching cart count:', error);
        });
}

// Initialize cart count on page load
document.addEventListener('DOMContentLoaded', function () {
    updateCartCount();
    updateAddToCartButton();
});

// Add CSS for success message animation
const style = document.createElement('style');
style.textContent = `
    @keyframes slideInRight {
        from {
            transform: translateX(100%);
            opacity: 0;
        }
        to {
            transform: translateX(0);
            opacity: 1;
        }
    }
    
    @keyframes slideOutRight {
        from {
            transform: translateX(0);
            opacity: 1;
        }
        to {
            transform: translateX(100%);
            opacity: 0;
        }
    }
    
    .success-message {
        pointer-events: none;
    }
    
    .success-message i {
        color: #ffffff;
        margin-right: 8px;
    }
`;
document.head.appendChild(style);
// Open modal specifically for Buy Now functionality
function openBuyNowModal(productId, productName, productPrice, productImage, productVariations, productSizes) {
    // Check if user is logged in
    if (typeof isUserLoggedIn !== 'undefined' && !isUserLoggedIn) {
        showLoginFirstModal();
        return;
    }
    
    console.log('Opening buy now modal for product:', productId, productName, productPrice, productImage, productVariations, productSizes);
    
    // Handle None or undefined values
    if (productVariations === 'None' || productVariations === 'undefined' || productVariations === null) {
        productVariations = '';
    }
    if (productSizes === 'None' || productSizes === 'undefined' || productSizes === null) {
        productSizes = '';
    }
    
    currentProduct.id = productId;
    currentProduct.name = productName;
    currentProduct.price = productPrice;
    currentProduct.image = productImage;

    // Reset selections
    currentProduct.selectedColor = null;
    currentProduct.selectedSize = null;
    currentProduct.quantity = 1;

    // Update modal content
    document.getElementById('modalProductName').textContent = productName;
    document.getElementById('modalProductPrice').textContent = '₱ ' + parseFloat(productPrice).toFixed(2);

    // Handle product image - get first image if multiple images are provided
    const productImages = productImage ? productImage.split(',') : [];
    const firstImage = productImages.length > 0 ? productImages[0].trim() : '';
    if (firstImage) {
        document.getElementById('modalProductImage').src = `/static/images/uploads/${firstImage}`;
    }

    document.getElementById('quantity').value = 1;

    // Reset selection displays
    document.getElementById('selectedColor').textContent = 'Please select a color';
    document.getElementById('selectedSize').textContent = 'Please select a size';

    // Generate dynamic color options based on product variations
    generateColorOptions(productVariations);

    // Generate dynamic size options based on product sizes
    generateSizeOptions(productSizes);

    // Clear previous selections for sizes and colors
    document.querySelectorAll('.size-option').forEach(option => {
        option.classList.remove('selected');
    });
    document.querySelectorAll('.color-option').forEach(option => {
        option.classList.remove('selected');
    });

    // Show Buy Now button and hide Add to Cart button
    document.getElementById('buyNowBtn').style.display = 'inline-block';
    document.getElementById('addToCartBtn').style.display = 'none';

    // Show modal
    document.getElementById('colorSizeModal').style.display = 'block';
    document.body.style.overflow = 'hidden'; // Prevent background scrolling
}

// Confirm buy now with selected options
function confirmBuyNow() {
    // Check if color and size are selected (including auto-selected defaults)
    if (!currentProduct.selectedColor || currentProduct.selectedColor === '' || 
        !currentProduct.selectedSize || currentProduct.selectedSize === '') {
        alert('Please select both color and size before proceeding.');
        return;
    }

    // Find the best matching image for the selected color
    const selectedImage = findColorMatchingImage(currentProduct.selectedColor, currentProduct.image);

    // Proceed directly to checkout with selected options
    proceedToBuyNow(selectedImage);
}

// Wishlist functionality
function addToWishlist(productId, productName, productPrice, btn) {
    const isCurrentlyWishlisted = btn && btn.classList.contains('active');
    fetch('/add-to-wishlist', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ product_id: productId, product_name: productName, product_price: productPrice })
    })
    .then(r => {
        if (r.status === 401) { window.location.href = '/login'; return null; }
        return r.json();
    })
    .then(data => {
        if (!data) return;
        if (data.success) {
            if (btn) {
                btn.classList.toggle('active', !isCurrentlyWishlisted);
                btn.title = !isCurrentlyWishlisted ? 'Remove from Wishlist' : 'Add to Wishlist';
            }
            if (typeof showSuccessWishlistModal === 'function') {
                showSuccessWishlistModal(data.message, isCurrentlyWishlisted);
            }
        } else {
            alert(data.error || 'Failed to update wishlist');
        }
    })
    .catch(() => alert('Failed to update wishlist. Please try again.'));
}

function buyNow(productId, productName, productPrice, variations) {
    // Open the color/size modal for buy now
    openColorSizeModal(productId, productName, productPrice, '', variations);

    // Modify the modal for buy now instead of add to cart
    const addToCartBtn = document.querySelector('.btn-add-to-cart');
    addToCartBtn.textContent = 'Buy Now';
    addToCartBtn.onclick = function () {
        if (!currentProduct.selectedColor || !currentProduct.selectedSize) {
            alert('Please select both color and size before proceeding.');
            return;
        }

        // Proceed directly to checkout with selected options
        proceedToBuyNow();
    };
}

function proceedToBuyNow(selectedImage) {
    // Send data to backend for direct checkout
    const checkoutData = {
        product_id: currentProduct.id,
        product_name: currentProduct.name,
        product_price: currentProduct.price,
        quantity: currentProduct.quantity,
        product_variation: currentProduct.selectedColor,  // Changed from 'variations' to 'product_variation'
        size: currentProduct.selectedSize,
        product_image: selectedImage // Include the color-specific image
    };

    fetch('/checkout_single_product', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/x-www-form-urlencoded',
        },
        body: new URLSearchParams(checkoutData)
    })
        .then(response => {
            if (!response.ok) {
                if (response.status === 401) {
                    alert('Please login first');
                    window.location.href = '/login';
                    return;
                }
                throw new Error('Network response was not ok');
            }
            return response.json();
        })
        .then(data => {
            if (data.success) {
                // Close modal and redirect to checkout
                closeColorSizeModal();
                window.location.href = '/checkout';
            } else {
                alert(data.error || 'Failed to proceed to checkout');
            }
        })
        .catch(error => {
            console.error('Error:', error);
            alert('Failed to proceed to checkout. Please try again.');
        });
}

// Make functions globally accessible
window.openColorSizeModal = openColorSizeModal;
window.openBuyNowModal = openBuyNowModal;
window.closeColorSizeModal = closeColorSizeModal;
window.confirmAddToCart = confirmAddToCart;
window.confirmBuyNow = confirmBuyNow;
window.increaseQuantity = increaseQuantity;
window.decreaseQuantity = decreaseQuantity;

console.log('✅ Color/Size Modal functions loaded and available globally');
console.log('Available functions:', {
    openColorSizeModal: typeof window.openColorSizeModal,
    openBuyNowModal: typeof window.openBuyNowModal,
    closeColorSizeModal: typeof window.closeColorSizeModal
});
