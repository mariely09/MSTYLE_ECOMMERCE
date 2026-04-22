# build_view_product.py
# Reads the saved JS block and writes the new view_product.html

with open('temp_js_block.txt', 'r', encoding='utf-8-sig') as f:
    js_block = f.read().strip()

html = open('mstyle_website/templates/view_product.html', 'w', encoding='utf-8')

def w(s):
    html.write(s)


# Write the HTML
w("""<!DOCTYPE html>
<html lang="en">

<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{ product.name }}</title>
    <link rel="stylesheet" href="{{ url_for('static', filename='css/homepage.css') }}">
    <link rel="stylesheet" href="{{ url_for('static', filename='css/homepg_header.css') }}">
    <link rel="stylesheet" href="{{ url_for('static', filename='css/view_product.css') }}">
    <link rel="stylesheet" href="{{ url_for('static', filename='css/reviews_rating.css') }}">
    <link rel="stylesheet" href="{{ url_for('static', filename='css/success_message_cartmodal.css') }}">
    <link rel="stylesheet" href="{{ url_for('static', filename='css/success_message_wishlistmodal.css') }}">
    <link rel="stylesheet" href="{{ url_for('static', filename='css/buyer_seller_chat.css') }}">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/5.15.4/css/all.min.css">
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.2/font/bootstrap-icons.min.css">
    <script src="{{ url_for('static', filename='js/logout.js') }}"></script>
""")

w("""    <style>
        /*  Design tokens ─────────────────────────────────────────── */
        :root {
            --primary:    #1a1a1a;
            --accent:     #2c3e50;
            --gold:       #d4af37;
            --gold-light: #f4d03f;
            --text-light: #6c757d;
            --bg:         #f8f9fa;
            --border:     #e9ecef;
            --premium-grad: linear-gradient(135deg, #1a1a1a, #2c3e50);
            --gold-grad:    linear-gradient(135deg, #d4af37, #f4d03f);
            --card-shadow:  0 2px 12px rgba(0,0,0,0.07);
        }
        body { background: var(--bg); }

        /*  Premium app-bar  */
        .vp-appbar {
            background: var(--premium-grad);
            padding: 14px 20px;
            display: flex;
            align-items: center;
            justify-content: space-between;
            position: sticky;
            top: 0;
            z-index: 100;
            box-shadow: 0 2px 12px rgba(0,0,0,0.25);
        }
        .vp-appbar-back {
            display: inline-flex;
            align-items: center;
            gap: 6px;
            background: rgba(255,255,255,0.12);
            color: #fff;
            text-decoration: none;
            border-radius: 50px;
            padding: 6px 14px;
            font-size: 13px;
            font-weight: 600;
            transition: background 0.2s;
        }
        .vp-appbar-back:hover { background: rgba(255,255,255,0.22); color: #fff; }
        .vp-appbar-title {
            color: #fff;
            font-size: 16px;
            font-weight: 700;
            flex: 1;
            text-align: center;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
            margin: 0 12px;
        }
        .vp-appbar-wish {
            background: none;
            border: none;
            color: #fff;
            font-size: 22px;
            cursor: pointer;
            padding: 4px 8px;
            transition: transform 0.15s;
        }
        .vp-appbar-wish:hover { transform: scale(1.15); }
        .vp-appbar-wish .fas { color: #dc3545; }

        /*  Page wrapper  */
        .vp-page { max-width: 1200px; margin: 0 auto; padding: 0 0 100px; }

        /*  Two-column layout  */
        .vp-layout {
            display: flex;
            flex-direction: row;
            gap: 0;
            align-items: flex-start;
        }

        /*  Image column  */
        .vp-image-col {
            position: sticky;
            top: 60px;
            width: 50%;
            flex-shrink: 0;
        }
        .vp-image-wrap {
            position: relative;
            width: 100%;
            aspect-ratio: 1 / 1;
            background: #fff;
            overflow: hidden;
        }
        .vp-image-wrap .product-image {
            width: 100%;
            height: 100%;
            position: relative;
        }
        .vp-image-wrap .product-img {
            width: 100%;
            height: 100%;
            object-fit: cover;
            display: none;
        }
        .vp-image-wrap .product-img.active { display: block; }
        .vp-image-wrap .product-image-slider {
            width: 100%;
            height: 100%;
            position: relative;
        }
        .vp-image-wrap .product-image-placeholder {
            width: 100%;
            height: 100%;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            color: var(--text-light);
            font-size: 48px;
        }
        /* Wishlist overlay button */
        .vp-wish-overlay {
            position: absolute;
            top: 14px;
            right: 14px;
            z-index: 10;
            background: rgba(255,255,255,0.9);
            border: none;
            border-radius: 50%;
            width: 42px;
            height: 42px;
            display: flex;
            align-items: center;
            justify-content: center;
            cursor: pointer;
            box-shadow: 0 2px 8px rgba(0,0,0,0.15);
            transition: transform 0.15s, box-shadow 0.15s;
            font-size: 18px;
            color: #dc3545;
        }
        .vp-wish-overlay:hover { transform: scale(1.1); box-shadow: 0 4px 14px rgba(0,0,0,0.2); }

        /*  Info column  */
        .vp-info-col {
            width: 50%;
            padding: 20px 24px 20px 20px;
            display: flex;
            flex-direction: column;
            gap: 14px;
        }

        /*  White cards  */
        .vp-card {
            background: #fff;
            border-radius: 16px;
            padding: 18px 20px;
            box-shadow: var(--card-shadow);
        }
        .vp-card-label {
            font-size: 12px;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.8px;
            color: var(--text-light);
            margin-bottom: 10px;
        }

        /*  Product name + price card  */
        .vp-product-name {
            font-size: 20px;
            font-weight: 800;
            color: var(--primary);
            margin: 0 0 8px;
            line-height: 1.3;
        }
        .vp-price-row { display: flex; align-items: baseline; gap: 10px; flex-wrap: wrap; margin-bottom: 8px; }
        .vp-price-main {
            font-size: 26px;
            font-weight: 900;
            background: var(--gold-grad);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
        }
        .vp-price-original { font-size: 14px; color: var(--text-light); text-decoration: line-through; }
        .vp-discount-badge {
            background: var(--gold-grad);
            color: #fff;
            font-size: 11px;
            font-weight: 700;
            padding: 2px 8px;
            border-radius: 20px;
        }
        .vp-savings { font-size: 12px; color: #2e7d32; font-weight: 600; }
        .vp-promo-tag {
            display: inline-flex;
            align-items: center;
            gap: 5px;
            background: rgba(212,175,55,0.1);
            border: 1px solid rgba(212,175,55,0.3);
            color: var(--gold);
            font-size: 11px;
            font-weight: 600;
            padding: 3px 10px;
            border-radius: 20px;
            margin-top: 4px;
        }
        .vp-rating-row { display: flex; align-items: center; gap: 6px; margin-bottom: 10px; }
        .vp-stars { color: var(--gold); font-size: 14px; }
        .vp-stars .far { color: #ddd; }
        .vp-review-count { font-size: 12px; color: var(--text-light); }
        .vp-description { font-size: 14px; color: #444; line-height: 1.6; margin: 0; }

        /*  Color swatches  */
        .vp-color-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; }
        .vp-selected-badge {
            font-size: 12px;
            font-weight: 600;
            color: var(--gold);
            background: rgba(212,175,55,0.1);
            padding: 2px 10px;
            border-radius: 20px;
        }
        .vp-card .color-options { display: flex; flex-wrap: wrap; gap: 10px; }
        .vp-card .color-option-container { position: relative; }
        .vp-card .color-option-container input[type="radio"] { display: none; }
        .vp-card .color-option {
            width: 64px;
            height: 64px;
            border-radius: 12px;
            overflow: hidden;
            border: 2px solid var(--border);
            cursor: pointer;
            position: relative;
            transition: border-color 0.2s, transform 0.15s;
        }
        .vp-card .color-option:hover { transform: scale(1.05); }
        .vp-card .color-option.selected {
            border: 2.5px solid var(--gold);
            box-shadow: 0 0 0 2px rgba(212,175,55,0.3);
        }
        .vp-card .color-option.selected::after {
            content: '\\f00c';
            font-family: 'Font Awesome 5 Free';
            font-weight: 900;
            position: absolute;
            bottom: 3px;
            right: 3px;
            background: var(--gold-grad);
            color: #fff;
            font-size: 9px;
            width: 16px;
            height: 16px;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            line-height: 16px;
            text-align: center;
        }
        .vp-card .color-option.out-of-stock { opacity: 0.4; cursor: not-allowed; }
        .vp-card .color-image { width: 100%; height: 100%; object-fit: cover; }
        .vp-card .color-fallback { width: 100%; height: 100%; display: flex; align-items: center; justify-content: center; }
        .vp-card .color-fallback-text { font-size: 9px; font-weight: 700; text-align: center; padding: 2px; }
        .vp-card .color-name-overlay {
            position: absolute;
            bottom: 0; left: 0; right: 0;
            background: rgba(0,0,0,0.45);
            color: #fff;
            font-size: 8px;
            font-weight: 600;
            text-align: center;
            padding: 2px 0;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }

        /*  Size pills  */
        .vp-card .size-options { display: flex; flex-wrap: wrap; gap: 8px; }
        .vp-card .size-option-container { position: relative; }
        .vp-card .size-option-container input[type="radio"] { display: none; }
        .vp-card .size-option {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            min-width: 48px;
            height: 40px;
            padding: 0 14px;
            border-radius: 50px;
            border: 1.5px solid var(--border);
            background: #fff;
            font-size: 13px;
            font-weight: 600;
            color: var(--primary);
            cursor: pointer;
            transition: all 0.2s;
            position: relative;
        }
        .vp-card .size-option:hover:not(.out-of-stock) { border-color: var(--gold); color: var(--gold); }
        .vp-card .size-option.selected {
            background: var(--gold-grad);
            border-color: transparent;
            color: #fff;
            box-shadow: 0 2px 8px rgba(212,175,55,0.35);
        }
        .vp-card .size-option.out-of-stock { opacity: 0.4; cursor: not-allowed; text-decoration: line-through; }
        .vp-card .size-option.out-of-stock::after {
            content: '\\00d7';
            position: absolute;
            top: -5px; right: -5px;
            background: #dc3545;
            color: #fff;
            font-size: 10px;
            font-weight: 900;
            width: 14px; height: 14px;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            line-height: 14px;
            text-align: center;
        }
        .vp-card .no-sizes { font-size: 13px; color: var(--text-light); margin: 0; }

        /*  Quantity card  */
        .vp-qty-row {
            display: flex;
            align-items: center;
            background: var(--bg);
            border-radius: 12px;
            border: 1.5px solid var(--border);
            overflow: hidden;
            width: fit-content;
        }
        .vp-qty-row .quantity-btn {
            width: 40px; height: 40px;
            border: none;
            background: transparent;
            font-size: 20px;
            cursor: pointer;
            color: var(--primary);
            transition: background 0.15s;
            display: flex;
            align-items: center;
            justify-content: center;
        }
        .vp-qty-row .quantity-btn:hover:not(:disabled) { background: rgba(212,175,55,0.1); }
        .vp-qty-row #quantity {
            width: 56px; height: 40px;
            text-align: center;
            font-size: 16px;
            font-weight: 800;
            border: none;
            border-left: 1.5px solid var(--border);
            border-right: 1.5px solid var(--border);
            background: #fff;
            outline: none;
            color: var(--primary);
            -moz-appearance: textfield;
        }
        .vp-qty-row #quantity::-webkit-inner-spin-button,
        .vp-qty-row #quantity::-webkit-outer-spin-button { -webkit-appearance: none; }
        .vp-stock-label { font-size: 12px; font-weight: 600; margin-top: 8px; }

        /*  Seller card  */
        .vp-seller-row { display: flex; align-items: center; gap: 14px; }
        .vp-seller-avatar {
            width: 52px; height: 52px;
            border-radius: 50%;
            background: var(--gold-grad);
            display: flex;
            align-items: center;
            justify-content: center;
            color: #fff;
            font-size: 22px;
            font-weight: 700;
            flex-shrink: 0;
            overflow: hidden;
        }
        .vp-seller-name { font-size: 15px; font-weight: 700; color: var(--primary); }
        .vp-seller-name a { color: inherit; text-decoration: none; }
        .vp-seller-name a:hover { color: var(--gold); }
        .vp-seller-actions { display: flex; gap: 8px; margin-top: 12px; flex-wrap: wrap; }
        .vp-btn-outline {
            display: inline-flex;
            align-items: center;
            gap: 6px;
            padding: 8px 16px;
            border-radius: 50px;
            border: 1.5px solid var(--primary);
            background: transparent;
            color: var(--primary);
            font-size: 13px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s;
        }
        .vp-btn-outline:hover { background: var(--primary); color: #fff; }

        /*  Reviews section  */
        .vp-reviews { max-width: 1200px; margin: 0 auto; padding: 0 24px 20px; }

        /*  Sticky bottom bar  */
        .vp-bottom-bar {
            position: fixed;
            bottom: 0; left: 0; right: 0;
            z-index: 200;
            background: #fff;
            border-top: 1px solid var(--border);
            padding: 12px 20px;
            display: flex;
            gap: 12px;
            box-shadow: 0 -4px 20px rgba(0,0,0,0.1);
        }
        .vp-btn-cart {
            flex: 1;
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 8px;
            padding: 14px;
            border-radius: 14px;
            border: 2px solid var(--primary);
            background: transparent;
            color: var(--primary);
            font-size: 14px;
            font-weight: 700;
            cursor: pointer;
            transition: all 0.2s;
        }
        .vp-btn-cart:hover { background: var(--primary); color: #fff; }
        .vp-btn-cart:disabled { border-color: #ccc; color: #ccc; cursor: not-allowed; }
        .vp-btn-buynow {
            flex: 1;
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 8px;
            padding: 14px;
            border-radius: 14px;
            border: none;
            background: var(--premium-grad);
            color: #fff;
            font-size: 14px;
            font-weight: 700;
            cursor: pointer;
            transition: opacity 0.2s, transform 0.15s;
            box-shadow: 0 4px 14px rgba(26,26,26,0.3);
        }
        .vp-btn-buynow:hover { opacity: 0.9; transform: translateY(-1px); }
        .vp-btn-buynow:disabled { background: #ccc; box-shadow: none; cursor: not-allowed; }

        /*  Responsive: mobile stacked  */
        @media (max-width: 768px) {
            .vp-layout { flex-direction: column; }
            .vp-image-col { width: 100%; position: static; }
            .vp-info-col { width: 100%; padding: 16px; }
            .vp-appbar-title { font-size: 14px; }
            .vp-reviews { padding: 0 16px 20px; }
        }

        /*  Hide old back-button (replaced by appbar)  */
        .back-button { display: none !important; }

        /*  Hide old .buttons div (replaced by sticky bar)  */
        .buttons { display: none !important; }
    </style>
</head>
""")
