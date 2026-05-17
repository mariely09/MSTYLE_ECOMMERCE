// Order List JavaScript Functions

// Handle Status Update (Confirm/Reject)
function handleStatusUpdate(orderId, newStatus, customerEmail, currentStatus, buttonElement) {
    console.log('🔄 handleStatusUpdate called');
    console.log('Order ID:', orderId);
    console.log('New Status:', newStatus);
    console.log('Customer Email:', customerEmail);
    console.log('Current Status:', currentStatus);
    
    // Create confirmation message
    let message = `Are you sure you want to update the order status from "${currentStatus}" to "${newStatus}"?\n\n`;
    
    if (newStatus === 'Confirmed') {
        message += `This will confirm the order. The seller will then prepare it before it becomes available for riders to pick up. The customer (${customerEmail}) will be notified that their order has been confirmed.`;
    } else if (newStatus === 'Rejected') {
        message += `This will reject the order. The customer (${customerEmail}) will be notified that their order has been rejected.`;
    }
    
    message += '\n\nAn email notification will be sent automatically.';
    
    if (!confirm(message)) {
        console.log('❌ User cancelled the action');
        return; // User cancelled
    }
    
    console.log('✅ User confirmed the action');
    
    // Show loading state
    const originalHTML = buttonElement.innerHTML;
    buttonElement.innerHTML = '<i class="bi bi-hourglass-split"></i>';
    buttonElement.disabled = true;
    
    // Store status update info for after page reload
    const updateInfo = {
        status: newStatus,
        customer: customerEmail,
        timestamp: Date.now()
    };
    
    console.log('💾 Storing to sessionStorage:', updateInfo);
    sessionStorage.setItem('statusUpdateInfo', JSON.stringify(updateInfo));
    
    // Verify it was stored
    const stored = sessionStorage.getItem('statusUpdateInfo');
    console.log('✅ Verified sessionStorage:', stored);
    
    // Create and submit form
    const form = document.createElement('form');
    form.method = 'POST';
    form.action = `/update_order_status/${orderId}`;
    
    const statusInput = document.createElement('input');
    statusInput.type = 'hidden';
    statusInput.name = 'stat';
    statusInput.value = newStatus;
    
    form.appendChild(statusInput);
    document.body.appendChild(form);
    
    console.log('📤 Submitting form to:', form.action);
    form.submit();
}

// Show Success Modal
function showSuccessModal(status, customerEmail) {
    console.log('showSuccessModal called with:', status, customerEmail);
    
    const modal = document.getElementById('successModal');
    if (!modal) {
        console.error('Success modal not found!');
        return;
    }
    
    const modalTitle = modal.querySelector('h2');
    const thankYouMessage = modal.querySelector('.thank-you-message');
    const orderMessage = modal.querySelector('.order-message');
    const successIcon = modal.querySelector('.success-icon i');
    
    console.log('Modal elements found:', {
        modal: !!modal,
        modalTitle: !!modalTitle,
        thankYouMessage: !!thankYouMessage,
        orderMessage: !!orderMessage,
        successIcon: !!successIcon
    });
    
    // Update modal content based on status
    if (status === 'Confirmed') {
        modalTitle.textContent = 'Order Confirmed Successfully!';
        modalTitle.style.color = '#28a745';
        thankYouMessage.textContent = 'Order Status Updated!';
        orderMessage.textContent = `The order has been confirmed and is now available for riders to accept. The customer (${customerEmail}) will be notified via email.`;
        successIcon.className = 'fas fa-check success-checkmark';
        successIcon.parentElement.style.background = 'linear-gradient(135deg, #28a745, #20c997)';
    } else if (status === 'Rejected') {
        modalTitle.textContent = 'Order Rejected!';
        modalTitle.style.color = '#dc3545';
        thankYouMessage.textContent = 'Order Status Updated!';
        orderMessage.textContent = `The order has been rejected. The customer (${customerEmail}) will be notified via email about the rejection.`;
        successIcon.className = 'fas fa-times success-checkmark';
        successIcon.parentElement.style.background = 'linear-gradient(135deg, #dc3545, #c82333)';
    }
    
    // Show modal
    console.log('Showing modal...');
    modal.classList.add('show');
    modal.style.display = 'flex';
    document.body.style.overflow = 'hidden';
    console.log('Modal should be visible now');
}

// Close Success Modal
function closeSuccessModal() {
    const modal = document.getElementById('successModal');
    modal.classList.remove('show');
    modal.style.display = 'none';
    document.body.style.overflow = 'auto';
}

// Store current order details for printing
let currentOrderDetails = {};

// Order Details Modal Functions
function openOrderModal(orderId, customerName, customerEmail, customerAddress, productName, productImage, productVariation, productSize, quantity, originalPrice, promotionType, discountPercentage, discountAmount, totalPrice, shippingFeeArg, orderDate, orderStatus, promotionName, customerPhone, sellerBusinessName, sellerAddress, sellerPhone, productId, riderEmail, riderName) {
    // Store order details for printing
    currentOrderDetails = {
        productId,
        orderId,
        customerName,
        customerEmail,
        customerAddress,
        customerPhone: customerPhone || 'Not provided',
        productName,
        productImage,
        productVariation,
        productSize,
        quantity,
        originalPrice,
        promotionType,
        discountPercentage,
        discountAmount,
        totalPrice,
        orderDate,
        orderStatus,
        promotionName,
        sellerBusinessName: sellerBusinessName || 'MSTYLE Seller',
        sellerAddress: sellerAddress || 'Philippines',
        sellerPhone: sellerPhone || '+63 XXX XXX XXXX',
        riderEmail: riderEmail || null,
        riderName: riderName || null
    };

    // Populate customer information
    document.getElementById('modal-customer-name').textContent = customerName;
    document.getElementById('modal-customer-email').textContent = customerEmail;
    document.getElementById('modal-customer-address').textContent = customerAddress || 'No address provided';

    // Populate order information
    document.getElementById('modal-order-id').textContent = '#' + orderId;
    document.getElementById('modal-order-date').textContent = orderDate || 'Date not available';
    document.getElementById('modal-order-quantity').textContent = quantity;

    // Set status with appropriate styling
    const statusElement = document.getElementById('modal-order-status');
    statusElement.textContent = orderStatus;
    statusElement.className = 'value status-value status-' + orderStatus.toLowerCase().replace(/\s+/g, '-');

    // Populate product information
    document.getElementById('modal-product-image').src = productImage;
    document.getElementById('modal-product-image').alt = productName;
    document.getElementById('modal-product-name').textContent = productName;
    document.getElementById('modal-product-variation').textContent = productVariation || 'No variation specified';
    document.getElementById('modal-product-size').textContent = productSize || 'One Size';

    // ── Promotion display ────────────────────────────────────────────────
    let promotionText = 'No Promotion';
    let discountText  = 'No Discount';
    let hasFreeShipping  = (promotionType === 'free_shipping');
    let hasPriceDiscount = false;

    // Effective unit sale price = totalPrice ÷ qty (most reliable — comes straight from DB)
    const qty          = parseInt(quantity) || 1;
    const origUnit     = parseFloat(originalPrice);
    const subtotalVal  = parseFloat(totalPrice);           // sale_price × qty (no shipping)
    const salePriceUnit = subtotalVal / qty;               // effective unit price after discount
    const totalDiscountApplied = parseFloat(discountAmount) || 0;

    if (promotionType) {
        switch (promotionType) {
            case 'free_shipping':
                promotionText = '🚚 Free Shipping';
                break;
            case 'buy_one_get_one':
                promotionText = 'Buy One Get One';
                break;
            case 'percentage':
                promotionText    = (parseFloat(discountPercentage) || 0) + '% OFF';
                hasPriceDiscount = true;
                break;
            case 'fixed':
                promotionText    = '₱' + (totalDiscountApplied > 0
                    ? (totalDiscountApplied / qty).toFixed(0)
                    : parseFloat(discountPercentage || 0).toFixed(0)) + ' OFF per item';
                hasPriceDiscount = true;
                break;
            default:
                promotionText = promotionName || promotionType;
                break;
        }
    }

    // ── Shipping fee — flat ₱50, free if free_shipping promo ────────────
    const shippingFee = hasFreeShipping ? 0 : (isNaN(parseFloat(shippingFeeArg)) ? 50 : parseFloat(shippingFeeArg));
    const shippingText = hasFreeShipping ? '₱0.00 (Free Shipping)' : '₱' + shippingFee.toFixed(2);

    // ── Grand total ──────────────────────────────────────────────────────
    const finalTotal = subtotalVal + shippingFee;

    // ── Populate pricing rows ────────────────────────────────────────────

    // Unit price — strikethrough when discounted
    const origEl = document.getElementById('modal-original-price');
    if (hasPriceDiscount) {
        origEl.innerHTML = '<span style="text-decoration:line-through;color:#95a5a6;font-weight:400;">₱'
            + origUnit.toFixed(2) + '</span>';
    } else {
        origEl.textContent = '₱' + origUnit.toFixed(2);
    }

    // Sale price row — only for percentage/fixed
    const salePriceRow = document.getElementById('modal-sale-price-row');
    const salePriceEl  = document.getElementById('modal-sale-price');
    if (hasPriceDiscount) {
        salePriceEl.textContent = '₱' + salePriceUnit.toFixed(2) + ' / unit';
        salePriceRow.style.display = '';
    } else {
        salePriceRow.style.display = 'none';
    }

    // Quantity
    document.getElementById('modal-pricing-qty').textContent = qty + ' item' + (qty > 1 ? 's' : '');

    // Subtotal (sale price × qty, NO shipping)
    document.getElementById('modal-subtotal').textContent = '₱' + subtotalVal.toFixed(2);

    // Promotion badge
    const promoEl = document.getElementById('modal-promotion');
    if (promotionType) {
        const badgeMap = {
            free_shipping:   'free-shipping',
            buy_one_get_one: 'bogo',
            percentage:      'percentage',
            fixed:           'fixed',
        };
        const badgeClass = badgeMap[promotionType] || 'other';
        promoEl.innerHTML = `<span class="promotion-badge ${badgeClass}">${promotionText}</span>`;
    } else {
        promoEl.innerHTML = '<span style="color:#6c757d;font-style:italic;">No Promotion</span>';
    }

    // Discount row — only when there's an actual price reduction
    const discountRow = document.getElementById('modal-discount-row');
    const discountEl  = document.getElementById('modal-discount');
    if (hasPriceDiscount && totalDiscountApplied > 0) {
        discountEl.textContent = '−₱' + totalDiscountApplied.toFixed(2);
        discountRow.style.display = '';
    } else {
        discountRow.style.display = 'none';
    }

    // Shipping
    const shipEl = document.getElementById('modal-shipping-fee');
    if (hasFreeShipping) {
        shipEl.innerHTML = '<span style="color:#27ae60;font-weight:600;">₱0.00</span>'
            + ' <span style="background:rgba(39,174,96,0.1);border:1px solid rgba(39,174,96,0.3);'
            + 'color:#1e8449;font-size:10px;font-weight:700;padding:1px 6px;border-radius:8px;margin-left:4px;">FREE</span>';
    } else {
        shipEl.textContent = shippingText;
    }

    // Grand total
    document.getElementById('modal-total-price').textContent = '₱' + finalTotal.toFixed(2);

    // Store for printing
    currentOrderDetails.shippingFee   = shippingFee;
    currentOrderDetails.itemSubtotal  = subtotalVal;
    currentOrderDetails.finalTotal    = finalTotal;
    currentOrderDetails.promotionText = promotionText;
    currentOrderDetails.discountText  = totalDiscountApplied > 0 ? '−₱' + totalDiscountApplied.toFixed(2) : 'No Discount';
    
    // Show/hide Contact Rider button based on rider assignment
    const contactRiderBtn = document.getElementById('contactRiderBtn');
    if (contactRiderBtn) {
        // Show Contact Rider button only if rider is assigned (statuses: For Pickup, Heading to Seller, Shipped, Delivered)
        const riderAssignedStatuses = ['for pickup', 'heading to seller', 'shipped', 'delivered'];
        const shouldShowRiderBtn = riderEmail && riderAssignedStatuses.includes(orderStatus.toLowerCase());
        
        console.log('Contact Rider Button Debug:', {
            riderEmail: riderEmail,
            riderName: riderName,
            orderStatus: orderStatus,
            shouldShow: shouldShowRiderBtn
        });
        
        contactRiderBtn.style.display = shouldShowRiderBtn ? 'inline-flex' : 'none';
    }
    
    // Show modal
    document.getElementById('orderDetailsModal').style.display = 'block';
    document.body.style.overflow = 'hidden'; // Prevent background scrolling
}

function closeOrderModal() {
    document.getElementById('orderDetailsModal').style.display = 'none';
    document.body.style.overflow = 'auto'; // Restore scrolling
}

// Print Invoice Function
function printInvoice() {
    const order = currentOrderDetails;
    
    // Get current date and time
    const now = new Date();
    const dateTime = now.toLocaleString('en-US', { 
        year: 'numeric', 
        month: 'long', 
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
        hour12: true
    });
    
    // Create a hidden iframe for printing
    let printFrame = document.getElementById('print-invoice-frame');
    if (!printFrame) {
        printFrame = document.createElement('iframe');
        printFrame.id = 'print-invoice-frame';
        printFrame.style.position = 'absolute';
        printFrame.style.width = '0';
        printFrame.style.height = '0';
        printFrame.style.border = 'none';
        document.body.appendChild(printFrame);
    }
    
    // Generate invoice HTML
    const invoiceHTML = `
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Invoice #${order.orderId}</title>
            <style>
                * {
                    margin: 0;
                    padding: 0;
                    box-sizing: border-box;
                }
                
                body {
                    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
                    padding: 15px;
                    color: #212529;
                    line-height: 1.4;
                    background: #f5f5f5;
                }
                
                .invoice-container {
                    max-width: 900px;
                    margin: 0 auto;
                    background: #fff;
                    box-shadow: 0 2px 12px rgba(0,0,0,0.08);
                    position: relative;
                    border: 2px dashed #999;
                    border-radius: 4px;
                    padding: 10px;
                }
                
                /* Corner marks for cutting guide */
                .invoice-container::before,
                .invoice-container::after {
                    content: '';
                    position: absolute;
                    width: 20px;
                    height: 20px;
                    border: 2px solid #999;
                }
                
                .invoice-container::before {
                    top: -2px;
                    left: -2px;
                    border-right: none;
                    border-bottom: none;
                }
                
                .invoice-container::after {
                    top: -2px;
                    right: -2px;
                    border-left: none;
                    border-bottom: none;
                }
               
                
                /* Parcel slip label */
                .parcel-label {
                    position: absolute;
                    top: 5px;
                    right: 5px;
                    background: #d4af37;
                    color: #2c3e50;
                    padding: 4px 12px;
                    border-radius: 3px;
                    font-size: 10px;
                    font-weight: 700;
                    letter-spacing: 1px;
                    text-transform: uppercase;
                    box-shadow: 0 2px 4px rgba(0,0,0,0.2);
                }
                
                /* Header Section - Lazada/Shopee Style */
                .invoice-header {
                    background: linear-gradient(135deg, #2c3e50 0%, #34495e 100%);
                    padding: 20px 30px;
                    display: flex;
                    justify-content: space-between;
                    align-items: center;
                    border-bottom: 3px solid #d4af37;
                }
                
                .header-left {
                    flex: 1;
                }
                
                .company-name {
                    font-size: 26px;
                    font-weight: 800;
                    color: #d4af37;
                    letter-spacing: 1px;
                    margin-bottom: 3px;
                    text-shadow: 2px 2px 4px rgba(0,0,0,0.3);
                }
                
                .company-tagline {
                    font-size: 11px;
                    color: rgba(255,255,255,0.8);
                    font-weight: 400;
                }
                
                .header-right {
                    text-align: right;
                }
                
                .invoice-title {
                    font-size: 22px;
                    font-weight: 700;
                    color: #fff;
                    margin-bottom: 3px;
                }
                
                .invoice-number {
                    font-size: 13px;
                    color: #d4af37;
                    font-weight: 600;
                    background: rgba(212, 175, 55, 0.2);
                    padding: 4px 12px;
                    border-radius: 20px;
                    display: inline-block;
                }
                
                /* Status Badge */
                .status-badge {
                    display: inline-block;
                    padding: 6px 16px;
                    border-radius: 20px;
                    font-size: 12px;
                    font-weight: 600;
                    text-transform: uppercase;
                    margin-top: 8px;
                }
                
                .status-pending { background: #fff3cd; color: #856404; }
                .status-confirmed { background: #d1ecf1; color: #0c5460; }
                .status-shipped { background: #cce5ff; color: #004085; }
                .status-delivered { background: #d4edda; color: #155724; }
                
                /* Invoice Body */
                .invoice-body {
                    padding: 20px 30px;
                }
                
                /* Info Cards - Shopee Style */
                .info-cards {
                    display: grid;
                    grid-template-columns: repeat(2, 1fr);
                    gap: 15px;
                    margin-bottom: 20px;
                }
                
                .info-card {
                    background: #fafafa;
                    border: 1px solid #e8e8e8;
                    border-radius: 6px;
                    padding: 15px;
                    position: relative;
                    overflow: hidden;
                }
                
                .info-card::before {
                    content: '';
                    position: absolute;
                    top: 0;
                    left: 0;
                    width: 4px;
                    height: 100%;
                    background: linear-gradient(180deg, #d4af37 0%, #f4d03f 100%);
                }
                
                .info-card-title {
                    font-size: 11px;
                    font-weight: 700;
                    color: #2c3e50;
                    text-transform: uppercase;
                    letter-spacing: 0.5px;
                    margin-bottom: 10px;
                    padding-bottom: 8px;
                    border-bottom: 1px solid #e0e0e0;
                }
                
                .info-row {
                    display: flex;
                    margin: 7px 0;
                    font-size: 12px;
                }
                
                .info-label {
                    min-width: 100px;
                    color: #666;
                    font-weight: 500;
                }
                
                .info-value {
                    flex: 1;
                    color: #212529;
                    font-weight: 400;
                    word-break: break-word;
                }
                
                /* Section Divider */
                .section-divider {
                    height: 1px;
                    background: linear-gradient(90deg, transparent, #e0e0e0, transparent);
                    margin: 15px 0;
                }
                
                .section-header {
                    font-size: 14px;
                    font-weight: 700;
                    color: #2c3e50;
                    margin: 15px 0 10px 0;
                    padding-left: 10px;
                    border-left: 3px solid #d4af37;
                }
                
                /* Product Table - E-commerce Style */
                .product-table {
                    width: 100%;
                    border-collapse: collapse;
                    margin: 10px 0;
                    border: 1px solid #e8e8e8;
                    border-radius: 6px;
                    overflow: hidden;
                }
                
                .product-table thead {
                    background: #fafafa;
                }
                
                .product-table th {
                    padding: 10px 12px;
                    text-align: left;
                    font-size: 11px;
                    font-weight: 700;
                    color: #2c3e50;
                    text-transform: uppercase;
                    letter-spacing: 0.5px;
                    border-bottom: 2px solid #e0e0e0;
                }
                
                .product-table td {
                    padding: 10px 12px;
                    font-size: 12px;
                    color: #555;
                    border-bottom: 1px solid #f0f0f0;
                }
                
                .product-table tbody tr:last-child td {
                    border-bottom: none;
                }
                
                /* Pricing Summary - Lazada Style */
                .pricing-summary {
                    max-width: 380px;
                    margin-left: auto;
                    margin-top: 15px;
                    border: 1px solid #e8e8e8;
                    border-radius: 6px;
                    overflow: hidden;
                }
                
                .pricing-row {
                    display: flex;
                    justify-content: space-between;
                    padding: 8px 15px;
                    font-size: 12px;
                    border-bottom: 1px solid #f0f0f0;
                }
                
                .pricing-row:last-child {
                    border-bottom: none;
                }
                
                .pricing-label {
                    color: #666;
                    font-weight: 500;
                }
                
                .pricing-value {
                    color: #212529;
                    font-weight: 600;
                }
                
                .pricing-row.discount .pricing-value {
                    color: #ff6b6b;
                }
                
                .pricing-row.subtotal {
                    background: #fafafa;
                    font-weight: 600;
                }
                
                .pricing-row.total {
                    background: linear-gradient(135deg, #2c3e50 0%, #34495e 100%);
                    color: #fff;
                    font-size: 14px;
                    font-weight: 700;
                    padding: 12px 15px;
                }
                
                .pricing-row.total .pricing-label,
                .pricing-row.total .pricing-value {
                    color: #fff;
                }
                
                .pricing-row.total .pricing-value {
                    color: #d4af37;
                    font-size: 16px;
                }
                
                /* Seller Info Section */
                .seller-section {
                    display: grid;
                    grid-template-columns: 1fr 1fr;
                    gap: 15px;
                    margin-top: 20px;
                    padding-top: 15px;
                    border-top: 2px dashed #e0e0e0;
                }
                
                .seller-info-box {
                    background: #fafafa;
                    border: 1px solid #e8e8e8;
                    border-radius: 6px;
                    padding: 15px;
                }
                
                .seller-info-box .info-card-title {
                    margin-bottom: 10px;
                }
                
                .signature-area {
                    text-align: center;
                    padding: 15px;
                }
                
                .signature-line {
                    border-top: 2px solid #2c3e50;
                    width: 180px;
                    margin: 40px auto 10px auto;
                }
                
                .signature-label {
                    font-size: 10px;
                    color: #666;
                    font-weight: 600;
                    text-transform: uppercase;
                    letter-spacing: 0.5px;
                }
                
                /* Footer */
                .invoice-footer {
                    background: #2c3e50;
                    color: #fff;
                    padding: 15px 30px;
                    text-align: center;
                    margin-top: 20px;
                }
                
                .footer-note {
                    font-size: 12px;
                    font-weight: 600;
                    margin-bottom: 5px;
                    color: #d4af37;
                }
                
                .footer-text {
                    font-size: 10px;
                    color: rgba(255,255,255,0.8);
                    margin: 3px 0;
                }
                
                .footer-contact {
                    font-size: 9px;
                    color: rgba(255,255,255,0.6);
                    margin-top: 8px;
                    padding-top: 8px;
                    border-top: 1px solid rgba(255,255,255,0.1);
                }
                
                /* Print Styles */
                @media print {
                    @page {
                        size: A4;
                        margin: 10mm;
                    }
                    
                    body {
                        padding: 0;
                        background: #fff;
                        margin: 0;
                    }
                    
                    .invoice-container {
                        box-shadow: none;
                        max-width: 100%;
                        margin: 0;
                        border: 3px dashed #333;
                        border-radius: 0;
                        padding: 8px;
                    }
                    
                    .invoice-container::before,
                    .invoice-container::after {
                        border-color: #333;
                        border-width: 3px;
                    }
                    
                    .cut-line {
                        border-top: 3px dashed #333;
                        margin: 15px -8px;
                    }
                    
                    .cut-line::before {
                        color: #000;
                        font-size: 24px;
                        left: 8px;
                    }
                    
                    .cut-line::after {
                        color: #000;
                        font-size: 11px;
                        font-weight: 700;
                    }
                    
                    .parcel-label {
                        background: #d4af37;
                        color: #000;
                        font-weight: 800;
                    }
                    
                    .invoice-header {
                        padding: 15px 20px;
                    }
                    
                    .invoice-body {
                        padding: 15px 20px;
                    }
                    
                    .invoice-footer {
                        padding: 12px 20px;
                        margin-top: 15px;
                    }
                    
                    .info-cards {
                        margin-bottom: 15px;
                        gap: 10px;
                    }
                    
                    .info-card {
                        padding: 12px;
                    }
                    
                    .section-divider {
                        margin: 10px 0;
                    }
                    
                    .section-header {
                        margin: 10px 0 8px 0;
                    }
                    
                    .product-table {
                        margin: 8px 0;
                    }
                    
                    .pricing-summary {
                        margin-top: 10px;
                    }
                    
                    .seller-section {
                        margin-top: 15px;
                        padding-top: 12px;
                        gap: 10px;
                    }
                    
                    .signature-line {
                        margin: 30px auto 8px auto;
                    }
                    
                    .info-card,
                    .product-table,
                    .pricing-summary,
                    .seller-info-box {
                        break-inside: avoid;
                        page-break-inside: avoid;
                    }
                    
                    /* Reduce font sizes for print */
                    .company-name {
                        font-size: 22px;
                    }
                    
                    .invoice-title {
                        font-size: 18px;
                    }
                    
                    .info-row {
                        margin: 5px 0;
                        font-size: 11px;
                    }
                    
                    .product-table th,
                    .product-table td {
                        padding: 8px 10px;
                        font-size: 11px;
                    }
                    
                    .pricing-row {
                        padding: 6px 12px;
                        font-size: 11px;
                    }
                    
                    .pricing-row.total {
                        padding: 10px 12px;
                        font-size: 13px;
                    }
                    
                    .pricing-row.total .pricing-value {
                        font-size: 15px;
                    }
                }
            </style>
        </head>
        <body>
            <div class="invoice-container">                
                <!-- Header -->
                <div class="invoice-header">
                    <div class="header-left">
                        <div class="company-name">MSTYLE</div>
                        <div class="company-tagline">Your Fashion E-Commerce Platform</div>
                    </div>
                    <div class="header-right">
                        <div class="invoice-title">INVOICE</div>
                        <div class="invoice-number">#${order.orderId}</div>
                    </div>
                </div>
                
                <!-- Body -->
                <div class="invoice-body">
                    <!-- Info Cards -->
                    <div class="info-cards">
                        <div class="info-card">
                            <div class="info-card-title">Buyer Information</div>
                            <div class="info-row">
                                <div class="info-label">Name:</div>
                                <div class="info-value">${order.customerName}</div>
                            </div>
                            <div class="info-row">
                                <div class="info-label">Phone:</div>
                                <div class="info-value">${order.customerPhone || 'Not provided'}</div>
                            </div>
                            <div class="info-row">
                                <div class="info-label">Address:</div>
                                <div class="info-value">${order.customerAddress || 'No address provided'}</div>
                            </div>
                        </div>
                        
                        <div class="info-card">
                            <div class="info-card-title">Order Details</div>
                            <div class="info-row">
                                <div class="info-label">Order ID:</div>
                                <div class="info-value">#${order.orderId}</div>
                            </div>
                            <div class="info-row">
                                <div class="info-label">Date & Time:</div>
                                <div class="info-value">${dateTime}</div>
                            </div>
                            <div class="info-row">
                                <div class="info-label">Payment:</div>
                                <div class="info-value">Cash on Delivery</div>
                            </div>
                            <div class="info-row">
                                <div class="info-label">Status:</div>
                                <div class="info-value">
                                    <span class="status-badge status-${order.orderStatus.toLowerCase().replace(/\s+/g, '-')}">${order.orderStatus}</span>
                                </div>
                            </div>
                        </div>
                    </div>
                    
               
                    <!-- Product Details -->
                    <div class="section-header">Product Details</div>
                    <table class="product-table">
                        <thead>
                            <tr>
                                <th>Product Name</th>
                                <th>Variation</th>
                                <th>Size</th>
                                <th style="text-align: center;">Qty</th>
                                <th style="text-align: right;">Unit Price</th>
                            </tr>
                        </thead>
                        <tbody>
                            <tr>
                                <td><strong>${order.productName}</strong></td>
                                <td>${order.productVariation || 'Standard'}</td>
                                <td>${order.productSize || 'One Size'}</td>
                                <td style="text-align: center;">${order.quantity}</td>
                                <td style="text-align: right;">₱${parseFloat(order.totalPrice).toFixed(2)}</td>
                            </tr>
                        </tbody>
                    </table>
                    
                    <!-- Pricing Summary -->
                    <div class="pricing-summary">
                        <div class="pricing-row">
                            <div class="pricing-label">Merchandise Subtotal:</div>
                            <div class="pricing-value">₱${order.itemSubtotal.toFixed(2)}</div>
                        </div>
                        ${order.promotionText !== 'No Promotion' ? `
                        <div class="pricing-row discount">
                            <div class="pricing-label">Discount (${order.promotionText}):</div>
                            <div class="pricing-value">-${order.discountText}</div>
                        </div>
                        ` : ''}
                        <div class="pricing-row">
                            <div class="pricing-label">Shipping Fee:</div>
                            <div class="pricing-value">₱${order.shippingFee.toFixed(2)}</div>
                        </div>
                        <div class="pricing-row total">
                            <div class="pricing-label">Total Payment:</div>
                            <div class="pricing-value">₱${order.finalTotal.toFixed(2)}</div>
                        </div>
                    </div>
                    
                    <!-- Seller Information -->
                    <div class="seller-section">
                        <div class="seller-info-box">
                            <div class="info-card-title">Seller Information</div>
                            <div class="info-row">
                                <div class="info-label">Business:</div>
                                <div class="info-value">${order.sellerBusinessName || 'MSTYLE Seller'}</div>
                            </div>
                            <div class="info-row">
                                <div class="info-label">Phone:</div>
                                <div class="info-value">${order.sellerPhone || '+63 XXX XXX XXXX'}</div>
                            </div>
                            <div class="info-row">
                                <div class="info-label">Address:</div>
                                <div class="info-value">${order.sellerAddress || 'Philippines'}</div>
                            </div>
                        </div>
                        
                        <div class="signature-area">
                            <div class="signature-line"></div>
                            <div class="signature-label">Authorized Signature</div>
                        </div>
                    </div>
                </div>
                
                <!-- Footer -->
                <div class="invoice-footer">
                    <div class="footer-note">Thank you for shopping with MSTYLE!</div>
                    <div class="footer-text">This is a computer-generated invoice and does not require a physical signature.</div>
                    <div class="footer-text">For any inquiries regarding this order, please contact the seller directly.</div>
                    <div class="footer-contact">
                        MSTYLE E-Commerce Platform | Email: support@mstyle.com | Website: www.mstyle.com
                    </div>
                </div>
            </div>
            
        </body>
        </html>
    `;
    
    // Write the HTML to the iframe
    const frameDoc = printFrame.contentWindow || printFrame.contentDocument;
    if (frameDoc.document) {
        frameDoc.document.open();
        frameDoc.document.write(invoiceHTML);
        frameDoc.document.close();
    } else {
        frameDoc.open();
        frameDoc.write(invoiceHTML);
        frameDoc.close();
    }
    
    // Wait for content to load then print
    setTimeout(() => {
        try {
            printFrame.contentWindow.focus();
            printFrame.contentWindow.print();
        } catch (e) {
            console.error('Print error:', e);
            // Fallback: try direct print
            window.print();
        }
    }, 500);
}

// Toast Notification System
function showToast(message, type = 'success', duration = 5000) {
    const toastContainer = document.getElementById('toast-container');
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;

    // Set icon based on type
    let icon = '';
    switch (type) {
        case 'success':
            icon = '<i class="bi bi-check-circle-fill"></i>';
            break;
        case 'error':
            icon = '<i class="bi bi-x-circle-fill"></i>';
            break;
        case 'warning':
            icon = '<i class="bi bi-exclamation-triangle-fill"></i>';
            break;
        case 'info':
            icon = '<i class="bi bi-info-circle-fill"></i>';
            break;
        default:
            icon = '<i class="bi bi-check-circle-fill"></i>';
    }

    toast.innerHTML = `
        <div class="toast-content">
            ${icon}
            <span class="toast-message">${message}</span>
            <button class="toast-close" onclick="closeToast(this)">
                <i class="bi bi-x"></i>
            </button>
        </div>
    `;

    toastContainer.appendChild(toast);

    // Trigger animation
    setTimeout(() => {
        toast.classList.add('toast-show');
    }, 100);

    // Auto remove after duration
    setTimeout(() => {
        closeToast(toast.querySelector('.toast-close'));
    }, duration);
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

// Search and Filter Functionality
function initializeSearchAndFilter() {
    const searchInput = document.getElementById('searchInput');
    const clearSearch = document.getElementById('clearSearch');
    const statusFilter = document.getElementById('statusFilter');
    const resetFilters = document.getElementById('resetFilters');
    const sortBy = document.getElementById('sortBy');

    let allRows = Array.from(document.querySelectorAll('tbody tr'));
    let filteredRows = [...allRows];

    // Search functionality
    searchInput.addEventListener('input', function () {
        const searchTerm = this.value.toLowerCase().trim();

        if (searchTerm) {
            clearSearch.style.display = 'block';
            searchInput.classList.add('active');
        } else {
            clearSearch.style.display = 'none';
            searchInput.classList.remove('active');
        }

        applyFilters();
    });

    clearSearch.addEventListener('click', function () {
        searchInput.value = '';
        clearSearch.style.display = 'none';
        searchInput.classList.remove('active');
        applyFilters();
    });

    // Filter functionality
    statusFilter.addEventListener('change', function () {
        if (this.value) {
            this.classList.add('active');
        } else {
            this.classList.remove('active');
        }
        applyFilters();
    });

    // Sort functionality
    sortBy.addEventListener('change', function () {
        applySorting();
        updateDisplay();
    });

    // Reset filters (only if button exists)
    if (resetFilters) {
        resetFilters.addEventListener('click', function () {
            searchInput.value = '';
            statusFilter.value = '';
            sortBy.value = 'date-desc';

            clearSearch.style.display = 'none';

            // Remove active classes
            document.querySelectorAll('.active').forEach(el => el.classList.remove('active'));

            applyFilters();
        });
    }

    function applyFilters() {
        const searchTerm = searchInput.value.toLowerCase().trim();
        const selectedStatus = statusFilter.value.toLowerCase();

        filteredRows = allRows.filter(row => {
            // Skip empty state row
            if (row.querySelector('.empty-message')) return false;

            // Search filter
            if (searchTerm) {
                const customerName = row.querySelector('.customer-name')?.textContent.toLowerCase() || '';
                const customerEmail = row.querySelector('.customer-email')?.textContent.toLowerCase() || '';
                const productName = row.querySelector('.product-name')?.textContent.toLowerCase() || '';

                const matchesSearch = customerName.includes(searchTerm) ||
                    customerEmail.includes(searchTerm) ||
                    productName.includes(searchTerm);

                if (!matchesSearch) return false;
            }

            // Status filter
            if (selectedStatus) {
                const statusBadge = row.querySelector('.status-badge');
                if (statusBadge) {
                    const rowStatus = statusBadge.textContent.toLowerCase().trim();
                    if (rowStatus !== selectedStatus) return false;
                }
            }

            return true;
        });

        applySorting();
        updateDisplay();
    }

    function applySorting() {
        const sortValue = sortBy.value;

        filteredRows.sort((a, b) => {
            switch (sortValue) {
                case 'date-desc':
                    const dateA = new Date(a.querySelector('.order-date .date')?.textContent || '');
                    const dateB = new Date(b.querySelector('.order-date .date')?.textContent || '');
                    return dateB - dateA;

                case 'date-asc':
                    const dateA2 = new Date(a.querySelector('.order-date .date')?.textContent || '');
                    const dateB2 = new Date(b.querySelector('.order-date .date')?.textContent || '');
                    return dateA2 - dateB2;

                case 'customer-asc':
                    const customerA = a.querySelector('.customer-name')?.textContent || '';
                    const customerB = b.querySelector('.customer-name')?.textContent || '';
                    return customerA.localeCompare(customerB);

                case 'customer-desc':
                    const customerA2 = a.querySelector('.customer-name')?.textContent || '';
                    const customerB2 = b.querySelector('.customer-name')?.textContent || '';
                    return customerB2.localeCompare(customerA2);

                case 'status-asc':
                    const statusA = a.querySelector('.status-badge')?.textContent || '';
                    const statusB = b.querySelector('.status-badge')?.textContent || '';
                    return statusA.localeCompare(statusB);

                case 'original-price-desc':
                    const origPriceA = parseFloat(a.cells[6]?.textContent.replace('₱', '').replace(/[^\d.-]/g, '') || '0');
                    const origPriceB = parseFloat(b.cells[6]?.textContent.replace('₱', '').replace(/[^\d.-]/g, '') || '0');
                    return origPriceB - origPriceA;

                case 'original-price-asc':
                    const origPriceA2 = parseFloat(a.cells[6]?.textContent.replace('₱', '').replace(/[^\d.-]/g, '') || '0');
                    const origPriceB2 = parseFloat(b.cells[6]?.textContent.replace('₱', '').replace(/[^\d.-]/g, '') || '0');
                    return origPriceA2 - origPriceB2;

                case 'promotion-asc':
                    const promoA = a.cells[7]?.textContent.trim() || 'No Promotion';
                    const promoB = b.cells[7]?.textContent.trim() || 'No Promotion';
                    return promoA.localeCompare(promoB);

                case 'price-desc':
                    const priceA = parseFloat(a.cells[8]?.textContent.replace('₱', '').replace(/[^\d.-]/g, '') || '0');
                    const priceB = parseFloat(b.cells[8]?.textContent.replace('₱', '').replace(/[^\d.-]/g, '') || '0');
                    return priceB - priceA;

                case 'price-asc':
                    const priceA2 = parseFloat(a.cells[8]?.textContent.replace('₱', '').replace(/[^\d.-]/g, '') || '0');
                    const priceB2 = parseFloat(b.cells[8]?.textContent.replace('₱', '').replace(/[^\d.-]/g, '') || '0');
                    return priceA2 - priceB2;

                default:
                    return 0;
            }
        });
    }

    function updateDisplay() {
        const tbody = document.querySelector('tbody');

        // Clear current rows
        tbody.innerHTML = '';

        if (filteredRows.length === 0) {
            // Show no results message
            const noResultsRow = document.createElement('tr');
            noResultsRow.innerHTML = `
                <td colspan="12" class="empty-message">
                    <div class="no-results-message">
                        <i class="bi bi-search"></i>
                        <h3>No Orders Found</h3>
                        <p>No orders match your current search and filter criteria. Try adjusting your filters or search terms.</p>
                    </div>
                </td>
            `;
            tbody.appendChild(noResultsRow);
        } else {
            // Show filtered rows with updated sequence numbers
            filteredRows.forEach((row, index) => {
                const sequenceBadge = row.querySelector('.sequence-badge');
                if (sequenceBadge) {
                    sequenceBadge.textContent = index + 1;
                }
                tbody.appendChild(row);
            });
        }
    }

    // Initialize display
    applySorting();
    updateDisplay();
}

// Event Listeners
document.addEventListener('DOMContentLoaded', function () {
    console.log('DOMContentLoaded - checking for status update...');
    
    // Check for recent status update first
    const statusUpdateInfo = sessionStorage.getItem('statusUpdateInfo');
    console.log('statusUpdateInfo from sessionStorage:', statusUpdateInfo);
    
    if (statusUpdateInfo) {
        const info = JSON.parse(statusUpdateInfo);
        console.log('Parsed info:', info);
        console.log('Time difference:', Date.now() - info.timestamp);
        
        // Only show if the update was recent (within last 5 seconds)
        if (Date.now() - info.timestamp < 5000) {
            console.log('Status update is recent, showing success modal...');
            // Show success modal instead of toast for status updates
            setTimeout(() => {
                showSuccessModal(info.status, info.customer);
            }, 500);
            // Clear the stored info
            sessionStorage.removeItem('statusUpdateInfo');
            // Don't show flash messages as toasts when showing success modal
            return;
        }
        console.log('Status update is too old, clearing...');
        // Clear the stored info if it's too old
        sessionStorage.removeItem('statusUpdateInfo');
    }
    
    console.log('No recent status update, showing flash messages as toasts...');
    // Show flash messages as toasts only if not showing success modal
    const flashMessages = document.querySelectorAll('#flash-messages .flash-message');
    flashMessages.forEach(function (message) {
        const category = message.getAttribute('data-category');
        const text = message.textContent;
        showToast(text, category, 6000);
    });
    
    // Initialize search and filter functionality
    initializeSearchAndFilter();
});

// Close modal when clicking outside of it
window.onclick = function(event) {
    const orderModal = document.getElementById('orderDetailsModal');
    const successModal = document.getElementById('successModal');
    
    if (event.target === orderModal) {
        closeOrderModal();
    }
    
    if (event.target === successModal) {
        closeSuccessModal();
    }
}

// Close modal with Escape key
document.addEventListener('keydown', function(event) {
    if (event.key === 'Escape') {
        const orderModal = document.getElementById('orderDetailsModal');
        const successModal = document.getElementById('successModal');
        
        if (orderModal.style.display === 'block') {
            closeOrderModal();
        }
        
        if (successModal.classList.contains('show')) {
            closeSuccessModal();
        }
    }
});

// Visual feedback for successful updates
function showUpdateSuccess(message) {
    const notification = document.createElement('div');
    notification.className = 'update-notification success';
    notification.innerHTML = `
        <i class="bi bi-check-circle-fill"></i>
        <span>${message}</span>
    `;
    notification.style.cssText = `
        position: fixed;
        top: 20px;
        right: 20px;
        background: #d4edda;
        color: #155724;
        padding: 15px 20px;
        border-radius: 8px;
        border: 1px solid #c3e6cb;
        box-shadow: 0 4px 12px rgba(0,0,0,0.15);
        z-index: 1000;
        animation: slideInRight 0.3s ease-out;
    `;

    document.body.appendChild(notification);

    setTimeout(() => {
        notification.style.opacity = '0';
        setTimeout(() => notification.remove(), 300);
    }, 4000);
}

// Contact Buyer Function
function contactBuyer() {
    const order = currentOrderDetails;
    
    if (!order || !order.customerEmail) {
        showToast('Unable to contact buyer. Customer information not available.', 'error');
        return;
    }
    
    // Close the order details modal
    closeOrderModal();
    
    // Open seller-buyer chat modal with product_id
    openSellerBuyerChatModal(
        order.customerEmail,
        order.customerName,
        order.orderId,
        order.productName,
        order.productId
    );
}

// Contact Rider Function
function contactRider() {
    const order = currentOrderDetails;
    
    if (!order || !order.riderEmail) {
        showToast('Unable to contact rider. Rider information not available.', 'error');
        return;
    }
    
    // Close the order details modal
    closeOrderModal();
    
    // Open seller-rider chat modal
    openSellerRiderChatModal(
        order.riderEmail,
        order.riderName,
        order.orderId,
        order.productName
    );
}


// ── Auto-sync: poll order statuses every 20 seconds ──────────────────────────
(function initSellerOrderPolling() {
  // Map of status → badge CSS class (mirrors the template's status classes)
  const statusClassMap = {
    'pending':           'status-pending',
    'confirmed':         'status-confirmed',
    'preparing':         'status-preparing',
    'waiting for pickup':'status-waiting-for-pickup',
    'for pickup':        'status-for-pickup',
    'heading to seller': 'status-heading-to-seller',
    'shipped':           'status-shipped',
    'in transit':        'status-in-transit',
    'out for delivery':  'status-out-for-delivery',
    'delivered':         'status-delivered',
    'completed':         'status-completed',
    'rejected':          'status-rejected',
    'cancelled':         'status-cancelled',
  };

  // Track last-known statuses so we only update DOM on actual changes
  const knownStatuses = {};

  // Initialise from current DOM
  document.querySelectorAll('tr[data-order-id], .order-card[data-order-id]').forEach(el => {
    const id = el.dataset.orderId;
    const status = el.dataset.status;
    if (id && status) knownStatuses[id] = status.toLowerCase();
  });

  async function pollSellerStatuses() {
    try {
      const resp = await fetch('/api/orders/seller-statuses', { credentials: 'same-origin' });
      if (!resp.ok) return;
      const data = await resp.json();
      if (!data.success || !Array.isArray(data.orders)) return;

      let anyChanged = false;
      data.orders.forEach(({ id, status }) => {
        const sid = String(id);
        if (knownStatuses[sid] && knownStatuses[sid].toLowerCase() !== status.toLowerCase()) {
          anyChanged = true;
        }
        knownStatuses[sid] = status;
      });

      // If any status changed, reload the page so the full order card re-renders
      // (avoids complex DOM surgery for action buttons, status chips, etc.)
      if (anyChanged) {
        console.log('🔄 Order status changed — reloading order list');
        window.location.reload();
      }
    } catch (e) {
      // Silent fail — polling is best-effort
    }
  }

  // Start polling after a short delay so the page finishes loading first
  setTimeout(() => {
    pollSellerStatuses();
    setInterval(pollSellerStatuses, 20000); // every 20 s
  }, 3000);
})();
