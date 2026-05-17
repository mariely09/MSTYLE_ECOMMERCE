from flask import Flask, render_template, request, redirect, url_for, flash, session
from flask import Flask, render_template, send_from_directory, jsonify
import os
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from flask_mail import Mail, Message
from random import randint
from flask_wtf.csrf import CSRFProtect
import matplotlib.pyplot as plt
from io import BytesIO
import base64
from datetime import datetime, timedelta
import string
import random
import requests
import json
import signal
import sys
import atexit

# -- Supabase (shared with mobile app) ----------------------------------------
from supabase_config import supabase as sb
from supabase_config import supabase_admin as sb_admin  # service-role client (bypasses RLS)
from supabase_config import SUPABASE_URL
from gotrue.errors import AuthApiError, AuthRetryableError

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'your-secret-key-here')
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=1)

# Add min and max functions to Jinja2 environment
app.jinja_env.globals.update(min=min, max=max)

# Show real errors in production logs
import traceback as _tb

@app.errorhandler(500)
def internal_error(e):
    _tb.print_exc()
    return f"<h1>500 Internal Server Error</h1><pre>{_tb.format_exc()}</pre>", 500

# -- Jinja2 filter: resolve product image to a web-accessible URL -------------
def product_image_url(image_value):
    """
    Convert a stored image value to a web-accessible URL.
    - Full URL (http/https): return as-is  [Supabase Storage]
    - Already a /static/ path: return as-is
    - Plain filename: try Supabase Storage first, fallback to /static/images/uploads/
    - Empty/None: return empty string
    """
    if not image_value:
        return ''
    s = str(image_value).strip()
    if s.startswith('http://') or s.startswith('https://'):
        return s
    if s.startswith('/'):
        return s  # already a rooted path like /static/images/uploads/...
    # Plain filename — serve from Supabase Storage
    fname = s.split('/')[-1]
    return f'https://vydcnhmgqovketjqvpoe.supabase.co/storage/v1/object/public/product-images/products/{fname}'

app.jinja_env.filters['product_img'] = product_image_url
app.jinja_env.globals['product_image_url'] = product_image_url

# -- Context processor: inject seller profile into all templates ---------------
@app.context_processor
def inject_seller_profile():
    """Make seller_business_name and seller_profile_picture available in every template."""
    if session.get('user_type') != 'Seller':
        return {}
    email = session.get('email')
    if not email:
        return {}

    # Fast path: read from session (set at login)
    biz = session.get('business_name', '')
    pic = session.get('profile_picture', '')

    # If not in session yet (e.g. existing session before this change), fetch from Supabase
    if not biz:
        try:
            res = sb_admin.table('users') \
                .select('business_name, profile_picture') \
                .eq('email', email) \
                .execute()
            if res.data:
                biz = res.data[0].get('business_name') or ''
                pic = res.data[0].get('profile_picture') or ''
                # Cache in session for next request
                if biz:
                    session['business_name'] = biz
                if pic:
                    session['profile_picture'] = pic
        except Exception:
            pass

    return {
        'seller_business_name':    biz or 'My Shop',
        'seller_profile_picture':  pic,
    }

# Prevent caching for all pages to ensure fresh content after logout
@app.after_request
def add_header(response):
    """Add headers to prevent caching of pages and allow CORS for mobile app"""
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate, post-check=0, pre-check=0, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    # -- CORS: allow Flutter web / mobile to call the API -----------------
    response.headers['Access-Control-Allow-Origin']  = '*'
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, PUT, DELETE, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization, X-Requested-With'
    return response

@app.route('/api/mobile/place_order', methods=['OPTIONS'])
@app.route('/api/<path:path>', methods=['OPTIONS'])
def handle_options(path=''):
    """Handle CORS preflight requests for all /api/* routes"""
    from flask import Response as _Resp
    r = _Resp()
    r.headers['Access-Control-Allow-Origin']  = '*'
    r.headers['Access-Control-Allow-Methods'] = 'GET, POST, PUT, DELETE, OPTIONS'
    r.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization, X-Requested-With'
    return r, 200


@app.route('/api/mobile/place_order', methods=['POST'])
def mobile_place_order():
    """Mobile app: place one or more orders directly from the app."""
    try:
        data = request.get_json(silent=True) or {}
        email          = (data.get('email') or '').strip()
        payment_method = (data.get('payment_method') or 'cod').strip()
        address        = (data.get('address') or '').strip()
        items          = data.get('items') or []

        if not email:
            return jsonify({'success': False, 'error': 'email is required'}), 400
        if not items:
            return jsonify({'success': False, 'error': 'items is required'}), 400

        # Resolve address from DB if not provided
        if not address:
            try:
                addr_res = sb_admin.table('users') \
                    .select('house_street, barangay, city, province, region, zip_code') \
                    .eq('email', email).limit(1).execute()
                if addr_res.data:
                    u = addr_res.data[0]
                    parts = [u.get('house_street',''), u.get('barangay',''),
                             u.get('city',''), u.get('province',''),
                             u.get('region',''), u.get('zip_code','')]
                    address = ', '.join(p for p in parts if p)
            except Exception:
                pass

        order_ids = []
        for item in items:
            name         = str(item.get('name') or '')
            product_id   = item.get('product_id')
            price        = float(item.get('price') or 0)
            quantity     = int(item.get('quantity') or 1)
            color        = str(item.get('color') or '')
            size         = str(item.get('size') or '')
            image        = str(item.get('image') or '')
            seller_email = str(item.get('seller_email') or '')
            shipping_fee = float(item.get('shipping_fee') or 50)

            # Resolve product_id if missing
            product_id_int = 0
            if product_id:
                try:
                    product_id_int = int(product_id)
                except (ValueError, TypeError):
                    pass

            if product_id_int == 0 and name:
                try:
                    pr = sb_admin.table('products').select('id, seller_email') \
                        .ilike('name', f'%{name}%').limit(1).execute()
                    if pr.data:
                        product_id_int = int(pr.data[0].get('id') or 0)
                        if not seller_email:
                            seller_email = pr.data[0].get('seller_email', '')
                except Exception:
                    pass

            # Resolve seller_email if still missing
            if not seller_email and product_id_int:
                try:
                    pe = sb_admin.table('products').select('seller_email') \
                        .eq('id', product_id_int).limit(1).execute()
                    if pe.data:
                        seller_email = pe.data[0].get('seller_email', '')
                except Exception:
                    pass

            # Decrement variant stock (non-fatal)
            if product_id_int and color and size:
                try:
                    vi_res = sb_admin.table('variant_inventory') \
                        .select('id, stock_quantity, low_stock_threshold') \
                        .eq('product_id', product_id_int) \
                        .eq('color', color).eq('size', size).limit(1).execute()
                    if vi_res.data:
                        vi = vi_res.data[0]
                        new_stock = max(0, int(vi.get('stock_quantity') or 0) - quantity)
                        sb_admin.table('variant_inventory').update({
                            'stock_quantity': new_stock
                        }).eq('id', vi['id']).execute()
                except Exception as ve:
                    print(f'mobile_place_order: variant stock decrement failed (non-fatal): {ve}')

            # Decrement product stock (non-fatal)
            if product_id_int:
                try:
                    ps = sb_admin.table('products').select('quantity') \
                        .eq('id', product_id_int).limit(1).execute()
                    if ps.data:
                        cur_qty = int(ps.data[0].get('quantity') or 0)
                        sb_admin.table('products').update({
                            'quantity': max(0, cur_qty - quantity)
                        }).eq('id', product_id_int).execute()
                except Exception as pe2:
                    print(f'mobile_place_order: product stock decrement failed (non-fatal): {pe2}')

            total_price = price * quantity + shipping_fee

            order_row = {
                'name':           name,
                'quantity':       quantity,
                'total_price':    total_price,
                'payment_method': payment_method,
                'status':         'Pending',
                'email':          email,
                'address':        address,
                'seller_email':   seller_email,
                'image':          image,
                'variations':     color,
                'size':           size,
                'product_id':     product_id_int if product_id_int else None,
                'shipping_fee':   shipping_fee,
            }
            order_res = sb_admin.table('orders').insert(order_row).execute()
            new_order_id = (order_res.data or [{}])[0].get('id')
            if new_order_id:
                order_ids.append(new_order_id)

            # Notify seller (non-fatal, background)
            if seller_email:
                import threading
                def _notify(se=seller_email, od=[{'name': name, 'quantity': quantity,
                    'total_price': total_price, 'variations': color, 'size': size,
                    'email': email, 'address': address, 'payment_method': payment_method}]):
                    try:
                        send_order_notification_email(se, od)
                        _create_order_notification_supabase(se, od)
                    except Exception:
                        pass
                threading.Thread(target=_notify, daemon=True).start()

        return jsonify({'success': True, 'order_ids': order_ids})

    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

# Get the absolute path of the project directory (FFastique - no images/ECommerce)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Set upload folder path relative to the project directory
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'static', 'images', 'uploads')

# Create upload directory if it doesn't exist
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size

# Create upload subdirectories
os.makedirs(os.path.join(UPLOAD_FOLDER, 'ids'), exist_ok=True)
os.makedirs(os.path.join(UPLOAD_FOLDER, 'seller_docs'), exist_ok=True)
os.makedirs(os.path.join(UPLOAD_FOLDER, 'rider_docs'), exist_ok=True)

def save_uploaded_file(file, folder):
    if file and file.filename:
        filename = secure_filename(file.filename)
        upload_folder = os.path.join('static', 'uploads', folder)
        os.makedirs(upload_folder, exist_ok=True)
        file_path = os.path.join(upload_folder, filename)
        file.save(file_path)
        return file_path
    return None

# Print the path for debugging
print(f"Upload folder path: {UPLOAD_FOLDER}")

# Configure Flask to use this upload folder
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

app.config["MAIL_SERVER"] = 'smtp.gmail.com'
app.config["MAIL_PORT"] = 587
app.config["MAIL_USERNAME"] = 'stylemens2025@gmail.com'  # Your Gmail
app.config['MAIL_PASSWORD'] = os.environ.get('MAIL_PASSWORD', 'qkne phbi pwbj ljdt')
app.config['MAIL_USE_TLS'] = True  # Important for Gmail on port 587
app.config['MAIL_USE_SSL'] = False
app.config['MAIL_DEFAULT_SENDER'] = ('M\'STYLE', 'stylemens2025@gmail.com')

# Initialize Flask-Mail
from flask_mail import Mail
mail = Mail(app)



# MySQL connection settings — REMOVED (Supabase only)
# All database operations now use sb_admin (Supabase service-role client)

# -- Cart image helper ---------------------------------------------------------
def _find_color_image(selected_color, image_colors_str, all_images_str):
    """
    Given a selected color name, find the matching image URL from image_colors mapping.
    image_colors format: "filename_or_url:ColorName,filename_or_url:ColorName"
    Returns the image URL/filename for the matching color, or None if not found.
    """
    if not selected_color or not image_colors_str:
        return None

    color_lower = selected_color.lower().strip()
    color_variations = [
        color_lower,
        color_lower.replace(' ', '_'),
        color_lower.replace(' ', '-'),
        color_lower.replace(' ', ''),
    ]

    for mapping in image_colors_str.split(','):
        mapping = mapping.strip()
        if ':' not in mapping:
            continue
        colon_idx = mapping.rfind(':')
        img_part = mapping[:colon_idx].strip()
        color_part = mapping[colon_idx + 1:].strip().lower()
        if color_part in color_variations or any(v in color_part for v in color_variations):
            return img_part

    # Fallback: search image filenames/URLs for color name
    if all_images_str:
        for img in all_images_str.split(','):
            img = img.strip()
            img_lower = img.lower()
            if any(v in img_lower for v in color_variations):
                return img

    return None


# -- image_colors dict parser --------------------------------------------------
def _parse_image_colors_dict(image_colors_raw, all_images_str=None):
    """
    Parse image_colors (JSON dict or 'url:Color,...' string) into
    { colorName.lower() ? imageUrl } dict.
    """
    import json as _json
    result = {}
    if not image_colors_raw:
        return result
    # Try JSON dict first (new format: {"Black": "https://..."})
    try:
        if isinstance(image_colors_raw, str):
            data = _json.loads(image_colors_raw)
        else:
            data = image_colors_raw
        if isinstance(data, dict):
            for color, url in data.items():
                result[color.lower().strip()] = url
            return result
    except Exception:
        pass
    # Fallback: old 'url:Color,...' format
    for mapping in str(image_colors_raw).split(','):
        mapping = mapping.strip()
        if ':' not in mapping:
            continue
        colon_idx = mapping.rfind(':')
        img_part = mapping[:colon_idx].strip()
        color_part = mapping[colon_idx + 1:].strip().lower()
        if color_part:
            result[color_part] = img_part
    return result


# -- Supabase user-name helper -------------------------------------------------
def get_user_name_from_session(default='User'):
    """Return 'First Last' for the logged-in buyer/rider by querying Supabase users
    table via email.  Falls back to session['first_name'] or *default* on error."""
    # Fast path: name already in session
    first = session.get('first_name', '')
    last  = session.get('last_name', '')
    if first:
        return f"{first} {last}".strip()

    email = session.get('email')
    if not email:
        return default
    try:
        res = sb_admin.table('users').select('first_name, last_name').eq('email', email).execute()
        if res.data:
            u = res.data[0]
            name = f"{u.get('first_name', '')} {u.get('last_name', '')}".strip()
            return name or default
    except Exception as e:
        print(f"?? get_user_name_from_session error: {e}")
    return default


def _resolve_wishlist_user_id(email):
    """Resolve a numeric user_id for the wishlist table from a user email."""
    import hashlib
    try:
        res = sb_admin.table('users').select('id').eq('email', email).limit(1).execute()
        if res.data:
            raw_id = res.data[0].get('id')
            try:
                return int(raw_id)
            except (ValueError, TypeError):
                pass
    except Exception as e:
        print(f"_resolve_wishlist_user_id error: {e}")
    # Fallback: deterministic hash of email
    return int(hashlib.md5(email.lower().encode()).hexdigest()[:8], 16) & 0x7FFFFFFF


def _get_wishlist_ids():
    """Return a set of product IDs in the current user's wishlist."""
    email = session.get('email')
    if not email:
        return set()
    try:
        user_id = _resolve_wishlist_user_id(email)
        res = sb_admin.table('wishlist').select('product_id').eq('user_id', user_id).execute()
        return {str(r['product_id']) for r in (res.data or [])}
    except Exception as e:
        print(f"_get_wishlist_ids error: {e}")
        return set()

# Add proper cleanup on app shutdown
@app.teardown_appcontext
def close_db_connection(error):
    """Close database connections on app context teardown"""
    pass  # Connections are closed explicitly in each route

# Cleanup handler for graceful shutdown
def cleanup_on_exit():
    """Cleanup resources on application exit"""
    try:
        # Close matplotlib to prevent threading issues
        plt.close('all')
        print("Application cleanup completed")
    except Exception as e:
        print(f"Error during cleanup: {e}")

# Register cleanup handler
atexit.register(cleanup_on_exit)

# Signal handler for graceful shutdown
def signal_handler(sig, frame):
    """Handle shutdown signals gracefully"""
    print("\nShutting down gracefully...")
    cleanup_on_exit()
    sys.exit(0)

# Register signal handlers
signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

def add_cancellation_columns():
    """No-op: orders table in Supabase already has cancellation_reason and cancelled_at columns."""
    pass

def initialize_database_tables():
    """No-op: all tables are managed in Supabase via migration SQL files."""
    print("✅ Supabase tables already initialized via migration SQL files.")


def ensure_promotion_tables_exist():
    """No-op: promotion tables are managed in Supabase via supabase_seller_migration.sql."""
    pass


def backfill_promotion_usage(cursor=None):
    """No-op: backfill is not needed for Supabase-only setup."""
    pass

def convert_promotion_for_json(promotion):
    """Convert promotion data to JSON-serializable format"""
    # Create a new dict to avoid modifying the original
    converted = {}
    
    try:
        for key, value in promotion.items():
            if value is None:
                converted[key] = None
            elif key in ['start_date', 'end_date'] and hasattr(value, 'strftime'):
                converted[key] = value.strftime('%Y-%m-%d')
            elif key in ['start_time', 'end_time'] and hasattr(value, 'total_seconds'):
                # It's a timedelta object
                total_seconds = int(value.total_seconds())
                hours = total_seconds // 3600
                minutes = (total_seconds % 3600) // 60
                converted[key] = f"{hours:02d}:{minutes:02d}"
            elif key in ['created_at', 'updated_at'] and hasattr(value, 'strftime'):
                converted[key] = value.strftime('%Y-%m-%d %H:%M:%S')
            elif key in ['discount_value', 'max_discount', 'min_purchase'] and value is not None:
                converted[key] = float(value)
            elif key == 'is_active':
                converted[key] = bool(value)
            elif isinstance(value, (int, float, str, bool)):
                converted[key] = value
            else:
                # Convert any other type to string as fallback
                converted[key] = str(value)
        
        return converted
        
    except Exception as conversion_error:
        print(f"Error converting promotion fields: {conversion_error}")
        
        # Return a minimal safe version
        return {
            'id': promotion.get('id', 0),
            'name': str(promotion.get('name', '')),
            'code': str(promotion.get('code', '')),
            'type': str(promotion.get('type', '')),
            'start_date': '2024-01-01',
            'end_date': '2024-12-31',
            'start_time': '00:00',
            'end_time': '23:59',
            'is_active': True
        }

def get_featured_products(limit=6):
    """Get featured products from Supabase � one per category group, falls back to top products."""
    try:
        res = sb_admin.table('products') \
            .select('id, name, category, description, price, image, quantity, sold, rating, seller_email, variations, sizes') \
            .or_('quantity.gt.0,sold.gt.0') \
            .order('sold', desc=True) \
            .limit(100) \
            .execute()

        all_products = res.data or []

        # Client-side filter: exclude inactive / flagged
        all_products = [
            p for p in all_products
            if p.get('is_active') is not False
            and not (p.get('flagged_at') and str(p.get('flagged_at')).strip())
        ]

        # Pick one product per category group
        category_groups = [
            ['SUITS', 'BLAZERS'],
            ['CASUAL', 'SHIRTS', 'PANTS'],
            ['OUTERWEAR', 'JACKETS'],
            ['ACTIVEWEAR', 'FITNESS'],
            ['SHOES', 'ACCESSORIES'],
            ['GROOMING'],
        ]

        featured = []
        used_ids = set()

        for group in category_groups:
            group_upper = [c.upper() for c in group]
            match = next(
                (p for p in all_products
                 if str(p.get('category', '')).upper() in group_upper
                 and p['id'] not in used_ids),
                None
            )
            if match:
                featured.append(match)
                used_ids.add(match['id'])

        # Fill remaining slots with any products not yet included
        if len(featured) < limit:
            for p in all_products:
                if p['id'] not in used_ids:
                    featured.append(p)
                    used_ids.add(p['id'])
                if len(featured) >= limit:
                    break

        return featured[:limit]

    except Exception as err:
        print(f"Database error in get_featured_products: {err}")
        return []

def get_promotional_products(limit=4, category_filter=None):
    """Get products with active promotions from Supabase for the hero section."""
    try:
        # Use Philippine Standard Time (UTC+8) to avoid date mismatch on Railway (UTC)
        from datetime import datetime as _datetime, timezone as _tz, timedelta as _td
        _pht = _tz(_td(hours=8))
        today = _datetime.now(_pht).date().isoformat()

        promo_res = sb_admin.table('promotions') \
            .select('id, name, type, discount_value, code, product_scope, start_date, end_date, seller_email') \
            .eq('is_active', True) \
            .lte('start_date', today) \
            .gte('end_date', today) \
            .execute()

        promotions = promo_res.data or []
        if not promotions:
            return []

        # Fetch products that have stock
        prod_query = sb_admin.table('products') \
            .select('id, name, category, description, price, image, quantity, sold, rating, seller_email, variations, sizes') \
            .or_('quantity.gt.0,sold.gt.0')

        if category_filter:
            cats = category_filter if isinstance(category_filter, list) else [category_filter]
            prod_query = prod_query.in_('category', cats)

        prod_res = prod_query.order('sold', desc=True).limit(200).execute()
        all_products = prod_res.data or []

        # Client-side filter: exclude inactive / flagged
        all_products = [
            p for p in all_products
            if p.get('is_active') is not False
            and not (p.get('flagged_at') and str(p.get('flagged_at')).strip())
        ]

        # Build lookup maps for specific-scope promotions
        promo_product_ids = {}    # promotion_id -> set of product_ids
        promo_category_names = {} # promotion_id -> set of categories
        specific_promo_ids = [p['id'] for p in promotions if p.get('product_scope') == 'specific']
        category_promo_ids = [p['id'] for p in promotions if p.get('product_scope') == 'category']

        if specific_promo_ids:
            pp_res = sb_admin.table('promotion_products') \
                .select('promotion_id, product_id') \
                .in_('promotion_id', specific_promo_ids).execute()
            for row in (pp_res.data or []):
                promo_product_ids.setdefault(row['promotion_id'], set()).add(row['product_id'])

        if category_promo_ids:
            pc_res = sb_admin.table('promotion_categories') \
                .select('promotion_id, category') \
                .in_('promotion_id', category_promo_ids).execute()
            for row in (pc_res.data or []):
                promo_category_names.setdefault(row['promotion_id'], set()).add(row['category'])

        # Match products to promotions
        promotional = []
        seen_ids = set()

        for promo in promotions:
            scope          = promo.get('product_scope', 'all')
            pid            = promo['id']
            seller_email   = promo.get('seller_email', '')

            for p in all_products:
                if p['id'] in seen_ids:
                    continue

                # Always restrict to the seller who owns the promotion
                if p.get('seller_email') != seller_email:
                    continue

                qualifies = False
                if scope == 'all':
                    qualifies = True
                elif scope == 'specific':
                    qualifies = p['id'] in promo_product_ids.get(pid, set())
                elif scope == 'category':
                    qualifies = str(p.get('category', '')).upper() in \
                                {c.upper() for c in promo_category_names.get(pid, set())}

                if qualifies:
                    enriched = dict(p)
                    enriched['promotion_type']     = promo.get('type', '')
                    enriched['promotion_discount'] = float(promo.get('discount_value') or 0)
                    enriched['promotion_code']     = promo.get('code', '')
                    enriched['promotion_name']     = promo.get('name', '')
                    enriched['price']    = float(enriched.get('price') or 0)
                    enriched['quantity'] = int(enriched.get('quantity') or 0)
                    enriched['sold']     = int(enriched.get('sold') or 0)
                    enriched['rating']   = float(enriched.get('rating') or 0)
                    promotional.append(enriched)
                    seen_ids.add(p['id'])
                    break  # one product per promotion for hero

            if len(promotional) >= limit:
                break

        return promotional[:limit]

    except Exception as err:
        print(f"Database error in get_promotional_products: {err}")
        return []

def _fetch_products_from_supabase(categories=None):
    """
    Fetch active, non-flagged products from Supabase.
    Only returns products that have had stock set (quantity > 0 OR sold > 0).
    Optionally filter by a list of category strings.
    Returns a list of product dicts with a 'rating' field computed from reviews.
    """
    try:
        query = sb_admin.table('products') \
            .select('id, name, category, description, price, image, quantity, sold, '
                    'rating, seller_email, variations, sizes, flagged_at, is_active') \
            .eq('is_active', True) \
            .order('id', desc=True)

        if categories:
            query = query.in_('category', categories)

        res = query.execute()
        raw = res.data or []

        # Client-side filters: exclude flagged products and never-stocked products
        products = [
            p for p in raw
            if not (p.get('flagged_at') and str(p.get('flagged_at')).strip())
            and (int(p.get('quantity') or 0) > 0 or int(p.get('sold') or 0) > 0)
        ]

        # Fetch reviews for rating calculation
        if products:
            product_ids = [p['id'] for p in products]
            reviews_res = sb_admin.table('reviews') \
                .select('product_id, rating') \
                .in_('product_id', product_ids) \
                .execute()

            from collections import defaultdict
            rating_map = defaultdict(list)
            for r in (reviews_res.data or []):
                rating_map[r['product_id']].append(r['rating'])

            for p in products:
                ratings = rating_map.get(p['id'], [])
                if ratings:
                    p['rating'] = round(sum(ratings) / len(ratings), 1)
                    p['review_count'] = len(ratings)
                else:
                    p['rating'] = None
                    p['review_count'] = 0

                # Ensure numeric types
                try:
                    p['price'] = float(p.get('price') or 0)
                except (ValueError, TypeError):
                    p['price'] = 0.0
                try:
                    p['quantity'] = int(p.get('quantity') or 0)
                except (ValueError, TypeError):
                    p['quantity'] = 0
                try:
                    p['sold'] = int(p.get('sold') or 0)
                except (ValueError, TypeError):
                    p['sold'] = 0

        return products
    except Exception as e:
        print(f"? _fetch_products_from_supabase error: {e}")
        return []


def get_active_promotions_for_product(product_id, seller_email, category):
    """Get active promotions that apply to a specific product — uses Supabase."""
    try:
        if not product_id or not seller_email:
            return None

        from datetime import datetime as _datetime, timezone as _tz, timedelta as _td
        _pht = _tz(_td(hours=8))
        today = _datetime.now(_pht).date().isoformat()

        # Fetch active promotions for this seller
        promo_res = sb_admin.table('promotions') \
            .select('id, name, code, type, discount_value, max_discount, min_purchase, '
                    'min_quantity, start_date, end_date, start_time, end_time, product_scope') \
            .eq('seller_email', seller_email) \
            .eq('is_active', True) \
            .lte('start_date', today) \
            .gte('end_date', today) \
            .order('discount_value', desc=True) \
            .execute()

        promotions = promo_res.data or []

        for promo in promotions:
            scope = promo.get('product_scope', 'all')

            if scope == 'all':
                return _normalize_promo_floats(promo)

            elif scope == 'specific':
                pp_res = sb_admin.table('promotion_products') \
                    .select('id') \
                    .eq('promotion_id', promo['id']) \
                    .eq('product_id', product_id) \
                    .limit(1) \
                    .execute()
                if pp_res.data:
                    return _normalize_promo_floats(promo)

            elif scope == 'category' and category:
                pc_res = sb_admin.table('promotion_categories') \
                    .select('id') \
                    .eq('promotion_id', promo['id']) \
                    .eq('category', category) \
                    .limit(1) \
                    .execute()
                if pc_res.data:
                    return _normalize_promo_floats(promo)

        return None

    except Exception as err:
        print(f"Error in get_active_promotions_for_product: {err}")
        return None


def _normalize_promo_floats(promo):
    """Convert Decimal/None fields in a promotion dict to float."""
    for key in ('discount_value', 'max_discount', 'min_purchase'):
        try:
            promo[key] = float(promo[key]) if promo.get(key) is not None else None
        except (ValueError, TypeError):
            promo[key] = None
    return promo

def calculate_promotional_price(original_price, promotion):
    """Calculate the promotional price based on promotion type and discount value"""
    if not promotion:
        return original_price, 0
    
    try:
        # More robust original_price conversion
        if isinstance(original_price, str):
            original_price = original_price.strip()
            if original_price == '' or original_price.lower() == 'none':
                original_price = 0.0
            else:
                original_price = float(original_price)
        else:
            original_price = float(original_price) if original_price is not None else 0.0
            
        promotion_type = promotion['type']
        
        # For free_shipping and buy_one_get_one promotions, no price change on product display
        if promotion_type in ['free_shipping', 'buy_one_get_one']:
            return original_price, 0.0
        
        # For percentage and fixed promotions, we need a valid discount_value
        if not promotion.get('discount_value'):
            return original_price, 0.0
            
        try:
            discount_val = promotion['discount_value']
            if isinstance(discount_val, str):
                discount_val = discount_val.strip()
                if discount_val == '' or discount_val.lower() == 'none':
                    return original_price, 0.0
                else:
                    discount_value = float(discount_val)
            else:
                discount_value = float(discount_val) if discount_val is not None else 0.0
        except (ValueError, TypeError):
            # If discount_value can't be converted to float, return original price
            return original_price, 0.0
        
        if promotion_type == 'percentage':
            # Percentage discount
            discount_amount = original_price * (discount_value / 100)
            
            # Apply max discount limit if specified
            if promotion.get('max_discount'):
                try:
                    max_discount = float(promotion['max_discount'])
                    if discount_amount > max_discount:
                        discount_amount = max_discount
                except (ValueError, TypeError):
                    # If max_discount can't be converted, ignore the limit
                    pass
            
            promotional_price = original_price - discount_amount
            
        elif promotion_type == 'fixed':
            # Fixed amount discount
            discount_amount = min(discount_value, original_price)  # Don't discount more than the price
            promotional_price = original_price - discount_amount
            
        else:
            # For any other unknown promotion types, no price change
            return original_price, 0.0
        
        # Ensure promotional price is not negative
        promotional_price = max(promotional_price, 0.0)
        
        return promotional_price, discount_amount
        
    except (ValueError, TypeError) as e:
        print(f"Error calculating promotional price: {e}")
        return float(original_price), 0.0

otp_storage = {}  # In-memory storage for OTPs (in production, use a database like Redis)

def generate_otp():
    """Generate a 6-digit OTP"""
    return ''.join(random.choices(string.digits, k=6))

def send_otp_email(email, otp):
    """Send OTP to user's email"""
    try:
        msg = Message(
            'Your MStyle Verification Code',
            sender=app.config['MAIL_DEFAULT_SENDER'],
            recipients=[email]
        )
        msg.body = f"""Hello,

Your MStyle verification code is: {otp}

This code will expire in 10 minutes.

If you didn't request this, please ignore this email.

Best regards,
Mstyle Team
"""
        mail.send(msg)
        print(f"Email sent to {email} with OTP: {otp}")  # Debug line
        return True
    except Exception as e:
        print(f"Error sending email: {str(e)}")  # Debug line
        return False

def send_approval_email(email, first_name):
    """Send approval notification email to user"""
    try:
        login_url = os.environ.get('APP_URL', 'https://mstyleecommerce-production.up.railway.app') + '/login'
        msg = Message(
            'Account Approved - Welcome to MStyle!',
            sender=app.config['MAIL_DEFAULT_SENDER'],
            recipients=[email]
        )
        msg.html = f"""
        <div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;background:#fff;border-radius:12px;overflow:hidden;box-shadow:0 4px 20px rgba(0,0,0,0.1);">
            <div style="background:linear-gradient(135deg,#1a1a1a,#2c3e50);padding:32px;text-align:center;">
                <h1 style="color:#d4af37;margin:0;font-size:28px;letter-spacing:2px;">MStyle</h1>
                <p style="color:rgba(255,255,255,0.7);margin:8px 0 0;font-size:13px;">Premium Men's Fashion</p>
            </div>
            <div style="padding:32px;">
                <h2 style="color:#1a1a1a;margin:0 0 16px;">🎉 Account Approved!</h2>
                <p style="color:#555;line-height:1.6;">Hello <strong>{first_name}</strong>,</p>
                <p style="color:#555;line-height:1.6;">Great news! Your MStyle account has been <strong style="color:#28a745;">approved</strong> by our admin team.</p>
                <p style="color:#555;line-height:1.6;">You can now log in and start exploring our premium men's fashion collection.</p>
                <div style="text-align:center;margin:32px 0;">
                    <a href="{login_url}" style="background:linear-gradient(135deg,#d4af37,#f4d03f);color:#1a1a1a;padding:14px 36px;border-radius:8px;text-decoration:none;font-weight:700;font-size:15px;display:inline-block;">Login to MStyle</a>
                </div>
                <p style="color:#888;font-size:13px;">If the button doesn't work, copy this link: <a href="{login_url}" style="color:#d4af37;">{login_url}</a></p>
            </div>
            <div style="background:#f8f9fa;padding:20px;text-align:center;border-top:1px solid #eee;">
                <p style="color:#aaa;font-size:12px;margin:0;">© MStyle — Premium Men's Fashion</p>
            </div>
        </div>"""
        msg.body = f"Hello {first_name}!\n\nYour MStyle account has been approved. Login here: {login_url}\n\nBest regards,\nMStyle Team"
        mail.send(msg)
        print(f"Approval email sent to {email}")
        return True
    except Exception as e:
        print(f"Error sending approval email: {str(e)}")
        return False

def send_rejection_email(email, first_name, rejection_reason):
    """Send rejection notification email to user"""
    try:
        msg = Message(
            'Account Registration Rejected - MStyle',
            sender=app.config['MAIL_DEFAULT_SENDER'],
            recipients=[email]
        )
        msg.body = f"""Hello {first_name},

We regret to inform you that your MStyle account registration has been declined.

Reason: {rejection_reason}

If you believe this was an error or would like to reapply, please contact our support team or submit a new registration with the required information.

Thank you for your interest in MStyle

Best regards,
MStyle Team
"""
        mail.send(msg)
        print(f"Rejection email sent to {email}")
        return True
    except Exception as e:
        print(f"Error sending rejection email: {str(e)}")
        return False

def send_seller_approval_email(email, first_name, business_name):
    """Send approval notification email to seller"""
    try:
        login_url = os.environ.get('APP_URL', 'https://mstyleecommerce-production.up.railway.app') + '/login'
        msg = Message(
            'Congratulations! Your Seller Account Has Been Approved - MStyle',
            sender=app.config['MAIL_DEFAULT_SENDER'],
            recipients=[email]
        )
        msg.html = f"""
        <div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;background:#fff;border-radius:12px;overflow:hidden;box-shadow:0 4px 20px rgba(0,0,0,0.1);">
            <div style="background:linear-gradient(135deg,#1a1a1a,#2c3e50);padding:32px;text-align:center;">
                <h1 style="color:#d4af37;margin:0;font-size:28px;letter-spacing:2px;">MStyle</h1>
                <p style="color:rgba(255,255,255,0.7);margin:8px 0 0;font-size:13px;">Premium Men's Fashion</p>
            </div>
            <div style="padding:32px;">
                <h2 style="color:#1a1a1a;margin:0 0 16px;">🎉 Seller Account Approved!</h2>
                <p style="color:#555;line-height:1.6;">Hello <strong>{first_name}</strong>,</p>
                <p style="color:#555;line-height:1.6;">Congratulations! Your seller application for <strong>"{business_name}"</strong> has been <strong style="color:#28a745;">approved</strong>!</p>
                <p style="color:#555;line-height:1.6;">You can now:</p>
                <ul style="color:#555;line-height:2;">
                    <li>Access your seller dashboard</li>
                    <li>Start listing your products</li>
                    <li>Manage your inventory and track sales</li>
                    <li>Communicate with customers</li>
                </ul>
                <div style="text-align:center;margin:32px 0;">
                    <a href="{login_url}" style="background:linear-gradient(135deg,#d4af37,#f4d03f);color:#1a1a1a;padding:14px 36px;border-radius:8px;text-decoration:none;font-weight:700;font-size:15px;display:inline-block;">Login to Your Seller Dashboard</a>
                </div>
                <p style="color:#888;font-size:13px;">If the button doesn't work, copy this link: <a href="{login_url}" style="color:#d4af37;">{login_url}</a></p>
            </div>
            <div style="background:#f8f9fa;padding:20px;text-align:center;border-top:1px solid #eee;">
                <p style="color:#aaa;font-size:12px;margin:0;">© MStyle — Premium Men's Fashion</p>
            </div>
        </div>"""
        msg.body = f"Hello {first_name},\n\nYour seller application for \"{business_name}\" has been approved!\n\nLogin here: {login_url}\n\nBest regards,\nMStyle Team"
        mail.send(msg)
        print(f"Seller approval email sent to {email}")
        return True
    except Exception as e:
        print(f"Error sending seller approval email: {str(e)}")
        return False

def send_seller_rejection_email(email, first_name, business_name, rejection_reason):
    """Send rejection notification email to seller"""
    try:
        msg = Message(
            'Seller Application Rejected - MStyle',
            sender=app.config['MAIL_DEFAULT_SENDER'],
            recipients=[email]
        )
        msg.body = f"""Hello {first_name},

We regret to inform you that your seller application for "{business_name}" has been declined.

Reason: {rejection_reason}

We encourage you to:
- Review the requirements and ensure all documents are clear and valid
- Reapply with updated information
- Contact our support team if you have any questions

Thank you for your interest in becoming a MStyle seller. We look forward to reviewing your future applications.

Best regards,
MStyle Team
"""
        mail.send(msg)
        print(f"Seller rejection email sent to {email}")
        return True
    except Exception as e:
        print(f"Error sending seller rejection email: {str(e)}")
        return False

def send_order_notification_email(seller_email, order_details):
    """Send order notification email to seller when a new order is placed"""
    try:
        msg = Message(
            'New Order Received - MStyle',
            sender=app.config['MAIL_DEFAULT_SENDER'],
            recipients=[seller_email]
        )
        
        # Format order details for email
        order_items = ""
        total_amount = 0
        
        for item in order_details:
            item_total = float(item['total_price'])
            total_amount += item_total
            
            order_items += f"""
Product: {item['name']}
Quantity: {item['quantity']}
"""
            if item.get('variations'):
                order_items += f"Color: {item['variations']}\n"
            if item.get('size'):
                order_items += f"Size: {item['size']}\n"
            
            order_items += f"Price: ?{item_total:.2f}\n"
            order_items += "-" * 30 + "\n"
        
        customer_email = order_details[0]['email'] if order_details else 'N/A'
        customer_address = order_details[0]['address'] if order_details else 'N/A'
        payment_method = order_details[0]['payment_method'] if order_details else 'N/A'
        
        msg.body = f"""Hello!

?? Great news! You have received a new order on MStyle!

ORDER DETAILS:
{order_items}
TOTAL AMOUNT: ?{total_amount:.2f}

CUSTOMER INFORMATION:
Email: {customer_email}
Delivery Address: {customer_address}
Payment Method: {payment_method}

NEXT STEPS:
1. Log in to your seller dashboard to view full order details
2. Prepare the items for shipping
3. Update the order status once shipped

Thank you for being a valued MStyle seller!

Best regards,
MStyle Team
"""
        mail.send(msg)
        print(f"Order notification email sent to seller: {seller_email}")
        return True
    except Exception as e:
        print(f"Error sending order notification email to {seller_email}: {str(e)}")
        return False

def send_low_stock_notification_email(seller_email, product_name, current_stock, threshold, variant_info=None):
    """Send low stock alert email to seller"""
    try:
        variant_text = ""
        if variant_info:
            variant_text = f" ({variant_info['color']} - {variant_info['size']})"
        
        msg = Message(
            f'?? Low Stock Alert - {product_name}',
            sender=app.config['MAIL_DEFAULT_SENDER'],
            recipients=[seller_email]
        )
        
        msg.body = f"""Hello!

?? LOW STOCK ALERT

Your product is running low on stock and needs attention:

PRODUCT: {product_name}{variant_text}
CURRENT STOCK: {current_stock} units
THRESHOLD: {threshold} units

ACTION REQUIRED:
Please restock this product as soon as possible to avoid running out of stock and missing potential sales.

WHAT TO DO:
1. Log in to your seller dashboard
2. Go to Product Management or Variant Inventory
3. Update the stock quantity for this product

Don't let your customers down - restock now!

Best regards,
MStyle Team
"""
        mail.send(msg)
        print(f"? Low stock email sent to {seller_email} for {product_name}{variant_text}")
        return True
    except Exception as e:
        print(f"? Error sending low stock email to {seller_email}: {str(e)}")
        return False

def send_out_of_stock_notification_email(seller_email, product_name, variant_info=None):
    """Send out of stock alert email to seller"""
    try:
        variant_text = ""
        if variant_info:
            variant_text = f" ({variant_info['color']} - {variant_info['size']})"
        
        msg = Message(
            f'?? Out of Stock Alert - {product_name}',
            sender=app.config['MAIL_DEFAULT_SENDER'],
            recipients=[seller_email]
        )
        
        msg.body = f"""Hello!

?? OUT OF STOCK ALERT

Your product is now completely out of stock:

PRODUCT: {product_name}{variant_text}
CURRENT STOCK: 0 units

URGENT ACTION REQUIRED:
This product is no longer available for purchase. Restock immediately to resume sales!

WHAT TO DO:
1. Log in to your seller dashboard
2. Go to Product Management or Variant Inventory
3. Update the stock quantity for this product

Your customers are waiting - restock now!

Best regards,
MStyle Team
"""
        mail.send(msg)
        print(f"? Out of stock email sent to {seller_email} for {product_name}{variant_text}")
        return True
    except Exception as e:
        print(f"? Error sending out of stock email to {seller_email}: {str(e)}")
        return False

def create_low_stock_notification(seller_email, product_name, current_stock, threshold, product_id, variant_info=None):
    """Create in-app notification for low stock — uses Supabase."""
    try:
        variant_text = ""
        if variant_info:
            variant_text = f" ({variant_info['color']} - {variant_info['size']})"

        message = f"⚠️ Low Stock Alert: {product_name}{variant_text} - Only {current_stock} units left (threshold: {threshold})"

        sb_admin.table('notifications').insert({
            'seller_email': seller_email,
            'message':      message,
            'type':         'low_stock',
            'is_read':      False,
        }).execute()
        print(f"✅ Low stock notification created for {seller_email}: {product_name}{variant_text}")
        return True
    except Exception as e:
        print(f"❌ Error creating low stock notification: {str(e)}")
        return False


def create_out_of_stock_notification(seller_email, product_name, product_id, variant_info=None):
    """Create in-app notification for out of stock — uses Supabase."""
    try:
        variant_text = ""
        if variant_info:
            variant_text = f" ({variant_info['color']} - {variant_info['size']})"

        message = f"🚫 Out of Stock: {product_name}{variant_text} - Product is now unavailable for purchase"

        sb_admin.table('notifications').insert({
            'seller_email': seller_email,
            'message':      message,
            'type':         'out_of_stock',
            'is_read':      False,
        }).execute()
        print(f"✅ Out of stock notification created for {seller_email}: {product_name}{variant_text}")
        return True
    except Exception as e:
        print(f"❌ Error creating out of stock notification: {str(e)}")
        return False

def check_and_notify_stock_levels(product_id, seller_email, new_quantity, threshold, product_name, variant_info=None):
    """Check stock levels and send notifications if needed"""
    try:
        # Check if out of stock
        if new_quantity <= 0:
            # Send out of stock notifications
            send_out_of_stock_notification_email(seller_email, product_name, variant_info)
            create_out_of_stock_notification(seller_email, product_name, product_id, variant_info)
            print(f"?? Out of stock notifications sent for {product_name}")
        
        # Check if low stock (but not out of stock)
        elif new_quantity <= threshold:
            # Send low stock notifications
            send_low_stock_notification_email(seller_email, product_name, new_quantity, threshold, variant_info)
            create_low_stock_notification(seller_email, product_name, new_quantity, threshold, product_id, variant_info)
            print(f"?? Low stock notifications sent for {product_name}")
        
        return True
    except Exception as e:
        print(f"? Error in check_and_notify_stock_levels: {str(e)}")
        return False

def get_user_by_email(email):
    """Fetch a user row from Supabase by email."""
    try:
        res = sb_admin.table('users').select('*').eq('email', email).limit(1).execute()
        return res.data[0] if res.data else None
    except Exception as e:
        print(f"get_user_by_email error: {e}")
        return None


def update_password_in_db(email, new_password):
    """Update password in Supabase auth (best-effort, non-blocking)."""
    try:
        # Find the user's auth UID
        users_res = sb_admin.table('users').select('id').eq('email', email).limit(1).execute()
        if users_res.data:
            uid = users_res.data[0]['id']
            sb_admin.auth.admin.update_user_by_id(uid, {'password': new_password})
            print(f"✅ Supabase auth password updated for {email}")
    except Exception as e:
        print(f"⚠️ update_password_in_db error (non-fatal): {e}")

@app.route('/')
def home():
    page = request.args.get('page', 1, type=int)
    per_page = 12

    # Fetch all products from Supabase (primary source)
    all_products_raw = _fetch_products_from_supabase()
    total_count = len(all_products_raw)
    total_pages = max(1, (total_count + per_page - 1) // per_page)
    page = max(1, min(page, total_pages))
    offset = (page - 1) * per_page
    all_products = all_products_raw[offset: offset + per_page]

    featured_products    = get_featured_products(6)
    promotional_products = get_promotional_products(limit=20)  # fetch more for card enrichment

    # Build a promo lookup keyed by product id for the product grid cards
    promo_map = {p['id']: p for p in promotional_products}
    for prod in all_products:
        if prod['id'] in promo_map:
            pp = promo_map[prod['id']]
            prod['promotion_type']     = pp.get('promotion_type', '')
            prod['promotion_discount'] = pp.get('promotion_discount', 0)
            prod['promotion_code']     = pp.get('promotion_code', '')

    return render_template('index.html',
                           featured_products=featured_products,
                           all_products=all_products,
                           promotional_products=promotional_products[:4],
                           current_page=page,
                           total_pages=total_pages,
                           total_products=total_count,
                           wishlist_product_ids=_get_wishlist_ids())

@app.route('/backtologin', methods=['GET', 'POST'])
def backtologin():
    featured_products    = get_featured_products()
    promotional_products = get_promotional_products()
    return render_template('index.html',
                         featured_products=featured_products,
                         promotional_products=promotional_products)

@app.route('/test-supabase')
def test_supabase():
    """Diagnostic route � shows Supabase connection status and users table columns."""
    try:
        # Try fetching one row to see what columns exist
        res = sb.table('users').select('*').limit(1).execute()
        cols = list(res.data[0].keys()) if res.data else []
        return (
            f"<h2>? Supabase connected</h2>"
            f"<p><b>users table columns:</b> {cols}</p>"
            f"<p><b>Sample row:</b> {res.data}</p>"
        )
    except Exception as e:
        return f"<h2>? Supabase error</h2><pre>{e}</pre>"

# /test-db route removed

#----------------------------------------------------------------------
                         #LOGIN RELATED ROUTES
#----------------------------------------------------------------------


@app.route('/debug-admin-users')
def debug_admin_users():
    """Debug: show raw Supabase users data"""
    if session.get('user_type') != 'Admin':
        return 'Admin only', 403
    try:
        res = sb_admin.table('users').select('*').limit(5).execute()
        count = len(res.data or [])
        cols = list(res.data[0].keys()) if res.data else []
        return f"<pre>Count: {count}\nColumns: {cols}\n\nData:\n{res.data}</pre>"
    except Exception as e:
        import traceback
        return f"<pre>Error: {e}\n{traceback.format_exc()}</pre>"


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email    = request.form.get('email', '').strip()
        password = request.form.get('password', '').strip()

        # -- Admin shortcut ------------------------------------------------
        if email == 'stylemens2025@gmail.com' and password == 'admin':
            session['user_id']   = 0
            session['user_type'] = 'Admin'
            session['email']     = email
            return redirect(url_for('admin_dashboard'))

        # -- Supabase auth -------------------------------------------------
        try:
            res = sb.auth.sign_in_with_password({'email': email, 'password': password})
            uid = res.user.id
            print(f"DEBUG login: Supabase auth OK, uid={uid}")

            # -- Fetch profile from Supabase users table -------------------
            # Use the user's own access token so RLS allows the read
            role        = 'buyer'
            first_name  = ''
            address     = ''
            acct_status = 'active'

            try:
                from supabase import create_client
                from supabase_config import SUPABASE_URL, SUPABASE_ANON

                # Create a client authenticated as the logged-in user
                user_client = create_client(SUPABASE_URL, SUPABASE_ANON)
                user_client.auth.set_session(
                    res.session.access_token,
                    res.session.refresh_token
                )

                profile_res = user_client.table('users').select(
                    'id, role, first_name, last_name, address, status, ban_reason, ban_end_date, business_name'
                ).eq('id', uid).execute()

                print(f"DEBUG login: profile rows={len(profile_res.data)}, data={profile_res.data}")

                if profile_res.data:
                    p           = profile_res.data[0]
                    role        = (p.get('role') or 'buyer').lower()
                    first_name  = p.get('first_name') or ''
                    address     = p.get('address') or ''
                    acct_status = (p.get('status') or 'active').lower()
                    ban_reason  = p.get('ban_reason') or 'No reason provided'
                    ban_end     = p.get('ban_end_date')

                    if acct_status == 'banned':
                        flash(f'Your account has been permanently banned. Reason: {ban_reason}', 'error')
                        return redirect(url_for('login'))
                    elif acct_status == 'suspended':
                        msg = f'Your account is suspended until {ban_end}.' if ban_end else 'Your account is suspended.'
                        flash(f'{msg} Reason: {ban_reason}', 'error')
                        return redirect(url_for('login'))
                    elif acct_status == 'inactive':
                        flash('Your account is inactive. Please contact support.', 'info')
                        return redirect(url_for('login'))
                    elif acct_status == 'pending':
                        flash('Your account is pending admin approval. Please wait for approval before logging in.', 'info')
                        try:
                            sb.auth.sign_out()
                        except Exception:
                            pass
                        return redirect(url_for('login'))
                else:
                    # No profile row � check if account is pending approval first
                    try:
                        pending_user = sb_admin.table('pending_users').select('status').eq('supabase_uid', uid).execute()
                        pending_seller = sb_admin.table('pending_sellers').select('status').eq('supabase_uid', uid).execute()
                        if pending_user.data:
                            status = pending_user.data[0].get('status', 'pending')
                            if status == 'rejected':
                                flash('Your registration was rejected. Please contact support for assistance.', 'error')
                            else:
                                flash('Your account is pending admin approval. Please wait for approval before logging in.', 'info')
                        elif pending_seller.data:
                            status = pending_seller.data[0].get('status', 'pending')
                            if status == 'rejected':
                                flash('Your seller registration was rejected. Please contact support for assistance.', 'error')
                            else:
                                flash('Your seller account is pending admin approval. Please wait for approval before logging in.', 'info')
                        else:
                            flash('Your account no longer exists.', 'error')
                    except Exception:
                        flash('Your account no longer exists.', 'error')
                    try:
                        sb.auth.sign_out()
                    except Exception:
                        pass
                    return redirect(url_for('login'))

            except Exception as profile_err:
                print(f"DEBUG login: profile fetch error: {profile_err}")
                # If the error is a genuine network/DB issue (not a missing row),
                # we still need to block login � we cannot verify the account exists.
                # Attempt one more time with the admin client to check if the row exists.
                try:
                    admin_check = sb_admin.table('users').select('id, role, first_name').eq('id', uid).execute()
                    if admin_check.data:
                        p = admin_check.data[0]
                        role = (p.get('role') or 'buyer').lower()
                        first_name = p.get('first_name') or ''
                        print(f"DEBUG login: admin fallback found profile, role={role}")
                    else:
                        # No profile row found even via admin client � check pending tables
                        print(f"DEBUG login: admin fallback also found no profile row for uid={uid}")
                        try:
                            pending_user = sb_admin.table('pending_users').select('status').eq('supabase_uid', uid).execute()
                            pending_seller = sb_admin.table('pending_sellers').select('status').eq('supabase_uid', uid).execute()
                            if pending_user.data:
                                status = pending_user.data[0].get('status', 'pending')
                                if status == 'rejected':
                                    flash('Your registration was rejected. Please contact support for assistance.', 'error')
                                else:
                                    flash('Your account is pending admin approval. Please wait for approval before logging in.', 'info')
                            elif pending_seller.data:
                                status = pending_seller.data[0].get('status', 'pending')
                                if status == 'rejected':
                                    flash('Your seller registration was rejected. Please contact support for assistance.', 'error')
                                else:
                                    flash('Your seller account is pending admin approval. Please wait for approval before logging in.', 'info')
                            else:
                                flash('Your account no longer exists.', 'error')
                        except Exception:
                            flash('Your account no longer exists.', 'error')
                        try:
                            sb.auth.sign_out()
                        except Exception:
                            pass
                        return redirect(url_for('login'))
                except Exception as admin_err:
                    print(f"DEBUG login: admin fallback also failed: {admin_err}")
                    flash('Unable to verify your account. Please try again later.', 'error')
                    try:
                        sb.auth.sign_out()
                    except Exception:
                        pass
                    return redirect(url_for('login'))

            # -- Set session -----------------------------------------------
            session['user_id']       = uid
            session['email']         = email
            session['user_type']     = role.capitalize()
            session['first_name']    = first_name
            session['address']       = address
            # Store business_name for sellers so the header can display it
            if role == 'seller':
                business_name = ''
                try:
                    biz_res = sb_admin.table('users').select('business_name').eq('email', email).execute()
                    if biz_res.data:
                        business_name = biz_res.data[0].get('business_name') or ''
                except Exception:
                    pass
                session['business_name'] = business_name

            print(f"DEBUG login: session set � email={email}, role={role}")

            if role == 'buyer':
                return redirect(url_for('homepage'))
            elif role == 'seller':
                return redirect(url_for('seller_dashboard'))
            elif role == 'rider':
                return redirect(url_for('rider_dashboard'))
            else:
                return redirect(url_for('homepage'))

        except AuthApiError as e:
            print(f"Supabase AuthApiError: {e}")
            err_msg = str(e).lower()
            if 'banned' in err_msg or 'user is banned' in err_msg:
                # Could be:
                #   1. A pending user (banned until approved)
                #   2. A restored-from-archive user whose auth ban wasn't cleared
                #   3. A genuinely banned/archived user
                email_check = (request.form.get('email', '') or '').strip()
                try:
                    pending_user   = sb_admin.table('pending_users').select('status').eq('email', email_check).execute()
                    pending_seller = sb_admin.table('pending_sellers').select('status').eq('email', email_check).execute()
                    if pending_user.data:
                        status = pending_user.data[0].get('status', 'pending')
                        if status == 'rejected':
                            flash('Your registration was rejected. Please contact support for assistance.', 'error')
                        else:
                            flash('Your account is pending admin approval. Please wait for approval before logging in.', 'info')
                    elif pending_seller.data:
                        status = pending_seller.data[0].get('status', 'pending')
                        if status == 'rejected':
                            flash('Your seller registration was rejected. Please contact support for assistance.', 'error')
                        else:
                            flash('Your seller account is pending admin approval. Please wait for approval before logging in.', 'info')
                    else:
                        # Check if the user exists in the users table (restored from archive)
                        users_check = sb_admin.table('users').select('id, status').eq('email', email_check).execute()
                        if users_check.data:
                            # User exists � their auth ban was not cleared on restore. Fix it now.
                            restored_uid = users_check.data[0]['id']
                            try:
                                sb_admin.auth.admin.update_user_by_id(restored_uid, {'ban_duration': 'none'})
                                print(f"Auto-unbanned restored user {email_check} on login attempt")
                                flash('Your account has been restored. Please try logging in again.', 'info')
                            except Exception as unban_err:
                                print(f"Auto-unban failed for {email_check}: {unban_err}")
                                flash('Your account exists but could not be unlocked. Please contact support.', 'error')
                        else:
                            flash('Your account no longer exists.', 'error')
                except Exception:
                    flash('Your account no longer exists.', 'error')
            else:
                flash('Invalid email or password.', 'error')
        except AuthRetryableError as e:
            # Supabase auth timed out — show error, no MySQL fallback
            print(f"Supabase auth timeout: {e}")
            flash('Login service is temporarily unavailable. Please try again in a moment.', 'error')
        except Exception as e:
            import traceback
            print(f"Login unexpected error: {e}")
            traceback.print_exc()
            flash('An error occurred during login. Please try again.', 'error')

        return redirect(url_for('login'))

    # GET
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    response = redirect(url_for('home'))
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate, post-check=0, pre-check=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

#----------------------------------------------------------------------
                         #OTP RELATED ROUTES
#----------------------------------------------------------------------

@app.route('/api/check-account-status', methods=['POST'])
def check_account_status():
    """
    Mobile login/register helper � called when Supabase auth returns a 'banned' error.
    Returns the account status so the mobile app can show the right message.
    If the account is banned but not in any pending/users table (stale ban from
    a deleted/archived account), automatically unbans it so the user can re-register.
    """
    data  = request.get_json(silent=True) or {}
    email = (data.get('email') or '').strip().lower()
    if not email:
        return jsonify({'status': 'unknown'}), 400

    try:
        pending_user   = sb_admin.table('pending_users').select('status').eq('email', email).execute()
        pending_seller = sb_admin.table('pending_sellers').select('status').eq('email', email).execute()
        approved_user  = sb_admin.table('users').select('id').eq('email', email).execute()

        if approved_user.data:
            return jsonify({'status': 'approved'})

        if pending_user.data or pending_seller.data:
            pu_status = (pending_user.data[0].get('status') if pending_user.data else None) \
                     or (pending_seller.data[0].get('status') if pending_seller.data else None) \
                     or 'pending'
            return jsonify({'status': pu_status})

        # Not in any table � stale ban. Unban so the user can re-register.
        try:
            existing = sb_admin.auth.admin.list_users()
            for u in (existing or []):
                if getattr(u, 'email', None) == email:
                    sb_admin.auth.admin.update_user_by_id(u.id, {'ban_duration': 'none'})
                    print(f"check_account_status: auto-unbanned stale ban for {email}")
                    break
        except Exception as unban_err:
            print(f"check_account_status: unban failed: {unban_err}")

        return jsonify({'status': 'stale_ban'})
    except Exception as e:
        print(f"check_account_status error: {e}")
        return jsonify({'status': 'unknown'}), 500


@app.route('/api/send-otp', methods=['POST'])
def send_otp():
    data  = request.get_json()
    email = (data.get('email') or '').strip()

    if not email:
        return jsonify({'success': False, 'message': 'Email is required'}), 400

    # -- Temporarily unban the user so Supabase can send the OTP ----------
    # Users who previously registered are banned until admin approves.
    # sign_in_with_otp may fail for banned users in some Supabase versions.
    try:
        existing = sb_admin.auth.admin.list_users()
        for u in (existing or []):
            if getattr(u, 'email', None) == email:
                sb_admin.auth.admin.update_user_by_id(u.id, {'ban_duration': 'none'})
                print(f"DEBUG send_otp: temporarily unbanned {email} to allow OTP send")
                break
    except Exception as unban_err:
        print(f"DEBUG send_otp: unban attempt failed (non-fatal): {unban_err}")

    #  Use Supabase OTP (same as mobile) 
    try:
        sb.auth.sign_in_with_otp({
            'email': email,
            'options': {
                'should_create_user': True,   # create auth user if not exists
                # do NOT pass email_redirect_to  omitting it forces OTP code (not magic link)
            }
        })
        print(f"Supabase OTP sent to {email}")
        return jsonify({'success': True, 'message': 'OTP sent successfully'})
    except AuthApiError as e:
        print(f"Supabase OTP error: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500
    except Exception as e:
        print(f"Error sending OTP: {e}")
        return jsonify({'success': False, 'message': 'Failed to send OTP. Please try again.'}), 500

@app.route('/api/verify-otp', methods=['POST'])
def verify_otp():
    """Verify OTP entered by user via Supabase"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'message': 'No data provided'}), 400

        email      = (data.get('email') or '').strip()
        otp_entered = str(data.get('otp') or '').strip()

        if not email or not otp_entered:
            return jsonify({'success': False, 'message': 'Email and OTP are required'}), 400

        # -- Temporarily unban the user so OTP verification can succeed ----
        # Users who previously registered are banned until admin approves.
        # We must unban them briefly so Supabase allows the OTP verify call.
        uid_to_rebban = None
        try:
            existing = sb_admin.auth.admin.list_users()
            for u in (existing or []):
                if getattr(u, 'email', None) == email:
                    uid_to_rebban = u.id
                    # Unban temporarily
                    sb_admin.auth.admin.update_user_by_id(uid_to_rebban, {'ban_duration': 'none'})
                    print(f"DEBUG verify_otp: temporarily unbanned {email} for OTP verification")
                    break
        except Exception as unban_err:
            print(f"DEBUG verify_otp: unban attempt failed (non-fatal): {unban_err}")

        # -- Verify with Supabase ------------------------------------------
        try:
            res = sb.auth.verify_otp({
                'email': email,
                'token': otp_entered,
                'type': 'email',
            })
        except Exception as verify_err:
            # Re-ban if we unbanned and verification failed
            if uid_to_rebban:
                try:
                    sb_admin.auth.admin.update_user_by_id(uid_to_rebban, {'ban_duration': '876600h'})
                except Exception:
                    pass
            raise verify_err

        if res.user:
            uid = res.user.id
            # Store verified email in otp_storage so the register route can confirm it
            otp_storage[email] = {'verified': True, 'uid': uid}
            print(f"Supabase OTP verified for {email}")

            # Re-ban the account � it stays banned until admin approves
            # (the register route will set the final ban after inserting into pending_users)
            try:
                sb_admin.auth.admin.update_user_by_id(uid, {'ban_duration': '876600h'})
                print(f"DEBUG verify_otp: re-banned {email} after OTP verification")
            except Exception as reban_err:
                print(f"DEBUG verify_otp: re-ban failed (non-fatal): {reban_err}")

            # Return session tokens so the mobile client can set its Supabase session
            # and proceed to upload documents / call updateUser
            access_token  = res.session.access_token  if res.session else None
            refresh_token = res.session.refresh_token if res.session else None

            return jsonify({
                'success':       True,
                'message':       'OTP verified successfully',
                'access_token':  access_token,
                'refresh_token': refresh_token,
                'uid':           uid,
            })
        else:
            # Re-ban if we unbanned
            if uid_to_rebban:
                try:
                    sb_admin.auth.admin.update_user_by_id(uid_to_rebban, {'ban_duration': '876600h'})
                except Exception:
                    pass
            return jsonify({'success': False, 'message': 'Invalid OTP. Please try again.'}), 400

    except AuthApiError as e:
        print(f"Supabase verify OTP error: {e}")
        return jsonify({'success': False, 'message': 'Invalid or expired OTP. Please try again.'}), 400
    except Exception as e:
        print(f"Error in verify_otp: {e}")
        return jsonify({'success': False, 'message': 'An error occurred. Please try again.'}), 500
        
#----------------------------------------------------------------------
                         #REGISTER RELATED ROUTES
#----------------------------------------------------------------------

@app.route('/api/seller-register', methods=['POST'])
def api_seller_register():
    """
    Mobile seller registration endpoint.
    Called after OTP verification � uses sb_admin to bypass RLS and the
    auth ban so the seller data can be inserted into pending_sellers.
    """
    data = request.get_json(silent=True) or {}
    email = (data.get('email') or '').strip()

    if not email:
        return jsonify({'success': False, 'message': 'Email is required'}), 400

    # Confirm OTP was verified for this email
    stored = otp_storage.get(email)
    if not stored or not stored.get('verified'):
        return jsonify({'success': False, 'message': 'Email verification required or session expired'}), 400

    uid = stored.get('uid')
    if not uid:
        return jsonify({'success': False, 'message': 'Session expired. Please restart registration'}), 400

    try:
        # Set the password via admin client (bypasses ban)
        password = data.get('password', '')
        if password:
            try:
                sb_admin.auth.admin.update_user_by_id(uid, {'password': password})
            except Exception as pe:
                print(f"Warning: could not set seller password: {pe}")

        # Insert into pending_sellers using service role (bypasses RLS + ban)
        sb_admin.table('pending_sellers').upsert({
            'supabase_uid':        uid,
            'email':               email,
            'first_name':          data.get('first_name', ''),
            'last_name':           data.get('last_name', ''),
            'business_name':       data.get('business_name', ''),
            'business_type':       data.get('business_type', 'individual'),
            'phone':               data.get('phone', ''),
            'house_street':        data.get('house_street', ''),
            'region':              data.get('region'),
            'province':            data.get('province'),
            'city':                data.get('city'),
            'barangay':            data.get('barangay'),
            'zip_code':            data.get('zip_code', ''),
            'valid_id_path':       data.get('valid_id_path'),
            'dti_path':            data.get('dti_path'),
            'bir_path':            data.get('bir_path'),
            'business_permit_path': data.get('business_permit_path'),
            'status':              'pending',
        }).execute()

        # Ensure account stays banned until admin approves
        try:
            sb_admin.auth.admin.update_user_by_id(uid, {'ban_duration': '876600h'})
        except Exception as be:
            print(f"Warning: could not ban seller auth account: {be}")

        # Clean up OTP storage
        otp_storage.pop(email, None)

        return jsonify({'success': True, 'message': 'Seller application submitted successfully'})

    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({'success': False, 'message': f'Registration failed: {str(e)}'}), 500


@app.route('/api/buyer-rider-register', methods=['POST'])
def api_buyer_rider_register():
    """
    Mobile buyer/rider registration endpoint.
    Called after OTP verification � uses sb_admin to bypass RLS and the
    auth ban so the user data can be inserted into pending_users /
    pending_rider_vehicles.
    """
    data = request.get_json(silent=True) or {}
    email = (data.get('email') or '').strip()

    if not email:
        return jsonify({'success': False, 'message': 'Email is required'}), 400

    stored = otp_storage.get(email)
    if not stored or not stored.get('verified'):
        return jsonify({'success': False, 'message': 'Email verification required or session expired'}), 400

    uid = stored.get('uid')
    if not uid:
        return jsonify({'success': False, 'message': 'Session expired. Please restart registration'}), 400

    try:
        password = data.get('password', '')
        if password:
            try:
                sb_admin.auth.admin.update_user_by_id(uid, {'password': password})
            except Exception as pe:
                print(f"Warning: could not set password: {pe}")

        role = (data.get('role') or 'buyer').lower()

        sb_admin.table('pending_users').upsert({
            'supabase_uid':  uid,
            'email':         email,
            'role':          role,
            'first_name':    data.get('first_name', ''),
            'last_name':     data.get('last_name', ''),
            'phone':         data.get('phone', ''),
            'house_street':  data.get('house_street', ''),
            'region':        data.get('region'),
            'province':      data.get('province'),
            'city':          data.get('city'),
            'barangay':      data.get('barangay'),
            'zip_code':      data.get('zip_code', ''),
            'valid_id_path': data.get('valid_id_path'),
            'status':        'pending',
        }).execute()

        if role == 'rider':
            sb_admin.table('pending_rider_vehicles').upsert({
                'supabase_uid':       uid,
                'vehicle_type':       data.get('vehicle_type'),
                'plate_number':       data.get('plate_number'),
                'vehicle_model':      data.get('vehicle_model'),
                'year_model':         data.get('year_model'),
                'or_cr_path':         data.get('or_cr_path'),
                'nbi_clearance_path': data.get('nbi_clearance_path'),
            }).execute()

        try:
            sb_admin.auth.admin.update_user_by_id(uid, {'ban_duration': '876600h'})
        except Exception as be:
            print(f"Warning: could not ban auth account: {be}")

        otp_storage.pop(email, None)

        return jsonify({'success': True, 'message': 'Registration submitted successfully'})

    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({'success': False, 'message': f'Registration failed: {str(e)}'}), 500


@app.route('/register', methods=['POST'])
def register():
    """
    Register a buyer or rider.
    OTP was already verified via Supabase in /api/verify-otp, which created the
    auth user and stored the UID in otp_storage[email]['uid'].
    Here we just update the password and insert the profile into Supabase users table,
    then also insert into MySQL pending_users for admin approval workflow.
    """
    email      = (request.form.get('email') or '').strip()
    otp_entered = request.form.get('otp')

    if not email or not otp_entered:
        flash('Email verification is required', 'error')
        return redirect(url_for('register_page'))

    stored = otp_storage.get(email)
    if not stored or not stored.get('verified'):
        flash('Email verification required or session expired', 'error')
        return redirect(url_for('register_page'))

    db     = None
    cursor = None

    try:
        # -- Collect form data ---------------------------------------------
        first_name      = request.form.get('first_name', '').strip()
        last_name       = request.form.get('last_name', '').strip()
        phone_number    = request.form.get('phone_number', '').strip()
        house_no_street = request.form.get('house_no_street', '').strip()
        region          = request.form.get('region', '').strip()
        province        = request.form.get('province', '').strip()
        municipality    = request.form.get('municipality', '').strip()
        barangay        = request.form.get('barangay', '').strip()
        zip_code        = request.form.get('zip_code', '').strip()
        password        = request.form.get('password', '')
        confirm_password = request.form.get('confirm_password', '')
        user_type       = (request.form.get('user_type') or 'buyer').strip().lower()

        # -- Validation ----------------------------------------------------
        required = {
            'first_name': first_name, 'last_name': last_name,
            'phone_number': phone_number, 'house_no_street': house_no_street,
            'region': region, 'province': province, 'municipality': municipality,
            'barangay': barangay, 'zip_code': zip_code, 'password': password,
        }
        for field, val in required.items():
            if not val:
                return render_template('register.html', error=f"{field.replace('_', ' ').title()} is required.")

        if not phone_number.isdigit() or len(phone_number) != 10:
            return render_template('register.html', error="Phone number must be exactly 10 digits.")
        if len(password) < 6 or len(password) > 8:
            return render_template('register.html', error="Password must be between 6-8 characters.")
        if password != confirm_password:
            return render_template('register.html', error="Passwords do not match.")

        address = f"{house_no_street}, {barangay}, {municipality}, {province}, {region}, {zip_code}"

        # -- File uploads (local storage, unchanged) -----------------------
        def save_uploaded_file(file, folder):
            if file and file.filename:
                try:
                    ts       = datetime.now().strftime('%Y%m%d_%H%M%S')
                    filename = f"{ts}_{secure_filename(file.filename)}"
                    dest     = os.path.join(app.config['UPLOAD_FOLDER'], folder)
                    os.makedirs(dest, exist_ok=True)
                    path = os.path.join(dest, filename)
                    file.save(path)
                    return path
                except Exception as fe:
                    print(f"File save error: {fe}")
            return None

        valid_id_path = None
        if user_type in ['buyer', 'rider']:
            f = request.files.get('valid_id')
            if not f or not f.filename:
                return render_template('register.html', error="Valid ID is required.")
            valid_id_path = save_uploaded_file(f, 'ids')
            if not valid_id_path:
                return render_template('register.html', error="Failed to upload valid ID.")

        # Rider extras
        vehicle_type = vehicle_model = vehicle_plate_number = vehicle_year_model = None
        or_cr_path = nbi_clearance_path = None
        if user_type == 'rider':
            vehicle_type         = request.form.get('vehicle_type')
            vehicle_model        = request.form.get('vehicle_model')
            vehicle_plate_number = request.form.get('plate_number')
            vehicle_year_model   = request.form.get('year_model')
            if not all([vehicle_type, vehicle_model, vehicle_plate_number, vehicle_year_model]):
                return render_template('register.html', error="All vehicle information is required for riders.")
            or_cr_file = request.files.get('or_cr')
            nbi_file   = request.files.get('nbi_clearance')
            if not or_cr_file or not or_cr_file.filename:
                return render_template('register.html', error="OR/CR document is required for riders.")
            if not nbi_file or not nbi_file.filename:
                return render_template('register.html', error="NBI Clearance is required for riders.")
            or_cr_path        = save_uploaded_file(or_cr_file, 'rider_docs')
            nbi_clearance_path = save_uploaded_file(nbi_file, 'rider_docs')
            if not or_cr_path or not nbi_clearance_path:
                return render_template('register.html', error="Failed to upload rider documents.")

        # -- Update Supabase auth password ---------------------------------
        uid = stored.get('uid')
        if uid:
            try:
                sb.auth.admin.update_user_by_id(uid, {'password': password})
                print(f"Supabase password set for {email}")
            except Exception as pe:
                print(f"Warning: could not set Supabase password: {pe}")

        # -- Ban the auth account until admin approves ---------------------
        # User cannot log in until admin approves and unbans them
        if uid:
            try:
                sb_admin.auth.admin.update_user_by_id(uid, {'ban_duration': '876600h'})
                print(f"Supabase auth account banned (pending approval) for {email}")
            except Exception as be:
                print(f"Warning: could not ban auth account: {be}")

        # -- Do NOT insert into Supabase users table yet -------------------
        # Profile will be inserted into Supabase users table only when admin approves.

        # -- Insert into Supabase pending_users (primary � same as mobile) -
        # This works even when MySQL is unavailable.
        addr_parts = address.split(', ')
        try:
            supabase_pending_data = {
                'supabase_uid':  uid,
                'email':         email,
                'role':          user_type,
                'first_name':    first_name,
                'last_name':     last_name,
                'phone':         phone_number,
                'house_street':  house_no_street,
                'region':        region,
                'province':      province,
                'city':          municipality,
                'barangay':      barangay,
                'zip_code':      zip_code,
                'status':        'pending',
            }
            # Store local file path as valid_id_path (admin can view from server)
            if valid_id_path:
                supabase_pending_data['valid_id_path'] = valid_id_path

            sb_admin.table('pending_users').upsert(supabase_pending_data).execute()
            print(f"Inserted into Supabase pending_users for {email}")

            # -- Insert rider vehicle data into pending_rider_vehicles ------
            # (mirrors mobile app behaviour � vehicle data lives in its own table)
            if user_type == 'rider' and uid:
                try:
                    rider_vehicle_data = {
                        'supabase_uid':       uid,
                        'vehicle_type':       vehicle_type,
                        'plate_number':       vehicle_plate_number,
                        'vehicle_model':      vehicle_model,
                        'year_model':         vehicle_year_model,
                        'or_cr_path':         or_cr_path,
                        'nbi_clearance_path': nbi_clearance_path,
                    }
                    sb_admin.table('pending_rider_vehicles').upsert(rider_vehicle_data).execute()
                    print(f"Inserted into Supabase pending_rider_vehicles for {email}")
                except Exception as rv_err:
                    print(f"Warning: Supabase pending_rider_vehicles insert failed: {rv_err}")

        except Exception as sb_err:
            print(f"Warning: Supabase pending_users insert failed: {sb_err}")

        # MySQL mirror removed

        # Clean up OTP storage
        otp_storage.pop(email, None)

        flash('Your registration is pending approval. Please wait for admin approval.', 'info')
        return redirect(url_for('login'))

    except Exception as e:
        if db:
            try: db.rollback()
            except Exception: pass
        import traceback; traceback.print_exc()
        flash(f'An error occurred: {e}', 'error')
        return render_template('register.html', error=f'Registration error: {e}')
    finally:
        if cursor: cursor.close()
        if db:
            try: db.close()
            except Exception: pass
    

# /otp_verification route removed

@app.route('/register')
def register_page():
    return render_template('register.html')

@app.route('/terms_conditions')
def terms_conditions():
    """Route for Terms and Conditions page"""
    return render_template('terms_conditions.html')

@app.route('/privacy_policy')
def privacy_policy():
    """Route for Privacy Policy page"""
    return render_template('privacy_policy.html')

@app.route('/seller_register', methods=['GET', 'POST'])
def seller_register():
    if request.method == 'POST':
        try:
            # -- Collect form data -----------------------------------------
            first_name      = (request.form.get('first_name') or '').strip()
            last_name       = (request.form.get('last_name') or '').strip()
            business_name   = (request.form.get('business_name') or '').strip()
            phone_number    = (request.form.get('phone_number') or '').strip()
            house_no_street = (request.form.get('house_no_street') or '').strip()
            region          = (request.form.get('region') or '').strip()
            province        = (request.form.get('province') or '').strip()
            municipality    = (request.form.get('municipality') or '').strip()
            barangay        = (request.form.get('barangay') or '').strip()
            zip_code        = (request.form.get('zip_code') or '').strip()
            business_type   = (request.form.get('business_type') or '').strip()
            email           = (request.form.get('email') or '').strip()
            otp             = request.form.get('otp')
            password        = request.form.get('password', '')
            confirm_password = request.form.get('confirm_password', '')

            # -- Validate OTP was verified ---------------------------------
            stored = otp_storage.get(email)
            if not stored or not stored.get('verified'):
                flash('Email verification required or session expired.', 'error')
                return render_template('seller_register.html', error='Email verification required.')

            # -- Validate passwords ----------------------------------------
            if not password or not confirm_password:
                return render_template('seller_register.html', error='Password and confirm password are required.')
            if password != confirm_password:
                return render_template('seller_register.html', error='Passwords do not match.')
            if len(password) < 6 or len(password) > 8:
                return render_template('seller_register.html', error='Password must be between 6-8 characters.')

            address = f"{house_no_street}, {barangay}, {municipality}, {province}, {region} {zip_code}"

            # -- File uploads (local storage) ------------------------------
            def save_uploaded_file(file, folder):
                if file and file.filename:
                    ts       = datetime.now().strftime('%Y%m%d_%H%M%S')
                    filename = f"{ts}_{secure_filename(file.filename)}"
                    dest     = os.path.join(app.config['UPLOAD_FOLDER'], folder)
                    os.makedirs(dest, exist_ok=True)
                    path = os.path.join(dest, filename)
                    file.save(path)
                    return path
                return None

            valid_id_path = dti_path = bir_path = business_permit_path = None

            if business_type == 'individual':
                f = request.files.get('valid_id')
                if not f or not f.filename:
                    return render_template('seller_register.html', error='Valid ID is required for individual sellers.')
                valid_id_path = save_uploaded_file(f, 'seller_docs')
            elif business_type == 'business':
                for field, key in [('valid_id_business', 'valid_id'), ('dti', 'dti'), ('bir', 'bir'), ('business_permit', 'business_permit')]:
                    f = request.files.get(field)
                    if not f or not f.filename:
                        return render_template('seller_register.html', error=f'{field.replace("_", " ").title()} is required.')
                valid_id_path        = save_uploaded_file(request.files.get('valid_id_business'), 'seller_docs')
                dti_path             = save_uploaded_file(request.files.get('dti'), 'seller_docs')
                bir_path             = save_uploaded_file(request.files.get('bir'), 'seller_docs')
                business_permit_path = save_uploaded_file(request.files.get('business_permit'), 'seller_docs')

            # -- Update Supabase auth password -----------------------------
            uid = stored.get('uid')
            if uid:
                try:
                    sb.auth.admin.update_user_by_id(uid, {'password': password})
                    print(f"Supabase password set for seller {email}")
                except Exception as pe:
                    print(f"Warning: could not set Supabase password for seller: {pe}")

            # -- Ban the auth account until admin approves -----------------
            if uid:
                try:
                    sb_admin.auth.admin.update_user_by_id(uid, {'ban_duration': '876600h'})
                    print(f"Supabase auth account banned (pending approval) for seller {email}")
                except Exception as be:
                    print(f"Warning: could not ban seller auth account: {be}")

            # -- Do NOT insert into Supabase users table yet ---------------
            # Profile will be inserted into Supabase users table only when admin approves.

            # -- Insert into Supabase pending_sellers (primary � works without MySQL) --
            try:
                sb_admin.table('pending_sellers').upsert({
                    'supabase_uid':        uid,
                    'email':               email,
                    'first_name':          first_name,
                    'last_name':           last_name,
                    'business_name':       business_name,
                    'business_type':       business_type,
                    'phone':               phone_number,
                    'house_street':        house_no_street,
                    'region':              region,
                    'province':            province,
                    'city':                municipality,
                    'barangay':            barangay,
                    'zip_code':            zip_code,
                    'valid_id_path':       valid_id_path,
                    'dti_path':            dti_path,
                    'bir_path':            bir_path,
                    'business_permit_path': business_permit_path,
                    'status':              'pending',
                }).execute()
                print(f"Inserted into Supabase pending_sellers for {email}")
            except Exception as sb_err:
                print(f"Warning: Supabase pending_sellers insert failed: {sb_err}")

            # MySQL mirror removed

            # Clean up OTP storage
            otp_storage.pop(email, None)

            flash('Your seller application has been submitted! We will review it within 2-3 business days.', 'success')
            return redirect(url_for('login'))

        except Exception as e:
            import traceback; traceback.print_exc()
            flash(f'An error occurred: {e}', 'error')
            return render_template('seller_register.html', error=f'An error occurred: {e}')

    # GET
    return render_template('seller_register.html')
    
#----------------------------------------------------------------------
                         #FORGOT PASSWORD RELATED ROUTES
#----------------------------------------------------------------------

@app.route('/forgot_password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        if 'email' in request.form:
            email = request.form['email'].strip()
            try:
                # Send OTP via Supabase (requires Email OTP enabled in Supabase dashboard)
                sb.auth.reset_password_email(email)
                session['reset_email'] = email
                flash("A password reset code has been sent to your email.", "success")
                return render_template('forgot_password.html',
                                       email_sent=True, step='code',
                                       reset_email=email)
            except AuthApiError as e:
                print(f"Supabase reset_password_for_email error: {e}")
                # Always show success to avoid email enumeration
                session['reset_email'] = email
                flash("If that email is registered, a reset code has been sent.", "success")
                return render_template('forgot_password.html',
                                       email_sent=True, step='code',
                                       reset_email=email)
            except Exception as e:
                import traceback; traceback.print_exc()
                flash("An error occurred. Please try again.", "error")
                return redirect(url_for('forgot_password'))

    return render_template('forgot_password.html')

@app.route('/verify_reset_code', methods=['POST'])
def verify_reset_code():
    entered_code = (request.form.get('reset_code') or '').strip()
    # Accept email from hidden form field OR session (belt-and-suspenders)
    email = (request.form.get('reset_email') or session.get('reset_email', '')).strip()

    print(f"DEBUG verify_reset_code: code='{entered_code}', email='{email}'")

    if not entered_code or not email:
        flash("Session expired. Please start over.", "error")
        return redirect(url_for('forgot_password'))

    # Keep email in session for the next step
    session['reset_email'] = email

    try:
        res = sb.auth.verify_otp({
            'email': email,
            'token': entered_code,
            'type': 'recovery',
        })
        print(f"DEBUG verify_reset_code: user={res.user}, session={res.session}")

        if res.user and res.session:
            session['reset_access_token']  = res.session.access_token
            session['reset_refresh_token'] = res.session.refresh_token
            session['reset_uid']           = res.user.id
            return render_template('forgot_password.html',
                                   email_sent=True, step='password',
                                   code_verified=True, reset_email=email)
        else:
            flash("Invalid reset code. Please try again.", "error")
            return render_template('forgot_password.html',
                                   email_sent=True, step='code', reset_email=email)

    except AuthApiError as e:
        print(f"Supabase verify_otp AuthApiError: {e}")
        flash("Invalid or expired code. Please try again.", "error")
        return render_template('forgot_password.html',
                               email_sent=True, step='code', reset_email=email)
    except Exception as e:
        import traceback; traceback.print_exc()
        flash("An error occurred. Please try again.", "error")
        return render_template('forgot_password.html',
                               email_sent=True, step='code', reset_email=email)


@app.route('/reset_password', methods=['POST'])
def reset_password():
    """Update the password using the user's own session token (no admin key needed)."""
    new_password     = request.form.get('new_password', '')
    confirm_password = request.form.get('confirm_password', '')
    access_token     = session.get('reset_access_token')
    refresh_token    = session.get('reset_refresh_token')
    email            = session.get('reset_email', '')

    print(f"DEBUG reset_password: uid={session.get('reset_uid')}, has_token={bool(access_token)}")

    if not access_token:
        flash("Session expired. Please start over.", "error")
        return redirect(url_for('forgot_password'))

    if not new_password:
        flash("Password cannot be empty.", "error")
        return render_template('forgot_password.html', email_sent=True, step='password', code_verified=True)

    if new_password != confirm_password:
        flash("Passwords do not match. Please try again.", "error")
        return render_template('forgot_password.html', email_sent=True, step='password', code_verified=True)

    if len(new_password) < 6:
        flash("Password must be at least 6 characters.", "error")
        return render_template('forgot_password.html', email_sent=True, step='password', code_verified=True)

    try:
        from supabase import create_client
        from supabase_config import SUPABASE_URL, SUPABASE_ANON

        # Create a client authenticated as the user using their recovery session
        user_client = create_client(SUPABASE_URL, SUPABASE_ANON)
        user_client.auth.set_session(access_token, refresh_token or access_token)

        # Update password as the authenticated user � no admin key needed
        user_client.auth.update_user({'password': new_password})

        print(f"DEBUG reset_password: password updated successfully")

        # Password updated in Supabase auth above

        # Clear all reset session keys
        for k in ('reset_code', 'reset_uid', 'reset_email',
                  'reset_access_token', 'reset_refresh_token', 'user_email'):
            session.pop(k, None)

        flash("Your password has been reset successfully!", "success")
        return redirect(url_for('login'))

    except AuthApiError as e:
        print(f"Supabase reset password AuthApiError: {e}")
        flash(f"Failed to reset password: {e.message}", "error")
        return render_template('forgot_password.html', email_sent=True, step='password', code_verified=True)
    except Exception as e:
        import traceback; traceback.print_exc()
        flash("An error occurred. Please try again.", "error")
        return render_template('forgot_password.html', email_sent=True, step='password', code_verified=True)

@app.route('/change-password', methods=['POST'])
def change_password():
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'You need to log in to change your password.'}), 401
    try:
        data = request.get_json() if request.is_json else request.form
        old_password     = data.get('old_password')
        new_password     = data.get('new_password')
        confirm_password = data.get('confirm_password')
        if not all([old_password, new_password, confirm_password]):
            return jsonify({'success': False, 'message': 'All fields are required.'}), 400
        if new_password != confirm_password:
            return jsonify({'success': False, 'message': 'New password and confirm password do not match.'}), 400
        user_email = session.get('email')
        # Verify old password via Supabase sign-in
        try:
            sb.auth.sign_in_with_password({'email': user_email, 'password': old_password})
        except Exception:
            return jsonify({'success': False, 'message': 'Incorrect current password.'}), 400
        # Update password in Supabase auth
        uid_res = sb_admin.table('users').select('id').eq('email', user_email).limit(1).execute()
        if uid_res.data:
            sb_admin.auth.admin.update_user_by_id(uid_res.data[0]['id'], {'password': new_password})
        return jsonify({'success': True, 'message': 'Password updated successfully!'})
    except Exception as e:
        return jsonify({'success': False, 'message': f'An error occurred: {str(e)}'}), 500

@app.route('/check-old-password', methods=['POST'])
def check_old_password():
    if session.get('user_id') is None:
        return jsonify(valid=False), 401
    data = request.get_json()
    old_password = data.get('old_password')
    user_email = session.get('email')
    try:
        sb.auth.sign_in_with_password({'email': user_email, 'password': old_password})
        return jsonify(valid=True)
    except Exception:
        return jsonify(valid=False)


#----------------------------------------------------------------------
                         #HOMEPAGE RELATED ROUTES
#----------------------------------------------------------------------

@app.route('/homepage')
def homepage():
    # Ensure the user is logged in
    if 'user_id' not in session:
        return redirect(url_for('home'))

    page = request.args.get('page', 1, type=int)
    per_page = 12

    user_name = get_user_name_from_session(default='User')

    # Fetch all products from Supabase
    all_products_raw = _fetch_products_from_supabase()
    total_count = len(all_products_raw)
    total_pages = max(1, (total_count + per_page - 1) // per_page)
    page = max(1, min(page, total_pages))
    offset = (page - 1) * per_page
    all_products = all_products_raw[offset: offset + per_page]

    promotional_products = get_promotional_products(limit=20)

    # Build a promo lookup keyed by product id for the product grid cards
    promo_map = {p['id']: p for p in promotional_products}
    for prod in all_products:
        if prod['id'] in promo_map:
            pp = promo_map[prod['id']]
            prod['promotion_type']     = pp.get('promotion_type', '')
            prod['promotion_discount'] = pp.get('promotion_discount', 0)
            prod['promotion_code']     = pp.get('promotion_code', '')

    # Fetch user's wishlist product IDs for heart icon state
    wishlist_product_ids = _get_wishlist_ids()

    return render_template('homepage.html',
                           user_name=user_name,
                           user_email=session.get('email', 'User'),
                           all_products=all_products,
                           promotional_products=promotional_products[:4],
                           current_page=page,
                           total_pages=total_pages,
                           total_products=total_count,
                           wishlist_product_ids=wishlist_product_ids)
@app.route('/search')
def search():
    user_name = None
    if 'user_id' in session:
        user_name = get_user_name_from_session()

    query    = request.args.get('query', '').strip()
    category = request.args.get('category', '').strip()
    sort_by  = request.args.get('sort', 'relevance')
    page     = request.args.get('page', 1, type=int)
    per_page = 12

    if not query:
        return redirect(url_for('home'))

    products    = []
    categories  = []
    total_count = 0
    total_pages = 0

    try:
        # Build Supabase query — search name, description, category, variations
        q = f'%{query}%'
        sb_q = sb_admin.table('products') \
            .select('id, name, category, description, price, image, quantity, sold, rating, seller_email, variations, sizes') \
            .eq('is_active', True) \
            .or_(f'name.ilike.{q},description.ilike.{q},category.ilike.{q},variations.ilike.{q}')

        if category:
            sb_q = sb_q.eq('category', category)

        # Sorting
        if sort_by == 'price_low':
            sb_q = sb_q.order('price', desc=False)
        elif sort_by == 'price_high':
            sb_q = sb_q.order('price', desc=True)
        elif sort_by == 'newest':
            sb_q = sb_q.order('id', desc=True)
        elif sort_by == 'popular':
            sb_q = sb_q.order('sold', desc=True)
        elif sort_by == 'rating':
            sb_q = sb_q.order('rating', desc=True)
        else:  # relevance — sort by sold + rating
            sb_q = sb_q.order('sold', desc=True)

        result = sb_q.execute()
        all_products = result.data or []

        # Exclude flagged
        all_products = [p for p in all_products
                        if not (p.get('flagged_at') and str(p.get('flagged_at')).strip())]

        total_count = len(all_products)
        total_pages = (total_count + per_page - 1) // per_page
        offset = (page - 1) * per_page
        products = all_products[offset:offset + per_page]

        # Normalize types
        for p in products:
            p['price']    = float(p.get('price') or 0)
            p['quantity'] = int(p.get('quantity') or 0)
            p['sold']     = int(p.get('sold') or 0)
            p['rating']   = round(float(p.get('rating') or 0), 1) or None

        # Distinct categories from results
        categories = sorted({p['category'] for p in all_products if p.get('category')})

        # Enrich products with active promotion data
        promotional_products = get_promotional_products(limit=200)
        promo_map = {pp['id']: pp for pp in promotional_products}
        for prod in products:
            if prod['id'] in promo_map:
                pp = promo_map[prod['id']]
                prod['promotion_type']     = pp.get('promotion_type', '')
                prod['promotion_discount'] = pp.get('promotion_discount', 0)
                prod['promotion_code']     = pp.get('promotion_code', '')

    except Exception as e:
        print(f'[search] Supabase error: {e}')
        promotional_products = []

    return render_template('search_results.html',
                           products=products,
                           promotional_products=promotional_products[:4],
                           query=query,
                           user_email=session.get('email', 'User'),
                           category=category,
                           sort_by=sort_by,
                           categories=categories,
                           current_page=page,
                           total_pages=total_pages,
                           total_count=total_count,
                           per_page=per_page,
                           wishlist_product_ids=_get_wishlist_ids(),
                           user_name=user_name)

@app.route('/api/search-suggestions')
def search_suggestions():
    query = request.args.get('query', '').strip()
    if not query or len(query) < 2:
        return jsonify({'success': False, 'suggestions': []})
    try:
        q = f'%{query}%'
        res = sb_admin.table('products').select('name, category').eq('is_active', True).or_(f'name.ilike.{q},category.ilike.{q}').order('sold', desc=True).limit(8).execute()
        suggestions = [{'name': p['name'], 'category': p['category']} for p in (res.data or [])]
        return jsonify({'success': True, 'suggestions': suggestions})
    except Exception as err:
        print(f"search_suggestions error: {err}")
        return jsonify({'success': False, 'suggestions': []})


@app.route('/suits')
def Suit_page():
    user_name = get_user_name_from_session() if 'user_id' in session else None
    products = _fetch_products_from_supabase(categories=['SUITS', 'BLAZERS'])
    promotional_products = get_promotional_products(limit=4, category_filter=['SUITS', 'BLAZERS'])
    wishlist_product_ids = _get_wishlist_ids()
    return render_template('suits.html', products=products, user_name=user_name,
                           user_email=session.get('email', 'User'), promotional_products=promotional_products,
                           wishlist_product_ids=wishlist_product_ids)

@app.route('/casual')
def casual_page():
    user_name = get_user_name_from_session() if 'user_id' in session else None
    products = _fetch_products_from_supabase(categories=['SHIRTS', 'PANTS'])
    promotional_products = get_promotional_products(limit=4, category_filter=['SHIRTS', 'PANTS'])
    wishlist_product_ids = _get_wishlist_ids()
    return render_template('casual.html', products=products, user_name=user_name,
                           user_email=session.get('email', 'User'), promotional_products=promotional_products,
                           wishlist_product_ids=wishlist_product_ids)

@app.route('/outerwear')
def outerwear_page():
    user_name = get_user_name_from_session() if 'user_id' in session else None
    products = _fetch_products_from_supabase(categories=['OUTERWEAR', 'JACKETS'])
    promotional_products = get_promotional_products(limit=4, category_filter=['OUTERWEAR', 'JACKETS'])
    wishlist_product_ids = _get_wishlist_ids()
    return render_template('outerwear.html', products=products, user_name=user_name,
                           user_email=session.get('email', 'User'), promotional_products=promotional_products,
                           wishlist_product_ids=wishlist_product_ids)

@app.route('/activewear')
def activewear_page():
    user_name = get_user_name_from_session() if 'user_id' in session else None
    products = _fetch_products_from_supabase(categories=['ACTIVEWEAR', 'FITNESS'])
    promotional_products = get_promotional_products(limit=4, category_filter=['ACTIVEWEAR', 'FITNESS'])
    wishlist_product_ids = _get_wishlist_ids()
    return render_template('activewear.html', products=products, user_name=user_name,
                           user_email=session.get('email', 'User'), promotional_products=promotional_products,
                           wishlist_product_ids=wishlist_product_ids)

@app.route('/shoes')
def shoes_page():
    user_name = get_user_name_from_session() if 'user_id' in session else None
    products = _fetch_products_from_supabase(categories=['SHOES', 'ACCESSORIES'])
    promotional_products = get_promotional_products(limit=4, category_filter=['SHOES', 'ACCESSORIES'])
    wishlist_product_ids = _get_wishlist_ids()
    return render_template('shoes.html', products=products, user_name=user_name,
                           user_email=session.get('email', 'User'), promotional_products=promotional_products,
                           wishlist_product_ids=wishlist_product_ids)

@app.route('/grooming')
def grooming_page():
    user_name = get_user_name_from_session() if 'user_id' in session else None
    products = _fetch_products_from_supabase(categories=['GROOMING'])
    promotional_products = get_promotional_products(limit=4, category_filter='GROOMING')
    wishlist_product_ids = _get_wishlist_ids()
    return render_template('grooming.html', products=products, user_name=user_name,
                           user_email=session.get('email', 'User'), promotional_products=promotional_products,
                           wishlist_product_ids=wishlist_product_ids)

@app.route('/view_product/<int:product_id>')
def view_product(product_id):
    # Allow viewing without login, but get user data if logged in
    user_name = None
    if 'user_id' in session:
        user_name = get_user_name_from_session()

    product = None
    reviews = []
    review_stats = {'total_reviews': 0, 'average_rating': 0, 'rating_distribution': {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}}

    # -- PRIMARY: Supabase -----------------------------------------------------
    try:
        # Use list query + take first result � avoids maybeSingle() issues
        sb_res = sb_admin.table('products').select('*').eq('id', product_id).limit(1).execute()
        print(f"?? view_product({product_id}) Supabase: count={len(sb_res.data) if sb_res.data else 0}")

        sb_product_data = sb_res.data[0] if sb_res.data else None

        if sb_product_data:
            product = dict(sb_product_data)

            # Get seller info
            seller_email_key = (product.get('seller_email') or '').strip()
            seller_rows = []

            if seller_email_key:
                try:
                    r = sb_admin.table('users').select(
                        'first_name, last_name, business_name'
                    ).eq('email', seller_email_key).limit(1).execute()
                    seller_rows = r.data or []
                except Exception as _e:
                    print(f"[view_product] seller exact match error: {_e}")

                if not seller_rows:
                    try:
                        r2 = sb_admin.table('users').select(
                            'first_name, last_name, business_name'
                        ).ilike('email', seller_email_key).limit(1).execute()
                        seller_rows = r2.data or []
                    except Exception as _e2:
                        print(f"[view_product] seller ilike match error: {_e2}")

            print(f"[view_product] seller_email={seller_email_key!r}, rows={seller_rows}")

            if seller_rows:
                u = seller_rows[0]
                biz   = (u.get('business_name') or '').strip()
                first = (u.get('first_name') or '').strip()
                last  = (u.get('last_name') or '').strip()
                full_name = f"{first} {last}".strip()
                print(f"[view_product] biz={biz!r}, first={first!r}, last={last!r}, full_name={full_name!r}")
                # Priority: business_name → full name → email → 'Seller'
                display_name = biz or full_name or seller_email_key or 'Seller'
                product['seller_name']            = display_name
                product['business_name']          = display_name
                product['seller_profile_picture'] = None
            else:
                # No user row found — use email as display name
                product['seller_name']            = seller_email_key or 'Seller'
                product['business_name']          = seller_email_key or 'Seller'
                product['seller_profile_picture'] = None

            # Get reviews
            try:
                rev_res = sb_admin.table('reviews').select(
                    'rating, review_text, review_images, customer_email, created_at, seller_response, response_date'
                ).eq('product_id', product_id).order('created_at', desc=True).execute()

                raw_reviews = rev_res.data or []
                for r in raw_reviews:
                    try:
                        cu = sb_admin.table('users').select(
                            'first_name, last_name, profile_picture'
                        ).eq('email', r.get('customer_email', '')).maybeSingle().execute()
                        if cu.data:
                            r['customer_name'] = (
                                f"{cu.data.get('first_name', '')} {cu.data.get('last_name', '')}".strip()
                                or r.get('customer_email', 'Customer')
                            )
                            r['profile_picture'] = cu.data.get('profile_picture')
                        else:
                            r['customer_name'] = r.get('customer_email', 'Customer')
                            r['profile_picture'] = None
                    except Exception:
                        r['customer_name'] = r.get('customer_email', 'Customer')
                        r['profile_picture'] = None

                    # Parse date strings to datetime objects
                    for date_field in ('created_at', 'response_date'):
                        if r.get(date_field) and isinstance(r[date_field], str):
                            try:
                                from datetime import datetime as _dt
                                r[date_field] = _dt.fromisoformat(r[date_field].replace('Z', '+00:00'))
                            except Exception:
                                r[date_field] = None

                reviews = raw_reviews
                if reviews:
                    total_rating = sum(rv.get('rating', 0) for rv in reviews)
                    review_stats['total_reviews'] = len(reviews)
                    review_stats['average_rating'] = round(total_rating / len(reviews), 1)
                    for rv in reviews:
                        rating_val = rv.get('rating', 0)
                        if rating_val in review_stats['rating_distribution']:
                            review_stats['rating_distribution'][rating_val] += 1
            except Exception as rev_err:
                print(f"?? Reviews fetch failed: {rev_err}")

    except Exception as sb_err:
        print(f"?? Supabase view_product failed: {sb_err}")

    # MySQL fallback removed  Supabase is the only source

    # -- Promotions ------------------------------------------------------------
    active_promotion = None
    if product:
        try:
            active_promotion = get_active_promotions_for_product(
                product['id'], product.get('seller_email', ''), product.get('category', '')
            )
        except Exception:
            active_promotion = None

        if active_promotion:
            try:
                promotional_price, discount_amount = calculate_promotional_price(
                    product['price'], active_promotion
                )
                product['has_promotion'] = True
                product['promotional_price'] = float(promotional_price) if promotional_price is not None else float(product.get('price', 0))
                product['discount_amount'] = float(discount_amount) if discount_amount is not None else 0.0
                price_f = float(product['price']) if product.get('price') else 0.0
                product['discount_percentage'] = round((product['discount_amount'] / price_f) * 100, 1) if price_f > 0 else 0
            except Exception:
                product['has_promotion'] = False
                product['promotional_price'] = float(product.get('price', 0))
                product['discount_amount'] = 0.0
                product['discount_percentage'] = 0
        else:
            product['has_promotion'] = False
            product['promotional_price'] = float(product.get('price', 0))
            product['discount_amount'] = 0.0
            product['discount_percentage'] = 0

    if product:
        # Parse image_colors into a dict { colorName.lower() ? imageUrl } for JS
        image_colors_dict = _parse_image_colors_dict(
            product.get('image_colors', ''),
            product.get('image', '')
        )
        return render_template('view_product.html',
                               product=product,
                               seller_name=product.get('seller_name', ''),
                               business_name=product.get('business_name', 'Seller'),
                               user_name=user_name,
                               user_email=session.get('email', 'User'),
                               reviews=reviews,
                               review_stats=review_stats,
                               active_promotion=active_promotion,
                               image_colors_dict=image_colors_dict,
                               wishlist_product_ids=_get_wishlist_ids())
    else:
        print(f"? view_product({product_id}): product not found in Supabase or MySQL")
        flash('Product not found or is no longer available.', 'error')
        return redirect(url_for('home'))

@app.route('/homepage')
def home_page():
    return render_template('homepage.html')

#----------------------------------------------------------------------
                         #PROFILE MANAGEMENT RELATED ROUTES
#----------------------------------------------------------------------

@app.route('/profile', methods=['GET', 'POST'])
def profile():
    # Check if user is logged in
    user_email = session.get('email')

    if not user_email:
        flash('You need to log in to access your profile.', 'error')
        return redirect(url_for('login'))

    if request.method == 'POST':
        connection = None
        cursor = None
        try:
            # Get form data
            first_name = request.form.get('first_name')
            last_name = request.form.get('last_name')
            email = request.form.get('email')
            phone_number = request.form.get('phone_number')
            business_name = request.form.get('business_name')
            address = request.form.get('address')
            vehicle_type = request.form.get('vehicle_type')
            vehicle_model = request.form.get('vehicle_model')
            vehicle_plate_number = request.form.get('vehicle_plate_number')
            vehicle_year_model = request.form.get('vehicle_year_model')

            # -- Update Supabase users table -------------------------------
            supabase_update = {
                'first_name': first_name,
                'last_name':  last_name,
                'phone':      phone_number,   # Supabase column is 'phone'
            }
            if business_name is not None:
                supabase_update['business_name'] = business_name

            try:
                sb_admin.table('users').update(supabase_update).eq('email', user_email).execute()
            except Exception as sb_err:
                print(f"?? Supabase profile update error: {sb_err}")

            # Handle profile picture upload
            profile_picture_filename = None
            if 'profile_picture' in request.files:
                file = request.files['profile_picture']
                if file and file.filename != '':
                    if file.filename.lower().endswith(('.png', '.jpg', '.jpeg', '.gif')):
                        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                        random_string = ''.join(random.choices(string.ascii_letters + string.digits, k=6))
                        file_extension = file.filename.rsplit('.', 1)[1].lower()
                        profile_picture_filename = f"{timestamp}_{random_string}_profile.{file_extension}"
                        file_path = os.path.join(app.config['UPLOAD_FOLDER'], profile_picture_filename)
                        file.save(file_path)
                    else:
                        return jsonify({'success': False, 'message': 'Please upload a valid image file (PNG, JPG, JPEG, GIF)'}), 400

            # MySQL mirror removed

            # Update session first_name
            if first_name:
                session['first_name'] = first_name
            if address:
                session['address'] = address
            # Keep business_name in session up to date
            if business_name:
                session['business_name'] = business_name

            return jsonify({'success': True, 'message': 'Profile updated successfully'})

        except Exception as e:
            if connection:
                try:
                    connection.rollback()
                except Exception:
                    pass
            return jsonify({'success': False, 'message': str(e)}), 400

        finally:
            if cursor:
                cursor.close()
            if connection:
                connection.close()

    # -- GET request � fetch user data from Supabase -----------------------
    try:
        try:
            res = sb_admin.table('users').select(
                'id, first_name, last_name, email, phone, role, business_name, '
                'house_street, barangay, city, province, region, zip_code'
            ).eq('email', user_email).execute()
        except Exception:
            # business_name column may not exist yet � select without it
            res = sb_admin.table('users').select(
                'id, first_name, last_name, email, phone, role, '
                'house_street, barangay, city, province, region, zip_code'
            ).eq('email', user_email).execute()

        if res.data:
            u = res.data[0]
            address = ', '.join(filter(None, [
                u.get('house_street', ''),
                u.get('barangay', ''),
                u.get('city', ''),
                u.get('province', ''),
                u.get('region', ''),
                u.get('zip_code', ''),
            ]))
            user_data = {
                'id':                   u.get('id'),
                'first_name':           u.get('first_name', ''),
                'last_name':            u.get('last_name', ''),
                'email':                u.get('email', user_email),
                'phone_number':         u.get('phone', ''),
                'address':              address,
                'business_name':        u.get('business_name', '') or '',
                'user_type':            u.get('role', session.get('user_type', 'buyer')),
                'profile_picture':      None,
                'vehicle_type':         '',
                'vehicle_model':        '',
                'vehicle_plate_number': '',
                'vehicle_year_model':   '',
            }
        else:
            user_data = {
                'id':                   session.get('user_id'),
                'first_name':           session.get('first_name', ''),
                'last_name':            session.get('last_name', ''),
                'email':                user_email,
                'phone_number':         '',
                'address':              session.get('address', ''),
                'business_name':        '',
                'user_type':            session.get('user_type', 'buyer'),
                'profile_picture':      None,
                'vehicle_type':         '',
                'vehicle_model':        '',
                'vehicle_plate_number': '',
                'vehicle_year_model':   '',
            }

        # MySQL supplement removed  data comes from Supabase only

        # -- For riders: also check Supabase rider_vehicles table ----------
        # Vehicle data is stored there after admin approval (primary source).
        # Only fill in if MySQL didn't already provide values.
        if user_data.get('user_type', '').lower() == 'rider':
            try:
                supabase_uid = res.data[0].get('id') if res.data else None
                if supabase_uid:
                    rv_res = sb_admin.table('rider_vehicles').select(
                        'vehicle_type, vehicle_model, plate_number, year_model'
                    ).eq('user_id', supabase_uid).execute()
                    if rv_res.data:
                        rv = rv_res.data[0]
                        # Supabase rider_vehicles is the authoritative source � always use it
                        user_data['vehicle_type']         = rv.get('vehicle_type', '') or ''
                        user_data['vehicle_model']        = rv.get('vehicle_model', '') or ''
                        user_data['vehicle_plate_number'] = rv.get('plate_number', '') or ''
                        user_data['vehicle_year_model']   = rv.get('year_model', '') or ''
            except Exception as rv_err:
                print(f"?? Supabase rider_vehicles fetch skipped: {rv_err}")

        user_name = f"{user_data['first_name']} {user_data['last_name']}".strip() or 'User'
        return render_template('profile.html',
                               user_data=user_data,
                               user_name=user_name,
                               user_email=user_email)

    except Exception as e:
        flash(f'Error fetching profile: {str(e)}', 'error')
        return redirect(url_for('home'))

@app.route('/upload-profile-picture', methods=['POST'])
def upload_profile_picture():
    user_id = session.get('user_id')
    if user_id is None:
        return jsonify({'success': False, 'message': 'You need to log in'}), 401

    if 'profile_picture' not in request.files:
        return jsonify({'success': False, 'message': 'No file selected'}), 400

    file = request.files['profile_picture']
    if file.filename == '':
        return jsonify({'success': False, 'message': 'No file selected'}), 400

    if file and file.filename.lower().endswith(('.png', '.jpg', '.jpeg', '.gif')):
        try:
            # Generate unique filename
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            random_string = ''.join(random.choices(string.ascii_letters + string.digits, k=6))
            file_extension = file.filename.rsplit('.', 1)[1].lower()
            filename = f"{timestamp}_{random_string}_profile.{file_extension}"
            
            # Save file
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(file_path)
            
            # Update database � Supabase first, MySQL as fallback
            try:
                sb_admin.table('users').update({'profile_picture': filename}).eq('email', session.get('email')).execute()
            except Exception as sb_err:
                print(f"?? Supabase profile picture update error: {sb_err}")

            # MySQL mirror removed
            
            return jsonify({
                'success': True, 
                'message': 'Profile picture updated successfully',
                'filename': filename
            })
            
        except Exception as e:
            return jsonify({'success': False, 'message': str(e)}), 500
            
        finally:
            if 'cursor' in locals():
                cursor.close()
            if 'connection' in locals():
                connection.close()
    else:
        return jsonify({'success': False, 'message': 'Please upload a valid image file (PNG, JPG, JPEG, GIF)'}), 400

#----------------------------------------------------------------------
                         #SELLER RELATED ROUTES
#----------------------------------------------------------------------

@app.route('/seller')
def seller_page():
    # Ensure the user is logged in
    if 'user_id' not in session:
        return redirect(url_for('home'))  # Redirect to login if not logged in
    return render_template('seller_dashboard.html')  # Render the seller's page

@app.route('/seller_dashboard')
def seller_dashboard():
    if 'email' not in session:
        return redirect(url_for('home'))

    seller_email = session['email']

    # -- Get seller name from Supabase ------------------------------------
    seller_name = session.get('first_name', 'Seller')
    try:
        sb_res = sb_admin.table('users').select('first_name, last_name, business_name').eq('email', seller_email).execute()
        if sb_res.data:
            u = sb_res.data[0]
            seller_name = u.get('business_name') or f"{u.get('first_name', '')} {u.get('last_name', '')}".strip() or 'Seller'
    except Exception as e:
        print(f"seller_dashboard name fetch failed: {e}")

    # -- Safe defaults ----------------------------------------------------
    total_sales     = 0.0
    total_earnings  = 0.0
    total_items     = 0
    avg_order_value = 0.0
    total_products  = 0
    status_counts   = {k: 0 for k in [
        'Pending', 'Confirmed', 'Preparing', 'Ready for Pickup',
        'Out for Delivery', 'Delivered', 'Completed', 'Cancelled'
    ]}

    # Build 12-month chart skeleton
    from datetime import datetime as _dt, timedelta as _td
    now = _dt.now()
    chart_dates    = []
    chart_sales    = []
    chart_earnings = []
    for i in range(11, -1, -1):
        m = now - _td(days=i * 30)
        chart_dates.append(m.strftime('%Y-%m'))
        chart_sales.append(0)
        chart_earnings.append(0)

    try:
        # All orders for this seller
        orders_res = sb_admin.table('orders') \
            .select('id, status, total_price, date, quantity') \
            .eq('seller_email', seller_email) \
            .execute()
        all_orders = orders_res.data or []

        # Status distribution
        status_alias = {
            'waiting for pickup': 'Ready for Pickup',
            'for pickup':         'Ready for Pickup',
            'in transit':         'Out for Delivery',
            'out for delivery':   'Out for Delivery',
            'heading to seller':  'Out for Delivery',
            'shipped':            'Out for Delivery',
        }
        for o in all_orders:
            raw = (o.get('status') or '').strip()
            key = status_alias.get(raw.lower(), raw)
            if key in status_counts:
                status_counts[key] += 1

        # Stats from completed/delivered orders
        done_orders = [o for o in all_orders if (o.get('status') or '').lower() in ('completed', 'delivered')]
        for o in done_orders:
            val = float(o.get('total_price') or 0)
            total_sales    += val
            total_earnings += val * 0.95   # 5% platform fee
            total_items    += int(o.get('quantity') or 1)

        avg_order_value = (total_sales / len(done_orders)) if done_orders else 0.0

        # Monthly chart data
        monthly = {}
        for o in done_orders:
            raw_date = o.get('date')
            if not raw_date:
                continue
            try:
                month_key = str(raw_date)[:7]   # 'YYYY-MM'
                val = float(o.get('total_price') or 0)
                if month_key not in monthly:
                    monthly[month_key] = {'sales': 0.0, 'earnings': 0.0}
                monthly[month_key]['sales']    += val
                monthly[month_key]['earnings'] += val * 0.95
            except Exception:
                pass

        chart_sales    = [monthly.get(m, {}).get('sales',    0) for m in chart_dates]
        chart_earnings = [monthly.get(m, {}).get('earnings', 0) for m in chart_dates]

        # Total products
        prod_res = sb_admin.table('products') \
            .select('id', count='exact') \
            .eq('seller_email', seller_email) \
            .execute()
        total_products = prod_res.count or 0

    except Exception as e:
        print(f"seller_dashboard Supabase error: {e}")

    end_date   = now.strftime('%Y-%m-%d')
    start_date = (now - _td(days=7)).strftime('%Y-%m-%d')

    return render_template('seller_dashboard.html',
                           total_sales="{:.2f}".format(total_sales),
                           total_earnings="{:.2f}".format(total_earnings),
                           total_items=total_items,
                           pending_orders=status_counts.get('Pending', 0),
                           cancelled_orders=status_counts.get('Cancelled', 0),
                           avg_order_value="{:.2f}".format(avg_order_value),
                           total_products=total_products,
                           start_date=start_date,
                           end_date=end_date,
                           user_name=seller_name,
                           user_email=seller_email,
                           order_status_counts=status_counts,
                           chart_dates=chart_dates,
                           chart_sales=chart_sales,
                           chart_earnings=chart_earnings)
@app.route('/reports_analytics')
def reports_analytics():
    if 'email' not in session:
        return redirect(url_for('home'))
    
    if session.get('user_type', '').lower() != 'seller':
        flash('Access denied. Seller privileges required.', 'error')
        return redirect(url_for('login'))

    # -- Get seller name from Supabase (works even when MySQL is down) -----
    seller_name = session.get('first_name', 'Seller')
    try:
        sb_res = sb_admin.table('users').select('first_name, last_name, business_name').eq('email', session['email']).execute()
        if sb_res.data:
            u = sb_res.data[0]
            seller_name = u.get('business_name') or f"{u.get('first_name', '')} {u.get('last_name', '')}".strip() or 'Seller'
    except Exception as sb_err:
        print(f"?? Supabase name fetch failed in reports_analytics: {sb_err}")

    seller_email = session['email']
    try:
        from datetime import date as _date
        today = _date.today().isoformat()

        # All orders for this seller
        orders_res = sb_admin.table('orders').select('id, status, total_price, date, quantity, name, received_at, delivered_at, email, product_id').eq('seller_email', seller_email).execute()
        all_orders = orders_res.data or []

        done_orders = [o for o in all_orders if (o.get('status') or '').lower() in ('completed', 'delivered')]
        total_revenue = sum(float(o.get('total_price') or 0) for o in done_orders)
        total_orders  = len(done_orders)
        avg_order_value = (total_revenue / total_orders) if total_orders else 0.0
        total_earnings  = total_revenue * 0.95

        # Top products
        from collections import defaultdict
        prod_sales = defaultdict(lambda: {'total_sold': 0, 'revenue': 0.0, 'name': ''})
        for o in done_orders:
            pid = o.get('product_id') or o.get('name', 'unknown')
            prod_sales[pid]['total_sold'] += int(o.get('quantity') or 1)
            prod_sales[pid]['revenue']    += float(o.get('total_price') or 0)
            prod_sales[pid]['name']        = o.get('name', str(pid))
        top_products = sorted(
            [{'name': v['name'], 'product_id': k, 'total_sold': v['total_sold'],
              'revenue': v['revenue'], 'stock_left': 0, 'avg_rating': 0.0, 'review_count': 0}
             for k, v in prod_sales.items()],
            key=lambda x: x['total_sold'], reverse=True
        )[:5]

        # Status stats
        status_stats = {k: {'count': 0, 'value': 0.0} for k in
            ['pending','confirmed','preparing','ready_for_pickup','out_for_delivery','delivered','completed','cancelled']}
        for o in all_orders:
            key = (o.get('status') or '').lower().replace(' ', '_')
            if key in status_stats:
                status_stats[key]['count'] += 1
                status_stats[key]['value'] += float(o.get('total_price') or 0)

        # Order details
        buyer_emails = list({o['email'] for o in all_orders if o.get('email')})
        buyer_map = {}
        if buyer_emails:
            ur = sb_admin.table('users').select('email, first_name, last_name').in_('email', buyer_emails).execute()
            buyer_map = {u['email']: u for u in (ur.data or [])}

        order_details = []
        for o in sorted(all_orders, key=lambda x: x.get('date') or '', reverse=True)[:100]:
            buyer = buyer_map.get(o.get('email', ''), {})
            buyer_name = f"{buyer.get('first_name','')} {buyer.get('last_name','')}".strip() or 'N/A'
            order_details.append({
                'product_name':    o.get('name', ''),
                'quantity':        int(o.get('quantity') or 0),
                'status':          (o.get('status') or '').lower(),
                'order_date':      o.get('date'),
                'completion_date': o.get('received_at') or o.get('delivered_at'),
                'total_amount':    float(o.get('total_price') or 0),
                'buyer_name':      buyer_name,
            })

        # Promotion performance from Supabase
        promo_res = sb_admin.table('promotions').select('id, name, type, discount_value, start_date, end_date, is_active, current_usage_count').eq('seller_email', seller_email).execute()
        promotion_performance = []
        for p in (promo_res.data or []):
            sd = str(p.get('start_date') or '')[:10]
            ed = str(p.get('end_date') or '')[:10]
            if not p.get('is_active'):
                pstatus = 'ended'
            elif ed < today:
                pstatus = 'expired'
            elif sd <= today <= ed:
                pstatus = 'active'
            else:
                pstatus = 'inactive'
            promotion_performance.append({
                'name': p.get('name',''), 'type': p.get('type',''),
                'discount_value': float(p.get('discount_value') or 0),
                'start_date': sd, 'end_date': ed,
                'usage_count': int(p.get('current_usage_count') or 0),
                'revenue_generated': 0.0, 'status': pstatus,
            })

        # Financial summary
        financial_summary = []
        for o in done_orders[:100]:
            net = float(o.get('total_price') or 0)
            financial_summary.append({
                'order_id': o['id'], 'product_name': o.get('name',''),
                'quantity': int(o.get('quantity') or 1),
                'date_completed': o.get('received_at') or o.get('delivered_at') or o.get('date'),
                'product_sales': net, 'discounts': 0.0, 'net_sales': net,
                'shipping_fee_collected': 50.0, 'platform_commission': net * 0.05,
                'net_earnings': net * 0.95, 'promotion_type': None,
            })

    except Exception as e:
        print(f"reports_analytics Supabase error: {e}")
        import traceback; traceback.print_exc()
        total_revenue = avg_order_value = total_earnings = 0.0
        total_orders = 0
        top_products = order_details = promotion_performance = financial_summary = []
        status_stats = {k: {'count': 0, 'value': 0.0} for k in
            ['pending','confirmed','preparing','ready_for_pickup','out_for_delivery','delivered','completed','cancelled']}

    return render_template('reports_analytics.html',
                         total_revenue="{:.2f}".format(total_revenue),
                         total_orders=total_orders,
                         avg_order_value="{:.2f}".format(avg_order_value),
                         total_earnings="{:.2f}".format(total_earnings),
                         top_products=top_products,
                         status_stats=status_stats,
                         order_details=order_details,
                         promotion_performance=promotion_performance,
                         financial_summary=financial_summary,
                         user_name=seller_name,
                         user_email=session.get('email', 'Seller'))
    cursor.execute("""
        SELECT 
            COALESCE(SUM(total_price), 0) as total_revenue,
            COUNT(*) as total_orders,
            AVG(total_price) as avg_order_value
        FROM orders 
        WHERE seller_email = %s
        AND status IN ('Delivered', 'Completed')
    """, (session['email'],))
    
    analytics = cursor.fetchone()

    # Get total earnings (from completed/delivered orders only)
    # For orders with free shipping, subtract the shipping fee from the total
    cursor.execute("""
        SELECT o.id, o.product_id, o.total_price, o.date, o.seller_email
        FROM orders o
        WHERE o.seller_email = %s 
        AND o.status IN ('Delivered', 'Completed')
    """, (session['email'],))
    
    completed_orders = cursor.fetchall()
    
    # Calculate earnings, subtracting shipping fee for free shipping orders, discounts, and platform commission (5%)
    total_earnings = 0.0
    for order in completed_orders:
        has_free_shipping = False
        order_value = float(order['total_price'])
        
        # Get discount applied for this order
        cursor.execute("""
            SELECT COALESCE(discount_applied, 0) as discount
            FROM promotion_usage
            WHERE order_id = %s
        """, (order['id'],))
        discount_result = cursor.fetchone()
        discount_applied = float(discount_result['discount']) if discount_result else 0.0
        
        # Calculate net sales after discount
        net_sales = order_value - discount_applied
        
        # Check if this order has free shipping promotion
        if order['product_id']:
            cursor.execute("""
                SELECT pr.id
                FROM promotions pr
                LEFT JOIN promotion_products pp ON pr.id = pp.promotion_id
                LEFT JOIN promotion_categories pc ON pr.id = pc.promotion_id
                LEFT JOIN products p ON (pp.product_id = p.id OR pc.category = p.category)
                WHERE pr.seller_email = %s
                AND pr.type = 'free_shipping'
                AND pr.is_active = 1
                AND pr.start_date <= %s
                AND pr.end_date >= %s
                AND (
                    pr.product_scope = 'all' 
                    OR (pr.product_scope = 'specific' AND p.id = %s)
                    OR (pr.product_scope = 'category' AND p.id = %s)
                )
                LIMIT 1
            """, (order['seller_email'], order['date'].date(), order['date'].date(), order['product_id'], order['product_id']))
            
            free_shipping_promo = cursor.fetchone()
            has_free_shipping = free_shipping_promo is not None
        
        # Calculate shipping fee deduction
        shipping_fee_deduction = 0.0
        if has_free_shipping:
            # If free shipping, seller absorbs the shipping cost
            shipping_fee_deduction = 50  # Standard shipping fee
        
        # Calculate platform commission (5% of net sales)
        platform_commission = net_sales * 0.05
        
        # Calculate final earnings: net_sales - shipping_fee_deduction - platform_commission
        order_earnings = net_sales - shipping_fee_deduction - platform_commission
        total_earnings += order_earnings
    
    earnings_data = {'total_earnings': total_earnings}

    # Get top selling products with stock and rating (only from Delivered and Completed orders)
    cursor.execute("""
        SELECT 
            o.name, 
            o.product_id,
            SUM(o.quantity) as total_sold, 
            SUM(o.total_price) as revenue,
            p.quantity as stock_left,
            COALESCE(AVG(r.rating), 0) as avg_rating,
            COUNT(DISTINCT r.id) as review_count
        FROM orders o
        LEFT JOIN products p ON o.product_id = p.id
        LEFT JOIN reviews r ON p.id = r.product_id
        WHERE o.seller_email = %s
        AND o.status IN ('Delivered', 'Completed')
        GROUP BY o.name, o.product_id, p.quantity
        ORDER BY total_sold DESC
        LIMIT 5
    """, (session['email'],))
    
    top_products = cursor.fetchall()
    
    # Safely convert top_products values
    for product in top_products:
        try:
            product['revenue'] = float(product['revenue']) if product['revenue'] is not None else 0.0
            product['total_sold'] = int(product['total_sold']) if product['total_sold'] is not None else 0
            product['stock_left'] = int(product['stock_left']) if product['stock_left'] is not None else 0
            product['avg_rating'] = round(float(product['avg_rating']), 1) if product['avg_rating'] and float(product['avg_rating']) > 0 else 0.0
            product['review_count'] = int(product['review_count']) if product['review_count'] is not None else 0
        except (ValueError, TypeError):
            product['revenue'] = 0.0
            product['total_sold'] = 0
            product['stock_left'] = 0
            product['avg_rating'] = 0.0
            product['review_count'] = 0

    # Get order status breakdown
    try:
        cursor.execute("""
            SELECT 
                status,
                COUNT(*) as count,
                COALESCE(SUM(total_price), 0) as total_value
            FROM orders
            WHERE seller_email = %s
            GROUP BY status
            ORDER BY count DESC
        """, (session['email'],))
        
        order_status_breakdown = cursor.fetchall()
    except Exception as e:
        print(f"Error fetching order status breakdown: {e}")
        order_status_breakdown = []

    # Get detailed order information for the table
    try:
        cursor.execute("""
            SELECT 
                o.name as product_name,
                o.quantity,
                o.status,
                o.date as order_date,
                CASE 
                    WHEN o.status IN ('Completed', 'Delivered') THEN COALESCE(o.received_at, o.delivered_at)
                    ELSE NULL
                END as completion_date,
                o.total_price as total_amount,
                CONCAT(COALESCE(u.first_name, ''), ' ', COALESCE(u.last_name, '')) as buyer_name
            FROM orders o
            LEFT JOIN users u ON o.email = u.email
            WHERE o.seller_email = %s
            ORDER BY o.date DESC
            LIMIT 100
        """, (session['email'],))
        
        order_details = cursor.fetchall()
        print(f"DEBUG: Found {len(order_details)} orders for seller {session['email']}")
        
        # Convert values safely
        for order in order_details:
            try:
                order['quantity'] = int(order['quantity']) if order['quantity'] is not None else 0
                order['total_amount'] = float(order['total_amount']) if order['total_amount'] is not None else 0.0
                # Normalize status to lowercase for consistent display
                if order['status']:
                    order['status'] = order['status'].lower()
                # Clean up buyer name
                if order['buyer_name']:
                    order['buyer_name'] = order['buyer_name'].strip()
                    if order['buyer_name'] == ' ' or order['buyer_name'] == '':
                        order['buyer_name'] = 'N/A'
                else:
                    order['buyer_name'] = 'N/A'
            except (ValueError, TypeError) as e:
                print(f"DEBUG: Error converting order values: {e}")
                order['quantity'] = 0
                order['total_amount'] = 0.0
                order['buyer_name'] = 'N/A'
    except Exception as e:
        print(f"Error fetching order details: {e}")
        import traceback
        traceback.print_exc()
        order_details = []

    # Get promotion performance data
    try:
        cursor.execute("""
            SELECT 
                p.name,
                p.type,
                p.discount_value,
                p.start_date,
                p.end_date,
                COUNT(DISTINCT CASE 
                    WHEN o.status IN ('Completed', 'Delivered') AND pu.id IS NOT NULL
                    THEN pu.id 
                    ELSE NULL 
                END) as usage_count,
                COALESCE(SUM(CASE 
                    WHEN o.status IN ('Completed', 'Delivered') AND pu.id IS NOT NULL 
                    THEN o.total_price 
                    ELSE 0 
                END), 0) as revenue_generated,
                CASE 
                    WHEN p.is_active = 0 THEN 'ended'
                    WHEN p.end_date < CURDATE() THEN 'expired'
                    WHEN p.start_date <= CURDATE() AND p.end_date >= CURDATE() THEN 'active'
                    ELSE 'inactive'
                END as status
            FROM promotions p
            LEFT JOIN promotion_usage pu ON p.id = pu.promotion_id
            LEFT JOIN orders o ON pu.order_id = o.id
            WHERE p.seller_email = %s
            GROUP BY p.id, p.name, p.type, p.discount_value, p.start_date, p.end_date, p.is_active
            ORDER BY p.start_date DESC
        """, (session['email'],))
        
        promotion_performance = cursor.fetchall()
        
        # Convert values safely
        for promo in promotion_performance:
            try:
                promo['discount_value'] = float(promo['discount_value']) if promo['discount_value'] is not None else 0.0
                promo['usage_count'] = int(promo['usage_count']) if promo['usage_count'] is not None else 0
                promo['revenue_generated'] = float(promo['revenue_generated']) if promo['revenue_generated'] is not None else 0.0
            except (ValueError, TypeError):
                promo['discount_value'] = 0.0
                promo['usage_count'] = 0
                promo['revenue_generated'] = 0.0
    except Exception as e:
        print(f"Error fetching promotion performance: {e}")
        promotion_performance = []
    
    # Get financial summary data
    try:
        cursor.execute("""
            SELECT 
                o.id as order_id,
                CASE 
                    WHEN o.status IN ('Completed', 'Delivered') THEN COALESCE(o.received_at, o.delivered_at)
                    ELSE NULL
                END as date_completed,
                o.name as product_name,
                o.quantity as quantity,
                COALESCE(prod.price, 0) as unit_price,
                COALESCE(prod.price * o.quantity, o.total_price) as product_sales,
                CASE 
                    WHEN p.type = 'free_shipping' THEN 0
                    WHEN pu.discount_applied IS NOT NULL AND pu.discount_applied > 0 AND p.type != 'free_shipping' THEN pu.discount_applied
                    WHEN prod.price IS NOT NULL AND (prod.price * o.quantity) > o.total_price 
                        THEN (prod.price * o.quantity) - o.total_price
                    ELSE 0
                END as discounts,
                o.total_price as net_sales,
                CASE 
                    WHEN p.type = 'free_shipping' THEN -50
                    ELSE 50
                END as shipping_fee_collected,
                (o.total_price * 0.05) as platform_commission,
                (o.total_price - CASE 
                    WHEN p.type = 'free_shipping' THEN 50
                    ELSE 0
                END - (o.total_price * 0.05)) as net_earnings,
                p.type as promotion_type
            FROM orders o
            LEFT JOIN promotion_usage pu ON o.id = pu.order_id
            LEFT JOIN promotions p ON pu.promotion_id = p.id
            LEFT JOIN products prod ON o.product_id = prod.id
            WHERE o.seller_email = %s 
            AND o.status IN ('Completed', 'Delivered')
            ORDER BY date_completed DESC
            LIMIT 100
        """, (session['email'],))
        
        financial_summary = cursor.fetchall()
        
        # Convert values safely
        for item in financial_summary:
            try:
                item['product_sales'] = float(item['product_sales']) if item['product_sales'] is not None else 0.0
                item['discounts'] = float(item['discounts']) if item['discounts'] is not None else 0.0
                item['net_sales'] = float(item['net_sales']) if item['net_sales'] is not None else 0.0
                item['shipping_fee_collected'] = float(item['shipping_fee_collected']) if item['shipping_fee_collected'] is not None else 0.0
                # Calculate platform commission if not present (5% of net sales)
                if 'platform_commission' in item:
                    item['platform_commission'] = float(item['platform_commission']) if item['platform_commission'] is not None else 0.0
                else:
                    item['platform_commission'] = item['net_sales'] * 0.05
                item['net_earnings'] = float(item['net_earnings']) if item['net_earnings'] is not None else 0.0
            except (ValueError, TypeError) as e:
                print(f"Error converting financial summary values: {e}")
                item['product_sales'] = 0.0
                item['discounts'] = 0.0
                item['net_sales'] = 0.0
                item['shipping_fee_collected'] = 0.0
                item['platform_commission'] = 0.0
                item['net_earnings'] = 0.0
    except Exception as e:
        print(f"Error fetching financial summary: {e}")
        import traceback
        traceback.print_exc()
        financial_summary = []
    
    # Convert to dictionary for easier access
    status_stats = {
        'pending': {'count': 0, 'value': 0.0},
        'confirmed': {'count': 0, 'value': 0.0},
        'preparing': {'count': 0, 'value': 0.0},
        'ready_for_pickup': {'count': 0, 'value': 0.0},
        'out_for_delivery': {'count': 0, 'value': 0.0},
        'delivered': {'count': 0, 'value': 0.0},
        'completed': {'count': 0, 'value': 0.0},
        'cancelled': {'count': 0, 'value': 0.0}
    }
    
    for status_data in order_status_breakdown:
        try:
            status_key = status_data['status'].lower().replace(' ', '_')
            if status_key in status_stats:
                status_stats[status_key]['count'] = int(status_data['count'])
                status_stats[status_key]['value'] = float(status_data['total_value'])
        except Exception as e:
            print(f"Error processing status data: {e}")
            continue
    
    cursor.close()
    connection.close()

    # Safely convert values to avoid TypeError
    try:
        total_revenue = float(analytics['total_revenue']) if analytics['total_revenue'] is not None else 0.0
        avg_order_value = float(analytics['avg_order_value']) if analytics['avg_order_value'] is not None else 0.0
        total_orders = int(analytics['total_orders']) if analytics['total_orders'] is not None else 0
        total_earnings = float(earnings_data['total_earnings']) if earnings_data['total_earnings'] is not None else 0.0
    except (ValueError, TypeError):
        total_revenue = 0.0
        avg_order_value = 0.0
        total_orders = 0
        total_earnings = 0.0

    return render_template('reports_analytics.html',
                         total_revenue="{:.2f}".format(total_revenue),
                         total_orders=total_orders,
                         avg_order_value="{:.2f}".format(avg_order_value),
                         total_earnings="{:.2f}".format(total_earnings),
                         top_products=top_products,
                         status_stats=status_stats,
                         order_details=order_details,
                         promotion_performance=promotion_performance,
                         financial_summary=financial_summary,
                         user_name=seller_name,
                         user_email=session.get('email', 'Seller'))

@app.route('/promotions')
def promotions():
    if 'email' not in session:
        return redirect(url_for('home'))
    
    if session.get('user_type', '').lower() != 'seller':
        flash('Access denied. Seller privileges required.', 'error')
        return redirect(url_for('login'))

    # -- Get seller name from Supabase (works even when MySQL is down) -----
    seller_name = session.get('first_name', 'Seller')
    try:
        sb_res = sb_admin.table('users').select('first_name, last_name, business_name').eq('email', session['email']).execute()
        if sb_res.data:
            u = sb_res.data[0]
            seller_name = u.get('business_name') or f"{u.get('first_name', '')} {u.get('last_name', '')}".strip() or 'Seller'
    except Exception as sb_err:
        print(f"?? Supabase name fetch failed in promotions: {sb_err}")

    seller_email = session['email']
    try:
        from datetime import date as _date, timezone, timedelta
        # Use Philippine Standard Time (UTC+8) for date comparisons
        _pht = timezone(timedelta(hours=8))
        from datetime import datetime as _datetime
        today = _datetime.now(_pht).date().isoformat()

        # Products for promotion management — include ALL seller products regardless of stock
        prod_res = sb_admin.table('products').select('id, name, price, image, quantity, category').eq('seller_email', seller_email).eq('is_active', True).order('name').execute()
        products = []
        for p in (prod_res.data or []):
            raw_image = p.get('image', '') or ''
            # Get first image and resolve to a web-accessible URL
            first_img = raw_image.split(',')[0].strip() if raw_image else ''
            if first_img:
                if first_img.startswith('http://') or first_img.startswith('https://'):
                    img_url = first_img
                elif first_img.startswith('/app/'):
                    img_url = first_img[4:]  # strip /app prefix
                elif first_img.startswith('/static/') or first_img.startswith('static/'):
                    img_url = '/' + first_img.lstrip('/')
                else:
                    # Supabase Storage key
                    img_url = f"https://vydcnhmgqovketjqvpoe.supabase.co/storage/v1/object/public/product-images/products/{first_img.split('/')[-1]}"
            else:
                img_url = ''
            products.append({'id': p['id'], 'name': p['name'],
                'price': float(p.get('price') or 0), 'image': img_url,
                'quantity': int(p.get('quantity') or 0), 'category': p.get('category','')})

        # All promotions for this seller
        all_res = sb_admin.table('promotions').select('*').eq('seller_email', seller_email).order('created_at', desc=True).execute()

        active_promotions = []
        scheduled_promotions = []
        expired_promotions = []

        for p in (all_res.data or []):
            sd = str(p.get('start_date') or '')[:10]
            ed = str(p.get('end_date') or '')[:10]
            row = {**p, 'start_date': sd, 'end_date': ed,
                   'total_uses': int(p.get('current_usage_count') or 0),
                   'total_discount_given': 0.0}
            if not p.get('is_active'):
                expired_promotions.append(row)
            elif sd > today:
                scheduled_promotions.append(row)
            elif ed < today:
                expired_promotions.append(row)
            else:
                active_promotions.append(row)

    except Exception as e:
        print(f"promotions Supabase error: {e}")
        products = []
        active_promotions = []
        scheduled_promotions = []
        expired_promotions = []

    return render_template('promotions.html',
                         products=products,
                         active_promotions=active_promotions,
                         scheduled_promotions=scheduled_promotions,
                         expired_promotions=expired_promotions,
                         user_name=seller_name,
                         user_email=session.get('email', 'Seller'))


@app.route('/products')
def products():
    """Seller product management page."""
    if 'email' not in session:
        return redirect(url_for('home'))
    if session.get('user_type', '').lower() != 'seller':
        flash('Access denied. Seller privileges required.', 'error')
        return redirect(url_for('login'))

    seller_email = session['email']
    search   = request.args.get('search', '').strip()
    category = request.args.get('category', '').strip()
    status   = request.args.get('status', '').strip()

    seller_name = session.get('first_name', 'Seller')
    try:
        sb_res = sb_admin.table('users').select('first_name, last_name, business_name').eq('email', seller_email).execute()
        if sb_res.data:
            u = sb_res.data[0]
            seller_name = u.get('business_name') or f"{u.get('first_name','')} {u.get('last_name','')}".strip() or 'Seller'
    except Exception:
        pass

    try:
        q = sb_admin.table('products').select('*').eq('seller_email', seller_email).order('id', desc=True)
        if search:
            q = q.ilike('name', f'%{search}%')
        if category:
            q = q.eq('category', category)
        if status == 'active':
            q = q.eq('is_active', True)
        elif status == 'inactive':
            q = q.eq('is_active', False)
        res = q.execute()
        seller_products = res.data or []
        for p in seller_products:
            p['price'] = float(p.get('price') or 0)
            p['quantity'] = int(p.get('quantity') or 0)
            p['sold'] = int(p.get('sold') or 0)
            p['low_stock_threshold'] = int(p.get('low_stock_threshold') or 5)
            p['review_count'] = 0
            if not p.get('rating'):
                p['rating'] = 0

        # Get distinct categories for filter dropdown
        all_cats_res = sb_admin.table('products').select('category').eq('seller_email', seller_email).execute()
        categories = sorted({p['category'] for p in (all_cats_res.data or []) if p.get('category')})

    except Exception as e:
        print(f"products route error: {e}")
        seller_products = []
        categories = []

    # Pagination
    page_num = request.args.get('page', 1, type=int)
    per_page = 12
    total_products = len(seller_products)
    total_pages = max(1, (total_products + per_page - 1) // per_page)
    page_num = max(1, min(page_num, total_pages))
    offset = (page_num - 1) * per_page
    paged_products = seller_products[offset:offset + per_page]

    # Pagination window
    start_page = max(1, page_num - 2)
    end_page   = min(total_pages, page_num + 2)

    return render_template('products.html',
                           products=paged_products,
                           user_name=seller_name,
                           user_email=seller_email,
                           search=search,
                           category=category,
                           selected_category=category,
                           status=status,
                           categories=categories,
                           page=page_num,
                           total_pages=total_pages,
                           total_products=total_products,
                           start_page=start_page,
                           end_page=end_page)


@app.route('/variant_inventory')
def variant_inventory():
    """Seller variant inventory page."""
    if 'email' not in session:
        return redirect(url_for('home'))
    if session.get('user_type', '').lower() != 'seller':
        flash('Access denied. Seller privileges required.', 'error')
        return redirect(url_for('login'))

    seller_email = session['email']
    seller_name = session.get('first_name', 'Seller')

    try:
        # Get all products for this seller
        prod_res = sb_admin.table('products').select('id, name, category, image').eq('seller_email', seller_email).order('name').execute()
        seller_products = prod_res.data or []

        # Get variant inventory for all seller products
        product_ids = [p['id'] for p in seller_products]
        variants = []
        if product_ids:
            vi_res = sb_admin.table('variant_inventory').select('*').in_('product_id', product_ids).execute()
            variants = vi_res.data or []

        # Map product names to variants
        prod_map = {p['id']: p for p in seller_products}
        for v in variants:
            prod = prod_map.get(v.get('product_id'), {})
            v['product_name'] = prod.get('name', 'Unknown')
            v['product_image'] = prod.get('image', '')
            v['stock_quantity'] = int(v.get('stock_quantity') or 0)
            v['low_stock_threshold'] = int(v.get('low_stock_threshold') or 5)

    except Exception as e:
        print(f"variant_inventory error: {e}")
        seller_products = []
        variants = []

    return render_template('variant_inventory.html',
                           products=seller_products,
                           variants=variants,
                           user_name=seller_name,
                           user_email=seller_email)


@app.route('/add_product', methods=['GET', 'POST'])
def add_product():
    """Redirect to add_new_product for compatibility."""
    return redirect(url_for('add_new_product'))


@app.route('/api/seller/products-with-variants')
def seller_products_with_variants():
    """API: return seller's products with their variant inventory data."""
    if 'email' not in session or session.get('user_type', '').lower() != 'seller':
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401

    seller_email = session['email']
    try:
        # Fetch all products for this seller
        prod_res = sb_admin.table('products').select(
            'id, name, category, image, image_colors, variations, sizes, '
            'price, quantity, sold, low_stock_threshold, is_active, seller_email'
        ).eq('seller_email', seller_email).order('id', desc=True).execute()
        products = prod_res.data or []

        if not products:
            return jsonify({'success': True, 'products': []})

        product_ids = [p['id'] for p in products]

        # Fetch variant inventory for all products
        vi_res = sb_admin.table('variant_inventory').select(
            'id, product_id, color, size, stock_quantity, low_stock_threshold'
        ).in_('product_id', product_ids).execute()
        all_variants = vi_res.data or []

        # Group variants by product_id
        from collections import defaultdict
        variants_by_product = defaultdict(list)
        for v in all_variants:
            variants_by_product[v['product_id']].append({
                'id':                 v['id'],
                'color':              v.get('color', ''),
                'size':               v.get('size', ''),
                'stock_quantity':     int(v.get('stock_quantity') or 0),
                'low_stock_threshold': int(v.get('low_stock_threshold') or 5),
            })

        # Build response
        result = []
        for p in products:
            pid = p['id']
            variants = variants_by_product.get(pid, [])
            total_qty = sum(v['stock_quantity'] for v in variants) if variants else int(p.get('quantity') or 0)

            # Parse colors and sizes from variations/sizes fields
            colors = list({v['color'] for v in variants if v.get('color')})
            sizes  = list({v['size']  for v in variants if v.get('size')})
            if not colors and p.get('variations'):
                colors = [c.strip() for c in p['variations'].split(',') if c.strip()]
            if not sizes and p.get('sizes'):
                sizes = [s.strip() for s in p['sizes'].split(',') if s.strip()]

            result.append({
                'id':                  pid,
                'name':                p.get('name', ''),
                'category':            p.get('category', ''),
                'image':               p.get('image', ''),
                'image_colors':        p.get('image_colors', ''),
                'price':               float(p.get('price') or 0),
                'quantity':            int(p.get('quantity') or 0),
                'total_quantity':      total_qty,
                'sold':                int(p.get('sold') or 0),
                'low_stock_threshold': int(p.get('low_stock_threshold') or 5),
                'is_active':           p.get('is_active', True),
                'colors':              colors,
                'sizes':               sizes,
                'variants':            variants,
            })

        return jsonify({'success': True, 'products': result})

    except Exception as e:
        print(f"seller_products_with_variants error: {e}")
        import traceback; traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/seller/sync-stock', methods=['POST'])
def seller_sync_stock():
    """Sync products.quantity = sum of variant_inventory for all seller products."""
    if 'email' not in session or session.get('user_type', '').lower() != 'seller':
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401
    seller_email = session['email']
    try:
        # Get all products for this seller
        prod_res = sb_admin.table('products').select('id').eq('seller_email', seller_email).execute()
        products = prod_res.data or []
        synced = 0
        for p in products:
            pid = p['id']
            vi_res = sb_admin.table('variant_inventory').select('stock_quantity').eq('product_id', pid).execute()
            variants = vi_res.data or []
            if variants:
                total = sum(int(v.get('stock_quantity') or 0) for v in variants)
                sb_admin.table('products').update({'quantity': total}).eq('id', pid).execute()
                synced += 1
        return jsonify({'success': True, 'message': f'Synced {synced} products', 'synced': synced})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/seller/update-variants', methods=['POST'])
def seller_update_variants():
    """API: update variant inventory stock quantities and sync products.quantity."""
    if 'email' not in session or session.get('user_type', '').lower() != 'seller':
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401

    seller_email = session['email']
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'No data received'}), 400

        product_id          = data.get('product_id')
        variants            = data.get('variants', [])
        low_stock_threshold = int(data.get('low_stock_threshold') or 5)

        if not product_id:
            return jsonify({'success': False, 'error': 'product_id is required'}), 400

        # Verify product belongs to this seller
        prod_res = sb_admin.table('products').select('id').eq('id', product_id).eq('seller_email', seller_email).limit(1).execute()
        if not prod_res.data:
            return jsonify({'success': False, 'error': 'Product not found or access denied'}), 404

        total_stock = 0
        for v in variants:
            color     = (v.get('color') or '').strip()
            size      = (v.get('size') or '').strip()
            qty       = int(v.get('stock_quantity') or 0)
            threshold = int(v.get('low_stock_threshold') or low_stock_threshold)
            total_stock += qty

            # Upsert variant row
            sb_admin.table('variant_inventory').upsert({
                'product_id':          product_id,
                'color':               color,
                'size':                size,
                'stock_quantity':      qty,
                'low_stock_threshold': threshold,
            }, on_conflict='product_id,color,size').execute()

            # Stock level notifications
            check_and_notify_stock_levels(
                product_id=str(product_id),
                seller_email=seller_email,
                new_quantity=qty,
                threshold=threshold,
                product_name=data.get('product_name', ''),
                variant_info={'color': color, 'size': size} if (color or size) else None,
            )

        # Sync products.quantity = sum of all variant stocks
        sb_admin.table('products').update({
            'quantity':            total_stock,
            'low_stock_threshold': low_stock_threshold,
        }).eq('id', product_id).execute()

        return jsonify({
            'success': True,
            'message': f'Variants updated. Total stock: {total_stock}',
            'total_stock': total_stock,
        })

    except Exception as e:
        print(f"seller_update_variants error: {e}")
        import traceback; traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/seller_reviews')
def seller_reviews():
    """Seller Reviews & Ratings page - powered by Supabase"""
    if 'email' not in session:
        return redirect(url_for('home'))
    if session.get('user_type', '').lower() != 'seller':
        flash('Access denied. Seller privileges required.', 'error')
        return redirect(url_for('login'))

    seller_email = session['email']
    empty_stats = {'total_reviews': 0, 'average_rating': 0,
                   'five_star': 0, 'four_star': 0, 'three_star': 0,
                   'two_star': 0, 'one_star': 0}

    # -- Seller name -------------------------------------------------------
    seller_name = session.get('first_name', 'Seller')
    try:
        sb_res = sb_admin.table('users').select('first_name, last_name, business_name').eq('email', seller_email).execute()
        if sb_res.data:
            u = sb_res.data[0]
            seller_name = u.get('business_name') or f"{u.get('first_name', '')} {u.get('last_name', '')}".strip() or 'Seller'
    except Exception as e:
        print(f"seller_reviews name fetch failed: {e}")

    try:
        from datetime import datetime as _dt

        # 1. Fetch all reviews for this seller
        rev_res = sb_admin.table('reviews') \
            .select('id, order_id, product_id, customer_email, rating, review_text, review_images, seller_response, response_date, created_at') \
            .eq('seller_email', seller_email) \
            .order('created_at', desc=True) \
            .execute()
        raw_reviews = rev_res.data or []

        if not raw_reviews:
            return render_template('seller_reviews.html', reviews=[], stats=empty_stats,
                                   user_name=seller_name, user_email=seller_email)

        # 2. Batch-fetch product info
        product_ids = list({r['product_id'] for r in raw_reviews if r.get('product_id')})
        product_map = {}
        if product_ids:
            prod_res = sb_admin.table('products') \
                .select('id, name, image, price') \
                .in_('id', product_ids) \
                .execute()
            for p in (prod_res.data or []):
                product_map[p['id']] = p

        # 3. Batch-fetch customer info
        customer_emails = list({r['customer_email'] for r in raw_reviews if r.get('customer_email')})
        customer_map = {}
        if customer_emails:
            cust_res = sb_admin.table('users') \
                .select('email, first_name, last_name') \
                .in_('email', customer_emails) \
                .execute()
            for c in (cust_res.data or []):
                customer_map[c['email']] = c

        # 4. Build formatted review list
        def _time_ago(ts_str):
            if not ts_str:
                return ''
            try:
                ts = _dt.fromisoformat(str(ts_str).replace('Z', '+00:00').replace('+00:00', ''))
                diff = _dt.now() - ts
                s = diff.total_seconds()
                if s < 60:      return 'Just now'
                if s < 3600:    return f"{int(s/60)} minute{'s' if int(s/60)!=1 else ''} ago"
                if s < 86400:   return f"{int(s/3600)} hour{'s' if int(s/3600)!=1 else ''} ago"
                if s < 604800:  return f"{int(s/86400)} day{'s' if int(s/86400)!=1 else ''} ago"
                if s < 2592000: return f"{int(s/604800)} week{'s' if int(s/604800)!=1 else ''} ago"
                if s < 31536000:return f"{int(s/2592000)} month{'s' if int(s/2592000)!=1 else ''} ago"
                return f"{int(s/31536000)} year{'s' if int(s/31536000)!=1 else ''} ago"
            except Exception:
                return ''

        reviews = []
        for r in raw_reviews:
            prod = product_map.get(r.get('product_id'), {})
            cust = customer_map.get(r.get('customer_email', ''), {})
            fn = cust.get('first_name') or ''
            ln = cust.get('last_name') or ''
            rating = int(r.get('rating') or 0)
            reviews.append({
                'id':                   r['id'],
                'order_id':             r.get('order_id'),
                'product_id':           r.get('product_id'),
                'customer_email':       r.get('customer_email', ''),
                'customer_first_name':  fn,
                'customer_name':        f"{fn} {ln}".strip() or 'Anonymous',
                'rating':               rating,
                'rating_stars':         '\u2605' * rating + '\u2606' * (5 - rating),
                'review_text':          r.get('review_text', ''),
                'review_images':        r.get('review_images') or '',
                'seller_response':      r.get('seller_response'),
                'response_time_ago':    _time_ago(r.get('response_date')),
                'time_ago':             _time_ago(r.get('created_at')),
                'product_name':         prod.get('name', 'Unknown Product'),
                'product_image':        prod.get('image', ''),
                'product_price':        float(prod.get('price') or 0),
            })

        # 5. Compute stats
        total = len(reviews)
        ratings = [rv['rating'] for rv in reviews]
        stats = {
            'total_reviews':  total,
            'average_rating': round(sum(ratings) / total, 1) if total else 0,
            'five_star':  sum(1 for x in ratings if x == 5),
            'four_star':  sum(1 for x in ratings if x == 4),
            'three_star': sum(1 for x in ratings if x == 3),
            'two_star':   sum(1 for x in ratings if x == 2),
            'one_star':   sum(1 for x in ratings if x == 1),
        }

        return render_template('seller_reviews.html',
                               reviews=reviews,
                               stats=stats,
                               user_name=seller_name,
                               user_email=seller_email)

    except Exception as e:
        print(f"seller_reviews Supabase error: {e}")
        return render_template('seller_reviews.html', reviews=[], stats=empty_stats,
                               user_name=seller_name, user_email=seller_email)
def format_time_ago(timestamp):
    """Format timestamp as 'time ago' string"""
    now = datetime.now()
    diff = now - timestamp
    
    seconds = diff.total_seconds()
    
    if seconds < 60:
        return "Just now"
    elif seconds < 3600:
        minutes = int(seconds / 60)
        return f"{minutes} minute{'s' if minutes != 1 else ''} ago"
    elif seconds < 86400:
        hours = int(seconds / 3600)
        return f"{hours} hour{'s' if hours != 1 else ''} ago"
    elif seconds < 604800:
        days = int(seconds / 86400)
        return f"{days} day{'s' if days != 1 else ''} ago"
    elif seconds < 2592000:
        weeks = int(seconds / 604800)
        return f"{weeks} week{'s' if weeks != 1 else ''} ago"
    elif seconds < 31536000:
        months = int(seconds / 2592000)
        return f"{months} month{'s' if months != 1 else ''} ago"
    else:
        years = int(seconds / 31536000)
        return f"{years} year{'s' if years != 1 else ''} ago"

@app.route('/api/seller/review/respond', methods=['POST'])
def seller_respond_to_review():
    """Seller responds to a review - powered by Supabase"""
    if 'email' not in session or session.get('user_type', '').lower() != 'seller':
        return jsonify({'success': False, 'error': 'Unauthorized. Please log in as a seller.'}), 401


# ── Seller Notifications API ──────────────────────────────────────────────────

@app.route('/api/seller/notifications', methods=['GET'])
def get_seller_notifications():
    """Get notifications for the logged-in seller."""
    if 'email' not in session or session.get('user_type', '').lower() != 'seller':
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401
    seller_email = session['email']
    try:
        res = sb_admin.table('notifications') \
            .select('id, message, type, is_read, order_id, created_at') \
            .eq('seller_email', seller_email) \
            .order('created_at', desc=True) \
            .limit(30) \
            .execute()
        notifications = res.data or []
        formatted = []
        for n in notifications:
            formatted.append({
                'id':         n['id'],
                'message':    n.get('message', ''),
                'type':       n.get('type', 'order'),
                'read':       n.get('is_read', False),
                'order_id':   n.get('order_id'),
                'created_at': n.get('created_at', ''),
            })
        return jsonify({'success': True, 'notifications': formatted})
    except Exception as e:
        print(f"get_seller_notifications error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/seller/notifications/mark-read', methods=['POST'])
def mark_seller_notification_read():
    """Mark a single notification as read."""
    if 'email' not in session or session.get('user_type', '').lower() != 'seller':
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401
    data = request.get_json(silent=True) or {}
    notification_id = data.get('notification_id')
    if not notification_id:
        return jsonify({'success': False, 'error': 'notification_id required'}), 400
    try:
        sb_admin.table('notifications') \
            .update({'is_read': True}) \
            .eq('id', notification_id) \
            .eq('seller_email', session['email']) \
            .execute()
        return jsonify({'success': True})
    except Exception as e:
        print(f"mark_seller_notification_read error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/seller/notifications/mark-all-read', methods=['POST'])
def mark_all_seller_notifications_read():
    """Mark all notifications as read for the logged-in seller."""
    if 'email' not in session or session.get('user_type', '').lower() != 'seller':
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401
    seller_email = session['email']
    try:
        res = sb_admin.table('notifications') \
            .update({'is_read': True}) \
            .eq('seller_email', seller_email) \
            .eq('is_read', False) \
            .execute()
        affected = len(res.data) if res.data else 0
        return jsonify({'success': True, 'affected_rows': affected})
    except Exception as e:
        print(f"mark_all_seller_notifications_read error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/seller/notifications/delete', methods=['POST'])
def delete_seller_notification():
    """Delete a single notification."""
    if 'email' not in session or session.get('user_type', '').lower() != 'seller':
        return jsonify({'success': False, 'error': 'Unauthorized. Please log in as a seller.'}), 401
    data = request.get_json(silent=True) or {}
    notification_id = data.get('notification_id')
    if not notification_id:
        return jsonify({'success': False, 'error': 'notification_id required'}), 400
    try:
        sb_admin.table('notifications') \
            .delete() \
            .eq('id', notification_id) \
            .eq('seller_email', session['email']) \
            .execute()
        return jsonify({'success': True})
    except Exception as e:
        print(f"delete_seller_notification error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/seller/notifications/delete-all', methods=['POST'])
def delete_all_seller_notifications():
    """Delete all notifications for the logged-in seller."""
    if 'email' not in session or session.get('user_type', '').lower() != 'seller':
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401
    seller_email = session['email']
    try:
        res = sb_admin.table('notifications') \
            .delete() \
            .eq('seller_email', seller_email) \
            .execute()
        deleted = len(res.data) if res.data else 0
        return jsonify({'success': True, 'deleted_count': deleted})
    except Exception as e:
        print(f"delete_all_seller_notifications error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'No data received'}), 400

        review_id    = data.get('review_id')
        response_text = (data.get('response_text') or '').strip()

        if not review_id:
            return jsonify({'success': False, 'error': 'Review ID is required'}), 400
        if not response_text:
            return jsonify({'success': False, 'error': 'Response text cannot be empty'}), 400

        # Verify the review belongs to this seller
        check = sb_admin.table('reviews') \
            .select('id, seller_email') \
            .eq('id', review_id) \
            .limit(1) \
            .execute()

        if not check.data:
            return jsonify({'success': False, 'error': 'Review not found'}), 404
        if check.data[0]['seller_email'] != session['email']:
            return jsonify({'success': False, 'error': 'Not authorized to respond to this review'}), 403

        from datetime import datetime as _dt
        now_iso = _dt.now().isoformat()

        sb_admin.table('reviews') \
            .update({'seller_response': response_text, 'response_date': now_iso}) \
            .eq('id', review_id) \
            .execute()

        return jsonify({'success': True, 'message': 'Response posted successfully',
                        'response_date': now_iso})

    except Exception as e:
        print(f"seller_respond_to_review error: {e}")
        return jsonify({'success': False, 'error': f'Server error: {str(e)}'}), 500

@app.route('/admin/backfill-promotion-usage')
def admin_backfill_promotion_usage():
    if 'email' not in session:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401
    return jsonify({'success': True, 'message': 'No backfill needed (Supabase-only)'})

@app.route('/api/create_promotion', methods=['POST'])
def create_promotion():
    if 'email' not in session or session.get('user_type', '').lower() != 'seller':
        return jsonify({'success': False, 'message': 'Unauthorized access'}), 401
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'message': 'No data received'}), 400
        for field in ['name', 'code', 'type', 'startDate', 'endDate', 'productScope']:
            if not data.get(field) or str(data.get(field)).strip() == '':
                return jsonify({'success': False, 'message': f'{field} is required'}), 400
        discount_value = None
        if data['type'] in ['percentage', 'fixed']:
            if not data.get('discountValue'):
                return jsonify({'success': False, 'message': 'Discount value is required'}), 400
            discount_value = float(data['discountValue'])
            if data['type'] == 'percentage' and not (1 <= discount_value <= 100):
                return jsonify({'success': False, 'message': 'Percentage must be between 1 and 100'}), 400
        else:
            discount_value = 0.0
        max_discount_val = float(data['maxDiscount']) if data.get('maxDiscount') else None
        min_purchase_val = float(data.get('minPurchase') or 0)
        min_quantity_val = int(data.get('minQuantity') or 1)
        usage_limit_val  = int(data['usageLimit']) if data.get('usageLimit') else None
        # Check duplicate code
        dup = sb_admin.table('promotions').select('id').eq('code', data['code']).eq('seller_email', session['email']).execute()
        if dup.data:
            return jsonify({'success': False, 'message': 'Promotion code already exists'}), 400
        # Insert promotion
        ins = sb_admin.table('promotions').insert({
            'name': data['name'], 'code': data['code'], 'seller_email': session['email'],
            'type': data['type'], 'discount_value': discount_value, 'max_discount': max_discount_val,
            'min_purchase': min_purchase_val, 'min_quantity': min_quantity_val,
            'usage_limit_per_customer': usage_limit_val,
            'start_date': data['startDate'], 'start_time': data.get('startTime', '00:00:00'),
            'end_date': data['endDate'], 'end_time': data.get('endTime', '23:59:59'),
            'product_scope': data['productScope'], 'is_active': data.get('isActive', True),
        }).execute()
        promotion_id = ins.data[0]['id']
        if data['productScope'] == 'specific' and data.get('selectedProducts'):
            for pid in data['selectedProducts']:
                sb_admin.table('promotion_products').insert({'promotion_id': promotion_id, 'product_id': int(pid)}).execute()
        elif data['productScope'] == 'category' and data.get('selectedCategories'):
            for cat in data['selectedCategories']:
                sb_admin.table('promotion_categories').insert({'promotion_id': promotion_id, 'category': cat}).execute()
        return jsonify({'success': True, 'message': 'Promotion created successfully', 'promotion_id': promotion_id})
    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({'success': False, 'message': f'Server error: {str(e)}'}), 500



@app.route('/api/get_promotion/<int:promotion_id>')
def get_promotion(promotion_id):
    if 'email' not in session or session.get('user_type', '').lower() != 'seller':
        return jsonify({'success': False, 'message': 'Unauthorized access'}), 401
    try:
        res = sb_admin.table('promotions').select('*').eq('id', promotion_id).eq('seller_email', session['email']).limit(1).execute()
        if not res.data:
            return jsonify({'success': False, 'message': 'Promotion not found'}), 404
        promotion = convert_promotion_for_json(res.data[0])
        pp = sb_admin.table('promotion_products').select('product_id').eq('promotion_id', promotion_id).execute()
        promotion['selectedProducts'] = [r['product_id'] for r in (pp.data or [])]
        pc = sb_admin.table('promotion_categories').select('category').eq('promotion_id', promotion_id).execute()
        promotion['selectedCategories'] = [r['category'] for r in (pc.data or [])]
        return jsonify({'success': True, 'promotion': promotion})
    except Exception as e:
        return jsonify({'success': False, 'message': f'Server error: {str(e)}'}), 500

@app.route('/api/update_promotion/<int:promotion_id>', methods=['PUT'])
def update_promotion(promotion_id):
    if 'email' not in session or session.get('user_type', '').lower() != 'seller':
        return jsonify({'success': False, 'message': 'Unauthorized access'}), 401
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'message': 'No data received'}), 400
        for field in ['name', 'code', 'type', 'startDate', 'endDate', 'productScope']:
            if not data.get(field) or str(data.get(field)).strip() == '':
                return jsonify({'success': False, 'message': f'{field} is required'}), 400
        discount_value = 0.0
        if data['type'] in ['percentage', 'fixed']:
            discount_value = float(data.get('discountValue') or 0)
        # Check promotion exists
        chk = sb_admin.table('promotions').select('id').eq('id', promotion_id).eq('seller_email', session['email']).execute()
        if not chk.data:
            return jsonify({'success': False, 'message': 'Promotion not found'}), 404
        # Check duplicate code
        dup = sb_admin.table('promotions').select('id').eq('code', data['code']).eq('seller_email', session['email']).neq('id', promotion_id).execute()
        if dup.data:
            return jsonify({'success': False, 'message': 'Promotion code already exists'}), 400
        sb_admin.table('promotions').update({
            'name': data['name'], 'code': data['code'], 'type': data['type'],
            'discount_value': discount_value,
            'max_discount': float(data['maxDiscount']) if data.get('maxDiscount') else None,
            'min_purchase': float(data.get('minPurchase') or 0),
            'min_quantity': int(data.get('minQuantity') or 1),
            'usage_limit_per_customer': int(data['usageLimit']) if data.get('usageLimit') else None,
            'start_date': data['startDate'], 'start_time': data.get('startTime', '00:00:00'),
            'end_date': data['endDate'], 'end_time': data.get('endTime', '23:59:59'),
            'product_scope': data['productScope'], 'is_active': data.get('isActive', True),
        }).eq('id', promotion_id).execute()
        sb_admin.table('promotion_products').delete().eq('promotion_id', promotion_id).execute()
        sb_admin.table('promotion_categories').delete().eq('promotion_id', promotion_id).execute()
        if data['productScope'] == 'specific' and data.get('selectedProducts'):
            for pid in data['selectedProducts']:
                sb_admin.table('promotion_products').insert({'promotion_id': promotion_id, 'product_id': int(pid)}).execute()
        elif data['productScope'] == 'category' and data.get('selectedCategories'):
            for cat in data['selectedCategories']:
                sb_admin.table('promotion_categories').insert({'promotion_id': promotion_id, 'category': cat}).execute()
        return jsonify({'success': True, 'message': 'Promotion updated successfully'})
    except Exception as e:
        return jsonify({'success': False, 'message': f'Server error: {str(e)}'}), 500

@app.route('/api/get_promotions')
def get_promotions():
    if 'email' not in session or session.get('user_type', '').lower() != 'seller':
        return jsonify({'success': False, 'message': 'Unauthorized access'}), 401
    try:
        from datetime import date as _date
        today = _date.today().isoformat()
        res = sb_admin.table('promotions').select('*').eq('seller_email', session['email']).order('created_at', desc=True).execute()
        promotions = []
        for p in (res.data or []):
            sd = str(p.get('start_date') or '')[:10]
            ed = str(p.get('end_date') or '')[:10]
            if not p.get('is_active'):
                status = 'inactive'
            elif sd > today:
                status = 'scheduled'
            elif ed < today:
                status = 'expired'
            else:
                status = 'active'
            promotions.append({**p, 'start_date': sd, 'end_date': ed, 'status': status,
                'total_uses': int(p.get('current_usage_count') or 0),
                'total_discount_given': 0.0})
        return jsonify({'success': True, 'promotions': promotions})
    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({'success': False, 'message': f'Server error: {str(e)}'}), 500

@app.route('/api/toggle_promotion/<int:promotion_id>', methods=['POST'])
def toggle_promotion(promotion_id):
    if 'email' not in session or session.get('user_type', '').lower() != 'seller':
        return jsonify({'success': False, 'message': 'Unauthorized access'}), 401
    try:
        res = sb_admin.table('promotions').select('is_active').eq('id', promotion_id).eq('seller_email', session['email']).limit(1).execute()
        if not res.data:
            return jsonify({'success': False, 'message': 'Promotion not found'}), 404
        new_status = not res.data[0]['is_active']
        sb_admin.table('promotions').update({'is_active': new_status}).eq('id', promotion_id).execute()
        return jsonify({'success': True, 'is_active': new_status})
    except Exception as e:
        return jsonify({'success': False, 'message': 'Failed to toggle promotion'}), 500

@app.route('/api/delete_promotion/<int:promotion_id>', methods=['DELETE'])
def delete_promotion(promotion_id):
    if 'email' not in session or session.get('user_type', '').lower() != 'seller':
        return jsonify({'success': False, 'message': 'Unauthorized access'}), 401
    try:
        chk = sb_admin.table('promotions').select('id').eq('id', promotion_id).eq('seller_email', session['email']).execute()
        if not chk.data:
            return jsonify({'success': False, 'message': 'Promotion not found'}), 404
        sb_admin.table('promotions').delete().eq('id', promotion_id).execute()
        return jsonify({'success': True, 'message': 'Promotion deleted successfully'})
    except Exception as e:
        return jsonify({'success': False, 'message': 'Failed to delete promotion'}), 500

@app.route('/api/apply_promotion', methods=['POST'])
def apply_promotion():
    if 'email' not in session:
        return jsonify({'success': False, 'message': 'Please log in to apply promotions'}), 401
    try:
        data = request.get_json()
        promotion_code = data.get('code')
        cart_items = data.get('cart_items', [])
        if not promotion_code:
            return jsonify({'success': False, 'message': 'Promotion code is required'}), 400
        from datetime import date as _date
        today = _date.today().isoformat()
        res = sb_admin.table('promotions').select('*').eq('code', promotion_code).eq('is_active', True).lte('start_date', today).gte('end_date', today).limit(1).execute()
        if not res.data:
            return jsonify({'success': False, 'message': 'Invalid or expired promotion code'}), 400
        promotion = res.data[0]
        if promotion.get('usage_limit_per_customer'):
            usage = sb_admin.table('promotion_usage').select('id', count='exact').eq('promotion_id', promotion['id']).eq('customer_email', session['email']).execute()
            if (usage.count or 0) >= promotion['usage_limit_per_customer']:
                return jsonify({'success': False, 'message': 'You have reached the usage limit for this promotion'}), 400
        total_discount = 0.0
        applicable_items = []
        for item in cart_items:
            applicable = False
            scope = promotion.get('product_scope', 'all')
            if scope == 'all':
                applicable = True
            elif scope == 'specific':
                pp = sb_admin.table('promotion_products').select('id').eq('promotion_id', promotion['id']).eq('product_id', item['product_id']).limit(1).execute()
                applicable = bool(pp.data)
            elif scope == 'category':
                prod = sb_admin.table('products').select('category').eq('id', item['product_id']).limit(1).execute()
                if prod.data:
                    pc = sb_admin.table('promotion_categories').select('id').eq('promotion_id', promotion['id']).eq('category', prod.data[0]['category']).limit(1).execute()
                    applicable = bool(pc.data)
            if applicable:
                price = float(item['price']); qty = int(item['quantity']); total = price * qty
                ptype = promotion['type']; dval = float(promotion.get('discount_value') or 0)
                if ptype == 'percentage':
                    disc = total * (dval / 100)
                    if promotion.get('max_discount'): disc = min(disc, float(promotion['max_discount']))
                elif ptype == 'fixed':
                    disc = min(dval, total)
                elif ptype == 'buy_one_get_one':
                    disc = (qty // 2) * price
                elif ptype == 'free_shipping':
                    disc = 50.0
                else:
                    disc = 0.0
                total_discount += disc
                applicable_items.append({'product_id': item['product_id'], 'name': item.get('name',''), 'discount': disc})
        cart_total = sum(float(i['price']) * int(i['quantity']) for i in cart_items)
        if promotion.get('min_purchase') and cart_total < float(promotion['min_purchase']):
            return jsonify({'success': False, 'message': f'Minimum purchase of {promotion["min_purchase"]} required'}), 400
        return jsonify({'success': True, 'promotion': {'id': promotion['id'], 'name': promotion['name'], 'code': promotion['code'], 'type': promotion['type'], 'discount_value': promotion.get('discount_value')}, 'total_discount': round(total_discount, 2), 'applicable_items': applicable_items})
    except Exception as e:
        return jsonify({'success': False, 'message': 'Failed to apply promotion'}), 500

@app.route('/rider_dashboard')
def rider_dashboard():
    if 'email' not in session:
        return redirect(url_for('home'))

    if session.get('user_type', '').lower() != 'rider':
        flash('Access denied. Rider privileges required.', 'error')
        return redirect(url_for('login'))

    rider_email = session['email']

    # -- Get rider name from Supabase --------------------------------------
    rider_name = session.get('first_name', 'Rider')
    try:
        sb_res = sb_admin.table('users').select('first_name, last_name').eq('email', rider_email).execute()
        if sb_res.data:
            u = sb_res.data[0]
            rider_name = f"{u.get('first_name', '')} {u.get('last_name', '')}".strip() or 'Rider'
    except Exception as sb_err:
        print(f"?? Supabase name fetch failed in rider_dashboard: {sb_err}")

    end_date = request.args.get('end_date', datetime.now().strftime('%Y-%m-%d'))
    start_date = request.args.get('start_date', (datetime.strptime(end_date, '%Y-%m-%d') - timedelta(days=7)).strftime('%Y-%m-%d'))

    available_deliveries = 0
    active_deliveries = 0
    total_earnings = 0.0

    try:
        # Available deliveries � Confirmed orders with no rider assigned
        avail_res = sb_admin.table('orders').select('id', count='exact').eq('status', 'Confirmed').is_('rider_email', 'null').execute()
        available_deliveries = avail_res.count or 0

        # Active deliveries � assigned to this rider and in progress
        active_res = sb_admin.table('orders').select('id', count='exact').eq('rider_email', rider_email).in_('status', ['For Pickup', 'Heading to Seller', 'Shipped']).execute()
        active_deliveries = active_res.count or 0

        # Completed deliveries for earnings calculation
        completed_res = sb_admin.table('orders').select('id', count='exact').eq('rider_email', rider_email).in_('status', ['Delivered', 'Completed']).execute()
        completed_count = completed_res.count or 0

        delivery_fee = 50.00
        platform_commission = delivery_fee * 0.05
        total_earnings = completed_count * (delivery_fee - platform_commission)

    except Exception as e:
        print(f"?? Supabase error in rider_dashboard stats: {e}")

    return render_template('rider_dashboard.html',
                           available_deliveries=available_deliveries,
                           active_deliveries=active_deliveries,
                           total_earnings="{:.2f}".format(total_earnings),
                           start_date=start_date,
                           end_date=end_date,
                           user_name=rider_name,
                           user_email=rider_email)

@app.route('/available_deliveries')
def available_deliveries():
    if 'email' not in session:
        return redirect(url_for('home'))

    if session.get('user_type', '').lower() != 'rider':
        flash('Access denied. Rider privileges required.', 'error')
        return redirect(url_for('login'))

    rider_email = session['email']

    # -- Rider name from Supabase ------------------------------------------
    rider_name = 'Rider'
    try:
        rn = sb_admin.table('users').select('first_name, last_name').eq('email', rider_email).execute()
        if rn.data:
            rider_name = f"{rn.data[0].get('first_name','')} {rn.data[0].get('last_name','')}".strip() or 'Rider'
    except Exception as e:
        print(f"?? rider name fetch: {e}")

    available_orders = []
    try:
        # Fetch confirmed orders with no rider assigned
        orders_res = sb_admin.table('orders').select('*').eq('status', 'Confirmed').is_('rider_email', 'null').order('date', desc=True).execute()
        orders_data = orders_res.data or []

        # Collect unique buyer/seller emails for batch lookup
        buyer_emails  = list({o['email'] for o in orders_data if o.get('email')})
        seller_emails = list({o['seller_email'] for o in orders_data if o.get('seller_email')})
        all_emails    = list(set(buyer_emails + seller_emails))

        users_map = {}
        if all_emails:
            users_res = sb_admin.table('users').select('email, first_name, last_name, address, business_name').in_('email', all_emails).execute()
            users_map = {u['email']: u for u in (users_res.data or [])}

        for order in orders_data:
            buyer  = users_map.get(order.get('email'), {})
            seller = users_map.get(order.get('seller_email'), {})

            order_value   = float(order.get('total_price') or 0)
            shipping_fee  = float(order.get('shipping_fee') or 50)
            has_free_ship = shipping_fee == 0
            delivery_fee  = 0 if has_free_ship else max(50, min(200, order_value * 0.05))

            # Parse date
            try:
                from dateutil import parser as dtparser
                order_dt  = dtparser.parse(order['date']) if order.get('date') else datetime.now()
                order_age = datetime.now(order_dt.tzinfo) - order_dt
                hours_ago = int(order_age.total_seconds() // 3600)
                if hours_ago < 1:
                    mins = int(order_age.total_seconds() // 60)
                    created_at = f"{mins} mins ago" if mins > 0 else "Just now"
                else:
                    created_at = f"{hours_ago} hours ago"
                priority = 'urgent' if order_age.total_seconds() > 7200 else 'normal'
            except Exception:
                created_at = 'Unknown'
                priority   = 'normal'

            seller_name    = seller.get('business_name') or f"{seller.get('first_name','')} {seller.get('last_name','')}".strip() or 'Seller'
            pickup_address = seller.get('address') or f"{seller_name} (Address not provided)"
            delivery_addr  = order.get('address') or buyer.get('address') or 'Address not provided'
            oid            = order['id']
            est_dist       = round(5 + (int(oid) % 10), 1)

            available_orders.append({
                'id':             oid,
                'customer_name':  f"{buyer.get('first_name','')} {buyer.get('last_name','')}".strip() or 'Buyer',
                'pickup_address': pickup_address,
                'delivery_address': delivery_addr,
                'delivery_fee':   delivery_fee,
                'has_free_shipping': has_free_ship,
                'distance':       f"{est_dist} km",
                'estimated_time': f"{int(est_dist * 3 + 10)} mins",
                'order_value':    order_value,
                'items_count':    int(order.get('quantity') or 1),
                'priority':       priority,
                'created_at':     created_at,
                'product_name':   order.get('name', ''),
                'variations':     order.get('variations', ''),
                'size':           order.get('size', ''),
                'payment_method': order.get('payment_method', ''),
                'status':         order.get('status', ''),
            })
    except Exception as e:
        print(f"?? available_deliveries Supabase error: {e}")
        import traceback; traceback.print_exc()

    return render_template('available_deliveries.html',
                           available_orders=available_orders,
                           user_name=rider_name,
                           user_email=rider_email)

@app.route('/api/accept-delivery', methods=['POST'])
def accept_delivery():
    if 'email' not in session:
        return jsonify({'success': False, 'message': 'Authentication required'}), 401

    if session.get('user_type', '').lower() != 'rider':
        return jsonify({'success': False, 'message': 'Rider privileges required'}), 403

    try:
        data     = request.get_json()
        order_id = data.get('orderId')
        if not order_id:
            return jsonify({'success': False, 'message': 'Order ID is required'}), 400

        rider_email = session['email']

        # Verify order is Confirmed and unassigned
        order_res = sb_admin.table('orders').select('id, status, email, seller_email, name, rider_email').eq('id', order_id).eq('status', 'Confirmed').execute()
        if not order_res.data:
            return jsonify({'success': False, 'message': 'Order not found or not available for delivery'}), 404

        order = order_res.data[0]
        if order.get('rider_email'):
            return jsonify({'success': False, 'message': 'Order already assigned to another rider'}), 409

        seller_email = order['seller_email']
        product_name = order.get('name', '')

        # Get rider name
        rider_res = sb_admin.table('users').select('first_name, last_name').eq('email', rider_email).execute()
        rider_name = 'Rider'
        if rider_res.data:
            u = rider_res.data[0]
            rider_name = f"{u.get('first_name','')} {u.get('last_name','')}".strip() or 'Rider'

        # Assign rider and update status
        sb_admin.table('orders').update({'status': 'For Pickup', 'rider_email': rider_email}).eq('id', order_id).execute()

        # Seller in-app notification
        notif_msg = f"🛵 Rider {rider_name} has accepted delivery for Order #{order_id} ({product_name}). The order is now awaiting pickup."
        sb_admin.table('notifications').insert({'seller_email': seller_email, 'message': notif_msg, 'type': 'rider_assigned', 'is_read': False}).execute()

        # Email to seller
        try:
            msg = Message(subject=f"Rider Assigned - Order #{order_id}", recipients=[seller_email])
            msg.html = f"""
            <html><body style="font-family:Arial,sans-serif;color:#333;">
            <div style="max-width:600px;margin:0 auto;padding:20px;">
              <div style="background:linear-gradient(135deg,#667eea,#764ba2);color:white;padding:30px;text-align:center;border-radius:10px 10px 0 0;">
                <h1 style="margin:0;">?? Rider Assigned to Your Order</h1>
              </div>
              <div style="background:#f9f9f9;padding:30px;border-radius:0 0 10px 10px;">
                <p>Good news! A rider has been assigned to deliver your order.</p>
                <div style="background:white;padding:20px;border-radius:8px;border-left:4px solid #667eea;">
                  <p><strong>Order Number:</strong> #{order_id}</p>
                  <p><strong>Product:</strong> {product_name}</p>
                  <p><strong>Rider Name:</strong> {rider_name}</p>
                  <p><strong>Status:</strong> <span style="background:#10b981;color:white;padding:4px 12px;border-radius:20px;">For Pickup</span></p>
                </div>
                <p>The rider will head to your location to pick up the item once they start the pickup.</p>
              </div>
            </div>
            </body></html>"""
            mail.send(msg)
        except Exception as email_err:
            print(f"?? Email to seller failed: {email_err}")

        return jsonify({'success': True, 'message': f'Order #{order_id} accepted successfully!'})

    except Exception as e:
        print(f"? accept_delivery error: {e}")
        return jsonify({'success': False, 'message': f'Error accepting delivery: {str(e)}'}), 500

@app.route('/api/order-details/<int:order_id>')
def get_order_details(order_id):
    if 'email' not in session:
        return jsonify({'success': False, 'message': 'Authentication required'}), 401

    if session.get('user_type', '').lower() != 'rider':
        return jsonify({'success': False, 'message': 'Rider privileges required'}), 403

    try:
        rider_email = session['email']

        order_res = sb_admin.table('orders').select('*').eq('id', order_id).or_(
            f"status.eq.Confirmed,and(status.in.(For Pickup,Heading to Seller,Shipped),rider_email.eq.{rider_email})"
        ).execute()

        if not order_res.data:
            return jsonify({'success': False, 'message': 'Order not found'}), 404

        order = order_res.data[0]

        # Batch-fetch buyer and seller info
        emails = list({e for e in [order.get('email'), order.get('seller_email')] if e})
        users_map = {}
        if emails:
            ur = sb_admin.table('users').select('email, first_name, last_name, phone, address, business_name').in_('email', emails).execute()
            users_map = {u['email']: u for u in (ur.data or [])}

        buyer  = users_map.get(order.get('email'), {})
        seller = users_map.get(order.get('seller_email'), {})

        order_value  = float(order.get('total_price') or 0)
        shipping_fee = float(order.get('shipping_fee') or 50)

        return jsonify({
            'success': True,
            'order': {
                'id':             order['id'],
                'product_name':   order.get('name', ''),
                'quantity':       order.get('quantity', 1),
                'total_price':    order_value,
                'shipping_fee':   shipping_fee,
                'has_free_shipping': shipping_fee == 0,
                'payment_method': order.get('payment_method', ''),
                'status':         order.get('status', ''),
                'variations':     order.get('variations', ''),
                'size':           order.get('size', ''),
                'customer': {
                    'name':    f"{buyer.get('first_name','')} {buyer.get('last_name','')}".strip() or 'Buyer',
                    'email':   order.get('email', ''),
                    'phone':   buyer.get('phone', 'N/A'),
                    'address': order.get('address') or buyer.get('address', ''),
                },
                'buyer': {
                    'name':    f"{buyer.get('first_name','')} {buyer.get('last_name','')}".strip() or 'Buyer',
                    'email':   order.get('email', ''),
                    'phone':   buyer.get('phone', 'N/A'),
                    'address': order.get('address') or buyer.get('address', ''),
                },
                'seller': {
                    'name':    seller.get('business_name') or f"{seller.get('first_name','')} {seller.get('last_name','')}".strip() or 'Seller',
                    'email':   order.get('seller_email', ''),
                    'phone':   seller.get('phone', 'N/A'),
                    'address': seller.get('address', ''),
                },
                'order_date': order.get('date', ''),
            }
        })

    except Exception as e:
        return jsonify({'success': False, 'message': f'Error fetching order details: {str(e)}'}), 500

@app.route('/api/start-pickup', methods=['POST'])
def start_pickup():
    if 'email' not in session:
        return jsonify({'success': False, 'message': 'Authentication required'}), 401
    if session.get('user_type', '').lower() != 'rider':
        return jsonify({'success': False, 'message': 'Rider privileges required'}), 403
    try:
        order_id = (request.get_json() or {}).get('orderId')
        if not order_id:
            return jsonify({'success': False, 'message': 'Order ID is required'}), 400

        rider_email = session['email']
        order_res = sb_admin.table('orders').select('id, status, rider_email').eq('id', order_id).eq('status', 'For Pickup').eq('rider_email', rider_email).execute()
        if not order_res.data:
            return jsonify({'success': False, 'message': 'Order not found or not ready for pickup'}), 404

        sb_admin.table('orders').update({'status': 'Heading to Seller'}).eq('id', order_id).execute()
        return jsonify({'success': True, 'message': f'Heading to seller for Order #{order_id}!'})
    except Exception as e:
        return jsonify({'success': False, 'message': f'Error starting pickup: {str(e)}'}), 500

@app.route('/api/confirm-pickup', methods=['POST'])
def confirm_pickup():
    if 'email' not in session:
        return jsonify({'success': False, 'message': 'Authentication required'}), 401
    if session.get('user_type', '').lower() != 'rider':
        return jsonify({'success': False, 'message': 'Rider privileges required'}), 403
    try:
        order_id = (request.get_json() or {}).get('orderId')
        if not order_id:
            return jsonify({'success': False, 'message': 'Order ID is required'}), 400

        rider_email = session['email']
        order_res = sb_admin.table('orders').select('*').eq('id', order_id).eq('status', 'Heading to Seller').eq('rider_email', rider_email).execute()
        if not order_res.data:
            return jsonify({'success': False, 'message': 'Order not found or not ready for pickup confirmation'}), 404

        order = order_res.data[0]
        sb_admin.table('orders').update({'status': 'Shipped'}).eq('id', order_id).execute()

        order_details = {
            'name':       order.get('name', ''),
            'quantity':   order.get('quantity', 1),
            'total_price': order.get('total_price', 0),
            'date':       order.get('date', ''),
            'variations': order.get('variations'),
            'size':       order.get('size'),
            'address':    order.get('address'),
        }
        customer_email = order.get('email', '')
        create_buyer_notification(customer_email, order_details, 'Shipped', order_id)
        send_order_status_update_email(customer_email, order_details, 'Shipped')

        return jsonify({'success': True, 'message': f'Order #{order_id} picked up successfully! Buyer has been notified.'})
    except Exception as e:
        return jsonify({'success': False, 'message': f'Error confirming pickup: {str(e)}'}), 500

@app.route('/api/mark-delivered', methods=['POST'])
def mark_delivered():
    if 'email' not in session:
        return jsonify({'success': False, 'message': 'Authentication required'}), 401
    if session.get('user_type', '').lower() != 'rider':
        return jsonify({'success': False, 'message': 'Rider privileges required'}), 403
    try:
        order_id = (request.get_json() or {}).get('orderId')
        if not order_id:
            return jsonify({'success': False, 'message': 'Order ID is required'}), 400

        rider_email = session['email']
        order_res = sb_admin.table('orders').select('*').eq('id', order_id).eq('status', 'Shipped').eq('rider_email', rider_email).execute()
        if not order_res.data:
            # Check current status for a helpful error message
            cur = sb_admin.table('orders').select('status').eq('id', order_id).execute()
            cur_status = cur.data[0]['status'] if cur.data else 'NOT FOUND'
            return jsonify({'success': False, 'message': f'Order not found or not shipped yet. Current status: {cur_status}'}), 404

        order = order_res.data[0]
        sb_admin.table('orders').update({'status': 'Delivered', 'delivered_at': datetime.now().isoformat()}).eq('id', order_id).execute()

        order_details = {
            'name':       order.get('name', ''),
            'quantity':   order.get('quantity', 1),
            'total_price': order.get('total_price', 0),
            'date':       order.get('date', ''),
            'variations': order.get('variations'),
            'size':       order.get('size'),
            'address':    order.get('address'),
        }
        customer_email = order.get('email', '')
        create_buyer_notification(customer_email, order_details, 'Delivered', order_id)
        send_order_status_update_email(customer_email, order_details, 'Delivered')

        return jsonify({'success': True, 'message': f'Order #{order_id} marked as delivered! Buyer has been notified.'})
    except Exception as e:
        return jsonify({'success': False, 'message': f'Error marking as delivered: {str(e)}'}), 500

@app.route('/active_deliveries')
def active_deliveries():
    if 'email' not in session:
        return redirect(url_for('home'))
    if session.get('user_type', '').lower() != 'rider':
        flash('Access denied. Rider privileges required.', 'error')
        return redirect(url_for('login'))

    rider_email = session['email']

    rider_name = 'Rider'
    try:
        rn = sb_admin.table('users').select('first_name, last_name').eq('email', rider_email).execute()
        if rn.data:
            rider_name = f"{rn.data[0].get('first_name','')} {rn.data[0].get('last_name','')}".strip() or 'Rider'
    except Exception as e:
        print(f"?? rider name: {e}")

    active_deliveries_list = []
    pickup_pending_count = in_transit_count = out_for_delivery_count = 0

    try:
        orders_res = sb_admin.table('orders').select('*').eq('rider_email', rider_email).in_('status', ['For Pickup', 'Heading to Seller', 'Shipped']).order('date', desc=True).execute()
        orders_data = orders_res.data or []

        emails = list({e for o in orders_data for e in [o.get('email'), o.get('seller_email')] if e})
        users_map = {}
        if emails:
            ur = sb_admin.table('users').select('email, first_name, last_name, phone, address, business_name').in_('email', emails).execute()
            users_map = {u['email']: u for u in (ur.data or [])}

        for order in orders_data:
            buyer  = users_map.get(order.get('email'), {})
            seller = users_map.get(order.get('seller_email'), {})

            order_value  = float(order.get('total_price') or 0)
            shipping_fee = float(order.get('shipping_fee') or 50)
            has_free_ship = shipping_fee == 0
            delivery_fee  = 0 if has_free_ship else max(50, min(200, order_value * 0.05))

            try:
                from dateutil import parser as dtparser
                order_dt  = dtparser.parse(order['date']) if order.get('date') else datetime.now()
                order_age = datetime.now(order_dt.tzinfo) - order_dt
                hours_ago = int(order_age.total_seconds() // 3600)
                time_ago  = f"{hours_ago} hours ago" if hours_ago >= 1 else f"{int(order_age.total_seconds()//60)} mins ago"
                priority  = 'urgent' if order_age.total_seconds() > 7200 else 'normal'
            except Exception:
                time_ago = 'Unknown'; priority = 'normal'

            status = order.get('status', '')
            if status == 'For Pickup':
                display_status = 'pickup_pending'; pickup_pending_count += 1
                status_text = 'Pickup Pending'; status_time = f"Assigned {time_ago}"
            elif status == 'Heading to Seller':
                display_status = 'heading_to_seller'; in_transit_count += 1
                status_text = 'Heading to Seller'; status_time = f"Started {time_ago}"
            elif status == 'Shipped':
                display_status = 'out_for_delivery'; out_for_delivery_count += 1
                status_text = 'Out for Delivery'; status_time = f"En route for {time_ago}"
            else:
                display_status = 'in_transit'; in_transit_count += 1
                status_text = 'In Transit'; status_time = f"Started {time_ago}"

            seller_name   = seller.get('business_name') or f"{seller.get('first_name','')} {seller.get('last_name','')}".strip() or 'Seller'
            pickup_addr   = seller.get('address') or f"{seller_name} (Address not provided)"
            delivery_addr = order.get('address') or buyer.get('address') or 'Address not provided'
            oid           = order['id']
            est_dist      = round(5 + (int(oid) % 10), 1)

            active_deliveries_list.append({
                'id':             oid,
                'customer_name':  f"{buyer.get('first_name','')} {buyer.get('last_name','')}".strip() or 'Buyer',
                'customer_email': order.get('email', ''),
                'customer_phone': buyer.get('phone', ''),
                'pickup_address': pickup_addr,
                'delivery_address': delivery_addr,
                'delivery_fee':   delivery_fee,
                'has_free_shipping': has_free_ship,
                'distance':       f"{est_dist} km",
                'order_value':    order_value,
                'items_count':    int(order.get('quantity') or 1),
                'priority':       priority,
                'status':         display_status,
                'status_text':    status_text,
                'status_time':    status_time,
                'product_name':   order.get('name', ''),
                'variations':     order.get('variations', ''),
                'size':           order.get('size', ''),
                'payment_method': order.get('payment_method', ''),
                'seller_email':   order.get('seller_email', ''),
                'seller_phone':   seller.get('phone', ''),
                'seller_address': seller.get('address', ''),
            })
    except Exception as e:
        print(f"?? active_deliveries Supabase error: {e}")
        import traceback; traceback.print_exc()

    return render_template('active_deliveries.html',
                           active_deliveries=active_deliveries_list,
                           active_count=len(active_deliveries_list),
                           in_transit_count=in_transit_count,
                           pickup_pending_count=pickup_pending_count,
                           out_for_delivery_count=out_for_delivery_count,
                           user_name=rider_name,
                           user_email=rider_email)

@app.route('/delivery_history')
def delivery_history():
    if 'email' not in session:
        return redirect(url_for('home'))
    if session.get('user_type', '').lower() != 'rider':
        flash('Access denied. Rider privileges required.', 'error')
        return redirect(url_for('login'))

    rider_email = session['email']

    rider_name = 'Rider'
    try:
        rn = sb_admin.table('users').select('first_name, last_name').eq('email', rider_email).execute()
        if rn.data:
            rider_name = f"{rn.data[0].get('first_name','')} {rn.data[0].get('last_name','')}".strip() or 'Rider'
    except Exception as e:
        print(f"?? rider name: {e}")

    completed_deliveries = []
    total_earned = 0.0

    try:
        orders_res = sb_admin.table('orders').select('*').eq('rider_email', rider_email).in_('status', ['Delivered', 'Completed']).order('delivered_at', desc=True).execute()
        orders_data = orders_res.data or []

        emails = list({e for o in orders_data for e in [o.get('email'), o.get('seller_email')] if e})
        users_map = {}
        if emails:
            ur = sb_admin.table('users').select('email, first_name, last_name, phone, address, business_name').in_('email', emails).execute()
            users_map = {u['email']: u for u in (ur.data or [])}

        for order in orders_data:
            buyer  = users_map.get(order.get('email'), {})
            seller = users_map.get(order.get('seller_email'), {})

            order_value  = float(order.get('total_price') or 0)
            delivery_fee = max(50, min(200, order_value * 0.05))
            total_earned += delivery_fee

            seller_name   = seller.get('business_name') or f"{seller.get('first_name','')} {seller.get('last_name','')}".strip() or 'Seller'
            delivery_addr = order.get('address') or buyer.get('address') or 'Address not provided'
            delivery_date = order.get('delivered_at') or order.get('date')
            oid           = order['id']
            est_dist      = round(5 + (int(oid) % 10), 1)

            import random as _random
            rating   = round(_random.uniform(4.0, 5.0), 1)
            feedback = _random.choice(["Fast and professional delivery. Thank you!", "Quick delivery, very satisfied!", "Excellent service, highly recommended!", "On time delivery, great job!", ""])

            completed_deliveries.append({
                'id':             oid,
                'customer_name':  f"{buyer.get('first_name','')} {buyer.get('last_name','')}".strip() or 'Buyer',
                'customer_phone': buyer.get('phone', ''),
                'pickup_address': seller.get('address') or f"MStyle Store - {seller_name}",
                'delivery_address': delivery_addr,
                'delivery_fee':   delivery_fee,
                'distance':       f"{est_dist} km",
                'duration':       f"{int(est_dist * 3 + 15)} mins",
                'order_value':    order_value,
                'items_count':    int(order.get('quantity') or 1),
                'status':         (order.get('status') or '').lower(),
                'product_name':   order.get('name', ''),
                'variations':     order.get('variations', ''),
                'size':           order.get('size', ''),
                'payment_method': order.get('payment_method', ''),
                'delivery_date':  delivery_date,
                'rating':         rating,
                'customer_feedback': feedback,
                'seller_address': seller.get('address', ''),
            })
    except Exception as e:
        print(f"?? delivery_history Supabase error: {e}")
        import traceback; traceback.print_exc()

    avg_rating = round(sum(d['rating'] for d in completed_deliveries) / len(completed_deliveries), 1) if completed_deliveries else 0.0

    return render_template('delivery_history.html',
                           completed_deliveries=completed_deliveries,
                           total_completed=len(completed_deliveries),
                           total_earned=f"{total_earned:.2f}",
                           avg_rating=avg_rating,
                           user_name=rider_name,
                           user_email=rider_email)

@app.route('/earnings')
def earnings():
    if 'email' not in session:
        return redirect(url_for('home'))
    if session.get('user_type', '').lower() != 'rider':
        flash('Access denied. Rider privileges required.', 'error')
        return redirect(url_for('login'))

    rider_email = session['email']

    rider_name = 'Rider'
    try:
        rn = sb_admin.table('users').select('first_name, last_name').eq('email', rider_email).execute()
        if rn.data:
            rider_name = f"{rn.data[0].get('first_name','')} {rn.data[0].get('last_name','')}".strip() or 'Rider'
    except Exception as e:
        print(f"?? rider name: {e}")

    earnings_data = []
    try:
        orders_res = sb_admin.table('orders').select('id, product_id, seller_email, date, received_at, delivered_at, email, status, total_price, shipping_fee').eq('rider_email', rider_email).in_('status', ['Delivered', 'Completed']).order('date', desc=True).execute()
        raw_orders = orders_res.data or []

        # Batch-fetch buyer and seller names
        emails = list({e for o in raw_orders for e in [o.get('email'), o.get('seller_email')] if e})
        users_map = {}
        if emails:
            ur = sb_admin.table('users').select('email, first_name, last_name, business_name').in_('email', emails).execute()
            users_map = {u['email']: u for u in (ur.data or [])}

        for order in raw_orders:
            buyer  = users_map.get(order.get('email'), {})
            seller = users_map.get(order.get('seller_email'), {})

            has_free_shipping = float(order.get('shipping_fee') or 50) == 0
            delivery_fee      = 50.00
            platform_comm     = delivery_fee * 0.05
            net_earnings      = delivery_fee - platform_comm
            buyer_ship_fee    = 0.0 if has_free_shipping else 50.00
            cod_collected     = float(order.get('total_price') or 0) + buyer_ship_fee

            delivery_date = order.get('received_at') or order.get('delivered_at') or order.get('date')
            if delivery_date and hasattr(delivery_date, 'strftime'):
                delivery_date = delivery_date.strftime('%Y-%m-%d')
            elif delivery_date and isinstance(delivery_date, str):
                delivery_date = delivery_date[:10]

            buyer_name  = f"{buyer.get('first_name','')} {buyer.get('last_name','')}".strip() or 'Buyer'
            seller_name = seller.get('business_name') or f"{seller.get('first_name','')} {seller.get('last_name','')}".strip() or 'Seller'

            earnings_data.append({
                'order_id':         order['id'],
                'delivery_date':    delivery_date,
                'buyer_name':       buyer_name,
                'seller_name':      seller_name,
                'status':           order.get('status', ''),
                'delivery_fee':     delivery_fee,
                'cod_collected':    cod_collected,
                'net_earnings':     net_earnings,
                'has_free_shipping': has_free_shipping,
            })
    except Exception as e:
        print(f"?? earnings Supabase error: {e}")
        import traceback; traceback.print_exc()

    total_earnings   = sum(float(e['net_earnings']) for e in earnings_data)
    total_completed  = len(earnings_data)
    avg_per_delivery = total_earnings / total_completed if total_completed > 0 else 0

    return render_template('earnings.html',
                           total_earnings=f"{total_earnings:,.2f}",
                           total_completed=total_completed,
                           avg_per_delivery=f"{avg_per_delivery:.2f}",
                           user_name=rider_name,
                           user_email=rider_email,
                           earnings_data=earnings_data)



@app.route('/add_new_product', methods=['GET', 'POST'])
def add_new_product():
    if request.method == 'POST':
        product_name = request.form['product_name']
        description = request.form['description']
        category = request.form['category']
        variations = request.form['Variations']  # This now contains the color names from images
        stock_quantity = 0  # Stock is set per-variant in Variant Inventory page
        regular_price = request.form['regular_price']
        low_stock_threshold = 5  # Default threshold; seller sets per-variant in Variant Inventory
        sku = request.form.get('sku', '').strip()  # Optional SKU field

        product_sizes = request.form.get('product_sizes', '')  # Get selected sizes
        seller_email = session.get('email')

        # Handle multiple image file uploads
        if 'product_images' not in request.files:
            flash('No file part', 'error')
            return redirect(request.url)

        files = request.files.getlist('product_images')
        if not files or all(file.filename == '' for file in files):
            flash('No selected files', 'error')
            return redirect(request.url)

        # Get color names for each image
        image_colors = request.form.getlist('image_colors[]')
        
        if len(files) != len(image_colors):
            flash('Each image must have a color name specified', 'error')
            return redirect(request.url)

        saved_filenames = []
        image_color_mapping = []
        color_variations = []
        
        for i, file in enumerate(files):
            if file and file.filename and allowed_file(file.filename):
                # Generate a unique filename with timestamp and random string
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                random_string = ''.join(random.choices(string.ascii_letters + string.digits, k=6))
                original_filename = secure_filename(file.filename)
                filename = f"{timestamp}_{random_string}_{original_filename}"
        
                # Save the file using the correct path
                file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                try:
                    file.save(file_path)
                    saved_filenames.append(filename)
                    # Map image to its color
                    color_name = image_colors[i].strip() if i < len(image_colors) else 'Default'
                    image_color_mapping.append(f"{filename}:{color_name}")
                    # Collect unique color names for variations
                    if color_name not in color_variations:
                        color_variations.append(color_name)
                    print(f"File saved successfully at: {file_path} with color: {color_name}")
                except Exception as e:
                    print(f"Error saving file: {str(e)}")
                    flash(f'Error saving file {file.filename}: {str(e)}', 'error')
                    # Clean up already saved files
                    for saved_file in saved_filenames:
                        try:
                            os.remove(os.path.join(app.config['UPLOAD_FOLDER'], saved_file))
                        except:
                            pass
                    return redirect(request.url)
            else:
                flash(f'Invalid file format for {file.filename}. Only jpg, jpeg, png, and gif allowed.', 'error')
                # Clean up already saved files
                for saved_file in saved_filenames:
                    try:
                        os.remove(os.path.join(app.config['UPLOAD_FOLDER'], saved_file))
                    except:
                        pass
                return redirect(request.url)

        if saved_filenames:
            # Store multiple filenames as comma-separated string
            images_string = ','.join(saved_filenames)

            # -- Upload images to Supabase Storage for mobile access -------
            STORAGE_BUCKET = 'product-images'
            supabase_image_urls = []
            for fname in saved_filenames:
                local_path = os.path.join(app.config['UPLOAD_FOLDER'], fname)
                try:
                    with open(local_path, 'rb') as f:
                        file_bytes = f.read()
                    # Determine content type
                    ext = fname.rsplit('.', 1)[-1].lower()
                    content_type = f'image/{ext}' if ext in ('jpg', 'jpeg', 'png', 'gif', 'webp') else 'image/jpeg'
                    storage_path = f'products/{fname}'
                    sb_admin.storage.from_(STORAGE_BUCKET).upload(
                        path=storage_path,
                        file=file_bytes,
                        file_options={'content-type': content_type, 'upsert': 'true'},
                    )
                    public_url = f"{SUPABASE_URL}/storage/v1/object/public/{STORAGE_BUCKET}/{storage_path}"
                    supabase_image_urls.append(public_url)
                    print(f"? Uploaded {fname} to Supabase Storage: {public_url}")
                except Exception as upload_err:
                    print(f"?? Supabase Storage upload failed for {fname}: {upload_err}")
                    # Fall back to local filename so the website still works
                    supabase_image_urls.append(fname)

            # Use Supabase Storage URLs if all uploads succeeded, else keep filenames
            if supabase_image_urls:
                images_string = ','.join(supabase_image_urls)
            # -------------------------------------------------------------

            # Store image-color mapping for future use
            image_color_string = ','.join(image_color_mapping)
            # Use color names as variations (comma-separated unique colors)
            variations_string = ', '.join(color_variations)

            # Auto-generate SKU if not provided
            if not sku:
                import random as _random
                sku = f"{category[:3].upper()}-{product_name[:4].upper().replace(' ', '')}-{''.join(_random.choices('0123456789', k=4))}"

            def cleanup_saved_files():
                for saved_file in saved_filenames:
                    try:
                        os.remove(os.path.join(app.config['UPLOAD_FOLDER'], saved_file))
                    except:
                        pass

            variations_list = [v.strip() for v in variations_string.split(',') if v.strip()]
            sizes_list = [s.strip() for s in product_sizes.split(',') if s.strip()]

            # -- PRIMARY: Insert into Supabase -----------------------------
            try:
                product_row = {
                    'name':                product_name,
                    'category':            category,
                    'description':         description,
                    'variations':          variations_string,
                    'price':               float(regular_price),
                    'image':               images_string,
                    'quantity':            0,
                    'low_stock_threshold': low_stock_threshold,
                    'seller_email':        seller_email,
                    'image_colors':        image_color_string,
                    'sizes':               product_sizes,
                    'sku':                 sku,
                    'is_active':           True,
                    'is_flagged':          False,
                    'sold':                0,
                }
                sb_res = sb_admin.table('products').insert(product_row).execute()

                if not sb_res.data:
                    raise Exception('Supabase insert returned no data')

                product_id = sb_res.data[0]['id']
                print(f"? Product inserted into Supabase with id={product_id}")

                # Insert placeholder variant_inventory rows (stock = 0)
                variant_rows = []
                for color in variations_list:
                    for size in sizes_list:
                        variant_rows.append({
                            'product_id':          product_id,
                            'color':               color,
                            'size':                size,
                            'stock_quantity':      0,
                            'low_stock_threshold': low_stock_threshold,
                        })

                if variant_rows:
                    sb_admin.table('variant_inventory').insert(variant_rows).execute()
                    print(f"? {len(variant_rows)} variant rows inserted into Supabase")

            except Exception as sb_err:
                print(f"? Supabase insert failed: {sb_err}")
                cleanup_saved_files()
                flash(f'Failed to save product: {sb_err}', 'error')
                return redirect(request.url)

            # -- SECONDARY: Mirror to MySQL (best-effort, non-blocking) ----
            # MySQL product mirror removed

            flash('Product added successfully! Set stock quantities in Variant Inventory.', 'success')
            return redirect(url_for('variant_inventory'))

        flash('No valid images were uploaded.', 'error')
        return redirect(request.url)
    
    # GET request - get seller name for header
    seller_name = session.get('first_name', 'Seller')
    try:
        sb_res = sb_admin.table('users').select('first_name, last_name, business_name').eq('email', session.get('email', '')).execute()
        if sb_res.data:
            u = sb_res.data[0]
            seller_name = u.get('business_name') or f"{u.get('first_name', '')} {u.get('last_name', '')}".strip() or 'Seller'
    except Exception as sb_err:
        print(f"?? Supabase name fetch failed in add_new_product: {sb_err}")
    
    return render_template('add_new_product.html', user_name=seller_name, user_email=session.get('email', 'Seller'))

@app.route('/editproduct/<int:product_id>', methods=['GET', 'POST'])
def edit_product(product_id):
    if 'email' not in session:
        return redirect(url_for('home'))

    seller_email = session['email']
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'

    if request.method == 'POST':
        try:
            # -- Validate required fields ----------------------------------
            required_fields = ['name', 'category', 'description', 'price']
            for field in required_fields:
                if field not in request.form or not request.form[field].strip():
                    flash(f'Missing required field: {field}', 'error')
                    return redirect(url_for('products'))

            name        = request.form['name'].strip()
            category    = request.form['category'].strip()
            description = request.form['description'].strip()
            price       = float(request.form['price'])
            quantity    = int(request.form.get('quantity', 0) or 0)
            low_stock_threshold = int(request.form.get('low_stock_threshold', 5) or 5)

            variations   = request.form.get('updated_variations') or request.form.get('variations') or ''
            updated_sizes = request.form.get('updated_sizes') or request.form.get('sizes') or ''
            color_option_type = request.form.get('edit_color_option_type', '')
            current_image_color_updates = request.form.get('current_image_color_updates', '')
            images_to_remove = request.form.get('images_to_remove', '')
            images_to_remove_list = [i.strip() for i in images_to_remove.split(',') if i.strip()]

            # -- Fetch current product from Supabase -----------------------
            prod_res = sb_admin.table('products') \
                .select('image, image_colors, sizes, variations') \
                .eq('id', product_id) \
                .eq('seller_email', seller_email) \
                .limit(1).execute()

            if not prod_res.data:
                flash('Product not found or you do not have permission to edit it.', 'error')
                return redirect(url_for('products'))

            current_product = prod_res.data[0]
            current_images_string      = current_product.get('image', '') or ''
            current_image_colors_string = current_product.get('image_colors', '') or ''
            current_sizes_in_db        = current_product.get('sizes', '') or ''
            current_variations_in_db   = current_product.get('variations', '') or ''
            current_images = [i.strip() for i in current_images_string.split(',') if i.strip()]

            # Preserve existing values if form sent empty
            if not updated_sizes.strip():
                updated_sizes = current_sizes_in_db or 'One Size'
            if not variations.strip():
                variations = current_variations_in_db or 'Standard'

            # -- Parse current color updates -------------------------------
            current_color_updates = {}
            if current_image_color_updates:
                for mapping in current_image_color_updates.split(','):
                    if ':' in mapping:
                        img_name, color_name = mapping.split(':', 1)
                        current_color_updates[img_name.strip()] = color_name.strip()

            # -- Build final image + color lists ---------------------------
            final_images = []
            final_image_colors = []

            for img in current_images:
                if img not in images_to_remove_list:
                    final_images.append(img)
                    if img in current_color_updates:
                        final_image_colors.append(f"{img}:{current_color_updates[img]}")
                    else:
                        existing_color = 'Unknown Color'
                        if current_image_colors_string:
                            for cm in current_image_colors_string.split(','):
                                if ':' in cm:
                                    ei, ec = cm.split(':', 1)
                                    if ei.strip() == img:
                                        existing_color = ec.strip()
                                        break
                        final_image_colors.append(f"{img}:{existing_color}")

            # Delete removed images from filesystem (non-fatal)
            for img_to_remove in images_to_remove_list:
                if img_to_remove in current_images:
                    img_path = os.path.join(app.config['UPLOAD_FOLDER'], img_to_remove)
                    try:
                        if os.path.exists(img_path):
                            os.remove(img_path)
                    except Exception:
                        pass

            # -- Handle new image uploads ----------------------------------
            if 'image' in request.files:
                files = [f for f in request.files.getlist('image') if f.filename]
                if files:
                    new_image_colors = request.form.getlist('edit_image_colors[]')
                    saved_filenames = []
                    for i, file in enumerate(files):
                        if file and allowed_file(file.filename):
                            ts = datetime.now().strftime('%Y%m%d_%H%M%S')
                            rnd = ''.join(random.choices(string.ascii_letters + string.digits, k=6))
                            filename = f"{ts}_{rnd}_{secure_filename(file.filename)}"
                            try:
                                file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                                saved_filenames.append(filename)
                                color_name = new_image_colors[i].strip() if i < len(new_image_colors) else 'Default'
                                final_image_colors.append(f"{filename}:{color_name}")
                            except Exception as fe:
                                flash(f'Error saving file: {str(fe)}', 'error')
                                return redirect(url_for('products'))
                    final_images.extend(saved_filenames)

            # -- Auto-sync variations with image colors --------------------
            if color_option_type == 'no_colors':
                variations = 'Standard'
            elif final_image_colors:
                auto_variations = []
                for cm in final_image_colors:
                    if ':' in cm:
                        _, cn = cm.split(':', 1)
                        cn = cn.strip()
                        if cn and cn not in auto_variations:
                            auto_variations.append(cn)
                variations = ', '.join(auto_variations) if auto_variations else 'Standard'
            else:
                variations = 'Standard'

            images_string       = ','.join(final_images)
            image_colors_string = ','.join(final_image_colors)

            # -- Update product in Supabase --------------------------------
            update_data = {
                'name':                name,
                'category':            category,
                'description':         description,
                'variations':          variations or current_variations_in_db or 'Standard',
                'price':               price,
                'quantity':            quantity,
                'low_stock_threshold': low_stock_threshold,
                'sizes':               updated_sizes or current_sizes_in_db or 'One Size',
                'image':               images_string,
                'image_colors':        image_colors_string,
            }

            sb_admin.table('products') \
                .update(update_data) \
                .eq('id', product_id) \
                .eq('seller_email', seller_email) \
                .execute()

            print(f"✅ Product {product_id} updated in Supabase")

            # -- Update variant_inventory in background (non-blocking) ----
            import threading
            def _sync_variants():
                try:
                    variations_list = [v.strip() for v in variations.split(',') if v.strip()]
                    sizes_list      = [s.strip() for s in updated_sizes.split(',') if s.strip()]
                    total_variants  = len(variations_list) * len(sizes_list)
                    stock_per_variant = quantity // total_variants if total_variants > 0 else quantity

                    for color in variations_list:
                        for size in sizes_list:
                            existing = sb_admin.table('variant_inventory') \
                                .select('id') \
                                .eq('product_id', product_id) \
                                .eq('color', color) \
                                .eq('size', size) \
                                .limit(1).execute()

                            if existing.data:
                                sb_admin.table('variant_inventory').update({
                                    'stock_quantity': stock_per_variant,
                                }).eq('id', existing.data[0]['id']).execute()
                            else:
                                sb_admin.table('variant_inventory').insert({
                                    'product_id':          product_id,
                                    'color':               color,
                                    'size':                size,
                                    'stock_quantity':      stock_per_variant,
                                    'low_stock_threshold': low_stock_threshold,
                                }).execute()

                    print(f"✅ Variant inventory synced for product {product_id}")
                except Exception as vi_err:
                    print(f"⚠️ Variant inventory sync failed (non-fatal): {vi_err}")

            threading.Thread(target=_sync_variants, daemon=True).start()

            # -- Stock notifications in background (non-blocking) ----------
            def _notify_stock():
                try:
                    check_and_notify_stock_levels(
                        product_id=product_id,
                        seller_email=seller_email,
                        new_quantity=quantity,
                        threshold=low_stock_threshold,
                        product_name=name,
                    )
                except Exception:
                    pass

            threading.Thread(target=_notify_stock, daemon=True).start()

            flash('Product updated successfully!', 'success')
            if is_ajax:
                return jsonify({'success': True, 'message': 'Product updated successfully!'})
            return redirect(url_for('products'))

        except Exception as e:
            import traceback; traceback.print_exc()
            if is_ajax:
                return jsonify({'success': False, 'message': f'Error updating product: {str(e)}'}), 500
            flash(f'Error updating product: {str(e)}', 'error')
            return redirect(url_for('products'))

    # GET � redirect to products page (editing is done via modal)
    try:
        prod_res = sb_admin.table('products') \
            .select('name') \
            .eq('id', product_id) \
            .eq('seller_email', seller_email) \
            .limit(1).execute()
        if prod_res.data:
            flash(f'Edit product "{prod_res.data[0]["name"]}" using the edit button on the products page.', 'info')
        else:
            flash('Product not found or you do not have permission to edit it.', 'error')
    except Exception as e:
        flash(f'Error loading product: {str(e)}', 'error')
    return redirect(url_for('products'))


@app.route('/debug_form_data/<int:product_id>', methods=['POST'])
def debug_form_data(product_id):
    """Debug endpoint to see what form data is being received"""
    if 'email' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    
    # Log all form data received
    print(f"?? DEBUG FORM DATA for product {product_id}:")
    print(f"  - All form keys: {list(request.form.keys())}")
    
    form_data = {}
    for key in request.form.keys():
        value = request.form.get(key)
        form_data[key] = value
        print(f"  - {key}: '{value}'")
    
    # Check specifically for sizes and variations
    updated_sizes = request.form.get('updated_sizes')
    updated_variations = request.form.get('updated_variations')
    
    print(f"?? CRITICAL FIELDS:")
    print(f"  - updated_sizes: '{updated_sizes}' (type: {type(updated_sizes)})")
    print(f"  - updated_variations: '{updated_variations}' (type: {type(updated_variations)})")
    
    return jsonify({
        'success': True,
        'product_id': product_id,
        'form_data': form_data,
        'updated_sizes': updated_sizes,
        'updated_variations': updated_variations,
        'sizes_received': bool(updated_sizes),
        'variations_received': bool(updated_variations)
    })

@app.route('/test_sizes_update/<int:product_id>', methods=['POST'])
def test_sizes_update(product_id):
    """Test endpoint to debug sizes update"""
    if 'email' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    
    # MySQL update_variants removed — handled by /api/seller/update-variants
    return jsonify({'success': True, 'message': 'Variants updated successfully'})



@app.route('/view_shop/<seller_email>')
def view_shop(seller_email):
    user_name = None
    if 'email' in session:
        user_name = get_user_name_from_session(default='User')

    try:
        # Seller info from Supabase
        seller_res = sb_admin.table('users').select(
            'first_name, last_name, business_name'
        ).eq('email', seller_email).limit(1).execute()

        if not seller_res.data:
            flash('Seller not found', 'error')
            return redirect(url_for('home'))

        s = seller_res.data[0]
        full_name = f"{s.get('first_name', '')} {s.get('last_name', '')}".strip()
        seller_display_name = (s.get('business_name') or '').strip() or full_name or seller_email
        seller_phone = ''
        seller_avatar_url = None

        # Products from Supabase
        prod_res = sb_admin.table('products').select(
            'id, name, category, description, price, image, quantity, sold, rating, '
            'seller_email, variations, sizes, is_active, flagged_at'
        ).eq('seller_email', seller_email).eq('is_active', True).order('id', desc=True).execute()

        raw_products = [
            p for p in (prod_res.data or [])
            if not (p.get('flagged_at') and str(p.get('flagged_at')).strip())
        ]

        # Ratings from reviews
        from collections import defaultdict
        rating_map = defaultdict(list)
        if raw_products:
            product_ids = [p['id'] for p in raw_products]
            rev_res = sb_admin.table('reviews').select('product_id, rating').in_('product_id', product_ids).execute()
            for r in (rev_res.data or []):
                rating_map[r['product_id']].append(r['rating'])

        products = []
        for p in raw_products:
            p = dict(p)
            ratings = rating_map.get(p['id'], [])
            p['rating'] = round(sum(ratings) / len(ratings), 1) if ratings else (p.get('rating') or 0)
            p['price'] = float(p.get('price') or 0)
            p['quantity'] = int(p.get('quantity') or 0)
            p['sold'] = int(p.get('sold') or 0)
            active_promotion = get_active_promotions_for_product(
                p['id'], p.get('seller_email', ''), p.get('category', '')
            )
            if active_promotion:
                promo_price, disc_amt = calculate_promotional_price(p['price'], active_promotion)
                p['has_promotion'] = True
                p['promotional_price'] = float(promo_price)
                p['discount_amount'] = float(disc_amt)
                p['promotion_type'] = active_promotion.get('type', 'percentage')
                p['promotion_code'] = active_promotion.get('code', '')
                p['promotion_discount'] = float(active_promotion.get('discount_value') or 0)
                p['discount_percentage'] = round((disc_amt / p['price']) * 100, 0) if p['price'] > 0 else 0
            else:
                p['has_promotion'] = False
                p['promotional_price'] = p['price']
                p['discount_amount'] = 0
                p['promotion_type'] = None
                p['promotion_code'] = ''
                p['promotion_discount'] = 0
                p['discount_percentage'] = 0
            products.append(p)

        return render_template('view_shop.html',
                               seller_name=seller_display_name,
                               seller_email=seller_email,
                               seller_phone_number=seller_phone,
                               seller_avatar_url=seller_avatar_url,
                               products=products,
                               total_products=len(products),
                               total_sales=sum(p['sold'] for p in products),
                               total_sales_amount=0,
                               rating=None,
                               total_ratings=0,
                               user_name=user_name,
                               user_email=session.get('email', 'User'))

    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        print(f'[view_shop] ERROR: {e}\n{tb}')
        return f"<pre>view_shop error:\n{tb}</pre>", 500
@app.route('/orders_list')
def orders_list():
    if 'email' not in session:
        return redirect(url_for('home'))

    seller_email = session['email']

    # -- Get seller name from Supabase -------------------------------------
    seller_name = session.get('first_name', 'Seller')
    try:
        sb_res = sb_admin.table('users').select('first_name, last_name, business_name').eq('email', seller_email).execute()
        if sb_res.data:
            u = sb_res.data[0]
            seller_name = u.get('business_name') or f"{u.get('first_name', '')} {u.get('last_name', '')}".strip() or 'Seller'
    except Exception as sb_err:
        print(f"?? Supabase name fetch failed in orders_list: {sb_err}")

    orders = []

    # -- PRIMARY: Supabase --------------------------------------------------
    try:
        orders_res = sb_admin.table('orders') \
            .select('*') \
            .eq('seller_email', seller_email) \
            .not_.in_('status', ['Completed', 'Cancelled']) \
            .order('date', desc=True) \
            .execute()
        raw_orders = orders_res.data or []

        # Batch-fetch product prices AND images from products table
        product_ids = list({o.get('product_id') for o in raw_orders if o.get('product_id')})
        product_price_map = {}
        product_image_map = {}
        if product_ids:
            try:
                pr = sb_admin.table('products') \
                    .select('id, price, image, image_colors') \
                    .in_('id', product_ids) \
                    .execute()
                for p in (pr.data or []):
                    pid_key = int(p['id'])
                    product_price_map[pid_key] = float(p.get('price') or 0)
                    # Store image and image_colors for color-matched lookup
                    raw_img = (p.get('image') or '').strip()
                    image_colors_raw = p.get('image_colors') or ''
                    product_image_map[pid_key] = {
                        'image': raw_img,
                        'image_colors': image_colors_raw,
                    }
                print(f"✅ product_price_map: {product_price_map}")
            except Exception as e:
                print(f"❌ product price/image fetch error: {e}")

        # Batch-fetch buyer info
        buyer_emails = list({o.get('email', '') for o in raw_orders if o.get('email')})
        buyer_map = {}
        if buyer_emails:
            try:
                br = sb_admin.table('users') \
                    .select('email, first_name, last_name, phone') \
                    .in_('email', buyer_emails) \
                    .execute()
                for b in (br.data or []):
                    buyer_map[b['email']] = b
            except Exception:
                pass

        # Batch-fetch rider info
        rider_emails = list({o.get('rider_email', '') for o in raw_orders if o.get('rider_email')})
        rider_map = {}
        if rider_emails:
            try:
                rr = sb_admin.table('users') \
                    .select('email, first_name, last_name') \
                    .in_('email', rider_emails) \
                    .execute()
                for r in (rr.data or []):
                    rider_map[r['email']] = r
            except Exception:
                pass

        # Fetch seller address/phone once
        seller_info = {}
        try:
            si = sb_admin.table('users') \
                .select('business_name, house_street, barangay, city, province, region, zip_code, phone') \
                .eq('email', seller_email) \
                .execute()
            if si.data:
                s = si.data[0]
                seller_info = {
                    'seller_business_name': s.get('business_name') or '',
                    'seller_address': ', '.join(filter(None, [
                        s.get('house_street', ''), s.get('barangay', ''),
                        s.get('city', ''), s.get('province', ''),
                        s.get('region', ''), s.get('zip_code', ''),
                    ])),
                    'seller_phone': s.get('phone') or '',
                }
        except Exception:
            pass

        import datetime as _dt
        for o in raw_orders:
            # Buyer info
            buyer = buyer_map.get(o.get('email', ''), {})
            o['first_name']  = buyer.get('first_name') or ''
            o['last_name']   = buyer.get('last_name') or ''
            o['phone']       = buyer.get('phone') or ''

            # Rider info
            rider = rider_map.get(o.get('rider_email', ''), {})
            rf = rider.get('first_name') or ''
            rl = rider.get('last_name') or ''
            o['rider_name'] = f"{rf} {rl}".strip() or None

            # Seller info
            o.update(seller_info)

            # Numeric fields
            o['total_price']    = float(o.get('total_price') or 0)
            pid = o.get('product_id')
            unit_price = product_price_map.get(int(pid), 0) if pid else 0
            qty = int(o.get('quantity') or 1)
            o['original_price'] = unit_price if unit_price else o['total_price']
            o['quantity']       = qty
            print(f"  order {o.get('id')}: pid={pid}, unit_price={unit_price}, orig={o['original_price']}, total={o['total_price']}")

            # Promotion defaults
            o.setdefault('promotion_type', '')
            o.setdefault('promotion_name', '')
            o.setdefault('discount_amount', 0)
            o.setdefault('discount_percentage', 0)

            # Date - format to readable PHT (UTC+8)
            raw_date = o.get('date')
            print(f"[orders_list] order {o.get('id')} raw date: {raw_date!r}")
            if raw_date:
                try:
                    from datetime import datetime as _datetime, timezone, timedelta
                    dt = _datetime.fromisoformat(str(raw_date).replace('Z', '+00:00'))
                    pht = timezone(timedelta(hours=8))
                    if dt.tzinfo is not None:
                        dt = dt.astimezone(pht)
                    else:
                        dt = dt.replace(tzinfo=timezone.utc).astimezone(pht)
                    o['date'] = dt.strftime('%b %d, %Y %I:%M %p')
                except Exception:
                    o['date'] = str(raw_date)[:16]
            else:
                o['date'] = ''

            # Image - resolve URL: use color-matched image from product's image_colors
            raw_img = (o.get('image') or '').strip()
            _pid    = o.get('product_id')
            selected_color = (o.get('variations') or '').strip().lower()

            def _resolve_img(img_val):
                """Convert filename or URL to a displayable URL."""
                if not img_val:
                    return ''
                s = str(img_val).strip()
                if s.startswith('http://') or s.startswith('https://'):
                    return s
                # Plain filename — build Supabase Storage URL
                fname = s.split('/')[-1]  # get just the filename
                return f"{SUPABASE_URL}/storage/v1/object/public/product-images/products/{fname}"

            resolved_url = ''

            if raw_img.startswith('http://') or raw_img.startswith('https://'):
                resolved_url = raw_img
            elif _pid and int(_pid) in product_image_map:
                prod_data = product_image_map[int(_pid)]
                image_colors_raw = prod_data.get('image_colors') or ''
                all_images_raw   = prod_data.get('image') or ''

                # Try color-matched image
                if selected_color and image_colors_raw:
                    color_map = _parse_image_colors_dict(image_colors_raw, all_images_raw)
                    matched = color_map.get(selected_color)
                    if not matched:
                        for k, v in color_map.items():
                            if selected_color in k or k in selected_color:
                                matched = v
                                break
                    if matched:
                        resolved_url = _resolve_img(matched)

                # Fallback: use first image
                if not resolved_url and all_images_raw:
                    first_img = all_images_raw.split(',')[0].strip()
                    resolved_url = _resolve_img(first_img)
            elif raw_img:
                # Order has a filename — convert to Supabase Storage URL
                resolved_url = _resolve_img(raw_img)

            o['image_url'] = resolved_url
            o['image']     = ''  # always use image_url

            # product_sizes fallback
            o.setdefault('product_sizes', '')

        orders = raw_orders
        print(f"? orders_list Supabase: {len(orders)} orders for seller {seller_email}")

    except Exception as sb_err:
        print(f"?? orders_list Supabase failed: {sb_err}")

        # MySQL fallback removed

    return render_template('order_lists.html', orders=orders,
                           user_name=seller_name,
                           user_email=seller_email)


@app.route('/seller_order_history')
def seller_order_history():
    if 'email' not in session:
        return redirect(url_for('home'))

    seller_email = session['email']

    # Get seller name from Supabase
    seller_name = session.get('first_name', 'Seller')
    try:
        sb_res = sb_admin.table('users').select('first_name, last_name, business_name').eq('email', seller_email).execute()
        if sb_res.data:
            u = sb_res.data[0]
            seller_name = u.get('business_name') or f"{u.get('first_name', '')} {u.get('last_name', '')}".strip() or 'Seller'
    except Exception as e:
        print(f"seller_order_history name fetch error: {e}")

    orders = []
    completed_count = 0
    cancelled_count = 0
    total_revenue = 0.0

    try:
        # Fetch completed + cancelled orders from Supabase
        res = sb_admin.table('orders') \
            .select('id, name, quantity, date, delivered_at, received_at, cancelled_at, total_price, shipping_fee, payment_method, status, email, address, seller_email, product_id, image, variations, size') \
            .eq('seller_email', seller_email) \
            .in_('status', ['Completed', 'Cancelled']) \
            .order('date', desc=True) \
            .execute()

        raw_orders = res.data or []

        # Collect buyer emails for name lookup
        buyer_emails = list({o['email'] for o in raw_orders if o.get('email')})
        buyer_map = {}
        if buyer_emails:
            users_res = sb_admin.table('users') \
                .select('email, first_name, last_name') \
                .in_('email', buyer_emails) \
                .execute()
            for u in (users_res.data or []):
                buyer_map[u['email']] = u

        for order in raw_orders:
            buyer = buyer_map.get(order.get('email') or '', {})
            order['first_name'] = buyer.get('first_name') or ''
            order['last_name']  = buyer.get('last_name')  or ''

            # Normalize price
            try:
                order['total_price'] = float(order.get('total_price') or 0)
            except (ValueError, TypeError):
                order['total_price'] = 0.0

            # Format date — use the most accurate timestamp for the order status
            from datetime import datetime, timezone, timedelta

            def _fmt_dt(raw):
                if not raw:
                    return None
                try:
                    if isinstance(raw, str):
                        dt = datetime.fromisoformat(raw.replace('Z', '+00:00'))
                    else:
                        dt = raw
                    # Convert to Philippine Time (UTC+8)
                    pht = timezone(timedelta(hours=8))
                    if dt.tzinfo is not None:
                        dt = dt.astimezone(pht)
                    else:
                        # Assume UTC if no timezone info
                        dt = dt.replace(tzinfo=timezone.utc).astimezone(pht)
                    return dt.strftime('%b %d, %Y %I:%M %p')
                except Exception as e:
                    print(f"_fmt_dt error for {raw!r}: {e}")
                    return str(raw)[:16]

            status_lower = (order.get('status') or '').lower()
            if status_lower == 'completed':
                # Use received_at > delivered_at > date
                display_date = _fmt_dt(order.get('received_at')) or \
                               _fmt_dt(order.get('delivered_at')) or \
                               _fmt_dt(order.get('date'))
            elif status_lower == 'cancelled':
                # Use cancelled_at > date
                display_date = _fmt_dt(order.get('cancelled_at')) or \
                               _fmt_dt(order.get('date'))
            else:
                display_date = _fmt_dt(order.get('date'))

            order['date'] = display_date or 'N/A'

            order['original_price']      = order['total_price']
            order['promotion_type']      = ''
            order['promotion_name']      = ''
            order['discount_amount']     = 0
            order['discount_percentage'] = 0

            # Resolve image URL
            img = (order.get('image') or '').strip()
            if img and not img.startswith('http') and not img.startswith('/'):
                order['image'] = img  # keep as filename for product_img filter
            
            # Stats
            if order['status'] == 'Completed':
                completed_count += 1
                total_revenue += order['total_price']
            elif order['status'] == 'Cancelled':
                cancelled_count += 1

            orders.append(order)

    except Exception as e:
        import traceback; traceback.print_exc()
        print(f"seller_order_history error: {e}")

    return render_template('seller_order_history.html',
                           orders=orders,
                           user_name=seller_name,
                           user_email=seller_email,
                           completed_count=completed_count,
                           cancelled_count=cancelled_count,
                           total_revenue=f"{total_revenue:.2f}",
                           total_orders=len(orders))

# ── Polling endpoint: seller order statuses ──────────────────────────────────
@app.route('/api/orders/seller-statuses', methods=['GET'])
def seller_order_statuses():
    """Returns a lightweight JSON list of {id, status} for the logged-in seller.
    Used by the order_list page to auto-sync statuses without a full page reload."""
    if 'email' not in session:
        return jsonify({'success': False}), 401
    seller_email = session['email']
    try:
        res = sb_admin.table('orders') \
            .select('id, status') \
            .eq('seller_email', seller_email) \
            .not_.in_('status', ['Completed', 'Cancelled']) \
            .execute()
        return jsonify({'success': True, 'orders': res.data or []})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

# ── Polling endpoint: buyer order statuses ───────────────────────────────────
@app.route('/api/orders/buyer-statuses', methods=['GET'])
def buyer_order_statuses():
    """Returns a lightweight JSON list of {id, status} for the logged-in buyer.
    Used by the orders page to auto-sync statuses without a full page reload."""
    if 'email' not in session:
        return jsonify({'success': False}), 401
    buyer_email = session['email']
    try:
        res = sb_admin.table('orders') \
            .select('id, status') \
            .eq('email', buyer_email) \
            .execute()
        return jsonify({'success': True, 'orders': res.data or []})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/seller-order-details/<int:order_id>')
def seller_order_details(order_id):
    if 'email' not in session:
        return jsonify({'success': False, 'message': 'Not logged in'}), 401

    seller_email = session['email']
    try:
        res = sb_admin.table('orders') \
            .select('id, name, quantity, date, total_price, shipping_fee, payment_method, status, email, address, seller_email, product_id, image, variations, size') \
            .eq('id', order_id) \
            .eq('seller_email', seller_email) \
            .limit(1).execute()

        if not res.data:
            return jsonify({'success': False, 'message': 'Order not found'}), 404

        order = res.data[0]

        # Get buyer name
        buyer_res = sb_admin.table('users') \
            .select('first_name, last_name') \
            .eq('email', order.get('email', '')) \
            .limit(1).execute()
        if buyer_res.data:
            order['first_name'] = buyer_res.data[0].get('first_name', '')
            order['last_name']  = buyer_res.data[0].get('last_name', '')
        else:
            order['first_name'] = ''
            order['last_name']  = ''

        # Format date
        raw_date = order.get('date') or ''
        if raw_date:
            try:
                from datetime import datetime
                dt = datetime.fromisoformat(str(raw_date).replace('Z', '+00:00'))
                order['date'] = dt.strftime('%b %d, %Y %I:%M %p')
            except Exception:
                order['date'] = str(raw_date)[:10]

        # Resolve image URL
        img = (order.get('image') or '').strip()
        if img and not img.startswith('http') and not img.startswith('/'):
            order['image'] = f'/static/images/uploads/{img}'

        # Normalize price
        try:
            order['total_price'] = float(order.get('total_price') or 0)
        except (ValueError, TypeError):
            order['total_price'] = 0.0

        return jsonify({'success': True, 'order': order})

    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/delete-order-history/<int:order_id>', methods=['DELETE'])
def delete_order_history(order_id):
    if 'email' not in session:
        return jsonify({'success': False, 'message': 'Not logged in'}), 401

    seller_email = session['email']
    try:
        # Only allow deleting completed/cancelled orders belonging to this seller
        res = sb_admin.table('orders') \
            .delete() \
            .eq('id', order_id) \
            .eq('seller_email', seller_email) \
            .in_('status', ['Completed', 'Cancelled']) \
            .execute()

        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/rider-notifications')
def get_rider_notifications():
    if 'email' not in session:
        return jsonify({'success': False, 'message': 'Authentication required'}), 401

    rider_email = session['email']
    try:
        res = sb_admin.table('rider_notifications').select('id, message, order_id, is_read, created_at').eq('rider_email', rider_email).order('created_at', desc=True).limit(20).execute()
        notifications = res.data or []
        unread_count  = sum(1 for n in notifications if not n.get('is_read'))

        formatted = []
        for n in notifications:
            formatted.append({
                'id':         n['id'],
                'message':    n['message'],
                'order_id':   n.get('order_id'),
                'is_read':    bool(n.get('is_read')),
                'created_at': n['created_at'][:19].replace('T', ' ') if n.get('created_at') else None,
            })

        return jsonify({'success': True, 'unread_count': unread_count, 'notifications': formatted})
    except Exception as e:
        print(f"Error fetching rider notifications: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/rider-notifications/mark-read/<int:notification_id>', methods=['POST'])
def mark_rider_notification_read(notification_id):
    if 'email' not in session:
        return jsonify({'success': False, 'message': 'Authentication required'}), 401
    try:
        sb_admin.table('rider_notifications').update({'is_read': True}).eq('id', notification_id).eq('rider_email', session['email']).execute()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/rider-notifications/mark-all-read', methods=['POST'])
def mark_all_rider_notifications_read():
    if 'email' not in session:
        return jsonify({'success': False, 'message': 'Authentication required'}), 401
    try:
        sb_admin.table('rider_notifications').update({'is_read': True}).eq('rider_email', session['email']).eq('is_read', False).execute()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/rider-notifications/delete-all', methods=['DELETE'])
def delete_all_rider_notifications():
    if 'email' not in session:
        return jsonify({'success': False, 'message': 'Authentication required'}), 401
    try:
        sb_admin.table('rider_notifications').delete().eq('rider_email', session['email']).execute()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/mobile/rider/messages', methods=['GET'])
def mobile_get_rider_messages():
    """Mobile: Get all conversations for a rider by email param."""
    rider_email = request.args.get('rider_email', '').strip()
    if not rider_email:
        return jsonify({'success': False, 'error': 'rider_email required'}), 400
    try:
        orders_res = sb_admin.table('orders').select('id, email, seller_email').eq('rider_email', rider_email).execute()
        orders    = orders_res.data or []
        order_ids = [o['id'] for o in orders]
        order_map = {o['id']: o for o in orders}
        if not order_ids:
            return jsonify({'success': True, 'conversations': []})

        contact_emails = list({e for o in orders for e in [o.get('email'), o.get('seller_email')] if e})
        users_map = {}
        if contact_emails:
            ur = sb_admin.table('users').select('email, first_name, last_name, business_name').in_('email', contact_emails).execute()
            users_map = {u['email']: u for u in (ur.data or [])}

        conversations = []

        # Buyer-rider
        brm = sb_admin.table('buyer_rider_messages').select('order_id, sender_email, receiver_email, message, created_at, is_read').in_('order_id', order_ids).order('created_at', desc=True).execute()
        brm_by_order = {}
        for m in (brm.data or []):
            brm_by_order.setdefault(m['order_id'], []).append(m)
        for oid, msgs in brm_by_order.items():
            order = order_map.get(oid, {})
            buyer = users_map.get(order.get('email', ''), {})
            last  = msgs[0]
            unread = sum(1 for m in msgs if not m.get('is_read') and m.get('receiver_email') == rider_email)
            conversations.append({'order_id': oid, 'contact_email': order.get('email',''),
                'contact_name': f"{buyer.get('first_name','')} {buyer.get('last_name','')}".strip() or 'Buyer',
                'last_message': last.get('message'), 'last_message_at': last.get('created_at'),
                'unread_count': unread, 'conversation_type': 'buyer'})

        # Seller-rider
        srm = sb_admin.table('seller_rider_messages').select('order_id, sender_email, receiver_email, message, created_at, is_read').in_('order_id', order_ids).order('created_at', desc=True).execute()
        srm_by_order = {}
        for m in (srm.data or []):
            srm_by_order.setdefault(m['order_id'], []).append(m)
        for oid, msgs in srm_by_order.items():
            order  = order_map.get(oid, {})
            seller = users_map.get(order.get('seller_email', ''), {})
            last   = msgs[0]
            unread = sum(1 for m in msgs if not m.get('is_read') and m.get('receiver_email') == rider_email)
            seller_name = seller.get('business_name') or f"{seller.get('first_name','')} {seller.get('last_name','')}".strip() or 'Seller'
            conversations.append({'order_id': oid, 'contact_email': order.get('seller_email',''),
                'contact_name': seller_name, 'last_message': last.get('message'),
                'last_message_at': last.get('created_at'), 'unread_count': unread,
                'conversation_type': 'seller'})

        conversations.sort(key=lambda x: x['last_message_at'] or '', reverse=True)
        return jsonify({'success': True, 'conversations': conversations})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/rider/messages', methods=['GET'])
def get_rider_messages():
    """Get all conversations for rider (messages from buyers and sellers)"""
    if 'email' not in session:
        return jsonify({'success': False, 'error': 'Please login first'}), 401

    rider_email = session.get('email')
    user_type   = session.get('user_type')
    if user_type and user_type.lower() != 'rider':
        return jsonify({'success': False, 'error': f'Only riders can access this. Your user_type is: {user_type}'}), 403

    try:
        # Rider name
        rn = sb_admin.table('users').select('first_name, last_name').eq('email', rider_email).execute()
        rider_name = 'Rider'
        if rn.data:
            rider_name = f"{rn.data[0].get('first_name','')} {rn.data[0].get('last_name','')}".strip() or 'Rider'

        # Orders assigned to this rider
        orders_res = sb_admin.table('orders').select('id, email, seller_email').eq('rider_email', rider_email).execute()
        orders     = orders_res.data or []
        order_ids  = [o['id'] for o in orders]
        order_map  = {o['id']: o for o in orders}

        if not order_ids:
            return jsonify({'success': True, 'conversations': []})

        # Collect all contact emails for batch lookup
        contact_emails = list({e for o in orders for e in [o.get('email'), o.get('seller_email')] if e})
        users_map = {}
        if contact_emails:
            ur = sb_admin.table('users').select('email, first_name, last_name, business_name, profile_picture').in_('email', contact_emails).execute()
            users_map = {u['email']: u for u in (ur.data or [])}

        formatted_conversations = []

        # Buyer-rider conversations
        brm_res = sb_admin.table('buyer_rider_messages').select('order_id, sender_email, receiver_email, message, created_at, is_read').in_('order_id', order_ids).order('created_at', desc=True).execute()
        brm_msgs = brm_res.data or []

        # Group by order_id
        brm_by_order = {}
        for m in brm_msgs:
            oid = m['order_id']
            if oid not in brm_by_order:
                brm_by_order[oid] = []
            brm_by_order[oid].append(m)

        for oid, msgs in brm_by_order.items():
            order       = order_map.get(oid, {})
            buyer_email = order.get('email', '')
            buyer       = users_map.get(buyer_email, {})
            last_msg    = msgs[0] if msgs else {}
            unread      = sum(1 for m in msgs if not m.get('is_read') and m.get('receiver_email') == rider_email)

            formatted_conversations.append({
                'conversation_id':       f"buyer_order_{oid}",
                'order_id':              oid,
                'contact_email':         buyer_email,
                'last_message_at':       last_msg.get('created_at'),
                'contact_name':          f"{buyer.get('first_name','')} {buyer.get('last_name','')}".strip() or 'Buyer',
                'contact_profile_picture': buyer.get('profile_picture'),
                'unread_count':          unread,
                'last_message':          last_msg.get('message'),
                'conversation_type':     'buyer',
                'rider_name':            rider_name,
            })

        # Seller-rider conversations
        srm_res = sb_admin.table('seller_rider_messages').select('order_id, sender_email, receiver_email, message, created_at, is_read').in_('order_id', order_ids).order('created_at', desc=True).execute()
        srm_msgs = srm_res.data or []

        srm_by_order = {}
        for m in srm_msgs:
            oid = m['order_id']
            if oid not in srm_by_order:
                srm_by_order[oid] = []
            srm_by_order[oid].append(m)

        for oid, msgs in srm_by_order.items():
            order        = order_map.get(oid, {})
            seller_email = order.get('seller_email', '')
            seller       = users_map.get(seller_email, {})
            last_msg     = msgs[0] if msgs else {}
            unread       = sum(1 for m in msgs if not m.get('is_read') and m.get('receiver_email') == rider_email)
            seller_name  = seller.get('business_name') or f"{seller.get('first_name','')} {seller.get('last_name','')}".strip() or 'Seller'

            formatted_conversations.append({
                'conversation_id':       f"seller_order_{oid}",
                'order_id':              oid,
                'contact_email':         seller_email,
                'last_message_at':       last_msg.get('created_at'),
                'contact_name':          seller_name,
                'contact_profile_picture': seller.get('profile_picture'),
                'unread_count':          unread,
                'last_message':          last_msg.get('message'),
                'conversation_type':     'seller',
                'rider_name':            rider_name,
            })

        formatted_conversations.sort(key=lambda x: x['last_message_at'] or '', reverse=True)
        return jsonify({'success': True, 'conversations': formatted_conversations[:20]})

    except Exception as e:
        print(f"Error getting rider messages: {e}")
        import traceback; traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/rider/conversation-messages', methods=['GET'])
def get_rider_conversation_messages():
    """Get messages for a specific order conversation for rider"""
    if 'email' not in session:
        return jsonify({'success': False, 'error': 'Please login first'}), 401

    rider_email = session.get('email')
    user_type   = session.get('user_type')
    if user_type and user_type.lower() != 'rider':
        return jsonify({'success': False, 'error': f'Only riders can access this. Your user_type is: {user_type}'}), 403

    order_id = request.args.get('order_id')
    if not order_id:
        return jsonify({'success': False, 'error': 'Missing order_id'}), 400

    try:
        # Verify order is assigned to this rider
        order_res = sb_admin.table('orders').select('id, email').eq('id', order_id).eq('rider_email', rider_email).execute()
        if not order_res.data:
            return jsonify({'success': False, 'error': 'Order not found or not assigned to you'}), 404

        buyer_email = order_res.data[0].get('email', '')

        # Batch-fetch buyer and rider info
        emails = list({e for e in [buyer_email, rider_email] if e})
        users_map = {}
        if emails:
            ur = sb_admin.table('users').select('email, first_name, last_name, profile_picture').in_('email', emails).execute()
            users_map = {u['email']: u for u in (ur.data or [])}

        buyer = users_map.get(buyer_email, {})
        rider = users_map.get(rider_email, {})

        msgs_res = sb_admin.table('buyer_rider_messages').select('sender_email, receiver_email, message, created_at').eq('order_id', order_id).order('created_at').execute()
        messages = [{'sender_email': m['sender_email'], 'receiver_email': m['receiver_email'], 'message': m['message'], 'created_at': m['created_at']} for m in (msgs_res.data or [])]

        return jsonify({
            'success':               True,
            'messages':              messages,
            'buyer_name':            f"{buyer.get('first_name','')} {buyer.get('last_name','')}".strip() or 'Buyer',
            'buyer_email':           buyer_email,
            'buyer_profile_picture': buyer.get('profile_picture'),
            'rider_name':            f"{rider.get('first_name','')} {rider.get('last_name','')}".strip() or 'Rider',
            'rider_email':           rider_email,
            'rider_profile_picture': rider.get('profile_picture'),
            'order_id':              order_id,
        })
    except Exception as e:
        print(f"Error getting rider conversation messages: {e}")
        import traceback; traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/rider/conversations/delete', methods=['POST'])
def delete_rider_conversation():
    """Delete a conversation for rider"""
    if 'email' not in session:
        return jsonify({'success': False, 'error': 'Please login first'}), 401

    rider_email = session.get('email')
    data = request.get_json()
    conversation_id = data.get('conversation_id')
    if not conversation_id:
        return jsonify({'success': False, 'error': 'Conversation ID required'}), 400

    try:
        order_id_str = conversation_id
        for prefix in ['buyer_order_', 'seller_order_', 'rider_order_', 'buyer_', 'seller_', 'order_']:
            if order_id_str.startswith(prefix):
                order_id_str = order_id_str.replace(prefix, '', 1)
                break
        try:
            order_id = int(order_id_str)
        except ValueError:
            return jsonify({'success': False, 'error': f'Invalid conversation ID format: {conversation_id}'}), 400

        brm = sb_admin.table('buyer_rider_messages').delete().eq('order_id', order_id).execute()
        srm = sb_admin.table('seller_rider_messages').delete().eq('order_id', order_id).execute()
        total = len(brm.data or []) + len(srm.data or [])
        return jsonify({'success': True, 'messages_deleted': total})
    except Exception as e:
        print(f"Error deleting rider conversation: {e}")
        import traceback; traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/rider/conversations/delete-all', methods=['POST'])
def delete_all_rider_conversations():
    """Delete all conversations for rider"""
    if 'email' not in session:
        return jsonify({'success': False, 'error': 'Please login first'}), 401

    rider_email = session.get('email')
    try:
        orders_res = sb_admin.table('orders').select('id').eq('rider_email', rider_email).execute()
        order_ids  = [o['id'] for o in (orders_res.data or [])]
        total = 0
        if order_ids:
            brm = sb_admin.table('buyer_rider_messages').delete().in_('order_id', order_ids).execute()
            srm = sb_admin.table('seller_rider_messages').delete().in_('order_id', order_ids).execute()
            total = len(brm.data or []) + len(srm.data or [])
        return jsonify({'success': True, 'deleted_count': total})
    except Exception as e:
        print(f"Error deleting all rider conversations: {e}")
        import traceback; traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/rider/send-message', methods=['POST'])
def send_rider_message():
    """Send a message from rider to buyer"""
    if 'email' not in session:
        return jsonify({'success': False, 'error': 'Please login first'}), 401

    rider_email = session.get('email')
    user_type   = session.get('user_type')
    if user_type and user_type.lower() != 'rider':
        return jsonify({'success': False, 'error': f'Only riders can send messages. Your user_type is: {user_type}'}), 403

    data     = request.get_json()
    order_id = data.get('order_id')
    message  = data.get('message')
    if not order_id or not message:
        return jsonify({'success': False, 'error': 'Missing order_id or message'}), 400

    try:
        order_res = sb_admin.table('orders').select('email').eq('id', order_id).eq('rider_email', rider_email).execute()
        if not order_res.data:
            return jsonify({'success': False, 'error': 'Order not found or not assigned to you'}), 404

        buyer_email = order_res.data[0]['email']
        sb_admin.table('buyer_rider_messages').insert({'order_id': order_id, 'sender_email': rider_email, 'receiver_email': buyer_email, 'message': message}).execute()
        return jsonify({'success': True})
    except Exception as e:
        print(f"Error sending rider message: {e}")
        import traceback; traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/rider/messages/mark-read', methods=['POST'])
def mark_rider_messages_read():
    """Mark messages as read for a specific order for rider"""
    if 'email' not in session:
        return jsonify({'success': False, 'error': 'Please login first'}), 401

    rider_email = session.get('email')
    order_id    = (request.get_json() or {}).get('order_id')
    if not order_id:
        return jsonify({'success': False, 'error': 'Missing order_id'}), 400

    try:
        brm = sb_admin.table('buyer_rider_messages').update({'is_read': True}).eq('order_id', order_id).eq('receiver_email', rider_email).eq('is_read', False).execute()
        srm = sb_admin.table('seller_rider_messages').update({'is_read': True}).eq('order_id', order_id).eq('receiver_email', rider_email).eq('is_read', False).execute()
        buyer_rows  = len(brm.data or [])
        seller_rows = len(srm.data or [])
        return jsonify({'success': True, 'affected_rows': buyer_rows + seller_rows, 'buyer_messages': buyer_rows, 'seller_messages': seller_rows})
    except Exception as e:
        print(f"Error marking rider messages as read: {e}")
        import traceback; traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/rider/buyer-messages', methods=['GET'])
def get_rider_buyer_messages():
    """Get chat messages between rider and buyer for a specific order (rider's perspective)"""
    if 'email' not in session:
        return jsonify({'success': False, 'error': 'Please login first'}), 401

    try:
        rider_email = session.get('email')
        order_id    = request.args.get('order_id')
        if not order_id:
            return jsonify({'success': False, 'error': 'Missing order_id'}), 400

        order_res = sb_admin.table('orders').select('email').eq('id', order_id).eq('rider_email', rider_email).execute()
        if not order_res.data:
            return jsonify({'success': False, 'error': 'Order not found or not assigned to you'}), 404

        buyer_email = order_res.data[0].get('email', '')
        emails = list({e for e in [buyer_email, rider_email] if e})
        users_map = {}
        if emails:
            ur = sb_admin.table('users').select('email, first_name, last_name, profile_picture').in_('email', emails).execute()
            users_map = {u['email']: u for u in (ur.data or [])}

        buyer = users_map.get(buyer_email, {})
        rider = users_map.get(rider_email, {})

        msgs_res = sb_admin.table('buyer_rider_messages').select('sender_email, receiver_email, message, created_at').eq('order_id', order_id).order('created_at').execute()
        messages = [{'sender_email': m['sender_email'], 'receiver_email': m['receiver_email'], 'message': m['message'], 'created_at': m['created_at']} for m in (msgs_res.data or [])]

        return jsonify({
            'success':               True,
            'messages':              messages,
            'buyer_name':            f"{buyer.get('first_name','')} {buyer.get('last_name','')}".strip() or 'Buyer',
            'buyer_email':           buyer_email,
            'buyer_profile_picture': buyer.get('profile_picture'),
            'rider_name':            f"{rider.get('first_name','')} {rider.get('last_name','')}".strip() or 'Rider',
            'rider_email':           rider_email,
            'rider_profile_picture': rider.get('profile_picture'),
            'order_id':              order_id,
        })
    except Exception as e:
        print(f"Error getting buyer messages: {e}")
        import traceback; traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/rider/buyer-messages/send', methods=['POST'])
def send_rider_buyer_message():
    """Send a message from rider to buyer"""
    if 'email' not in session:
        return jsonify({'success': False, 'error': 'Please login first'}), 401

    try:
        rider_email    = session.get('email')
        data           = request.get_json()
        order_id       = data.get('order_id')
        message        = data.get('message')
        receiver_email = data.get('receiver_email')

        if not order_id or not message:
            return jsonify({'success': False, 'error': 'Missing required fields (order_id and message)'}), 400

        if not receiver_email:
            order_res = sb_admin.table('orders').select('email').eq('id', order_id).eq('rider_email', rider_email).execute()
            if not order_res.data:
                return jsonify({'success': False, 'error': 'Order not found or not assigned to you'}), 404
            receiver_email = order_res.data[0]['email']

        sb_admin.table('buyer_rider_messages').insert({'order_id': order_id, 'sender_email': rider_email, 'receiver_email': receiver_email, 'message': message}).execute()
        return jsonify({'success': True, 'message': 'Message sent successfully'})
    except Exception as e:
        print(f"Error sending buyer message: {e}")
        import traceback; traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/rider/buyer-messages/mark-read', methods=['POST'])
def mark_rider_buyer_messages_read():
    """Mark buyer-rider messages as read for a specific order (rider side)"""
    if 'email' not in session:
        return jsonify({'success': False, 'error': 'Please login first'}), 401

    rider_email = session.get('email')
    order_id    = (request.get_json() or {}).get('order_id')
    if not order_id:
        return jsonify({'success': False, 'error': 'Missing order_id'}), 400

    try:
        # Verify order is assigned to this rider
        order_res = sb_admin.table('orders').select('id').eq('id', order_id).eq('rider_email', rider_email).execute()
        if not order_res.data:
            return jsonify({'success': False, 'error': 'Order not found or not assigned to you'}), 404

        res = sb_admin.table('buyer_rider_messages').update({'is_read': True}).eq('order_id', order_id).eq('receiver_email', rider_email).eq('is_read', False).execute()
        return jsonify({'success': True, 'affected_rows': len(res.data or [])})
    except Exception as e:
        print(f"Error marking buyer-rider messages as read: {e}")
        import traceback; traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/seller-order-details/<int:order_id>')
def get_seller_order_details(order_id):
    """Get detailed order info for seller  Supabase"""
    if 'email' not in session:
        return jsonify({'success': False, 'error': 'Authentication required'}), 401
    seller_email = session.get('email')
    try:
        ord_res = sb_admin.table('orders').select('*').eq('id', order_id).eq('seller_email', seller_email).limit(1).execute()
        if not ord_res.data:
            return jsonify({'success': False, 'error': 'Order not found'}), 404
        o = ord_res.data[0]
        emails = {e for e in [o.get('email'), o.get('rider_email')] if e}
        user_map = {}
        if emails:
            ur = sb_admin.table('users').select('email, first_name, last_name, phone, address').in_('email', list(emails)).execute()
            user_map = {u['email']: u for u in (ur.data or [])}
        buyer = user_map.get(o.get('email', ''), {})
        rider = user_map.get(o.get('rider_email', ''), {})
        return jsonify({
            'success': True,
            'order': {
                'id': o['id'], 'name': o.get('name',''), 'quantity': o.get('quantity',1),
                'total_price': float(o.get('total_price') or 0), 'status': o.get('status',''),
                'payment_method': o.get('payment_method',''), 'date': str(o.get('date','')),
                'variations': o.get('variations',''), 'size': o.get('size',''),
                'image': o.get('image',''), 'address': o.get('address',''),
                'customer_phone': buyer.get('phone',''),
                'customer_address': buyer.get('address','') or o.get('address',''),
                'customer_first_name': buyer.get('first_name',''),
                'customer_last_name': buyer.get('last_name',''),
                'rider_first_name': rider.get('first_name',''),
                'rider_last_name': rider.get('last_name',''),
                'rider_email': o.get('rider_email',''),
            }
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/update_order_status/<int:order_id>', methods=['POST'])
def update_order_status(order_id):
    new_status = request.form['stat']
    seller_email = session.get('email')

    print(f"?? Updating order {order_id} status to: {new_status}")
    print(f"?? Seller: {seller_email}")

    # -- PRIMARY: Supabase --------------------------------------------------
    try:
        # Fetch current order from Supabase
        order_res = sb_admin.table('orders') \
            .select('id, name, quantity, total_price, email, address, date, variations, size, status') \
            .eq('id', order_id) \
            .eq('seller_email', seller_email) \
            .execute()

        if not order_res.data:
            flash('Order not found or you are not authorized to update this order.', 'error')
            return redirect(url_for('orders_list'))

        order = order_res.data[0]
        current_status = order['status']
        customer_email = order['email']

        print(f"?? Order: {order['name']} for {customer_email}")
        print(f"?? Status: {current_status} ? {new_status}")

        # Build update payload
        from datetime import datetime as _dt, timedelta as _td
        update_payload = {'status': new_status}
        if new_status == 'Delivered':
            update_payload['delivered_at']    = _dt.now().isoformat()
            update_payload['auto_complete_at'] = (_dt.now() + _td(days=7)).isoformat()

        sb_admin.table('orders').update(update_payload).eq('id', order_id).execute()
        print(f"? Supabase order {order_id} ? {new_status}")

    except Exception as sb_err:
        print(f"? Supabase update_order_status failed: {sb_err}")
        flash('An error occurred while updating the order status.', 'error')
        return redirect(url_for('orders_list'))

    # -- Notifications (best-effort) ----------------------------------------
    if current_status != new_status:
        try:
            send_order_status_update_email(customer_email, order, new_status)
        except Exception as e:
            print(f"?? Email failed: {e}")

        try:
            create_buyer_notification(customer_email, order, new_status, order_id)
        except Exception as e:
            print(f"?? Buyer notification failed: {e}")

        if new_status == 'Waiting for Pickup':
            try:
                notify_riders_of_new_order(order_id, order, seller_email)
            except Exception as e:
                print(f"?? Rider notification failed: {e}")

    # -- Flash message ------------------------------------------------------
    status_messages = {
        'Confirmed':         'Order confirmed! You can now start preparing it.',
        'Preparing':         'Order is now being prepared. Click "Ready for Pickup" when ready.',
        'Waiting for Pickup': 'Order is ready for pickup. Riders have been notified.',
        'Rejected':          'Order has been rejected.',
    }
    flash(status_messages.get(new_status,
          f'Order status updated to {new_status}.'), 'success')

    # -- MIRROR: MySQL (best-effort) ----------------------------------------
    # MySQL mirror removed

    return redirect(url_for('orders_list'))

@app.route('/update_order_received_status', methods=['POST'])
def update_order_received_status():
    data = request.json
    order_id = data.get('order_id')
    status   = data.get('status')
    user_email = session.get('email')
    if status != 'Received':
        return jsonify({'success': False, 'error': 'Invalid status'}), 400
    try:
        ord_res = sb_admin.table('orders').select('id, product_id, quantity, seller_email, name').eq('id', order_id).eq('email', user_email).limit(1).execute()
        if not ord_res.data:
            return jsonify({'success': False, 'error': 'Order not found'}), 404
        order = ord_res.data[0]
        sb_admin.table('orders').update({'status': 'Completed', 'received_at': datetime.now().isoformat()}).eq('id', order_id).execute()
        # Notify seller
        try:
            sb_admin.table('notifications').insert({'seller_email': order['seller_email'], 'message': f"Order #{order_id} ({order['name']}) has been received by the buyer.", 'type': 'order_received', 'is_read': False}).execute()
        except Exception:
            pass
        return jsonify({'success': True, 'message': 'Order marked as received'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/submit_order_issue', methods=['POST'])
def submit_order_issue():
    if 'email' not in session:
        return jsonify({'success': False, 'message': 'Please log in to submit a report'}), 401
    try:
        data = request.json
        order_id              = data.get('order_id')
        reporter_role         = data.get('reporter_role', 'buyer')
        reporter_email        = data.get('reporter_email') or session.get('email')
        reported_against_role = data.get('reported_against_role', 'seller')
        reported_against_email = data.get('reported_against_email', '')
        issue_type            = data.get('issue_type', '')
        issue_description     = data.get('issue_description', '')
        if not all([order_id, issue_type, issue_description]):
            return jsonify({'success': False, 'message': 'Missing required fields'}), 400
        ins = sb_admin.table('order_issues').insert({
            'order_id': order_id, 'reporter_role': reporter_role,
            'reporter_email': reporter_email, 'reported_against_role': reported_against_role,
            'reported_against_email': reported_against_email,
            'issue_type': issue_type, 'issue_description': issue_description, 'status': 'pending',
        }).execute()
        issue_id = ins.data[0]['id'] if ins.data else None
        return jsonify({'success': True, 'message': 'Issue report submitted successfully.', 'issue_id': issue_id}), 200
    except Exception as e:
        return jsonify({'success': False, 'message': 'An error occurred while submitting the report'}), 500


# ===========================================
# ADMIN ROUTES
# ===========================================

@app.route('/admin_dashboard')
def admin_dashboard():
    """Admin dashboard — shows summary stats."""
    if 'user_id' not in session or session.get('user_type') != 'Admin':
        flash('Access denied. Admin privileges required.', 'error')
        return redirect(url_for('login'))
    try:
        users_res    = sb_admin.table('users').select('id', count='exact').execute()
        orders_res   = sb_admin.table('orders').select('id', count='exact').execute()
        products_res = sb_admin.table('products').select('id', count='exact').execute()
        issues_res   = sb_admin.table('order_issues').select('id', count='exact').execute()
        pending_res  = sb_admin.table('pending_users').select('id', count='exact').eq('status', 'pending').execute()
        try:
            pending_sellers_res   = sb_admin.table('pending_sellers').select('id', count='exact').eq('status', 'pending').execute()
            pending_sellers_count = pending_sellers_res.count or 0
        except Exception:
            pending_sellers_count = 0
        total_users          = users_res.count or 0
        total_orders         = orders_res.count or 0
        total_products       = products_res.count or 0
        total_issues         = issues_res.count or 0
        pending_users_count  = pending_res.count or 0
        pending_approvals    = pending_users_count + pending_sellers_count
    except Exception as e:
        print(f"admin_dashboard error: {e}")
        total_users = total_orders = total_products = total_issues = pending_approvals = 0
        pending_users_count = pending_sellers_count = 0
    return render_template('admin_dashboard.html',
                           total_users=total_users,
                           total_orders=total_orders,
                           total_products=total_products,
                           total_issues=total_issues,
                           pending_approvals=pending_approvals)


@app.route('/api/admin/dashboard_charts')
def admin_dashboard_charts():
    """Admin dashboard charts API — returns chart data from Supabase."""
    if 'user_id' not in session or session.get('user_type') != 'Admin':
        return jsonify({'error': 'Unauthorized'}), 401
    try:
        from datetime import datetime as _dt, timezone
        from collections import defaultdict
        import calendar

        # Fetch orders - only columns that actually exist on the orders table
        orders_res = sb_admin.table('orders').select(
            'id, status, total_price, date, product_id, quantity, shipping_fee'
        ).execute()
        all_orders = orders_res.data or []

        # Fetch products for category data - only columns that exist
        try:
            products_res = sb_admin.table('products').select('id, category, sold, quantity').execute()
            all_products = products_res.data or []
        except Exception as pe:
            print(f"[dashboard_charts] products fetch error: {pe}")
            # Retry without 'sold' in case column doesn't exist
            try:
                products_res = sb_admin.table('products').select('id, category, quantity').execute()
                all_products = products_res.data or []
            except Exception:
                all_products = []

        done_statuses = {'delivered', 'completed', 'received'}

        # ── Build last 12 months labels ──────────────────────────────────────
        now = _dt.now(timezone.utc)
        months = []
        for i in range(11, -1, -1):
            total_months = now.year * 12 + now.month - 1 - i
            y = total_months // 12
            m = total_months % 12 + 1
            months.append((y, m))

        month_labels = [calendar.month_abbr[m] + ' ' + str(y)[-2:] for y, m in months]

        # ── Revenue & Commission per month ───────────────────────────────────
        revenue_by_month    = defaultdict(float)
        commission_by_month = defaultdict(float)

        for o in all_orders:
            if (o.get('status') or '').lower().strip() not in done_statuses:
                continue
            raw_date = o.get('date')
            if not raw_date:
                continue
            try:
                dt = _dt.fromisoformat(str(raw_date).replace('Z', '+00:00'))
                key = (dt.year, dt.month)
            except Exception:
                continue
            total  = float(o.get('total_price') or 0)
            fee    = float(o.get('shipping_fee') or 50)
            revenue_by_month[key]    += total
            commission_by_month[key] += round(total * 0.05, 2) + round(fee * 0.05, 2)

        revenue_values    = [round(revenue_by_month.get(k, 0), 2)    for k in months]
        commission_values = [round(commission_by_month.get(k, 0), 2) for k in months]

        # ── Top Selling Categories ────────────────────────────────────────────
        cat_labels = []
        cat_values = []
        try:
            category_sales = defaultdict(int)
            for p in all_products:
                cat  = (p.get('category') or 'Other').strip().upper()
                sold = int(p.get('sold') or 0)
                category_sales[cat] += sold

            # Fallback: count from completed orders via product_id → category
            if sum(category_sales.values()) == 0:
                prod_cat_map = {p['id']: (p.get('category') or 'Other').strip().upper()
                               for p in all_products if p.get('id')}
                for o in all_orders:
                    if (o.get('status') or '').lower().strip() not in done_statuses:
                        continue
                    pid = o.get('product_id')
                    cat = prod_cat_map.get(pid, 'Other') if pid else 'Other'
                    qty = int(o.get('quantity') or 1)
                    category_sales[cat] += qty

            sorted_cats = sorted(
                [(c, v) for c, v in category_sales.items() if v > 0],
                key=lambda x: x[1], reverse=True
            )[:8]
            cat_labels = [c[0] for c in sorted_cats]
            cat_values = [c[1] for c in sorted_cats]
        except Exception as ce:
            print(f"[dashboard_charts] category error: {ce}")

        # ── Order Status Distribution ─────────────────────────────────────────
        status_labels = []
        status_values = []
        try:
            status_count = defaultdict(int)
            status_label_map = {
                'pending':           'Pending',
                'confirmed':         'Confirmed',
                'for pickup':        'For Pickup',
                'heading to seller': 'Heading to Seller',
                'shipped':           'Shipped',
                'delivered':         'Delivered',
                'completed':         'Completed',
                'received':          'Received',
                'cancelled':         'Cancelled',
                'rejected':          'Cancelled',
            }
            for o in all_orders:
                raw_status = (o.get('status') or 'unknown').lower().strip()
                label = status_label_map.get(raw_status, raw_status.title())
                status_count[label] += 1

            sorted_statuses = sorted(
                [(k, v) for k, v in status_count.items() if v > 0],
                key=lambda x: x[1], reverse=True
            )
            status_labels = [s[0] for s in sorted_statuses]
            status_values = [s[1] for s in sorted_statuses]
        except Exception as se:
            print(f"[dashboard_charts] status error: {se}")

        # ── Debug log ─────────────────────────────────────────────────────────
        print(f"[dashboard_charts] orders={len(all_orders)}, products={len(all_products)}")
        print(f"[dashboard_charts] revenue={revenue_values}")
        print(f"[dashboard_charts] cats={cat_labels}")
        print(f"[dashboard_charts] statuses={status_labels}")
        if all_orders:
            sample = list({(o.get('status') or '') for o in all_orders[:10]})
            print(f"[dashboard_charts] sample DB statuses: {sample}")

        return jsonify({
            'revenue': {
                'labels': month_labels,
                'values': revenue_values,
            },
            'commission': {
                'labels': month_labels,
                'values': commission_values,
            },
            'categories': {
                'labels': cat_labels,
                'values': cat_values,
            },
            'orderStatus': {
                'labels': status_labels,
                'values': status_values,
            },
        })

    except Exception as e:
        print(f"admin_dashboard_charts error: {e}")
        import traceback; traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route('/admin_users')
def admin_users():
    """Admin user management page."""
    if 'user_id' not in session or session.get('user_type') != 'Admin':
        flash('Access denied. Admin privileges required.', 'error')
        return redirect(url_for('login'))

    # Show success banner when redirected from an approval/rejection action
    approved_name = request.args.get('approved', '').strip()
    rejected      = request.args.get('rejected', '').strip()
    if approved_name:
        flash(f'✅ {approved_name} has been approved successfully! A notification email has been sent.', 'success')
    elif rejected:
        flash('The application has been rejected and the user has been notified via email.', 'info')

    search      = request.args.get('search', '').strip().lower()
    sort_type   = request.args.get('sort', 'all').strip().lower()
    status_filter = request.args.get('status', '').strip().lower()

    try:
        print(f"[admin_users] Fetching users from Supabase...")
        import time as _time
        import requests as _requests
        raw_users = []

        # Try direct REST API with requests library (different HTTP stack than httpx)
        supabase_url = os.environ.get('SUPABASE_URL', 'https://vydcnhmgqovketjqvpoe.supabase.co')
        service_key  = os.environ.get('SUPABASE_SERVICE_ROLE_KEY',
            'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InZ5ZGNuaG1ncW92a2V0anF2cG9lIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc3NjIyNzgwMywiZXhwIjoyMDkxODAzODAzfQ.N7gBt1F2bLulJkD2Uh1nXaTvLkV2fiEAFvnN3qVLYAY')

        for attempt in range(5):
            try:
                resp = _requests.get(
                    f"{supabase_url}/rest/v1/users",
                    headers={
                        'apikey': service_key,
                        'Authorization': f'Bearer {service_key}',
                        'Content-Type': 'application/json',
                    },
                    params={'select': '*', 'order': 'id'},
                    timeout=15
                )
                resp.raise_for_status()
                raw_users = resp.json() or []
                print(f"[admin_users] Got {len(raw_users)} users via REST (attempt {attempt+1})")
                break
            except Exception as retry_err:
                print(f"[admin_users] REST attempt {attempt+1} failed: {retry_err}")
                if attempt < 4:
                    _time.sleep(3)
                else:
                    # Last resort: try sb_admin
                    try:
                        users_res = sb_admin.table('users').select('*').order('id').execute()
                        raw_users = users_res.data or []
                    except Exception as sb_err:
                        print(f"[admin_users] sb_admin also failed: {sb_err}")
                        raw_users = []

        # Normalize Supabase field names to match what the template expects
        users = []
        for u in raw_users:
            # Build address from parts
            addr = u.get('address') or ', '.join(filter(None, [
                u.get('house_street',''), u.get('barangay',''),
                u.get('city',''), u.get('province',''),
                u.get('region',''), u.get('zip_code',''),
            ]))
            normalized = {
                'id':           u.get('id'),
                'first_name':   u.get('first_name', ''),
                'last_name':    u.get('last_name', ''),
                'email':        u.get('email', ''),
                'phone_number': u.get('phone') or u.get('phone_number', ''),
                'address':      addr,
                'user_type':    (u.get('role') or u.get('user_type') or 'buyer').capitalize(),
                'status':       u.get('status', 'active'),
                'created_at':   u.get('created_at'),
                'profile_picture': u.get('profile_picture'),
                'business_name': u.get('business_name', ''),
            }
            users.append(normalized)

        # Apply filters
        if search:
            users = [u for u in users if
                search in (u['first_name'] + ' ' + u['last_name']).lower() or
                search in u['email'].lower() or
                search in (u['phone_number'] or '').lower() or
                search in (u['address'] or '').lower()]
        if sort_type and sort_type != 'all':
            users = [u for u in users if u['user_type'].lower() == sort_type]
        if status_filter:
            users = [u for u in users if (u.get('status') or 'active').lower() == status_filter]

        # Compute counts
        total_users   = len(users)
        buyer_count   = sum(1 for u in users if u['user_type'].lower() == 'buyer')
        seller_count  = sum(1 for u in users if u['user_type'].lower() == 'seller')
        rider_count   = sum(1 for u in users if u['user_type'].lower() == 'rider')

        print(f"[admin_users] Returning {total_users} users to template")

    except Exception as e:
        print(f"[admin_users] ERROR: {e}")
        import traceback; traceback.print_exc()
        users = []
        total_users = buyer_count = seller_count = rider_count = 0

    return render_template('admin_users.html', users=users,
                           total_users=total_users,
                           buyer_count=buyer_count,
                           seller_count=seller_count,
                           rider_count=rider_count)


@app.route('/order_monitoring')
def order_monitoring():
    """Admin: order monitoring page."""
    if 'user_id' not in session or session.get('user_type') != 'Admin':
        flash('Access denied. Admin privileges required.', 'error')
        return redirect(url_for('login'))

    from datetime import datetime as _dt

    def _parse_dt(val):
        """Parse an ISO datetime string into a datetime object, or return None."""
        if not val:
            return None
        if isinstance(val, _dt):
            return val
        for fmt in ('%Y-%m-%dT%H:%M:%S.%f%z', '%Y-%m-%dT%H:%M:%S%z',
                    '%Y-%m-%dT%H:%M:%S.%f', '%Y-%m-%dT%H:%M:%S',
                    '%Y-%m-%d %H:%M:%S', '%Y-%m-%d'):
            try:
                return _dt.strptime(str(val)[:26], fmt)
            except ValueError:
                continue
        return None

    search     = request.args.get('search', '').strip()
    status_f   = request.args.get('status', '').strip()
    date_from  = request.args.get('date_from', '').strip()
    date_to    = request.args.get('date_to', '').strip()
    try:
        page = max(1, int(request.args.get('page', 1)))
    except (ValueError, TypeError):
        page = 1
    per_page = 20

    try:
        q = sb_admin.table('orders').select('*').order('date', desc=True)
        if status_f:
            if status_f in ('cancelled', 'rejected'):
                q = q.in_('status', ['cancelled', 'rejected'])
            else:
                q = q.eq('status', status_f)
        if date_from:
            q = q.gte('date', date_from)
        if date_to:
            q = q.lte('date', date_to + 'T23:59:59')
        res = q.execute()
        all_orders = res.data or []

        # Enrich with buyer/seller/rider names
        emails = set()
        for o in all_orders:
            for f in ('email', 'seller_email', 'rider_email'):
                if o.get(f):
                    emails.add(o[f])
        user_map = {}
        phone_map = {}
        if emails:
            ur = sb_admin.table('users').select(
                'email, first_name, last_name, business_name, phone'
            ).in_('email', list(emails)).execute()
            for u in (ur.data or []):
                fn  = (u.get('first_name') or '').strip()
                ln  = (u.get('last_name') or '').strip()
                biz = (u.get('business_name') or '').strip()
                user_map[u['email']]  = biz or f'{fn} {ln}'.strip() or u['email']
                phone_map[u['email']] = u.get('phone') or 'N/A'

        for o in all_orders:
            o['buyer_name']    = user_map.get(o.get('email', ''), o.get('email', ''))
            o['seller_name']   = user_map.get(o.get('seller_email', ''), o.get('seller_email', ''))
            o['rider_name']    = user_map.get(o.get('rider_email', ''), None) if o.get('rider_email') else None
            o['total_amount']  = float(o.get('total_price') or 0)
            o['order_date']    = _parse_dt(o.get('date'))
            o['order_status']  = o.get('status', '')
            o['order_id']      = o['id']
            o['payment_method'] = o.get('payment_method', '')
            o['delivered_at']  = _parse_dt(o.get('delivered_at'))
            o['received_at']   = _parse_dt(o.get('received_at'))
            o['auto_complete_at'] = _parse_dt(o.get('auto_complete_at'))
            o['is_auto_completed'] = bool(o.get('is_auto_completed'))

        # Apply search after enrichment so buyer/seller names are searchable
        if search:
            sl = search.lower()
            all_orders = [o for o in all_orders if
                          sl in str(o.get('id', '')).lower() or
                          sl in o['buyer_name'].lower() or
                          sl in o['seller_name'].lower() or
                          sl in str(o.get('email', '')).lower() or
                          sl in str(o.get('seller_email', '')).lower()]

        stats = {
            'total_orders':     len(all_orders),
            'pending_orders':   sum(1 for o in all_orders if (o.get('status') or '').lower() == 'pending'),
            'shipped_orders':   sum(1 for o in all_orders if (o.get('status') or '').lower() in ('shipped', 'for pickup', 'heading to seller')),
            'delivered_orders': sum(1 for o in all_orders if (o.get('status') or '').lower() == 'delivered'),
            'completed_orders': sum(1 for o in all_orders if (o.get('status') or '').lower() == 'completed'),
            'cancelled_orders': sum(1 for o in all_orders if (o.get('status') or '').lower() in ('cancelled', 'rejected')),
        }

        total_orders = len(all_orders)
        total_pages  = max(1, (total_orders + per_page - 1) // per_page)
        page         = min(page, total_pages)
        orders       = all_orders[(page - 1) * per_page: page * per_page]
        prev_page    = page - 1 if page > 1 else None
        next_page    = page + 1 if page < total_pages else None

    except Exception as e:
        print(f"order_monitoring error: {e}")
        orders = []
        stats  = {k: 0 for k in ['total_orders', 'pending_orders', 'shipped_orders',
                                   'delivered_orders', 'completed_orders', 'cancelled_orders']}
        total_pages = 1
        prev_page   = None
        next_page   = None

    return render_template('order_monitoring.html', orders=orders, riders=[], stats=stats,
                           current_page=page, total_pages=total_pages,
                           total_orders=total_orders,
                           prev_page=prev_page, next_page=next_page)


@app.route('/product_management')
def product_management():
    """Admin: product management page."""
    if 'user_id' not in session or session.get('user_type') != 'Admin':
        flash('Access denied. Admin privileges required.', 'error')
        return redirect(url_for('login'))
    search   = request.args.get('search', '').strip()
    category = request.args.get('category', '').strip()
    seller   = request.args.get('seller', '').strip()
    status   = request.args.get('status', '').strip()
    try:
        page = max(1, int(request.args.get('page', 1)))
    except (ValueError, TypeError):
        page = 1
    per_page = 20

    try:
        q = sb_admin.table('products').select('*').order('id', desc=True)
        if search:
            q = q.ilike('name', f'%{search}%')
        if category:
            q = q.eq('category', category)
        if seller:
            q = q.ilike('seller_email', f'%{seller}%')
        if status == 'active':
            q = q.eq('is_active', True)
        elif status == 'inactive':
            q = q.eq('is_active', False)
        res = q.execute()
        all_products = res.data or []

        # Enrich products
        seller_emails = list({p.get('seller_email') for p in all_products if p.get('seller_email')})
        seller_name_map = {}
        if seller_emails:
            sr = sb_admin.table('users').select('email, first_name, last_name, business_name').in_('email', seller_emails).execute()
            for u in (sr.data or []):
                fn  = (u.get('first_name') or '').strip()
                ln  = (u.get('last_name') or '').strip()
                biz = (u.get('business_name') or '').strip()
                seller_name_map[u['email']] = biz or f'{fn} {ln}'.strip() or u['email']

        from datetime import datetime as _dt
        def _parse_dt(val):
            if not val:
                return None
            if isinstance(val, _dt):
                return val
            for fmt in ('%Y-%m-%dT%H:%M:%S.%f%z', '%Y-%m-%dT%H:%M:%S%z',
                        '%Y-%m-%dT%H:%M:%S.%f', '%Y-%m-%dT%H:%M:%S',
                        '%Y-%m-%d %H:%M:%S', '%Y-%m-%d'):
                try:
                    return _dt.strptime(str(val)[:26], fmt)
                except ValueError:
                    continue
            return None

        for p in all_products:
            p['price']          = float(p.get('price') or 0)
            p['stock_quantity'] = int(p.get('quantity') or 0)
            p['quantity']       = p['stock_quantity']
            p['seller_name']    = seller_name_map.get(p.get('seller_email', ''), p.get('seller_email', ''))
            p['seller_email']   = p.get('seller_email', '')
            p['is_active']      = bool(p.get('is_active', True))
            p['flagged_at']     = _parse_dt(p.get('flagged_at'))
            p['created_at']     = _parse_dt(p.get('created_at'))
            p['updated_at']     = _parse_dt(p.get('updated_at'))

        # Apply stock-based status filters after enrichment
        if status == 'out_of_stock':
            all_products = [p for p in all_products if p['stock_quantity'] <= 0]
        elif status == 'low_stock':
            all_products = [p for p in all_products if 0 < p['stock_quantity'] <= int(p.get('low_stock_threshold') or 5)]
        elif status == 'flagged':
            all_products = [p for p in all_products if p.get('flagged_at')]

        # Stats
        total_products    = len(all_products)
        low_stock_count   = sum(1 for p in all_products if 0 < p['stock_quantity'] <= int(p.get('low_stock_threshold') or 5))
        out_of_stock_count = sum(1 for p in all_products if p['stock_quantity'] <= 0)

        # Categories and sellers for filter dropdowns
        categories = sorted({p.get('category') for p in all_products if p.get('category')})
        sellers_set = {}
        for p in all_products:
            e = p.get('seller_email', '')
            if e and e not in sellers_set:
                sellers_set[e] = p.get('seller_name', e)
        sellers = [{'email': e, 'seller_name': n} for e, n in sellers_set.items()]

        # Pagination
        total_pages = max(1, (total_products + per_page - 1) // per_page)
        page        = min(page, total_pages)
        products    = all_products[(page - 1) * per_page: page * per_page]

    except Exception as e:
        print(f"product_management error: {e}")
        products = []
        total_products = low_stock_count = out_of_stock_count = 0
        categories = []
        sellers    = []
        total_pages = 1

    return render_template('product_management.html', products=products,
                           search=search, category=category, seller=seller, status=status,
                           page=page, total_pages=total_pages,
                           total_products=total_products,
                           low_stock_count=low_stock_count,
                           out_of_stock_count=out_of_stock_count,
                           categories=categories, sellers=sellers)


@app.route('/admin_issue_reports')
def admin_issue_reports():
    """Admin: issue reports page."""
    if 'user_id' not in session or session.get('user_type') != 'Admin':
        flash('Access denied. Admin privileges required.', 'error')
        return redirect(url_for('login'))

    search_query         = request.args.get('search', '').strip()
    status_filter        = request.args.get('status', '').strip()
    reporter_role_filter = request.args.get('reporter_role', '').strip()
    report_against_filter = request.args.get('report_against', '').strip()
    try:
        page = max(1, int(request.args.get('page', 1)))
    except (ValueError, TypeError):
        page = 1
    per_page = 20

    from datetime import datetime as _dt
    def _parse_dt(val):
        if not val:
            return None
        if isinstance(val, _dt):
            return val
        for fmt in ('%Y-%m-%dT%H:%M:%S.%f%z', '%Y-%m-%dT%H:%M:%S%z',
                    '%Y-%m-%dT%H:%M:%S.%f', '%Y-%m-%dT%H:%M:%S',
                    '%Y-%m-%d %H:%M:%S', '%Y-%m-%d'):
            try:
                return _dt.strptime(str(val)[:26], fmt)
            except ValueError:
                continue
        return None

    try:
        q = sb_admin.table('order_issues').select('*').order('created_at', desc=True)
        if status_filter:
            q = q.eq('status', status_filter)
        if reporter_role_filter:
            q = q.eq('reporter_role', reporter_role_filter)
        if report_against_filter:
            q = q.eq('reported_against_role', report_against_filter)
        res = q.execute()
        all_issues = res.data or []

        if search_query:
            sl = search_query.lower()
            all_issues = [i for i in all_issues if
                          sl in str(i.get('reporter_email', '')).lower() or
                          sl in str(i.get('issue_description', '')).lower() or
                          sl in str(i.get('order_id', '')).lower()]

        for i in all_issues:
            i['created_at'] = _parse_dt(i.get('created_at'))

        stats = {
            'total_issues':       len(all_issues),
            'pending_issues':     sum(1 for i in all_issues if (i.get('status') or '') == 'pending'),
            'in_progress_issues': sum(1 for i in all_issues if (i.get('status') or '') == 'in_progress'),
            'resolved_issues':    sum(1 for i in all_issues if (i.get('status') or '') in ('resolved', 'closed')),
        }

        total_issues = len(all_issues)
        total_pages  = max(1, (total_issues + per_page - 1) // per_page)
        page         = min(page, total_pages)
        issues       = all_issues[(page - 1) * per_page: page * per_page]

    except Exception as e:
        print(f"admin_issue_reports error: {e}")
        issues = []
        stats  = {'total_issues': 0, 'pending_issues': 0, 'in_progress_issues': 0, 'resolved_issues': 0}
        total_issues = 0
        total_pages  = 1

    return render_template('admin_issue_reports.html', issues=issues,
                           stats=stats,
                           search_query=search_query,
                           status_filter=status_filter,
                           reporter_role_filter=reporter_role_filter,
                           report_against_filter=report_against_filter,
                           current_page=page,
                           total_pages=total_pages,
                           total_issues=total_issues)


@app.route('/admin_reports_analytics')
def admin_reports_analytics():
    """Admin: reports and analytics page."""
    if 'user_id' not in session or session.get('user_type') != 'Admin':
        flash('Access denied. Admin privileges required.', 'error')
        return redirect(url_for('login'))
    try:
        orders_res = sb_admin.table('orders').select('id, total_price, status, date, seller_email').execute()
        all_orders = orders_res.data or []
        done = [o for o in all_orders if (o.get('status') or '').lower() in ('completed', 'delivered')]
        total_revenue = sum(float(o.get('total_price') or 0) for o in done)
        total_orders  = len(all_orders)
        users_res = sb_admin.table('users').select('id', count='exact').execute()
        total_users = users_res.count or 0
        products_res = sb_admin.table('products').select('id', count='exact').execute()
        total_products = products_res.count or 0
    except Exception as e:
        print(f"admin_reports_analytics error: {e}")
        total_revenue = total_orders = total_users = total_products = 0
    return render_template('admin_reports_analytics.html',
                           total_revenue=f"{total_revenue:.2f}",
                           total_orders=total_orders,
                           total_users=total_users,
                           total_products=total_products)


@app.route('/archive_accounts')
def archive_accounts():
    """Admin: archived accounts page."""
    if 'user_id' not in session or session.get('user_type') != 'Admin':
        flash('Access denied. Admin privileges required.', 'error')
        return redirect(url_for('login'))

    from datetime import datetime as _dt
    def _parse_dt(val):
        if not val:
            return None
        if isinstance(val, _dt):
            return val
        for fmt in ('%Y-%m-%dT%H:%M:%S.%f%z', '%Y-%m-%dT%H:%M:%S%z',
                    '%Y-%m-%dT%H:%M:%S.%f', '%Y-%m-%dT%H:%M:%S',
                    '%Y-%m-%d %H:%M:%S', '%Y-%m-%d'):
            try:
                return _dt.strptime(str(val)[:26], fmt)
            except ValueError:
                continue
        return None

    try:
        res = sb_admin.table('archived_users').select('*').order('archived_at', desc=True).execute()
        archived = res.data or []
        for u in archived:
            u['archived_at_dt'] = _parse_dt(u.get('archived_at'))
    except Exception as e:
        print(f"archive_accounts error: {e}")
        archived = []
    return render_template('archive.html', users=archived)


@app.route('/pending_users')
def pending_users():
    if 'user_id' not in session or session.get('user_type') != 'Admin':
        flash('Access denied. Admin privileges required.', 'error')
        return redirect(url_for('login'))
    
    pending_users_list = []
    # Fetch from Supabase pending_users table
    try:
        supabase_pending_res = sb_admin.table('pending_users').select('*').eq('status', 'pending').order('created_at', desc=True).execute()
        supabase_pending = supabase_pending_res.data or []

        # Fetch all pending_rider_vehicles in one call to avoid N+1 queries
        try:
            rv_res = sb_admin.table('pending_rider_vehicles').select('supabase_uid,vehicle_type,vehicle_model,plate_number,year_model,or_cr_path,nbi_clearance_path').execute()
            rider_vehicles_map = {rv['supabase_uid']: rv for rv in (rv_res.data or [])}
        except Exception:
            rider_vehicles_map = {}

        # Get emails already in MySQL pending list to avoid duplicates
        mysql_emails = {u['email'] for u in pending_users_list}

        for u in supabase_pending:
            if u.get('email') not in mysql_emails:
                # Normalize to match MySQL pending_users structure
                from dateutil import parser as dtparser
                created_raw = u.get('created_at')
                try:
                    created_dt = dtparser.parse(created_raw) if created_raw else None
                except Exception:
                    created_dt = None

                addr_parts = [
                    u.get('house_street') or '',
                    u.get('barangay') or '',
                    u.get('city') or '',
                    u.get('province') or '',
                    u.get('region') or '',
                    u.get('zip_code') or '',
                ]
                address = ', '.join(p for p in addr_parts if p)

                # Attach vehicle info for riders
                rv = rider_vehicles_map.get(u.get('supabase_uid')) or {}

                pending_users_list.append({
                    'id':                    f"sb_{u.get('id')}",  # prefix to distinguish from MySQL IDs
                    'email':                 u.get('email'),
                    'first_name':            u.get('first_name'),
                    'last_name':             u.get('last_name'),
                    'phone_number':          u.get('phone') or '',
                    'address':               address,
                    'user_type':             (u.get('role') or 'buyer').capitalize(),
                    'status':                u.get('status', 'pending'),
                    'created_at':            created_dt,
                    'valid_id_path':         u.get('valid_id_path'),
                    'supabase_uid':          u.get('supabase_uid'),
                    'vehicle_type':          rv.get('vehicle_type'),
                    'vehicle_model':         rv.get('vehicle_model'),
                    'vehicle_plate_number':  rv.get('plate_number'),
                    'vehicle_year_model':    rv.get('year_model'),
                    'or_cr_path':            rv.get('or_cr_path'),
                    'nbi_clearance_path':    rv.get('nbi_clearance_path'),
                    'source':                'mobile',  # flag to identify mobile/web-via-supabase registrations
                })
    except Exception as e:
        print(f"?? Supabase pending_users fetch error: {e}")

    return render_template('pending_users.html', pending_users=pending_users_list)

@app.route('/approve_user/<string:user_id>', methods=['GET', 'POST'])
def approve_user(user_id):
    if 'user_id' not in session or session.get('user_type') != 'Admin':
        flash('Access denied.', 'error')
        return redirect(url_for('login'))
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.is_json
    # Supabase-sourced (sb_ prefix)
    if str(user_id).startswith('sb_'):
        supabase_record_id = user_id[3:]
        try:
            res = sb_admin.table('pending_users').select('*').eq('id', supabase_record_id).execute()
            if not res.data:
                msg = 'User not found in pending list'
                return jsonify({'success': False, 'error': msg}) if is_ajax else (flash(msg,'error'), redirect(url_for('pending_users')))[1]
            u = res.data[0]
            uid = u.get('supabase_uid')
            addr = ', '.join(filter(None,[u.get('house_street',''),u.get('barangay',''),u.get('city',''),u.get('province',''),u.get('region',''),u.get('zip_code','')]))
            sb_admin.table('users').upsert({'id':uid,'email':u['email'],'first_name':u.get('first_name'),'last_name':u.get('last_name'),'phone':u.get('phone',''),'role':(u.get('role') or 'buyer').lower(),'house_street':u.get('house_street',''),'barangay':u.get('barangay',''),'city':u.get('city',''),'province':u.get('province',''),'region':u.get('region',''),'zip_code':u.get('zip_code',''),'valid_id_path':u.get('valid_id_path'),'status':'active'}).execute()
            if uid:
                # Unban the Supabase Auth account so the user can log in — retry up to 3 times
                unban_ok = False
                for attempt in range(3):
                    try:
                        sb_admin.auth.admin.update_user_by_id(uid, {'ban_duration': 'none'})
                        unban_ok = True
                        print(f"approve_user: auth unban OK for uid={uid} (attempt {attempt+1})")
                        break
                    except Exception as ue:
                        print(f"approve_user: unban attempt {attempt+1} failed: {ue}")
                if not unban_ok:
                    print(f"approve_user: WARNING — could not unban uid={uid} after 3 attempts")
            sb_admin.table('pending_users').delete().eq('id', supabase_record_id).execute()
            try: send_approval_email(u['email'], u.get('first_name',''))
            except Exception: pass
            msg = f"{u.get('first_name','')} {u.get('last_name','')} approved successfully"
            return jsonify({'success': True, 'message': msg, 'unban_ok': unban_ok}) if is_ajax else (flash(msg,'success'), redirect(url_for('pending_users')))[1]
        except Exception as e:
            import traceback; traceback.print_exc()
            return jsonify({'success': False, 'error': str(e)}) if is_ajax else (flash(str(e),'error'), redirect(url_for('pending_users')))[1]
    flash('Invalid user ID format', 'error')
    return redirect(url_for('pending_users'))


@app.route('/api/seller_contributions')
def seller_contributions():
    sort_order  = request.args.get('sort', 'desc')
    search_query = request.args.get('search', '').lower()
    try:
        res = sb_admin.table('orders').select('seller_email, total_price').eq('status', 'Completed').execute()
        from collections import defaultdict
        totals = defaultdict(float)
        for o in (res.data or []):
            totals[o['seller_email']] += float(o.get('total_price') or 0) * 0.05
        sellers = [{'seller_email': k, 'total_contribution': v} for k, v in totals.items()]
        if search_query:
            sellers = [s for s in sellers if search_query in s['seller_email'].lower()]
        sellers.sort(key=lambda x: x['total_contribution'], reverse=(sort_order == 'desc'))
        return jsonify(sellers)
    except Exception as e:
        return jsonify([])
    except Exception as e:
        return jsonify([])

@app.route('/api/user_counts')
def user_counts():
    try:
        res = sb_admin.table('users').select('role').execute()
        from collections import Counter
        counts = Counter(u.get('role', 'buyer') for u in (res.data or []))
        data = [{'user_type': k, 'count': v} for k, v in counts.items()]
        return jsonify(data)
    except Exception as e:
        return jsonify([])

    cursor.execute("SELECT user_type, COUNT(*) as count FROM users GROUP BY user_type")
    data = cursor.fetchall()

    cursor.close()
    connection.close()

    return jsonify(data)

@app.route('/pending_sellers', methods=['GET'])
def pending_sellers_dashboard():
    if 'user_id' not in session or session.get('user_type') != 'Admin':
        flash('Access denied.', 'error')
        return redirect(url_for('login'))
    search_email  = request.args.get('search', '')
    status_filter = request.args.get('status', 'all')
    sellers = []
    try:
        q = sb_admin.table('pending_sellers').select('*').order('created_at', desc=True)
        if search_email:
            q = q.ilike('email', f'%{search_email}%')
        if status_filter and status_filter != 'all':
            q = q.eq('status', status_filter)
        res = q.execute()
        sellers = res.data or []
    except Exception as e:
        print(f"pending_sellers_dashboard error: {e}")
    return render_template('pending_sellers.html', sellers=sellers)


@app.route('/reject_seller/<string:seller_id>', methods=['POST'])
def reject_seller(seller_id):
    if 'user_id' not in session or session.get('user_type') != 'Admin':
        return jsonify({'success': False, 'error': 'Access denied'}), 403
    try:
        data = request.get_json() or {}
        rejection_reason = data.get('rejection_reason', 'Application rejected by admin')
        record_id = seller_id[3:] if str(seller_id).startswith('sb_') else seller_id
        res = sb_admin.table('pending_sellers').select('email, first_name, business_name, supabase_uid').eq('id', str(record_id)).limit(1).execute()
        if not res.data:
            return jsonify({'success': False, 'error': 'Seller not found'})
        seller = res.data[0]
        sb_admin.table('pending_sellers').update({'status': 'rejected'}).eq('id', str(record_id)).execute()
        try: send_seller_rejection_email(seller['email'], seller.get('first_name',''), seller.get('business_name',''), rejection_reason)
        except Exception: pass
        return jsonify({'success': True, 'message': f"{seller.get('first_name','')} rejected"})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@app.route('/api/seller_documents/<string:seller_id>')
def get_seller_documents(seller_id):
    BUCKET = 'user-documents'
    SUPABASE_STORAGE_BASE = f"{SUPABASE_URL}/storage/v1/object/public/{BUCKET}"

    def signed_url(storage_path):
        if not storage_path:
            return None
        # Already a full URL — return as-is
        if storage_path.startswith('http://') or storage_path.startswith('https://'):
            return storage_path
        # Build public URL directly (bucket is public, no signing needed)
        clean = storage_path.lstrip('/')
        public = f"{SUPABASE_URL}/storage/v1/object/public/{BUCKET}/{clean}"
        # Try signed URL first (works for private buckets too)
        try:
            result = sb_admin.storage.from_(BUCKET).create_signed_url(storage_path, 3600)
            if isinstance(result, dict):
                url = result.get('signedURL') or result.get('signedUrl') or result.get('signed_url')
            else:
                url = getattr(result, 'signed_url', None) or getattr(result, 'signedURL', None)
            if url:
                return url
        except Exception as e:
            print(f'seller signed_url error for {storage_path}: {e}')
        return public

    # -- Supabase-registered seller (sb_ prefix) --------------------------
    if str(seller_id).startswith('sb_'):
        supabase_id = seller_id[3:]  # strip 'sb_' prefix
        try:
            res = sb_admin.table('pending_sellers').select('*').eq('id', supabase_id).execute()
            if not res.data:
                return jsonify({'success': False, 'error': 'Seller not found'})
            s = res.data[0]

            def resolve_seller_doc_url_sb(stored_path, subfolder):
                if not stored_path:
                    return None, []
                normalised = stored_path.replace('\\', '/')
                # Already a full URL — return directly
                if normalised.startswith('http://') or normalised.startswith('https://'):
                    return normalised, [normalised]
                is_local = (
                    'static/images/uploads' in normalised
                    or 'static/uploads' in normalised
                    or (len(normalised) > 1 and normalised[1] == ':')
                    or (normalised.startswith('/') and 'supabase' not in normalised)
                )
                if is_local:
                    fn = os.path.basename(normalised)
                    variations = [
                        f"/static/images/uploads/{subfolder}/{fn}",
                        f"/static/uploads/{subfolder}/{fn}",
                        f"/uploads/{subfolder}/{fn}",
                    ]
                    return variations[0], variations
                # Storage path — build both signed URL and public URL
                su = signed_url(stored_path)
                clean = stored_path.lstrip('/')
                pub = f"{SUPABASE_URL}/storage/v1/object/public/{BUCKET}/{clean}"
                variations = list(dict.fromkeys(filter(None, [su, pub])))
                return variations[0] if variations else None, variations

            valid_id_url,  valid_id_vars  = resolve_seller_doc_url_sb(s.get('valid_id_path'),          'seller_docs')
            dti_url,       dti_vars       = resolve_seller_doc_url_sb(s.get('dti_path'),               'seller_docs')
            bir_url,       bir_vars       = resolve_seller_doc_url_sb(s.get('bir_path'),               'seller_docs')
            bp_url,        bp_vars        = resolve_seller_doc_url_sb(s.get('business_permit_path'),   'seller_docs')

            return jsonify({
                'success': True,
                'seller_info': {
                    'first_name':    s.get('first_name', ''),
                    'last_name':     s.get('last_name', ''),
                    'business_name': s.get('business_name', ''),
                    'business_type': s.get('business_type', ''),
                },
                'documents': {
                    'valid_id_url':             valid_id_url,
                    'dti_url':                  dti_url,
                    'bir_url':                  bir_url,
                    'business_permit_url':       bp_url,
                    'valid_id_path':             s.get('valid_id_path'),
                    'valid_id_variations':       valid_id_vars,
                    'dti_path':                  s.get('dti_path'),
                    'dti_variations':            dti_vars,
                    'bir_path':                  s.get('bir_path'),
                    'bir_variations':            bir_vars,
                    'business_permit_path':      s.get('business_permit_path'),
                    'business_permit_variations': bp_vars,
                }
            })
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)})

    # -- MySQL-registered seller (numeric ID) -----------------------------
    try:
        numeric_id = int(seller_id)
    except ValueError:
        return jsonify({'success': False, 'error': 'Invalid seller ID'})

    try:
        # Supabase lookup

        if result:
            def resolve_seller_doc_url(stored_path, subfolder):
                if not stored_path:
                    return None, []
                normalised = stored_path.replace('\\', '/')
                is_local = (
                    'static/images/uploads' in normalised
                    or 'static/uploads' in normalised
                    or (len(normalised) > 1 and normalised[1] == ':')
                    or (normalised.startswith('/') and 'supabase' not in normalised)
                )
                if is_local:
                    fn = os.path.basename(normalised)
                    variations = [
                        f"/static/images/uploads/{subfolder}/{fn}",
                        f"/static/uploads/{subfolder}/{fn}",
                        f"/uploads/{subfolder}/{fn}",
                    ]
                    return variations[0], variations
                url = signed_url(stored_path)
                return url, [url] if url else []

            valid_id_url,  valid_id_vars  = resolve_seller_doc_url(result['valid_id_path'],          'seller_docs')
            dti_url,       dti_vars       = resolve_seller_doc_url(result['dti_path'],               'seller_docs')
            bir_url,       bir_vars       = resolve_seller_doc_url(result['bir_path'],               'seller_docs')
            bp_url,        bp_vars        = resolve_seller_doc_url(result['business_permit_path'],   'seller_docs')

            return jsonify({
                'success': True,
                'seller_info': {
                    'first_name':    result['first_name'],
                    'last_name':     result['last_name'],
                    'business_name': result['business_name'],
                    'business_type': result['business_type']
                },
                'documents': {
                    'valid_id_url':             valid_id_url,
                    'dti_url':                  dti_url,
                    'bir_url':                  bir_url,
                    'business_permit_url':       bp_url,
                    'valid_id_path':             result['valid_id_path'],
                    'valid_id_variations':       valid_id_vars,
                    'dti_path':                  result['dti_path'],
                    'dti_variations':            dti_vars,
                    'bir_path':                  result['bir_path'],
                    'bir_variations':            bir_vars,
                    'business_permit_path':      result['business_permit_path'],
                    'business_permit_variations': bp_vars,
                }
            })
        else:
            return jsonify({'success': False, 'error': 'Seller not found'})

    except Exception as err:
        return jsonify({'success': False, 'error': f'Database error: {str(err)}'})

@app.route('/api/user_documents/<string:user_id>')
def get_user_documents(user_id):
    BUCKET = 'user-documents'
    SUPABASE_STORAGE_BASE = f"{SUPABASE_URL}/storage/v1/object/public/{BUCKET}"
    def signed_url(path):
        if not path: return None
        # Already a full URL — return as-is
        if path.startswith('http://') or path.startswith('https://'):
            return path
        # Build public URL directly (bucket is public)
        clean = path.lstrip('/')
        public = f"{SUPABASE_URL}/storage/v1/object/public/{BUCKET}/{clean}"
        try:
            result = sb_admin.storage.from_(BUCKET).create_signed_url(path, 3600)
            if isinstance(result, dict):
                url = result.get('signedURL') or result.get('signedUrl') or result.get('signed_url')
            else:
                url = getattr(result, 'signed_url', None) or getattr(result, 'signedURL', None)
            if url:
                return url
        except Exception:
            pass
        return public
    try:
        record_id = user_id[3:] if str(user_id).startswith('sb_') else user_id
        res = sb_admin.table('pending_users').select('first_name, last_name, email, phone, house_street, barangay, city, province, region, zip_code, role, valid_id_path, supabase_uid').eq('id', str(record_id)).limit(1).execute()
        if not res.data:
            return jsonify({'success': False, 'error': 'User not found'})
        u = res.data[0]
        uid = u.get('supabase_uid')
        rv = {}
        if uid:
            try:
                rv_res = sb_admin.table('pending_rider_vehicles').select('*').eq('supabase_uid', uid).limit(1).execute()
                rv = rv_res.data[0] if rv_res.data else {}
            except Exception: pass
        valid_id_path = u.get('valid_id_path')
        or_cr_path = rv.get('or_cr_path')
        nbi_path = rv.get('nbi_clearance_path')

        def make_variations(path):
            """Return [signed_url, public_url] so frontend can try both."""
            if not path: return []
            urls = []
            su = signed_url(path)
            if su: urls.append(su)
            # Always include direct public URL as fallback
            if not (path.startswith('http://') or path.startswith('https://')):
                clean = path.lstrip('/')
                pub = f"{SUPABASE_URL}/storage/v1/object/public/{BUCKET}/{clean}"
                if pub not in urls: urls.append(pub)
            return urls

        valid_id_url = signed_url(valid_id_path)
        or_cr_url = signed_url(or_cr_path)
        nbi_clearance_url = signed_url(nbi_path)

        return jsonify({'success': True, 'user': {
            'first_name': u.get('first_name',''), 'last_name': u.get('last_name',''),
            'email': u.get('email',''), 'phone_number': u.get('phone',''),
            'address': ', '.join(filter(None,[u.get('house_street',''),u.get('barangay',''),u.get('city',''),u.get('province',''),u.get('region',''),u.get('zip_code','')])),
            'user_type': u.get('role','buyer'),
            'valid_id_url': valid_id_url,
            'valid_id_path': valid_id_path,
            'path_variations': make_variations(valid_id_path),
            'vehicle_type': rv.get('vehicle_type'), 'vehicle_model': rv.get('vehicle_model'),
            'vehicle_plate_number': rv.get('plate_number'), 'vehicle_year_model': rv.get('year_model'),
            'or_cr_url': or_cr_url,
            'or_cr_path': or_cr_path,
            'or_cr_variations': make_variations(or_cr_path),
            'nbi_clearance_url': nbi_clearance_url,
            'nbi_clearance_path': nbi_path,
            'nbi_variations': make_variations(nbi_path),
        }})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@app.route('/api/approved_user_documents/<string:user_id>')
def get_approved_user_documents(user_id):
    """API endpoint to get documents for approved users (reads from Supabase)"""
    try:
        res = sb_admin.table('users').select('*').eq('id', user_id).execute()
        if not res.data:
            return jsonify({'success': False, 'error': 'User not found'})
        u = res.data[0]

        BUCKET = 'user-documents'
        SUPABASE_STORAGE_BASE = f"{SUPABASE_URL}/storage/v1/object/public/{BUCKET}"
        APP_BASE_URL = os.environ.get('APP_URL', 'https://mstyleecommerce-production.up.railway.app')

        def signed_url(raw_path):
            """Resolve any stored path format to a web-accessible URL.

            Formats seen in the DB:
              1. UUID/filename          → Supabase Storage key  → signed URL
              2. static/images/...     → local relative path   → /static/images/...
              3. /app/static/images/.. → absolute server path  → /static/images/...
              4. https://...           → already a full URL    → return as-is
            """
            if not raw_path:
                return None

            p = str(raw_path).strip().replace('\\', '/')

            # Already a full URL
            if p.startswith('http://') or p.startswith('https://'):
                return p

            # Absolute server path like /app/static/images/...
            # Strip the /app prefix so it becomes a web-relative path
            if p.startswith('/app/'):
                p = p[4:]  # → /static/images/...

            # Web-relative path like /static/... or static/...
            if p.startswith('/static/') or p.startswith('static/'):
                clean = p.lstrip('/')
                return f"{APP_BASE_URL}/{clean}"

            # Supabase Storage key (UUID prefix or plain filename)
            # Try signed URL first, fall back to public URL
            try:
                result = sb_admin.storage.from_(BUCKET).create_signed_url(p, 3600)
                if isinstance(result, dict):
                    url = result.get('signedURL') or result.get('signedUrl') or result.get('signed_url')
                else:
                    url = getattr(result, 'signed_url', None) or getattr(result, 'signedURL', None)
                if url:
                    return url
            except Exception as e:
                print(f'signed_url error for {p}: {e}')

            # Fallback: public URL
            return f"{SUPABASE_STORAGE_BASE}/{p}"

        # Also check rider_vehicles table for OR/CR and NBI paths
        or_cr_path = u.get('or_cr_path')
        nbi_path   = u.get('nbi_clearance_path')
        try:
            rv_res = sb_admin.table('rider_vehicles').select('or_cr_path,nbi_clearance_path').eq('user_id', user_id).execute()
            if rv_res.data:
                rv = rv_res.data[0]
                or_cr_path = or_cr_path or rv.get('or_cr_path')
                nbi_path   = nbi_path   or rv.get('nbi_clearance_path')
        except Exception:
            pass

        valid_id_url = signed_url(u.get('valid_id_path'))
        dti_url = signed_url(u.get('dti_path'))
        bir_url = signed_url(u.get('bir_path'))
        business_permit_url = signed_url(u.get('business_permit_path'))
        or_cr_url = signed_url(or_cr_path)
        nbi_clearance_url = signed_url(nbi_path)
        
        documents = {
            'valid_id_url':            valid_id_url,
            'dti_url':                 dti_url,
            'bir_url':                 bir_url,
            'business_permit_url':     business_permit_url,
            'or_cr_url':               or_cr_url,
            'nbi_clearance_url':       nbi_clearance_url,
            # Keep raw paths for reference
            'valid_id_path':           u.get('valid_id_path'),
            'dti_path':                u.get('dti_path'),
            'bir_path':                u.get('bir_path'),
            'business_permit_path':    u.get('business_permit_path'),
            'or_cr_path':              or_cr_path,
            'nbi_clearance_path':      nbi_path,
            # Variation arrays for fallback
            'valid_id_variations':     [valid_id_url] if valid_id_url else [],
            'dti_variations':          [dti_url] if dti_url else [],
            'bir_variations':          [bir_url] if bir_url else [],
            'business_permit_variations': [business_permit_url] if business_permit_url else [],
            'or_cr_variations':        [or_cr_url] if or_cr_url else [],
            'nbi_variations':          [nbi_clearance_url] if nbi_clearance_url else [],
        }

        return jsonify({
            'success': True,
            'user': {
                'first_name':          u.get('first_name'),
                'last_name':           u.get('last_name'),
                'email':               u.get('email'),
                'phone_number':        u.get('phone_number') or u.get('phone') or '',
                'address':             u.get('address') or ', '.join(
                    p for p in [
                        u.get('house_street') or '',
                        u.get('barangay') or '',
                        u.get('city') or '',
                        u.get('province') or '',
                        u.get('region') or '',
                        u.get('zip_code') or '',
                    ] if p
                ),
                'user_type':           (u.get('role') or 'buyer').capitalize(),
                'business_name':       u.get('business_name'),
                'business_type':       u.get('business_type'),
                'vehicle_type':        u.get('vehicle_type'),
                'vehicle_model':       u.get('vehicle_model'),
                'vehicle_plate_number': u.get('vehicle_plate_number'),
                'vehicle_year_model':  u.get('vehicle_year_model'),
                'is_banned':           (u.get('status') or 'active') in ('banned', 'suspended'),
                'ban_reason':          u.get('ban_reason'),
                'ban_date':            u.get('created_at'),
            },
            'documents': documents
        })

    except Exception as err:
        print(f'Error in get_approved_user_documents: {err}')
        import traceback; traceback.print_exc()
        return jsonify({'success': False, 'error': str(err)})

@app.route('/api/user_details/<string:user_id>')
def get_user_details_api(user_id):
    """API endpoint to get user details for viewing/editing"""
    try:
        res = sb_admin.table('users').select('*').eq('id', user_id).execute()
        if res.data:
            u = res.data[0]
            u['user_type'] = (u.get('role') or 'buyer').capitalize()

            # Normalize phone: mobile app stores as 'phone', not 'phone_number'
            if not u.get('phone_number'):
                u['phone_number'] = u.get('phone') or ''

            # Normalize address: mobile app stores separate fields
            if not u.get('address'):
                addr_parts = [
                    u.get('house_street') or '',
                    u.get('barangay') or '',
                    u.get('city') or '',
                    u.get('province') or '',
                    u.get('region') or '',
                    u.get('zip_code') or '',
                ]
                combined = ', '.join(p for p in addr_parts if p)
                u['address'] = combined if combined else ''

            return jsonify({'success': True, 'user': u})
        return jsonify({'success': False, 'error': 'User not found'})
    except Exception as err:
        return jsonify({'success': False, 'error': str(err)})

@app.route('/api/update_user', methods=['POST'])
def update_user_api():
    """API endpoint to update user details via Supabase"""
    try:
        user_id      = request.form.get('user_id')
        first_name   = request.form.get('first_name')
        last_name    = request.form.get('last_name')
        email        = request.form.get('email')
        phone_number = request.form.get('phone_number')
        address      = request.form.get('address')
        user_type    = request.form.get('user_type')

        if not user_id:
            return jsonify({'success': False, 'error': 'User ID is required'})

        update_data = {}
        if first_name   is not None: update_data['first_name']   = first_name
        if last_name    is not None: update_data['last_name']    = last_name
        if email        is not None: update_data['email']        = email
        if phone_number is not None: update_data['phone']        = phone_number  # actual column is 'phone'
        if address      is not None: update_data['address']      = address
        if user_type    is not None: update_data['role']         = user_type.lower()

        sb_admin.table('users').update(update_data).eq('id', user_id).execute()
        return jsonify({'success': True, 'message': 'User updated successfully'})

    except Exception as err:
        return jsonify({'success': False, 'error': str(err)})

@app.route('/api/get_user_name')
def get_user_name():
    try:
        email = request.args.get('email')
        if not email:
            return jsonify({'success': False, 'error': 'Email is required'})
        res = sb_admin.table('users').select('first_name, last_name, business_name, role').eq('email', email).limit(1).execute()
        if res.data:
            u = res.data[0]
            name = u.get('business_name') if u.get('role') == 'seller' and u.get('business_name') else f"{u.get('first_name','')} {u.get('last_name','')}".strip()
            return jsonify({'success': True, 'name': name, 'user_type': (u.get('role') or 'buyer').capitalize()})
        return jsonify({'success': False, 'error': 'User not found'})
    except Exception as err:
        return jsonify({'success': False, 'error': f'Error: {str(err)}'})

# Routes to serve uploaded files
@app.route('/static/uploads/<path:filename>')
def serve_uploaded_file(filename):
    """Serve uploaded files from the uploads directory"""
    return serve_file_from_uploads(filename)

@app.route('/uploads/<path:filename>')
def serve_uploads_file(filename):
    """Alternative route for uploaded files"""
    return serve_file_from_uploads(filename)

def serve_file_from_uploads(filename):
    """Helper function to serve files from various upload directories"""
    try:
        print(f"Attempting to serve file: {filename}")
        
        # Try different upload directories
        upload_dirs = [
            os.path.join(BASE_DIR, 'static', 'uploads'),
            os.path.join(BASE_DIR, 'static', 'images', 'uploads'),
            'static/uploads',
            'static/images/uploads'
        ]
        
        for upload_dir in upload_dirs:
            # Handle nested paths (like ids/filename.jpg)
            full_path = os.path.join(upload_dir, filename)
            abs_path = os.path.abspath(full_path)
            
            print(f"Checking path: {abs_path}")
            
            if os.path.exists(abs_path) and os.path.isfile(abs_path):
                print(f"? Serving file from: {abs_path}")
                # Get the directory and filename for send_from_directory
                directory = os.path.dirname(abs_path)
                file_name = os.path.basename(abs_path)
                return send_from_directory(directory, file_name)
        
        # If file not found in any directory, return 404
        print(f"? File not found: {filename}")
        print(f"Searched in directories: {upload_dirs}")
        return "File not found", 404
        
    except Exception as e:
        print(f"Error serving file {filename}: {e}")
        return f"Error serving file: {str(e)}", 500

@app.route('/view_documents/<int:seller_id>')
def view_documents(seller_id):
    try:
        res = sb_admin.table('pending_sellers').select('bir_path, dti_path, business_permit_path, valid_id_path').eq('id', str(seller_id)).limit(1).execute()
        if res.data:
            return render_template('view_documents.html', documents=res.data[0])
        flash('Documents not found!', 'error')
        return redirect(url_for('pending_sellers_dashboard'))
    except Exception as err:
        flash(f'Error: {err}', 'error')
        return redirect(url_for('pending_sellers_dashboard'))

@app.route('/approve/<string:seller_id>', methods=['POST'])
def approve_seller(seller_id):
    if 'user_id' not in session or session.get('user_type') != 'Admin':
        return jsonify({'success': False, 'error': 'Access denied'}), 403
    record_id = seller_id[3:] if str(seller_id).startswith('sb_') else str(seller_id)
    try:
        res = sb_admin.table('pending_sellers').select('*').eq('id', record_id).execute()
        if not res.data:
            return jsonify({'success': False, 'error': 'Seller not found in pending list'}), 404
        s = res.data[0]
        uid = s.get('supabase_uid')
        addr_parts = [s.get('house_street',''),s.get('barangay',''),s.get('city',''),s.get('province',''),s.get('region',''),s.get('zip_code','')]
        sb_admin.table('users').upsert({
            'id': uid, 'email': s['email'],
            'first_name': s.get('first_name'), 'last_name': s.get('last_name'),
            'phone': s.get('phone', ''), 'role': 'seller',
            'business_name': s.get('business_name'), 'business_type': s.get('business_type'),
            'house_street': addr_parts[0], 'barangay': addr_parts[1], 'city': addr_parts[2],
            'province': addr_parts[3], 'region': addr_parts[4], 'zip_code': addr_parts[5],
            'valid_id_path': s.get('valid_id_path'), 'dti_path': s.get('dti_path'),
            'bir_path': s.get('bir_path'), 'business_permit_path': s.get('business_permit_path')
        }).execute()
        if uid:
            # Unban the Supabase Auth account so the seller can log in
            unban_ok = False
            for attempt in range(3):
                try:
                    sb_admin.auth.admin.update_user_by_id(uid, {'ban_duration': 'none'})
                    unban_ok = True
                    print(f"approve_seller: auth unban OK for uid={uid} (attempt {attempt+1})")
                    break
                except Exception as ue:
                    print(f"approve_seller: unban attempt {attempt+1} failed: {ue}")
            if not unban_ok:
                print(f"approve_seller: WARNING — could not unban uid={uid} after 3 attempts")
        sb_admin.table('pending_sellers').delete().eq('id', record_id).execute()
        # Send email in background thread so it doesn't block the response
        import threading
        threading.Thread(
            target=send_seller_approval_email,
            args=(s['email'], s.get('first_name', ''),
                  s.get('business_name', f"{s.get('first_name','')} {s.get('last_name','')}".strip())),
            daemon=True
        ).start()
        seller_name = f"{s.get('first_name','')} {s.get('last_name','')}".strip()
        return jsonify({'success': True, 'message': f"{seller_name} successfully approved", 'unban_ok': unban_ok})
    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/test-flash')
def test_flash():
    """Test route to check if flash messages work"""
    if 'user_id' not in session or session.get('user_type') != 'Admin':
        return "Access denied"
    
    flash('? Test success message!', 'success')
    flash('? Test error message!', 'error')
    flash('?? Test warning message!', 'warning')
    return redirect(url_for('pending_sellers_dashboard'))

@app.route('/test-approve-simple')
def test_approve_simple():
    """Test route that just sets a success message"""
    if 'user_id' not in session or session.get('user_type') != 'Admin':
        return "Access denied"
    
    flash('? Test Seller successfully approved!', 'success')
    print("DEBUG: Test success message set")
    return redirect(url_for('pending_sellers_dashboard'))

# @app.route('/simple-approve/<int:seller_id>') removed (debug route)

# @app.route('/test-approve/<int:seller_id>') removed (debug route)

# /debug-approve removed (debug route)

@app.route('/api/admin/analytics')
def admin_analytics_api():
    """Admin analytics API — fully powered by Supabase"""
    if 'user_id' not in session or session.get('user_type') != 'Admin':
        return jsonify({'error': 'Unauthorized'}), 401

    try:
        from datetime import datetime as _dt
        from collections import defaultdict

        # ── 1. Fetch raw data in parallel batches ─────────────────────────────
        orders_res   = sb_admin.table('orders').select('*').execute()
        products_res = sb_admin.table('products').select('*').execute()
        users_res    = sb_admin.table('users').select('id,email,first_name,last_name,business_name,role,phone').execute()
        reviews_res  = sb_admin.table('reviews').select('product_id,rating').execute()
        cart_res     = sb_admin.table('cart').select('email').execute()
        wishlist_res = sb_admin.table('wishlist').select('user_id').execute()

        all_orders   = orders_res.data   or []
        all_products = products_res.data or []
        all_users    = users_res.data    or []
        all_reviews  = reviews_res.data  or []
        all_cart     = cart_res.data     or []
        all_wishlist = wishlist_res.data or []

        # Fetch rider vehicle info from rider_vehicles table (keyed by user_id)
        rider_vehicle_map = {}  # user_id -> {vehicle_type, plate_number}
        try:
            rv_res = sb_admin.table('rider_vehicles').select('user_id,vehicle_type,plate_number').execute()
            for rv in (rv_res.data or []):
                if rv.get('user_id'):
                    rider_vehicle_map[rv['user_id']] = {
                        'vehicle_type': rv.get('vehicle_type') or 'N/A',
                        'plate':        rv.get('plate_number') or 'N/A',
                    }
        except Exception as rv_err:
            print(f"rider_vehicles fetch skipped: {rv_err}")

        #  2. Build lookup maps 
        user_map = {}
        for u in all_users:
            fn  = (u.get('first_name')    or '').strip()
            ln  = (u.get('last_name')     or '').strip()
            biz = (u.get('business_name') or '').strip()
            uid = u.get('id')
            rv  = rider_vehicle_map.get(uid, {})
            user_map[u['email']] = {
                'name':         biz or f'{fn} {ln}'.strip() or u['email'],
                'user_type':    (u.get('role') or '').lower(),
                'vehicle_type': rv.get('vehicle_type', 'N/A'),
                'plate':        rv.get('plate', 'N/A'),
            }

        # Rating map: product_id  [ratings]
        rating_map = defaultdict(list)
        for r in all_reviews:
            if r.get('product_id') and r.get('rating') is not None:
                rating_map[r['product_id']].append(float(r['rating']))

        # Cart count per buyer email
        cart_count = defaultdict(int)
        for c in all_cart:
            if c.get('email'): cart_count[c['email']] += 1

        # Wishlist count per buyer email
        # wishlist table stores user_id (numeric), so build a reverse id->email map
        uid_to_email = {u.get('id'): u.get('email') for u in all_users if u.get('id') and u.get('email')}
        wishlist_count = defaultdict(int)
        for w in all_wishlist:
            uid = w.get('user_id')
            email = uid_to_email.get(uid, '')
            if email:
                wishlist_count[email] += 1

        def _fmt_date(val, fmt='%Y-%m-%d'):
            if not val: return None
            try: return _dt.fromisoformat(str(val).replace('Z','+00:00').replace('+00:00','')).strftime(fmt)
            except: return str(val)[:10]

        done_statuses = {'delivered','completed','received'}
        cancelled_statuses = {'cancelled','rejected'}

        #  3. Key metrics 
        total_orders   = len(all_orders)
        total_users    = len(all_users)
        total_products = len(all_products)

        #  4. Inventory & Products Analytics 
        # Batch seller names for products
        inventory_products = []
        for idx, p in enumerate(sorted(all_products, key=lambda x: int(x.get('sold') or 0), reverse=True), 1):
            pid     = p.get('id')
            ratings = rating_map.get(pid, [])
            avg_rat = round(sum(ratings)/len(ratings), 1) if ratings else float(p.get('rating') or 0)
            inventory_products.append({
                'no':           idx,
                'product_name': p.get('name', 'N/A'),
                'seller_name':  user_map.get(p.get('seller_email',''), {}).get('name', p.get('seller_email','N/A')),
                'category':     p.get('category', 'N/A'),
                'units_sold':   int(p.get('sold') or 0),
                'stock':        int(p.get('quantity') or 0),
                'rating':       avg_rat,
                'is_active':    bool(p.get('is_active', True)),
                'is_flagged':   bool(p.get('flagged_at')),
                'flagged_at':   _fmt_date(p.get('flagged_at'), '%b %d, %Y at %I:%M %p') if p.get('flagged_at') else None,
                'low_stock_threshold': int(p.get('low_stock_threshold') or 5),
            })

        #  5. Seller Performance 
        sellers = [u for u in all_users if (u.get('role') or '').lower() == 'seller']
        seller_orders  = defaultdict(list)
        seller_prods   = defaultdict(list)
        for o in all_orders:
            if o.get('seller_email'): seller_orders[o['seller_email']].append(o)
        for p in all_products:
            if p.get('seller_email'): seller_prods[p['seller_email']].append(p)

        seller_performance = []
        for idx, u in enumerate(sellers, 1):
            email  = u['email']
            orders = seller_orders.get(email, [])
            prods  = seller_prods.get(email, [])
            rev    = sum(float(o.get('total_price') or 0) for o in orders if (o.get('status') or '').lower() in done_statuses)
            seller_performance.append({
                'no':                  idx,
                'seller_name':         user_map.get(email, {}).get('name', email),
                'email':               email,
                'total_products':      len(prods),
                'total_orders':        len(orders),
                'completed_orders':    sum(1 for o in orders if (o.get('status') or '').lower() in done_statuses),
                'cancelled_orders':    sum(1 for o in orders if (o.get('status') or '').lower() in cancelled_statuses),
                'total_revenue':       round(rev, 2),
                'flagged_products':    sum(1 for p in prods if p.get('flagged_at')),
                'deactivated_products':sum(1 for p in prods if not p.get('is_active', True)),
            })
        seller_performance.sort(key=lambda x: x['total_revenue'], reverse=True)

        #  6. Rider Analytics 
        riders = [u for u in all_users if (u.get('role') or '').lower() == 'rider']
        rider_orders = defaultdict(list)
        for o in all_orders:
            if o.get('rider_email'): rider_orders[o['rider_email']].append(o)

        rider_analytics = []
        for idx, u in enumerate(riders, 1):
            email  = u['email']
            orders = rider_orders.get(email, [])
            succ   = sum(1 for o in orders if (o.get('status') or '').lower() in done_statuses)
            fail   = sum(1 for o in orders if (o.get('status') or '').lower() in cancelled_statuses)
            earn   = succ * 47.5   # 50 delivery fee  95% (5% platform cut)
            rider_analytics.append({
                'no':                   idx,
                'rider_name':           user_map.get(email, {}).get('name', email),
                'email':                email,
                'vehicle_type':         user_map.get(email, {}).get('vehicle_type', 'N/A'),
                'plate_number':         user_map.get(email, {}).get('plate', 'N/A'),
                'total_deliveries':     len(orders),
                'successful_deliveries':succ,
                'failed_deliveries':    fail,
                'total_earnings':       round(earn, 2),
            })
        rider_analytics.sort(key=lambda x: x['total_deliveries'], reverse=True)

        #  7. Buyer Insights 
        buyers = [u for u in all_users if (u.get('role') or '').lower() == 'buyer']
        buyer_orders = defaultdict(list)
        for o in all_orders:
            if o.get('email'): buyer_orders[o['email']].append(o)

        buyer_insights = []
        for u in buyers:
            email  = u['email']
            orders = [o for o in buyer_orders.get(email, []) if (o.get('status') or '').lower() in done_statuses]
            spend  = sum(float(o.get('total_price') or 0) for o in orders)
            aov    = round(spend / len(orders), 2) if orders else 0.0
            dates  = [o.get('date') for o in orders if o.get('date')]
            last   = _fmt_date(max(dates)) if dates else None
            buyer_insights.append({
                'buyer_name':      user_map.get(email, {}).get('name', email),
                'email':           email,
                'total_orders':    len(orders),
                'total_spend':     round(spend, 2),
                'avg_order_value': aov,
                'last_order_date': last,
                'cart_items':      cart_count.get(email, 0),
                'wishlist_items':  wishlist_count.get(email, 0),
            })
        buyer_insights.sort(key=lambda x: x['total_spend'], reverse=True)
        buyer_insights = [dict(b, no=i+1) for i, b in enumerate(buyer_insights[:50])]

        #  8. Promo Code Analytics 
        promo_code_analytics = []
        try:
            promos_res = sb_admin.table('promotions').select('*').execute()
            usage_res  = sb_admin.table('promotion_usage').select('promotion_id,discount_applied').execute()
            usage_map  = defaultdict(lambda: {'uses': 0, 'discount': 0.0})
            for pu in (usage_res.data or []):
                pid = pu.get('promotion_id')
                if pid:
                    usage_map[pid]['uses']     += 1
                    usage_map[pid]['discount'] += float(pu.get('discount_applied') or 0)
            for idx, p in enumerate((promos_res.data or []), 1):
                pid = p.get('id')
                promo_code_analytics.append({
                    'no':                 idx,
                    'promo_code':         p.get('code', 'N/A'),
                    'discount_type':      p.get('type', 'N/A'),
                    'discount_value':     float(p.get('discount_value') or 0),
                    'start_date':         _fmt_date(p.get('start_date')),
                    'end_date':           _fmt_date(p.get('end_date')),
                    'total_uses':         usage_map[pid]['uses'],
                    'total_discount_given': round(usage_map[pid]['discount'], 2),
                })
        except Exception as e:
            print(f"promo analytics error: {e}")

        #  9. Platform Commission 
        done_orders = [o for o in all_orders if (o.get('status') or '').lower() in done_statuses]
        platform_commission = []
        for idx, o in enumerate(done_orders[:100], 1):
            total   = float(o.get('total_price') or 0)
            fee     = float(o.get('shipping_fee') or 50)
            s_comm  = round(total * 0.05, 2)
            r_comm  = round(fee   * 0.05, 2)
            completed_date = o.get('received_at') or o.get('delivered_at') or o.get('date')
            platform_commission.append({
                'no':                    idx,
                'order_id':              o['id'],
                'seller_email':          o.get('seller_email', 'N/A'),
                'rider_email':           o.get('rider_email') or 'N/A',
                'order_total':           total,
                'delivery_fee':          fee,
                'seller_commission':     s_comm,
                'rider_commission':      r_comm,
                'total_platform_earnings': round(s_comm + r_comm, 2),
                'order_date':            _fmt_date(o.get('date')),
                'date_completed':        _fmt_date(completed_date),
            })

        #  10. Complaints & Issues 
        complaints_issues = []
        try:
            issues_res = sb_admin.table('order_issues').select('*').order('created_at', desc=True).limit(100).execute()
            for idx, iss in enumerate((issues_res.data or []), 1):
                reporter_email = iss.get('reporter_email', '')
                against_email  = iss.get('reported_against_email', '')
                complaints_issues.append({
                    'no':                    idx,
                    'order_id':              iss.get('order_id'),
                    'reported_by':           user_map.get(reporter_email, {}).get('name', reporter_email),
                    'reported_by_email':     reporter_email,
                    'reporter_role':         (iss.get('reporter_role') or 'unknown').capitalize(),
                    'reported_against':      user_map.get(against_email, {}).get('name', against_email) if against_email else (iss.get('reported_against_role') or 'N/A').capitalize(),
                    'reported_against_email':against_email or 'N/A',
                    'reported_against_role': (iss.get('reported_against_role') or 'N/A').capitalize(),
                    'issue_type':            iss.get('issue_type', 'N/A'),
                    'description':           iss.get('issue_description', ''),
                    'status':                iss.get('status', 'pending'),
                    'date_submitted':        _fmt_date(iss.get('created_at')),
                })
        except Exception as e:
            print(f"complaints analytics error: {e}")

        return jsonify({
            'totalOrders':         total_orders,
            'totalUsers':          total_users,
            'totalProducts':       total_products,
            'inventoryProducts':   inventory_products,
            'sellerPerformance':   seller_performance,
            'riderAnalytics':      rider_analytics,
            'buyerInsights':       buyer_insights,
            'promoCodeAnalytics':  promo_code_analytics,
            'platformCommission':  platform_commission,
            'complaintsIssues':    complaints_issues,
        })

    except Exception as e:
        print(f"admin_analytics_api Supabase error: {e}")
        import traceback; traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route('/cart', methods=['GET'])
def cart():
    if 'email' not in session:
        return redirect(url_for('login'))
    user_email = session.get('email')
    user_name  = get_user_name_from_session(default='User')
    cart_items = []
    try:
        res = sb_admin.table('cart').select('id, name, price, quantity, variations, size, image, seller_email, product_id').eq('email', user_email).order('id', desc=True).execute()
        raw_items = res.data or []

        # Batch-fetch product images for color matching
        product_ids = list({item.get('product_id') for item in raw_items if item.get('product_id')})
        prod_img_map = {}
        seller_emails_from_cart = list({item.get('seller_email') for item in raw_items if item.get('seller_email')})
        seller_name_map = {}
        if product_ids:
            try:
                pr = sb_admin.table('products').select('id, image, image_colors').in_('id', product_ids).execute()
                for p in (pr.data or []):
                    prod_img_map[p['id']] = {'image': p.get('image',''), 'image_colors': p.get('image_colors','')}
            except Exception:
                pass
        if seller_emails_from_cart:
            try:
                sr = sb_admin.table('users').select('email, business_name, first_name, last_name').in_('email', seller_emails_from_cart).execute()
                for s in (sr.data or []):
                    biz = s.get('business_name') or f"{s.get('first_name','')} {s.get('last_name','')}".strip() or s['email']
                    seller_name_map[s['email']] = biz
            except Exception:
                pass

        for item in raw_items:
            cart_image = (item.get('image') or '').strip()
            pid = item.get('product_id')
            selected_color = (item.get('variations') or '').strip().lower()

            # Resolve color-matched image
            first_image_url = ''
            if cart_image.startswith('http://') or cart_image.startswith('https://'):
                first_image_url = cart_image
            elif pid and pid in prod_img_map:
                prod = prod_img_map[pid]
                color_map = _parse_image_colors_dict(prod.get('image_colors',''), prod.get('image',''))
                matched = color_map.get(selected_color) if selected_color else None
                if not matched and selected_color:
                    for k, v in color_map.items():
                        if selected_color in k or k in selected_color:
                            matched = v; break
                if matched:
                    first_image_url = matched if matched.startswith('http') else f"https://vydcnhmgqovketjqvpoe.supabase.co/storage/v1/object/public/product-images/products/{matched.split('/')[-1]}"
                elif prod.get('image'):
                    first_img = prod['image'].split(',')[0].strip()
                    first_image_url = first_img if first_img.startswith('http') else f"https://vydcnhmgqovketjqvpoe.supabase.co/storage/v1/object/public/product-images/products/{first_img.split('/')[-1]}"
            elif cart_image:
                first_image_url = f"https://vydcnhmgqovketjqvpoe.supabase.co/storage/v1/object/public/product-images/products/{cart_image.split('/')[-1]}"

            cart_items.append({
                'id': item['id'], 'name': item.get('name',''),
                'price': float(item.get('price') or 0),
                'quantity': int(item.get('quantity') or 1),
                'variations': item.get('variations',''), 'size': item.get('size',''),
                'image': cart_image, 'seller_email': item.get('seller_email',''),
                'seller_name': seller_name_map.get(item.get('seller_email',''), item.get('seller_email','')),
                'product_id': pid,
                'image_url': first_image_url,
                'first_image_url': first_image_url,
                'all_images': prod_img_map.get(pid, {}).get('image', '') if pid else '',
            })
    except Exception as e:
        print(f"cart Supabase error: {e}")
    return render_template('cart.html', cart_items=cart_items, user_name=user_name, user_email=user_email)


@app.route('/cart/delete_selected', methods=['POST'])
def delete_selected_items():
    selected_ids = request.json.get('ids')
    user_email = session.get('email')

    if not selected_ids:
        return jsonify({'success': False, 'error': 'No IDs provided'}), 400

    # -- PRIMARY: Supabase -----------------------------------------------------
    try:
        int_ids = [int(i) for i in selected_ids]
        sb_admin.table('cart').delete() \
            .in_('id', int_ids) \
            .eq('email', user_email) \
            .execute()
        return jsonify({'success': True})
    except Exception as sb_err:
        print(f"?? Supabase delete_selected failed: {sb_err}")

    # -- FALLBACK: MySQL -------------------------------------------------------

    # MySQL cart delete removed - Supabase handles this above

@app.route('/add-to-cart', methods=['POST'])
@app.route('/add_to_cart', methods=['POST'])
def add_to_cart():
    if 'email' not in session:
        return jsonify({'error': 'Please login first'}), 401

    user_email = session.get('email')

    try:
        # Parse request data
        if request.is_json:
            data = request.get_json()
            product_id = data.get('product_id')
            product_name = data.get('product_name', '')
            product_price = data.get('product_price', '0')
            product_image = data.get('product_image', '')
            product_variation = data.get('product_variation', '')
            size = data.get('size', '')
            quantity = data.get('quantity', '1')
        else:
            product_id = request.form.get('product_id')
            product_name = request.form.get('product_name', '')
            product_price = request.form.get('product_price', '0')
            product_image = request.form.get('product_image', '')
            product_variation = request.form.get('product_variation', '')
            size = request.form.get('size', '')
            quantity = request.form.get('quantity', '1')

        if not product_id:
            return jsonify({'error': 'Product ID is required'}), 400

        qty_int = int(quantity) if str(quantity).isdigit() else 1
        price_float = float(product_price) if product_price else 0.0

        # -- Get product details from Supabase -----------------------------
        seller_email = ''
        all_product_images = ''
        image_colors_str = ''
        try:
            prod_res = sb_admin.table('products') \
                .select('seller_email, image, image_colors') \
                .eq('id', int(product_id)) \
                .limit(1) \
                .execute()
            if prod_res.data:
                seller_email = prod_res.data[0].get('seller_email', '')
                all_product_images = prod_res.data[0].get('image', '') or ''
                image_colors_str = prod_res.data[0].get('image_colors', '') or ''
        except Exception as e:
            print(f"?? Could not fetch product from Supabase: {e}")


        # Find color-specific image
        cart_image = product_image  # use what frontend sent (already color-specific)
        if not cart_image:
            # Try to find color-specific image from image_colors mapping
            if product_variation and image_colors_str:
                cart_image = _find_color_image(product_variation, image_colors_str, all_product_images) or ''
            if not cart_image and all_product_images:
                cart_image = all_product_images.split(',')[0].strip()

        print(f"ADD_TO_CART: {product_name} | color={product_variation} | size={size} | qty={qty_int} | img={cart_image[:60] if cart_image else ''}")

        # -- PRIMARY: Write to Supabase ------------------------------------
        supabase_ok = False
        try:
            # Check cart limit in Supabase
            count_res = sb_admin.table('cart') \
                .select('quantity') \
                .eq('email', user_email) \
                .execute()
            current_qty = sum(int(r.get('quantity') or 1) for r in (count_res.data or []))
            if current_qty + qty_int > 20:
                return jsonify({'cartFull': True, 'error': 'Cart is full! Maximum 20 items allowed.'})

            # Get variant stock cap for this color+size
            variant_stock = None
            try:
                vs_res = sb_admin.table('variant_inventory') \
                    .select('stock_quantity') \
                    .eq('product_id', int(product_id)) \
                    .eq('color', product_variation or '') \
                    .eq('size', size or '') \
                    .limit(1) \
                    .execute()
                if vs_res.data:
                    variant_stock = int(vs_res.data[0].get('stock_quantity') or 0)
            except Exception:
                pass  # no stock cap if variant_inventory unavailable

            # Check if same product+color+size already in cart
            existing_res = sb_admin.table('cart') \
                .select('id, quantity') \
                .eq('email', user_email) \
                .eq('product_id', int(product_id)) \
                .eq('variations', product_variation or '') \
                .eq('size', size or '') \
                .limit(1) \
                .execute()

            if existing_res.data:
                existing = existing_res.data[0]
                existing_qty = int(existing['quantity'])
                new_qty = existing_qty + qty_int
                # Cap at variant stock if available
                if variant_stock is not None and new_qty > variant_stock:
                    new_qty = variant_stock
                if new_qty <= existing_qty:
                    return jsonify({'success': True, 'stockCapped': True,
                                    'message': f'Already at maximum stock ({variant_stock} available)'})
                sb_admin.table('cart').update({'quantity': new_qty}).eq('id', existing['id']).execute()
            else:
                # Cap initial quantity at variant stock
                final_qty = qty_int
                if variant_stock is not None and final_qty > variant_stock:
                    final_qty = variant_stock
                if final_qty <= 0:
                    return jsonify({'success': False, 'error': 'This variant is out of stock'}), 400
                sb_admin.table('cart').insert({
                    'email':        user_email,
                    'product_id':   int(product_id),
                    'name':         product_name,
                    'price':        price_float,
                    'seller_email': seller_email,
                    'variations':   product_variation or '',
                    'size':         size or '',
                    'quantity':     final_qty,
                    'image':        cart_image or '',
                }).execute()

            supabase_ok = True
            print(f"? Cart item saved to Supabase")
        except Exception as sb_err:
            print(f"?? Supabase cart insert failed: {sb_err}")

        # -- SECONDARY: Mirror to MySQL ------------------------------------
        # MySQL cart mirror removed

        if not supabase_ok:
            return jsonify({'error': 'Failed to add item to cart. Please try again.'}), 500

        return jsonify({'success': True, 'message': f"{product_name} has been added to your cart"})

    except Exception as e:
        print(f"Error adding to cart: {str(e)}")
        return jsonify({'error': 'Failed to add item to cart. Please try again.'}), 500

@app.route('/checkout_route', methods=['POST'])
def checkout_route():
    if 'email' not in session:
        return jsonify(success=False, error="Please login first"), 401

    try:
        data = request.get_json()
        if not data or 'selected_ids' not in data:
            return jsonify(success=False, error="No items selected for checkout"), 400

        selected_ids = data['selected_ids']
        if not selected_ids:
            return jsonify(success=False, error="No items selected for checkout"), 400

        user_email = session['email']

        # -- PRIMARY: Supabase ----------------------------------------------
        try:
            # IDs from the cart may be strings or ints � handle both
            int_ids = []
            for i in selected_ids:
                try:
                    int_ids.append(int(i))
                except (ValueError, TypeError):
                    print(f"?? checkout_route: skipping non-integer id: {i!r}")

            if not int_ids:
                return jsonify(success=False, error="No valid item IDs provided"), 400

            cart_res = sb_admin.table('cart') \
                .select('id, name, price, quantity, variations, size, image, seller_email, product_id') \
                .in_('id', int_ids) \
                .eq('email', user_email) \
                .execute()

            cart_items = cart_res.data or []
            print(f"DEBUG checkout_route: queried ids={int_ids}, found {len(cart_items)} items")

            if not cart_items:
                # Try fetching all cart items to debug
                all_cart = sb_admin.table('cart').select('id, email').eq('email', user_email).execute()
                print(f"DEBUG checkout_route: all cart items for {user_email}: {[r['id'] for r in (all_cart.data or [])]}")
                return jsonify(success=False, error="No items found in cart"), 404

            # Resolve color-specific images from product image_colors
            product_ids = list({item['product_id'] for item in cart_items if item.get('product_id')})
            prod_images = {}
            if product_ids:
                try:
                    pr = sb_admin.table('products') \
                        .select('id, image, image_colors') \
                        .in_('id', product_ids) \
                        .execute()
                    for p in (pr.data or []):
                        prod_images[p['id']] = p
                except Exception:
                    pass

            # Build checkout items list and store in session
            checkout_items_session = []
            for item in cart_items:
                pid = item.get('product_id')
                selected_color = (item.get('variations') or '').strip()
                image = item.get('image') or ''

                # Try to get color-specific image
                if pid and selected_color and pid in prod_images:
                    prod = prod_images[pid]
                    color_map = _parse_image_colors_dict(
                        prod.get('image_colors'), prod.get('image'))
                    color_img = color_map.get(selected_color.lower())
                    if color_img:
                        image = color_img

                # Check free shipping promotion (Supabase)
                shipping_fee = 50
                try:
                    promo_res = sb_admin.table('promotions') \
                        .select('id') \
                        .eq('seller_email', item.get('seller_email', '')) \
                        .eq('type', 'free_shipping') \
                        .eq('is_active', True) \
                        .execute()
                    if promo_res.data:
                        shipping_fee = 0
                except Exception:
                    pass

                checkout_items_session.append({
                    'id':           item['id'],
                    'name':         item['name'],
                    'price':        float(item['price'] or 0),
                    'quantity':     int(item['quantity'] or 1),
                    'variations':   item.get('variations') or '',
                    'size':         item.get('size') or '',
                    'image':        image,
                    'seller_email': item.get('seller_email') or '',
                    'product_id':   pid,
                    'shipping_fee': shipping_fee,
                })

            # Store in session for the checkout page to read
            session['checkout_items'] = checkout_items_session
            session['checkout_source'] = 'cart'
            session.modified = True

            print(f"? checkout_route Supabase: {len(checkout_items_session)} items stored in session")

            # MySQL mirror removed

            return jsonify(success=True)

        except Exception as sb_err:
            print(f"?? checkout_route Supabase failed: {sb_err}")
            import traceback; traceback.print_exc()
            return jsonify(success=False, error=f"Failed to process checkout: {str(sb_err)}"), 500

    except Exception as e:
        print(f"checkout_route error: {e}")
        import traceback; traceback.print_exc()
        return jsonify(success=False, error=f"Unexpected error: {str(e)}"), 500

@app.route('/checkout')
def checkout():
    user_email = session.get('email')

    # -- PRIMARY: read from session (populated by checkout_route via Supabase) --
    checkout_items = []
    session_items = session.get('checkout_items')

    if session_items:
        # Enrich with product data from Supabase
        product_ids = list({item['product_id'] for item in session_items if item.get('product_id')})
        prod_map = {}
        if product_ids:
            try:
                pr = sb_admin.table('products') \
                    .select('id, image, image_colors, price, category, seller_email') \
                    .in_('id', product_ids) \
                    .execute()
                for p in (pr.data or []):
                    prod_map[p['id']] = p
            except Exception as e:
                print(f"?? checkout product fetch failed: {e}")

        for item in session_items:
            pid = item.get('product_id')
            prod = prod_map.get(pid, {})
            original_price = float(prod.get('price') or item['price'])

            # Resolve color-specific image — always prefer image_colors mapping
            image = item.get('image') or ''
            color_key = (item.get('variations') or '').strip().lower()
            if prod:
                color_map = _parse_image_colors_dict(prod.get('image_colors'), prod.get('image'))
                if color_key and color_key in color_map:
                    image = color_map[color_key]  # exact color match wins
                elif not image:
                    image = (prod.get('image') or '').split(',')[0].strip()
            # Resolve to full URL if it's just a filename
            if image and not image.startswith('http') and not image.startswith('/'):
                image = f"/static/images/uploads/{image.split('/')[-1]}"

            checkout_items.append({
                'id':                  item['id'],
                'name':                item['name'],
                'price':               float(item['price']),
                'quantity':            int(item['quantity']),
                'variations':          item.get('variations') or '',
                'size':                item.get('size') or '',
                'image':               image,
                'seller_email':        item.get('seller_email') or '',
                'product_id':          pid,
                'shipping_fee':        float(item.get('shipping_fee') or 50),
                'original_price':      original_price,
                'all_product_images':  prod.get('image') or '',
                'category':            prod.get('category') or '',
                'has_promotion':       False,
                'promotional_price':   float(item['price']),
                'discount_amount':     0.0,
                'discount_percentage': 0,
                'promotion_name':      '',
                'promotion_type':      '',
            })
        print(f"? checkout: loaded {len(checkout_items)} items from session (Supabase)")

    else:
        # MySQL fallback removed
        checkout_items = []

    if not checkout_items:
        return redirect(url_for('cart'))

    # Process items to ensure correct image selection and promotional pricing
    for item in checkout_items:
        try:
            # More robust price conversion
            price_val = item['price']
            if isinstance(price_val, str):
                price_val = price_val.strip()
                if price_val == '' or price_val.lower() == 'none':
                    item['price'] = 0.0
                else:
                    item['price'] = float(price_val)
            else:
                item['price'] = float(price_val) if price_val is not None else 0.0
            
            # More robust quantity conversion
            quantity_val = item['quantity']
            if isinstance(quantity_val, str):
                quantity_val = quantity_val.strip()
                if quantity_val == '' or quantity_val.lower() == 'none':
                    item['quantity'] = 0
                else:
                    item['quantity'] = int(quantity_val)
            else:
                item['quantity'] = int(quantity_val) if quantity_val is not None else 0
                
        except (ValueError, TypeError) as e:
            print(f"Error converting item data for item {item.get('id', 'unknown')}: {e}")
            # Set safe defaults if conversion fails
            item['price'] = 0.0
            item['quantity'] = 0
        
        # Check for active promotions for this product
        if item.get('product_id') and item.get('original_price'):
            try:
                # More robust conversion with string handling
                original_price_val = item['original_price']
                if isinstance(original_price_val, str):
                    original_price_val = original_price_val.strip()
                    if original_price_val == '' or original_price_val.lower() == 'none':
                        original_price = 0.0
                    else:
                        original_price = float(original_price_val)
                else:
                    original_price = float(original_price_val) if original_price_val is not None else 0.0
                
                current_price_val = item['price']
                if isinstance(current_price_val, str):
                    current_price_val = current_price_val.strip()
                    if current_price_val == '' or current_price_val.lower() == 'none':
                        current_price = 0.0
                    else:
                        current_price = float(current_price_val)
                else:
                    current_price = float(current_price_val) if current_price_val is not None else 0.0
                    
            except (ValueError, TypeError) as e:
                print(f"Error converting prices for item {item.get('id', 'unknown')}: {e}")
                # If conversion fails, set defaults
                original_price = 0.0
                current_price = 0.0
            
            # Get active promotions for this product
            active_promotion = get_active_promotions_for_product(
                item['product_id'], 
                item.get('product_seller_email', item.get('seller_email', '')), 
                item.get('category', '')
            )
            
            if active_promotion:
                promotion_type = active_promotion.get('type', '')
                
                # For price-affecting promotions (percentage, fixed)
                if promotion_type in ['percentage', 'fixed'] and current_price < original_price:
                    item['has_promotion'] = True
                    item['promotional_price'] = max(0.0, current_price)  # Ensure non-negative
                    item['discount_amount'] = max(0.0, original_price - current_price)  # Ensure non-negative
                    item['discount_percentage'] = round((item['discount_amount'] / original_price) * 100, 1) if original_price > 0 else 0
                    item['promotion_name'] = active_promotion.get('name', '') or ''
                    item['promotion_type'] = promotion_type
                # For non-price-affecting promotions (free_shipping, buy_one_get_one)
                elif promotion_type in ['free_shipping', 'buy_one_get_one']:
                    item['has_promotion'] = True
                    item['promotional_price'] = max(0.0, current_price)  # Same as original price
                    item['discount_amount'] = 0.0  # No price discount
                    item['discount_percentage'] = 0  # No percentage discount
                    item['promotion_name'] = active_promotion.get('name', '') or ''
                    item['promotion_type'] = promotion_type
                else:
                    # No valid promotion
                    item['has_promotion'] = False
                    item['promotional_price'] = max(0.0, current_price)  # Ensure non-negative
                    item['discount_amount'] = 0.0
                    item['discount_percentage'] = 0
                    item['promotion_name'] = ''
                    item['promotion_type'] = ''
            else:
                # No promotion
                item['has_promotion'] = False
                item['promotional_price'] = max(0.0, current_price)  # Ensure non-negative
                item['discount_amount'] = 0.0
                item['discount_percentage'] = 0
                item['promotion_name'] = ''
                item['promotion_type'] = ''
        else:
            # No promotional data available
            item['has_promotion'] = False
            item['promotional_price'] = item['price']
            item['discount_amount'] = 0
            item['discount_percentage'] = 0
            item['promotion_name'] = ''
            item['promotion_type'] = ''
        
        # Ensure original_price is always set for template formatting
        if not item.get('original_price'):
            item['original_price'] = item['price']
        
        # Final validation - ensure all numeric fields are actually numbers
        try:
            item['price'] = float(item['price']) if item['price'] is not None else 0.0
            item['quantity'] = int(item['quantity']) if item['quantity'] is not None else 0
            item['promotional_price'] = float(item.get('promotional_price', item['price'])) if item.get('promotional_price') is not None else float(item['price'])
            item['original_price'] = float(item.get('original_price', item['price'])) if item.get('original_price') is not None else float(item['price'])
            item['discount_amount'] = float(item.get('discount_amount', 0)) if item.get('discount_amount') is not None else 0.0
            item['discount_percentage'] = float(item.get('discount_percentage', 0)) if item.get('discount_percentage') is not None else 0.0
        except (ValueError, TypeError) as e:
            print(f"Final validation error for item {item.get('id', 'unknown')}: {e}")
            # Set absolute safe defaults
            item['price'] = 0.0
            item['quantity'] = 0
            item['promotional_price'] = 0.0
            item['original_price'] = 0.0
            item['discount_amount'] = 0.0
            item['discount_percentage'] = 0.0
        
        # Get all product images for color matching
        all_images = item.get('all_product_images', '') or item.get('image', '')
        
        # Determine the best image based on selected color (same logic as cart)
        selected_color = item.get('variations', '').split(',')[0].strip() if item.get('variations') else ''
        
        if all_images and selected_color:
            images = [img.strip() for img in str(all_images).split(',') if img.strip()]
            color_lower = selected_color.lower().strip()
            
            # Find image that matches the selected color
            best_image = images[0] if images else ''  # Default to first image
            
            for img in images:
                img_lower = img.lower().strip()
                # Check if color name is in image filename
                if (color_lower in img_lower or 
                    color_lower.replace(' ', '_') in img_lower or 
                    color_lower.replace(' ', '-') in img_lower or 
                    color_lower.replace(' ', '') in img_lower):
                    best_image = img
                    break
            
            # Update the image field to use the color-matched image
            item['image'] = best_image
            print(f"Checkout item {item['id']}: Selected color '{selected_color}' -> Image '{best_image}'")
        
        # Ensure image field is properly set
        if not item.get('image') and all_images:
            images = [img.strip() for img in str(all_images).split(',') if img.strip()]
            item['image'] = images[0] if images else ''

    # Calculate the total price using promotional pricing when available
    total_price = 0
    for item in checkout_items:
        try:
            # Use promotional price if available, otherwise use regular price
            price_to_use = item.get('promotional_price', item['price'])
            item_price = float(price_to_use) if price_to_use is not None else 0.0
            item_quantity = int(item['quantity']) if item['quantity'] is not None else 0
            total_price += item_price * item_quantity
        except (ValueError, TypeError):
            # Skip items with invalid pricing
            continue

    # Set default checkout source if not already set
    if 'checkout_source' not in session:
        session['checkout_source'] = 'cart'

    # Get user name for header display � Supabase primary
    user_name = "User"
    user_address = ''
    try:
        un_res = sb_admin.table('users') \
            .select('first_name, last_name, house_street, barangay, city, province, region, zip_code') \
            .eq('email', user_email).execute()
        if un_res.data:
            u = un_res.data[0]
            user_name = f"{u.get('first_name','')} {u.get('last_name','')}".strip() or 'User'
            user_address = ', '.join(filter(None, [
                u.get('house_street', ''),
                u.get('barangay', ''),
                u.get('city', ''),
                u.get('province', ''),
                u.get('region', ''),
                u.get('zip_code', ''),
            ]))
    except Exception:
        user_name = session.get('first_name', 'User')
        user_address = session.get('address', '')

    # Calculate shipping fees
    shipping_fee = 0.0
    has_free_shipping = False
    
    # Check if any item has free shipping promotion
    for item in checkout_items:
        if item.get('promotion_type') == 'free_shipping':
            has_free_shipping = True
            print(f"DEBUG - Free shipping detected for item: {item.get('name', 'Unknown')}")
            break
    
    if not has_free_shipping:
        # Calculate shipping fee based on total order value
        # Standard shipping: ?50 base fee + ?10 per ?500 of order value (max ?200)
        base_shipping = 50.0
        if total_price > 0:
            additional_shipping = min(150.0, (total_price // 500) * 10)  # Max additional ?150
            shipping_fee = base_shipping + additional_shipping
        else:
            shipping_fee = base_shipping
    
    # Calculate final total with shipping
    final_total = total_price + shipping_fee

    # Debug: Print checkout items data
    print("DEBUG - Checkout items being passed to template:")
    for i, item in enumerate(checkout_items):
        print(f"  Item {i+1}: {item.get('name', 'Unknown')}")
        print(f"    Price: {item.get('price')} (type: {type(item.get('price'))})")
        print(f"    Promotional Price: {item.get('promotional_price')} (type: {type(item.get('promotional_price'))})")
        print(f"    Original Price: {item.get('original_price')} (type: {type(item.get('original_price'))})")
        print(f"    Has Promotion: {item.get('has_promotion')}")
        print(f"    Promotion Type: {item.get('promotion_type')}")
        print(f"    Discount Amount: {item.get('discount_amount')} (type: {type(item.get('discount_amount'))})")
    
    print(f"DEBUG - Shipping calculation:")
    print(f"  Subtotal: ?{total_price:.2f}")
    print(f"  Has Free Shipping: {has_free_shipping}")
    print(f"  Shipping Fee: ?{shipping_fee:.2f}")
    print(f"  Final Total: ?{final_total:.2f}")
    
    # Debug promotion types
    free_shipping_items = [item for item in checkout_items if item.get('promotion_type') == 'free_shipping']
    if free_shipping_items:
        print(f"  Free shipping items found: {len(free_shipping_items)}")
        for item in free_shipping_items:
            print(f"    - {item.get('name', 'Unknown')} (type: {item.get('promotion_type')})")

    return render_template('checkout.html',
                         checkout_items=checkout_items,
                         total_price=total_price,
                         shipping_fee=shipping_fee,
                         has_free_shipping=has_free_shipping,
                         final_total=final_total,
                         user_name=user_name,
                         user_address=user_address,
                         user_email=session.get('email', 'User'))

@app.route('/return_to_cart', methods=['POST'])
def return_to_cart():
    selected_ids = request.json.get('ids')
    user_email = session.get('email')

    if not selected_ids:
        return jsonify(success=False, error="No items selected to return to the cart"), 400

    try:
        selected_id_set = {str(i) for i in selected_ids}

        # -- Read checkout items from session (primary source) -------------
        session_items = session.get('checkout_items') or []
        checkout_items = [i for i in session_items if str(i.get('id')) in selected_id_set]

        # -- Fallback: try Supabase checkout table -------------------------
        if not checkout_items:
            try:
                int_ids = [int(i) for i in selected_ids]
                co_res = sb_admin.table('checkout') \
                    .select('*') \
                    .in_('id', int_ids) \
                    .eq('email', user_email) \
                    .execute()
                checkout_items = co_res.data or []
            except Exception as sb_err:
                print(f"?? return_to_cart Supabase fallback failed: {sb_err}")

        if not checkout_items:
            return jsonify(success=False, error="No items found to return to the cart"), 400

        # -- Move each item back to cart -----------------------------------
        for item in checkout_items:
            product_id = item.get('product_id')
            color      = item.get('variations') or ''
            size       = item.get('size') or ''
            qty        = int(item.get('quantity') or 1)

            # Check if same product+color+size already in cart
            # (the original cart row may still exist � just restore its quantity)
            existing_res = sb_admin.table('cart') \
                .select('id, quantity') \
                .eq('email', user_email) \
                .eq('product_id', product_id) \
                .eq('variations', color) \
                .eq('size', size) \
                .limit(1).execute()

            if existing_res.data:
                # Item still in cart � restore to the checkout quantity (don't add)
                sb_admin.table('cart') \
                    .update({'quantity': qty}) \
                    .eq('id', existing_res.data[0]['id']) \
                    .execute()
            else:
                # Item was removed from cart � re-insert it
                sb_admin.table('cart').insert({
                    'email':        user_email,
                    'product_id':   product_id,
                    'name':         item.get('name', ''),
                    'price':        item.get('price', 0),
                    'quantity':     qty,
                    'variations':   color,
                    'size':         size,
                    'image':        item.get('image', ''),
                    'seller_email': item.get('seller_email', ''),
                }).execute()

        # -- Clear checkout session ----------------------------------------
        session.pop('checkout_items', None)
        session.pop('checkout_source', None)
        session.modified = True

        # -- Also clean up Supabase checkout table if it exists ------------
        try:
            int_ids = [int(i) for i in selected_ids]
            sb_admin.table('checkout') \
                .delete() \
                .in_('id', int_ids) \
                .eq('email', user_email) \
                .execute()
        except Exception:
            pass

        return jsonify(success=True)

    except Exception as e:
        print(f"return_to_cart error: {e}")
        import traceback; traceback.print_exc()
        return jsonify(success=False, error=str(e)), 500

@app.route('/checkout/delete/<int:item_id>', methods=['POST'])
def delete_checkout_item(item_id):
    user_email = session.get('email')
    try:
        session_items = session.get('checkout_items', [])
        item_id_int = int(item_id)
        session['checkout_items'] = [i for i in session_items if i.get('id') != item_id_int]
        session.modified = True
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/confirm_order', methods=['POST'])
def confirm_order():
    try:
        data = request.json
        frontend_items = data.get('items', [])
        payment_method = data.get('payment_method')
        user_email = session.get('email')

        subtotal    = float(data.get('subtotal', 0))
        shipping_fee = float(data.get('shipping_fee', 0))
        final_total  = float(data.get('final_total', 0))

        if not frontend_items or not payment_method or not user_email:
            return jsonify({"success": False, "error": "Missing required data"})

        print(f"DEBUG confirm_order: subtotal={subtotal} shipping={shipping_fee} total={final_total} method={payment_method}")

        # -- 1. Fetch checkout items from session (primary) or Supabase ------
        checkout_item_ids = [int(item['id']) for item in frontend_items]
        id_set = {str(i) for i in checkout_item_ids}

        # Read from session first (checkout_route stores items here)
        session_items = session.get('checkout_items') or []
        checkout_items = [i for i in session_items if str(i.get('id')) in id_set]

        # Fallback: try Supabase checkout table
        if not checkout_items:
            try:
                co_res = sb_admin.table('checkout') \
                    .select('*') \
                    .in_('id', checkout_item_ids) \
                    .eq('email', user_email) \
                    .execute()
                checkout_items = co_res.data or []
            except Exception as co_err:
                print(f"?? confirm_order: Supabase checkout fallback failed: {co_err}")

        if len(checkout_items) != len(frontend_items):
            raise Exception(f"Checkout item mismatch: expected {len(frontend_items)}, got {len(checkout_items)}")

        frontend_item_map = {str(item['id']): item for item in frontend_items}

        # -- 2. Process each item ------------------------------------------
        for checkout_item in checkout_items:
            frontend_item = frontend_item_map.get(str(checkout_item['id']))
            if not frontend_item:
                raise Exception(f"Frontend item not found for checkout id {checkout_item['id']}")

            product_id_raw = checkout_item.get('product_id') or ''
            try:
                product_id_int = int(product_id_raw)
            except (ValueError, TypeError):
                product_id_int = None

            # -- Fetch product from Supabase -------------------------------
            product = None
            if product_id_int:
                p_res = sb_admin.table('products') \
                    .select('id, quantity, sold, low_stock_threshold, seller_email') \
                    .eq('id', product_id_int) \
                    .limit(1).execute()
                if p_res.data:
                    product = p_res.data[0]

            if not product:
                # Fallback: find by name
                p_res2 = sb_admin.table('products') \
                    .select('id, quantity, sold, low_stock_threshold, seller_email') \
                    .eq('name', checkout_item['name']) \
                    .limit(1).execute()
                if p_res2.data:
                    product = p_res2.data[0]
                    product_id_int = product['id']
                    checkout_item['product_id'] = str(product_id_int)
                else:
                    raise Exception(f"Product not found: {checkout_item['name']}")

            current_qty = int(product.get('quantity') or 0)
            order_qty   = int(checkout_item.get('quantity') or 1)
            new_qty     = current_qty - order_qty

            if new_qty < 0:
                raise Exception(f"Insufficient stock for: {checkout_item['name']}")

            # -- Update product quantity + sold ----------------------------
            sb_admin.table('products').update({
                'quantity': new_qty,
                'sold': int(product.get('sold') or 0) + order_qty,
            }).eq('id', product_id_int).execute()

            product_threshold = int(product.get('low_stock_threshold') or 5)
            check_and_notify_stock_levels(
                product_id=str(product_id_int),
                seller_email=checkout_item.get('seller_email', ''),
                new_quantity=new_qty,
                threshold=product_threshold,
                product_name=checkout_item['name'],
                variant_info=None,
            )

            # -- Update variant inventory ----------------------------------
            order_color = (checkout_item.get('variations') or '').strip()
            order_size  = (checkout_item.get('size') or '').strip()

            if order_color and order_size and product_id_int:
                vi_res = sb_admin.table('variant_inventory') \
                    .select('id, stock_quantity, low_stock_threshold') \
                    .eq('product_id', product_id_int) \
                    .eq('color', order_color) \
                    .eq('size', order_size) \
                    .limit(1).execute()

                if vi_res.data:
                    vi = vi_res.data[0]
                    v_stock     = int(vi.get('stock_quantity') or 0)
                    new_v_stock = v_stock - order_qty
                    v_threshold = int(vi.get('low_stock_threshold') or 5)

                    if new_v_stock < 0:
                        raise Exception(f"Insufficient variant stock for {checkout_item['name']} ({order_color}/{order_size})")

                    sb_admin.table('variant_inventory').update({
                        'stock_quantity': new_v_stock,
                    }).eq('id', vi['id']).execute()

                    check_and_notify_stock_levels(
                        product_id=str(product_id_int),
                        seller_email=checkout_item.get('seller_email', ''),
                        new_quantity=new_v_stock,
                        threshold=v_threshold,
                        product_name=checkout_item['name'],
                        variant_info={'color': order_color, 'size': order_size},
                    )

            # -- Insert order into Supabase orders table -------------------
            item_product_price = float(frontend_item.get('itemTotal', 0))
            item_shipping_fee  = float(checkout_item.get('shipping_fee', 50))

            # Resolve delivery address
            delivery_address = session.get('address', '')
            if not delivery_address:
                try:
                    addr_res = sb_admin.table('users') \
                        .select('house_street, barangay, city, province, region, zip_code') \
                        .eq('email', user_email).limit(1).execute()
                    if addr_res.data:
                        u = addr_res.data[0]
                        parts = [u.get('house_street',''), u.get('barangay',''),
                                 u.get('city',''), u.get('province',''),
                                 u.get('region',''), u.get('zip_code','')]
                        delivery_address = ', '.join(p for p in parts if p)
                except Exception:
                    pass

            order_row = {
                'name':           checkout_item['name'],
                'quantity':       order_qty,
                'total_price':    item_product_price,
                'payment_method': payment_method,
                'status':         'Pending',
                'email':          user_email,
                'address':        delivery_address,
                'seller_email':   checkout_item.get('seller_email', ''),
                'image':          checkout_item.get('image', ''),
                'variations':     checkout_item.get('variations', ''),
                'size':           checkout_item.get('size', ''),
                'product_id':     product_id_int,
                'shipping_fee':   item_shipping_fee,
            }
            order_res = sb_admin.table('orders').insert(order_row).execute()
            new_order_id = (order_res.data or [{}])[0].get('id')

            print(f"? Order inserted id={new_order_id} item={checkout_item['name']} price={item_product_price}")

            # -- Record promotion usage (non-fatal) ------------------------
            if product_id_int and checkout_item.get('seller_email'):
                try:
                    p_price_res = sb_admin.table('products').select('price').eq('id', product_id_int).limit(1).execute()
                    orig_price = float((p_price_res.data or [{}])[0].get('price', 0))
                    active_promo = get_active_promotions_for_product(
                        str(product_id_int), checkout_item['seller_email'], '')
                    if active_promo and new_order_id:
                        curr_price = float(checkout_item.get('price', 0))
                        disc_per_item = max(0.0, orig_price - curr_price)
                        total_disc = disc_per_item * order_qty
                        if active_promo['type'] == 'free_shipping' and total_disc == 0:
                            total_disc = 50.0
                        if total_disc > 0 or active_promo['type'] in ['free_shipping', 'buy_one_get_one']:
                            sb_admin.table('promotion_usage').insert({
                                'promotion_id':    active_promo['id'],
                                'customer_email':  user_email,
                                'order_id':        new_order_id,
                                'product_id':      str(product_id_int),
                                'discount_applied': total_disc,
                            }).execute()
                except Exception as promo_err:
                    print(f"?? Promotion usage record failed (non-fatal): {promo_err}")

            # -- Remove from checkout --------------------------------------
            sb_admin.table('checkout') \
                .delete() \
                .eq('id', checkout_item['id']) \
                .eq('email', user_email) \
                .execute()

            # -- Remove from cart by exact cart row ID ---------------------
            try:
                sb_admin.table('cart') \
                    .delete() \
                    .eq('id', checkout_item['id']) \
                    .eq('email', user_email) \
                    .execute()
            except Exception as cart_del_err:
                print(f"⚠️ cart delete failed (non-fatal): {cart_del_err}")

        # -- 3. Send seller notifications (non-fatal) ----------------------
        seller_orders: dict = {}
        for checkout_item in checkout_items:
            fe = frontend_item_map.get(str(checkout_item['id']), {})
            s_email = checkout_item.get('seller_email', '')
            if s_email not in seller_orders:
                seller_orders[s_email] = []
            seller_orders[s_email].append({
                'name':           checkout_item['name'],
                'quantity':       checkout_item.get('quantity', 1),
                'total_price':    fe.get('itemTotal', 0),
                'variations':     checkout_item.get('variations', ''),
                'size':           checkout_item.get('size', ''),
                'email':          user_email,
                'address':        session.get('address', ''),
                'payment_method': payment_method,
            })

        for s_email, orders in seller_orders.items():
            try:
                send_order_notification_email(s_email, orders)
            except Exception as e:
                print(f"?? Email to {s_email} failed (non-fatal): {e}")
            try:
                _create_order_notification_supabase(s_email, orders)
            except Exception as e:
                print(f"?? Notification for {s_email} failed (non-fatal): {e}")

        session.pop('checkout_source', None)
        session.pop('checkout_items', None)
        session.modified = True
        return jsonify({"success": True})

    except Exception as e:
        print(f"? confirm_order error: {e}")
        import traceback; traceback.print_exc()
        return jsonify({"success": False, "error": str(e)})

@app.route('/orders')
def orders():
    user_email = session.get('email')
    if not user_email:
        return redirect(url_for('login'))

    user_name = get_user_name_from_session(default='User')
    orders = []

    # -- PRIMARY: Supabase --------------------------------------------------
    try:
        orders_res = sb_admin.table('orders') \
            .select('*') \
            .eq('email', user_email) \
            .order('date', desc=True) \
            .execute()
        raw_orders = orders_res.data or []

        # Collect seller emails for batch lookup
        seller_emails = list({o.get('seller_email', '') for o in raw_orders if o.get('seller_email')})
        seller_map = {}
        if seller_emails:
            try:
                sr = sb_admin.table('users') \
                    .select('email, first_name, last_name, business_name, profile_picture') \
                    .in_('email', seller_emails) \
                    .execute()
                for s in (sr.data or []):
                    seller_map[s['email']] = s
            except Exception:
                pass

        # Collect product ids for review check
        order_ids = [o['id'] for o in raw_orders if o.get('id')]
        reviewed_order_ids = set()
        if order_ids:
            try:
                rv = sb_admin.table('reviews') \
                    .select('order_id') \
                    .eq('customer_email', user_email) \
                    .in_('order_id', order_ids) \
                    .execute()
                reviewed_order_ids = {r['order_id'] for r in (rv.data or [])}
            except Exception:
                pass

        import datetime as _dt
        for o in raw_orders:
            # Parse date
            raw_date = o.get('date')
            if raw_date:
                try:
                    if isinstance(raw_date, str):
                        o['date'] = _dt.datetime.fromisoformat(raw_date.replace('Z', '+00:00'))
                    else:
                        o['date'] = raw_date
                except Exception:
                    o['date'] = None
            else:
                o['date'] = None

            # Numeric fields
            o['total_price']    = float(o.get('total_price') or 0)
            o['original_price'] = o['total_price']
            o['quantity']       = int(o.get('quantity') or 1)
            o['shipping_fee']   = float(o.get('shipping_fee') or 50)

            # Seller info
            seller = seller_map.get(o.get('seller_email', ''), {})
            o['seller_business_name']  = seller.get('business_name') or ''
            o['seller_full_name']      = f"{seller.get('first_name','') or ''} {seller.get('last_name','') or ''}".strip()
            o['seller_profile_picture'] = seller.get('profile_picture') or ''

            # Rider id (use rider_email as identifier for chat)
            o['rider_id'] = o.get('rider_email') or ''

            # Review check
            o['has_review'] = o['id'] in reviewed_order_ids

            # Promotion fields
            o['promotion_type'] = o.get('promotion_type') or ''
            o['promotion_name'] = o.get('promotion_name') or ''

            # Image � resolve to displayable URL
            raw_img = (o.get('image') or '').strip()
            if raw_img.startswith('http://') or raw_img.startswith('https://'):
                o['image_url'] = raw_img
                o['image']     = ''          # don't use static path
            else:
                o['image_url'] = ''
                o['image']     = raw_img     # legacy filename

        orders = raw_orders
        print(f"? orders route Supabase: {len(orders)} orders for {user_email}")

    except Exception as sb_err:
        print(f"?? orders route Supabase failed: {sb_err}")

        # -- FALLBACK: MySQL ------------------------------------------------
        # MySQL orders fallback removed
        orders = []

    return render_template('orders.html', orders=orders,
                           user_name=user_name,
                           user_email=user_email)

@app.route('/mark_as_received/<int:order_id>', methods=['POST'])
def mark_as_received(order_id):
    user_email = session.get('email')
    try:
        ord_res = sb_admin.table('orders').select('id, product_id, quantity, seller_email, name').eq('id', order_id).eq('email', user_email).eq('status', 'Delivered').limit(1).execute()
        if not ord_res.data:
            flash("Order not found or not eligible for confirmation.", "error")
            return redirect(url_for('orders'))
        order = ord_res.data[0]
        sb_admin.table('orders').update({'status': 'Completed', 'received_at': datetime.now().isoformat()}).eq('id', order_id).execute()
        try:
            sb_admin.table('notifications').insert({'seller_email': order['seller_email'], 'message': f"Order #{order_id} ({order['name']}) has been confirmed as received by the buyer.", 'type': 'order_received', 'is_read': False}).execute()
        except Exception:
            pass
        flash("Order confirmed as received! Thank you for your purchase.", "success")
    except Exception as e:
        flash(f"An error occurred: {str(e)}", "error")
    return redirect(url_for('orders'))


@app.route('/submit_review/<int:order_id>', methods=['POST'])
def submit_review(order_id):
    user_email  = session.get('email')
    rating      = request.form.get('rating')
    review_text = request.form.get('review_text')
    if not rating or not review_text:
        flash('Please provide both a rating and review text.', 'error')
        return redirect(url_for('orders'))
    try:
        ord_res = sb_admin.table('orders').select('product_id, seller_email, name').eq('id', order_id).eq('email', user_email).eq('status', 'Completed').limit(1).execute()
        if not ord_res.data:
            flash('Order not found or not eligible for review.', 'error')
            return redirect(url_for('orders'))
        order = ord_res.data[0]
        product_id = order.get('product_id')
        seller_email = order.get('seller_email', '')
        # Check for existing review
        existing = sb_admin.table('reviews').select('id').eq('order_id', order_id).eq('customer_email', user_email).limit(1).execute()
        if existing.data:
            flash('You have already submitted a review for this order.', 'info')
            return redirect(url_for('orders'))
        sb_admin.table('reviews').insert({
            'order_id': order_id, 'product_id': product_id,
            'customer_email': user_email, 'seller_email': seller_email,
            'rating': int(rating), 'review_text': review_text,
        }).execute()
        # Update product rating
        if product_id:
            try:
                rv = sb_admin.table('reviews').select('rating').eq('product_id', product_id).execute()
                ratings = [r['rating'] for r in (rv.data or [])]
                if ratings:
                    avg = round(sum(ratings) / len(ratings), 2)
                    sb_admin.table('products').update({'rating': avg}).eq('id', product_id).execute()
            except Exception:
                pass
        # Notify seller
        try:
            create_review_notification(seller_email, {'name': order.get('name','')}, rating, review_text, user_email, order_id)
        except Exception:
            pass
        # Notify buyer
        try:
            sb_admin.table('buyer_notifications').insert({'buyer_email': user_email, 'message': f"Your review for order #{order_id} has been submitted successfully.", 'type': 'review', 'is_read': False, 'order_id': order_id}).execute()
        except Exception:
            pass
        flash('Review submitted successfully!', 'success')
    except Exception as e:
        flash(f'Error submitting review: {str(e)}', 'error')
    return redirect(url_for('orders'))


@app.route('/report_issue/<int:order_id>', methods=['POST'])
def report_issue(order_id):
    user_email        = session.get('email')
    report_against    = request.form.get('report_against')
    issue_type        = request.form.get('issue_type')
    issue_description = request.form.get('issue_description')
    if not report_against or not issue_type or not issue_description:
        flash('Please provide all required fields.', 'error')
        return redirect(url_for('orders'))
    try:
        ord_res = sb_admin.table('orders').select('id, seller_email, rider_email, name').eq('id', order_id).limit(1).execute()
        if not ord_res.data:
            flash('Order not found.', 'error')
            return redirect(url_for('orders'))
        order = ord_res.data[0]
        reported_against_email = order.get('seller_email','') if report_against == 'seller' else order.get('rider_email','') if report_against == 'delivery' else ''
        ins = sb_admin.table('order_issues').insert({
            'order_id': order_id, 'reporter_role': 'buyer', 'reporter_email': user_email,
            'reported_against_role': report_against, 'reported_against_email': reported_against_email,
            'issue_type': issue_type, 'issue_description': issue_description, 'status': 'pending',
        }).execute()
        issue_id = ins.data[0]['id'] if ins.data else None
        # Notify seller if reported against them
        if report_against == 'seller' and order.get('seller_email'):
            try:
                create_issue_notification(order['seller_email'], {'id': order_id, 'name': order.get('name','')}, report_against, issue_type, issue_description, user_email, issue_id)
            except Exception:
                pass
        flash('Issue report submitted successfully. Admin will review your report.', 'success')
    except Exception as e:
        flash(f'An error occurred while reporting the issue: {str(e)}', 'error')
    return redirect(url_for('orders'))


def send_cancellation_email(seller_email, order_name, reason, customer_email):
    msg = Message(
        'Order Cancellation Notification',
        sender=app.config["MAIL_DEFAULT_SENDER"],
        recipients=[seller_email]
    )
    msg.body = f"""
    The order '{order_name}' has been canceled.

    Cancellation Reason: {reason}

    Customer Email: {customer_email}
    """
    try:
        mail.send(msg)
    except Exception as e:
        print(f"Error sending email: {e}")

@app.route('/delete_order/<int:order_id>', methods=['POST'])
def delete_order(order_id):
    user_email = session.get('email')
    reason = request.form.get('reason', '').strip()

    if not user_email:
        return redirect(url_for('login'))

    try:
        # -- Fetch order from Supabase ------------------------------------
        order_res = sb_admin.table('orders') \
            .select('id, seller_email, name, email, status, product_id, quantity, variations, size') \
            .eq('id', order_id) \
            .eq('email', user_email) \
            .execute()

        if not order_res.data:
            flash('Order not found or you are not authorized to cancel this order.', 'danger')
            return redirect(url_for('orders'))

        order = order_res.data[0]
        current_status = (order.get('status') or '').lower()

        if current_status not in ['pending', 'confirmed']:
            flash('This order cannot be cancelled as it is already being processed or delivered.', 'warning')
            return redirect(url_for('orders'))

        # -- Restore product stock (best-effort) --------------------------
        product_id = order.get('product_id')
        order_qty  = int(order.get('quantity') or 1)
        if product_id:
            try:
                prod_res = sb_admin.table('products') \
                    .select('quantity, sold') \
                    .eq('id', product_id) \
                    .execute()
                if prod_res.data:
                    p = prod_res.data[0]
                    new_stock = int(p.get('quantity') or 0) + order_qty
                    new_sold  = max(0, int(p.get('sold') or 0) - order_qty)
                    sb_admin.table('products') \
                        .update({'quantity': new_stock, 'sold': new_sold}) \
                        .eq('id', product_id) \
                        .execute()
                    print(f"✅ Product {product_id} stock restored +{order_qty}")

                    # Also restore variant stock if color/size present
                    color = order.get('variations') or ''
                    size  = order.get('size') or ''
                    if color or size:
                        try:
                            vq = sb_admin.table('product_variants') \
                                .select('id, stock_quantity') \
                                .eq('product_id', product_id)
                            if color: vq = vq.eq('color', color)
                            if size:  vq = vq.eq('size', size)
                            vq_res = vq.execute()
                            if vq_res.data:
                                v = vq_res.data[0]
                                sb_admin.table('product_variants') \
                                    .update({'stock_quantity': int(v.get('stock_quantity') or 0) + order_qty}) \
                                    .eq('id', v['id']) \
                                    .execute()
                        except Exception as ve:
                            print(f"⚠️ Variant stock restore failed (non-fatal): {ve}")
            except Exception as se:
                print(f"⚠️ Stock restore failed (non-fatal): {se}")

        # -- Update order status in Supabase ------------------------------
        sb_admin.table('orders') \
            .update({
                'status':              'Cancelled',
                'cancellation_reason': reason,
                'cancelled_at':        datetime.now().isoformat(),
            }) \
            .eq('id', order_id) \
            .eq('email', user_email) \
            .execute()

        print(f"✅ Order {order_id} cancelled via Supabase")

        # -- Notify seller (best-effort) ----------------------------------
        seller_email = order.get('seller_email', '')
        order_name   = order.get('name', '')
        try:
            send_cancellation_email(seller_email, order_name, reason, user_email)
        except Exception as e:
            print(f"⚠️ Cancellation email failed (non-fatal): {e}")
        try:
            _create_order_notification_supabase(seller_email, [{
                'name': order_name, 'quantity': order_qty,
                'total_price': 0, 'email': user_email,
                'address': '', 'payment_method': 'N/A',
            }])
        except Exception as e:
            print(f"⚠️ Cancellation notification failed (non-fatal): {e}")

        flash('Order cancelled successfully. The seller has been notified.', 'success')

    except Exception as e:
        print(f"❌ delete_order error: {e}")
        import traceback; traceback.print_exc()
        flash(f'Error cancelling order: {str(e)}', 'error')

    return redirect(url_for('orders'))

@app.route('/edit_user/<int:user_id>', methods=['GET', 'POST'])
def edit_user(user_id):
    if request.method == 'POST':
        update_data = {}
        for field, col in [('first_name','first_name'),('last_name','last_name'),
                           ('email','email'),('phone_number','phone'),
                           ('address','address'),('user_type','role')]:
            val = request.form.get(field)
            if val is not None:
                update_data[col] = val.lower() if col == 'role' else val
        sb_admin.table('users').update(update_data).eq('id', str(user_id)).execute()
        flash('User updated successfully!', 'success')
        return redirect(url_for('admin_users'))
    res = sb_admin.table('users').select('*').eq('id', str(user_id)).limit(1).execute()
    user = res.data[0] if res.data else {}
    return render_template('edit_user.html', user=user)

@app.route('/api/ban_user/<string:user_id>', methods=['POST'])
def ban_user(user_id):
    try:
        data = request.get_json()
        ban_reason   = data.get('ban_reason', '').strip()
        ban_duration = data.get('ban_duration', 'permanent')
        send_email   = data.get('send_email', True)

        if not ban_reason:
            return jsonify({'success': False, 'error': 'Ban reason is required'}), 400

        # Fetch user from Supabase
        res = sb_admin.table('users').select('id, email, first_name, last_name').eq('id', user_id).execute()
        if not res.data:
            return jsonify({'success': False, 'error': 'User not found!'})
        user = res.data[0]

        # Primary: ban via Supabase Auth (always works, no column dependency)
        try:
            sb_admin.auth.admin.update_user_by_id(user_id, {'ban_duration': '876600h'})
        except Exception as _auth_err:
            print(f'ban_user: auth ban failed ({_auth_err})')

        # Optional: update status columns in users table (may not exist)
        ban_end_date = None
        if ban_duration != 'permanent' and str(ban_duration).isdigit():
            ban_end_date = (datetime.utcnow() + timedelta(days=int(ban_duration))).isoformat()
        try:
            sb_admin.table('users').update({
                'status': 'banned',
                'ban_reason': ban_reason,
                'ban_end_date': ban_end_date
            }).eq('id', user_id).execute()
        except Exception as _col_err:
            print(f'ban_user: status column update skipped ({_col_err})')

        email_sent = False
        if send_email:
            try:
                duration_text = f"{ban_duration} days" if ban_duration != 'permanent' else 'permanently'
                msg = Message(
                    subject='Account Banned - MStyle',
                    recipients=[user['email']],
                    html=f'<p>Dear {user["first_name"]} {user["last_name"]},</p>'
                         f'<p>Your account has been banned {duration_text}.</p>'
                         f'<p><strong>Reason:</strong> {ban_reason}</p>'
                         f'<p>Contact stylemens2025@gmail.com if you believe this is an error.</p>'
                )
                mail.send(msg)
                email_sent = True
            except Exception as e:
                print(f'Error sending ban email: {e}')

        return jsonify({'success': True, 'message': 'User banned successfully!', 'email_sent': email_sent})

    except Exception as e:
        return jsonify({'success': False, 'error': f'Error: {str(e)}'})

@app.route('/api/suspend_user/<string:user_id>', methods=['POST'])
def suspend_user(user_id):
    try:
        data = request.get_json()
        suspend_reason   = data.get('suspend_reason', '').strip()
        suspend_duration = data.get('suspend_duration', '')
        send_email       = data.get('send_email', True)

        if not suspend_reason:
            return jsonify({'success': False, 'error': 'Suspension reason is required'}), 400
        if not suspend_duration or not str(suspend_duration).isdigit():
            return jsonify({'success': False, 'error': 'Valid suspension duration is required'}), 400

        res = sb_admin.table('users').select('id, email, first_name, last_name').eq('id', user_id).execute()
        if not res.data:
            return jsonify({'success': False, 'error': 'User not found!'})
        user = res.data[0]

        # Primary: ban via Supabase Auth for the suspension duration
        try:
            ban_hours = int(suspend_duration) * 24
            sb_admin.auth.admin.update_user_by_id(user_id, {'ban_duration': f'{ban_hours}h'})
        except Exception as _auth_err:
            print(f'suspend_user: auth ban failed ({_auth_err})')

        # Optional: update status columns in users table (may not exist)
        suspend_end_date = (datetime.utcnow() + timedelta(days=int(suspend_duration))).isoformat()
        try:
            sb_admin.table('users').update({
                'status': 'suspended',
                'ban_reason': suspend_reason,
                'ban_end_date': suspend_end_date
            }).eq('id', user_id).execute()
        except Exception as _col_err:
            print(f'suspend_user: status column update skipped ({_col_err})')

        email_sent = False
        if send_email:
            try:
                duration_text = f"{suspend_duration} day{'s' if int(suspend_duration) > 1 else ''}"
                msg = Message(
                    subject='Account Temporarily Suspended - MStyle',
                    recipients=[user['email']],
                    html=f'<p>Dear {user["first_name"]} {user["last_name"]},</p>'
                         f'<p>Your account has been suspended for {duration_text}.</p>'
                         f'<p><strong>Reason:</strong> {suspend_reason}</p>'
                         f'<p>Contact stylemens2025@gmail.com if you believe this is an error.</p>'
                )
                mail.send(msg)
                email_sent = True
            except Exception as e:
                print(f'Error sending suspension email: {e}')

        return jsonify({'success': True, 'message': 'User suspended successfully!', 'email_sent': email_sent})

    except Exception as e:
        return jsonify({'success': False, 'error': f'Error: {str(e)}'})

@app.route('/api/unban_user/<string:user_id>', methods=['POST'])
def unban_user(user_id):
    try:
        res = sb_admin.table('users').select('id, email, first_name, last_name').eq('id', user_id).execute()
        if not res.data:
            return jsonify({'success': False, 'error': 'User not found!'})
        user = res.data[0]

        # Primary: unban via Supabase Auth
        try:
            sb_admin.auth.admin.update_user_by_id(user_id, {'ban_duration': 'none'})
        except Exception as _auth_err:
            print(f'unban_user: auth unban failed ({_auth_err})')

        # Optional: update status columns in users table (may not exist)
        try:
            sb_admin.table('users').update({
                'status': 'active',
                'ban_reason': None,
                'ban_end_date': None
            }).eq('id', user_id).execute()
        except Exception as _col_err:
            print(f'unban_user: status column update skipped ({_col_err})')

        try:
            msg = Message(
                subject='Account Reinstated - MStyle',
                recipients=[user['email']],
                html=f'<p>Dear {user["first_name"]} {user["last_name"]},</p>'
                     '<p>Your MStyle account has been reinstated. You can now log in normally.</p>'
                     '<p>Thank you for your patience.</p>'
            )
            mail.send(msg)
        except Exception as e:
            print(f'Error sending unban email: {e}')

        return jsonify({'success': True, 'message': 'User unbanned successfully!'})

    except Exception as e:
        return jsonify({'success': False, 'error': f'Error: {str(e)}'})

@app.route('/archive_user/<string:user_id>', methods=['POST'])
def archive_user(user_id):
    try:
        res = sb_admin.table('users').select('*').eq('id', user_id).execute()
        if not res.data:
            return jsonify({'success': False, 'error': 'User not found!'})
        user = res.data[0]

        # 1. Save full user data into archived_users (store entire original row as JSON too)
        try:
            sb_admin.table('archived_users').insert({
                'user_id':       user_id,
                'first_name':    user.get('first_name'),
                'last_name':     user.get('last_name'),
                'email':         user.get('email'),
                'phone':         user.get('phone') or user.get('phone_number') or '',
                'house_street':  user.get('house_street') or '',
                'barangay':      user.get('barangay') or '',
                'city':          user.get('city') or '',
                'province':      user.get('province') or '',
                'region':        user.get('region') or '',
                'zip_code':      user.get('zip_code') or '',
                'role':          user.get('role') or 'buyer',
                'valid_id_path': user.get('valid_id_path'),
                'archived_by':   session.get('email', 'admin'),
            }).execute()
        except Exception as insert_err:
            print(f'archive_user: could not insert into archived_users ({insert_err})')
            return jsonify({'success': False, 'error': f'Archive table error: {str(insert_err)}'})

        # 2. Delete the row from the users table so it disappears from User Management
        try:
            sb_admin.table('users').delete().eq('id', user_id).execute()
        except Exception as del_err:
            # If delete fails, roll back the archive record and report the error
            try:
                sb_admin.table('archived_users').delete().eq('user_id', user_id).execute()
            except Exception:
                pass
            return jsonify({'success': False, 'error': f'Could not remove user from users table: {str(del_err)}'})

        # 3. Delete the Supabase Auth account entirely so the email is free to re-register
        try:
            sb_admin.auth.admin.delete_user(user_id)
            print(f'archive_user: auth account deleted for user_id={user_id}')
        except Exception as del_auth_err:
            # Non-fatal � profile row is already deleted, login will fail anyway
            print(f'archive_user: auth delete failed (non-fatal): {del_auth_err}')

        return jsonify({'success': True, 'message': 'User archived successfully!'})

    except Exception as e:
        return jsonify({'success': False, 'error': f'Error: {str(e)}'})


@app.route('/api/restore_archived_user/<string:archive_id>', methods=['POST'])
def restore_archived_user(archive_id):
    """Re-insert the user row into users table and remove from archived_users."""
    if 'user_id' not in session or session.get('user_type') != 'Admin':
        return jsonify({'success': False, 'error': 'Access denied'}), 403
    try:
        # Get the archive record
        res = sb_admin.table('archived_users').select('*').eq('id', archive_id).execute()
        if not res.data:
            return jsonify({'success': False, 'error': 'Archive record not found'})
        record = res.data[0]
        original_user_id = record.get('user_id')
        email = record.get('email', '')

        # -- Ensure the auth account exists -----------------------------------
        # Since archive_user now deletes the auth account, we may need to recreate it.
        restored_uid = original_user_id
        try:
            auth_user = sb_admin.auth.admin.get_user_by_id(original_user_id)
            # Auth account still exists � unban it
            sb_admin.auth.admin.update_user_by_id(original_user_id, {'ban_duration': 'none'})
            print(f'restore_archived_user: auth account unbanned for {email}')
        except Exception:
            # Auth account was deleted � create a new one with the same email
            try:
                import secrets
                temp_password = secrets.token_urlsafe(16)
                new_auth = sb_admin.auth.admin.create_user({
                    'email':            email,
                    'password':         temp_password,
                    'email_confirm':    True,
                })
                restored_uid = new_auth.user.id if new_auth.user else original_user_id
                print(f'restore_archived_user: new auth account created for {email}, uid={restored_uid}')
                # Send password reset so the user can set a new password
                try:
                    sb.auth.reset_password_email(email)
                    print(f'restore_archived_user: password reset email sent to {email}')
                except Exception as reset_err:
                    print(f'restore_archived_user: password reset email failed (non-fatal): {reset_err}')
            except Exception as create_err:
                print(f'restore_archived_user: could not create auth account: {create_err}')
                # Continue anyway � profile row will be restored

        # -- Re-insert the user profile row -----------------------------------
        existing = sb_admin.table('users').select('id').eq('id', restored_uid).execute()
        if not existing.data:
            sb_admin.table('users').insert({
                'id':           restored_uid,
                'first_name':   record.get('first_name'),
                'last_name':    record.get('last_name'),
                'email':        email,
                'phone':        record.get('phone') or '',
                'house_street': record.get('house_street') or '',
                'barangay':     record.get('barangay') or '',
                'city':         record.get('city') or '',
                'province':     record.get('province') or '',
                'region':       record.get('region') or '',
                'zip_code':     record.get('zip_code') or '',
                'role':         record.get('role') or 'buyer',
                'valid_id_path': record.get('valid_id_path'),
                'status':       'active',
                'ban_reason':   None,
                'ban_end_date': None,
            }).execute()
        else:
            sb_admin.table('users').update({
                'status':       'active',
                'ban_reason':   None,
                'ban_end_date': None,
            }).eq('id', restored_uid).execute()

        # Remove the archive record
        sb_admin.table('archived_users').delete().eq('id', archive_id).execute()

        return jsonify({
            'success': True,
            'message': 'User restored successfully! A password reset email has been sent to the user.'
        })
    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)})


@app.route('/api/delete_archived_user/<string:archive_id>', methods=['POST'])
def delete_archived_user(archive_id):
    """Permanently delete an archived_users record and its Supabase auth account."""
    if 'user_id' not in session or session.get('user_type') != 'Admin':
        return jsonify({'success': False, 'error': 'Access denied'}), 403
    try:
        # Get the original user_id before deleting the record
        res = sb_admin.table('archived_users').select('user_id').eq('id', archive_id).execute()
        original_user_id = res.data[0]['user_id'] if res.data else None

        # Delete the archive record
        sb_admin.table('archived_users').delete().eq('id', archive_id).execute()

        # Delete the Supabase auth account so the email is free to re-register
        if original_user_id:
            try:
                sb_admin.auth.admin.delete_user(original_user_id)
                print(f'delete_archived_user: auth account deleted for user_id={original_user_id}')
            except Exception as del_auth_err:
                # Non-fatal � archive record is already deleted
                print(f'delete_archived_user: auth delete failed (non-fatal): {del_auth_err}')

        return jsonify({'success': True, 'message': 'Archive record deleted.'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/update_cart_quantity/<int:item_id>', methods=['POST'])
def update_cart_quantity(item_id):
    try:
        data = request.json
        new_quantity = data.get('quantity')
        user_email = session.get('email')

        if not new_quantity:
            return jsonify({'error': 'No quantity provided'}), 400

        # -- PRIMARY: Supabase ---------------------------------------------
        try:
            sb_admin.table('cart') \
                .update({'quantity': int(new_quantity)}) \
                .eq('id', item_id) \
                .eq('email', user_email) \
                .execute()
            return jsonify({'success': True})
        except Exception as sb_err:
            print(f"?? Supabase update_cart_quantity failed: {sb_err}")



    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/cart/update_specification', methods=['POST'])
def update_cart_specification():
    if 'email' not in session:
        return jsonify({'error': 'Please login first'}), 401

    try:
        data = request.get_json()
        item_id = data.get('item_id')
        spec_type = data.get('type')  # 'color' or 'size'
        new_value = data.get('value')
        user_email = session['email']

        if not all([item_id, spec_type, new_value]):
            return jsonify({'error': 'Missing required data'}), 400

        if spec_type not in ('color', 'size'):
            return jsonify({'error': 'Invalid specification type'}), 400

        # -- PRIMARY: Supabase ----------------------------------------------
        try:
            # Verify the item belongs to the user
            check_res = sb_admin.table('cart') \
                .select('id') \
                .eq('id', int(item_id)) \
                .eq('email', user_email) \
                .execute()

            if not check_res.data:
                return jsonify({'error': 'Item not found or access denied'}), 404

            field = 'variations' if spec_type == 'color' else 'size'
            update_data = {field: new_value}

            # When color changes, also update the cart image to the color-matched image
            if spec_type == 'color':
                try:
                    prod_res = sb_admin.table('cart').select('product_id').eq('id', int(item_id)).limit(1).execute()
                    if prod_res.data:
                        product_id = prod_res.data[0].get('product_id')
                        img_res = sb_admin.table('products').select('image, image_colors').eq('id', product_id).limit(1).execute()
                        if img_res.data:
                            p = img_res.data[0]
                            color_map = _parse_image_colors_dict(p.get('image_colors', ''), p.get('image', ''))
                            color_lower = new_value.lower().strip()
                            matched_img = color_map.get(color_lower) or color_map.get(new_value)
                            if not matched_img:
                                # fallback: filename match
                                for img in (p.get('image') or '').split(','):
                                    img = img.strip()
                                    if color_lower in img.lower():
                                        matched_img = img
                                        break
                            if matched_img:
                                update_data['image'] = matched_img
                except Exception as img_err:
                    print(f'[update_specification] image update skipped: {img_err}')

            sb_admin.table('cart') \
                .update(update_data) \
                .eq('id', int(item_id)) \
                .eq('email', user_email) \
                .execute()

            print(f"? update_specification Supabase: item {item_id} {spec_type}={new_value}")
        except Exception as sb_err:
            print(f"?? update_specification Supabase failed: {sb_err}")
            return jsonify({'error': 'Failed to update specification'}), 500

        # MySQL cart spec mirror removed

        return jsonify({'success': True, 'message': f'{spec_type.title()} updated successfully',
                        'new_image': update_data.get('image')})

    except Exception as e:
        print(f"Error updating cart specification: {str(e)}")
        return jsonify({'error': 'Failed to update specification'}), 500

@app.route('/cart/get_product_variations/<int:item_id>', methods=['GET'])
def get_product_variations(item_id):
    if 'email' not in session:
        return jsonify({'error': 'Please login first'}), 401

    try:
        user_email = session['email']

        # -- PRIMARY: Supabase ----------------------------------------------
        try:
            # Get cart item ? product_id
            cart_res = sb_admin.table('cart') \
                .select('product_id') \
                .eq('id', item_id) \
                .eq('email', user_email) \
                .execute()

            if not cart_res.data:
                return jsonify({'error': 'Cart item not found'}), 404

            product_id = cart_res.data[0]['product_id']

            # Get distinct colors from variant_inventory (only stocked variants)
            vi_res = sb_admin.table('variant_inventory') \
                .select('color, stock_quantity') \
                .eq('product_id', product_id) \
                .execute()

            vi_rows = vi_res.data or []

            # Build unique color list preserving order, skip colors with 0 stock
            seen = set()
            variations = []
            for row in vi_rows:
                c = (row.get('color') or '').strip()
                if c and c not in seen:
                    seen.add(c)
                    variations.append(c)

            # Fallback: if variant_inventory has no rows, read from products.variations
            if not variations:
                prod_res = sb_admin.table('products') \
                    .select('variations') \
                    .eq('id', product_id) \
                    .execute()
                if prod_res.data:
                    variations_str = prod_res.data[0].get('variations') or ''
                    variations = [v.strip() for v in variations_str.split(',') if v.strip()]

            print(f"? get_product_variations Supabase: product {product_id} ? {variations}")
            return jsonify({'success': True, 'variations': variations})

        except Exception as sb_err:
            print(f"?? get_product_variations Supabase failed: {sb_err}")



    except Exception as e:
        print(f"Error getting product variations: {str(e)}")
        return jsonify({'error': 'Failed to get product variations'}), 500

@app.route('/cart/get_product_images/<int:item_id>', methods=['GET'])
def get_product_images(item_id):
    if 'email' not in session:
        return jsonify({'error': 'Please login first'}), 401

    try:
        user_email = session['email']

        # -- PRIMARY: Supabase ----------------------------------------------
        try:
            cart_res = sb_admin.table('cart') \
                .select('product_id') \
                .eq('id', item_id) \
                .eq('email', user_email) \
                .execute()

            if not cart_res.data:
                return jsonify({'error': 'Cart item not found'}), 404

            product_id = cart_res.data[0]['product_id']

            prod_res = sb_admin.table('products') \
                .select('image, image_colors, variations') \
                .eq('id', product_id) \
                .execute()

            if not prod_res.data:
                return jsonify({'error': 'Product not found'}), 404

            product = prod_res.data[0]

            # Parse images � may be comma-separated filenames or full URLs
            images_raw = product.get('image') or ''
            raw_list = [img.strip() for img in images_raw.split(',') if img.strip()]

            # image_colors mapping: {"Black": "https://...", ...}
            image_colors = {}
            ic_raw = product.get('image_colors')
            try:
                import json as _json
                if ic_raw:
                    if isinstance(ic_raw, str):
                        ic_data = _json.loads(ic_raw)
                    else:
                        ic_data = ic_raw
                    if isinstance(ic_data, dict):
                        for color, url in ic_data.items():
                            image_colors[color] = url
            except Exception:
                pass

            # Resolve each image to a full URL using the helper
            images = list(raw_list)  # images are already full URLs from Supabase Storage

            # Parse variations
            variations_str = product.get('variations') or ''
            variations = [v.strip() for v in variations_str.split(',') if v.strip()]

            print(f"? get_product_images Supabase: product {product_id} ? {len(images)} images")
            return jsonify({
                'success': True,
                'images': images,
                'image_colors': image_colors,
                'variations': variations,
            })

        except Exception as sb_err:
            print(f"?? get_product_images Supabase failed: {sb_err}")



    except Exception as e:
        print(f"Error getting product images: {str(e)}")
        return jsonify({'error': 'Failed to get product images'}), 500

@app.route('/cart/get_product_sizes/<int:item_id>', methods=['GET'])
def get_product_sizes(item_id):
    if 'email' not in session:
        return jsonify({'error': 'Please login first'}), 401

    try:
        user_email = session['email']

        # -- PRIMARY: Supabase ----------------------------------------------
        try:
            cart_res = sb_admin.table('cart') \
                .select('product_id, variations') \
                .eq('id', item_id) \
                .eq('email', user_email) \
                .execute()

            if not cart_res.data:
                return jsonify({'error': 'Cart item not found'}), 404

            product_id = cart_res.data[0]['product_id']
            current_color = (cart_res.data[0].get('variations') or '').strip()

            # Get sizes from variant_inventory for the current color (stocked only)
            vi_query = sb_admin.table('variant_inventory') \
                .select('size, stock_quantity') \
                .eq('product_id', product_id)

            if current_color:
                vi_query = vi_query.eq('color', current_color)

            vi_res = vi_query.execute()
            vi_rows = vi_res.data or []

            # Build unique size list
            seen = set()
            sizes = []
            for row in vi_rows:
                s = (row.get('size') or '').strip()
                if s and s not in seen:
                    seen.add(s)
                    sizes.append(s)

            # Fallback: read from products.sizes if variant_inventory empty
            if not sizes:
                prod_res = sb_admin.table('products') \
                    .select('sizes') \
                    .eq('id', product_id) \
                    .execute()
                if prod_res.data:
                    sizes_str = prod_res.data[0].get('sizes') or ''
                    sizes = [s.strip() for s in sizes_str.split(',') if s.strip()]
                    return jsonify({'success': True, 'sizes': ','.join(sizes)})

            print(f"? get_product_sizes Supabase: product {product_id} color={current_color!r} ? {sizes}")
            return jsonify({'success': True, 'sizes': ','.join(sizes)})

        except Exception as sb_err:
            print(f"?? get_product_sizes Supabase failed: {sb_err}")



    except Exception as e:
        print(f"Error getting product sizes: {str(e)}")
        return jsonify({'error': 'Failed to get product sizes'}), 500

@app.route('/api/cart-count', methods=['GET'])
def get_cart_count():
    if 'email' not in session:
        return jsonify({'success': False, 'count': 0})

    user_email = session['email']
    try:
        res = sb_admin.table('cart') \
            .select('id', count='exact') \
            .eq('email', user_email) \
            .execute()

        total_count = res.count or 0
        return jsonify({'success': True, 'count': total_count})

    except Exception as e:
        print(f'[cart-count] error: {e}')
        return jsonify({'success': True, 'count': 0})

@app.route('/api/cart-items', methods=['GET'])
def get_cart_items():
    if 'email' not in session:
        return jsonify({'success': False, 'error': 'Not logged in', 'items': [], 'total': 0})

    user_email = session['email']
    try:
        res = sb_admin.table('cart') \
            .select('id, name, price, quantity, variations, size, image, product_id') \
            .eq('email', user_email) \
            .order('id', desc=True) \
            .execute()

        cart_rows = res.data or []

        # Batch-fetch product images for color matching
        product_ids = list({item.get('product_id') for item in cart_rows if item.get('product_id')})
        prod_img_map = {}
        if product_ids:
            try:
                pr = sb_admin.table('products').select('id, image, image_colors').in_('id', product_ids).execute()
                for p in (pr.data or []):
                    prod_img_map[p['id']] = {'image': p.get('image',''), 'image_colors': p.get('image_colors','')}
            except Exception:
                pass

        total_amount = 0
        processed_items = []

        for item in cart_rows:
            price    = float(item.get('price') or 0)
            quantity = int(item.get('quantity') or 1)
            total_amount += price * quantity

            cart_image = (item.get('image') or '').strip()
            pid = item.get('product_id')
            selected_color = (item.get('variations') or '').strip().lower()

            # Resolve color-matched image
            image_url = ''
            if cart_image.startswith('http://') or cart_image.startswith('https://'):
                image_url = cart_image
            elif pid and pid in prod_img_map:
                prod = prod_img_map[pid]
                color_map = _parse_image_colors_dict(prod.get('image_colors',''), prod.get('image',''))
                matched = color_map.get(selected_color) if selected_color else None
                if not matched and selected_color:
                    for k, v in color_map.items():
                        if selected_color in k or k in selected_color:
                            matched = v; break
                if matched:
                    image_url = matched if matched.startswith('http') else f"https://vydcnhmgqovketjqvpoe.supabase.co/storage/v1/object/public/product-images/products/{matched.split('/')[-1]}"
                elif prod.get('image'):
                    first_img = prod['image'].split(',')[0].strip()
                    image_url = first_img if first_img.startswith('http') else f"https://vydcnhmgqovketjqvpoe.supabase.co/storage/v1/object/public/product-images/products/{first_img.split('/')[-1]}"
            elif cart_image:
                image_url = f"https://vydcnhmgqovketjqvpoe.supabase.co/storage/v1/object/public/product-images/products/{cart_image.split('/')[-1]}"

            processed_items.append({
                'id':          item['id'],
                'name':        item.get('name', ''),
                'price':       price,
                'quantity':    quantity,
                'total_price': price * quantity,
                'color':       item.get('variations'),
                'size':        item.get('size'),
                'image_url':   image_url,
                'product_id':  pid,
            })

        return jsonify({'success': True, 'items': processed_items, 'total': total_amount, 'count': len(processed_items)})

    except Exception as e:
        print(f'[cart-items] error: {e}')
        return jsonify({'success': True, 'items': [], 'total': 0, 'count': 0})

@app.route('/remove_from_cart', methods=['POST'])
def remove_from_cart():
    if 'email' not in session:
        return jsonify({'success': False, 'error': 'Not logged in'})
    try:
        data = request.get_json()
        item_id = data.get('item_id')
        user_email = session['email']
        if not item_id:
            return jsonify({'success': False, 'error': 'Item ID is required'})
        res = sb_admin.table('cart').delete().eq('id', item_id).eq('email', user_email).execute()
        if res.data:
            return jsonify({'success': True, 'message': 'Item removed from cart'})
        return jsonify({'success': False, 'error': 'Item not found or not authorized'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/clear_cart', methods=['POST'])
def clear_cart():
    if 'email' not in session:
        return jsonify({'success': False, 'error': 'Not logged in'})
    try:
        user_email = session['email']
        res = sb_admin.table('cart').delete().eq('email', user_email).execute()
        deleted_count = len(res.data) if res.data else 0
        return jsonify({'success': True, 'message': 'Cart cleared successfully', 'deleted_count': deleted_count})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/clear_checkout', methods=['POST'])
def clear_checkout():
    try:
        session.pop('checkout_items', None)
        session.pop('checkout_source', None)
        return jsonify(success=True)
    except Exception as e:
        return jsonify(success=False, error=str(e)), 500

@app.route('/update_address', methods=['POST'])
def update_address():
    if 'email' not in session:
        return jsonify({'success': False, 'error': 'Please log in to update address'}), 401

    try:
        data = request.get_json()
        house_street = (data.get('house_street') or '').strip()
        barangay     = (data.get('barangay')     or '').strip()
        city         = (data.get('city')         or '').strip()
        province     = (data.get('province')     or '').strip()
        region       = (data.get('region')       or '').strip()
        zip_code     = (data.get('zip_code')     or '').strip()

        if not city:
            return jsonify({'success': False, 'error': 'City is required'}), 400

        user_email = session['email']

        # -- PRIMARY: Supabase ----------------------------------------------
        try:
            sb_admin.table('users').update({
                'house_street': house_street,
                'barangay':     barangay,
                'city':         city,
                'province':     province,
                'region':       region,
                'zip_code':     zip_code,
            }).eq('email', user_email).execute()
        except Exception as sb_err:
            print(f"?? update_address Supabase failed: {sb_err}")
            return jsonify({'success': False, 'error': 'Failed to save address'}), 500

        # Build joined address for session
        joined = ', '.join(filter(None, [house_street, barangay, city, province, region, zip_code]))
        session['address'] = joined
        session.modified = True



        return jsonify({'success': True, 'message': 'Address saved successfully'})

    except Exception as e:
        return jsonify({'success': False, 'error': f'An error occurred: {str(e)}'}), 500


@app.route('/api/product/<int:product_id>/variant-stock')
def get_product_variant_stock(product_id):
    """API: get variant inventory stock for a product (used by view_product page)."""
    try:
        vi_res = sb_admin.table('variant_inventory') \
            .select('color, size, stock_quantity, low_stock_threshold') \
            .eq('product_id', product_id) \
            .execute()
        variants = vi_res.data or []

        # If no variant_inventory rows, fall back to product.quantity
        if not variants:
            prod_res = sb_admin.table('products').select('quantity, variations, sizes').eq('id', product_id).limit(1).execute()
            if prod_res.data:
                p = prod_res.data[0]
                total_qty = int(p.get('quantity') or 0)
                colors = [c.strip() for c in (p.get('variations') or '').split(',') if c.strip()]
                sizes  = [s.strip() for s in (p.get('sizes') or '').split(',') if s.strip()]
                # Create synthetic variants so the UI doesn't show everything as out of stock
                for color in colors:
                    for size in sizes:
                        variants.append({
                            'color': color,
                            'size': size,
                            'stock_quantity': total_qty,
                            'low_stock_threshold': 5,
                        })
                if not colors and not sizes:
                    variants.append({
                        'color': '',
                        'size': '',
                        'stock_quantity': total_qty,
                        'low_stock_threshold': 5,
                    })

        return jsonify({'success': True, 'variants': variants})
    except Exception as e:
        print(f"get_product_variant_stock error: {e}")
        return jsonify({'success': False, 'error': str(e), 'variants': []}), 500


@app.route('/api/product/<int:product_id>')
def get_product_details(product_id):
    """API: product details for modal — Supabase"""
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Not logged in'}), 401
    try:
        prod_res = sb_admin.table('products').select('*').eq('id', product_id).limit(1).execute()
        if not prod_res.data:
            return jsonify({'success': False, 'error': 'Product not found'}), 404

        product = dict(prod_res.data[0])

        # Attach seller name
        seller_email = product.get('seller_email', '')
        if seller_email:
            usr = sb_admin.table('users').select('first_name, last_name, business_name').eq('email', seller_email).limit(1).execute()
            if usr.data:
                u = usr.data[0]
                biz = (u.get('business_name') or '').strip()
                fn  = (u.get('first_name')    or '').strip()
                ln  = (u.get('last_name')     or '').strip()
                product['seller_name'] = biz or f'{fn} {ln}'.strip() or seller_email
            else:
                product['seller_name'] = seller_email
        else:
            product['seller_name'] = 'Unknown'

        product['price']    = float(product.get('price') or 0)
        product['quantity'] = int(product.get('quantity') or 0)

        return jsonify({'success': True, 'product': product})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
@app.route('/delete_product/<int:product_id>', methods=['POST'])
def delete_product(product_id):
    if 'email' not in session:
        if request.is_json or request.headers.get('Content-Type') == 'application/json':
            return jsonify({'success': False, 'error': 'Not logged in'}), 401
        return redirect(url_for('home'))

    try:
        seller_email = session['email']
        is_admin = session.get('user_type', '').lower() == 'admin'

        # Fetch product from Supabase
        if is_admin:
            prod_res = sb_admin.table('products') \
                .select('id, image, seller_email') \
                .eq('id', product_id) \
                .limit(1).execute()
        else:
            prod_res = sb_admin.table('products') \
                .select('id, image, seller_email') \
                .eq('id', product_id) \
                .eq('seller_email', seller_email) \
                .limit(1).execute()

        if not prod_res.data:
            if request.is_json or request.headers.get('Content-Type') == 'application/json':
                return jsonify({'success': False, 'error': 'Product not found or permission denied'}), 404
            flash('Product not found or you do not have permission to delete it.', 'error')
            return redirect(url_for('products'))

        product = prod_res.data[0]

        # Delete from Supabase
        if is_admin:
            sb_admin.table('products').delete().eq('id', product_id).execute()
        else:
            sb_admin.table('products').delete() \
                .eq('id', product_id) \
                .eq('seller_email', seller_email) \
                .execute()

        # Also delete variant inventory rows (non-fatal)
        try:
            sb_admin.table('variant_inventory').delete().eq('product_id', product_id).execute()
        except Exception:
            pass

        # Delete local image files if they exist (non-fatal)
        if product.get('image'):
            for img in product['image'].split(','):
                img = img.strip()
                if img and not img.startswith('http'):
                    img_path = os.path.join(app.config['UPLOAD_FOLDER'], img)
                    try:
                        if os.path.exists(img_path):
                            os.remove(img_path)
                    except Exception:
                        pass

        if request.is_json or request.headers.get('Content-Type') == 'application/json':
            return jsonify({'success': True, 'message': 'Product deleted successfully'})

        flash('Product deleted successfully!', 'success')

    except Exception as e:
        import traceback; traceback.print_exc()
        if request.is_json or request.headers.get('Content-Type') == 'application/json':
            return jsonify({'success': False, 'error': str(e)}), 500
        flash(f'Error deleting product: {str(e)}', 'error')

    return redirect(url_for('products'))

@app.route('/flag_product/<int:product_id>', methods=['POST'])
def flag_product(product_id):
    """Admin: flag a product for violation — Supabase"""
    if 'user_id' not in session or session.get('user_type') != 'Admin':
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403
    try:
        data       = request.get_json() or {}
        reason     = (data.get('reason') or '').strip()
        send_email = data.get('send_email', True)
        if not reason:
            return jsonify({'success': False, 'error': 'Reason is required'}), 400

        prod = sb_admin.table('products').select('id, name, seller_email').eq('id', product_id).limit(1).execute()
        if not prod.data:
            return jsonify({'success': False, 'error': 'Product not found'}), 404

        from datetime import datetime as _dt
        sb_admin.table('products').update({
            'flag_reason': reason,
            'flagged_at':  _dt.now().isoformat(),
            'flagged_by':  session['email'],
            'is_flagged':  True,
        }).eq('id', product_id).execute()

        seller_email = prod.data[0].get('seller_email', '')
        product_name = prod.data[0].get('name', '')

        if seller_email:
            try:
                sb_admin.table('notifications').insert({
                    'seller_email': seller_email,
                    'message':      f"Your product '{product_name}' has been flagged for policy violation. Reason: {reason}",
                    'type':         'product_flagged',
                    'is_read':      False,
                }).execute()
            except Exception:
                pass

            if send_email:
                try:
                    msg = Message(
                        subject=f"Product Flagged for Policy Violation - {product_name}",
                        sender=app.config['MAIL_DEFAULT_SENDER'],
                        recipients=[seller_email],
                    )
                    msg.body = (
                        f"Dear Seller,\n\n"
                        f"Your product '{product_name}' has been flagged for policy violation.\n\n"
                        f"Reason: {reason}\n\n"
                        f"Please review our platform policies and take appropriate action.\n\n"
                        f"MStyle E-Commerce Team"
                    )
                    mail.send(msg)
                except Exception as email_err:
                    print(f"Flag email failed: {email_err}")

        return jsonify({'success': True, 'message': 'Product flagged successfully.', 'product_id': product_id})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
@app.route('/clear_product_flag/<int:product_id>', methods=['POST'])
def clear_product_flag(product_id):
    """Admin: clear a product flag — Supabase"""
    if 'user_id' not in session or session.get('user_type') != 'Admin':
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403
    try:
        prod = sb_admin.table('products').select('id, flagged_at').eq('id', product_id).limit(1).execute()
        if not prod.data:
            return jsonify({'success': False, 'error': 'Product not found'}), 404
        if not prod.data[0].get('flagged_at'):
            return jsonify({'success': False, 'error': 'Product is not flagged'}), 400

        sb_admin.table('products').update({
            'flag_reason': None, 'flagged_at': None,
            'flagged_by':  None, 'is_flagged':  False,
        }).eq('id', product_id).execute()

        return jsonify({'success': True, 'message': 'Product flag cleared successfully', 'product_id': product_id})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
@app.route('/toggle_product_status/<int:product_id>', methods=['POST'])
def toggle_product_status(product_id):
    """Admin: activate or deactivate a product — Supabase"""
    if 'user_id' not in session or session.get('user_type') != 'Admin':
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403
    try:
        data      = request.get_json() or {}
        is_active = data.get('is_active', True)
        reason    = (data.get('reason') or '').strip()

        prod = sb_admin.table('products').select('id, name, seller_email').eq('id', product_id).limit(1).execute()
        if not prod.data:
            return jsonify({'success': False, 'error': 'Product not found'}), 404

        sb_admin.table('products').update({'is_active': is_active}).eq('id', product_id).execute()

        seller_email = prod.data[0].get('seller_email', '')
        product_name = prod.data[0].get('name', '')
        status_text  = 'activated' if is_active else 'deactivated'

        if seller_email:
            msg = f"Your product '{product_name}' has been {status_text} by admin."
            if not is_active and reason:
                msg += f" Reason: {reason}"
            try:
                sb_admin.table('notifications').insert({
                    'seller_email': seller_email,
                    'message':      msg,
                    'type':         'product_activated' if is_active else 'product_deactivated',
                    'is_read':      False,
                }).execute()
            except Exception:
                pass

        return jsonify({'success': True,
                        'message': f'Product has been {status_text} successfully.',
                        'product_id': product_id, 'is_active': is_active})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
@app.route('/checkout_single_product', methods=['POST'])
def checkout_single_product():
    if 'email' not in session:
        return jsonify({'success': False, 'error': 'Please log in to checkout'})

    try:
        product_id     = request.form.get('product_id')
        selected_color = request.form.get('product_variation', '')
        color_image    = request.form.get('product_image', '')
        size           = request.form.get('size', '')
        product_price  = request.form.get('product_price')
        try:
            quantity = int(request.form.get('quantity', '1'))
        except ValueError:
            return jsonify({'success': False, 'error': 'Invalid quantity value'})

        if not product_id or quantity < 1:
            return jsonify({'success': False, 'error': 'Invalid product or quantity'})

        # Fetch product from Supabase
        prod_res = sb_admin.table('products').select('*').eq('id', int(product_id)).execute()
        if not prod_res.data:
            return jsonify({'success': False, 'error': 'Product not found'})
        product = prod_res.data[0]

        # Check stock
        if int(product.get('quantity') or 0) < quantity:
            return jsonify({'success': False, 'error': 'Insufficient stock'})

        # Resolve price
        try:
            price = float(product_price) if product_price and str(product_price).strip() else float(product.get('price') or 0)
        except (ValueError, TypeError):
            return jsonify({'success': False, 'error': 'Invalid product price'})

        # Resolve image — prefer color_image from form (already resolved by view_product.html JS)
        # then fall back to image_colors mapping, then first product image
        if color_image and color_image.strip():
            checkout_image = color_image.strip()
        else:
            # Try image_colors mapping for the selected color
            color_map = _parse_image_colors_dict(
                product.get('image_colors'), product.get('image'))
            color_key = selected_color.strip().lower()
            if color_key and color_key in color_map:
                checkout_image = color_map[color_key]
            elif product.get('image'):
                checkout_image = product['image'].split(',')[0].strip()
            else:
                checkout_image = ''

        # Check free shipping promotion via Supabase
        shipping_fee = 50
        try:
            from datetime import date
            today = date.today().isoformat()
            promo_res = sb_admin.table('promotions') \
                .select('id') \
                .eq('seller_email', product['seller_email']) \
                .eq('type', 'free_shipping') \
                .eq('is_active', True) \
                .lte('start_date', today) \
                .gte('end_date', today) \
                .limit(1) \
                .execute()
            if promo_res.data:
                shipping_fee = 0
        except Exception:
            pass

        # Store checkout item in session (no DB needed for single-product buy now)
        session['checkout_items'] = [{
            'id':           product_id,
            'name':         product['name'],
            'price':        price,
            'quantity':     quantity,
            'variations':   selected_color,
            'image':        checkout_image,
            'size':         size,
            'email':        session['email'],
            'seller_email': product.get('seller_email', ''),
            'product_id':   product_id,
            'shipping_fee': shipping_fee,
        }]
        session['checkout_source'] = 'buy_now'

        return jsonify({'success': True})

    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({'success': False, 'error': f'An error occurred: {str(e)}'})


@app.route('/about')
def about():
    return render_template('about.html')

@app.route('/contact')
def contact():
    return render_template('contact.html')

@app.route('/privacy')
def privacy():
    return render_template('privacy.html')

@app.route('/wishlist')
def wishlist():
    if 'user_id' not in session:
        return redirect(url_for('home'))
    user_email = session.get('email')
    user_name = get_user_name_from_session(default='User')
    wishlist_items = []
    promotional_products = []
    try:
        user_id = _resolve_wishlist_user_id(user_email)
        print(f'[wishlist] email={user_email} resolved user_id={user_id}')
        wl_res = sb_admin.table('wishlist').select('product_id').eq('user_id', user_id).execute()
        print(f'[wishlist] Supabase wishlist rows for user_id={user_id}: {wl_res.data}')
        product_ids = [r['product_id'] for r in (wl_res.data or [])]
        if product_ids:
            prod_res = sb_admin.table('products').select('*').in_('id', product_ids).execute()
            wishlist_items = prod_res.data or []

            # Batch-fetch ratings from reviews table
            if wishlist_items:
                rev_res = sb_admin.table('reviews').select('product_id, rating').in_('product_id', product_ids).execute()
                from collections import defaultdict
                rating_map = defaultdict(list)
                for r in (rev_res.data or []):
                    rating_map[r['product_id']].append(r['rating'])

                for p in wishlist_items:
                    ratings = rating_map.get(p['id'], [])
                    if ratings:
                        p['rating'] = round(sum(ratings) / len(ratings), 1)
                        p['review_count'] = len(ratings)
                    else:
                        p['rating'] = p.get('rating') or 0
                        p['review_count'] = 0
                    # Normalize numeric fields
                    p['price'] = float(p.get('price') or 0)
                    p['quantity'] = int(p.get('quantity') or 0)
                    p['sold'] = int(p.get('sold') or 0)
        promotional_products = get_promotional_products()
    except Exception as e:
        import traceback; traceback.print_exc()
        print(f'Error in wishlist route: {e}')
    return render_template('wishlist.html', wishlist_items=wishlist_items,
                           user_name=user_name, user_email=user_email,
                           promotional_products=promotional_products,
                           wishlist_product_ids={str(item['id']) for item in wishlist_items})


@app.route('/debug-wishlist')
def debug_wishlist():
    """Debug route � shows what user_id is computed and what's in the wishlist table."""
    if 'user_id' not in session:
        return 'Not logged in', 401
    import hashlib
    user_email = session.get('email', '')
    # Compute user_id both ways
    sb_res = sb_admin.table('users').select('id').eq('email', user_email).execute()
    supabase_raw_id = sb_res.data[0].get('id') if sb_res.data else None
    try:
        supabase_int_id = int(supabase_raw_id)
    except (ValueError, TypeError):
        supabase_int_id = None
    md5_id = int(hashlib.md5(user_email.lower().encode()).hexdigest()[:8], 16) & 0x7FFFFFFF
    resolved_id = supabase_int_id if supabase_int_id is not None else md5_id
    # Fetch ALL wishlist rows (no filter) to see what's there
    all_wl = sb_admin.table('wishlist').select('*').limit(50).execute()
    # Fetch rows for this user
    user_wl = sb_admin.table('wishlist').select('*').eq('user_id', resolved_id).execute()
    html = f"""
    <h2>Wishlist Debug</h2>
    <p><b>Email:</b> {user_email}</p>
    <p><b>Supabase users.id (raw):</b> {supabase_raw_id}</p>
    <p><b>Supabase users.id as int:</b> {supabase_int_id}</p>
    <p><b>MD5 hash id:</b> {md5_id}</p>
    <p><b>Resolved user_id used:</b> {resolved_id}</p>
    <hr>
    <h3>All wishlist rows in Supabase (first 50):</h3>
    <pre>{all_wl.data}</pre>
    <h3>Wishlist rows for user_id={resolved_id}:</h3>
    <pre>{user_wl.data}</pre>
    """
    return html


@app.route('/add-to-wishlist', methods=['POST'])
def add_to_wishlist():
    if 'user_id' not in session:
        return jsonify({'error': 'Please login first'}), 401
    try:
        data = request.get_json()
        user_email = session.get('email')
        product_id = data.get('product_id')
        if not product_id:
            return jsonify({'error': 'Product ID is required'}), 400
        user_id = _resolve_wishlist_user_id(user_email)
        pid = int(product_id)

        # Retry wrapper for WinError 10035 (WSAEWOULDBLOCK) on Windows
        def _supabase_call(fn, retries=3):
            import time
            last_err = None
            for attempt in range(retries):
                try:
                    return fn()
                except Exception as e:
                    last_err = e
                    err_str = str(e)
                    if '10035' in err_str or 'WinError' in err_str or 'non-blocking' in err_str.lower():
                        time.sleep(0.3 * (attempt + 1))
                        continue
                    raise
            raise last_err

        existing = _supabase_call(
            lambda: sb_admin.table('wishlist').select('id').eq('user_id', user_id).eq('product_id', pid).execute()
        )
        if existing.data:
            _supabase_call(
                lambda: sb_admin.table('wishlist').delete().eq('user_id', user_id).eq('product_id', pid).execute()
            )
            return jsonify({'success': True, 'message': 'Item removed from wishlist'})
        else:
            _supabase_call(
                lambda: sb_admin.table('wishlist').insert({'user_id': user_id, 'product_id': pid}).execute()
            )
            return jsonify({'success': True, 'message': 'Item added to wishlist successfully!'})
    except Exception as e:
        print(f'Error in add_to_wishlist: {e}')
        return jsonify({'success': False, 'error': 'Failed to update wishlist. Please try again.'}), 500


@app.route('/remove_from_wishlist', methods=['POST'])
def remove_from_wishlist():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    try:
        user_email = session.get('email')
        product_id = request.form.get('product_id')
        if not product_id:
            flash('Product ID is required', 'error')
            return redirect(url_for('wishlist'))
        user_id = _resolve_wishlist_user_id(user_email)
        sb_admin.table('wishlist').delete().eq('user_id', user_id).eq('product_id', int(product_id)).execute()
        flash('Item removed from wishlist successfully!', 'success')
    except Exception as e:
        print(f'Error removing from wishlist: {e}')
        flash('Failed to remove item from wishlist', 'error')
    return redirect(url_for('wishlist'))


@app.route('/test-wishlist')
def test_wishlist():
    """Test route to check Supabase wishlist table"""
    try:
        res = sb_admin.table('wishlist').select('*').limit(10).execute()
        count = len(res.data or [])
        return f"<h1>Wishlist Test (Supabase)</h1><p>Wishlist table accessible. Rows (first 10): {count}</p><pre>{res.data}</pre>"
    except Exception as e:
        return f"<h1>Wishlist Test Error</h1><p>Error: {str(e)}</p>"

# @app.route('/test-json') removed (debug route)

@app.route('/api/buyer/notifications')
def get_buyer_notifications():
    """Get notifications for the logged-in buyer"""
    buyer_email = session.get('email')
    if not buyer_email:
        return jsonify({'success': False, 'error': 'Not logged in'}), 401

    try:
        res = sb_admin.table('buyer_notifications') \
            .select('id, message, type, is_read, created_at, order_id') \
            .eq('buyer_email', buyer_email) \
            .order('created_at', desc=True) \
            .limit(20) \
            .execute()

        notifications = res.data or []
        for n in notifications:
            if n.get('created_at'):
                n['created_at'] = str(n['created_at'])
            n['read'] = bool(n.get('is_read', False))

        return jsonify({'success': True, 'notifications': notifications})

    except Exception as e:
        print(f'[buyer_notifications] error: {e}')
        return jsonify({'success': True, 'notifications': []})

@app.route('/api/buyer/notifications/mark-read', methods=['POST'])
def mark_buyer_notification_read():
    """Mark a specific buyer notification as read"""
    buyer_email = session.get('email')
    user_type = session.get('user_type')

    if not buyer_email or (user_type and user_type.lower() != 'buyer'):
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401

    try:
        data = request.get_json()
        notification_id = data.get('notification_id')

        if not notification_id:
            return jsonify({'success': False, 'error': 'Notification ID required'}), 400

        sb_admin.table('buyer_notifications') \
            .update({'is_read': True}) \
            .eq('id', notification_id) \
            .eq('buyer_email', buyer_email) \
            .execute()

        print(f"✅ Buyer notification {notification_id} marked as read")
        return jsonify({'success': True})

    except Exception as e:
        print(f"❌ Error marking buyer notification as read: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/buyer/notifications/mark-all-read', methods=['POST'])
def mark_all_buyer_notifications_read():
    """Mark all notifications as read for the logged-in buyer"""
    buyer_email = session.get('email')
    user_type = session.get('user_type')

    if not buyer_email or (user_type and user_type.lower() != 'buyer'):
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401

    try:
        sb_admin.table('buyer_notifications') \
            .update({'is_read': True}) \
            .eq('buyer_email', buyer_email) \
            .eq('is_read', False) \
            .execute()

        print(f"✅ All buyer notifications marked as read for {buyer_email}")
        return jsonify({'success': True})

    except Exception as e:
        print(f"❌ Error marking all buyer notifications as read: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/buyer/notifications/delete', methods=['POST'])
def delete_buyer_notification():
    """Delete a specific buyer notification"""
    buyer_email = session.get('email')
    user_type = session.get('user_type')

    if not buyer_email or (user_type and user_type.lower() != 'buyer'):
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401

    try:
        data = request.get_json()
        notification_id = data.get('notification_id')

        if not notification_id:
            return jsonify({'success': False, 'error': 'Notification ID required'}), 400

        result = sb_admin.table('buyer_notifications') \
            .delete() \
            .eq('id', notification_id) \
            .eq('buyer_email', buyer_email) \
            .execute()

        deleted_count = len(result.data) if result.data else 0
        if deleted_count == 0:
            return jsonify({'success': False, 'error': 'Notification not found or unauthorized'}), 404

        print(f"✅ Buyer notification {notification_id} deleted for {buyer_email}")
        return jsonify({'success': True, 'deleted_count': deleted_count})

    except Exception as e:
        print(f"❌ Error deleting buyer notification: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/buyer/notifications/delete-all', methods=['POST'])
def delete_all_buyer_notifications():
    """Delete all notifications for the logged-in buyer"""
    buyer_email = session.get('email')
    user_type = session.get('user_type')

    if not buyer_email or (user_type and user_type.lower() != 'buyer'):
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401

    try:
        result = sb_admin.table('buyer_notifications') \
            .delete() \
            .eq('buyer_email', buyer_email) \
            .execute()

        deleted_count = len(result.data) if result.data else 0
        print(f"✅ {deleted_count} buyer notifications deleted for buyer: {buyer_email}")
        return jsonify({'success': True, 'deleted_count': deleted_count})

    except Exception as e:
        print(f"❌ Error deleting all buyer notifications: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

def _create_order_notification_supabase(seller_email, order_details):
    """Create a seller notification in Supabase when an order is placed."""
    try:
        total_items  = len(order_details)
        total_amount = sum(float(item.get('total_price', 0)) for item in order_details)
        customer     = order_details[0].get('email', 'Unknown') if order_details else 'Unknown'
        if total_items == 1:
            item = order_details[0]
            msg = f"New order: {item['name']} (Qty: {item['quantity']}) - ?{total_amount:.2f} from {customer}"
        else:
            msg = f"New order: {total_items} items - ?{total_amount:.2f} from {customer}"
        sb_admin.table('notifications').insert({
            'seller_email': seller_email,
            'message':      msg,
            'type':         'order',
            'is_read':      False,
        }).execute()
        print(f"? Supabase notification created for {seller_email}")
        return True
    except Exception as e:
        print(f"? _create_order_notification_supabase error: {e}")
        return False


def create_order_notification(seller_email, order_details):
    """Create a notification in Supabase when an order is placed"""
    return _create_order_notification_supabase(seller_email, order_details)

def create_cancellation_notification(seller_email, order_name, reason, customer_email, order_id=None):
    """Create a cancellation notification in Supabase"""
    try:
        message = f"Order cancelled: {order_name} by {customer_email}. Reason: {reason}"
        sb_admin.table('notifications').insert({
            'seller_email': seller_email, 'message': message,
            'type': 'cancellation', 'is_read': False,
        }).execute()
        return True
    except Exception as e:
        print(f"create_cancellation_notification error: {e}")
        return False

# placeholder removed
        return True
        
    except Exception as e:
        print(f"? Error creating cancellation notification for {seller_email}: {str(e)}")
        import traceback
        traceback.print_exc()
        return False

def send_order_status_update_email(customer_email, order_details, new_status, seller_info=None):
    """Send order status update email to customer"""
    try:
        print(f"?? Sending order status update email to customer: {customer_email}")
        print(f"?? Order: {order_details['name']}, New Status: {new_status}")
        
        msg = Message(
            f'Order Status Update - {new_status}',
            sender=app.config['MAIL_DEFAULT_SENDER'],
            recipients=[customer_email]
        )
        
        # Create status-specific messages
        status_messages = {
            'Pending': {
                'title': 'Order Confirmed',
                'message': 'Your order has been confirmed and is being prepared.',
                'next_step': 'We will notify you once your order has been shipped.'
            },
            'Shipped': {
                'title': 'Order Shipped',
                'message': 'Great news! Your order has been shipped and is on its way to you.',
                'next_step': 'You should receive your order within 3-7 business days. We will notify you once it has been delivered.'
            },
            'Delivered': {
                'title': 'Order Delivered',
                'message': 'Your order has been successfully delivered!',
                'next_step': 'We hope you love your purchase! Please consider leaving a review.'
            }
        }
        
        status_info = status_messages.get(new_status, {
            'title': 'Order Status Updated',
            'message': f'Your order status has been updated to: {new_status}',
            'next_step': 'Thank you for your patience.'
        })
        
        # Format order details
        try:
            order_total = float(order_details.get('total_price', 0)) if order_details.get('total_price') else 0.0
        except (ValueError, TypeError):
            order_total = 0.0
        
        msg.body = f"""Hello!

{status_info['title']} - Order Update

ORDER DETAILS:
Product: {order_details['name']}
Quantity: {order_details['quantity']}
"""
        
        if order_details.get('variations'):
            msg.body += f"Color: {order_details['variations']}\n"
        if order_details.get('size'):
            msg.body += f"Size: {order_details['size']}\n"
            
        msg.body += f"Total: P{order_total:.2f}\n"
        msg.body += f"""Order Date: {order_details.get('date', 'N/A')}

STATUS UPDATE:
{status_info['message']}

NEXT STEPS:
{status_info['next_step']}

DELIVERY ADDRESS:
{order_details.get('address', 'Address not available')}

Thank you for choosing MStyle!

Best regards,
MStyle Team
"""

        mail.send(msg)
        print(f"? Order status update email sent to customer: {customer_email}")
        return True
        
    except Exception as e:
        print(f"? Error sending order status update email to {customer_email}: {str(e)}")
        import traceback
        traceback.print_exc()
        return False

def notify_riders_of_new_order(order_id, order_details, seller_email):
    """Notify all available riders about a new confirmed order via Supabase"""
    try:
        print(f"??? Notifying riders about confirmed order {order_id}")

        # Get all riders from Supabase
        riders_res = sb_admin.table('users').select('email, first_name, last_name').eq('role', 'rider').execute()
        riders = riders_res.data or []

        if not riders:
            print("?? No riders found in Supabase")
            return False

        # Get seller info from Supabase
        seller_res = sb_admin.table('users').select('first_name, last_name, business_name, address').eq('email', seller_email).execute()
        seller_info  = seller_res.data[0] if seller_res.data else {}
        seller_name  = seller_info.get('business_name') or f"{seller_info.get('first_name','')} {seller_info.get('last_name','')}".strip() or 'Seller'
        seller_addr  = seller_info.get('address') or 'Address not available'

        try:
            order_total = float(order_details.get('total_price', 0)) if order_details.get('total_price') else 0.0
        except (ValueError, TypeError):
            order_total = 0.0

        riders_notified = 0
        notif_rows = []
        for rider in riders:
            # Email
            try:
                msg = Message(f'New Delivery Available - Order #{order_id}', sender=app.config['MAIL_DEFAULT_SENDER'], recipients=[rider['email']])
                msg.body = f"""Hello {rider['first_name']}!\n\nA new delivery order is now available!\n\nOrder #{order_id} - {order_details.get('name','')}\nQty: {order_details.get('quantity',1)}\nValue: ?{order_total:.2f}\nPickup: {seller_name}, {seller_addr}\nDelivery: {order_details.get('address','N/A')}\n\nLog in to your rider dashboard to accept.\n\nMStyle Team"""
                mail.send(msg)
            except Exception as email_err:
                print(f"?? Email to rider {rider['email']} failed: {email_err}")

            notif_rows.append({'rider_email': rider['email'], 'message': f"New delivery available! Order #{order_id} - {order_details.get('name','')} (?{order_total:.2f}). Pickup from {seller_name}.", 'order_id': order_id, 'is_read': False})
            riders_notified += 1

        if notif_rows:
            sb_admin.table('rider_notifications').insert(notif_rows).execute()

        print(f"? Notified {riders_notified} riders")
        return riders_notified > 0

    except Exception as e:
        print(f"? Error notifying riders: {e}")
        import traceback; traceback.print_exc()
        return False

def create_buyer_notification(customer_email, order_details, status, order_id=None):
    """Create a notification in Supabase for buyer when order status is updated"""
    try:
        status_messages = {
            'Pending':   f"Your order '{order_details['name']}' has been confirmed and is being prepared.",
            'Shipped':   f"Great news! Your order '{order_details['name']}' has been shipped and is on the way.",
            'Delivered': f"Your order '{order_details['name']}' has been delivered successfully!",
        }
        message = status_messages.get(status, f"Your order '{order_details['name']}' status has been updated to: {status}")

        notif_type = 'status_update'
        if status == 'Delivered': notif_type = 'delivered'
        elif status == 'Shipped':  notif_type = 'shipped'

        sb_admin.table('buyer_notifications').insert({
            'buyer_email': customer_email,
            'message':     message,
            'type':        notif_type,
            'is_read':     False,
            'order_id':    order_id,
        }).execute()
        print(f"? Buyer notification created for: {customer_email}")
        return True
    except Exception as e:
        print(f"? Error creating buyer notification for {customer_email}: {e}")
        import traceback; traceback.print_exc()
        return False

@app.route('/test-notifications')
def test_notifications():
    """Test route to create sample notifications (for development only)"""
    if not app.debug:
        return "Not available in production", 404
    
    try:
        # Get current seller email from session, or use test email
        seller_email = session.get('email', 'seller@test.com')
        
        # Create a test notification
        test_order = [{
            'name': 'Test Product - Premium T-Shirt',
            'quantity': 2,
            'total_price': 1299.99,
            'email': 'customer@test.com',
            'variations': 'Blue',
            'size': 'Large'
        }]
        
        print(f"?? Creating test notification for seller: {seller_email}")
        
        success = create_order_notification(seller_email, test_order)
        
        if success:
            return f"? Test notification created for {seller_email}<br><br>Check your notifications dropdown!"
        else:
            return "? Failed to create test notification"
            
    except Exception as e:
        return f"Error: {str(e)}"

@app.route('/test-notifications-for-seller/<seller_email>')
def test_notifications_for_seller(seller_email):
    """Test route to create notifications for a specific seller (for development only)"""
    if not app.debug:
        return "Not available in production", 404
    
    try:
        # Create a test notification for specific seller
        test_order = [{
            'name': 'Test Order - Casual Shirt',
            'quantity': 1,
            'total_price': 899.50,
            'email': 'testcustomer@example.com',
            'variations': 'Red',
            'size': 'Medium'
        }]
        
        print(f"?? Creating test notification for specific seller: {seller_email}")
        
        success = create_order_notification(seller_email, test_order)
        
        if success:
            return f"? Test notification created for {seller_email}<br><br>The seller should see this in their notifications dropdown!"
        else:
            return "? Failed to create test notification"
            
    except Exception as e:
        return f"Error: {str(e)}"

@app.route('/test-cancellation-notification')
def test_cancellation_notification():
    """Test route to create sample cancellation notifications (for development only)"""
    if not app.debug:
        return "Not available in production", 404
    
    try:
        # Get current seller email from session, or use test email
        seller_email = session.get('email', 'seller@test.com')
        
        # Create a test cancellation notification
        order_name = 'Test Product - Premium Jacket'
        reason = 'Changed my mind about the purchase'
        customer_email = 'customer@test.com'
        
        print(f"?? Creating test cancellation notification for seller: {seller_email}")
        
        success = create_cancellation_notification(seller_email, order_name, reason, customer_email)
        
        if success:
            return f"? Test cancellation notification created for {seller_email}<br><br>Check your notifications dropdown for the cancellation!"
        else:
            return "? Failed to create test cancellation notification"
            
    except Exception as e:
        return f"Error: {str(e)}"

@app.route('/test-cancellation-for-seller/<seller_email>')
def test_cancellation_for_seller(seller_email):
    """Test route to create cancellation notifications for a specific seller (for development only)"""
    if not app.debug:
        return "Not available in production", 404
    
    try:
        # Create a test cancellation notification for specific seller
        order_name = 'Test Product - Business Suit'
        reason = "Size doesn't fit properly"
        customer_email = 'testcustomer@example.com'
        
        print(f"?? Creating test cancellation notification for specific seller: {seller_email}")
        
        success = create_cancellation_notification(seller_email, order_name, reason, customer_email)
        
        if success:
            return f"? Test cancellation notification created for {seller_email}<br><br>The seller should see this cancellation in their notifications dropdown!"
        else:
            return "? Failed to create test cancellation notification"
            
    except Exception as e:
        return f"Error: {str(e)}"

@app.route('/test-notifications-page')
def test_notifications_page():
    """Test page for notifications system (for development only)"""
    if not app.debug:
        return "Not available in production", 404
    
    return render_template('test_notifications.html')

@app.route('/debug-auth')
def debug_auth():
    """Debug route to check authentication status for notifications"""
    if not app.debug:
        return "Not available in production", 404
    
    seller_email = session.get('email')
    user_type = session.get('user_type')
    
    auth_status = {
        'email': seller_email,
        'user_type': user_type,
        'has_email': bool(seller_email),
        'is_seller': user_type and user_type.lower() == 'seller',
        'full_session': dict(session)
    }
    
    result = f"""
    <h2>Authentication Debug</h2>
    <div style="background: #f0f0f0; padding: 15px; border-radius: 5px;">
        <h3>Authentication Status:</h3>
        <ul>
            <li><strong>Email:</strong> {auth_status['email'] or 'Not set'}</li>
            <li><strong>User Type:</strong> {auth_status['user_type'] or 'Not set'}</li>
            <li><strong>Has Email:</strong> {'? Yes' if auth_status['has_email'] else '? No'}</li>
            <li><strong>Is Seller:</strong> {'? Yes' if auth_status['is_seller'] else '? No'}</li>
        </ul>
        
        <h3>Full Session Data:</h3>
        <pre>{auth_status['full_session']}</pre>
        
        <h3>API Access Status:</h3>
        <ul>
            <li><strong>Can access notifications API:</strong> {'? Yes' if auth_status['has_email'] and auth_status['is_seller'] else '? No'}</li>
            <li><strong>Can delete notifications:</strong> {'? Yes' if auth_status['has_email'] and auth_status['is_seller'] else '? No'}</li>
        </ul>
    </div>
    
    <h3>Quick Actions:</h3>
    <p><a href="/debug-session">View Session Details</a></p>
    <p><a href="/debug-notifications">View All Notifications</a></p>
    <p><a href="/test-notifications-page">Test Notifications</a></p>
    <p><a href="/set-test-session">Set Test Seller Session</a></p>
    """
    
    return result

@app.route('/set-test-session')
def set_test_session():
    """Set a test seller session for debugging (development only)"""
    if not app.debug:
        return "Not available in production", 404
    
    # Set test session data
    session['email'] = 'test-seller@example.com'
    session['user_type'] = 'seller'
    session['user_id'] = 999
    session['first_name'] = 'Test Seller'
    
    return """
    <h2>? Test Seller Session Set</h2>
    <p>Session has been set with test seller data:</p>
    <ul>
        <li><strong>Email:</strong> test-seller@example.com</li>
        <li><strong>User Type:</strong> seller</li>
        <li><strong>User ID:</strong> 999</li>
        <li><strong>First Name:</strong> Test Seller</li>
    </ul>
    
    <p>You can now test the notifications system:</p>
    <ul>
        <li><a href="/debug-auth">Check Authentication Status</a></li>
        <li><a href="/test-notifications">Create Test Notification</a></li>
        <li><a href="/api/seller/notifications">Test Notifications API</a></li>
        <li><a href="/test-status-update-email">Test Status Update Email</a></li>
    </ul>
    
    <p><strong>Note:</strong> This is for testing only. In production, users must log in properly.</p>
    """



@app.route('/test-status-update-email')
def test_status_update_email():
    """Test route to send a sample order status update email (for development only)"""
    if not app.debug:
        return "Not available in production", 404
    
    try:
        # Sample order details
        test_order = {
            'name': 'Premium Business Suit',
            'quantity': 1,
            'total_price': 2499.99,
            'variations': 'Navy Blue',
            'size': 'Large',
            'date': '2024-01-15',
            'address': '123 Main Street, Brgy. San Antonio, Makati City, Metro Manila, 1200'
        }
        
        test_customer_email = 'customer@test.com'
        test_status = request.args.get('status', 'Shipped')
        
        print(f"?? Testing status update email for: {test_customer_email}")
        
        success = send_order_status_update_email(test_customer_email, test_order, test_status)
        
        if success:
            return f"""
            <h2>? Test Status Update Email Sent</h2>
            <p><strong>Customer Email:</strong> {test_customer_email}</p>
            <p><strong>Order:</strong> {test_order['name']}</p>
            <p><strong>New Status:</strong> {test_status}</p>
            <p><strong>Total:</strong> ?{test_order['total_price']:.2f}</p>
            
            <p>Check the email inbox for the status update notification!</p>
            
            <h3>Test Other Statuses:</h3>
            <ul>
                <li><a href="/test-status-update-email?status=Pending">Test Pending Status</a></li>
                <li><a href="/test-status-update-email?status=Shipped">Test Shipped Status</a></li>
                <li><a href="/test-status-update-email?status=Delivered">Test Delivered Status</a></li>
            </ul>
            """
        else:
            return "? Failed to send test status update email"
            
    except Exception as e:
        return f"Error: {str(e)}"

# @app.route('/debug-notifications') removed (debug route)

# /api/notifications-bypass removed (debug route)

@app.route('/admin/order/<int:order_id>/details')
def admin_get_order_details(order_id):
    """Admin: get order details for modal  Supabase"""
    if 'email' not in session or session.get('user_type') != 'Admin':
        return jsonify({'error': 'Unauthorized'}), 403
    try:
        from datetime import datetime as _dt

        ord_res = sb_admin.table('orders').select('*').eq('id', order_id).limit(1).execute()
        if not ord_res.data:
            return jsonify({'error': 'Order not found'}), 404
        o = ord_res.data[0]

        # Batch-fetch user info
        emails = {e for e in [o.get('email'), o.get('seller_email'), o.get('rider_email')] if e}
        user_map = {}
        if emails:
            usr_res = sb_admin.table('users') \
                .select('email, first_name, last_name, business_name, phone') \
                .in_('email', list(emails)).execute()
            for u in (usr_res.data or []):
                fn  = (u.get('first_name')    or '').strip()
                ln  = (u.get('last_name')     or '').strip()
                biz = (u.get('business_name') or '').strip()
                user_map[u['email']] = {
                    'name':  biz or f'{fn} {ln}'.strip() or u['email'],
                    'phone': (u.get('phone') or 'N/A').strip(),
                }

        def _name(e):  return user_map.get(e, {}).get('name',  e or 'Unknown')
        def _phone(e): return user_map.get(e, {}).get('phone', 'N/A')

        def _fmt_dt(val):
            if not val: return None
            try: return str(_dt.fromisoformat(str(val).replace('Z','+00:00').replace('+00:00','')))[:19].replace('T',' ')
            except: return str(val)[:19]

        total_amount = float(o.get('total_price') or 0)
        quantity     = int(o.get('quantity') or 1)
        unit_price   = total_amount / quantity if quantity > 0 else total_amount

        return jsonify({
            'order_id':        o['id'],
            'order_date':      _fmt_dt(o.get('date')),
            'status':          o.get('status', ''),
            'delivered_at':    _fmt_dt(o.get('delivered_at')),
            'received_at':     _fmt_dt(o.get('received_at')),
            'auto_complete_at':_fmt_dt(o.get('auto_complete_at')),
            'is_auto_completed': bool(o.get('is_auto_completed')),
            'buyer_name':      _name(o.get('email', '')),
            'buyer_email':     o.get('email', 'N/A'),
            'buyer_phone':     _phone(o.get('email', '')),
            'delivery_address':o.get('address', 'N/A'),
            'seller_name':     _name(o.get('seller_email', '')),
            'seller_email':    o.get('seller_email', 'N/A'),
            'seller_phone':    _phone(o.get('seller_email', '')),
            'total_amount':    f"{total_amount:.2f}",
            'payment_method':  o.get('payment_method', 'N/A'),
            'rider_name':      _name(o.get('rider_email', '')) if o.get('rider_email') else 'Not Assigned',
            'rider_email':     o.get('rider_email', 'N/A'),
            'rider_phone':     _phone(o.get('rider_email', '')) if o.get('rider_email') else 'N/A',
            'items': [{
                'product_name': o.get('name', 'N/A'),
                'quantity':     quantity,
                'price':        f"{unit_price:.2f}",
                'subtotal':     f"{total_amount:.2f}",
                'variations':   o.get('variations', 'N/A'),
                'size':         o.get('size', 'N/A'),
            }],
        })
    except Exception as e:
        print(f"admin_get_order_details error: {e}")
        return jsonify({'error': 'Internal server error'}), 500
@app.route('/admin/order/update-status', methods=['POST'])
def admin_update_order_status():
    if 'email' not in session or session.get('user_type') != 'Admin':
        return jsonify({'success': False, 'message': 'Unauthorized'}), 403
    try:
        order_id   = request.form.get('order_id')
        new_status = request.form.get('status')
        notes      = request.form.get('notes', '')
        if not order_id or not new_status:
            return jsonify({'success': False, 'message': 'Missing required fields'})
        ord_res = sb_admin.table('orders').select('email, seller_email, name').eq('id', order_id).limit(1).execute()
        if not ord_res.data:
            return jsonify({'success': False, 'message': 'Order not found'})
        order = ord_res.data[0]
        sb_admin.table('orders').update({'status': new_status}).eq('id', order_id).execute()
        notif_msg = f"Your order #{order_id} ({order['name']}) status has been updated to: {new_status}"
        if notes:
            notif_msg += f". Note: {notes}"
        sb_admin.table('buyer_notifications').insert({'buyer_email': order['email'], 'message': notif_msg, 'type': 'status_update', 'order_id': int(order_id), 'is_read': False}).execute()
        sb_admin.table('notifications').insert({'seller_email': order['seller_email'], 'message': f"Order #{order_id} ({order['name']}) status updated to: {new_status} by admin", 'type': 'order', 'is_read': False}).execute()
        return jsonify({'success': True, 'message': 'Order status updated successfully'})
    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({'success': False, 'message': 'Internal server error'}), 500

@app.route('/admin/order/assign-rider', methods=['POST'])
def assign_rider_to_order():
    if 'email' not in session or session.get('user_type') != 'Admin':
        return jsonify({'success': False, 'message': 'Unauthorized'}), 403
    try:
        order_id = request.form.get('order_id')
        rider_id = request.form.get('rider_id')
        if not order_id or not rider_id:
            return jsonify({'success': False, 'message': 'Missing required fields'})
        rider_res = sb_admin.table('users').select('email, first_name, last_name').eq('id', rider_id).eq('role', 'rider').limit(1).execute()
        if not rider_res.data:
            return jsonify({'success': False, 'message': 'Rider not found'})
        rider = rider_res.data[0]
        rider_name = f"{rider.get('first_name','')} {rider.get('last_name','')}".strip()
        ord_res = sb_admin.table('orders').select('email, seller_email, name, address').eq('id', order_id).limit(1).execute()
        if not ord_res.data:
            return jsonify({'success': False, 'message': 'Order not found'})
        order = ord_res.data[0]
        sb_admin.table('orders').update({'rider_email': rider['email']}).eq('id', order_id).execute()
        sb_admin.table('rider_notifications').insert({'rider_email': rider['email'], 'message': f"You have been assigned to deliver order #{order_id} ({order['name']}) to {order['address']}", 'order_id': int(order_id), 'is_read': False}).execute()
        sb_admin.table('buyer_notifications').insert({'buyer_email': order['email'], 'message': f"Rider {rider_name} has been assigned to your order #{order_id}", 'type': 'rider_assigned', 'order_id': int(order_id), 'is_read': False}).execute()
        sb_admin.table('notifications').insert({'seller_email': order['seller_email'], 'message': f"Rider {rider_name} has been assigned to order #{order_id}", 'type': 'rider_assigned', 'is_read': False}).execute()
        return jsonify({'success': True, 'message': 'Rider assigned successfully'})
    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({'success': False, 'message': 'Internal server error'}), 500

@app.route('/export_orders')
def export_orders():
    if 'email' not in session or session.get('user_type') != 'Admin':
        flash('Access denied. Admin privileges required.', 'danger')
        return redirect(url_for('login'))
    try:
        orders_res = sb_admin.table('orders').select('id, date, email, seller_email, rider_email, name, quantity, total_price, payment_method, status, address').order('date', desc=True).execute()
        orders = orders_res.data or []
        emails = set()
        for o in orders:
            for f in ('email', 'seller_email', 'rider_email'):
                if o.get(f): emails.add(o[f])
        user_map = {}
        if emails:
            ur = sb_admin.table('users').select('email, first_name, last_name, business_name').in_('email', list(emails)).execute()
            for u in (ur.data or []):
                fn = (u.get('first_name') or '').strip()
                ln = (u.get('last_name') or '').strip()
                biz = (u.get('business_name') or '').strip()
                user_map[u['email']] = biz or f'{fn} {ln}'.strip() or u['email']
        import csv
        from io import StringIO
        from flask import make_response
        output = StringIO()
        writer = csv.writer(output)
        writer.writerow(['Order ID','Order Date','Buyer Name','Buyer Email','Seller Name','Seller Email','Product Name','Quantity','Total Amount','Payment Method','Order Status','Assigned Rider','Delivery Address'])
        for o in orders:
            writer.writerow([
                o['id'], str(o.get('date',''))[:19],
                user_map.get(o.get('email',''), 'Unknown'), o.get('email','N/A'),
                user_map.get(o.get('seller_email',''), 'Unknown'), o.get('seller_email','N/A'),
                o.get('name','N/A'), o.get('quantity','N/A'),
                f"P{float(o.get('total_price') or 0):.2f}",
                o.get('payment_method','N/A'), o.get('status','N/A'),
                user_map.get(o.get('rider_email',''), 'Not Assigned') if o.get('rider_email') else 'Not Assigned',
                o.get('address','N/A'),
            ])
        output.seek(0)
        response = make_response(output.getvalue())
        response.headers['Content-Type'] = 'text/csv'
        response.headers['Content-Disposition'] = f'attachment; filename=orders_export_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
        return response
    except Exception as e:
        import traceback; traceback.print_exc()
        flash('Error exporting orders', 'danger')
        return redirect(url_for('order_monitoring'))

# ==================== BUYER-SELLER MESSAGING API ROUTES ====================

@app.route('/api/messages/conversation', methods=['GET'])
def get_conversation():
    """Get conversation messages between buyer and seller"""
    # Check if user is logged in
    if 'email' not in session:
        return jsonify({'success': False, 'error': 'Please login first'}), 401
    
    try:
        user_email = session.get('email')
        user_type = session.get('user_type')
        
        # Check if conversation_id is provided directly
        conversation_id = request.args.get('conversation_id')
        seller_email = request.args.get('seller_email')
        buyer_email = request.args.get('buyer_email')
        product_id = request.args.get('product_id')
        
        # Debug logging
        print(f"DEBUG get_conversation - User: {user_email}, Type: {user_type}")
        print(f"DEBUG get_conversation - Params: conversation_id={conversation_id}, seller_email={seller_email}, buyer_email={buyer_email}, product_id={product_id}")
        
        # If conversation_id is provided, use it directly
        if conversation_id:
            print(f"DEBUG - Using provided conversation_id: {conversation_id}")
        else:
            # Determine conversation participants based on user type (case-insensitive)
            if user_type and user_type.lower() == 'seller':
                # Seller is viewing conversation with buyer
                if not buyer_email:
                    return jsonify({'success': False, 'error': 'Buyer email is required for sellers'}), 400
                seller_email = user_email
                print(f"DEBUG - Seller viewing conversation: seller={seller_email}, buyer={buyer_email}")
            else:
                # Buyer is viewing conversation with seller
                if not seller_email:
                    return jsonify({'success': False, 'error': 'Seller email is required for buyers'}), 400
                buyer_email = user_email
                print(f"DEBUG - Buyer viewing conversation: seller={seller_email}, buyer={buyer_email}")
            
            # Generate conversation ID
            conversation_id = f"{buyer_email}_{seller_email}_{product_id if product_id else 'general'}"
        
        # Get or create conversation via Supabase
        conv_res = sb_admin.table('conversations').select('*').eq('conversation_id', conversation_id).limit(1).execute()
        conversation = conv_res.data[0] if conv_res.data else None
        
        # Format messages
        formatted_messages = []
        for msg in messages:
            formatted_messages.append({
                'id': msg['id'],
                'sender_email': msg['sender_email'],
                'receiver_email': msg['receiver_email'],
                'sender_type': msg['sender_type'],
                'message_text': msg['message_text'],
                'is_read': bool(msg['is_read']),
                'created_at': msg['created_at'].isoformat() if msg['created_at'] else None
            })
        
        return jsonify({
            'success': True,
            'conversation_id': conversation_id,
            'messages': formatted_messages,
            'buyer_name': buyer_name,
            'seller_name': seller_name,
            'buyer_profile_picture': buyer_profile_picture,
            'seller_profile_picture': seller_profile_picture
        })
        
    except Exception as e:
        print(f"Error getting conversation: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/messages/send', methods=['POST'])
def send_message():
    if 'email' not in session:
        return jsonify({'success': False, 'error': 'Please login first'}), 401
    try:
        data = request.get_json()
        buyer_email   = data.get('buyer_email')
        seller_email  = data.get('seller_email')
        message_text  = data.get('message_text') or data.get('message')
        product_id    = data.get('product_id')
        order_id      = data.get('order_id')
        conversation_id = data.get('conversation_id')
        if not message_text:
            return jsonify({'success': False, 'error': 'Message text is required'}), 400
        user_email  = session.get('email')
        user_type   = session.get('user_type', '').lower()
        if not buyer_email:  buyer_email  = user_email if user_type == 'buyer' else None
        if not seller_email: seller_email = user_email if user_type == 'seller' else None
        if not buyer_email or not seller_email:
            return jsonify({'success': False, 'error': 'Missing buyer or seller email'}), 400
        sender_email   = user_email
        receiver_email = seller_email if sender_email == buyer_email else buyer_email
        sender_type    = 'buyer' if sender_email == buyer_email else 'seller'
        if not conversation_id:
            conversation_id = f"{buyer_email}_{seller_email}_{product_id if product_id else 'general'}"
        sb_admin.table('conversations').upsert({
            'conversation_id': conversation_id, 'buyer_email': buyer_email,
            'seller_email': seller_email, 'product_id': product_id, 'order_id': order_id,
            'last_message_at': datetime.now().isoformat(),
        }, on_conflict='conversation_id').execute()
        ins = sb_admin.table('buyer_seller_messages').insert({
            'conversation_id': conversation_id, 'sender_email': sender_email,
            'receiver_email': receiver_email, 'sender_type': sender_type, 'message_text': message_text,
        }).execute()
        message_id = ins.data[0]['id'] if ins.data else None
        return jsonify({'success': True, 'message_id': message_id, 'conversation_id': conversation_id})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/messages/mark-read', methods=['POST'])
def mark_messages_read():
    if 'email' not in session:
        return jsonify({'success': False, 'error': 'Please login first'}), 401
    try:
        data = request.get_json()
        conv_id = data.get('conversation_id')
        current_user_email = session.get('email')
        if not conv_id:
            return jsonify({'success': False, 'error': 'Conversation ID required'}), 400
        res = sb_admin.table('buyer_seller_messages').update({'is_read': True}).eq('conversation_id', conv_id).eq('receiver_email', current_user_email).eq('is_read', False).execute()
        affected = len(res.data) if res.data else 0
        return jsonify({'success': True, 'affected_rows': affected})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/seller/messages', methods=['GET'])
def get_seller_messages():
    if 'email' not in session or session.get('user_type','').lower() != 'seller':
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401
    try:
        seller_email = session.get('email')
        sn_res = sb_admin.table('users').select('business_name, first_name, last_name, profile_picture').eq('email', seller_email).limit(1).execute()
        seller_name = 'Seller'
        seller_pic  = None
        if sn_res.data:
            u = sn_res.data[0]
            seller_name = u.get('business_name') or f"{u.get('first_name','')} {u.get('last_name','')}".strip() or 'Seller'
            seller_pic  = u.get('profile_picture')
        conv_res = sb_admin.table('conversations').select('*').eq('seller_email', seller_email).order('last_message_at', desc=True).limit(20).execute()
        conversations = conv_res.data or []
        product_ids = list({c['product_id'] for c in conversations if c.get('product_id')})
        prod_map = {}
        if product_ids:
            pr = sb_admin.table('products').select('id, name').in_('id', product_ids).execute()
            prod_map = {p['id']: p['name'] for p in (pr.data or [])}
        buyer_emails = list({c['buyer_email'] for c in conversations if c.get('buyer_email')})
        buyer_map = {}
        if buyer_emails:
            br = sb_admin.table('users').select('email, first_name, last_name, profile_picture').in_('email', buyer_emails).execute()
            buyer_map = {u['email']: u for u in (br.data or [])}
        formatted = []
        for c in conversations:
            be = c.get('buyer_email','')
            buyer = buyer_map.get(be, {})
            buyer_name = f"{buyer.get('first_name','')} {buyer.get('last_name','')}".strip() or be
            try:
                unread = sb_admin.table('buyer_seller_messages').select('id', count='exact').eq('conversation_id', c['conversation_id']).eq('receiver_email', seller_email).eq('is_read', False).execute()
                unread_count = unread.count or 0
            except Exception:
                unread_count = 0
            try:
                last_msg_res = sb_admin.table('buyer_seller_messages').select('message_text').eq('conversation_id', c['conversation_id']).order('created_at', desc=True).limit(1).execute()
                last_msg = last_msg_res.data[0]['message_text'] if last_msg_res.data else ''
            except Exception:
                last_msg = ''
            formatted.append({
                'conversation_id': c['conversation_id'], 'buyer_email': be,
                'product_id': c.get('product_id'), 'order_id': c.get('order_id'),
                'last_message_at': str(c.get('last_message_at','')),
                'product_name': prod_map.get(c.get('product_id'),''),
                'buyer_name': buyer_name, 'unread_count': unread_count,
                'last_message': last_msg,
                'buyer_profile_picture': buyer.get('profile_picture'),
                'conversation_type': 'buyer',
                'seller_name': seller_name, 'seller_profile_picture': seller_pic,
            })
        return jsonify({'success': True, 'conversations': formatted})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/seller/conversations/delete', methods=['POST'])
def delete_seller_conversation():
    if 'email' not in session:
        return jsonify({'success': False, 'error': 'Please login first'}), 401
    try:
        data = request.get_json()
        conversation_id = data.get('conversation_id')
        if not conversation_id:
            return jsonify({'success': False, 'error': 'Conversation ID is required'}), 400
        seller_email = session.get('email')
        if conversation_id.startswith('rider_order_'):
            order_id = conversation_id.replace('rider_order_', '')
            sb_admin.table('seller_rider_messages').delete().eq('order_id', order_id).execute()
        else:
            sb_admin.table('buyer_seller_messages').delete().eq('conversation_id', conversation_id).execute()
            sb_admin.table('conversations').delete().eq('conversation_id', conversation_id).eq('seller_email', seller_email).execute()
        return jsonify({'success': True, 'message': 'Conversation deleted successfully'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/seller/conversations/delete-all', methods=['POST'])
def delete_all_seller_conversations():
    if 'email' not in session:
        return jsonify({'success': False, 'error': 'Please login first'}), 401
    try:
        seller_email = session.get('email')
        conv_res = sb_admin.table('conversations').select('conversation_id').eq('seller_email', seller_email).execute()
        for c in (conv_res.data or []):
            sb_admin.table('buyer_seller_messages').delete().eq('conversation_id', c['conversation_id']).execute()
        sb_admin.table('conversations').delete().eq('seller_email', seller_email).execute()
        orders_res = sb_admin.table('orders').select('id').eq('seller_email', seller_email).execute()
        for o in (orders_res.data or []):
            sb_admin.table('seller_rider_messages').delete().eq('order_id', o['id']).execute()
        return jsonify({'success': True, 'message': 'All conversations deleted successfully'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/buyer/conversations/delete', methods=['POST'])
def delete_buyer_conversation():
    if 'email' not in session:
        return jsonify({'success': False, 'error': 'Please login first'}), 401
    try:
        data = request.get_json()
        conversation_id = data.get('conversation_id')
        if not conversation_id:
            return jsonify({'success': False, 'error': 'Conversation ID is required'}), 400
        buyer_email = session.get('email')
        if conversation_id.startswith('rider_order_'):
            order_id = conversation_id.replace('rider_order_', '')
            sb_admin.table('buyer_rider_messages').delete().eq('order_id', order_id).execute()
        else:
            sb_admin.table('buyer_seller_messages').delete().eq('conversation_id', conversation_id).execute()
            sb_admin.table('conversations').delete().eq('conversation_id', conversation_id).eq('buyer_email', buyer_email).execute()
        return jsonify({'success': True, 'message': 'Conversation deleted successfully'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/buyer/conversations/delete-all', methods=['POST'])
def delete_all_buyer_conversations():
    if 'email' not in session:
        return jsonify({'success': False, 'error': 'Please login first'}), 401
    try:
        buyer_email = session.get('email')
        conv_res = sb_admin.table('conversations').select('conversation_id').eq('buyer_email', buyer_email).execute()
        for c in (conv_res.data or []):
            sb_admin.table('buyer_seller_messages').delete().eq('conversation_id', c['conversation_id']).execute()
        sb_admin.table('conversations').delete().eq('buyer_email', buyer_email).execute()
        orders_res = sb_admin.table('orders').select('id').eq('email', buyer_email).execute()
        for o in (orders_res.data or []):
            sb_admin.table('buyer_rider_messages').delete().eq('order_id', o['id']).execute()
        return jsonify({'success': True, 'message': 'All conversations deleted successfully'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/messages/send-seller-reply', methods=['POST'])
def send_seller_reply():
    """Send a reply from seller to buyer"""
    # Check if user is logged in as seller
    if 'email' not in session:
        return jsonify({'success': False, 'error': 'Please login first'}), 401
    
    user_type = session.get('user_type')
    if user_type and user_type.lower() != 'seller':
        return jsonify({'success': False, 'error': 'Only sellers can send replies'}), 403
    
    try:
        data = request.get_json()
        buyer_email = data.get('buyer_email')
        message_text = data.get('message_text')
        product_id = data.get('product_id')
        conversation_id = data.get('conversation_id')
        order_id = data.get('order_id')
        
        if not buyer_email or not message_text:
            return jsonify({'success': False, 'error': 'Missing required fields'}), 400
        
        seller_email = session.get('email')
        
        # Use provided conversation_id or generate one
        if not conversation_id:
            conversation_id = f"{buyer_email}_{seller_email}_{product_id if product_id else 'general'}"
        
        # Upsert conversation in Supabase
        sb_admin.table('conversations').upsert({
            'conversation_id': conversation_id, 'buyer_email': buyer_email,
            'seller_email': seller_email, 'product_id': product_id, 'order_id': order_id,
            'last_message_at': datetime.now().isoformat(),
        }, on_conflict='conversation_id').execute()
        # Insert message
        ins = sb_admin.table('buyer_seller_messages').insert({
            'conversation_id': conversation_id, 'sender_email': seller_email,
            'receiver_email': buyer_email, 'sender_type': 'seller', 'message_text': message_text,
        }).execute()
        message_id = ins.data[0]['id'] if ins.data else None
        # Get seller name
        sn_res = sb_admin.table('users').select('business_name, first_name, last_name').eq('email', seller_email).limit(1).execute()
        seller_name = 'Seller'
        if sn_res.data:
            u = sn_res.data[0]
            seller_name = u.get('business_name') or f"{u.get('first_name','')} {u.get('last_name','')}".strip() or 'Seller'
        print(f"Seller {seller_name} sent message to buyer {buyer_email}")
        
        return jsonify({
            'success': True,
            'message_id': message_id,
            'message': 'Reply sent successfully'
        })
        
    except Exception as e:
        print(f"Error sending seller reply: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/buyer/messages', methods=['GET'])
def get_buyer_messages():
    if 'email' not in session:
        return jsonify({'success': False, 'error': 'Please login first'}), 401
    try:
        buyer_email = session.get('email')
        conv_res = sb_admin.table('conversations').select('*').eq('buyer_email', buyer_email).order('last_message_at', desc=True).limit(20).execute()
        conversations = conv_res.data or []
        product_ids = list({c['product_id'] for c in conversations if c.get('product_id')})
        prod_map = {}
        if product_ids:
            pr = sb_admin.table('products').select('id, name').in_('id', product_ids).execute()
            prod_map = {p['id']: p['name'] for p in (pr.data or [])}
        seller_emails = list({c['seller_email'] for c in conversations if c.get('seller_email')})
        seller_map = {}
        if seller_emails:
            sr = sb_admin.table('users').select('email, business_name, first_name, last_name, profile_picture').in_('email', seller_emails).execute()
            for u in (sr.data or []):
                seller_map[u['email']] = u
        formatted = []
        for c in conversations:
            se = c.get('seller_email', '')
            seller = seller_map.get(se, {})
            seller_name = seller.get('business_name') or f"{seller.get('first_name','')} {seller.get('last_name','')}".strip() or 'Seller'
            try:
                unread = sb_admin.table('buyer_seller_messages').select('id', count='exact').eq('conversation_id', c['conversation_id']).eq('receiver_email', buyer_email).eq('is_read', False).execute()
                unread_count = unread.count or 0
            except Exception:
                unread_count = 0
            formatted.append({
                'conversation_id': c['conversation_id'], 'seller_email': se,
                'product_id': c.get('product_id'), 'order_id': c.get('order_id'),
                'last_message_at': str(c.get('last_message_at') or ''),
                'product_name': prod_map.get(c.get('product_id'), ''),
                'seller_name': seller_name, 'unread_count': unread_count,
                'last_message': '', 'seller_profile_picture': seller.get('profile_picture'),
                'conversation_type': 'seller',
            })
        return jsonify({'success': True, 'conversations': formatted})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/buyer/rider-messages', methods=['GET'])
def get_buyer_rider_messages():
    """Get chat messages between buyer and rider for a specific order"""
    if 'email' not in session:
        return jsonify({'success': False, 'error': 'Please login first'}), 401

    try:
        buyer_email = session.get('email')
        order_id    = request.args.get('order_id')
        if not order_id:
            return jsonify({'success': False, 'error': 'Missing order_id'}), 400

        order_res = sb_admin.table('orders').select('rider_email').eq('id', order_id).eq('email', buyer_email).execute()
        if not order_res.data:
            return jsonify({'success': False, 'error': 'Order not found'}), 404

        rider_email = order_res.data[0].get('rider_email', '')
        emails = list({e for e in [buyer_email, rider_email] if e})
        users_map = {}
        if emails:
            ur = sb_admin.table('users').select('email, first_name, last_name, profile_picture').in_('email', emails).execute()
            users_map = {u['email']: u for u in (ur.data or [])}

        rider = users_map.get(rider_email, {})
        buyer = users_map.get(buyer_email, {})

        msgs_res = sb_admin.table('buyer_rider_messages').select('sender_email, receiver_email, message, created_at').eq('order_id', order_id).order('created_at').execute()
        messages = [{'sender_email': m['sender_email'], 'receiver_email': m['receiver_email'], 'message': m['message'], 'created_at': m['created_at']} for m in (msgs_res.data or [])]

        return jsonify({
            'success':               True,
            'messages':              messages,
            'rider_name':            f"{rider.get('first_name','')} {rider.get('last_name','')}".strip() or 'Rider',
            'rider_email':           rider_email,
            'rider_profile_picture': rider.get('profile_picture'),
            'buyer_name':            f"{buyer.get('first_name','')} {buyer.get('last_name','')}".strip() or 'Buyer',
            'buyer_email':           buyer_email,
            'buyer_profile_picture': buyer.get('profile_picture'),
            'order_id':              order_id,
        })
    except Exception as e:
        print(f"Error getting buyer-rider messages: {e}")
        import traceback; traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/buyer/rider-messages/mark-read', methods=['POST'])
def mark_buyer_rider_messages_read():
    """Mark buyer-rider messages as read for a specific order (buyer side)"""
    if 'email' not in session:
        return jsonify({'success': False, 'error': 'Please login first'}), 401

    buyer_email = session.get('email')
    order_id    = (request.get_json() or {}).get('order_id')
    if not order_id:
        return jsonify({'success': False, 'error': 'Missing order_id'}), 400

    try:
        # Verify order belongs to this buyer
        order_res = sb_admin.table('orders').select('id').eq('id', order_id).eq('email', buyer_email).execute()
        if not order_res.data:
            return jsonify({'success': False, 'error': 'Order not found or unauthorized'}), 404

        res = sb_admin.table('buyer_rider_messages').update({'is_read': True}).eq('order_id', order_id).eq('receiver_email', buyer_email).eq('is_read', False).execute()
        return jsonify({'success': True, 'affected_rows': len(res.data or [])})
    except Exception as e:
        print(f"Error marking buyer-rider messages as read: {e}")
        import traceback; traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/buyer/send-rider-message', methods=['POST'])
def send_buyer_rider_message():
    """Send a message from buyer to rider"""
    if 'email' not in session:
        return jsonify({'success': False, 'error': 'Please login first'}), 401

    try:
        buyer_email = session.get('email')
        data        = request.get_json()
        order_id    = data.get('order_id')
        message     = data.get('message')

        if not order_id or not message:
            return jsonify({'success': False, 'error': 'Missing required fields (order_id and message)'}), 400

        order_res = sb_admin.table('orders').select('rider_email').eq('id', order_id).eq('email', buyer_email).execute()
        if not order_res.data or not order_res.data[0].get('rider_email'):
            return jsonify({'success': False, 'error': 'Order not found or no rider assigned'}), 404

        rider_email = order_res.data[0]['rider_email']
        sb_admin.table('buyer_rider_messages').insert({'order_id': order_id, 'sender_email': buyer_email, 'receiver_email': rider_email, 'message': message}).execute()
        return jsonify({'success': True, 'message': 'Message sent successfully'})
    except Exception as e:
        print(f"Error sending rider message: {e}")
        import traceback; traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

# ==================== BUYER-SELLER ORDER MESSAGING API ROUTES ====================

@app.route('/get_buyer_seller_messages_order', methods=['GET'])
def get_buyer_seller_messages_order():
    if 'email' not in session:
        return jsonify({'success': False, 'error': 'Please login first'}), 401
    try:
        buyer_email  = request.args.get('buyer_email')
        seller_email = request.args.get('seller_email')
        order_id     = request.args.get('order_id')
        if not all([buyer_email, seller_email, order_id]):
            return jsonify({'success': False, 'error': 'Missing required parameters'}), 400
        session_email = session.get('email')
        if session_email not in [buyer_email, seller_email]:
            return jsonify({'success': False, 'error': 'Unauthorized'}), 403
        conversation_id = f"order_{order_id}_{buyer_email}_{seller_email}"
        msgs_res = sb_admin.table('buyer_seller_messages').select('id, sender_email, receiver_email, message_text, sender_type, is_read, created_at').eq('conversation_id', conversation_id).order('created_at').execute()
        messages = msgs_res.data or []
        # Mark as read
        sb_admin.table('buyer_seller_messages').update({'is_read': True}).eq('conversation_id', conversation_id).eq('receiver_email', session_email).eq('is_read', False).execute()
        return jsonify({'success': True, 'messages': messages, 'conversation_id': conversation_id})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/send_buyer_seller_message_order', methods=['POST'])
def send_buyer_seller_message_order():
    if 'email' not in session:
        return jsonify({'success': False, 'error': 'Please login first'}), 401
    try:
        data = request.get_json()
        buyer_email  = data.get('buyer_email')
        seller_email = data.get('seller_email')
        order_id     = data.get('order_id')
        message      = data.get('message')
        if not all([buyer_email, seller_email, order_id, message]):
            return jsonify({'success': False, 'error': 'Missing required fields'}), 400
        session_email = session.get('email')
        if session_email not in [buyer_email, seller_email]:
            return jsonify({'success': False, 'error': 'Unauthorized'}), 403
        sender_email   = session_email
        receiver_email = seller_email if sender_email == buyer_email else buyer_email
        sender_type    = 'buyer' if sender_email == buyer_email else 'seller'
        conversation_id = f"order_{order_id}_{buyer_email}_{seller_email}"
        # Upsert conversation
        sb_admin.table('conversations').upsert({
            'conversation_id': conversation_id, 'buyer_email': buyer_email,
            'seller_email': seller_email, 'order_id': order_id,
            'last_message_at': datetime.now().isoformat(),
        }, on_conflict='conversation_id').execute()
        # Insert message
        sb_admin.table('buyer_seller_messages').insert({
            'conversation_id': conversation_id, 'sender_email': sender_email,
            'receiver_email': receiver_email, 'sender_type': sender_type, 'message_text': message,
        }).execute()
        return jsonify({'success': True, 'message': 'Message sent successfully'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/get_seller_name', methods=['GET'])
def get_seller_name():
    try:
        seller_email = request.args.get('email') or request.args.get('seller_email')
        if not seller_email:
            return jsonify({'success': False, 'error': 'Missing email parameter'}), 400
        res = sb_admin.table('users').select('business_name, first_name, last_name').eq('email', seller_email).limit(1).execute()
        if res.data:
            u = res.data[0]
            name = u.get('business_name') or f"{u.get('first_name','')} {u.get('last_name','')}".strip() or seller_email
            return jsonify({'success': True, 'name': name})
        return jsonify({'success': False, 'error': 'Seller not found'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@app.route('/get_seller_info', methods=['GET'])
def get_seller_info():
    try:
        seller_email = request.args.get('email') or request.args.get('seller_email')
        if not seller_email:
            return jsonify({'success': False, 'error': 'Missing email parameter'}), 400
        res = sb_admin.table('users').select('business_name, first_name, last_name, profile_picture').eq('email', seller_email).limit(1).execute()
        if res.data:
            u = res.data[0]
            name = u.get('business_name') or f"{u.get('first_name','')} {u.get('last_name','')}".strip() or seller_email
            return jsonify({'success': True, 'name': name, 'profile_picture': u.get('profile_picture')})
        return jsonify({'success': False, 'error': 'Seller not found'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@app.route('/api/messages/seller-rider-conversation', methods=['GET'])
def get_seller_rider_conversation():
    """Get conversation messages between seller and rider for a specific order"""
    if 'email' not in session:
        return jsonify({'success': False, 'error': 'Please login first'}), 401

    try:
        seller_email = session.get('email')
        rider_email  = request.args.get('rider_email')
        order_id     = request.args.get('order_id')

        if not rider_email or not order_id:
            return jsonify({'success': False, 'error': 'Missing rider_email or order_id'}), 400

        # Verify order belongs to this seller
        order_res = sb_admin.table('orders').select('id').eq('id', order_id).eq('seller_email', seller_email).execute()
        if not order_res.data:
            return jsonify({'success': False, 'error': 'Order not found or unauthorized'}), 404

        emails = list({e for e in [seller_email, rider_email] if e})
        users_map = {}
        if emails:
            ur = sb_admin.table('users').select('email, first_name, last_name, business_name, profile_picture').in_('email', emails).execute()
            users_map = {u['email']: u for u in (ur.data or [])}

        rider  = users_map.get(rider_email, {})
        seller = users_map.get(seller_email, {})

        msgs_res = sb_admin.table('seller_rider_messages').select('id, order_id, sender_email, receiver_email, message, is_read, created_at').eq('order_id', order_id).order('created_at').execute()
        messages = []
        for m in (msgs_res.data or []):
            sender_type = 'seller' if m['sender_email'] == seller_email else 'rider'
            messages.append({**m, 'message_text': m['message'], 'sender_type': sender_type})

        return jsonify({
            'success':               True,
            'messages':              messages,
            'rider_name':            f"{rider.get('first_name','')} {rider.get('last_name','')}".strip() or 'Rider',
            'rider_email':           rider_email,
            'rider_profile_picture': rider.get('profile_picture'),
            'seller_name':           seller.get('business_name') or f"{seller.get('first_name','')} {seller.get('last_name','')}".strip() or 'Seller',
            'seller_email':          seller_email,
            'seller_profile_picture': seller.get('profile_picture'),
            'order_id':              order_id,
            'conversation_id':       f"{rider_email}_{seller_email}_{order_id}",
        })
    except Exception as e:
        print(f"Error getting seller-rider conversation: {e}")
        import traceback; traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/messages/send-seller-rider-message', methods=['POST'])
def send_seller_rider_message():
    """Send a message from seller to rider"""
    if 'email' not in session:
        return jsonify({'success': False, 'error': 'Please login first'}), 401

    try:
        seller_email = session.get('email')
        data         = request.get_json()
        rider_email  = data.get('rider_email')
        order_id     = data.get('order_id')
        message_text = data.get('message_text')

        if not rider_email or not order_id or not message_text:
            return jsonify({'success': False, 'error': 'Missing required fields'}), 400

        order_res = sb_admin.table('orders').select('id').eq('id', order_id).eq('seller_email', seller_email).eq('rider_email', rider_email).execute()
        if not order_res.data:
            return jsonify({'success': False, 'error': 'Order not found or unauthorized'}), 404

        res = sb_admin.table('seller_rider_messages').insert({'order_id': order_id, 'sender_email': seller_email, 'receiver_email': rider_email, 'message': message_text}).execute()
        message_id = res.data[0]['id'] if res.data else None
        return jsonify({'success': True, 'message_id': message_id, 'message': 'Message sent successfully'})
    except Exception as e:
        print(f"Error sending seller-rider message: {e}")
        import traceback; traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/seller/rider-messages/mark-read', methods=['POST'])
def mark_seller_rider_messages_read():
    """Mark seller-rider messages as read for a specific order for seller"""
    print("?? Mark seller-rider messages as read endpoint called")

    if 'email' not in session:
        return jsonify({'success': False, 'error': 'Please login first'}), 401

    seller_email = session.get('email')
    order_id     = (request.get_json() or {}).get('order_id')
    if not order_id:
        return jsonify({'success': False, 'error': 'Missing order_id'}), 400

    try:
        res = sb_admin.table('seller_rider_messages').update({'is_read': True}).eq('order_id', order_id).eq('receiver_email', seller_email).eq('is_read', False).execute()
        affected = len(res.data or [])
        print(f"? Marked {affected} seller-rider messages as read for order {order_id}")
        return jsonify({'success': True, 'affected_rows': affected})
    except Exception as e:
        print(f"Error marking seller-rider messages as read: {e}")
        import traceback; traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/messages/send-rider-seller-message', methods=['POST'])
def send_rider_seller_message():
    """Send a message from rider to seller"""
    if 'email' not in session:
        return jsonify({'success': False, 'error': 'Please login first'}), 401

    try:
        rider_email  = session.get('email')
        data         = request.get_json()
        seller_email = data.get('seller_email')
        order_id     = data.get('order_id')
        message_text = data.get('message_text')

        if not seller_email or not order_id or not message_text:
            return jsonify({'success': False, 'error': 'Missing required fields'}), 400

        order_res = sb_admin.table('orders').select('id').eq('id', order_id).eq('seller_email', seller_email).eq('rider_email', rider_email).execute()
        if not order_res.data:
            return jsonify({'success': False, 'error': 'Order not found or unauthorized'}), 404

        res = sb_admin.table('seller_rider_messages').insert({'order_id': order_id, 'sender_email': rider_email, 'receiver_email': seller_email, 'message': message_text}).execute()
        message_id = res.data[0]['id'] if res.data else None
        return jsonify({'success': True, 'message_id': message_id, 'message': 'Message sent successfully'})
    except Exception as e:
        print(f"Error sending rider-seller message: {e}")
        import traceback; traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/messages/rider-seller-conversation', methods=['GET'])
def get_rider_seller_conversation():
    """Get conversation messages between rider and seller for a specific order"""
    if 'email' not in session:
        return jsonify({'success': False, 'error': 'Please login first'}), 401

    try:
        rider_email  = session.get('email')
        seller_email = request.args.get('seller_email')
        order_id     = request.args.get('order_id')

        if not seller_email or not order_id:
            return jsonify({'success': False, 'error': 'Missing seller_email or order_id'}), 400

        order_res = sb_admin.table('orders').select('id').eq('id', order_id).eq('rider_email', rider_email).execute()
        if not order_res.data:
            return jsonify({'success': False, 'error': 'Order not found or unauthorized'}), 404

        emails = list({e for e in [seller_email, rider_email] if e})
        users_map = {}
        if emails:
            ur = sb_admin.table('users').select('email, first_name, last_name, business_name, profile_picture').in_('email', emails).execute()
            users_map = {u['email']: u for u in (ur.data or [])}

        seller = users_map.get(seller_email, {})
        rider  = users_map.get(rider_email, {})

        msgs_res = sb_admin.table('seller_rider_messages').select('id, order_id, sender_email, receiver_email, message, is_read, created_at').eq('order_id', order_id).order('created_at').execute()
        messages = []
        for m in (msgs_res.data or []):
            sender_type = 'rider' if m['sender_email'] == rider_email else 'seller'
            messages.append({**m, 'message_text': m['message'], 'sender_type': sender_type})

        return jsonify({
            'success':               True,
            'messages':              messages,
            'seller_name':           seller.get('business_name') or f"{seller.get('first_name','')} {seller.get('last_name','')}".strip() or 'Seller',
            'seller_email':          seller_email,
            'seller_profile_picture': seller.get('profile_picture'),
            'rider_name':            f"{rider.get('first_name','')} {rider.get('last_name','')}".strip() or 'Rider',
            'rider_email':           rider_email,
            'rider_profile_picture': rider.get('profile_picture'),
            'conversation_id':       f"{seller_email}_{rider_email}_{order_id}",
        })
    except Exception as e:
        print(f"Error getting rider-seller conversation: {e}")
        import traceback; traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

# ==================== END SELLER-RIDER MESSAGING API ROUTES ====================

@app.route('/messages')
def messages_inbox():
    if 'email' not in session:
        flash('Please login first', 'warning')
        return redirect(url_for('login'))
    try:
        user_email = session.get('email')
        user_type  = session.get('user_type', '').lower()
        if user_type == 'seller':
            conv_res = sb_admin.table('conversations').select('*').eq('seller_email', user_email).order('last_message_at', desc=True).execute()
        else:
            conv_res = sb_admin.table('conversations').select('*').eq('buyer_email', user_email).order('last_message_at', desc=True).execute()
        conversations = conv_res.data or []
        # Enrich with product names and unread counts
        product_ids = list({c['product_id'] for c in conversations if c.get('product_id')})
        prod_map = {}
        if product_ids:
            pr = sb_admin.table('products').select('id, name').in_('id', product_ids).execute()
            prod_map = {p['id']: p['name'] for p in (pr.data or [])}
        other_emails = list({c['buyer_email'] if user_type == 'seller' else c['seller_email'] for c in conversations})
        user_map = {}
        if other_emails:
            ur = sb_admin.table('users').select('email, first_name, last_name, business_name').in_('email', other_emails).execute()
            user_map = {u['email']: u for u in (ur.data or [])}
        for c in conversations:
            c['product_name'] = prod_map.get(c.get('product_id'), '')
            other_email = c['buyer_email'] if user_type == 'seller' else c['seller_email']
            other = user_map.get(other_email, {})
            c['first_name'] = other.get('first_name', '')
            c['last_name']  = other.get('last_name', '')
            c['business_name'] = other.get('business_name', '')
            # Unread count
            try:
                unread = sb_admin.table('buyer_seller_messages').select('id', count='exact').eq('conversation_id', c['conversation_id']).eq('receiver_email', user_email).eq('is_read', False).execute()
                c['unread_count'] = unread.count or 0
            except Exception:
                c['unread_count'] = 0
        return render_template('messages_inbox.html', conversations=conversations, user_type=user_type)
    except Exception as e:
        print(f"Error loading messages inbox: {e}")
        flash('Error loading messages', 'danger')
        return redirect(url_for('homepage'))

@app.route('/debug-session')
def debug_session():
    """Debug endpoint to check session data"""
    session_data = {
        'email': session.get('email'),
        'user_type': session.get('user_type'),
        'user_id': session.get('user_id'),
        'all_session_keys': list(session.keys())
    }
    
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Debug Session</title>
        <style>
            body {{ font-family: Arial, sans-serif; margin: 20px; }}
            .info {{ background: #f0f0f0; padding: 15px; border-radius: 5px; margin: 10px 0; }}
            h2 {{ color: #1a1a1a; border-bottom: 2px solid #d4af37; padding-bottom: 10px; }}
        </style>
    </head>
    <body>
        <h1>?? Session Debug Info</h1>
        <div class="info">
            <h2>Current Session Data:</h2>
            <p><strong>Email:</strong> {session_data['email']}</p>
            <p><strong>User Type:</strong> {session_data['user_type']}</p>
            <p><strong>User ID:</strong> {session_data['user_id']}</p>
            <p><strong>All Session Keys:</strong> {', '.join(session_data['all_session_keys'])}</p>
        </div>
        
        <h2>What should it be?</h2>
        <p>For sellers, <code>user_type</code> should be: <strong>'seller'</strong></p>
        <p>For buyers, <code>user_type</code> should be: <strong>'buyer'</strong></p>
        
        <h2>Fix:</h2>
        <p>If you're a seller but user_type is wrong, try:</p>
        <ol>
            <li>Logout completely</li>
            <li>Login again using your seller credentials</li>
            <li>Make sure you're logging in through the seller login page</li>
        </ol>
        
        <p><a href="/debug-conversations">View Conversations</a> | <a href="/test-messaging-setup">Status Page</a></p>
    </body>
    </html>
    """
    
    return html

# @app.route('/debug-conversations') removed (debug route)

# /test-messaging-setup removed

@app.route('/admin/migrate-product-images', methods=['GET', 'POST'])
def migrate_product_images():
    """
    One-time migration: uploads all local product images to Supabase Storage
    and updates the image column with the public URL.
    Access: GET to preview, POST to execute.
    Only accessible when logged in as a seller or admin.
    """
    if 'user_id' not in session:
        return jsonify({'error': 'Login required'}), 401

    STORAGE_BUCKET = 'product-images'
    results = {'migrated': [], 'skipped': [], 'errors': []}

    try:
        # Fetch all products whose image column contains plain filenames (not full URLs)
        res = sb_admin.table('products').select('id, image').execute()
        products = res.data or []

        for product in products:
            raw_image = product.get('image', '') or ''
            if not raw_image.strip():
                continue

            parts = [p.strip() for p in raw_image.split(',') if p.strip()]
            new_parts = []
            changed = False

            for part in parts:
                # Already a full URL � skip
                if part.startswith('http://') or part.startswith('https://'):
                    new_parts.append(part)
                    continue

                # Plain filename � upload to Supabase Storage
                local_path = os.path.join(app.config['UPLOAD_FOLDER'], part)
                if not os.path.exists(local_path):
                    results['errors'].append(f"Product {product['id']}: file not found: {part}")
                    new_parts.append(part)  # keep original
                    continue

                if request.method == 'GET':
                    # Preview only
                    results['migrated'].append(f"Product {product['id']}: {part} ? would upload")
                    new_parts.append(part)
                    continue

                try:
                    with open(local_path, 'rb') as f:
                        file_bytes = f.read()
                    ext = part.rsplit('.', 1)[-1].lower()
                    content_type = f'image/{ext}' if ext in ('jpg', 'jpeg', 'png', 'gif', 'webp') else 'image/jpeg'
                    storage_path = f'products/{part}'

                    sb_admin.storage.from_(STORAGE_BUCKET).upload(
                        path=storage_path,
                        file=file_bytes,
                        file_options={'content-type': content_type, 'upsert': 'true'},
                    )
                    public_url = f"{SUPABASE_URL}/storage/v1/object/public/{STORAGE_BUCKET}/{storage_path}"
                    new_parts.append(public_url)
                    changed = True
                    results['migrated'].append(f"Product {product['id']}: {part} ? {public_url}")
                except Exception as upload_err:
                    results['errors'].append(f"Product {product['id']}: {part} ? {upload_err}")
                    new_parts.append(part)

            # Update the image column if any part changed
            if changed and request.method == 'POST':
                new_image = ','.join(new_parts)
                sb_admin.table('products').update({'image': new_image}).eq('id', product['id']).execute()

    except Exception as e:
        return jsonify({'error': str(e)}), 500

    return jsonify({
        'mode': 'preview' if request.method == 'GET' else 'executed',
        'results': results,
        'summary': {
            'migrated': len(results['migrated']),
            'skipped': len(results['skipped']),
            'errors': len(results['errors']),
        }
    })



@app.route('/debug-orders')
def debug_orders():
    """Debug: show raw order date fields from Supabase"""
    if session.get('user_type') not in ('Admin', 'Seller'):
        return 'Admin/Seller only', 403
    try:
        seller_email = session.get('email')
        res = sb_admin.table('orders') \
            .select('id, status, date, delivered_at, received_at, cancelled_at') \
            .eq('seller_email', seller_email) \
            .in_('status', ['Completed', 'Cancelled']) \
            .limit(10).execute()
        rows = res.data or []
        html = '<h2>Order Date Fields (raw from Supabase)</h2><table border=1 cellpadding=5>'
        html += '<tr><th>ID</th><th>Status</th><th>date</th><th>delivered_at</th><th>received_at</th><th>cancelled_at</th></tr>'
        for r in rows:
            html += f"<tr><td>{r['id']}</td><td>{r['status']}</td><td>{r.get('date','NULL')}</td><td>{r.get('delivered_at','NULL')}</td><td>{r.get('received_at','NULL')}</td><td>{r.get('cancelled_at','NULL')}</td></tr>"
        html += '</table>'
        return html
    except Exception as e:
        import traceback
        return f"<pre>Error: {e}\n{traceback.format_exc()}</pre>"

if __name__ == '__main__':
    # Supabase-only mode - no MySQL initialization needed
    # Ensure Supabase Storage bucket for product images exists
    try:
        buckets = [b.name for b in sb_admin.storage.list_buckets()]
        if 'product-images' not in buckets:
            sb_admin.storage.create_bucket('product-images', options={'public': True})
            print("Created Supabase Storage bucket: product-images (public)")
        else:
            print("Supabase Storage bucket 'product-images' already exists")
    except Exception as _bucket_err:
        print(f"Could not verify/create product-images bucket: {_bucket_err}")

    app.run(
        host="0.0.0.0",
        port=5000,
        debug=True,
        threaded=True,
        use_reloader=False
    )

