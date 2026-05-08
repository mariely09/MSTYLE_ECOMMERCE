// Seller Order History JavaScript

document.addEventListener('DOMContentLoaded', function() {
    initializeFilters();
    initializeSearch();
});

let allOrders = [];
let filteredOrders = [];

function initializeFilters() {
    // Get all order rows (table rows)
    allOrders = Array.from(document.querySelectorAll('tbody tr[data-status]'));
    filteredOrders = [...allOrders];
    
    // Set up event listeners
    const statusFilter = document.getElementById('statusFilter');
    const sortBy = document.getElementById('sortBy');
    const searchInput = document.getElementById('searchInput');
    const clearSearch = document.getElementById('clearSearch');
    
    if (statusFilter) {
        statusFilter.addEventListener('change', filterOrders);
    }
    
    if (sortBy) {
        sortBy.addEventListener('change', sortOrders);
    }
    
    if (searchInput) {
        searchInput.addEventListener('input', debounce(handleSearch, 300));
    }
    
    if (clearSearch) {
        clearSearch.addEventListener('click', clearSearchInput);
    }
}

function initializeSearch() {
    const searchInput = document.getElementById('searchInput');
    const clearSearch = document.getElementById('clearSearch');
    
    if (searchInput) {
        searchInput.addEventListener('input', function() {
            // Show/hide clear button
            if (clearSearch) {
                clearSearch.style.display = this.value ? 'block' : 'none';
            }
            searchOrders();
        });
    }
}

function handleSearch() {
    const searchInput = document.getElementById('searchInput');
    const clearSearch = document.getElementById('clearSearch');
    
    if (clearSearch) {
        clearSearch.style.display = searchInput.value ? 'block' : 'none';
    }
    
    searchOrders();
}

function clearSearchInput() {
    const searchInput = document.getElementById('searchInput');
    const clearSearch = document.getElementById('clearSearch');
    
    if (searchInput) {
        searchInput.value = '';
    }
    
    if (clearSearch) {
        clearSearch.style.display = 'none';
    }
    
    filterOrders();
}

function filterOrders() {
    const statusFilterEl = document.getElementById('statusFilter');
    const searchInputEl = document.getElementById('searchInput');
    
    const statusFilter = statusFilterEl ? statusFilterEl.value : 'all';
    const searchTerm = searchInputEl ? searchInputEl.value.toLowerCase() : '';
    
    filteredOrders = allOrders.filter(order => {
        // Status filter
        if (statusFilter !== 'all') {
            const orderStatus = order.dataset.status;
            if (orderStatus !== statusFilter) return false;
        }
        
        // Search filter
        if (searchTerm) {
            const customer = order.dataset.customer.toLowerCase();
            const product = order.dataset.product.toLowerCase();
            if (!customer.includes(searchTerm) && !product.includes(searchTerm)) {
                return false;
            }
        }
        
        return true;
    });
    
    // Apply current sort after filtering
    applySortToFiltered();
    
    updateDisplay();
}

function applySortToFiltered() {
    const sortBy = document.getElementById('sortBy');
    if (!sortBy) return;
    
    const sortValue = sortBy.value;
    
    filteredOrders.sort((a, b) => {
        switch (sortValue) {
            case 'date_desc':
                return new Date(b.dataset.date) - new Date(a.dataset.date);
            case 'date_asc':
                return new Date(a.dataset.date) - new Date(b.dataset.date);
            case 'customer_asc':
                return a.dataset.customer.localeCompare(b.dataset.customer);
            case 'price_desc':
                return parseFloat(b.dataset.price) - parseFloat(a.dataset.price);
            case 'price_asc':
                return parseFloat(a.dataset.price) - parseFloat(b.dataset.price);
            default:
                return 0;
        }
    });
}



function searchOrders() {
    filterOrders(); // This will handle both status and search filtering
}

function sortOrders() {
    const sortBy = document.getElementById('sortBy');
    if (!sortBy) return;
    
    const sortValue = sortBy.value;
    
    // First apply filters to get the current filtered set
    filterOrders();
    
    // Then sort the filtered results
    filteredOrders.sort((a, b) => {
        switch (sortValue) {
            case 'date_desc':
                return new Date(b.dataset.date) - new Date(a.dataset.date);
            case 'date_asc':
                return new Date(a.dataset.date) - new Date(b.dataset.date);
            case 'customer_asc':
                return a.dataset.customer.localeCompare(b.dataset.customer);
            case 'price_desc':
                return parseFloat(b.dataset.price) - parseFloat(a.dataset.price);
            case 'price_asc':
                return parseFloat(a.dataset.price) - parseFloat(b.dataset.price);
            default:
                return 0;
        }
    });
    
    updateDisplay();
}

function updateDisplay() {
    const tbody = document.querySelector('tbody');
    if (!tbody) return;
    
    // Remove any existing no-results row
    const existingEmptyRow = tbody.querySelector('.no-results-row');
    if (existingEmptyRow) {
        existingEmptyRow.remove();
    }
    
    // Hide all rows first
    allOrders.forEach(row => row.style.display = 'none');
    
    if (filteredOrders.length === 0) {
        // Show empty state or no results message
        if (allOrders.length > 0) {
            // No orders match filters - show message
            const noResultsRow = document.createElement('tr');
            noResultsRow.className = 'no-results-row';
            noResultsRow.innerHTML = `
                <td colspan="11" class="empty-message">
                    <div class="empty-state">
                        <div class="empty-icon">
                            <i class="bi bi-search"></i>
                        </div>
                        <h3>No Orders Found</h3>
                        <p>No orders match your current filters. Try adjusting your search criteria.</p>
                        <button class="btn btn-secondary" onclick="clearAllFilters()">
                            <i class="bi bi-arrow-clockwise"></i>
                            Clear Filters
                        </button>
                    </div>
                </td>
            `;
            tbody.appendChild(noResultsRow);
        }
    } else {
        // Re-order the DOM elements to match the sorted order
        filteredOrders.forEach((order, index) => {
            tbody.appendChild(order); // This moves the element to the end
            order.style.display = '';
            // Update the sequence number
            const sequenceBadge = order.querySelector('.sequence-badge');
            if (sequenceBadge) {
                sequenceBadge.textContent = index + 1;
            }
        });
    }
    
    // Update pagination info
    updatePaginationInfo();
}

function updatePaginationInfo() {
    const paginationInfo = document.querySelector('.pagination-info');
    if (paginationInfo) {
        paginationInfo.textContent = `Showing ${filteredOrders.length} of ${allOrders.length} orders`;
    }
}

function clearAllFilters() {
    const statusFilter = document.getElementById('statusFilter');
    const sortBy = document.getElementById('sortBy');
    const searchInput = document.getElementById('searchInput');
    const clearSearch = document.getElementById('clearSearch');
    
    if (statusFilter) statusFilter.value = 'all';
    if (sortBy) sortBy.value = 'date_desc';
    if (searchInput) searchInput.value = '';
    if (clearSearch) clearSearch.style.display = 'none';
    
    filteredOrders = [...allOrders];
    sortOrders();
}

function viewOrderDetails(orderId) {
    // Fetch order details via AJAX
    fetch(`/api/seller-order-details/${orderId}`)
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                showOrderDetailsModal(data.order);
            } else {
                showToast('Failed to load order details: ' + (data.message || 'Unknown error'), 'error');
            }
        })
        .catch(error => {
            console.error('Error fetching order details:', error);
            showToast('Error loading order details', 'error');
        });
}

function showOrderDetailsModal(order) {
    // Populate customer information
    document.getElementById('modal-customer-name').textContent = `${order.first_name} ${order.last_name}`;
    document.getElementById('modal-customer-email').textContent = order.email;
    document.getElementById('modal-customer-address').textContent = order.address || 'No address provided';
    
    // Populate order information
    document.getElementById('modal-order-id').textContent = '#' + order.id;
    document.getElementById('modal-order-date').textContent = order.date || 'Date not available';
    document.getElementById('modal-order-quantity').textContent = order.quantity;
    
    // Set status with appropriate styling
    const statusElement = document.getElementById('modal-order-status');
    statusElement.textContent = order.status;
    statusElement.className = 'value status-value status-' + order.status.toLowerCase().replace(/\s+/g, '-');
    
    // Populate product information
    document.getElementById('modal-product-image').src = order.image || '/static/images/placeholder.png';
    document.getElementById('modal-product-image').alt = order.name;
    document.getElementById('modal-product-name').textContent = order.name;
    document.getElementById('modal-product-variation').textContent = order.variations || 'No variation specified';
    document.getElementById('modal-product-size').textContent = order.size || 'One Size';
    
    // Calculate pricing
    const totalPrice = parseFloat(order.total_price) || 0;
    const shippingFee = parseFloat(order.shipping_fee) || 50;
    const quantity = parseInt(order.quantity) || 1;
    const subtotal = totalPrice - shippingFee;
    const unitPrice = quantity > 0 ? subtotal / quantity : subtotal;

    const shippingText = shippingFee === 0 ? '₱0.00 (Free Shipping)' : '₱' + shippingFee.toFixed(2);

    // Populate pricing information
    document.getElementById('modal-unit-price').textContent = '₱' + unitPrice.toFixed(2);
    document.getElementById('modal-quantity').textContent = quantity;
    document.getElementById('modal-subtotal').textContent = '₱' + subtotal.toFixed(2);
    document.getElementById('modal-shipping-fee').textContent = shippingText;
    document.getElementById('modal-total-price').textContent = '₱' + totalPrice.toFixed(2);
    
    // Show modal
    const modal = document.getElementById('orderDetailsModal');
    modal.style.display = 'block';
    document.body.style.overflow = 'hidden';
}

function closeOrderModal() {
    const modal = document.getElementById('orderDetailsModal');
    modal.style.display = 'none';
    document.body.style.overflow = 'auto';
}

function contactCustomer(email, name) {
    const subject = encodeURIComponent(`Regarding your order - MStyle`);
    const body = encodeURIComponent(`Dear ${name},\n\nI hope this message finds you well. I wanted to reach out regarding your recent order.\n\nBest regards,\nMStyle Team`);
    
    window.location.href = `mailto:${email}?subject=${subject}&body=${body}`;
}

function confirmDeleteOrder(orderId, productName) {
    const confirmed = confirm(
        `Are you sure you want to delete this order?\n\n` +
        `Product: ${productName}\n` +
        `Order ID: #${orderId}\n\n` +
        `This action cannot be undone. The order will be permanently removed from your history.`
    );
    
    if (confirmed) {
        deleteOrder(orderId);
    }
}

function deleteOrder(orderId) {
    // Show loading toast
    showToast('Deleting order...', 'info', 2000);
    
    fetch(`/api/delete-order-history/${orderId}`, {
        method: 'DELETE',
        headers: {
            'Content-Type': 'application/json'
        }
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            showToast('Order deleted successfully', 'success');
            // Remove the row from the table
            setTimeout(() => {
                location.reload();
            }, 1000);
        } else {
            showToast('Failed to delete order: ' + (data.message || 'Unknown error'), 'error');
        }
    })
    .catch(error => {
        console.error('Error deleting order:', error);
        showToast('Error deleting order', 'error');
    });
}

function calculateShippingFee(itemTotal, promotionType) {
    if (promotionType === 'free_shipping') {
        return 0;
    }
    
    const baseShipping = 50.0;
    const additionalShipping = Math.min(150.0, Math.floor(itemTotal / 500) * 10);
    return baseShipping + additionalShipping;
}

function exportHistory() {
    const orders = filteredOrders.map(orderRow => {
        const data = orderRow.dataset;
        const cells = orderRow.querySelectorAll('td');
        return {
            'No': cells[0].textContent.trim(),
            'Customer': data.customer,
            'Product': data.product,
            'Status': data.status,
            'Date': data.date,
            'Amount': `₱${parseFloat(data.price).toFixed(2)}`
        };
    });
    
    if (orders.length === 0) {
        showToast('No orders to export', 'warning');
        return;
    }
    
    // Convert to CSV
    const headers = Object.keys(orders[0]);
    const csvContent = [
        headers.join(','),
        ...orders.map(order => headers.map(header => `"${order[header]}"`).join(','))
    ].join('\n');
    
    // Download CSV
    const blob = new Blob([csvContent], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `order_history_${new Date().toISOString().split('T')[0]}.csv`;
    link.style.display = 'none';
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
    
    showToast('Order history exported successfully', 'success');
}

// Toast notification system
function showToast(message, type = 'success', duration = 5000) {
    const toastContainer = document.getElementById('toast-container');
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    
    const icons = {
        success: 'bi-check-circle-fill',
        error: 'bi-x-circle-fill',
        warning: 'bi-exclamation-triangle-fill',
        info: 'bi-info-circle-fill'
    };
    
    toast.innerHTML = `
        <div class="toast-content">
            <i class="bi ${icons[type] || icons.success}"></i>
            <span class="toast-message">${message}</span>
            <button class="toast-close" onclick="closeToast(this)">
                <i class="bi bi-x"></i>
            </button>
        </div>
    `;
    
    toastContainer.appendChild(toast);
    
    setTimeout(() => toast.classList.add('toast-show'), 100);
    setTimeout(() => closeToast(toast.querySelector('.toast-close')), duration);
}

function closeToast(closeButton) {
    const toast = closeButton.closest('.toast');
    toast.classList.remove('toast-show');
    toast.classList.add('toast-hide');
    
    setTimeout(() => {
        if (toast.parentNode) {
            toast.parentNode.removeChild(toast);
        }
    }, 300);
}

// Utility function for debouncing
function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
        const later = () => {
            clearTimeout(timeout);
            func(...args);
        };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
}

// Modal event listeners
document.addEventListener('click', function(event) {
    const modal = document.getElementById('orderDetailsModal');
    if (event.target === modal) {
        closeOrderModal();
    }
});

document.addEventListener('keydown', function(event) {
    if (event.key === 'Escape') {
        closeOrderModal();
    }
});