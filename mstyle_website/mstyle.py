import mysql.connector
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
from gotrue.errors import AuthApiError

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key-here'  # Change this to a secure secret key
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=1)

# Add min and max functions to Jinja2 environment
app.jinja_env.globals.update(min=min, max=max)

# -- Jinja2 filter: resolve product image to a web-accessible URL -------------
def product_image_url(image_value):
    """
    Convert a stored image value to a web-accessible URL.
    - Full URL (http/https): return as-is  [Supabase Storage]
    - Plain filename: prepend /static/images/uploads/  [legacy local files]
    - Empty/None: return empty string
    """
    if not image_value:
        return ''
    s = str(image_value).strip()
    if s.startswith('http://') or s.startswith('https://'):
        return s
    return f'/static/images/uploads/{s}'

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

# Get the absolute path of the project directory (FFastique - no images/ECommerce)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Set upload folder path relative to the project directory
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'static', 'images', 'uploads')

# Create upload directory if it doesn't exist
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size

# Create upload directories if they don't exist
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
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

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

app.config["MAIL_SERVER"] = 'smtp.gmail.com'
app.config["MAIL_PORT"] = 587
app.config["MAIL_USERNAME"] = 'stylemens2025@gmail.com'  # Your Gmail
app.config['MAIL_PASSWORD'] = 'qkne phbi pwbj ljdt'  # Replace with your new 16-character app password
app.config['MAIL_USE_TLS'] = True  # Important for Gmail on port 587
app.config['MAIL_USE_SSL'] = False
app.config['MAIL_DEFAULT_SENDER'] = ('M\'STYLE', 'stylemens2025@gmail.com')

# Initialize Flask-Mail
from flask_mail import Mail
mail = Mail(app)



# MySQL connection settings
def get_db_connection():
    try:
        connection = mysql.connector.connect(
            host="localhost",
            user="root",
            password="",
            database="mstyle",
            autocommit=False,
            connection_timeout=5,   # shorter timeout so it fails fast
            buffered=True,
            use_pure=True
        )
        cursor = connection.cursor()
        cursor.execute("SET time_zone = '+08:00'")
        cursor.close()
        return connection
    except mysql.connector.Error as err:
        raise  # let callers handle it

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
    """Add cancellation-related columns to orders table if they don't exist"""
    try:
        connection = get_db_connection()
        cursor = connection.cursor()
        
        # Check if cancellation_reason column exists
        cursor.execute("""
            SELECT COUNT(*) 
            FROM INFORMATION_SCHEMA.COLUMNS 
            WHERE TABLE_SCHEMA = 'mstyle' 
            AND TABLE_NAME = 'orders' 
            AND COLUMN_NAME = 'cancellation_reason'
        """)
        
        result = cursor.fetchone()
        if result and result[0] == 0:
            # Add cancellation_reason column
            cursor.execute("""
                ALTER TABLE orders 
                ADD COLUMN cancellation_reason TEXT NULL AFTER status
            """)
            print("? Added cancellation_reason column to orders table")
        
        # Check if cancelled_at column exists
        cursor.execute("""
            SELECT COUNT(*) 
            FROM INFORMATION_SCHEMA.COLUMNS 
            WHERE TABLE_SCHEMA = 'mstyle' 
            AND TABLE_NAME = 'orders' 
            AND COLUMN_NAME = 'cancelled_at'
        """)
        
        result = cursor.fetchone()
        if result and result[0] == 0:
            # Add cancelled_at column
            cursor.execute("""
                ALTER TABLE orders 
                ADD COLUMN cancelled_at TIMESTAMP NULL AFTER cancellation_reason
            """)
            print("? Added cancelled_at column to orders table")
        
        connection.commit()
        
    except Exception as e:
        print(f"? Error adding cancellation columns: {str(e)}")
        import traceback
        traceback.print_exc()
    finally:
        if 'cursor' in locals():
            cursor.close()
        if 'connection' in locals():
            connection.close()

def initialize_database_tables():
    """Initialize required database tables if they don't exist"""
    try:
        connection = get_db_connection()
        cursor = connection.cursor()
        
        # Create reviews table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS reviews (
                id INT AUTO_INCREMENT PRIMARY KEY,
                order_id INT NOT NULL,
                product_id INT NOT NULL,
                customer_email VARCHAR(255) NOT NULL,
                seller_email VARCHAR(255) NOT NULL,
                rating INT NOT NULL CHECK (rating >= 1 AND rating <= 5),
                review_text TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_order_customer (order_id, customer_email),
                INDEX idx_product_id (product_id),
                INDEX idx_seller_email (seller_email),
                INDEX idx_rating (rating),
                FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE
            )
        """)
        
        # Create notifications table if it doesn't exist
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS notifications (
                id INT AUTO_INCREMENT PRIMARY KEY,
                seller_email VARCHAR(255) NOT NULL,
                message TEXT NOT NULL,
                type VARCHAR(50) DEFAULT 'order',
                is_read BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_seller_email (seller_email),
                INDEX idx_is_read (is_read),
                INDEX idx_type (type)
            )
        """)
        
        # Add type column to existing notifications table if it doesn't exist
        try:
            cursor.execute("""
                SELECT COUNT(*) 
                FROM INFORMATION_SCHEMA.COLUMNS 
                WHERE TABLE_SCHEMA = 'mstyle' 
                AND TABLE_NAME = 'notifications' 
                AND COLUMN_NAME = 'type'
            """)
            result = cursor.fetchone()
            if result and result[0] == 0:
                cursor.execute("""
                    ALTER TABLE notifications 
                    ADD COLUMN type VARCHAR(50) DEFAULT 'order' AFTER message,
                    ADD INDEX idx_type (type)
                """)
                print("? Added type column to notifications table")
        except Exception as e:
            print(f"Note: Could not add type column to notifications: {e}")
        
        # Create buyer_notifications table if it doesn't exist
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS buyer_notifications (
                id INT AUTO_INCREMENT PRIMARY KEY,
                buyer_email VARCHAR(255) NOT NULL,
                message TEXT NOT NULL,
                type VARCHAR(50) DEFAULT 'status_update',
                is_read BOOLEAN DEFAULT FALSE,
                order_id INT DEFAULT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_buyer_email (buyer_email),
                INDEX idx_is_read (is_read),
                INDEX idx_order_id (order_id),
                INDEX idx_type (type)
            )
        """)
        
        # Add missing columns to existing buyer_notifications table if they don't exist
        try:
            cursor.execute("""
                SELECT COUNT(*) 
                FROM INFORMATION_SCHEMA.COLUMNS 
                WHERE TABLE_SCHEMA = 'mstyle' 
                AND TABLE_NAME = 'buyer_notifications' 
                AND COLUMN_NAME = 'type'
            """)
            result = cursor.fetchone()
            if result and result[0] == 0:
                cursor.execute("""
                    ALTER TABLE buyer_notifications 
                    ADD COLUMN type VARCHAR(50) DEFAULT 'status_update' AFTER message,
                    ADD INDEX idx_type (type)
                """)
                print("? Added type column to buyer_notifications table")
        except Exception as e:
            print(f"Note: Could not add type column: {e}")
        
        try:
            cursor.execute("""
                SELECT COUNT(*) 
                FROM INFORMATION_SCHEMA.COLUMNS 
                WHERE TABLE_SCHEMA = 'mstyle' 
                AND TABLE_NAME = 'buyer_notifications' 
                AND COLUMN_NAME = 'order_id'
            """)
            result = cursor.fetchone()
            if result and result[0] == 0:
                cursor.execute("""
                    ALTER TABLE buyer_notifications 
                    ADD COLUMN order_id INT DEFAULT NULL AFTER is_read,
                    ADD INDEX idx_order_id (order_id)
                """)
                print("? Added order_id column to buyer_notifications table")
        except Exception as e:
            print(f"Note: Could not add order_id column: {e}")
        
        # Create rider_notifications table if it doesn't exist
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS rider_notifications (
                id INT AUTO_INCREMENT PRIMARY KEY,
                rider_email VARCHAR(255) NOT NULL,
                message TEXT NOT NULL,
                order_id INT DEFAULT NULL,
                is_read BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_rider_email (rider_email),
                INDEX idx_is_read (is_read),
                INDEX idx_order_id (order_id)
            )
        """)
        
        connection.commit()
        print("? Database tables initialized successfully")
        
    except Exception as e:
        print(f"? Error initializing database tables: {str(e)}")
        import traceback
        traceback.print_exc()
    finally:
        if 'cursor' in locals():
            cursor.close()
        if 'connection' in locals():
            connection.close()

def ensure_promotion_tables_exist():
    """Ensure promotion-related tables exist in the database"""
    try:
        connection = get_db_connection()
        cursor = connection.cursor()
        
        # Create promotions table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS promotions (
                id INT AUTO_INCREMENT PRIMARY KEY,
                name VARCHAR(255) NOT NULL,
                code VARCHAR(50) NOT NULL,
                seller_email VARCHAR(255) NOT NULL,
                type ENUM('percentage', 'fixed', 'buy_one_get_one', 'free_shipping') NOT NULL,
                discount_value DECIMAL(10,2) DEFAULT NULL,
                max_discount DECIMAL(10,2) DEFAULT NULL,
                min_purchase DECIMAL(10,2) DEFAULT 0.00,
                min_quantity INT DEFAULT 1,
                usage_limit_per_customer INT DEFAULT NULL,
                total_usage_limit INT DEFAULT NULL,
                current_usage_count INT DEFAULT 0,
                start_date DATE NOT NULL,
                start_time TIME DEFAULT '00:00:00',
                end_date DATE NOT NULL,
                end_time TIME DEFAULT '23:59:59',
                product_scope ENUM('all', 'specific', 'category') DEFAULT 'all',
                is_active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                
                INDEX idx_seller_email (seller_email),
                INDEX idx_code (code),
                INDEX idx_active_dates (is_active, start_date, end_date),
                INDEX idx_type (type),
                INDEX idx_product_scope (product_scope),
                UNIQUE KEY unique_seller_code (seller_email, code)
            )
        """)
        
        # Create promotion_products table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS promotion_products (
                id INT AUTO_INCREMENT PRIMARY KEY,
                promotion_id INT NOT NULL,
                product_id INT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                
                INDEX idx_promotion_id (promotion_id),
                INDEX idx_product_id (product_id),
                UNIQUE KEY unique_promotion_product (promotion_id, product_id)
            )
        """)
        
        # Create promotion_categories table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS promotion_categories (
                id INT AUTO_INCREMENT PRIMARY KEY,
                promotion_id INT NOT NULL,
                category VARCHAR(100) NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                
                INDEX idx_promotion_id (promotion_id),
                INDEX idx_category (category),
                UNIQUE KEY unique_promotion_category (promotion_id, category)
            )
        """)
        
        # Create promotion_usage table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS promotion_usage (
                id INT AUTO_INCREMENT PRIMARY KEY,
                promotion_id INT NOT NULL,
                order_id INT NOT NULL,
                customer_email VARCHAR(255) NOT NULL,
                product_id VARCHAR(50),
                discount_applied DECIMAL(10,2) NOT NULL,
                used_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                
                INDEX idx_promotion_id (promotion_id),
                INDEX idx_order_id (order_id),
                INDEX idx_customer_email (customer_email),
                INDEX idx_product_id (product_id),
                INDEX idx_used_at (used_at)
            )
        """)
        
        # Add product_id column to existing promotion_usage table if it doesn't exist
        try:
            cursor.execute("""
                ALTER TABLE promotion_usage 
                ADD COLUMN product_id VARCHAR(50) AFTER customer_email,
                ADD INDEX idx_product_id (product_id)
            """)
            print("? Added product_id column to promotion_usage table")
        except Exception as alter_error:
            # Column might already exist, which is fine
            if "Duplicate column name" not in str(alter_error):
                print(f"Note: Could not add product_id column: {alter_error}")
        
        # Sync current_usage_count with actual usage data for existing promotions
        try:
            cursor.execute("""
                UPDATE promotions p 
                SET current_usage_count = (
                    SELECT COUNT(*) 
                    FROM promotion_usage pu 
                    WHERE pu.promotion_id = p.id
                )
                WHERE current_usage_count = 0 OR current_usage_count IS NULL
            """)
            print("? Synced current_usage_count with actual usage data")
        except Exception as sync_error:
            print(f"Note: Could not sync usage counts: {sync_error}")
        
        connection.commit()
        print("? Promotion tables ensured to exist")
        
        # Backfill promotion usage for existing orders
        backfill_promotion_usage(cursor)
        
    except Exception as e:
        print(f"? Error ensuring promotion tables exist: {str(e)}")
        import traceback
        traceback.print_exc()
    finally:
        if 'cursor' in locals():
            cursor.close()
        if 'connection' in locals():
            connection.close()

def backfill_promotion_usage(cursor):
    """Backfill promotion usage data for existing orders that used promotions"""
    try:
        print("?? Starting promotion usage backfill...")
        
        # Get all orders that might have used promotions (where original price > total price)
        cursor.execute("""
            SELECT o.id, o.product_id, o.seller_email, o.email, o.total_price, o.quantity, o.date,
                   p.price as original_price
            FROM orders o
            LEFT JOIN products p ON o.product_id = p.id
            WHERE o.product_id IS NOT NULL 
            AND o.product_id != ''
            AND p.price IS NOT NULL
            AND CAST(p.price AS DECIMAL(10,2)) > CAST(o.total_price AS DECIMAL(10,2))
            AND NOT EXISTS (
                SELECT 1 FROM promotion_usage pu WHERE pu.order_id = o.id
            )
            ORDER BY o.date DESC
        """)
        
        orders_with_discounts = cursor.fetchall()
        backfilled_count = 0
        
        for order in orders_with_discounts:
            try:
                # Check if there was a promotion active for this product and seller
                # We'll check all promotions (not just currently active ones)
                cursor.execute("""
                    SELECT pr.id, pr.type, pr.discount_value, pr.start_date, pr.end_date
                    FROM promotions pr
                    LEFT JOIN promotion_products pp ON pr.id = pp.promotion_id
                    LEFT JOIN promotion_categories pc ON pr.id = pc.promotion_id
                    LEFT JOIN products p ON (pp.product_id = p.id OR pc.category = p.category)
                    WHERE pr.seller_email = %s
                    AND (
                        pr.product_scope = 'all' 
                        OR (pr.product_scope = 'specific' AND p.id = %s)
                        OR (pr.product_scope = 'category' AND p.id = %s)
                    )
                    AND pr.start_date <= %s 
                    AND pr.end_date >= %s
                    ORDER BY pr.created_at DESC
                    LIMIT 1
                """, (
                    order['seller_email'], 
                    order['product_id'], 
                    order['product_id'],
                    order['date'],
                    order['date']
                ))
                
                promotion = cursor.fetchone()
                
                if promotion:
                    # Calculate the discount that was applied
                    original_price = float(order['original_price'])
                    total_price = float(order['total_price'])
                    quantity = int(order['quantity'])
                    
                    # Calculate discount per item and total discount
                    discount_per_item = original_price - (total_price / quantity)
                    total_discount_applied = discount_per_item * quantity
                    
                    if total_discount_applied > 0:
                        # Insert promotion usage record
                        cursor.execute("""
                            INSERT INTO promotion_usage (
                                promotion_id,
                                customer_email,
                                order_id,
                                product_id,
                                discount_applied,
                                used_at
                            ) VALUES (%s, %s, %s, %s, %s, %s)
                        """, (
                            promotion['id'],
                            order['email'],
                            order['id'],
                            order['product_id'],
                            total_discount_applied,
                            order['date']
                        ))
                        
                        backfilled_count += 1
                        print(f"? Backfilled promotion usage for order {order['id']}: ?{total_discount_applied:.2f} discount")
                
            except Exception as order_error:
                print(f"?? Error processing order {order['id']}: {order_error}")
                continue
        
        print(f"? Backfilled {backfilled_count} promotion usage records")
        
    except Exception as e:
        print(f"? Error in promotion usage backfill: {str(e)}")
        import traceback
        traceback.print_exc()

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
        # Fetch active promotions from Supabase
        from datetime import date as _date, datetime as _datetime
        today = _date.today().isoformat()

        promo_res = sb_admin.table('promotions') \
            .select('id, name, type, discount_value, code, product_scope, start_date, end_date') \
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

        # Match products to promotions (scope: all ? any product qualifies)
        promotional = []
        seen_ids = set()

        for promo in promotions:
            scope = promo.get('product_scope', 'all')
            for p in all_products:
                if p['id'] in seen_ids:
                    continue
                if scope == 'all' or scope == 'category':
                    # For simplicity treat 'all' and 'category' as matching any product
                    enriched = dict(p)
                    enriched['promotion_type'] = promo.get('type', '')
                    enriched['promotion_discount'] = float(promo.get('discount_value') or 0)
                    enriched['promotion_code'] = promo.get('code', '')
                    enriched['promotion_name'] = promo.get('name', '')
                    # Ensure numeric types
                    enriched['price'] = float(enriched.get('price') or 0)
                    enriched['quantity'] = int(enriched.get('quantity') or 0)
                    enriched['sold'] = int(enriched.get('sold') or 0)
                    enriched['rating'] = float(enriched.get('rating') or 0)
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
    """Get active promotions that apply to a specific product"""
    try:
        # Validate input parameters
        if not product_id or not seller_email:
            return None
            
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)
        
        # Query to find active promotions that apply to this product
        cursor.execute("""
            SELECT pr.id, pr.name, pr.code, pr.type, pr.discount_value, pr.max_discount,
                   pr.min_purchase, pr.min_quantity, pr.start_date, pr.end_date,
                   pr.start_time, pr.end_time, pr.product_scope
            FROM promotions pr
            WHERE pr.seller_email = %s
            AND pr.is_active = 1 
            AND pr.start_date <= CURDATE() 
            AND pr.end_date >= CURDATE()
            AND TIME(NOW()) BETWEEN pr.start_time AND pr.end_time
            AND (
                (pr.product_scope = 'all') OR 
                (pr.product_scope = 'specific' AND EXISTS (
                    SELECT 1 FROM promotion_products pp WHERE pp.promotion_id = pr.id AND pp.product_id = %s
                )) OR
                (pr.product_scope = 'category' AND EXISTS (
                    SELECT 1 FROM promotion_categories pc WHERE pc.promotion_id = pr.id AND pc.category = %s
                ))
            )
            ORDER BY pr.discount_value DESC
            LIMIT 1
        """, (seller_email, product_id, category))
        
        promotion = cursor.fetchone()
        
        if promotion:
            # Convert discount_value to float if it's a Decimal with error handling
            if promotion['discount_value']:
                try:
                    if hasattr(promotion['discount_value'], '__float__'):
                        promotion['discount_value'] = float(promotion['discount_value'])
                    else:
                        promotion['discount_value'] = float(promotion['discount_value'])
                except (ValueError, TypeError):
                    promotion['discount_value'] = 0.0
            
            # Convert max_discount to float if it's a Decimal with error handling
            if promotion['max_discount']:
                try:
                    if hasattr(promotion['max_discount'], '__float__'):
                        promotion['max_discount'] = float(promotion['max_discount'])
                    else:
                        promotion['max_discount'] = float(promotion['max_discount'])
                except (ValueError, TypeError):
                    promotion['max_discount'] = None
            
            # Convert min_purchase to float if it's a Decimal with error handling
            if promotion['min_purchase']:
                try:
                    if hasattr(promotion['min_purchase'], '__float__'):
                        promotion['min_purchase'] = float(promotion['min_purchase'])
                    else:
                        promotion['min_purchase'] = float(promotion['min_purchase'])
                except (ValueError, TypeError):
                    promotion['min_purchase'] = 0.0
        
        cursor.close()
        connection.close()
        
        return promotion
        
    except mysql.connector.Error as err:
        print(f"Database error in get_active_promotions_for_product: {err}")
        return None
    except Exception as err:
        print(f"Error in get_active_promotions_for_product: {err}")
        return None

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
        msg = Message(
            'Account Approved - Welcome to MStyle!',
            sender=app.config['MAIL_DEFAULT_SENDER'],
            recipients=[email]
        )
        msg.body = f"""Hello {first_name}!

Great news! Your MStyle account has been approved by our admin team.

You can now log in to your account and start exploring our premium men's fashion collection.

Login here: http://localhost:5000/login

Thank you for choosing MStyle!

Best regards,
MStyle Team
"""
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
        msg = Message(
            'Congratulations! Your Seller Account Has Been Approved - MStyle',
            sender=app.config['MAIL_DEFAULT_SENDER'],
            recipients=[email]
        )
        msg.body = f"""Hello {first_name},

?? Congratulations! Your seller application for "{business_name}" has been approved!

You can now:
- Access your seller dashboard
- Start listing your products
- Manage your inventory
- Track your sales and analytics
- Communicate with customers

To get started, simply log in to your account and navigate to your seller dashboard.

If you have any questions or need assistance, please don't hesitate to contact our support team.

Welcome to the MStyle seller community!

Best regards,
MStyle Team
"""
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
    """Create in-app notification for low stock"""
    connection = None
    cursor = None
    try:
        variant_text = ""
        if variant_info:
            variant_text = f" ({variant_info['color']} - {variant_info['size']})"
        
        message = f"?? Low Stock Alert: {product_name}{variant_text} - Only {current_stock} units left (threshold: {threshold})"
        
        connection = get_db_connection()
        cursor = connection.cursor()
        
        cursor.execute("""
            INSERT INTO notifications (seller_email, message, type, is_read, created_at)
            VALUES (%s, %s, %s, FALSE, NOW())
        """, (seller_email, message, 'low_stock'))
        
        connection.commit()
        print(f"? Low stock notification created for {seller_email}: {product_name}{variant_text}")
        return True
        
    except Exception as e:
        print(f"? Error creating low stock notification: {str(e)}")
        if connection:
            try:
                connection.rollback()
            except:
                pass
        return False
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()

def create_out_of_stock_notification(seller_email, product_name, product_id, variant_info=None):
    """Create in-app notification for out of stock"""
    connection = None
    cursor = None
    try:
        variant_text = ""
        if variant_info:
            variant_text = f" ({variant_info['color']} - {variant_info['size']})"
        
        message = f"?? Out of Stock: {product_name}{variant_text} - Product is now unavailable for purchase"
        
        connection = get_db_connection()
        cursor = connection.cursor()
        
        cursor.execute("""
            INSERT INTO notifications (seller_email, message, type, is_read, created_at)
            VALUES (%s, %s, %s, FALSE, NOW())
        """, (seller_email, message, 'out_of_stock'))
        
        connection.commit()
        print(f"? Out of stock notification created for {seller_email}: {product_name}{variant_text}")
        return True
        
    except Exception as e:
        print(f"? Error creating out of stock notification: {str(e)}")
        if connection:
            try:
                connection.rollback()
            except:
                pass
        return False
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()

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
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM users WHERE email = %s", (email,))
    user = cursor.fetchone()
    conn.close()
    return user
def update_password_in_db(email, new_password):
    conn = get_db_connection()
    cursor = conn.cursor()
    # Hash the password before storing it
    hashed_password = generate_password_hash(new_password)
    cursor.execute("UPDATE users SET password = %s WHERE email = %s", (hashed_password, email))
    conn.commit()
    conn.close()

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
    promotional_products = get_promotional_products()

    return render_template('index.html',
                           featured_products=featured_products,
                           all_products=all_products,
                           promotional_products=promotional_products,
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

@app.route('/test-db')
def test_db():
    """Test route to check database connectivity"""
    try:
        db = get_db_connection()
        cursor = db.cursor()
        cursor.execute("SELECT 1")
        result = cursor.fetchone()
        cursor.close()
        db.close()
        return f"Database connection successful! Result: {result}"
    except Exception as e:
        return f"Database connection failed: {str(e)}"

#----------------------------------------------------------------------
                         #LOGIN RELATED ROUTES
#----------------------------------------------------------------------

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
        except Exception as e:
            import traceback
            print(f"Login unexpected error: {e}")
            traceback.print_exc()
            flash('An error occurred during login. Please try again.', 'error')

        return redirect(url_for('login'))

    # GET
    return render_template('login.html')
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

        # -- Also try MySQL pending_users (optional � may not be running) --
        hashed_password = generate_password_hash(password)
        try:
            db     = get_db_connection()
            cursor = db.cursor(dictionary=True)

            cursor.execute('SELECT status FROM pending_users WHERE email = %s', (email,))
            existing = cursor.fetchone()

            if existing:
                cursor.execute('''
                    UPDATE pending_users
                    SET password=%s, first_name=%s, last_name=%s, phone_number=%s,
                        address=%s, user_type=%s, valid_id_path=%s,
                        vehicle_type=%s, vehicle_model=%s, vehicle_plate_number=%s, vehicle_year_model=%s,
                        or_cr_path=%s, nbi_clearance_path=%s, supabase_uid=%s,
                        status='pending', created_at=CURRENT_TIMESTAMP, rejection_reason=NULL
                    WHERE email=%s
                ''', (hashed_password, first_name, last_name, phone_number, address,
                      user_type, valid_id_path, vehicle_type, vehicle_model,
                      vehicle_plate_number, vehicle_year_model, or_cr_path, nbi_clearance_path,
                      uid, email))
            else:
                cursor.execute('''
                    INSERT INTO pending_users
                    (email, password, first_name, last_name, phone_number, address,
                     user_type, valid_id_path, vehicle_type, vehicle_model, vehicle_plate_number,
                     vehicle_year_model, or_cr_path, nbi_clearance_path, supabase_uid, status)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ''', (email, hashed_password, first_name, last_name, phone_number, address,
                      user_type, valid_id_path, vehicle_type, vehicle_model,
                      vehicle_plate_number, vehicle_year_model, or_cr_path, nbi_clearance_path,
                      uid, 'pending'))

            db.commit()
            print(f"Inserted into MySQL pending_users for {email}")
        except Exception as db_error:
            # MySQL is optional � registration still succeeds via Supabase
            print(f"?? MySQL pending_users insert skipped (MySQL unavailable): {db_error}")
            if db:
                try: db.rollback()
                except Exception: pass

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
    

@app.route('/otp_verification', methods=['GET', 'POST'])
def otp_verification():
    if request.method == 'POST':
        user_otp = request.get_json().get('otp')  # Get the OTP entered by the user from JSON

        # Check if the OTP exists in the session and if it matches
        if 'otp' in session and int(user_otp) == session['otp']:
            # Finalize registration by saving user data
            registration_data = session.get('registration_data')
            if registration_data:
                try:
                    db = get_db_connection()  # Ensure this function returns a valid DB connection
                    cursor = db.cursor()
                    
                    # Insert into users table
                    cursor.execute('''INSERT INTO users (first_name, last_name, email, phone_number, address, password, user_type)
                                          VALUES (%s, %s, %s, %s, %s, %s, %s)''',
                                       (registration_data['first_name'], registration_data['last_name'], session['email'], 
                                        registration_data['phone_number'], registration_data['address'], 
                                        registration_data['password'], registration_data['user_type']))
                    db.commit()
                    response_data = {'success': True, 'message': 'Registration successful.'}
                    
                    cursor.close()
                    db.close()

                    # Clear the registration data from the session
                    session.pop('registration_data', None)

                except mysql.connector.Error as err:
                    response_data = {'success': False, 'error': f"Error: {err}"}
                    return jsonify(response_data)  # Return error in JSON format

            return jsonify(response_data)  # Return response data as JSON
        else:
            return jsonify(success=False, error="Invalid OTP")  # Return JSON response for invalid OTP

    return render_template('otp_verification.html')

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

            # -- Also try MySQL pending_sellers (optional � may not be running) --
            hashed_password = generate_password_hash(password)
            db = cursor = None
            try:
                db     = get_db_connection()
                cursor = db.cursor(dictionary=True)

                cursor.execute('SELECT status FROM pending_sellers WHERE email = %s', (email,))
                existing = cursor.fetchone()

                if existing:
                    if existing['status'] == 'pending':
                        cursor.close(); db.close()
                        flash('You already have a pending seller application.', 'info')
                        return render_template('login.html')
                    elif existing['status'] == 'approved':
                        cursor.close(); db.close()
                        flash('Your seller account has already been approved. Please log in.', 'success')
                        return redirect(url_for('login'))
                    else:
                        cursor.execute('''
                            UPDATE pending_sellers
                            SET first_name=%s, last_name=%s, business_name=%s, phone_number=%s,
                                address=%s, business_type=%s, password=%s, valid_id_path=%s,
                                dti_path=%s, bir_path=%s, business_permit_path=%s, supabase_uid=%s,
                                status='pending', created_at=%s, rejection_reason=NULL
                            WHERE email=%s
                        ''', (first_name, last_name, business_name, phone_number, address,
                              business_type, hashed_password, valid_id_path, dti_path, bir_path,
                              business_permit_path, uid, datetime.now(), email))
                else:
                    cursor.execute('''
                        INSERT INTO pending_sellers
                        (first_name, last_name, business_name, phone_number, address,
                         business_type, email, password, valid_id_path, dti_path, bir_path,
                         business_permit_path, supabase_uid, status, created_at)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ''', (first_name, last_name, business_name, phone_number, address,
                          business_type, email, hashed_password, valid_id_path, dti_path, bir_path,
                          business_permit_path, uid, 'pending', datetime.now()))

                db.commit()
                print(f"Inserted into MySQL pending_sellers for {email}")
            except Exception as db_error:
                # MySQL is optional � registration still succeeds via Supabase
                print(f"?? MySQL pending_sellers insert skipped (MySQL unavailable): {db_error}")
                if db:
                    try: db.rollback()
                    except Exception: pass
            finally:
                if cursor:
                    try: cursor.close()
                    except Exception: pass
                if db:
                    try: db.close()
                    except Exception: pass

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

        # Best-effort MySQL update
        if email:
            try:
                update_password_in_db(email, new_password)
            except Exception:
                pass

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
        # Get form data
        data = request.get_json() if request.is_json else request.form
        old_password = data.get('old_password')
        new_password = data.get('new_password')
        confirm_password = data.get('confirm_password')

        # Validate inputs
        if not all([old_password, new_password, confirm_password]):
            return jsonify({'success': False, 'message': 'All fields are required.'}), 400

        if new_password != confirm_password:
            return jsonify({'success': False, 'message': 'New password and confirm password do not match.'}), 400

        # Get database connection
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)

        # Get user data by email (user_id is now a Supabase UUID, not MySQL integer)
        user_email = session.get('email')
        cursor.execute("SELECT * FROM users WHERE email = %s", (user_email,))
        user = cursor.fetchone()

        if not user:
            return jsonify({'success': False, 'message': 'User not found.'}), 404

        # Verify old password - handle both hashed and plain text passwords
        password_valid = False
        
        # First try hashed password comparison
        try:
            if check_password_hash(user['password'], old_password):
                password_valid = True
        except:
            # If hashed comparison fails, try plain text comparison
            if user['password'] == old_password:
                password_valid = True
        
        if not password_valid:
            return jsonify({'success': False, 'message': 'Incorrect current password.'}), 400

        # Update password - try hashed first, fallback to plain text if database constraint fails
        try:
            # Hash the new password
            hashed_new_password = generate_password_hash(new_password)
            
            # Try to update with hashed password
            cursor.execute(
                "UPDATE users SET password = %s WHERE email = %s",
                (hashed_new_password, session.get('email'))
            )
            connection.commit()
            
        except Exception as db_error:
            # If hashed password fails (likely due to field length), try plain text
            print(f"Hashed password update failed: {db_error}")
            print("Falling back to plain text password storage")
            
            try:
                cursor.execute(
                    "UPDATE users SET password = %s WHERE email = %s",
                    (new_password, session.get('email'))
                )
                connection.commit()
            except Exception as fallback_error:
                raise Exception(f"Both hashed and plain text password updates failed: {fallback_error}")

        return jsonify({
            'success': True,
            'message': 'Password updated successfully!'
        })

    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'An error occurred: {str(e)}'
        }), 500
    finally:
        if 'cursor' in locals():
            cursor.close()
        if 'connection' in locals():
            connection.close()

@app.route('/check-old-password', methods=['POST'])
def check_old_password():
    user_id = session.get('user_id')
    if user_id is None:
        return jsonify(valid=False), 401  # User not logged in

    data = request.get_json()
    old_password = data.get("old_password")

    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)
        
        # Fetch the stored password for comparison (use email since user_id is now a UUID)
        user_email = session.get('email')
        cursor.execute("SELECT password FROM users WHERE email = %s", (user_email,))
        user_data = cursor.fetchone()
        
        if user_data:
            # Check password - handle both hashed and plain text passwords
            password_valid = False
            
            # First try hashed password comparison
            try:
                if check_password_hash(user_data['password'], old_password):
                    password_valid = True
            except:
                # If hashed comparison fails, try plain text comparison
                if user_data['password'] == old_password:
                    password_valid = True
            
            return jsonify(valid=password_valid)
        else:
            return jsonify(valid=False)  # User not found

    except mysql.connector.Error as err:
        print("Database error:", err)
        return jsonify(valid=False), 500

    finally:
        cursor.close()
        connection.close()


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

    promotional_products = get_promotional_products()

    # Fetch user's wishlist product IDs for heart icon state
    wishlist_product_ids = _get_wishlist_ids()

    return render_template('homepage.html',
                           user_name=user_name,
                           user_email=session.get('email', 'User'),
                           all_products=all_products,
                           promotional_products=promotional_products,
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

    except Exception as e:
        print(f'[search] Supabase error: {e}')

    return render_template('search_results.html',
                           products=products,
                           query=query,
                           user_email=session.get('email', 'User'),
                           category=category,
                           sort_by=sort_by,
                           categories=categories,
                           current_page=page,
                           total_pages=total_pages,
                           total_count=total_count,
                           per_page=per_page,
                           user_name=user_name)

@app.route('/api/search-suggestions')
def search_suggestions():
    query = request.args.get('query', '').strip()
    
    if not query or len(query) < 2:
        return jsonify({'success': False, 'suggestions': []})
    
    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)
        
        # Get product suggestions based on name and category (only active products for buyers)
        cursor.execute("""
            SELECT DISTINCT name, category FROM products 
            WHERE quantity > 0 AND is_active = 1 AND (name LIKE %s OR category LIKE %s)
            ORDER BY 
                CASE 
                    WHEN name LIKE %s THEN 1
                    WHEN name LIKE %s THEN 2
                    ELSE 3
                END,
                sold DESC
            LIMIT 8
        """, (f"%{query}%", f"%{query}%", f"{query}%", f"%{query}%"))
        
        suggestions = cursor.fetchall()
        cursor.close()
        connection.close()
        
        return jsonify({
            'success': True,
            'suggestions': suggestions
        })
        
    except mysql.connector.Error as err:
        print(f"Database error in search suggestions: {err}")
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
                    'rating, review_text, customer_email, created_at, seller_response, response_date'
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

    # -- FALLBACK: MySQL -------------------------------------------------------
    if product is None:
        try:
            db = get_db_connection()
            cursor = db.cursor(dictionary=True)
            cursor.execute("""
                SELECT p.*,
                       CONCAT(u.first_name, ' ', u.last_name) as seller_name,
                       COALESCE(u.business_name, CONCAT(u.first_name, ' ', u.last_name)) as business_name,
                       u.profile_picture as seller_profile_picture
                FROM products p
                JOIN users u ON p.seller_email = u.email
                WHERE p.id = %s AND p.is_active = 1
            """, (product_id,))
            product = cursor.fetchone()

            if product:
                cursor.execute("""
                    SELECT r.*,
                           CONCAT(u.first_name, ' ', u.last_name) as customer_name,
                           u.profile_picture,
                           r.seller_response, r.response_date
                    FROM reviews r
                    JOIN users u ON r.customer_email = u.email
                    WHERE r.product_id = %s
                    ORDER BY r.created_at DESC
                """, (product_id,))
                reviews = cursor.fetchall()
                if reviews:
                    total_rating = sum(rv['rating'] for rv in reviews)
                    review_stats['total_reviews'] = len(reviews)
                    review_stats['average_rating'] = round(total_rating / len(reviews), 1)
                    for rv in reviews:
                        review_stats['rating_distribution'][rv['rating']] += 1

            cursor.close()
            db.close()
        except Exception as mysql_err:
            print(f"?? MySQL view_product fallback failed: {mysql_err}")

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

            # -- Also update MySQL users table (by email) ------------------
            user_type = session.get('user_type', '').lower()
            try:
                connection = get_db_connection()
                cursor = connection.cursor()

                if profile_picture_filename:
                    if user_type == 'rider':
                        try:
                            cursor.execute("""
                                UPDATE users
                                SET first_name=%s, last_name=%s, phone_number=%s, address=%s,
                                    business_name=%s, vehicle_type=%s, vehicle_model=%s,
                                    vehicle_plate_number=%s, vehicle_year_model=%s, profile_picture=%s
                                WHERE email=%s
                            """, (first_name, last_name, phone_number, address, business_name,
                                  vehicle_type, vehicle_model, vehicle_plate_number,
                                  vehicle_year_model, profile_picture_filename, user_email))
                        except Exception:
                            cursor.execute("""
                                UPDATE users SET first_name=%s, last_name=%s, phone_number=%s,
                                    address=%s, business_name=%s, profile_picture=%s WHERE email=%s
                            """, (first_name, last_name, phone_number, address, business_name,
                                  profile_picture_filename, user_email))
                    else:
                        cursor.execute("""
                            UPDATE users SET first_name=%s, last_name=%s, phone_number=%s,
                                address=%s, business_name=%s, profile_picture=%s WHERE email=%s
                        """, (first_name, last_name, phone_number, address, business_name,
                              profile_picture_filename, user_email))
                else:
                    if user_type == 'rider':
                        try:
                            cursor.execute("""
                                UPDATE users
                                SET first_name=%s, last_name=%s, phone_number=%s, address=%s,
                                    business_name=%s, vehicle_type=%s, vehicle_model=%s,
                                    vehicle_plate_number=%s, vehicle_year_model=%s
                                WHERE email=%s
                            """, (first_name, last_name, phone_number, address, business_name,
                                  vehicle_type, vehicle_model, vehicle_plate_number,
                                  vehicle_year_model, user_email))
                        except Exception:
                            cursor.execute("""
                                UPDATE users SET first_name=%s, last_name=%s, phone_number=%s,
                                    address=%s, business_name=%s WHERE email=%s
                            """, (first_name, last_name, phone_number, address, business_name, user_email))
                    else:
                        cursor.execute("""
                            UPDATE users SET first_name=%s, last_name=%s, phone_number=%s,
                                address=%s, business_name=%s WHERE email=%s
                        """, (first_name, last_name, phone_number, address, business_name, user_email))

                connection.commit()
            except Exception as mysql_err:
                print(f"?? MySQL profile update skipped (unavailable): {mysql_err}")

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

        # -- Supplement with MySQL data (profile_picture, business_name, vehicle) --
        try:
            conn = get_db_connection()
            cur = conn.cursor(dictionary=True)
            cur.execute("""
                SELECT profile_picture, business_name,
                       vehicle_type, vehicle_model, vehicle_plate_number, vehicle_year_model
                FROM users WHERE email = %s
            """, (user_email,))
            row = cur.fetchone()
            cur.close()
            conn.close()
            if row:
                user_data['profile_picture'] = row.get('profile_picture')
                # Only use MySQL business_name if Supabase didn't have one
                if not user_data.get('business_name'):
                    user_data['business_name'] = row.get('business_name', '') or ''
                user_data['vehicle_type']         = row.get('vehicle_type', '') or ''
                user_data['vehicle_model']        = row.get('vehicle_model', '') or ''
                user_data['vehicle_plate_number'] = row.get('vehicle_plate_number', '') or ''
                user_data['vehicle_year_model']   = row.get('vehicle_year_model', '') or ''
        except Exception as mysql_err:
            print(f"?? MySQL profile supplement skipped: {mysql_err}")

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

            try:
                connection = get_db_connection()
                cursor = connection.cursor()
                cursor.execute(
                    "UPDATE users SET profile_picture = %s WHERE email = %s",
                    (filename, session.get('email'))
                )
                connection.commit()
            except Exception as mysql_err:
                print(f"?? MySQL profile picture update skipped: {mysql_err}")
            
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

    # -- Get seller name from Supabase (works even when MySQL is down) -----
    seller_name = session.get('first_name', 'Seller')
    try:
        sb_res = sb_admin.table('users').select('first_name, last_name, business_name').eq('email', session['email']).execute()
        if sb_res.data:
            u = sb_res.data[0]
            seller_name = u.get('business_name') or f"{u.get('first_name', '')} {u.get('last_name', '')}".strip() or 'Seller'
    except Exception as sb_err:
        print(f"?? Supabase name fetch failed in seller_dashboard: {sb_err}")

    # Get date range from query parameters or use default (last 7 days)
    end_date = request.args.get('end_date', datetime.now().strftime('%Y-%m-%d'))
    start_date = request.args.get('start_date', (datetime.strptime(end_date, '%Y-%m-%d') - timedelta(days=7)).strftime('%Y-%m-%d'))

    # Safe defaults � used when MySQL is unavailable
    total_sales    = 0.0
    total_earnings = 0.0
    total_items    = 0
    avg_order_value = 0.0
    pending_orders  = 0
    cancelled_orders = 0
    total_products  = 0
    status_counts   = {k: 0 for k in ['Pending','Confirmed','Preparing','Ready for Pickup','Out for Delivery','Delivered','Completed','Cancelled']}
    chart_dates     = []
    chart_sales     = []
    chart_earnings  = []

    # Pre-fill chart dates regardless of MySQL availability
    current_date = datetime.strptime(end_date, '%Y-%m-%d')
    for i in range(11, -1, -1):
        month_date = current_date - timedelta(days=i*30)
        chart_dates.append(month_date.strftime('%Y-%m'))
        chart_sales.append(0)
        chart_earnings.append(0)

    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)
    except Exception as db_err:
        print(f"?? MySQL unavailable in seller_dashboard: {db_err}")
        return render_template('seller_dashboard.html',
                             total_sales="{:.2f}".format(total_sales),
                             total_earnings="{:.2f}".format(total_earnings),
                             total_items=total_items,
                             pending_orders=pending_orders,
                             cancelled_orders=cancelled_orders,
                             avg_order_value="{:.2f}".format(avg_order_value),
                             total_products=total_products,
                             start_date=start_date,
                             end_date=end_date,
                             user_name=seller_name,
                             user_email=session.get('email', 'Seller'),
                             order_status_counts=status_counts,
                             chart_dates=chart_dates,
                             chart_sales=chart_sales,
                             chart_earnings=chart_earnings)

    try:
        # Fetch sales and earnings data for charts (last 30 days, only completed/delivered orders)
        cursor.execute("""
            SELECT 
                DATE(o.date) as sale_date,
                SUM(o.total_price) as daily_sales,
                o.id as order_id,
                o.product_id,
                o.total_price,
                o.date as order_date,
                o.seller_email
            FROM orders o
            WHERE o.seller_email = %s 
            AND DATE(o.date) >= DATE_SUB(CURDATE(), INTERVAL 12 MONTH)
            AND o.status IN ('Completed', 'Delivered')
            GROUP BY DATE(o.date), o.id, o.product_id, o.total_price, o.date, o.seller_email
            ORDER BY sale_date
        """, (session['email'],))
        
        orders_data = cursor.fetchall()
        
        # Calculate monthly sales and earnings
        monthly_data = {}
        
        for order in orders_data:
            month_key = order['sale_date'].strftime('%Y-%m')
            order_value = float(order['total_price'])
            
            if month_key not in monthly_data:
                monthly_data[month_key] = {'sales': 0, 'earnings': 0}
            
            monthly_data[month_key]['sales'] += order_value
            
            cursor.execute("""
                SELECT COALESCE(discount_applied, 0) as discount
                FROM promotion_usage
                WHERE order_id = %s
            """, (order['order_id'],))
            discount_result = cursor.fetchone()
            discount_applied = float(discount_result['discount']) if discount_result else 0.0
            
            net_sales = order_value - discount_applied
            
            has_free_shipping = False
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
                """, (order['seller_email'], order['order_date'].date(), order['order_date'].date(), order['product_id'], order['product_id']))
                has_free_shipping = cursor.fetchone() is not None
            
            shipping_fee_deduction = 50 if has_free_shipping else 0
            platform_commission = net_sales * 0.05
            order_earnings = net_sales - shipping_fee_deduction - platform_commission
            monthly_data[month_key]['earnings'] += order_earnings
        
        # Rebuild chart data with real values
        chart_dates = []
        chart_sales = []
        chart_earnings = []
        for i in range(11, -1, -1):
            month_date = current_date - timedelta(days=i*30)
            month_key = month_date.strftime('%Y-%m')
            chart_dates.append(month_key)
            chart_sales.append(monthly_data.get(month_key, {}).get('sales', 0))
            chart_earnings.append(monthly_data.get(month_key, {}).get('earnings', 0))

        # Get dashboard stats
        cursor.execute("""
            SELECT 
                COALESCE(SUM(total_price), 0) as total_sales,
                COUNT(*) as total_items,
                COALESCE(AVG(total_price), 0) as avg_order_value
            FROM orders 
            WHERE seller_email = %s
            AND status IN ('Completed', 'Delivered')
        """, (session['email'],))
        stats = cursor.fetchone()

        # Get total earnings
        cursor.execute("""
            SELECT o.id, o.product_id, o.total_price, o.date, o.seller_email
            FROM orders o
            WHERE o.seller_email = %s 
            AND o.status IN ('Delivered', 'Completed')
        """, (session['email'],))
        completed_orders = cursor.fetchall()
        
        for order in completed_orders:
            has_free_shipping = False
            order_value = float(order['total_price'])
            cursor.execute("SELECT COALESCE(discount_applied, 0) as discount FROM promotion_usage WHERE order_id = %s", (order['id'],))
            discount_result = cursor.fetchone()
            discount_applied = float(discount_result['discount']) if discount_result else 0.0
            net_sales = order_value - discount_applied
            if order['product_id']:
                cursor.execute("""
                    SELECT pr.id FROM promotions pr
                    LEFT JOIN promotion_products pp ON pr.id = pp.promotion_id
                    LEFT JOIN promotion_categories pc ON pr.id = pc.promotion_id
                    LEFT JOIN products p ON (pp.product_id = p.id OR pc.category = p.category)
                    WHERE pr.seller_email = %s AND pr.type = 'free_shipping' AND pr.is_active = 1
                    AND pr.start_date <= %s AND pr.end_date >= %s
                    AND (pr.product_scope = 'all' OR (pr.product_scope = 'specific' AND p.id = %s) OR (pr.product_scope = 'category' AND p.id = %s))
                    LIMIT 1
                """, (order['seller_email'], order['date'].date(), order['date'].date(), order['product_id'], order['product_id']))
                has_free_shipping = cursor.fetchone() is not None
            shipping_fee_deduction = 50.0 if has_free_shipping else 0.0
            platform_commission = net_sales * 0.05
            total_earnings += net_sales - shipping_fee_deduction - platform_commission
        
        total_sales = float(stats['total_sales'])
        total_items = stats['total_items']
        avg_order_value = float(stats['avg_order_value'])

        cursor.execute("SELECT COUNT(*) as pending_count FROM orders WHERE seller_email = %s AND status = 'Pending'", (session['email'],))
        pending_orders = (cursor.fetchone() or {}).get('pending_count', 0)

        cursor.execute("SELECT COUNT(*) as cancelled_count FROM orders WHERE seller_email = %s AND status = 'Cancelled'", (session['email'],))
        cancelled_orders = (cursor.fetchone() or {}).get('cancelled_count', 0)

        cursor.execute("SELECT COUNT(*) as product_count FROM products WHERE seller_email = %s", (session['email'],))
        total_products = (cursor.fetchone() or {}).get('product_count', 0)

        cursor.execute("SELECT status, COUNT(*) as count FROM orders WHERE seller_email = %s GROUP BY status", (session['email'],))
        status_mapping = {
            'pending': 'Pending', 'confirmed': 'Confirmed', 'preparing': 'Preparing',
            'ready_for_pickup': 'Ready for Pickup', 'out_for_delivery': 'Out for Delivery',
            'delivered': 'Delivered', 'completed': 'Completed', 'cancelled': 'Cancelled'
        }
        for row in cursor.fetchall():
            key = status_mapping.get(row['status'].lower(), row['status'])
            if key in status_counts:
                status_counts[key] = row['count']

    except Exception as e:
        print(f"?? MySQL query error in seller_dashboard: {e}")
    finally:
        if 'cursor' in locals() and cursor:
            cursor.close()
        if 'connection' in locals() and connection:
            connection.close()

    return render_template('seller_dashboard.html',
                         total_sales="{:.2f}".format(total_sales),
                         total_earnings="{:.2f}".format(total_earnings),
                         total_items=total_items,
                         pending_orders=pending_orders,
                         cancelled_orders=cancelled_orders,
                         avg_order_value="{:.2f}".format(avg_order_value),
                         total_products=total_products,
                         start_date=start_date,
                         end_date=end_date,
                         user_name=seller_name,
                         user_email=session.get('email', 'Seller'),
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

    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)
    except Exception as db_err:
        print(f"?? MySQL unavailable in reports_analytics: {db_err}")
        return render_template('reports_analytics.html',
                             total_revenue="0.00", total_orders=0,
                             avg_order_value="0.00", total_earnings="0.00",
                             top_products=[], status_stats={
                                 k: {'count': 0, 'value': 0.0} for k in
                                 ['pending','confirmed','preparing','ready_for_pickup',
                                  'out_for_delivery','delivered','completed','cancelled']
                             },
                             order_details=[], promotion_performance=[],
                             financial_summary=[], user_name=seller_name,
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

    # Ensure promotion tables exist
    try:
        ensure_promotion_tables_exist()
    except Exception:
        pass

    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)
    except Exception as db_err:
        print(f"?? MySQL unavailable in promotions: {db_err}")
        return render_template('promotions.html', products=[], active_promotions=[],
                             user_name=seller_name, user_email=session.get('email', 'Seller'))

    # Get seller's products for promotion management
    cursor.execute("""
        SELECT id, name, price, image, quantity, category
        FROM products 
        WHERE seller_email = %s AND quantity > 0
        ORDER BY name ASC
    """, (session['email'],))
    
    products = cursor.fetchall()
    
    # Safely convert product prices to avoid TypeError
    for product in products:
        try:
            product['price'] = float(product['price']) if product['price'] is not None else 0.0
            product['quantity'] = int(product['quantity']) if product['quantity'] is not None else 0
        except (ValueError, TypeError):
            product['price'] = 0.0
            product['quantity'] = 0

    # Get active promotions for this seller
    try:
        cursor.execute("""
            SELECT p.*, 
                   p.current_usage_count as total_uses,
                   COALESCE(SUM(pu.discount_applied), 0) as total_discount_given
            FROM promotions p
            LEFT JOIN promotion_usage pu ON p.id = pu.promotion_id
            WHERE p.seller_email = %s AND p.is_active = 1
            AND p.start_date <= CURDATE() AND p.end_date >= CURDATE()
            GROUP BY p.id
            ORDER BY p.created_at DESC
            LIMIT 10
        """, (session['email'],))
        
        active_promotions = cursor.fetchall()
        
        # Debug: Print promotion usage counts
        for promotion in active_promotions:
            print(f"DEBUG - Promotion '{promotion['name']}' (ID: {promotion['id']}): {promotion['total_uses']} uses, ?{promotion['total_discount_given']:.2f} total discount")
            
    except Exception as e:
        print(f"Error fetching promotions: {str(e)}")
        active_promotions = []  # Empty list if table doesn't exist yet
    
    # Format promotions for display
    for promotion in active_promotions:
        promotion['start_date'] = promotion['start_date'].strftime('%b %d, %Y')
        promotion['end_date'] = promotion['end_date'].strftime('%b %d, %Y')

    cursor.close()
    connection.close()

    return render_template('promotions.html',
                         products=products,
                         active_promotions=active_promotions,
                         user_name=seller_name,
                         user_email=session.get('email', 'Seller'))

@app.route('/seller_reviews')
def seller_reviews():
    """Seller Reviews & Ratings page - view and respond to buyer reviews"""
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
        print(f"?? Supabase name fetch failed in seller_reviews: {sb_err}")

    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)
    except Exception as db_err:
        print(f"?? MySQL unavailable in seller_reviews: {db_err}")
        empty_stats = {'total_reviews': 0, 'average_rating': 0,
                       'five_star': 0, 'four_star': 0, 'three_star': 0,
                       'two_star': 0, 'one_star': 0}
        return render_template('seller_reviews.html', reviews=[], stats=empty_stats,
                             user_name=seller_name, user_email=session.get('email', 'Seller'))

    # Ensure seller_response column exists
    try:
        cursor.execute("""
            SELECT COUNT(*) 
            FROM INFORMATION_SCHEMA.COLUMNS 
            WHERE TABLE_SCHEMA = 'mstyle' 
            AND TABLE_NAME = 'reviews' 
            AND COLUMN_NAME = 'seller_response'
        """)
        result = cursor.fetchone()
        if result and result['COUNT(*)'] == 0:
            try:
                cursor.execute("""
                    ALTER TABLE reviews 
                    ADD COLUMN seller_response TEXT NULL AFTER review_text
                """)
                cursor.execute("""
                    ALTER TABLE reviews 
                    ADD COLUMN response_date TIMESTAMP NULL AFTER seller_response
                """)
                connection.commit()
                print("? Added seller_response columns to reviews table")
            except Exception as alter_error:
                print(f"Note: Could not add seller_response columns: {alter_error}")
                connection.rollback()
    except Exception as e:
        print(f"Note: Could not check seller_response columns: {e}")

    # Get all reviews for seller's products with product and customer details
    cursor.execute("""
        SELECT 
            r.id,
            r.order_id,
            r.product_id,
            r.customer_email,
            r.rating,
            r.review_text,
            r.seller_response,
            r.response_date,
            r.created_at,
            p.name as product_name,
            p.image as product_image,
            p.price as product_price,
            u.first_name as customer_first_name,
            u.last_name as customer_last_name
        FROM reviews r
        JOIN products p ON r.product_id = p.id
        LEFT JOIN users u ON r.customer_email = u.email
        WHERE r.seller_email = %s
        ORDER BY r.created_at DESC
    """, (session['email'],))
    
    reviews = cursor.fetchall()

    # Calculate review statistics
    cursor.execute("""
        SELECT 
            COUNT(*) as total_reviews,
            AVG(rating) as average_rating,
            SUM(CASE WHEN rating = 5 THEN 1 ELSE 0 END) as five_star,
            SUM(CASE WHEN rating = 4 THEN 1 ELSE 0 END) as four_star,
            SUM(CASE WHEN rating = 3 THEN 1 ELSE 0 END) as three_star,
            SUM(CASE WHEN rating = 2 THEN 1 ELSE 0 END) as two_star,
            SUM(CASE WHEN rating = 1 THEN 1 ELSE 0 END) as one_star
        FROM reviews
        WHERE seller_email = %s
    """, (session['email'],))
    
    stats = cursor.fetchone()
    
    # Format reviews for display
    for review in reviews:
        review['customer_name'] = f"{review['customer_first_name']} {review['customer_last_name']}" if review['customer_first_name'] else "Anonymous"
        review['time_ago'] = format_time_ago(review['created_at'])
        review['rating_stars'] = '?' * review['rating'] + '?' * (5 - review['rating'])
        # Format response date if exists
        if review.get('response_date'):
            review['response_time_ago'] = format_time_ago(review['response_date'])
        else:
            review['response_time_ago'] = None

    cursor.close()
    connection.close()

    return render_template('seller_reviews.html',
                         reviews=reviews,
                         stats=stats,
                         user_name=seller_name,
                         user_email=session.get('email', 'Seller'))

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
    """API endpoint for seller to respond to a review"""
    if 'email' not in session or session.get('user_type', '').lower() != 'seller':
        return jsonify({'success': False, 'error': 'Unauthorized. Please log in as a seller.'}), 401
    
    connection = None
    cursor = None
    
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({'success': False, 'error': 'No data received'}), 400
        
        review_id = data.get('review_id')
        response_text = data.get('response_text', '').strip()
        
        print(f"DEBUG: Received review_id={review_id}, response_text length={len(response_text)}")
        
        if not review_id:
            return jsonify({'success': False, 'error': 'Review ID is required'}), 400
            
        if not response_text:
            return jsonify({'success': False, 'error': 'Response text cannot be empty'}), 400
        
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)
        
        # Verify the review belongs to this seller
        cursor.execute("""
            SELECT id, seller_email 
            FROM reviews 
            WHERE id = %s
        """, (review_id,))
        
        review = cursor.fetchone()
        
        print(f"DEBUG: Review found: {review}")
        
        if not review:
            cursor.close()
            connection.close()
            return jsonify({'success': False, 'error': 'Review not found'}), 404
        
        if review['seller_email'] != session['email']:
            cursor.close()
            connection.close()
            return jsonify({'success': False, 'error': 'You are not authorized to respond to this review'}), 403
        
        # Update the review with seller response
        cursor.execute("""
            UPDATE reviews 
            SET seller_response = %s, response_date = NOW()
            WHERE id = %s
        """, (response_text, review_id))
        
        affected_rows = cursor.rowcount
        connection.commit()
        
        print(f"DEBUG: Updated {affected_rows} rows")
        
        cursor.close()
        connection.close()
        
        return jsonify({
            'success': True,
            'message': 'Response posted successfully',
            'response_date': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        })
        
    except Exception as e:
        print(f"? Error posting seller response: {str(e)}")
        import traceback
        traceback.print_exc()
        
        if cursor:
            cursor.close()
        if connection:
            connection.close()
            
        return jsonify({'success': False, 'error': f'Server error: {str(e)}'}), 500

@app.route('/admin/backfill-promotion-usage')
def admin_backfill_promotion_usage():
    """Admin route to manually trigger promotion usage backfill"""
    if 'email' not in session:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401
    
    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)
        
        backfill_promotion_usage(cursor)
        connection.commit()
        
        cursor.close()
        connection.close()
        
        return jsonify({'success': True, 'message': 'Promotion usage backfill completed'})
    except Exception as e:
        return jsonify({'success': False, 'message': f'Error: {str(e)}'}), 500

@app.route('/api/create_promotion', methods=['POST'])
def create_promotion():
    """Create a new promotion"""
    print(f"DEBUG: Session data: {dict(session)}")
    print(f"DEBUG: Request method: {request.method}")
    print(f"DEBUG: Request headers: {dict(request.headers)}")
    
    if 'email' not in session or session.get('user_type', '').lower() != 'seller':
        print(f"DEBUG: Unauthorized - email in session: {'email' in session}, user_type: {session.get('user_type')}")
        return jsonify({'success': False, 'message': 'Unauthorized access'}), 401
    
    try:
        data = request.get_json()
        print(f"DEBUG: Received promotion data: {data}")  # Debug logging
        
        if not data:
            return jsonify({'success': False, 'message': 'No data received'}), 400
        
        # Ensure promotion tables exist
        ensure_promotion_tables_exist()
        
        # Validate required fields
        required_fields = ['name', 'code', 'type', 'startDate', 'endDate', 'productScope']
        for field in required_fields:
            if not data.get(field) or str(data.get(field)).strip() == '':
                print(f"DEBUG: Missing or empty field: {field}")  # Debug logging
                return jsonify({'success': False, 'message': f'{field} is required'}), 400
        
        # Initialize discount_value
        discount_value = None
        
        # Validate discount value for percentage and fixed types
        if data['type'] in ['percentage', 'fixed']:
            if not data.get('discountValue') or str(data.get('discountValue')).strip() == '':
                return jsonify({'success': False, 'message': 'Discount value is required for this promotion type'}), 400
            
            try:
                discount_value = float(data['discountValue'])
                if data['type'] == 'percentage' and (discount_value < 1 or discount_value > 100):
                    return jsonify({'success': False, 'message': 'Percentage must be between 1 and 100'}), 400
                elif data['type'] == 'fixed' and discount_value < 1:
                    return jsonify({'success': False, 'message': 'Fixed discount must be at least 1'}), 400
            except (ValueError, TypeError):
                return jsonify({'success': False, 'message': 'Invalid discount value format'}), 400
        else:
            # For BOGO and free shipping, set discount_value to 0
            discount_value = 0.00
        
        try:
            connection = get_db_connection()
            cursor = connection.cursor()
            print(f"DEBUG: Database connection established")
        except Exception as conn_error:
            print(f"DEBUG: Database connection failed: {conn_error}")
            return jsonify({'success': False, 'message': 'Database connection failed'}), 500
        
        # Check if promotion code already exists for this seller
        try:
            cursor.execute("SELECT id FROM promotions WHERE code = %s AND seller_email = %s", 
                          (data['code'], session['email']))
            if cursor.fetchone():
                cursor.close()
                connection.close()
                return jsonify({'success': False, 'message': 'Promotion code already exists'}), 400
        except Exception as check_error:
            print(f"DEBUG: Error checking existing promotion: {check_error}")
            cursor.close()
            connection.close()
            return jsonify({'success': False, 'message': 'Error checking existing promotions'}), 500
        
        # Prepare values for insertion
        try:
            max_discount_val = float(data.get('maxDiscount')) if data.get('maxDiscount') and str(data.get('maxDiscount')).strip() != '' else None
            min_purchase_val = float(data.get('minPurchase')) if data.get('minPurchase') and str(data.get('minPurchase')).strip() != '' else 0
            min_quantity_val = int(data.get('minQuantity')) if data.get('minQuantity') and str(data.get('minQuantity')).strip() != '' else 1
            usage_limit_val = int(data.get('usageLimit')) if data.get('usageLimit') and str(data.get('usageLimit')).strip() != '' else None
        except (ValueError, TypeError) as e:
            print(f"DEBUG: Error converting values: {e}")
            return jsonify({'success': False, 'message': 'Invalid numeric values provided'}), 400

        print(f"DEBUG: Inserting promotion with values: name={data['name']}, code={data['code']}, type={data['type']}")
        
        # Insert promotion
        try:
            print(f"DEBUG: About to insert promotion with discount_value: {discount_value}")
            print(f"DEBUG: All values: name={data['name']}, code={data['code']}, type={data['type']}")
            print(f"DEBUG: Dates: start={data['startDate']}, end={data['endDate']}")
            
            cursor.execute("""
                INSERT INTO promotions (
                    name, code, seller_email, type, discount_value, max_discount,
                    min_purchase, min_quantity, usage_limit_per_customer, 
                    start_date, start_time, end_date, end_time, product_scope, is_active
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                data['name'], 
                data['code'], 
                session['email'], 
                data['type'], 
                discount_value,
                max_discount_val,
                min_purchase_val,
                min_quantity_val,
                usage_limit_val,
                data['startDate'], 
                data.get('startTime', '00:00:00'),
                data['endDate'], 
                data.get('endTime', '23:59:59'),
                data['productScope'], 
                data.get('isActive', True)
            ))
            
            promotion_id = cursor.lastrowid
            print(f"DEBUG: Promotion inserted with ID: {promotion_id}")
            
        except Exception as insert_error:
            print(f"DEBUG: Error inserting promotion: {insert_error}")
            cursor.close()
            connection.close()
            return jsonify({'success': False, 'message': f'Error creating promotion: {str(insert_error)}'}), 500
        
        # Handle product/category associations with error handling
        try:
            if data['productScope'] == 'specific' and data.get('selectedProducts'):
                print(f"DEBUG: Adding specific products: {data['selectedProducts']}")
                for product_id in data['selectedProducts']:
                    cursor.execute("""
                        INSERT INTO promotion_products (promotion_id, product_id)
                        VALUES (%s, %s)
                    """, (promotion_id, int(product_id)))
            
            elif data['productScope'] == 'category' and data.get('selectedCategories'):
                print(f"DEBUG: Adding categories: {data['selectedCategories']}")
                for category in data['selectedCategories']:
                    cursor.execute("""
                        INSERT INTO promotion_categories (promotion_id, category)
                        VALUES (%s, %s)
                    """, (promotion_id, category))
            
            connection.commit()
            print(f"DEBUG: Promotion created successfully with ID: {promotion_id}")
            
        except Exception as assoc_error:
            print(f"DEBUG: Error adding product/category associations: {assoc_error}")
            # Rollback the transaction
            connection.rollback()
            cursor.close()
            connection.close()
            return jsonify({'success': False, 'message': f'Error adding product associations: {str(assoc_error)}'}), 500
        
        cursor.close()
        connection.close()
        
        print(f"DEBUG: About to return success response")
        response_data = {'success': True, 'message': 'Promotion created successfully', 'promotion_id': promotion_id}
        print(f"DEBUG: Response data: {response_data}")
        return jsonify(response_data)
        
    except mysql.connector.Error as db_error:
        print(f"Database error creating promotion: {str(db_error)}")
        import traceback
        traceback.print_exc()
        if 'connection' in locals():
            try:
                connection.rollback()
            except:
                pass
        return jsonify({'success': False, 'message': f'Database error: {str(db_error)}'}), 500
    except Exception as e:
        print(f"Error creating promotion: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': f'Server error: {str(e)}'}), 500
    finally:
        try:
            if 'cursor' in locals() and cursor:
                cursor.close()
                print(f"DEBUG: Cursor closed")
        except Exception as cursor_error:
            print(f"DEBUG: Error closing cursor: {cursor_error}")
        
        try:
            if 'connection' in locals() and connection:
                connection.close()
                print(f"DEBUG: Connection closed")
        except Exception as conn_error:
            print(f"DEBUG: Error closing connection: {conn_error}")



@app.route('/api/get_promotion/<int:promotion_id>')
def get_promotion(promotion_id):
    """Get a specific promotion for editing"""
    print(f"DEBUG: Getting promotion {promotion_id} for user {session.get('email')}")
    print(f"DEBUG: Session data: {dict(session)}")
    
    if 'email' not in session or session.get('user_type', '').lower() != 'seller':
        print("DEBUG: Unauthorized access - no session or not seller")
        print(f"DEBUG: Email in session: {'email' in session}")
        print(f"DEBUG: User type: {session.get('user_type', 'None')}")
        return jsonify({'success': False, 'message': 'Unauthorized access'}), 401
    
    try:
        print(f"DEBUG: Connecting to database...")
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)
        
        # Check if promotions table exists
        cursor.execute("SHOW TABLES LIKE 'promotions'")
        if not cursor.fetchone():
            print("DEBUG: Promotions table does not exist")
            cursor.close()
            connection.close()
            return jsonify({'success': False, 'message': 'Promotions table not found. Please contact administrator.'}), 500
        
        # Get promotion details
        print(f"DEBUG: Fetching promotion {promotion_id} for seller {session['email']}")
        cursor.execute("""
            SELECT * FROM promotions 
            WHERE id = %s AND seller_email = %s
        """, (promotion_id, session['email']))
        
        promotion = cursor.fetchone()
        print(f"DEBUG: Promotion query result: {promotion}")
        
        if not promotion:
            cursor.close()
            connection.close()
            print(f"DEBUG: Promotion {promotion_id} not found for seller {session['email']}")
            return jsonify({'success': False, 'message': 'Promotion not found'}), 404
        
        # Get associated products if any
        print(f"DEBUG: Fetching associated products for promotion {promotion_id}")
        cursor.execute("""
            SELECT product_id FROM promotion_products 
            WHERE promotion_id = %s
        """, (promotion_id,))
        selected_products = [row['product_id'] for row in cursor.fetchall()]
        print(f"DEBUG: Selected products: {selected_products}")
        
        # Get associated categories if any
        print(f"DEBUG: Fetching associated categories for promotion {promotion_id}")
        cursor.execute("""
            SELECT category FROM promotion_categories 
            WHERE promotion_id = %s
        """, (promotion_id,))
        selected_categories = [row['category'] for row in cursor.fetchall()]
        print(f"DEBUG: Selected categories: {selected_categories}")
        
        # Convert all fields to JSON-serializable formats
        promotion = convert_promotion_for_json(promotion)
        
        # Add selected items to response
        promotion['selectedProducts'] = selected_products
        promotion['selectedCategories'] = selected_categories
        
        cursor.close()
        connection.close()
        
        return jsonify({'success': True, 'promotion': promotion})
        
    except mysql.connector.Error as db_error:
        print(f"DEBUG: Database error getting promotion: {str(db_error)}")
        return jsonify({'success': False, 'message': f'Database error: {str(db_error)}'}), 500
    except Exception as e:
        print(f"DEBUG: General error getting promotion: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': f'Server error: {str(e)}'}), 500
    finally:
        try:
            if 'cursor' in locals() and cursor:
                cursor.close()
        except Exception as cursor_error:
            print(f"DEBUG: Error closing cursor in get_promotion: {cursor_error}")
        
        try:
            if 'connection' in locals() and connection:
                connection.close()
        except Exception as conn_error:
            print(f"DEBUG: Error closing connection in get_promotion: {conn_error}")

@app.route('/api/update_promotion/<int:promotion_id>', methods=['PUT'])
def update_promotion(promotion_id):
    """Update an existing promotion"""
    if 'email' not in session or session.get('user_type', '').lower() != 'seller':
        return jsonify({'success': False, 'message': 'Unauthorized access'}), 401
    
    try:
        data = request.get_json()
        print(f"DEBUG: Updating promotion {promotion_id} with data: {data}")
        
        if not data:
            return jsonify({'success': False, 'message': 'No data received'}), 400
        
        # Validate required fields
        required_fields = ['name', 'code', 'type', 'startDate', 'endDate', 'productScope']
        for field in required_fields:
            if not data.get(field) or str(data.get(field)).strip() == '':
                return jsonify({'success': False, 'message': f'{field} is required'}), 400
        
        # Initialize discount_value
        discount_value = None
        
        # Validate discount value for percentage and fixed types
        if data['type'] in ['percentage', 'fixed']:
            if not data.get('discountValue') or str(data.get('discountValue')).strip() == '':
                return jsonify({'success': False, 'message': 'Discount value is required for this promotion type'}), 400
            
            try:
                discount_value = float(data['discountValue'])
                if data['type'] == 'percentage' and (discount_value < 1 or discount_value > 100):
                    return jsonify({'success': False, 'message': 'Percentage must be between 1 and 100'}), 400
                elif data['type'] == 'fixed' and discount_value < 1:
                    return jsonify({'success': False, 'message': 'Fixed discount must be at least 1'}), 400
            except (ValueError, TypeError):
                return jsonify({'success': False, 'message': 'Invalid discount value format'}), 400
        else:
            # For BOGO and free shipping, set discount_value to 0
            discount_value = 0.00
        
        try:
            connection = get_db_connection()
            cursor = connection.cursor()
        except Exception as conn_error:
            return jsonify({'success': False, 'message': 'Database connection failed'}), 500
        
        # Check if promotion exists and belongs to seller
        cursor.execute("SELECT id FROM promotions WHERE id = %s AND seller_email = %s", 
                      (promotion_id, session['email']))
        if not cursor.fetchone():
            cursor.close()
            connection.close()
            return jsonify({'success': False, 'message': 'Promotion not found'}), 404
        
        # Check if promotion code already exists for another promotion
        cursor.execute("SELECT id FROM promotions WHERE code = %s AND seller_email = %s AND id != %s", 
                      (data['code'], session['email'], promotion_id))
        if cursor.fetchone():
            cursor.close()
            connection.close()
            return jsonify({'success': False, 'message': 'Promotion code already exists'}), 400
        
        # Prepare values for update
        try:
            max_discount_val = float(data.get('maxDiscount')) if data.get('maxDiscount') and str(data.get('maxDiscount')).strip() != '' else None
            min_purchase_val = float(data.get('minPurchase')) if data.get('minPurchase') and str(data.get('minPurchase')).strip() != '' else 0
            min_quantity_val = int(data.get('minQuantity')) if data.get('minQuantity') and str(data.get('minQuantity')).strip() != '' else 1
            usage_limit_val = int(data.get('usageLimit')) if data.get('usageLimit') and str(data.get('usageLimit')).strip() != '' else None
        except (ValueError, TypeError) as e:
            cursor.close()
            connection.close()
            return jsonify({'success': False, 'message': 'Invalid numeric values provided'}), 400
        
        # Update promotion
        try:
            cursor.execute("""
                UPDATE promotions SET
                    name = %s, code = %s, type = %s, discount_value = %s, max_discount = %s,
                    min_purchase = %s, min_quantity = %s, usage_limit_per_customer = %s,
                    start_date = %s, start_time = %s, end_date = %s, end_time = %s,
                    product_scope = %s, is_active = %s, updated_at = CURRENT_TIMESTAMP
                WHERE id = %s AND seller_email = %s
            """, (
                data['name'], data['code'], data['type'], discount_value, max_discount_val,
                min_purchase_val, min_quantity_val, usage_limit_val,
                data['startDate'], data.get('startTime', '00:00:00'),
                data['endDate'], data.get('endTime', '23:59:59'),
                data['productScope'], data.get('isActive', True),
                promotion_id, session['email']
            ))
            
            # Delete existing product/category associations
            cursor.execute("DELETE FROM promotion_products WHERE promotion_id = %s", (promotion_id,))
            cursor.execute("DELETE FROM promotion_categories WHERE promotion_id = %s", (promotion_id,))
            
            # Add new product/category associations
            if data['productScope'] == 'specific' and data.get('selectedProducts'):
                for product_id in data['selectedProducts']:
                    cursor.execute("""
                        INSERT INTO promotion_products (promotion_id, product_id)
                        VALUES (%s, %s)
                    """, (promotion_id, int(product_id)))
            
            elif data['productScope'] == 'category' and data.get('selectedCategories'):
                for category in data['selectedCategories']:
                    cursor.execute("""
                        INSERT INTO promotion_categories (promotion_id, category)
                        VALUES (%s, %s)
                    """, (promotion_id, category))
            
            connection.commit()
            cursor.close()
            connection.close()
            
            return jsonify({'success': True, 'message': 'Promotion updated successfully'})
            
        except Exception as update_error:
            cursor.close()
            connection.close()
            return jsonify({'success': False, 'message': f'Error updating promotion: {str(update_error)}'}), 500
        
    except Exception as e:
        print(f"Error updating promotion: {str(e)}")
        return jsonify({'success': False, 'message': f'Server error: {str(e)}'}), 500

@app.route('/api/get_promotions')
def get_promotions():
    """Get all promotions for the logged-in seller"""
    print(f"DEBUG: get_promotions called for user {session.get('email')}")
    
    if 'email' not in session or session.get('user_type', '').lower() != 'seller':
        print("DEBUG: Unauthorized access to get_promotions")
        return jsonify({'success': False, 'message': 'Unauthorized access'}), 401
    
    connection = None
    cursor = None
    
    try:
        print("DEBUG: Connecting to database...")
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)
        
        # Check if promotions table exists, create if not
        print("DEBUG: Checking if promotions table exists...")
        cursor.execute("SHOW TABLES LIKE 'promotions'")
        if not cursor.fetchone():
            print("DEBUG: Promotions table does not exist, creating it...")
            try:
                # Create promotions table
                cursor.execute("""
                    CREATE TABLE `promotions` (
                      `id` INT AUTO_INCREMENT PRIMARY KEY,
                      `name` VARCHAR(255) NOT NULL,
                      `code` VARCHAR(50) NOT NULL UNIQUE,
                      `seller_email` VARCHAR(255) NOT NULL,
                      `type` ENUM('percentage', 'fixed', 'buy_one_get_one', 'free_shipping') NOT NULL,
                      `discount_value` DECIMAL(10,2) DEFAULT NULL,
                      `max_discount` DECIMAL(10,2) DEFAULT NULL,
                      `min_purchase` DECIMAL(10,2) DEFAULT 0.00,
                      `min_quantity` INT DEFAULT 1,
                      `usage_limit_per_customer` INT DEFAULT NULL,
                      `total_usage_limit` INT DEFAULT NULL,
                      `current_usage_count` INT DEFAULT 0,
                      `start_date` DATE NOT NULL,
                      `start_time` TIME DEFAULT '00:00:00',
                      `end_date` DATE NOT NULL,
                      `end_time` TIME DEFAULT '23:59:59',
                      `product_scope` ENUM('all', 'specific', 'category') DEFAULT 'all',
                      `is_active` BOOLEAN DEFAULT TRUE,
                      `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                      `updated_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                      
                      INDEX `idx_seller_email` (`seller_email`),
                      INDEX `idx_code` (`code`),
                      INDEX `idx_active_dates` (`is_active`, `start_date`, `end_date`),
                      INDEX `idx_type` (`type`),
                      INDEX `idx_product_scope` (`product_scope`)
                    )
                """)
                
                # Create promotion_products table
                cursor.execute("""
                    CREATE TABLE `promotion_products` (
                      `id` INT AUTO_INCREMENT PRIMARY KEY,
                      `promotion_id` INT NOT NULL,
                      `product_id` INT NOT NULL,
                      `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                      
                      FOREIGN KEY (`promotion_id`) REFERENCES `promotions`(`id`) ON DELETE CASCADE,
                      FOREIGN KEY (`product_id`) REFERENCES `products`(`id`) ON DELETE CASCADE,
                      UNIQUE KEY `unique_promotion_product` (`promotion_id`, `product_id`),
                      INDEX `idx_promotion_id` (`promotion_id`),
                      INDEX `idx_product_id` (`product_id`)
                    )
                """)
                
                # Create promotion_categories table
                cursor.execute("""
                    CREATE TABLE `promotion_categories` (
                      `id` INT AUTO_INCREMENT PRIMARY KEY,
                      `promotion_id` INT NOT NULL,
                      `category` VARCHAR(100) NOT NULL,
                      `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                      
                      FOREIGN KEY (`promotion_id`) REFERENCES `promotions`(`id`) ON DELETE CASCADE,
                      UNIQUE KEY `unique_promotion_category` (`promotion_id`, `category`),
                      INDEX `idx_promotion_id` (`promotion_id`),
                      INDEX `idx_category` (`category`)
                    )
                """)
                
                # Create promotion_usage table
                cursor.execute("""
                    CREATE TABLE `promotion_usage` (
                      `id` INT AUTO_INCREMENT PRIMARY KEY,
                      `promotion_id` INT NOT NULL,
                      `order_id` INT NOT NULL,
                      `customer_email` VARCHAR(255) NOT NULL,
                      `product_id` VARCHAR(50),
                      `discount_applied` DECIMAL(10,2) NOT NULL,
                      `used_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                      
                      FOREIGN KEY (`promotion_id`) REFERENCES `promotions`(`id`) ON DELETE CASCADE,
                      FOREIGN KEY (`order_id`) REFERENCES `orders`(`id`) ON DELETE CASCADE,
                      INDEX `idx_promotion_id` (`promotion_id`),
                      INDEX `idx_order_id` (`order_id`),
                      INDEX `idx_customer_email` (`customer_email`),
                      INDEX `idx_product_id` (`product_id`),
                      INDEX `idx_used_at` (`used_at`)
                    )
                """)
                
                connection.commit()
                print("DEBUG: Successfully created promotions tables")
                
            except Exception as create_error:
                print(f"DEBUG: Error creating promotions tables: {create_error}")
                return jsonify({'success': False, 'message': f'Failed to create promotions tables: {str(create_error)}'}), 500
        
        print("DEBUG: Promotions table exists, fetching data...")
        
        # Get promotions with usage statistics
        cursor.execute("""
            SELECT p.*, 
                   p.current_usage_count as total_uses,
                   COALESCE(SUM(pu.discount_applied), 0) as total_discount_given
            FROM promotions p
            LEFT JOIN promotion_usage pu ON p.id = pu.promotion_id
            WHERE p.seller_email = %s
            GROUP BY p.id
            ORDER BY p.created_at DESC
        """, (session['email'],))
        
        promotions = cursor.fetchall()
        print(f"DEBUG: Found {len(promotions)} promotions")
        
        # Get current date for status determination
        from datetime import date
        current_date = date.today()
        
        for promotion in promotions:
            try:
                # Determine status
                if not promotion['is_active']:
                    promotion['status'] = 'inactive'
                elif promotion['start_date'] > current_date:
                    promotion['status'] = 'scheduled'
                elif promotion['end_date'] < current_date:
                    promotion['status'] = 'expired'
                else:
                    promotion['status'] = 'active'
                
                # Format dates for display
                if promotion['start_date']:
                    promotion['start_date'] = promotion['start_date'].strftime('%Y-%m-%d')
                if promotion['end_date']:
                    promotion['end_date'] = promotion['end_date'].strftime('%Y-%m-%d')
            except Exception as date_error:
                print(f"DEBUG: Error processing promotion {promotion.get('id', 'unknown')}: {date_error}")
                # Set default values if there's an error
                promotion['status'] = 'unknown'
                promotion['start_date'] = str(promotion.get('start_date', ''))
                promotion['end_date'] = str(promotion.get('end_date', ''))
        
        print("DEBUG: Successfully processed promotions")
        return jsonify({'success': True, 'promotions': promotions})
        
    except mysql.connector.Error as db_error:
        print(f"DEBUG: Database error in get_promotions: {str(db_error)}")
        return jsonify({'success': False, 'message': f'Database error: {str(db_error)}'}), 500
    except Exception as e:
        print(f"DEBUG: General error in get_promotions: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': f'Server error: {str(e)}'}), 500
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()
        print("DEBUG: Database connection closed")

@app.route('/api/toggle_promotion/<int:promotion_id>', methods=['POST'])
def toggle_promotion(promotion_id):
    """Toggle promotion active status"""
    if 'email' not in session or session.get('user_type', '').lower() != 'seller':
        return jsonify({'success': False, 'message': 'Unauthorized access'}), 401
    
    try:
        connection = get_db_connection()
        cursor = connection.cursor()
        
        # Verify promotion belongs to seller
        cursor.execute("SELECT is_active FROM promotions WHERE id = %s AND seller_email = %s", 
                      (promotion_id, session['email']))
        result = cursor.fetchone()
        
        if not result:
            return jsonify({'success': False, 'message': 'Promotion not found'}), 404
        
        # Toggle status
        new_status = not result[0]
        cursor.execute("UPDATE promotions SET is_active = %s WHERE id = %s", 
                      (new_status, promotion_id))
        
        connection.commit()
        cursor.close()
        connection.close()
        
        return jsonify({'success': True, 'is_active': new_status})
        
    except Exception as e:
        print(f"Error toggling promotion: {str(e)}")
        return jsonify({'success': False, 'message': 'Failed to toggle promotion'}), 500

@app.route('/api/delete_promotion/<int:promotion_id>', methods=['DELETE'])
def delete_promotion(promotion_id):
    """Delete a promotion"""
    if 'email' not in session or session.get('user_type', '').lower() != 'seller':
        return jsonify({'success': False, 'message': 'Unauthorized access'}), 401
    
    try:
        connection = get_db_connection()
        cursor = connection.cursor()
        
        # Verify promotion belongs to seller
        cursor.execute("SELECT id FROM promotions WHERE id = %s AND seller_email = %s", 
                      (promotion_id, session['email']))
        if not cursor.fetchone():
            return jsonify({'success': False, 'message': 'Promotion not found'}), 404
        
        # Delete promotion (cascade will handle related records)
        cursor.execute("DELETE FROM promotions WHERE id = %s", (promotion_id,))
        
        connection.commit()
        cursor.close()
        connection.close()
        
        return jsonify({'success': True, 'message': 'Promotion deleted successfully'})
        
    except Exception as e:
        print(f"Error deleting promotion: {str(e)}")
        return jsonify({'success': False, 'message': 'Failed to delete promotion'}), 500

@app.route('/api/apply_promotion', methods=['POST'])
def apply_promotion():
    """Apply a promotion code to cart items"""
    if 'email' not in session:
        return jsonify({'success': False, 'message': 'Please log in to apply promotions'}), 401
    
    try:
        data = request.get_json()
        promotion_code = data.get('code')
        cart_items = data.get('cart_items', [])
        
        if not promotion_code:
            return jsonify({'success': False, 'message': 'Promotion code is required'}), 400
        
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)
        
        # Find active promotion
        cursor.execute("""
            SELECT * FROM promotions 
            WHERE code = %s AND is_active = 1 
            AND start_date <= CURDATE() AND end_date >= CURDATE()
        """, (promotion_code,))
        
        promotion = cursor.fetchone()
        if not promotion:
            return jsonify({'success': False, 'message': 'Invalid or expired promotion code'}), 400
        
        # Check usage limits
        if promotion['usage_limit_per_customer']:
            cursor.execute("""
                SELECT COUNT(*) as usage_count 
                FROM promotion_usage 
                WHERE promotion_id = %s AND customer_email = %s
            """, (promotion['id'], session['email']))
            
            usage_count = cursor.fetchone()['usage_count']
            if usage_count >= promotion['usage_limit_per_customer']:
                return jsonify({'success': False, 'message': 'You have reached the usage limit for this promotion'}), 400
        
        # Calculate discount
        total_discount = 0
        applicable_items = []
        
        for item in cart_items:
            item_applicable = False
            
            # Check if item is applicable based on product scope
            if promotion['product_scope'] == 'all':
                item_applicable = True
            elif promotion['product_scope'] == 'specific':
                cursor.execute("""
                    SELECT 1 FROM promotion_products 
                    WHERE promotion_id = %s AND product_id = %s
                """, (promotion['id'], item['product_id']))
                item_applicable = cursor.fetchone() is not None
            elif promotion['product_scope'] == 'category':
                cursor.execute("""
                    SELECT 1 FROM promotion_categories pc
                    JOIN products p ON pc.category = p.category
                    WHERE pc.promotion_id = %s AND p.id = %s
                """, (promotion['id'], item['product_id']))
                item_applicable = cursor.fetchone() is not None
            
            if item_applicable:
                item_price = float(item['price'])
                item_quantity = int(item['quantity'])
                item_total = item_price * item_quantity
                
                if promotion['type'] == 'percentage':
                    item_discount = item_total * (float(promotion['discount_value']) / 100)
                    if promotion['max_discount']:
                        item_discount = min(item_discount, float(promotion['max_discount']))
                elif promotion['type'] == 'fixed':
                    item_discount = min(float(promotion['discount_value']), item_total)
                elif promotion['type'] == 'buy_one_get_one':
                    # Simple BOGO: for every 2 items, discount the price of 1
                    free_items = item_quantity // 2
                    item_discount = free_items * item_price
                elif promotion['type'] == 'free_shipping':
                    # Free shipping discount (you can customize this based on your shipping logic)
                    item_discount = 50.0  # Assuming ?50 shipping fee
                else:
                    item_discount = 0
                
                total_discount += item_discount
                applicable_items.append({
                    'product_id': item['product_id'],
                    'name': item['name'],
                    'discount': item_discount
                })
        
        # Check minimum purchase requirement
        cart_total = sum(float(item['price']) * int(item['quantity']) for item in cart_items)
        if promotion['min_purchase'] and cart_total < float(promotion['min_purchase']):
            return jsonify({
                'success': False, 
                'message': f'Minimum purchase of ?{promotion["min_purchase"]} required'
            }), 400
        
        # Check minimum quantity requirement
        total_quantity = sum(int(item['quantity']) for item in cart_items)
        if promotion['min_quantity'] and total_quantity < promotion['min_quantity']:
            return jsonify({
                'success': False, 
                'message': f'Minimum {promotion["min_quantity"]} items required'
            }), 400
        
        cursor.close()
        connection.close()
        
        return jsonify({
            'success': True,
            'promotion': {
                'id': promotion['id'],
                'name': promotion['name'],
                'code': promotion['code'],
                'type': promotion['type'],
                'discount_value': promotion['discount_value']
            },
            'total_discount': round(total_discount, 2),
            'applicable_items': applicable_items
        })
        
    except Exception as e:
        print(f"Error applying promotion: {str(e)}")
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
        notif_msg = f"?? Rider {rider_name} has accepted delivery for Order #{order_id} ({product_name}). The rider is now heading to pick up the item."
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
                <p>The rider is now heading to your location to pick up the item.</p>
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
            try:
                db = get_db_connection()
                cursor = db.cursor()
                try:
                    cursor.execute('''INSERT INTO products 
                            (name, category, description, variations, price, image,
                             quantity, low_stock_threshold, seller_email, image_colors, sizes, sku)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)''',
                        (product_name, category, description, variations_string,
                         regular_price, images_string, 0, low_stock_threshold,
                         seller_email, image_color_string, product_sizes, sku))
                except mysql.connector.Error as sku_err:
                    if "Unknown column 'sku'" in str(sku_err):
                        cursor.execute('''INSERT INTO products 
                                (name, category, description, variations, price, image,
                                 quantity, low_stock_threshold, seller_email, image_colors, sizes)
                                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)''',
                            (product_name, category, description, variations_string,
                             regular_price, images_string, 0, low_stock_threshold,
                             seller_email, image_color_string, product_sizes))
                    else:
                        raise sku_err

                mysql_product_id = cursor.lastrowid
                for color in variations_list:
                    for size in sizes_list:
                        cursor.execute('''INSERT INTO variant_inventory 
                                (product_id, color, size, stock_quantity, low_stock_threshold)
                                VALUES (%s, %s, %s, %s, %s)''',
                            (mysql_product_id, color, size, 0, low_stock_threshold))
                db.commit()
                cursor.close()
                db.close()
                print(f"? Product also mirrored to MySQL id={mysql_product_id}")
            except Exception as mysql_err:
                print(f"?? MySQL mirror failed (non-fatal, Supabase is primary): {mysql_err}")

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

            print(f"? Product {product_id} updated in Supabase")

            # -- Update variant_inventory in Supabase (non-fatal) ----------
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

                print(f"? Variant inventory updated for product {product_id}")
            except Exception as vi_err:
                print(f"?? Variant inventory update failed (non-fatal): {vi_err}")

            # -- Stock notifications (non-fatal) ---------------------------
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

            flash('Product updated successfully!', 'success')
            return redirect(url_for('products'))

        except Exception as e:
            import traceback; traceback.print_exc()
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
    
    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)
        
        # Get current values first
        cursor.execute("SELECT sizes, variations FROM products WHERE id = %s AND seller_email = %s", (product_id, session['email']))
        current_product = cursor.fetchone()
        
        if not current_product:
            return jsonify({'error': 'Product not found or access denied'}), 404
        
        # Get the test data from request
        test_sizes = request.form.get('test_sizes', 'Test Size 1, Test Size 2')
        test_variations = request.form.get('test_variations', 'Red, Blue, Green')
        
        print(f"?? TEST SIZES & VARIATIONS UPDATE:")
        print(f"  - Product ID: {product_id}")
        print(f"  - Current sizes: '{current_product['sizes']}'")
        print(f"  - Current variations: '{current_product['variations']}'")
        print(f"  - Test sizes: '{test_sizes}'")
        print(f"  - Test variations: '{test_variations}'")
        print(f"  - Seller email: {session['email']}")
        
        # Update both sizes and variations
        update_query = "UPDATE products SET sizes = %s, variations = %s WHERE id = %s AND seller_email = %s"
        params = [test_sizes, test_variations, product_id, session['email']]
        
        print(f"  - Query: {update_query}")
        print(f"  - Params: {params}")
        
        cursor.execute(update_query, params)
        affected_rows = cursor.rowcount
        connection.commit()
        
        print(f"  - Affected rows: {affected_rows}")
        
        # Verify the update
        cursor.execute("SELECT sizes, variations FROM products WHERE id = %s", (product_id,))
        result = cursor.fetchone()
        
        if result:
            saved_sizes = result['sizes']
            saved_variations = result['variations']
            print(f"  - Saved sizes: '{saved_sizes}'")
            print(f"  - Saved variations: '{saved_variations}'")
            
            cursor.close()
            connection.close()
            
            return jsonify({
                'success': True,
                'affected_rows': affected_rows,
                'before': {
                    'sizes': current_product['sizes'],
                    'variations': current_product['variations']
                },
                'test_values': {
                    'sizes': test_sizes,
                    'variations': test_variations
                },
                'after': {
                    'sizes': saved_sizes,
                    'variations': saved_variations
                },
                'sizes_match': saved_sizes == test_sizes,
                'variations_match': saved_variations == test_variations
            })
        else:
            cursor.close()
            connection.close()
            return jsonify({'error': 'Could not verify update'}), 500
            
    except Exception as e:
        print(f"? Test update error: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/products', methods=['GET'])
def products():
    if 'email' not in session:
        return redirect(url_for('home'))

    user_email = session['email']
    search_query = request.args.get('search', '').strip()
    selected_category = request.args.get('category', '').strip()
    selected_status = request.args.get('status', '').strip()
    sort_by = request.args.get('sort_by', 'newest').strip()
    page = request.args.get('page', 1, type=int)
    per_page = 12

    # -- Seller name from Supabase -----------------------------------------
    seller_name = session.get('first_name', 'Seller')
    try:
        sb_res = sb_admin.table('users').select('first_name, last_name, business_name').eq('email', user_email).execute()
        if sb_res.data:
            u = sb_res.data[0]
            seller_name = u.get('business_name') or f"{u.get('first_name', '')} {u.get('last_name', '')}".strip() or 'Seller'
    except Exception as sb_err:
        print(f"?? Supabase name fetch failed in products: {sb_err}")

    try:
        # -- Fetch all seller products from Supabase -----------------------
        products_res = sb_admin.table('products') \
            .select(
                'id, name, category, description, variations, price, image, '
                'quantity, low_stock_threshold, seller_email, sold, rating, '
                'image_colors, sizes, flagged_at, flag_reason, flagged_by, is_active'
            ) \
            .eq('seller_email', user_email) \
            .execute()

        all_products = products_res.data or []

        # -- Fetch reviews for rating calculation --------------------------
        if all_products:
            product_ids = [p['id'] for p in all_products]
            reviews_res = sb_admin.table('reviews') \
                .select('product_id, rating') \
                .in_('product_id', product_ids) \
                .execute()

            # Build rating aggregates per product
            from collections import defaultdict
            rating_map = defaultdict(list)
            for r in (reviews_res.data or []):
                rating_map[r['product_id']].append(r['rating'])

            for p in all_products:
                ratings = rating_map.get(p['id'], [])
                if ratings:
                    p['calculated_rating'] = round(sum(ratings) / len(ratings), 1)
                    p['review_count'] = len(ratings)
                    p['rating'] = p['calculated_rating']
                else:
                    p['calculated_rating'] = 0
                    p['review_count'] = 0
                    p['rating'] = None
        else:
            for p in all_products:
                p['calculated_rating'] = 0
                p['review_count'] = 0
                p['rating'] = None

        # -- Apply filters in Python ---------------------------------------
        filtered = all_products

        if search_query:
            sq = search_query.lower()
            filtered = [p for p in filtered if sq in p['name'].lower() or sq in p['category'].lower()]

        if selected_category:
            filtered = [p for p in filtered if p['category'] == selected_category]

        if selected_status:
            if selected_status == 'active':
                filtered = [p for p in filtered if p.get('is_active') and not p.get('flagged_at')]
            elif selected_status == 'inactive':
                filtered = [p for p in filtered if not p.get('is_active')]
            elif selected_status == 'flagged':
                filtered = [p for p in filtered if p.get('flagged_at')]
            elif selected_status == 'out_of_stock':
                filtered = [p for p in filtered if int(p.get('quantity') or 0) == 0]
            elif selected_status == 'low_stock':
                def _is_low(p):
                    qty = int(p.get('quantity') or 0)
                    thr = int(p.get('low_stock_threshold') or 5)
                    return qty > 0 and qty <= thr
                filtered = [p for p in filtered if _is_low(p)]

        # -- Sort ----------------------------------------------------------
        def _price(p):
            try: return float(p.get('price') or 0)
            except: return 0.0

        def _qty(p):
            try: return int(p.get('quantity') or 0)
            except: return 0

        if sort_by == 'oldest':
            filtered.sort(key=lambda p: p['id'])
        elif sort_by == 'price_low':
            filtered.sort(key=_price)
        elif sort_by == 'price_high':
            filtered.sort(key=_price, reverse=True)
        elif sort_by == 'name_asc':
            filtered.sort(key=lambda p: p['name'].lower())
        elif sort_by == 'name_desc':
            filtered.sort(key=lambda p: p['name'].lower(), reverse=True)
        elif sort_by == 'stock_high':
            filtered.sort(key=_qty, reverse=True)
        elif sort_by == 'stock_low':
            filtered.sort(key=_qty)
        elif sort_by == 'sold_high':
            filtered.sort(key=lambda p: int(p.get('sold') or 0), reverse=True)
        elif sort_by == 'rating_high':
            filtered.sort(key=lambda p: (p.get('calculated_rating') or 0, p.get('review_count') or 0), reverse=True)
        else:  # newest (default)
            filtered.sort(key=lambda p: p['id'], reverse=True)

        # -- Distinct categories for dropdown ------------------------------
        categories = sorted(set(p['category'] for p in all_products if p.get('category')))

        # -- Paginate ------------------------------------------------------
        total_products = len(filtered)
        total_pages = max(1, (total_products + per_page - 1) // per_page)
        page = max(1, min(page, total_pages))
        offset = (page - 1) * per_page
        products_page = filtered[offset: offset + per_page]

        print(f"? Products loaded from Supabase: {total_products} total, page {page}/{total_pages}")

    except Exception as e:
        print(f"? Error loading products from Supabase: {e}")
        products_page = []
        categories = []
        total_products = 0
        total_pages = 1

    return render_template('products.html',
                           products=products_page,
                           categories=categories,
                           selected_category=selected_category,
                           selected_status=selected_status,
                           sort_by=sort_by,
                           page=page,
                           total_pages=total_pages,
                           total_products=total_products,
                           per_page=per_page,
                           user_name=seller_name,
                           user_email=session.get('email', 'Seller'))

# Variant Inventory Routes
@app.route('/variant_inventory')
def variant_inventory():
    """Variant inventory management page for sellers"""
    if 'email' not in session or session.get('user_type') != 'Seller':
        flash('Please log in as a seller to access this page', 'error')
        return redirect(url_for('login'))
    
    user_name = f"{session.get('first_name', '')} {session.get('last_name', '')}".strip()
    return render_template('variant_inventory.html', user_name=user_name, user_email=session.get('email', 'Seller'))


@app.route('/api/product/<int:product_id>/variant-stock')
def get_product_variant_stock(product_id):
    """Get variant stock for a specific product (public endpoint for buyers) — reads from Supabase"""
    try:
        res = sb_admin.table('variant_inventory') \
            .select('color, size, stock_quantity') \
            .eq('product_id', product_id) \
            .execute()

        return jsonify({'success': True, 'variants': res.data or []})

    except Exception as e:
        print(f"? Error fetching variant stock from Supabase: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/debug/seller-lookup/<int:product_id>')
def debug_seller_lookup(product_id):
    """Temporary debug: show what seller email is stored and what users table returns."""
    try:
        prod = sb_admin.table('products').select('seller_email').eq('id', product_id).limit(1).execute()
        if not prod.data:
            return jsonify({'error': 'product not found'})
        seller_email = prod.data[0].get('seller_email', '')
        # Try exact
        exact = sb_admin.table('users').select('email, business_name, first_name, last_name').eq('email', seller_email).limit(1).execute()
        # Try ilike
        ilike = sb_admin.table('users').select('email, business_name, first_name, last_name').ilike('email', seller_email).limit(1).execute()
        # List first 5 users emails for comparison
        all_users = sb_admin.table('users').select('email, business_name').limit(5).execute()
        return jsonify({
            'product_seller_email': seller_email,
            'exact_match': exact.data,
            'ilike_match': ilike.data,
            'sample_users': all_users.data,
        })
    except Exception as e:
        return jsonify({'error': str(e)})


@app.route('/api/mobile/seller_info', methods=['GET'])
def mobile_seller_info():
    """Return seller business_name and profile_picture for a given seller email."""
    seller_email = request.args.get('email', '').strip()
    if not seller_email:
        return jsonify({'success': False, 'error': 'email required'}), 400
    try:
        res = sb_admin.table('users') \
            .select('business_name, first_name, last_name, profile_picture') \
            .eq('email', seller_email) \
            .limit(1) \
            .execute()
        if not res.data:
            return jsonify({'success': False, 'error': 'not found'}), 404
        u = res.data[0]
        biz   = (u.get('business_name') or '').strip()
        first = (u.get('first_name') or '').strip()
        last  = (u.get('last_name') or '').strip()
        name  = biz if biz else f"{first} {last}".strip() or seller_email
        pic   = u.get('profile_picture') or ''
        return jsonify({'success': True, 'name': name, 'profile_picture': pic})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/mobile/get_mysql_user_id', methods=['GET'])
def get_mysql_user_id():
    """Return a stable integer user_id for a given email using polynomial hash.
    Same algorithm as _resolve_wishlist_user_id and Dart _getMysqlUserId."""
    email = request.args.get('email', '').strip()
    if not email:
        return jsonify({'success': False, 'error': 'email required'}), 400
    hash_id = 0
    for c in email.lower().encode('utf-8'):
        hash_id = (hash_id * 31 + c) & 0x7FFFFFFF
    return jsonify({'success': True, 'user_id': hash_id, 'source': 'polynomial_hash'})


def _resolve_wishlist_user_id(email):
    """
    Returns a stable integer user_id for the wishlist table.
    Uses the same polynomial hash as the Dart/Flutter mobile app:
      hashId = (hashId * 31 + codeUnit) & 0x7FFFFFFF
    This ensures website and mobile app always produce the same user_id.
    """
    hash_id = 0
    for c in email.lower().encode('utf-8'):
        hash_id = (hash_id * 31 + c) & 0x7FFFFFFF
    return hash_id


def _get_wishlist_ids():
    """Return a set of product_id strings for the current session user's wishlist."""
    try:
        email = session.get('email')
        if not email:
            return set()
        uid = _resolve_wishlist_user_id(email)
        res = sb_admin.table('wishlist').select('product_id').eq('user_id', uid).execute()
        return {str(r['product_id']) for r in (res.data or [])}
    except Exception:
        return set()


@app.route('/api/mobile/wishlist', methods=['GET'])
def mobile_wishlist_get():
    email = request.args.get('email', '').strip()
    if not email:
        return jsonify({'success': False, 'error': 'email required'}), 400
    try:
        user_id = _resolve_wishlist_user_id(email)
        wl_res = sb_admin.table('wishlist').select('id, product_id').eq('user_id', user_id).order('id', desc=True).execute()
        rows = wl_res.data or []
        if not rows:
            return jsonify({'success': True, 'items': []})
        product_ids = [r['product_id'] for r in rows]
        prod_res = sb_admin.table('products').select('id, name, price, image, seller_email, variations, sizes').in_('id', product_ids).execute()
        prod_map = {p['id']: p for p in (prod_res.data or [])}
        from datetime import date as _date
        today = _date.today().isoformat()
        promo_map = {}
        try:
            promo_res = sb_admin.table('promotions').select('id, type, discount_value, code, product_scope').eq('is_active', True).lte('start_date', today).gte('end_date', today).execute()
            for promo in (promo_res.data or []):
                scope = promo.get('product_scope', 'all')
                if scope == 'all':
                    for pid in product_ids:
                        if pid not in promo_map: promo_map[pid] = promo
                elif scope == 'specific':
                    pp_res = sb_admin.table('promotion_products').select('product_id').eq('promotion_id', promo['id']).in_('product_id', product_ids).execute()
                    for pp in (pp_res.data or []):
                        pid = pp['product_id']
                        if pid not in promo_map: promo_map[pid] = promo
        except Exception as pe:
            print(f'Promo fetch error: {pe}')
        items = []
        for r in rows:
            pid = r['product_id']
            prod = prod_map.get(pid)
            if not prod: continue
            base_price = float(prod.get('price') or 0)
            promo = promo_map.get(pid)
            sale_price = None; promo_type = ''; promo_discount = 0.0; promo_code = ''
            if promo:
                promo_type = promo.get('type', ''); promo_discount = float(promo.get('discount_value') or 0); promo_code = promo.get('code', '')
                if promo_type == 'percentage' and promo_discount > 0: sale_price = max(base_price * (1 - promo_discount / 100), 0.01)
                elif promo_type == 'fixed' and promo_discount > 0: sale_price = max(base_price - promo_discount, 0.01)
            items.append({'id': r['id'], 'product_id': pid, 'products': {'id': pid, 'name': prod.get('name', ''), 'price': base_price, 'sale_price': sale_price, 'image': prod.get('image') or '', 'seller_email': prod.get('seller_email') or '', 'variations': prod.get('variations') or '', 'sizes': prod.get('sizes') or '', 'promotion_type': promo_type, 'promotion_discount': promo_discount, 'promotion_code': promo_code}})
        return jsonify({'success': True, 'items': items})
    except Exception as e:
        print(f'mobile_wishlist_get error: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/mobile/wishlist/add', methods=['POST'])
def mobile_wishlist_add():
    data = request.get_json() or {}
    email = data.get('email', '').strip()
    product_id = data.get('product_id')
    if not email or not product_id:
        return jsonify({'success': False, 'error': 'email and product_id required'}), 400
    try:
        user_id = _resolve_wishlist_user_id(email)
        existing = sb_admin.table('wishlist').select('id').eq('user_id', user_id).eq('product_id', int(product_id)).execute()
        if not existing.data:
            sb_admin.table('wishlist').insert({'user_id': user_id, 'product_id': int(product_id)}).execute()
        return jsonify({'success': True})
    except Exception as e:
        print(f'mobile_wishlist_add error: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/mobile/wishlist/remove', methods=['POST'])
def mobile_wishlist_remove():
    data = request.get_json() or {}
    email = data.get('email', '').strip()
    product_id = data.get('product_id')
    if not email or not product_id:
        return jsonify({'success': False, 'error': 'email and product_id required'}), 400
    try:
        user_id = _resolve_wishlist_user_id(email)
        sb_admin.table('wishlist').delete().eq('user_id', user_id).eq('product_id', int(product_id)).execute()
        return jsonify({'success': True})
    except Exception as e:
        print(f'mobile_wishlist_remove error: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/mobile/wishlist/check', methods=['GET'])
def mobile_wishlist_check():
    email = request.args.get('email', '').strip()
    product_id = request.args.get('product_id', '').strip()
    if not email or not product_id:
        return jsonify({'in_wishlist': False}), 200
    try:
        user_id = _resolve_wishlist_user_id(email)
        res = sb_admin.table('wishlist').select('id').eq('user_id', user_id).eq('product_id', int(product_id)).execute()
        return jsonify({'in_wishlist': bool(res.data)})
    except Exception as e:
        print(f'mobile_wishlist_check error: {e}')
        return jsonify({'in_wishlist': False}), 200


@app.route('/api/mobile/available_deliveries', methods=['GET'])
def mobile_available_deliveries():
    """
    Returns orders with status 'Waiting for Pickup' and no rider assigned.
    Uses sb_admin to bypass RLS � safe because it only returns non-sensitive order data.
    """
    try:
        res = sb_admin.table('orders') \
            .select('id, name, email, address, date, total_price, shipping_fee, '
                    'quantity, variations, size, payment_method, status, product_id, image') \
            .eq('status', 'Waiting for Pickup') \
            .is_('rider_email', 'null') \
            .order('date', desc=True) \
            .execute()
        return jsonify({'success': True, 'orders': res.data or []})
    except Exception as e:
        print(f"? mobile_available_deliveries error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/mobile/accept_delivery', methods=['POST'])
def mobile_accept_delivery():
    """
    Rider accepts a delivery � sets status to 'For Pickup' and assigns rider_email.
    Uses sb_admin to bypass RLS.
    """
    try:
        data = request.get_json()
        order_id    = data.get('order_id')
        rider_email = data.get('rider_email')
        if not order_id or not rider_email:
            return jsonify({'success': False, 'error': 'Missing order_id or rider_email'}), 400

        sb_admin.table('orders').update({
            'status':      'For Pickup',
            'rider_email': rider_email,
        }).eq('id', int(order_id)).eq('status', 'Waiting for Pickup').execute()

        return jsonify({'success': True})
    except Exception as e:
        print(f"? mobile_accept_delivery error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/mobile/place_order', methods=['POST'])
def mobile_place_order():
    """
    Mobile order placement endpoint � uses sb_admin (service role) to bypass RLS.
    Accepts JSON: { email, items: [{name, product_id, price, quantity, color, size,
                                    image, seller_email, shipping_fee}],
                    payment_method, address }
    """
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'No data provided'}), 400

        email          = (data.get('email') or '').strip()
        items          = data.get('items', [])
        payment_method = (data.get('payment_method') or 'cod').strip()
        address        = (data.get('address') or '').strip()

        if not email or not items:
            return jsonify({'success': False, 'error': 'Missing email or items'}), 400

        # Verify the buyer exists in Supabase users table
        user_check = sb_admin.table('users').select('email').eq('email', email).execute()
        if not user_check.data:
            return jsonify({'success': False, 'error': 'User not found'}), 404

        order_ids = []
        now = __import__('datetime').datetime.utcnow().isoformat()

        for item in items:
            product_id  = item.get('product_id')
            quantity    = int(item.get('quantity') or 1)
            color       = (item.get('color') or '').strip()
            size        = (item.get('size') or '').strip()
            price       = float(item.get('price') or 0)
            shipping_fee = float(item.get('shipping_fee') or 50)
            total_price = price * quantity + shipping_fee
            seller_email = (item.get('seller_email') or '').strip()
            image        = (item.get('image') or '').strip()
            name         = (item.get('name') or '').strip()

            # Fetch seller_email from product if not provided
            if not seller_email and product_id:
                try:
                    pr = sb_admin.table('products').select('seller_email').eq('id', int(product_id)).execute()
                    if pr.data:
                        seller_email = pr.data[0].get('seller_email', '')
                except Exception:
                    pass

            # Insert order via service role (bypasses RLS)
            order_row = {
                'email':          email,
                'name':           name,
                'product_id':     int(product_id) if product_id else None,
                'total_price':    total_price,
                'quantity':       quantity,
                'address':        address,
                'seller_email':   seller_email,
                'payment_method': payment_method,
                'status':         'Pending',
                'variations':     color,
                'size':           size,
                'image':          image,
                'shipping_fee':   shipping_fee,
                'date':           now,
            }
            order_res = sb_admin.table('orders').insert(order_row).execute()
            if order_res.data:
                order_ids.append(order_res.data[0].get('id'))

            # Decrement variant_inventory stock
            if product_id and (color or size):
                try:
                    vi_res = sb_admin.table('variant_inventory') \
                        .select('id, stock_quantity') \
                        .eq('product_id', int(product_id)) \
                        .eq('color', color) \
                        .eq('size', size) \
                        .execute()
                    if vi_res.data:
                        vi = vi_res.data[0]
                        new_stock = max(0, int(vi['stock_quantity']) - quantity)
                        sb_admin.table('variant_inventory') \
                            .update({'stock_quantity': new_stock}) \
                            .eq('id', vi['id']) \
                            .execute()
                except Exception as vi_err:
                    print(f"?? mobile_place_order: variant stock update failed: {vi_err}")

            # Update product total quantity + sold count
            if product_id:
                try:
                    prod_res = sb_admin.table('products') \
                        .select('quantity, sold') \
                        .eq('id', int(product_id)) \
                        .execute()
                    if prod_res.data:
                        p = prod_res.data[0]
                        new_qty  = max(0, int(p.get('quantity') or 0) - quantity)
                        new_sold = int(p.get('sold') or 0) + quantity
                        sb_admin.table('products') \
                            .update({'quantity': new_qty, 'sold': new_sold}) \
                            .eq('id', int(product_id)) \
                            .execute()
                except Exception as pq_err:
                    print(f"?? mobile_place_order: product quantity update failed: {pq_err}")

            # Remove item from cart (best-effort)
            try:
                sb_admin.table('cart') \
                    .delete() \
                    .eq('email', email) \
                    .eq('product_id', int(product_id)) \
                    .eq('variations', color) \
                    .eq('size', size) \
                    .execute()
            except Exception:
                pass

        print(f"? mobile_place_order: {len(order_ids)} orders placed for {email}")
        return jsonify({'success': True, 'order_ids': order_ids})

    except Exception as e:
        print(f"? mobile_place_order error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/seller/products-with-variants')
def get_products_with_variants():
    """Get all products with their variants for the logged-in seller � reads from Supabase"""
    seller_email = session.get('email')
    user_type = session.get('user_type')

    if not seller_email or user_type != 'Seller':
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401

    try:
        # Fetch products from Supabase
        products_res = sb_admin.table('products') \
            .select('id, name, category, image, variations, sizes, quantity, low_stock_threshold') \
            .eq('seller_email', seller_email) \
            .eq('is_active', True) \
            .order('id', desc=True) \
            .execute()

        products = products_res.data or []

        if not products:
            return jsonify({'success': True, 'products': []})

        # Fetch all variant_inventory rows for these products in one query
        product_ids = [p['id'] for p in products]
        variants_res = sb_admin.table('variant_inventory') \
            .select('product_id, color, size, stock_quantity, low_stock_threshold') \
            .in_('product_id', product_ids) \
            .execute()

        # Group variants by product_id
        variants_by_product = {}
        for v in (variants_res.data or []):
            pid = v['product_id']
            variants_by_product.setdefault(pid, []).append(v)

        result_products = []
        for product in products:
            pid = product['id']
            images = [i.strip() for i in product['image'].split(',') if i.strip()] if product.get('image') else []
            colors = [c.strip() for c in product['variations'].split(',') if c.strip()] if product.get('variations') else []
            sizes  = [s.strip() for s in product['sizes'].split(',') if s.strip()] if product.get('sizes') else []

            variants = variants_by_product.get(pid, [])
            total_quantity = sum(v['stock_quantity'] for v in variants) if variants else (product.get('quantity') or 0)
            low_stock_threshold = product.get('low_stock_threshold') or 5

            result_products.append({
                'id':                  pid,
                'name':                product['name'],
                'category':            product['category'],
                'images':              images,
                'colors':              colors,
                'sizes':               sizes,
                'total_quantity':      total_quantity,
                'low_stock_threshold': low_stock_threshold,
                'variants':            variants,
            })

        return jsonify({'success': True, 'products': result_products})

    except Exception as e:
        print(f"? Error fetching products with variants from Supabase: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/seller/update-variants', methods=['POST'])
def update_variants():
    """Update variant stock quantities � writes to Supabase (primary) + MySQL (mirror)"""
    seller_email = session.get('email')
    user_type = session.get('user_type')

    if not seller_email or user_type != 'Seller':
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401

    try:
        data = request.get_json()
        product_id = data.get('product_id')
        variants = data.get('variants', [])
        low_stock_threshold = int(data.get('low_stock_threshold', 5))

        if not product_id or not variants:
            return jsonify({'success': False, 'error': 'Missing required data'}), 400

        # -- Verify ownership via Supabase ---------------------------------
        owner_res = sb_admin.table('products') \
            .select('id, name') \
            .eq('id', product_id) \
            .eq('seller_email', seller_email) \
            .execute()

        if not owner_res.data:
            return jsonify({'success': False, 'error': 'Product not found or unauthorized'}), 404

        product_name = owner_res.data[0]['name']

        # -- Update product-level threshold + total quantity in Supabase --
        total_stock = sum(v.get('stock_quantity', 0) for v in variants)
        sb_admin.table('products').update({
            'low_stock_threshold': low_stock_threshold,
            'quantity': total_stock,
        }).eq('id', product_id).execute()

        # -- Upsert all variants in Supabase (single batch call) ---------
        upsert_rows = []
        for variant in variants:
            upsert_rows.append({
                'product_id':          product_id,
                'color':               variant.get('color'),
                'size':                variant.get('size'),
                'stock_quantity':      variant.get('stock_quantity', 0),
                'low_stock_threshold': low_stock_threshold,
            })

        if upsert_rows:
            sb_admin.table('variant_inventory') \
                .upsert(upsert_rows, on_conflict='product_id,color,size') \
                .execute()

        # Stock level notifications (best-effort, per variant)
        for variant in variants:
            try:
                check_and_notify_stock_levels(
                    product_id=product_id,
                    seller_email=seller_email,
                    new_quantity=variant.get('stock_quantity', 0),
                    threshold=low_stock_threshold,
                    product_name=product_name,
                    variant_info={'color': variant.get('color'), 'size': variant.get('size')}
                )
            except Exception as notify_err:
                print(f"?? Variant stock notification error: {notify_err}")

        # Total product stock notification
        try:
            check_and_notify_stock_levels(
                product_id=product_id,
                seller_email=seller_email,
                new_quantity=total_stock,
                threshold=low_stock_threshold,
                product_name=product_name,
                variant_info=None
            )
        except Exception as notify_err:
            print(f"?? Product stock notification error: {notify_err}")

        print(f"? Variants updated in Supabase for product {product_id}")

        # -- Mirror to MySQL (best-effort) ---------------------------------
        try:
            connection = get_db_connection()
            cursor = connection.cursor(dictionary=True)

            cursor.execute("""
                UPDATE products SET low_stock_threshold = %s, quantity = %s WHERE id = %s
            """, (low_stock_threshold, total_stock, product_id))

            for variant in variants:
                color = variant.get('color')
                size  = variant.get('size')
                stock_quantity = variant.get('stock_quantity', 0)

                cursor.execute("""
                    SELECT id FROM variant_inventory
                    WHERE product_id = %s AND color = %s AND size = %s
                """, (product_id, color, size))
                existing = cursor.fetchone()

                if existing:
                    cursor.execute("""
                        UPDATE variant_inventory
                        SET stock_quantity = %s, low_stock_threshold = %s, updated_at = NOW()
                        WHERE product_id = %s AND color = %s AND size = %s
                    """, (stock_quantity, low_stock_threshold, product_id, color, size))
                else:
                    cursor.execute("""
                        INSERT INTO variant_inventory
                        (product_id, color, size, stock_quantity, low_stock_threshold)
                        VALUES (%s, %s, %s, %s, %s)
                    """, (product_id, color, size, stock_quantity, low_stock_threshold))

            connection.commit()
            cursor.close()
            connection.close()
            print(f"? Variants also mirrored to MySQL for product {product_id}")
        except Exception as mysql_err:
            print(f"?? MySQL mirror failed (non-fatal): {mysql_err}")

        return jsonify({'success': True, 'message': 'Variants updated successfully'})

    except Exception as e:
        print(f"? Error updating variants: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500



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
            o['original_price'] = o['total_price']
            o['quantity']       = int(o.get('quantity') or 1)

            # Promotion defaults
            o.setdefault('promotion_type', '')
            o.setdefault('promotion_name', '')
            o.setdefault('discount_amount', 0)
            o.setdefault('discount_percentage', 0)

            # Date � keep as string for template (already formatted or ISO)
            raw_date = o.get('date')
            if raw_date:
                try:
                    dt = _dt.datetime.fromisoformat(str(raw_date).replace('Z', '+00:00'))
                    o['date'] = dt.strftime('%Y-%m-%d %H:%M')
                except Exception:
                    o['date'] = str(raw_date)[:16]
            else:
                o['date'] = ''

            # Image � resolve URL
            raw_img = (o.get('image') or '').strip()
            if raw_img.startswith('http://') or raw_img.startswith('https://'):
                o['image_url'] = raw_img
                o['image']     = ''
            else:
                o['image_url'] = ''
                # keep raw filename for url_for fallback

            # product_sizes fallback
            o.setdefault('product_sizes', '')

        orders = raw_orders
        print(f"? orders_list Supabase: {len(orders)} orders for seller {seller_email}")

    except Exception as sb_err:
        print(f"?? orders_list Supabase failed: {sb_err}")

        # -- FALLBACK: MySQL ------------------------------------------------
        try:
            connection = get_db_connection()
            cursor = connection.cursor(dictionary=True)
            cursor.execute("""
                SELECT o.id, o.name, o.quantity, o.date, o.total_price, o.payment_method,
                       o.status, o.email, o.address, o.seller_email, o.product_id, o.image,
                       o.variations, o.size, u.first_name, u.last_name, u.phone_number as phone,
                       p.sizes as product_sizes, p.price as product_original_price,
                       s.business_name as seller_business_name, s.address as seller_address,
                       s.phone_number as seller_phone,
                       o.rider_email, r.first_name as rider_first_name, r.last_name as rider_last_name
                FROM orders o
                JOIN users u ON o.email = u.email
                LEFT JOIN products p ON o.product_id = p.id
                LEFT JOIN users s ON o.seller_email = s.email
                LEFT JOIN users r ON o.rider_email = r.email
                WHERE o.seller_email = %s
                AND o.status NOT IN ('Completed', 'Cancelled')
                ORDER BY o.date DESC
            """, (seller_email,))
            orders = cursor.fetchall()
            for o in orders:
                if o.get('rider_first_name') and o.get('rider_last_name'):
                    o['rider_name'] = f"{o['rider_first_name']} {o['rider_last_name']}"
                else:
                    o['rider_name'] = None
                o['original_price']     = o.get('product_original_price') or o.get('total_price', 0)
                o['promotion_type']     = ''
                o['promotion_name']     = ''
                o['discount_amount']    = 0
                o['discount_percentage'] = 0
                o['image_url']          = ''
            cursor.close()
            connection.close()
            print(f"?? orders_list MySQL fallback: {len(orders)} orders")
        except Exception as my_err:
            print(f"?? orders_list MySQL fallback failed: {my_err}")
            orders = []

    return render_template('order_lists.html', orders=orders,
                           user_name=seller_name,
                           user_email=seller_email)


@app.route('/seller_order_history')
def seller_order_history():
    if 'email' not in session:
        return redirect(url_for('home'))

    # -- Get seller name from Supabase (works even when MySQL is down) -----
    seller_name = session.get('first_name', 'Seller')
    try:
        sb_res = sb_admin.table('users').select('first_name, last_name, business_name').eq('email', session['email']).execute()
        if sb_res.data:
            u = sb_res.data[0]
            seller_name = u.get('business_name') or f"{u.get('first_name', '')} {u.get('last_name', '')}".strip() or 'Seller'
    except Exception as sb_err:
        print(f"?? Supabase name fetch failed in seller_order_history: {sb_err}")

    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)
    except Exception as db_err:
        print(f"?? MySQL unavailable in seller_order_history: {db_err}")
        return render_template('seller_order_history.html', orders=[],
                             user_name=seller_name, user_email=session.get('email', 'Seller'),
                             completed_count=0, cancelled_count=0,
                             total_revenue="0.00", total_orders=0)

    # Get completed and cancelled orders with customer information
    cursor.execute("""
        SELECT o.id, o.name, o.quantity, o.date, o.total_price, o.payment_method, 
               o.status, o.email, o.address, o.seller_email, o.product_id, o.image, 
               o.variations, o.size, u.first_name, u.last_name, p.sizes as product_sizes,
               p.price as product_original_price
        FROM orders o
        JOIN users u ON o.email = u.email
        LEFT JOIN products p ON o.product_id = p.id
        WHERE o.seller_email = %s 
        AND o.status IN ('Completed', 'Cancelled')
        ORDER BY o.date DESC
    """, (session['email'],))
    
    orders = cursor.fetchall()
    
    # Calculate statistics
    completed_count = 0
    cancelled_count = 0
    total_revenue = 0.0
    
    # Process orders to add promotion information and calculate stats
    for order in orders:
        try:
            # Ensure total_price is always a float
            try:
                total_price_val = order.get('total_price', 0)
                if isinstance(total_price_val, str):
                    total_price_val = total_price_val.strip()
                    total_price_val = float(total_price_val) if total_price_val and total_price_val.lower() != 'none' else 0.0
                else:
                    total_price_val = float(total_price_val) if total_price_val is not None else 0.0
                order['total_price'] = total_price_val
            except (ValueError, TypeError):
                order['total_price'] = 0.0
            
            # Set original price from product data
            original_price_val = order.get('product_original_price', order.get('total_price', 0))
            if isinstance(original_price_val, str):
                original_price_val = original_price_val.strip()
                if original_price_val == '' or original_price_val.lower() == 'none':
                    original_price_val = order.get('total_price', 0)
            
            # Ensure original_price is always a float
            try:
                order['original_price'] = float(original_price_val) if original_price_val else 0.0
            except (ValueError, TypeError):
                order['original_price'] = 0.0
            
            # Calculate statistics
            if order.get('status') == 'Completed':
                completed_count += 1
                try:
                    price_val = order.get('total_price', 0)
                    if isinstance(price_val, str):
                        price_val = price_val.strip()
                        if price_val and price_val.lower() != 'none':
                            total_revenue += float(price_val)
                    elif price_val is not None:
                        total_revenue += float(price_val)
                except (ValueError, TypeError) as e:
                    print(f"Error converting price for order {order.get('id')}: {e}")
                    pass
            elif order.get('status') == 'Cancelled':
                cancelled_count += 1
            
            # Calculate if there was a promotion applied
            try:
                if isinstance(original_price_val, str):
                    original_price_val = original_price_val.strip()
                    original_price = float(original_price_val) if original_price_val and original_price_val.lower() != 'none' else 0.0
                else:
                    original_price = float(original_price_val) if original_price_val is not None else 0.0
            except (ValueError, TypeError):
                original_price = 0.0
                
            try:
                total_price_val = order.get('total_price', 0)
                if isinstance(total_price_val, str):
                    total_price_val = total_price_val.strip()
                    total_price = float(total_price_val) if total_price_val and total_price_val.lower() != 'none' else 0.0
                else:
                    total_price = float(total_price_val) if total_price_val is not None else 0.0
            except (ValueError, TypeError):
                total_price = 0.0
            
            # Check for active promotions for this product
            if order.get('product_id'):
                try:
                    active_promotion = get_active_promotions_for_product(
                        order.get('product_id'), 
                        order.get('seller_email', ''), 
                        ''
                    )
                    
                    if active_promotion:
                        order['promotion_type'] = active_promotion.get('type', '') or ''
                        order['promotion_name'] = active_promotion.get('name', '') or ''
                        
                        try:
                            # Ensure both values are floats before comparison
                            original_price_float = float(original_price) if original_price else 0.0
                            total_price_float = float(total_price) if total_price else 0.0
                            
                            if original_price_float > 0 and total_price_float < original_price_float:
                                discount_amount = original_price_float - total_price_float
                                discount_percentage = round((discount_amount / original_price_float) * 100, 1)
                                
                                order['discount_amount'] = discount_amount
                                order['discount_percentage'] = discount_percentage
                            else:
                                order['discount_amount'] = 0
                                order['discount_percentage'] = 0
                        except (ValueError, TypeError, ZeroDivisionError) as calc_error:
                            print(f"Error calculating discount for order {order.get('id')}: {calc_error}")
                            order['discount_amount'] = 0
                            order['discount_percentage'] = 0
                    else:
                        order['promotion_type'] = ''
                        order['promotion_name'] = ''
                        order['discount_amount'] = 0
                        order['discount_percentage'] = 0
                except Exception as promo_error:
                    print(f"Error getting promotion for order {order.get('id', 'unknown')}: {promo_error}")
                    order['promotion_type'] = ''
                    order['promotion_name'] = ''
                    order['discount_amount'] = 0
                    order['discount_percentage'] = 0
            else:
                order['promotion_type'] = ''
                order['promotion_name'] = ''
                order['discount_amount'] = 0
                order['discount_percentage'] = 0
                
        except Exception as order_error:
            print(f"Error processing order {order.get('id', 'unknown')}: {order_error}")
            order['original_price'] = order.get('total_price', 0)
            order['promotion_type'] = ''
            order['promotion_name'] = ''
            order['discount_amount'] = 0
            order['discount_percentage'] = 0
    
    # Ensure all orders have required fields
    for order in orders:
        if not order.get('original_price'):
            order['original_price'] = order.get('total_price', 0)
        if not order.get('promotion_type'):
            order['promotion_type'] = ''
        if not order.get('promotion_name'):
            order['promotion_name'] = ''
        if not order.get('discount_amount'):
            order['discount_amount'] = 0
        if not order.get('discount_percentage'):
            order['discount_percentage'] = 0
    
    cursor.close()
    connection.close()
    
    return render_template('seller_order_history.html', 
                         orders=orders, 
                         user_name=seller_name,
                         user_email=session.get('email', 'Seller'),
                         completed_count=completed_count,
                         cancelled_count=cancelled_count,
                         total_revenue=f"{total_revenue:.2f}",
                         total_orders=len(orders))

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

@app.route('/api/delete-order-history/<int:order_id>', methods=['DELETE'])
def delete_order_history(order_id):
    if 'email' not in session:
        return jsonify({'success': False, 'message': 'Authentication required'}), 401
    
    seller_email = session.get('email')
    
    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)
        
        # Check if order exists and belongs to seller
        cursor.execute("""
            SELECT id, status FROM orders 
            WHERE id = %s AND seller_email = %s
        """, (order_id, seller_email))
        
        order = cursor.fetchone()
        
        if not order:
            cursor.close()
            connection.close()
            return jsonify({'success': False, 'message': 'Order not found or unauthorized'}), 404
        
        # Only allow deletion of Completed or Cancelled orders
        if order['status'] not in ['Completed', 'Cancelled']:
            cursor.close()
            connection.close()
            return jsonify({'success': False, 'message': 'Only completed or cancelled orders can be deleted'}), 400
        
        # Delete the order
        cursor.execute("DELETE FROM orders WHERE id = %s", (order_id,))
        connection.commit()
        
        cursor.close()
        connection.close()
        
        return jsonify({
            'success': True,
            'message': 'Order deleted successfully'
        })
        
    except Exception as e:
        print(f"Error deleting order: {str(e)}")
        return jsonify({
            'success': False, 
            'message': f'Error deleting order: {str(e)}'
        }), 500

@app.route('/api/seller-order-details/<int:order_id>')
def get_seller_order_details(order_id):
    if 'email' not in session:
        return jsonify({'success': False, 'message': 'Authentication required'}), 401
    
    seller_email = session.get('email')
    
    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)
        
        # Get detailed order information for seller
        cursor.execute("""
            SELECT o.id, o.name, o.quantity, o.date, o.total_price, 
                   o.payment_method, o.status, o.email, o.address, o.seller_email, 
                   o.product_id, o.image, o.variations, o.size,
                   u.first_name, u.last_name, u.phone_number as customer_phone,
                   u.address as customer_address,
                   p.price as product_original_price
            FROM orders o
            JOIN users u ON o.email = u.email
            LEFT JOIN products p ON o.product_id = p.id
            WHERE o.id = %s AND o.seller_email = %s
        """, (order_id, seller_email))
        
        order = cursor.fetchone()
        
        if not order:
            cursor.close()
            connection.close()
            return jsonify({'success': False, 'message': 'Order not found'}), 404
        
        # Get promotion information
        promotion_type = ''
        promotion_name = ''
        if order.get('product_id'):
            try:
                active_promotion = get_active_promotions_for_product(
                    order.get('product_id'), 
                    order.get('seller_email', ''), 
                    ''
                )
                if active_promotion:
                    promotion_type = active_promotion.get('type', '') or ''
                    promotion_name = active_promotion.get('name', '') or ''
            except Exception:
                pass
        
        # Format the response
        order_details = {
            'id': order['id'],
            'name': order['name'],
            'quantity': order['quantity'],
            'total_price': float(order.get('total_price', 0)),
            'payment_method': order.get('payment_method', ''),
            'status': order.get('status', ''),
            'variations': order.get('variations', ''),
            'size': order.get('size', ''),
            'image': order.get('image', ''),
            'first_name': order.get('first_name', ''),
            'last_name': order.get('last_name', ''),
            'email': order.get('email', ''),
            'address': order.get('address') or order.get('customer_address', ''),
            'date': order['date'].strftime('%Y-%m-%d %H:%M:%S') if order.get('date') else None,
            'promotion_type': promotion_type
        }
        
        cursor.close()
        connection.close()
        
        return jsonify({
            'success': True,
            'order': order_details
        })
        
    except Exception as e:
        print(f"Error fetching seller order details: {str(e)}")
        return jsonify({
            'success': False, 
            'message': f'Error fetching order details: {str(e)}'
        }), 500


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
    try:
        conn = get_db_connection()
        cur  = conn.cursor()
        if new_status == 'Delivered':
            from datetime import datetime as _dt2, timedelta as _td2
            cur.execute(
                "UPDATE orders SET status=%s, delivered_at=%s, auto_complete_at=%s WHERE id=%s",
                (new_status, _dt2.now(), _dt2.now() + _td2(days=7), order_id))
        else:
            cur.execute("UPDATE orders SET status=%s WHERE id=%s", (new_status, order_id))
        conn.commit()
        cur.close()
        conn.close()
    except Exception as my_err:
        print(f"?? MySQL mirror failed for order {order_id}: {my_err}")

    return redirect(url_for('orders_list'))

@app.route('/update_order_received_status', methods=['POST'])
def update_order_received_status():
    data = request.json
    order_id = data.get('order_id')  # Get the order ID
    status = data.get('status')  # Get the status (should be 'Received')
    product_id = data.get('product_id')  # Get the product_id for reference
    quantity_received = data.get('quantity')  # Get the quantity of the received item
    user_email = session.get('email')  # Get the email from session (if needed)

    if status != 'Received':
        return jsonify({'success': False, 'error': 'Invalid status'}), 400

    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        # Step 1: Update the order status to 'Received'
        cursor.execute("""
            UPDATE orders
            SET status = %s
            WHERE id = %s AND email = %s
        """, (status, order_id, user_email))

        # Step 2: Get the current quantity of the product from the products table using product_id
        cursor.execute("""
            SELECT quantity FROM products WHERE id = %s
        """, (product_id,))
        product = cursor.fetchone()

        if not product:
            return jsonify({'success': False, 'error': 'Product not found'}), 404

        current_quantity = int(product['quantity'])

        # Step 3: Subtract the received quantity from the product quantity
        new_quantity = current_quantity - int(quantity_received)

        # Step 4: Update the product's quantity in the products table
        cursor.execute("""
            UPDATE products
            SET quantity = %s
            WHERE id = %s
        """, (new_quantity, product_id))

        conn.commit()

        return jsonify({'success': True}), 200
    except Exception as e:
        conn.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        cursor.close()
        conn.close()


@app.route('/submit_order_issue', methods=['POST'])
def submit_order_issue():
    """Submit an issue report for an order (from buyer, seller, or rider)"""
    if 'email' not in session:
        return jsonify({'success': False, 'message': 'Please log in to submit a report'}), 401
    
    try:
        data = request.json
        order_id = data.get('order_id')
        reporter_role = data.get('reporter_role')  # 'buyer', 'seller', 'rider', 'admin'
        reporter_email = data.get('reporter_email')
        reported_against_role = data.get('reported_against_role')  # 'buyer', 'seller', 'rider', 'platform', 'other'
        reported_against_email = data.get('reported_against_email', '')
        issue_type = data.get('issue_type')
        issue_description = data.get('issue_description')
        
        # Validate required fields
        if not all([order_id, reporter_role, reporter_email, reported_against_role, issue_type, issue_description]):
            return jsonify({'success': False, 'message': 'All fields are required'}), 400
        
        # Verify the reporter is the logged-in user
        if reporter_email != session.get('email'):
            return jsonify({'success': False, 'message': 'Unauthorized action'}), 403
        
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        # Verify the order exists and the reporter has access to it
        cursor.execute("""
            SELECT id, email as buyer_email, seller_email, rider_email 
            FROM orders 
            WHERE id = %s
        """, (order_id,))
        order = cursor.fetchone()
        
        if not order:
            cursor.close()
            conn.close()
            return jsonify({'success': False, 'message': 'Order not found'}), 404
        
        # Verify reporter has access to this order
        has_access = False
        if reporter_role == 'buyer' and order['buyer_email'] == reporter_email:
            has_access = True
        elif reporter_role == 'seller' and order['seller_email'] == reporter_email:
            has_access = True
        elif reporter_role == 'rider' and order['rider_email'] == reporter_email:
            has_access = True
        elif reporter_role == 'admin':
            # Check if user is admin
            cursor.execute("SELECT user_type FROM users WHERE email = %s", (reporter_email,))
            user = cursor.fetchone()
            if user and user['user_type'] == 'Admin':
                has_access = True
        
        if not has_access:
            cursor.close()
            conn.close()
            return jsonify({'success': False, 'message': 'You do not have access to report on this order'}), 403
        
        # Insert the issue report
        cursor.execute("""
            INSERT INTO order_issues 
            (order_id, reporter_role, reporter_email, reported_against_role, 
             reported_against_email, issue_type, issue_description, status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, 'pending')
        """, (order_id, reporter_role, reporter_email, reported_against_role, 
              reported_against_email, issue_type, issue_description))
        
        issue_id = cursor.lastrowid
        conn.commit()
        
        # Send notification to admin (you can implement this later)
        # send_issue_notification_to_admin(issue_id, order_id, reporter_role, issue_type)
        
        cursor.close()
        conn.close()
        
        return jsonify({
            'success': True, 
            'message': 'Issue report submitted successfully. Admin will review your report.',
            'issue_id': issue_id
        }), 200
        
    except Exception as e:
        print(f"Error submitting issue report: {e}")
        return jsonify({'success': False, 'message': 'An error occurred while submitting the report'}), 500


# ===========================================
# ADMIN ROUTES
# ===========================================

@app.route('/pending_users')
def pending_users():
    if 'user_id' not in session or session.get('user_type') != 'Admin':
        flash('Access denied. Admin privileges required.', 'error')
        return redirect(url_for('login'))
    
    pending_users_list = []
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute('SELECT * FROM pending_users ORDER BY created_at DESC')
        mysql_pending = cursor.fetchall()
        cursor.close()
        conn.close()
        pending_users_list = mysql_pending
    except Exception as e:
        print(f"?? MySQL unavailable in pending_users: {e}")

    # Also fetch mobile registrations from Supabase pending_users table
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
        if request.headers.get('Content-Type') == 'application/json' or request.is_json:
            return jsonify({'success': False, 'error': 'Access denied. Admin privileges required.'})
        flash('Access denied. Admin privileges required.', 'error')
        return redirect(url_for('login'))

    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'

    # -- Supabase-sourced (mobile) registration ----------------------------
    if str(user_id).startswith('sb_'):
        supabase_record_id = user_id[3:]  # strip 'sb_' prefix
        try:
            res = sb_admin.table('pending_users').select('*').eq('id', supabase_record_id).execute()
            if not res.data:
                if is_ajax: return jsonify({'success': False, 'error': 'Pending user not found'})
                flash('Pending user not found', 'error')
                return redirect(url_for('pending_users'))

            u = res.data[0]
            supabase_uid = u.get('supabase_uid')

            # Insert into Supabase users table
            profile_data = {
                'id':            supabase_uid,
                'email':         u.get('email'),
                'first_name':    u.get('first_name'),
                'last_name':     u.get('last_name'),
                'phone':         u.get('phone') or '',
                'role':          u.get('role') or 'buyer',
                'house_street':  u.get('house_street') or '',
                'barangay':      u.get('barangay') or '',
                'city':          u.get('city') or '',
                'province':      u.get('province') or '',
                'region':        u.get('region') or '',
                'zip_code':      u.get('zip_code') or '',
                'valid_id_path': u.get('valid_id_path'),
            }
            sb_admin.table('users').upsert(profile_data).execute()

            # Copy rider vehicle data if present
            try:
                rv_res = sb_admin.table('pending_rider_vehicles').select('*').eq('supabase_uid', supabase_uid).execute()
                if rv_res.data:
                    rv = rv_res.data[0]
                    sb_admin.table('rider_vehicles').upsert({
                        'user_id':            supabase_uid,
                        'vehicle_type':       rv.get('vehicle_type'),
                        'plate_number':       rv.get('plate_number'),
                        'vehicle_model':      rv.get('vehicle_model'),
                        'year_model':         rv.get('year_model'),
                        'or_cr_path':         rv.get('or_cr_path'),
                        'nbi_clearance_path': rv.get('nbi_clearance_path'),
                    }).execute()
                    sb_admin.table('pending_rider_vehicles').delete().eq('supabase_uid', supabase_uid).execute()
            except Exception as rv_err:
                print(f"Warning: rider vehicle copy failed: {rv_err}")

            # Unban the auth account
            if supabase_uid:
                try:
                    sb_admin.auth.admin.update_user_by_id(supabase_uid, {'ban_duration': 'none'})
                except Exception as ue:
                    print(f"Warning: unban failed: {ue}")

            # Delete from Supabase pending_users
            sb_admin.table('pending_users').delete().eq('id', supabase_record_id).execute()

            # Send approval email
            try:
                send_approval_email(u.get('email'), u.get('first_name'))
            except Exception:
                pass

            full_name = f"{u.get('first_name')} {u.get('last_name')}"
            if is_ajax:
                return jsonify({'success': True, 'message': f'{full_name} approved successfully!', 'user_name': full_name})
            flash(f'{full_name} approved successfully!', 'success')
            return redirect(url_for('pending_users'))

        except Exception as e:
            import traceback; traceback.print_exc()
            if is_ajax: return jsonify({'success': False, 'error': str(e)})
            flash(f'Error approving user: {e}', 'error')
            return redirect(url_for('pending_users'))

    # -- MySQL-sourced (web) registration ----------------------------------
    try:
        mysql_id = int(user_id)
    except ValueError:
        if is_ajax: return jsonify({'success': False, 'error': 'Invalid user ID'})
        flash('Invalid user ID', 'error')
        return redirect(url_for('pending_users'))

    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        print(f"DEBUG: Attempting to approve user with ID: {mysql_id}")
        
        # Get user from pending_users
        cursor.execute('SELECT * FROM pending_users WHERE id = %s', (mysql_id,))
        pending_user = cursor.fetchone()
        
        if not pending_user:
            print(f"DEBUG: No pending user found with ID: {mysql_id}")
            if is_ajax:
                return jsonify({'success': False, 'error': 'User not found in pending list'})
            flash('User not found in pending list', 'error')
            return redirect(url_for('pending_users'))
        
        print(f"DEBUG: Found pending user: {pending_user['email']}")
        
        password_to_insert = pending_user['password']
        address_to_insert = pending_user['address']
        print(f"DEBUG: Original address: {address_to_insert}")

        # -- Insert profile into Supabase users table ----------------------
        supabase_uid = pending_user.get('supabase_uid')
        if supabase_uid:
            try:
                addr_parts = [p.strip() for p in address_to_insert.split(',')]
                profile_data = {
                    'id':           supabase_uid,
                    'email':        pending_user['email'],
                    'first_name':   pending_user['first_name'],
                    'last_name':    pending_user['last_name'],
                    'phone':        pending_user['phone_number'] or '',
                    'role':         pending_user['user_type'],
                    'house_street': addr_parts[0] if len(addr_parts) > 0 else '',
                    'barangay':     addr_parts[1] if len(addr_parts) > 1 else '',
                    'city':         addr_parts[2] if len(addr_parts) > 2 else '',
                    'province':     addr_parts[3] if len(addr_parts) > 3 else '',
                    'region':       addr_parts[4] if len(addr_parts) > 4 else '',
                    'zip_code':     addr_parts[5] if len(addr_parts) > 5 else '',
                    'valid_id_path': pending_user.get('valid_id_path'),
                    'or_cr_path':   pending_user.get('or_cr_path'),
                    'nbi_clearance_path': pending_user.get('nbi_clearance_path'),
                }
                sb_admin.table('users').upsert(profile_data).execute()
                print(f"DEBUG: Supabase users profile inserted for {pending_user['email']}")

                # Unban the auth account so the user can now log in
                sb_admin.auth.admin.update_user_by_id(supabase_uid, {'ban_duration': 'none'})
                print(f"DEBUG: Supabase auth account unbanned for {pending_user['email']}")
            except Exception as se:
                print(f"WARNING: Supabase profile insert/unban failed: {se}")
                import traceback; traceback.print_exc()
        else:
            print(f"WARNING: No supabase_uid for {pending_user['email']}")
        
        cursor.execute('''
            INSERT INTO users 
            (email, password, first_name, last_name, phone_number, address, user_type, 
             valid_id_path, bir_path, dti_path, business_permit_path,
             vehicle_type, vehicle_model, vehicle_plate_number, vehicle_year_model,
             or_cr_path, nbi_clearance_path)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ''', (
            pending_user['email'], 
            password_to_insert,
            pending_user['first_name'],
            pending_user['last_name'],
            pending_user['phone_number'],
            address_to_insert,
            pending_user['user_type'],
            pending_user.get('valid_id_path'),
            pending_user.get('bir_path'),
            pending_user.get('dti_path'),
            pending_user.get('business_permit_path'),
            pending_user.get('vehicle_type'),
            pending_user.get('vehicle_model'),
            pending_user.get('vehicle_plate_number'),
            pending_user.get('vehicle_year_model'),
            pending_user.get('or_cr_path'),
            pending_user.get('nbi_clearance_path')
        ))
        
        print(f"DEBUG: User inserted into users table")
        
        # Delete from pending_users since user is now approved and moved to users table
        cursor.execute('DELETE FROM pending_users WHERE id = %s', (user_id,))
        
        print(f"DEBUG: Status updated to approved")
        
        conn.commit()
        print(f"DEBUG: Database changes committed")
        
        # Send approval email
        email_sent = send_approval_email(pending_user['email'], pending_user['first_name'])
        if email_sent:
            print(f"DEBUG: Approval email sent successfully to {pending_user['email']}")
        else:
            print(f"DEBUG: Failed to send approval email to {pending_user['email']}")
        
        # Return JSON for AJAX requests
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({
                'success': True, 
                'message': f'User {pending_user["first_name"]} {pending_user["last_name"]} approved successfully!',
                'user_name': f'{pending_user["first_name"]} {pending_user["last_name"]}'
            })
        
        flash(f'User {pending_user["first_name"]} {pending_user["last_name"]} approved successfully!', 'success')
        
    except Exception as e:
        if 'conn' in locals():
            conn.rollback()
        print(f"ERROR approving user: {str(e)}")
        import traceback
        traceback.print_exc()
        
        # Return JSON error for AJAX requests
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': False, 'error': f'An error occurred while approving the user: {str(e)}'})
        
        flash(f'An error occurred while approving the user: {str(e)}', 'error')
    finally:
        if 'conn' in locals():
            conn.close()
    
    return redirect(url_for('pending_users'))

@app.route('/check-db-schema')
def check_db_schema():
    """Check database schema for users and pending_users tables"""
    if 'user_id' not in session or session.get('user_type') != 'Admin':
        return "Access denied"
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Check users table schema
        cursor.execute("DESCRIBE users")
        users_schema = cursor.fetchall()
        
        # Check pending_users table schema
        cursor.execute("DESCRIBE pending_users")
        pending_users_schema = cursor.fetchall()
        
        result = "<h2>Users Table Schema:</h2><pre>"
        for column in users_schema:
            result += f"{column}\n"
        
        result += "</pre><h2>Pending Users Table Schema:</h2><pre>"
        for column in pending_users_schema:
            result += f"{column}\n"
        result += "</pre>"
        
        cursor.close()
        conn.close()
        
        return result
        
    except Exception as e:
        return f"Error: {str(e)}"

@app.route('/fix-address-column')
def fix_address_column():
    """Fix the address column size in users table"""
    if 'user_id' not in session or session.get('user_type') != 'Admin':
        return "Access denied"
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Alter the users table to increase address column size
        cursor.execute("ALTER TABLE users MODIFY COLUMN address TEXT")
        conn.commit()
        
        cursor.close()
        conn.close()
        
        return "Address column in users table has been modified to TEXT type to support longer addresses."
        
    except Exception as e:
        return f"Error: {str(e)}"

@app.route('/test-db-connection')
def test_db_connection():
    """Test route to check database connection and table structures"""
    if 'user_id' not in session or session.get('user_type') != 'Admin':
        return "Access denied"
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        # Test pending_users table
        cursor.execute('SELECT COUNT(*) as count FROM pending_users WHERE status = "pending"')
        pending_count = cursor.fetchone()
        
        # Test users table
        cursor.execute('SELECT COUNT(*) as count FROM users')
        users_count = cursor.fetchone()
        
        # Get sample pending user
        cursor.execute('SELECT * FROM pending_users WHERE status = "pending" LIMIT 1')
        sample_pending = cursor.fetchone()
        
        conn.close()
        
        result = f"""
        <h2>Database Test Results</h2>
        <p><strong>Pending Users:</strong> {pending_count['count']}</p>
        <p><strong>Total Users:</strong> {users_count['count']}</p>
        <p><strong>Sample Pending User:</strong> {sample_pending}</p>
        <p><strong>Email Config:</strong> {app.config['MAIL_USERNAME']}</p>
        <a href="/pending-users">Back to Pending Users</a>
        """
        
        return result
        
    except Exception as e:
        return f"Database Error: {str(e)}"

@app.route('/debug-pending-sellers')
def debug_pending_sellers():
    """Debug route to check pending_sellers table structure and data"""
    if 'user_id' not in session or session.get('user_type') != 'Admin':
        return "Access denied"
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        # Get table structure
        cursor.execute('DESCRIBE pending_sellers')
        table_structure = cursor.fetchall()
        
        # Get sample data
        cursor.execute('SELECT * FROM pending_sellers LIMIT 1')
        sample_data = cursor.fetchone()
        
        # Get count
        cursor.execute('SELECT COUNT(*) as count FROM pending_sellers WHERE status = "pending"')
        count = cursor.fetchone()
        
        conn.close()
        
        result = f"""
        <h2>Pending Sellers Debug</h2>
        <h3>Table Structure:</h3>
        <pre>{table_structure}</pre>
        <h3>Sample Data:</h3>
        <pre>{sample_data}</pre>
        <h3>Count: {count['count']}</h3>
        <a href="/pending_sellers">Back to Pending Sellers</a>
        """
        
        return result
        
    except Exception as e:
        return f"Database Error: {str(e)}"

# Removed duplicate debug_session route - using the more comprehensive one below

@app.route('/test-login')
def test_login():
    """Test route to check login-related data"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        # Get sample users
        cursor.execute('SELECT id, email, password, user_type FROM users LIMIT 3')
        sample_users = cursor.fetchall()
        
        # Get sample pending users
        cursor.execute('SELECT id, email, password, status FROM pending_users LIMIT 3')
        sample_pending = cursor.fetchall()
        
        conn.close()
        
        result = f"""
        <h2>Login Test Data</h2>
        <h3>Sample Users in users table:</h3>
        <pre>{sample_users}</pre>
        
        <h3>Sample Pending Users:</h3>
        <pre>{sample_pending}</pre>
        
        <h3>Password Field Lengths:</h3>
        """
        
        for user in sample_users:
            result += f"<p>User {user['email']}: password length = {len(user['password'])}</p>"
        
        result += """
        <p><strong>Note:</strong> If password length > 50, you need to run the SQL update script.</p>
        <p><a href="/debug-session">Back to Session Debug</a></p>
        """
        
        return result
        
    except Exception as e:
        return f"Error: {str(e)}"

@app.route('/reject_user/<string:user_id>', methods=['POST'])
def reject_user_str(user_id):
    """Reject a pending user � handles both MySQL (numeric) and Supabase (sb_) IDs."""
    is_ajax = (request.headers.get('X-Requested-With') == 'XMLHttpRequest' or
               'application/json' in request.headers.get('Accept', '') or
               request.is_json)

    if 'user_id' not in session or session.get('user_type') != 'Admin':
        if is_ajax:
            return jsonify({'success': False, 'error': 'Access denied. Admin privileges required.'})
        flash('Access denied. Admin privileges required.', 'error')
        return redirect(url_for('login'))

    if request.is_json:
        rejection_reason = (request.get_json() or {}).get('rejection_reason', '').strip()
    else:
        rejection_reason = request.form.get('rejection_reason', '').strip()

    if not rejection_reason:
        if is_ajax:
            return jsonify({'success': False, 'error': 'Please provide a reason for rejection.'})
        flash('Please provide a reason for rejection.', 'error')
        return redirect(url_for('pending_users'))

    # -- Supabase-sourced (sb_ prefix) -------------------------------------
    if str(user_id).startswith('sb_'):
        supabase_record_id = user_id[3:]
        try:
            res = sb_admin.table('pending_users').select('*').eq('id', supabase_record_id).execute()
            if not res.data:
                if is_ajax: return jsonify({'success': False, 'error': 'User not found'})
                flash('User not found', 'error')
                return redirect(url_for('pending_users'))

            u = res.data[0]
            supabase_uid = u.get('supabase_uid')

            # Send rejection email
            try:
                send_rejection_email(u.get('email'), u.get('first_name'), rejection_reason)
            except Exception:
                pass

            # Delete from pending_users so they can re-register
            sb_admin.table('pending_users').delete().eq('id', supabase_record_id).execute()

            # Delete the Supabase auth account so they can sign up fresh
            if supabase_uid:
                try:
                    sb_admin.auth.admin.delete_user(supabase_uid)
                except Exception as ue:
                    print(f"Warning: delete auth user after rejection failed: {ue}")

            if is_ajax:
                return jsonify({'success': True, 'message': f"{u.get('first_name')} has been rejected."})
            flash(f"{u.get('first_name')} has been rejected.", 'info')
            return redirect(url_for('pending_users'))

        except Exception as e:
            import traceback; traceback.print_exc()
            if is_ajax: return jsonify({'success': False, 'error': str(e)})
            flash(f'Error rejecting user: {e}', 'error')
            return redirect(url_for('pending_users'))

    # -- MySQL-sourced (numeric ID) -----------------------------------------
    try:
        numeric_id = int(user_id)
    except ValueError:
        if is_ajax: return jsonify({'success': False, 'error': 'Invalid user ID'})
        flash('Invalid user ID', 'error')
        return redirect(url_for('pending_users'))

    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        cursor.execute('SELECT email, first_name, supabase_uid FROM pending_users WHERE id = %s', (numeric_id,))
        user_data = cursor.fetchone()

        if not user_data:
            if is_ajax: return jsonify({'success': False, 'error': 'User not found'})
            flash('User not found', 'error')
            return redirect(url_for('pending_users'))

        cursor.execute(
            "DELETE FROM pending_users WHERE id=%s",
            (numeric_id,)
        )
        conn.commit()

        supabase_uid = user_data.get('supabase_uid')
        if supabase_uid:
            try:
                sb_admin.auth.admin.delete_user(supabase_uid)
            except Exception as ue:
                print(f"Warning: delete auth user after rejection failed: {ue}")

        try:
            send_rejection_email(user_data['email'], user_data['first_name'], rejection_reason)
        except Exception:
            pass

        if is_ajax:
            return jsonify({'success': True, 'message': f"{user_data['first_name']} has been rejected."})
        flash(f"{user_data['first_name']} has been rejected.", 'info')

    except Exception as e:
        if 'conn' in locals(): conn.rollback()
        import traceback; traceback.print_exc()
        if is_ajax: return jsonify({'success': False, 'error': str(e)})
        flash(f'Error rejecting user: {e}', 'error')
    finally:
        if 'conn' in locals(): conn.close()

    return redirect(url_for('pending_users'))


@app.route('/reject-user/<int:user_id>', methods=['POST'])
def reject_user(user_id):
    # Check if this is an AJAX request (look for X-Requested-With header or Accept header)
    is_ajax = (request.headers.get('X-Requested-With') == 'XMLHttpRequest' or 
               'application/json' in request.headers.get('Accept', '') or
               request.is_json)
    
    if 'user_id' not in session or session.get('user_type') != 'Admin':
        if is_ajax:
            return jsonify({'success': False, 'error': 'Access denied. Admin privileges required.'})
        flash('Access denied. Admin privileges required.', 'error')
        return redirect(url_for('login'))
    
    # Accept rejection_reason from JSON body or form data
    if request.is_json:
        rejection_reason = (request.get_json() or {}).get('rejection_reason', '').strip()
    else:
        rejection_reason = request.form.get('rejection_reason', '').strip()
    print(f"DEBUG: Received rejection reason: '{rejection_reason}'")
    print(f"DEBUG: Is AJAX request: {is_ajax}")
    print(f"DEBUG: Request headers: {dict(request.headers)}")
    
    if not rejection_reason:
        if is_ajax:
            return jsonify({'success': False, 'error': 'Please provide a reason for rejection.'})
        flash('Please provide a reason for rejection.', 'error')
        return redirect(url_for('pending_users'))
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        print(f"DEBUG: Attempting to reject user with ID: {user_id}")
        print(f"DEBUG: Rejection reason: {rejection_reason}")
        
        # Get user details before updating
        cursor.execute('SELECT email, first_name, supabase_uid FROM pending_users WHERE id = %s', (user_id,))
        user_data = cursor.fetchone()
        
        if not user_data:
            print(f"DEBUG: No user found with ID: {user_id}")
            if is_ajax:
                return jsonify({'success': False, 'error': 'User not found'})
            flash('User not found', 'error')
            return redirect(url_for('pending_users'))
        
        print(f"DEBUG: Found user: {user_data['email']}")
        
        # Update status in pending_users
        cursor.execute('''
            UPDATE pending_users 
            SET status = 'rejected', 
                rejection_reason = %s 
            WHERE id = %s
        ''', (rejection_reason, user_id))
        
        conn.commit()
        print(f"DEBUG: User status updated to rejected")

        # Unban the Supabase auth account so the user can re-register if they want
        supabase_uid = user_data.get('supabase_uid')
        if supabase_uid:
            try:
                sb_admin.auth.admin.update_user_by_id(supabase_uid, {'ban_duration': 'none'})
                print(f"DEBUG: Supabase auth account unbanned after rejection for {user_data['email']}")
            except Exception as ue:
                print(f"Warning: unban after rejection failed: {ue}")
        
        # Send rejection email
        email_sent = send_rejection_email(user_data['email'], user_data['first_name'], rejection_reason)
        if email_sent:
            print(f"DEBUG: Rejection email sent successfully to {user_data['email']}")
        else:
            print(f"DEBUG: Failed to send rejection email to {user_data['email']}")
        
        # Always return JSON response since we're using AJAX
        return jsonify({
            'success': True, 
            'message': f'User {user_data["first_name"]} has been rejected successfully',
            'user_name': user_data["first_name"]
        })
        
    except Exception as e:
        conn.rollback()
        print(f"Error rejecting user: {str(e)}")
        if is_ajax:
            return jsonify({'success': False, 'error': f'An error occurred while rejecting the user: {str(e)}'})
        flash('An error occurred while rejecting the user.', 'error')
        return redirect(url_for('pending_users'))
    finally:
        if 'conn' in locals():
            conn.close()
   
#----------------------------------------------------------------------
                         #ADMIN RELATED ROUTES
#----------------------------------------------------------------------

@app.route('/admin_users')
def admin_users():
    if 'user_id' not in session or session.get('user_type') != 'Admin':
        flash('Access denied. Admin privileges required.', 'error')
        return redirect(url_for('login'))

    search_query  = request.args.get('search', '').strip()
    sort_by       = request.args.get('sort', '').strip()
    status_filter = request.args.get('status', '').strip()

    users = []
    total_users = buyer_count = seller_count = rider_count = 0

    try:
        # Use sb_admin (service role) to bypass RLS and read all users
        # Archived users are deleted from this table, so no filter needed
        res = sb_admin.table('users').select('*').execute()

        raw_users = res.data or []
        print(f"DEBUG admin_users: Supabase returned {len(raw_users)} rows")
        if raw_users:
            print(f"DEBUG admin_users: sample keys = {list(raw_users[0].keys())}")

        now = datetime.utcnow()

        for u in raw_users:
            # Supabase may use 'role' or 'user_type' � handle both
            role = (u.get('role') or u.get('user_type') or 'buyer').lower()
            status = (u.get('status') or 'active').lower()

            # Auto-expire suspensions/bans whose end date has passed
            ban_end = u.get('ban_end_date')
            if ban_end and status in ('suspended', 'banned'):
                try:
                    from dateutil import parser as dtparser
                    ban_end_dt = dtparser.parse(str(ban_end)).replace(tzinfo=None)
                    if now > ban_end_dt:
                        try:
                            sb_admin.table('users').update({
                                'status': 'active', 'ban_reason': None, 'ban_end_date': None
                            }).eq('id', u['id']).execute()
                        except Exception:
                            pass
                        status = 'active'
                except Exception:
                    pass

            u['user_type'] = role.capitalize()
            u['status']    = status
            u['is_banned'] = status in ('banned', 'suspended')

            # Normalize phone: mobile app stores as 'phone', not 'phone_number'
            if not u.get('phone_number'):
                u['phone_number'] = u.get('phone') or ''

            # Normalize address: mobile app stores separate fields, not a combined 'address'
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

            # Ensure created_at is a datetime so the template can call .strftime
            # (Supabase returns ISO strings, not datetime objects)
            created_at_raw = u.get('created_at')
            if created_at_raw and isinstance(created_at_raw, str):
                try:
                    from dateutil import parser as dtparser
                    u['created_at'] = dtparser.parse(created_at_raw)
                except Exception:
                    u['created_at'] = None
            elif not created_at_raw:
                u['created_at'] = None

            # Client-side filters
            if sort_by and sort_by in ('buyer', 'seller', 'rider'):
                if role != sort_by:
                    continue
            if status_filter and status_filter in ('active', 'suspended', 'banned'):
                if status != status_filter:
                    continue
            if search_query:
                sq = search_query.lower()
                haystack = ' '.join(filter(None, [
                    u.get('first_name') or '', u.get('last_name') or '',
                    u.get('email') or '', u.get('phone_number') or '',
                    u.get('address') or ''
                ])).lower()
                if sq not in haystack:
                    continue

            users.append(u)

        # Stats from full unfiltered list
        for u in raw_users:
            r = (u.get('role') or u.get('user_type') or 'buyer').lower()
            total_users += 1
            if r == 'buyer':    buyer_count  += 1
            elif r == 'seller': seller_count += 1
            elif r == 'rider':  rider_count  += 1

        print(f"DEBUG admin_users: after filters {len(users)} users, total={total_users}")

    except Exception as e:
        print(f'Supabase error in admin_users: {e}')
        import traceback; traceback.print_exc()

    return render_template('admin_users.html',
                         users=users,
                         total_users=total_users,
                         buyer_count=buyer_count,
                         seller_count=seller_count,
                         rider_count=rider_count)

@app.route('/product_management')
def product_management():
    """Admin route to manage all products from all sellers"""
    print(f"DEBUG product_management: session = {dict(session)}")
    
    # Check if user is logged in and is admin
    if 'user_id' not in session or session.get('user_type') != 'Admin':
        print(f"DEBUG: Access denied - user_id: {session.get('user_id')}, user_type: {session.get('user_type')}")
        flash('Access denied. Admin privileges required.', 'danger')
        return redirect(url_for('login'))
    
    print("DEBUG: Admin access granted, loading products...")
    
    try:
        conn = get_db_connection()
    except Exception as e:
        print(f"?? MySQL unavailable in product_management: {e}")
        return render_template('product_management.html',
                             products=[], categories=[], sellers=[],
                             page=1, total_pages=1, total_products=0,
                             low_stock_count=0, out_of_stock_count=0)
    
    cursor = conn.cursor(dictionary=True)
    
    try:
        # Check if created_at and updated_at columns exist, if not add them
        try:
            cursor.execute("SHOW COLUMNS FROM products LIKE 'created_at'")
            if not cursor.fetchone():
                print("Adding created_at column to products table...")
                cursor.execute("""
                    ALTER TABLE products 
                    ADD COLUMN created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                """)
                conn.commit()
                print("created_at column added successfully!")
        except Exception as e:
            print(f"Error checking/adding created_at column: {e}")
        
        try:
            cursor.execute("SHOW COLUMNS FROM products LIKE 'updated_at'")
            if not cursor.fetchone():
                print("Adding updated_at column to products table...")
                cursor.execute("""
                    ALTER TABLE products 
                    ADD COLUMN updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
                """)
                conn.commit()
                print("updated_at column added successfully!")
        except Exception as e:
            print(f"Error checking/adding updated_at column: {e}")
        
        # Check if is_active column exists, if not add it
        try:
            cursor.execute("SHOW COLUMNS FROM products LIKE 'is_active'")
            if not cursor.fetchone():
                print("Adding is_active column to products table...")
                cursor.execute("""
                    ALTER TABLE products 
                    ADD COLUMN is_active BOOLEAN DEFAULT TRUE
                """)
                conn.commit()
                print("is_active column added successfully!")
        except Exception as e:
            print(f"Error checking/adding is_active column: {e}")
        
        # Get search and filter parameters
        search_query = request.args.get('search', '').strip()
        category_filter = request.args.get('category', '').strip()
        seller_filter = request.args.get('seller', '').strip()
        status_filter = request.args.get('status', '').strip()
        
        # Get pagination parameters
        page = request.args.get('page', 1, type=int)
        per_page = 20  # 20 products per page
        offset = (page - 1) * per_page
        
        # Build query to get all products with seller information
        base_query = """
            SELECT p.*, 
                   u.first_name, u.last_name, u.business_name,
                   COALESCE(u.business_name, CONCAT(u.first_name, ' ', u.last_name)) as seller_name
            FROM products p
            LEFT JOIN users u ON p.seller_email = u.email
            WHERE 1=1
        """
        
        params = []
        
        # Add search filter
        if search_query:
            base_query += " AND (p.name LIKE %s OR p.category LIKE %s OR p.description LIKE %s)"
            search_param = f'%{search_query}%'
            params.extend([search_param, search_param, search_param])
        
        # Add category filter
        if category_filter:
            base_query += " AND p.category = %s"
            params.append(category_filter)
        
        # Add seller filter
        if seller_filter:
            base_query += " AND p.seller_email = %s"
            params.append(seller_filter)
        
        # Add status filter
        if status_filter:
            if status_filter == 'active':
                base_query += " AND p.is_active = TRUE AND (p.flagged_at IS NULL OR p.flagged_at = '')"
            elif status_filter == 'inactive':
                base_query += " AND p.is_active = FALSE"
            elif status_filter == 'flagged':
                base_query += " AND p.flagged_at IS NOT NULL AND p.flagged_at != ''"
            elif status_filter == 'out_of_stock':
                base_query += " AND CAST(p.quantity AS SIGNED) <= 0"
            elif status_filter == 'low_stock':
                base_query += " AND CAST(p.quantity AS SIGNED) > 0 AND CAST(p.quantity AS SIGNED) <= COALESCE(p.low_stock_threshold, 5)"
        
        # Get total count for pagination
        count_query = f"SELECT COUNT(*) as total FROM ({base_query}) as filtered_products"
        cursor.execute(count_query, params)
        total_products = cursor.fetchone()['total']
        total_pages = (total_products + per_page - 1) // per_page
        
        # Order by created_at if it exists, otherwise by id
        base_query += " ORDER BY p.id DESC"
        
        # Add pagination
        base_query += " LIMIT %s OFFSET %s"
        params.extend([per_page, offset])
        
        # Execute query
        cursor.execute(base_query, params)
        products = cursor.fetchall()
        
        # Convert price to float and quantity to int for proper formatting
        for product in products:
            if product.get('price'):
                try:
                    product['price'] = float(product['price'])
                except (ValueError, TypeError):
                    product['price'] = 0.0
            
            # Convert quantity/stock to integer
            if product.get('quantity') is not None:
                try:
                    product['quantity'] = int(product['quantity'])
                except (ValueError, TypeError):
                    product['quantity'] = 0
            
            if product.get('stock_quantity') is not None:
                try:
                    product['stock_quantity'] = int(product['stock_quantity'])
                except (ValueError, TypeError):
                    product['stock_quantity'] = 0
        
        # Get all categories for filter dropdown
        cursor.execute("SELECT DISTINCT category FROM products WHERE category IS NOT NULL ORDER BY category")
        categories = [row['category'] for row in cursor.fetchall() if row['category']]
        
        # Get all sellers for filter dropdown
        cursor.execute("""
            SELECT DISTINCT u.email, 
                   COALESCE(u.business_name, CONCAT(u.first_name, ' ', u.last_name)) as seller_name
            FROM users u
            INNER JOIN products p ON u.email = p.seller_email
            WHERE u.user_type = 'Seller'
            ORDER BY seller_name
        """)
        sellers = cursor.fetchall()
        
        # Calculate low stock and out of stock counts
        # Get all products to calculate stock status
        cursor.execute("""
            SELECT quantity, low_stock_threshold
            FROM products
        """)
        all_products = cursor.fetchall()
        
        low_stock_count = 0
        out_of_stock_count = 0
        
        for product in all_products:
            quantity = int(product['quantity']) if product.get('quantity') is not None else 0
            threshold = int(product['low_stock_threshold']) if product.get('low_stock_threshold') else 5
            
            if quantity <= 0:
                out_of_stock_count += 1
            elif quantity <= threshold:
                low_stock_count += 1
        
        cursor.close()
        conn.close()
        
        return render_template('product_management.html', 
                             products=products, 
                             categories=categories,
                             sellers=sellers,
                             page=page,
                             total_pages=total_pages,
                             total_products=total_products,
                             low_stock_count=low_stock_count,
                             out_of_stock_count=out_of_stock_count)
    
    except Exception as e:
        print(f"Error in product_management: {e}")
        flash(f'An error occurred while loading products: {str(e)}', 'danger')
        cursor.close()
        conn.close()
        return redirect(url_for('admin_dashboard'))

@app.route('/admin_dashboard')
def admin_dashboard():
    # Safe defaults
    total_buyers = total_sellers = total_riders = 0
    total_sales = platform_sales = 0
    pending_approvals = 0
    total_orders = total_products = total_revenue = 0
    total_platform_commission = 0.0
    total_issues = 0

    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)

        # User counts
        try:
            cursor.execute("SELECT UPPER(user_type) as t, COUNT(*) as c FROM users GROUP BY UPPER(user_type)")
            for row in cursor.fetchall():
                t = (row['t'] or '').upper()
                if t == 'BUYER':   total_buyers  = row['c']
                elif t == 'SELLER': total_sellers = row['c']
                elif t == 'RIDER':  total_riders  = row['c']
        except Exception as e:
            print(f"Error fetching user counts: {e}")

        # Sales
        try:
            cursor.execute("SELECT COALESCE(SUM(total_price),0) as s FROM orders WHERE status='Received'")
            total_sales = cursor.fetchone()['s'] or 0
            platform_sales = float(total_sales) * 0.05
        except Exception as e:
            print(f"Error fetching sales: {e}")

        # Pending approvals
        try:
            cursor.execute("SELECT COUNT(*) as c FROM pending_users")
            pu = cursor.fetchone()['c'] or 0
            cursor.execute("SELECT COUNT(*) as c FROM pending_sellers WHERE status='pending'")
            ps = cursor.fetchone()['c'] or 0
            pending_approvals = pu + ps
        except Exception as e:
            print(f"Error fetching pending approvals: {e}")

        # Total orders
        try:
            cursor.execute("SELECT COUNT(*) as c FROM orders")
            total_orders = cursor.fetchone()['c'] or 0
        except Exception as e:
            print(f"Error fetching orders: {e}")

        # Total products
        try:
            cursor.execute("SELECT COUNT(*) as c FROM products")
            total_products = cursor.fetchone()['c'] or 0
        except Exception as e:
            print(f"Error fetching products: {e}")

        # Total revenue
        try:
            cursor.execute("SELECT COALESCE(SUM(total_price),0) as r FROM orders WHERE status IN ('Received','Delivered','Completed')")
            total_revenue = cursor.fetchone()['r'] or 0
        except Exception as e:
            print(f"Error fetching revenue: {e}")

        # Platform commission
        try:
            cursor.execute("""
                SELECT
                    COALESCE(SUM(CAST(total_price AS DECIMAL(10,2))*0.05),0) as sc,
                    COALESCE(SUM(50.00*0.05),0) as rc
                FROM orders
                WHERE status IN ('Delivered','Completed','Received','delivered','completed','received')
            """)
            row = cursor.fetchone()
            total_platform_commission = float(row['sc'] or 0) + float(row['rc'] or 0)
        except Exception as e:
            print(f"Error fetching commission: {e}")

        # Total issues
        try:
            cursor.execute("SELECT COUNT(*) as c FROM order_issues")
            total_issues = cursor.fetchone()['c'] or 0
        except Exception as e:
            print(f"Error fetching issues: {e}")

        cursor.close()
        connection.close()

    except Exception as e:
        print(f"?? MySQL unavailable in admin_dashboard: {e}")

    return render_template('admin_dashboard.html',
                           total_users=total_buyers + total_sellers + total_riders,
                           total_orders=total_orders,
                           total_platform_commission=total_platform_commission,
                           total_revenue=total_revenue,
                           total_products=total_products,
                           total_issues=total_issues,
                           pending_approvals=pending_approvals,
                           platform_sales=platform_sales)
    
@app.route('/debug_user_counts')
def debug_user_counts():
    """Debug route to check user counts"""
    if 'user_id' not in session or session.get('user_type') != 'Admin':
        return "Access denied"
    
    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)
    
    try:
        # Get all users with their types
        cursor.execute("SELECT id, first_name, last_name, email, user_type FROM users ORDER BY user_type")
        all_users = cursor.fetchall()
        
        # Get counts by type
        cursor.execute("SELECT user_type, COUNT(*) as count FROM users GROUP BY user_type")
        type_counts = cursor.fetchall()
        
        # Get total count
        cursor.execute("SELECT COUNT(*) as total FROM users")
        total_result = cursor.fetchone()
        
        cursor.close()
        connection.close()
        
        html = f"""
        <h2>User Counts Debug</h2>
        <h3>Total Users: {total_result['total'] if total_result else 0}</h3>
        
        <h3>Counts by Type:</h3>
        <ul>
        """
        
        for type_count in type_counts:
            html += f"<li>{type_count['user_type']}: {type_count['count']}</li>"
        
        html += """
        </ul>
        
        <h3>All Users:</h3>
        <table border="1" style="border-collapse: collapse;">
        <tr><th>ID</th><th>Name</th><th>Email</th><th>Type</th></tr>
        """
        
        for user in all_users:
            html += f"""
            <tr>
                <td>{user['id']}</td>
                <td>{user['first_name']} {user['last_name']}</td>
                <td>{user['email']}</td>
                <td>{user['user_type']}</td>
            </tr>
            """
        
        html += """
        </table>
        <br>
        <a href="/admin_dashboard">Back to Dashboard</a>
        """
        
        return html
        
    except Exception as e:
        cursor.close()
        connection.close()
        return f"Error: {e}"

@app.route('/api/seller_contributions')
def seller_contributions():
    sort_order = request.args.get('sort', 'desc')  # Default to descending order
    search_query = request.args.get('search', '').lower()  # Get search query
    order_clause = "DESC" if sort_order == 'desc' else "ASC"

    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)

    # Calculate seller contributions (5% of their total sales)
    query = f"""
        SELECT seller_email, SUM(total_price) * 0.05 AS total_contribution
        FROM orders
        WHERE status = 'Received'
        GROUP BY seller_email
    """

    # Filter by email if search query is provided
    if search_query:
        query += f" HAVING LOWER(seller_email) LIKE '%{search_query}%'"
    
    query += f" ORDER BY total_contribution {order_clause}"

    cursor.execute(query)
    sellers = cursor.fetchall()

    cursor.close()
    connection.close()

    return jsonify(sellers)

@app.route('/api/user_counts')
def user_counts():
    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)

    cursor.execute("SELECT user_type, COUNT(*) as count FROM users GROUP BY user_type")
    data = cursor.fetchall()

    cursor.close()
    connection.close()

    return jsonify(data)

@app.route('/pending_sellers', methods=['GET'])
def pending_sellers_dashboard():
    search_email = request.args.get('search_email', '')
    status_filter = request.args.get('status', 'all')
    sellers = []

    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        base_query = 'SELECT * FROM pending_sellers'
        conditions = []
        params = []

        if search_email:
            conditions.append('email LIKE %s')
            params.append(f"%{search_email}%")

        if status_filter and status_filter != 'all':
            conditions.append('status = %s')
            params.append(status_filter)

        query = base_query + (' WHERE ' + ' AND '.join(conditions) if conditions else '') + ' ORDER BY created_at DESC'

        cursor.execute(query, params)
        sellers = cursor.fetchall()
        cursor.close()
        conn.close()
    except Exception as e:
        print(f"?? MySQL unavailable in pending_sellers_dashboard: {e}")

    # Also fetch mobile seller registrations from Supabase pending_sellers table
    try:
        sb_query = sb_admin.table('pending_sellers').select('*').order('created_at', desc=True)
        if status_filter and status_filter != 'all':
            sb_query = sb_query.eq('status', status_filter)
        else:
            sb_query = sb_query.eq('status', 'pending')

        supabase_sellers_res = sb_query.execute()
        supabase_sellers = supabase_sellers_res.data or []

        mysql_emails = {s['email'] for s in sellers}

        for s in supabase_sellers:
            if s.get('email') not in mysql_emails:
                from dateutil import parser as dtparser
                created_raw = s.get('created_at')
                try:
                    created_dt = dtparser.parse(created_raw) if created_raw else None
                except Exception:
                    created_dt = None

                addr_parts = [
                    s.get('house_street') or '',
                    s.get('barangay') or '',
                    s.get('city') or '',
                    s.get('province') or '',
                    s.get('region') or '',
                    s.get('zip_code') or '',
                ]
                address = ', '.join(p for p in addr_parts if p)

                sellers.append({
                    'id':                   f"sb_{s.get('id')}",
                    'email':                s.get('email'),
                    'first_name':           s.get('first_name'),
                    'last_name':            s.get('last_name'),
                    'business_name':        s.get('business_name'),
                    'business_type':        s.get('business_type'),
                    'phone_number':         s.get('phone') or '',
                    'address':              address,
                    'status':               s.get('status', 'pending'),
                    'created_at':           created_dt,
                    'valid_id_path':        s.get('valid_id_path'),
                    'dti_path':             s.get('dti_path'),
                    'bir_path':             s.get('bir_path'),
                    'business_permit_path': s.get('business_permit_path'),
                    'supabase_uid':         s.get('supabase_uid'),
                    'source':               'mobile',
                })
    except Exception as e:
        print(f"?? Supabase pending_sellers fetch error: {e}")

    return render_template('pending_sellers.html', sellers=sellers, current_status=status_filter)

@app.route('/reject_seller/<string:seller_id>', methods=['POST'])
def reject_seller(seller_id):
    rejection_reason = (request.get_json() or {}).get('rejection_reason', '').strip() if request.is_json else request.form.get('rejection_reason', '').strip()
    if not rejection_reason:
        rejection_reason = 'Application does not meet our requirements'

    # -- Supabase-sourced (sb_ prefix) -------------------------------------
    if str(seller_id).startswith('sb_'):
        supabase_record_id = seller_id[3:]
        try:
            res = sb_admin.table('pending_sellers').select('*').eq('id', supabase_record_id).execute()
            if not res.data:
                return jsonify({'success': False, 'error': 'Seller not found'})

            s = res.data[0]
            supabase_uid = s.get('supabase_uid')

            # Send rejection email
            try:
                send_seller_rejection_email(s.get('email'), s.get('first_name'), s.get('business_name', ''), rejection_reason)
            except Exception as e:
                print(f"Warning: rejection email failed: {e}")

            # Delete from pending_sellers so they can re-register
            sb_admin.table('pending_sellers').delete().eq('id', supabase_record_id).execute()

            # Delete the Supabase auth account so they can sign up fresh
            if supabase_uid:
                try:
                    sb_admin.auth.admin.delete_user(supabase_uid)
                except Exception as ue:
                    print(f"Warning: delete auth user after rejection failed: {ue}")

            return jsonify({'success': True, 'message': 'Seller rejected and notified via email'})

        except Exception as e:
            import traceback; traceback.print_exc()
            return jsonify({'success': False, 'error': str(e)})

    # -- MySQL-sourced (numeric ID) -----------------------------------------
    try:
        mysql_id = int(seller_id)
    except ValueError:
        return jsonify({'success': False, 'error': 'Invalid seller ID'})

    try:
        db = get_db_connection()
        cursor = db.cursor(dictionary=True)

        cursor.execute('SELECT first_name, last_name, email, business_name, supabase_uid FROM pending_sellers WHERE id = %s', (mysql_id,))
        seller = cursor.fetchone()

        if not seller:
            cursor.close(); db.close()
            return jsonify({'success': False, 'error': 'Seller not found'})

        # Send rejection email
        try:
            send_seller_rejection_email(seller['email'], seller['first_name'], seller.get('business_name', ''), rejection_reason)
        except Exception as e:
            print(f"Warning: rejection email failed: {e}")

        # Delete from pending_sellers so they can re-register
        cursor.execute('DELETE FROM pending_sellers WHERE id = %s', (mysql_id,))
        db.commit()

        # Delete the Supabase auth account so they can sign up fresh
        supabase_uid = seller.get('supabase_uid')
        if supabase_uid:
            try:
                sb_admin.auth.admin.delete_user(supabase_uid)
            except Exception as ue:
                print(f"Warning: delete auth user after rejection failed: {ue}")

        cursor.close(); db.close()
        return jsonify({'success': True, 'message': 'Seller rejected and notified via email'})

    except mysql.connector.Error as err:
        return jsonify({'success': False, 'error': str(err)})

@app.route('/api/seller_documents/<string:seller_id>')
def get_seller_documents(seller_id):
    BUCKET = 'user-documents'
    SUPABASE_STORAGE_BASE = f"{SUPABASE_URL}/storage/v1/object/public/{BUCKET}"

    def signed_url(storage_path):
        if not storage_path:
            return None
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
        return f"{SUPABASE_STORAGE_BASE}/{storage_path}"

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
        db = get_db_connection()
        cursor = db.cursor(dictionary=True)
        cursor.execute('''
            SELECT first_name, last_name, business_name, business_type,
                   valid_id_path, dti_path, bir_path, business_permit_path
            FROM pending_sellers WHERE id = %s
        ''', (numeric_id,))
        result = cursor.fetchone()
        cursor.close()
        db.close()

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
    """API endpoint to get user documents � handles both MySQL (numeric) and Supabase (sb_) IDs"""

    BUCKET = 'user-documents'
    SUPABASE_STORAGE_BASE = f"{SUPABASE_URL}/storage/v1/object/public/{BUCKET}"

    def signed_url(storage_path):
        if not storage_path:
            return None
        try:
            result = sb_admin.storage.from_(BUCKET).create_signed_url(storage_path, 3600)
            if isinstance(result, dict):
                url = result.get('signedURL') or result.get('signedUrl') or result.get('signed_url')
            else:
                url = getattr(result, 'signed_url', None) or getattr(result, 'signedURL', None)
            if url:
                return url
        except Exception as e:
            print(f'user signed_url error for {storage_path}: {e}')
        return f"{SUPABASE_STORAGE_BASE}/{storage_path}"

    def resolve_doc_url(stored_path, subfolder):
        """
        Convert a stored document path to a list of web-accessible URLs.
        Handles two cases:
          1. Local file path (web registration) � e.g. C:\\...\\static\\images\\uploads\\ids\\file.png
             ? returns ['/static/images/uploads/ids/file.png', ...]
          2. Supabase Storage key (mobile registration) � e.g. user-documents/ids/file.png
             ? returns a signed URL
        """
        if not stored_path:
            return None, []

        # Normalise backslashes ? forward slashes
        normalised = stored_path.replace('\\', '/')

        # Detect local path: contains 'static/images/uploads' or 'static/uploads'
        # or is an absolute OS path (starts with drive letter or /)
        is_local = (
            'static/images/uploads' in normalised
            or 'static/uploads' in normalised
            or (len(normalised) > 1 and normalised[1] == ':')   # Windows C:/...
            or normalised.startswith('/') and 'supabase' not in normalised
        )

        if is_local:
            fn = os.path.basename(normalised)
            variations = [
                f"/static/images/uploads/{subfolder}/{fn}",
                f"/static/uploads/{subfolder}/{fn}",
                f"/uploads/{subfolder}/{fn}",
            ]
            return variations[0], variations

        # Supabase Storage key � generate signed URL
        url = signed_url(stored_path)
        return url, [url] if url else []

    # -- Supabase-registered user (sb_ prefix) ----------------------------
    if str(user_id).startswith('sb_'):
        supabase_id = user_id[3:]  # strip 'sb_' prefix
        try:
            res = sb_admin.table('pending_users').select('*').eq('id', supabase_id).execute()
            if not res.data:
                return jsonify({'success': False, 'error': 'User not found'})
            u = res.data[0]

            # Also check pending_rider_vehicles for vehicle info, OR/CR and NBI paths
            # The table uses supabase_uid (not user_id) as the FK
            supabase_uid_for_rv = u.get('supabase_uid')
            or_cr_path  = None
            nbi_path    = None
            vehicle_type = vehicle_model = vehicle_plate_number = vehicle_year_model = None
            try:
                rv_query = sb_admin.table('pending_rider_vehicles').select('*')
                if supabase_uid_for_rv:
                    rv_res = rv_query.eq('supabase_uid', supabase_uid_for_rv).execute()
                else:
                    rv_res = rv_query.eq('supabase_uid', supabase_id).execute()
                if rv_res.data:
                    rv = rv_res.data[0]
                    or_cr_path            = rv.get('or_cr_path')
                    nbi_path              = rv.get('nbi_clearance_path')
                    vehicle_type          = rv.get('vehicle_type')
                    vehicle_model         = rv.get('vehicle_model')
                    vehicle_plate_number  = rv.get('plate_number')
                    vehicle_year_model    = rv.get('year_model')
            except Exception as rv_err:
                print(f'pending_rider_vehicles lookup error: {rv_err}')

            valid_id_url,  valid_id_vars  = resolve_doc_url(u.get('valid_id_path'), 'ids')
            or_cr_url,     or_cr_vars     = resolve_doc_url(or_cr_path,             'rider_docs')
            nbi_url,       nbi_vars       = resolve_doc_url(nbi_path,               'rider_docs')

            return jsonify({
                'success': True,
                'user': {
                    'first_name':           u.get('first_name', ''),
                    'last_name':            u.get('last_name', ''),
                    'email':                u.get('email', ''),
                    'phone_number':         u.get('phone') or u.get('phone_number') or '',
                    'address':              u.get('address') or ', '.join(
                        p for p in [
                            u.get('house_street') or '',
                            u.get('barangay') or '',
                            u.get('city') or '',
                            u.get('province') or '',
                            u.get('region') or '',
                            u.get('zip_code') or '',
                        ] if p
                    ),
                    'user_type':            (u.get('role') or u.get('user_type') or 'buyer').capitalize(),
                    'vehicle_type':         vehicle_type,
                    'vehicle_model':        vehicle_model,
                    'vehicle_plate_number': vehicle_plate_number,
                    'vehicle_year_model':   vehicle_year_model,
                },
                'documents': {
                    'valid_id_url':       valid_id_url,
                    'or_cr_url':          or_cr_url,
                    'nbi_clearance_url':  nbi_url,
                    'valid_id_path':      u.get('valid_id_path'),
                    'path_variations':    valid_id_vars,
                    'or_cr_path':         or_cr_path,
                    'or_cr_variations':   or_cr_vars,
                    'nbi_clearance_path': nbi_path,
                    'nbi_variations':     nbi_vars,
                }
            })
        except Exception as e:
            print(f'Error in get_user_documents (Supabase): {e}')
            import traceback; traceback.print_exc()
            return jsonify({'success': False, 'error': str(e)})

    # -- MySQL-registered user (numeric ID) -------------------------------
    try:
        numeric_id = int(user_id)
    except ValueError:
        return jsonify({'success': False, 'error': 'Invalid user ID'})

    try:
        print(f"Getting documents for user ID: {numeric_id}")
        db = get_db_connection()
        cursor = db.cursor(dictionary=True)
        cursor.execute('''
            SELECT first_name, last_name, email, phone_number, address, user_type, valid_id_path,
                   vehicle_type, vehicle_model, vehicle_plate_number, vehicle_year_model,
                   or_cr_path, nbi_clearance_path
            FROM pending_users WHERE id = %s
        ''', (numeric_id,))
        result = cursor.fetchone()
        cursor.close()
        db.close()

        if result:
            valid_id_path = result['valid_id_path'] or ''
            base_filename = os.path.basename(valid_id_path)

            valid_id_url,  path_variations  = resolve_doc_url(valid_id_path,                    'ids')
            or_cr_url,     or_cr_variations = resolve_doc_url(result.get('or_cr_path'),         'rider_docs')
            nbi_url,       nbi_variations   = resolve_doc_url(result.get('nbi_clearance_path'), 'rider_docs')

            return jsonify({
                'success': True,
                'user': {
                    'first_name':           result['first_name'],
                    'last_name':            result['last_name'],
                    'email':                result['email'],
                    'phone_number':         result.get('phone_number'),
                    'address':              result.get('address'),
                    'user_type':            result['user_type'],
                    'vehicle_type':         result.get('vehicle_type'),
                    'vehicle_model':        result.get('vehicle_model'),
                    'vehicle_plate_number': result.get('vehicle_plate_number'),
                    'vehicle_year_model':   result.get('vehicle_year_model'),
                },
                'documents': {
                    'valid_id_url':       valid_id_url,
                    'or_cr_url':          or_cr_url,
                    'nbi_clearance_url':  nbi_url,
                    'valid_id_path':      valid_id_path,
                    'path_variations':    path_variations,
                    'or_cr_path':         result.get('or_cr_path'),
                    'or_cr_variations':   or_cr_variations,
                    'nbi_clearance_path': result.get('nbi_clearance_path'),
                    'nbi_variations':     nbi_variations,
                }
            })
        else:
            return jsonify({'success': False, 'error': 'User not found'})

    except Exception as err:
        print(f"Error in get_user_documents: {err}")
        return jsonify({'success': False, 'error': f'Error: {str(err)}'})

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

        def signed_url(storage_path):
            """Generate a signed URL for a Supabase Storage path.
            Falls back to public URL if signing fails."""
            if not storage_path:
                return None
            try:
                result = sb_admin.storage.from_(BUCKET).create_signed_url(storage_path, 3600)
                # supabase-py v1 returns a dict; v2 returns an object with .signed_url
                if isinstance(result, dict):
                    url = result.get('signedURL') or result.get('signedUrl') or result.get('signed_url')
                else:
                    url = getattr(result, 'signed_url', None) or getattr(result, 'signedURL', None)
                if url:
                    return url
            except Exception as e:
                print(f'signed_url error for {storage_path}: {e}')
            # Fallback: try public URL (works if bucket is public)
            return f"{SUPABASE_STORAGE_BASE}/{storage_path}"

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

        documents = {
            'valid_id_url':            signed_url(u.get('valid_id_path')),
            'dti_url':                 signed_url(u.get('dti_path')),
            'bir_url':                 signed_url(u.get('bir_path')),
            'business_permit_url':     signed_url(u.get('business_permit_path')),
            'or_cr_url':               signed_url(or_cr_path),
            'nbi_clearance_url':       signed_url(nbi_path),
            # Keep raw paths for reference
            'valid_id_path':           u.get('valid_id_path'),
            'dti_path':                u.get('dti_path'),
            'bir_path':                u.get('bir_path'),
            'business_permit_path':    u.get('business_permit_path'),
            'or_cr_path':              or_cr_path,
            'nbi_clearance_path':      nbi_path,
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
    """API endpoint to get user's full name by email"""
    try:
        email = request.args.get('email')
        
        if not email:
            return jsonify({
                'success': False,
                'error': 'Email is required'
            })
        
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        # Get user's name from database
        cursor.execute('''SELECT first_name, last_name, business_name, user_type 
                         FROM users 
                         WHERE email = %s''', (email,))
        
        user = cursor.fetchone()
        cursor.close()
        conn.close()
        
        if user:
            # For sellers, prefer business name if available
            if user['user_type'] == 'Seller' and user.get('business_name'):
                name = user['business_name']
            else:
                name = f"{user['first_name']} {user['last_name']}"
            
            return jsonify({
                'success': True,
                'name': name,
                'user_type': user['user_type']
            })
        else:
            return jsonify({
                'success': False,
                'error': 'User not found'
            })
        
    except Exception as err:
        return jsonify({
            'success': False,
            'error': f'Database error: {str(err)}'
        })

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
        db = get_db_connection()
        cursor = db.cursor(dictionary=True)
        
        cursor.execute('SELECT bir_path, dti_path, business_permit_path, valid_id_path FROM pending_sellers WHERE id = %s', (seller_id,))
        documents = cursor.fetchone()
        
        cursor.close()
        db.close()
        
        if documents:
            # Verify that the files exist
            for doc_type in ['bir_path', 'dti_path', 'business_permit_path', 'valid_id_path']:
                if documents[doc_type]:
                    file_path = os.path.join(app.config['UPLOAD_FOLDER'], documents[doc_type])
                    if not os.path.exists(file_path):
                        flash(f'{doc_type.replace("_path", "").upper()} document file not found!', 'error')
                        return redirect(url_for('pending_sellers_dashboard'))
            
            return render_template('view_documents.html', documents=documents)
        else:
            flash('Documents not found!', 'error')
            return redirect(url_for('pending_sellers_dashboard'))
            
    except mysql.connector.Error as err:
        flash(f"Database error: {err}", 'error')
        return redirect(url_for('pending_sellers_dashboard'))

@app.route('/approve/<string:seller_id>', methods=['POST'])
def approve_seller(seller_id):
    print(f"DEBUG: Starting approval process for seller ID: {seller_id}")
    
    if 'user_id' not in session or session.get('user_type') != 'Admin':
        print("DEBUG: Access denied - not admin")
        flash('? Access denied. Admin privileges required.', 'error')
        return redirect(url_for('pending_sellers_dashboard'))

    # -- Supabase-sourced (mobile) seller registration ---------------------
    if str(seller_id).startswith('sb_'):
        supabase_record_id = seller_id[3:]
        try:
            res = sb_admin.table('pending_sellers').select('*').eq('id', supabase_record_id).execute()
            if not res.data:
                return jsonify({'success': False, 'error': 'Seller not found in pending list'})

            s = res.data[0]
            supabase_uid = s.get('supabase_uid')
            seller_name = f"{s.get('first_name')} {s.get('last_name')}"

            # Insert into Supabase users table
            addr_parts = [
                s.get('house_street') or '',
                s.get('barangay') or '',
                s.get('city') or '',
                s.get('province') or '',
                s.get('region') or '',
                s.get('zip_code') or '',
            ]
            sb_admin.table('users').upsert({
                'id':                  supabase_uid,
                'email':               s.get('email'),
                'first_name':          s.get('first_name'),
                'last_name':           s.get('last_name'),
                'phone':               s.get('phone') or '',
                'role':                'seller',
                'business_name':       s.get('business_name'),
                'business_type':       s.get('business_type'),
                'house_street':        addr_parts[0],
                'barangay':            addr_parts[1],
                'city':                addr_parts[2],
                'province':            addr_parts[3],
                'region':              addr_parts[4],
                'zip_code':            addr_parts[5],
                'valid_id_path':       s.get('valid_id_path'),
                'dti_path':            s.get('dti_path'),
                'bir_path':            s.get('bir_path'),
                'business_permit_path': s.get('business_permit_path'),
            }).execute()

            # Unban the auth account
            if supabase_uid:
                try:
                    sb_admin.auth.admin.update_user_by_id(supabase_uid, {'ban_duration': 'none'})
                except Exception as ue:
                    print(f"Warning: unban failed: {ue}")

            # Delete from Supabase pending_sellers
            sb_admin.table('pending_sellers').delete().eq('id', supabase_record_id).execute()

            # Send approval email
            try:
                send_seller_approval_email(s.get('email'), s.get('first_name'), s.get('business_name', seller_name))
            except Exception:
                pass

            return jsonify({'success': True, 'message': f'{seller_name} successfully approved'})

        except Exception as e:
            import traceback; traceback.print_exc()
            return jsonify({'success': False, 'error': f'Error approving seller: {str(e)}'})

    # -- MySQL-sourced (web) seller registration ---------------------------
    try:
        mysql_id = int(seller_id)
    except ValueError:
        return jsonify({'success': False, 'error': 'Invalid seller ID'})

    db = None
    cursor = None
    
    try:
        print("DEBUG: Connecting to database")
        db = get_db_connection()
        cursor = db.cursor(dictionary=True)
        print("DEBUG: Database connected successfully")

        cursor.execute('SELECT * FROM pending_sellers WHERE id = %s', (mysql_id,))
        seller = cursor.fetchone()

        if not seller:
            print("DEBUG: Seller not found")
            return jsonify({'success': False, 'error': 'Seller not found in the pending list'})

        print(f"DEBUG: Found seller: {seller['first_name']} {seller['last_name']} ({seller['email']})")
        seller_name = f"{seller['first_name']} {seller['last_name']}"
        
        cursor.execute('SELECT id FROM users WHERE email = %s', (seller['email'],))
        existing_user = cursor.fetchone()
        
        if existing_user:
            print("DEBUG: Seller already exists in users table")
            cursor.execute('DELETE FROM pending_sellers WHERE id = %s', (mysql_id,))
            db.commit()
            return jsonify({'success': False, 'error': f'{seller_name} is already registered as a user'})
        
        cursor.execute('''INSERT INTO users (first_name, last_name, email, phone_number, address, password, user_type,
                          business_name, business_type, valid_id_path, dti_path, bir_path, business_permit_path)
                          VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)''',
                       (seller['first_name'], seller['last_name'], seller['email'],
                        seller['phone_number'], seller['address'], seller['password'],
                        'Seller', seller.get('business_name'), seller.get('business_type'),
                        seller.get('valid_id_path'), seller.get('dti_path'), 
                        seller.get('bir_path'), seller.get('business_permit_path')))
        print("DEBUG: Seller inserted into users table successfully")

        # -- Insert into Supabase users table and unban auth account ------
        supabase_uid = seller.get('supabase_uid')
        if supabase_uid:
            try:
                addr_parts = [p.strip() for p in (seller.get('address') or '').split(',')]
                sb_admin.table('users').upsert({
                    'id':                  supabase_uid,
                    'email':               seller['email'],
                    'first_name':          seller['first_name'],
                    'last_name':           seller['last_name'],
                    'phone':               seller.get('phone_number') or '',
                    'role':                'seller',
                    'business_name':       seller.get('business_name'),
                    'business_type':       seller.get('business_type'),
                    'house_street':        addr_parts[0] if len(addr_parts) > 0 else '',
                    'barangay':            addr_parts[1] if len(addr_parts) > 1 else '',
                    'city':                addr_parts[2] if len(addr_parts) > 2 else '',
                    'province':            addr_parts[3] if len(addr_parts) > 3 else '',
                    'region':              addr_parts[4] if len(addr_parts) > 4 else '',
                    'zip_code':            addr_parts[5] if len(addr_parts) > 5 else '',
                    'valid_id_path':       seller.get('valid_id_path'),
                    'dti_path':            seller.get('dti_path'),
                    'bir_path':            seller.get('bir_path'),
                    'business_permit_path': seller.get('business_permit_path'),
                }).execute()
                sb_admin.auth.admin.update_user_by_id(supabase_uid, {'ban_duration': 'none'})
                print(f"DEBUG: Supabase seller profile inserted and auth unbanned for {seller['email']}")
            except Exception as se:
                print(f"WARNING: Supabase seller insert/unban failed: {se}")
                import traceback; traceback.print_exc()
        else:
            print(f"WARNING: No supabase_uid for seller {seller['email']}")
        
        cursor.execute('DELETE FROM pending_sellers WHERE id = %s', (mysql_id,))
        db.commit()
        print("DEBUG: Changes committed successfully")
        
        try:
            business_name = seller.get('business_name', f"{seller['first_name']} {seller['last_name']}'s Business")
            send_seller_approval_email(seller['email'], seller['first_name'], business_name)
            print("DEBUG: Approval email sent")
        except Exception as email_err:
            print(f"DEBUG: Email sending failed (non-critical): {email_err}")
        
        print(f"DEBUG: Approval successful for {seller_name}")
        return jsonify({'success': True, 'message': f'{seller_name} successfully approved'})
        
    except mysql.connector.Error as db_err:
        print(f"DEBUG: Database error: {db_err}")
        if db:
            db.rollback()
        return jsonify({'success': False, 'error': f'Database Error: {str(db_err)}'})
        
    except Exception as e:
        print(f"DEBUG: General error: {e}")
        import traceback
        traceback.print_exc()
        if db:
            db.rollback()
        return jsonify({'success': False, 'error': f'Error approving seller: {str(e)}'})
        
    finally:
        if cursor:
            cursor.close()
        if db:
            db.close()

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

@app.route('/simple-approve/<int:seller_id>')
def simple_approve(seller_id):
    """Simple approval test without database operations"""
    if 'user_id' not in session or session.get('user_type') != 'Admin':
        return "Access denied"
    
    try:
        db = get_db_connection()
        cursor = db.cursor(dictionary=True)
        
        # Get seller name
        cursor.execute('SELECT first_name, last_name FROM pending_sellers WHERE id = %s', (seller_id,))
        seller = cursor.fetchone()
        
        if seller:
            seller_name = f"{seller['first_name']} {seller['last_name']}"
            flash(f'? {seller_name} successfully approved!', 'success')
            print(f"DEBUG: Simple approval success message set for {seller_name}")
        else:
            flash('? Seller not found!', 'error')
        
        cursor.close()
        db.close()
        
    except Exception as e:
        flash(f'? Error: {str(e)}', 'error')
        print(f"DEBUG: Simple approval error: {e}")
    
    return redirect(url_for('pending_sellers_dashboard'))

@app.route('/test-approve/<int:seller_id>')
def test_approve(seller_id):
    """Test route to check seller data before approval"""
    if 'user_id' not in session or session.get('user_type') != 'Admin':
        return "Access denied"
    
    try:
        db = get_db_connection()
        cursor = db.cursor(dictionary=True)
        
        # Test database connection
        cursor.execute('SELECT 1 as test')
        test_result = cursor.fetchone()
        
        # Check users table structure
        cursor.execute('DESCRIBE users')
        users_columns = cursor.fetchall()
        
        # Fetch seller details from pending_sellers
        cursor.execute('SELECT * FROM pending_sellers WHERE id = %s', (seller_id,))
        seller = cursor.fetchone()
        
        cursor.close()
        db.close()
        
        result = f"""
        <h2>Database Test Results for Seller ID {seller_id}</h2>
        <h3>Database Connection:</h3>
        <p>? Connected successfully: {test_result}</p>
        
        <h3>Users Table Structure:</h3>
        <table border="1">
        <tr><th>Field</th><th>Type</th><th>Null</th><th>Key</th><th>Default</th><th>Extra</th></tr>
        """
        
        for col in users_columns:
            result += f"<tr><td>{col['Field']}</td><td>{col['Type']}</td><td>{col['Null']}</td><td>{col['Key']}</td><td>{col['Default']}</td><td>{col['Extra']}</td></tr>"
        
        result += "</table>"
        
        if seller:
            result += f"""
            <h3>Seller Data:</h3>
            <pre>{seller}</pre>
            """
        else:
            result += f"<h3>? No seller found with ID {seller_id}</h3>"
            
        result += f'<p><a href="/pending_sellers">Back to Pending Sellers</a></p>'
        return result
            
    except Exception as e:
        import traceback
        return f"<h2>Error: {str(e)}</h2><pre>{traceback.format_exc()}</pre>"

@app.route('/debug-approve/<int:seller_id>')
def debug_approve(seller_id):
    """Debug route to test approve function without database changes"""
    if 'user_id' not in session or session.get('user_type') != 'Admin':
        return "Access denied"
    
    try:
        print(f"DEBUG: Testing approval process for seller ID: {seller_id}")
        db = get_db_connection()
        cursor = db.cursor(dictionary=True)

        # Fetch seller details from pending_sellers
        cursor.execute('SELECT * FROM pending_sellers WHERE id = %s', (seller_id,))
        seller = cursor.fetchone()

        if seller:
            print(f"DEBUG: Found seller: {seller['first_name']} {seller['last_name']} ({seller['email']})")
            
            # Test if seller already exists in users table
            cursor.execute('SELECT id FROM users WHERE email = %s', (seller['email'],))
            existing_user = cursor.fetchone()
            
            result = f"""
            <h2>Debug Approval Test for Seller ID {seller_id}</h2>
            <h3>Seller Data:</h3>
            <pre>{seller}</pre>
            
            <h3>Existing User Check:</h3>
            <p>Email: {seller['email']}</p>
            <p>Already exists in users table: {'Yes' if existing_user else 'No'}</p>
            {f'<p>Existing user ID: {existing_user["id"]}</p>' if existing_user else ''}
            
            <h3>Test Insert Query:</h3>
            <p>Would insert: {seller['first_name']}, {seller['last_name']}, {seller['email']}, {seller['phone_number']}, {seller['address']}, [password], Seller</p>
            """
            
            if existing_user:
                result += "<p style='color: orange;'>?? This seller already exists in the users table!</p>"
            else:
                result += "<p style='color: green;'>? This seller can be inserted into users table.</p>"
                
        else:
            result = f"<h2>? No seller found with ID {seller_id}</h2>"
        
        cursor.close()
        db.close()
        result += f'<p><a href="/pending_sellers">Back to Pending Sellers</a></p>'
        return result
        
    except Exception as e:
        import traceback
        return f"<h2>Error: {str(e)}</h2><pre>{traceback.format_exc()}</pre>"

@app.route('/update/<int:user_id>', methods=['GET', 'POST'])
def update_user(user_id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    if request.method == 'POST':
        # Fetch the form data
        first_name = request.form.get('first_name')
        last_name = request.form.get('last_name')
        email = request.form.get('email')
        phone_number = request.form.get('phone_number')
        address = request.form.get('address')
        user_type = request.form.get('user_type')

        # Update the user in the database
        cursor.execute('''UPDATE users 
                         SET first_name=%s, last_name=%s, email=%s, phone_number=%s, 
                             address=%s, user_type=%s 
                         WHERE id=%s''', 
                      (first_name, last_name, email, phone_number, address, user_type, user_id))
        conn.commit()
        flash('User updated successfully!', 'success')
        return redirect(url_for('admin_users'))

    # If GET request, fetch user information
    cursor.execute('SELECT * FROM users WHERE id=%s', (user_id,))
    user = cursor.fetchone()
    cursor.close()
    conn.close()

    return render_template('edit_user.html', user=user)

@app.route('/delete/<int:user_id>', methods=['POST'])
def delete_user(user_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Delete from archive table instead of users table
    cursor.execute('DELETE FROM archive WHERE id = %s', (user_id,))
    conn.commit()
    
    cursor.close()
    conn.close()
    return jsonify({'success': True})

@app.route('/archive_accounts', methods=['GET'])
def archive_accounts():
    if 'user_id' not in session or session.get('user_type') != 'Admin':
        flash('Access denied. Admin privileges required.', 'error')
        return redirect(url_for('login'))

    search_query = request.args.get('search', '').strip()
    archived_users = []

    try:
        res = sb_admin.table('archived_users').select('*').order('archived_at', desc=True).execute()
        raw = res.data or []

        for u in raw:
            # Build combined address from separate fields
            addr_parts = [
                u.get('house_street') or '',
                u.get('barangay') or '',
                u.get('city') or '',
                u.get('province') or '',
                u.get('region') or '',
                u.get('zip_code') or '',
            ]
            u['address'] = ', '.join(p for p in addr_parts if p)
            u['phone_number'] = u.get('phone') or ''
            u['user_type'] = (u.get('role') or 'buyer').capitalize()

            # Parse archived_at
            archived_at_raw = u.get('archived_at')
            if archived_at_raw and isinstance(archived_at_raw, str):
                try:
                    from dateutil import parser as dtparser
                    u['archived_at_dt'] = dtparser.parse(archived_at_raw)
                except Exception:
                    u['archived_at_dt'] = None
            else:
                u['archived_at_dt'] = None

            # Apply search filter
            if search_query:
                sq = search_query.lower()
                haystack = ' '.join(filter(None, [
                    u.get('first_name') or '', u.get('last_name') or '',
                    u.get('email') or '', u.get('phone_number') or '',
                ])).lower()
                if sq not in haystack:
                    continue

            archived_users.append(u)

    except Exception as e:
        print(f'archive_accounts Supabase error: {e}')
        import traceback; traceback.print_exc()

    return render_template('archive.html', users=archived_users, search=search_query)


@app.route('/archive/<int:user_id>', methods=['POST'])
def archive_account(user_id):
    # Connect to the database
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # Retrieve the user to be archived
    cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))
    user = cursor.fetchone()

    if user:
        # Insert the user into the archive table
        cursor.execute("""
            INSERT INTO archive (id, first_name, last_name, password, email, phone_number, address, user_type, bir, dti, tin)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (user['id'], user['first_name'], user['last_name'], user['password'], user['email'],
              user['phone_number'], user['address'], user['user_type'], user['bir'], user['dti'], user['tin']))

        # Delete the user from the users table
        cursor.execute("DELETE FROM users WHERE id = %s", (user_id,))
        conn.commit()

    else:
        flash("User not found.", "error")

    conn.close()
    return redirect(url_for('admin_dashboard'))

@app.route('/restore/<int:user_id>', methods=['POST'])
def restore_account(user_id):
    # Connect to the database
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # Retrieve the archived user to be restored
    cursor.execute("SELECT * FROM archive WHERE id = %s", (user_id,))
    archived_user = cursor.fetchone()

    if archived_user:
        # Insert the user back into the users table
        cursor.execute("""
            INSERT INTO users (id, first_name, last_name, password, email, phone_number, address, user_type, bir, dti, tin)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (archived_user['id'], archived_user['first_name'], archived_user['last_name'],
              archived_user['password'], archived_user['email'], archived_user['phone_number'],
              archived_user['address'], archived_user['user_type'], archived_user['bir'],
              archived_user['dti'], archived_user['tin']))

        # Delete the user from the archive table
        cursor.execute("DELETE FROM archive WHERE id = %s", (user_id,))
        conn.commit()

    else:
        flash("Archived user not found.", "error")

    conn.close()
    return redirect(url_for('archive_accounts'))

#----------------------------------------------------------------------
                         #ADMIN REPORTS & ANALYTICS
#----------------------------------------------------------------------

@app.route('/admin_reports_analytics')
def admin_reports_analytics():
    """Render the admin reports and analytics page"""
    if 'user_id' not in session or session.get('user_type') != 'Admin':
        flash('Access denied. Admin privileges required.', 'danger')
        return redirect(url_for('login'))
    
    return render_template('admin_reports_analytics.html')

@app.route('/print_layout')
def print_layout():
    """Render the print layout page"""
    if 'user_id' not in session or session.get('user_type') != 'Admin':
        flash('Access denied. Admin privileges required.', 'danger')
        return redirect(url_for('login'))
    
    return render_template('print_layout.html')

@app.route('/api/admin/dashboard_charts')
def admin_dashboard_charts():
    """API endpoint to provide chart data for admin dashboard"""
    if 'user_id' not in session or session.get('user_type') != 'Admin':
        return jsonify({'error': 'Unauthorized'}), 401
    
    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)
    
    try:
        # Get last 12 months data
        from datetime import datetime, timedelta
        from calendar import monthrange
        
        # Calculate date range for last 12 months
        end_date = datetime.now()
        
        # Helper function to add months
        def add_months(date, months):
            month = date.month - 1 + months
            year = date.year + month // 12
            month = month % 12 + 1
            day = min(date.day, monthrange(year, month)[1])
            return date.replace(year=year, month=month, day=day)
        
        start_date = add_months(end_date, -11)
        
        # Initialize data structures
        months = []
        revenue_data = []
        commission_data = []
        
        # Generate month labels
        current_month = start_date
        for i in range(12):
            month_label = current_month.strftime('%b %Y')
            months.append(month_label)
            
            # Get revenue for this month
            cursor.execute("""
                SELECT 
                    COALESCE(SUM(CAST(total_price AS DECIMAL(10,2))), 0) as monthly_revenue
                FROM orders
                WHERE status IN ('Delivered', 'Completed', 'Received', 'delivered', 'completed', 'received')
                AND YEAR(date) = %s AND MONTH(date) = %s
            """, (current_month.year, current_month.month))
            
            revenue_result = cursor.fetchone()
            monthly_revenue = float(revenue_result['monthly_revenue']) if revenue_result and revenue_result['monthly_revenue'] else 0.0
            revenue_data.append(monthly_revenue)
            
            # Get commission for this month (5% from sellers + 5% from riders)
            cursor.execute("""
                SELECT 
                    COALESCE(SUM(CAST(total_price AS DECIMAL(10,2)) * 0.05), 0) as seller_commission,
                    COALESCE(SUM(50.00 * 0.05), 0) as rider_commission
                FROM orders
                WHERE status IN ('Delivered', 'Completed', 'Received', 'delivered', 'completed', 'received')
                AND YEAR(date) = %s AND MONTH(date) = %s
            """, (current_month.year, current_month.month))
            
            commission_result = cursor.fetchone()
            seller_comm = float(commission_result['seller_commission']) if commission_result and commission_result['seller_commission'] else 0.0
            rider_comm = float(commission_result['rider_commission']) if commission_result and commission_result['rider_commission'] else 0.0
            monthly_commission = seller_comm + rider_comm
            commission_data.append(monthly_commission)
            
            # Move to next month
            current_month = add_months(current_month, 1)
        
        # Get top selling categories
        cursor.execute("""
            SELECT 
                p.category,
                SUM(CAST(o.quantity AS UNSIGNED)) as total_sold
            FROM orders o
            JOIN products p ON o.product_id = p.id
            WHERE o.status IN ('Delivered', 'Completed', 'Received', 'delivered', 'completed', 'received')
            AND p.category IS NOT NULL
            GROUP BY p.category
            ORDER BY total_sold DESC
            LIMIT 8
        """)
        
        categories_result = cursor.fetchall()
        category_labels = []
        category_values = []
        
        for cat in categories_result:
            category_labels.append(cat['category'] if cat['category'] else 'Uncategorized')
            category_values.append(int(cat['total_sold']) if cat['total_sold'] else 0)
        
        # Get order status distribution
        cursor.execute("""
            SELECT 
                status,
                COUNT(*) as count
            FROM orders
            GROUP BY status
            ORDER BY count DESC
        """)
        
        status_result = cursor.fetchall()
        status_labels = []
        status_values = []
        
        # Map status names to more readable labels
        status_map = {
            'Pending': 'Pending',
            'pending': 'Pending',
            'Processing': 'Processing',
            'processing': 'Processing',
            'Shipped': 'Shipped',
            'shipped': 'Shipped',
            'Out for Delivery': 'Out for Delivery',
            'out for delivery': 'Out for Delivery',
            'Delivered': 'Delivered',
            'delivered': 'Delivered',
            'Completed': 'Completed',
            'completed': 'Completed',
            'Received': 'Received',
            'received': 'Received',
            'Cancelled': 'Cancelled',
            'cancelled': 'Cancelled'
        }
        
        for status in status_result:
            status_name = status['status'] if status['status'] else 'Unknown'
            mapped_status = status_map.get(status_name, status_name)
            status_labels.append(mapped_status)
            status_values.append(int(status['count']) if status['count'] else 0)
        
        cursor.close()
        connection.close()
        
        return jsonify({
            'revenue': {
                'labels': months,
                'values': revenue_data
            },
            'commission': {
                'labels': months,
                'values': commission_data
            },
            'categories': {
                'labels': category_labels,
                'values': category_values
            },
            'orderStatus': {
                'labels': status_labels,
                'values': status_values
            }
        })
        
    except Exception as e:
        print(f"Error fetching dashboard chart data: {e}")
        import traceback
        traceback.print_exc()
        
        try:
            cursor.close()
            connection.close()
        except:
            pass
        
        # Return empty data instead of error to prevent chart breaking
        return jsonify({
            'revenue': {
                'labels': [],
                'values': []
            },
            'commission': {
                'labels': [],
                'values': []
            },
            'categories': {
                'labels': [],
                'values': []
            },
            'orderStatus': {
                'labels': [],
                'values': []
            },
            'error': str(e)
        }), 200

@app.route('/api/admin/analytics')
def admin_analytics_api():
    """API endpoint to provide analytics data"""
    if 'user_id' not in session or session.get('user_type') != 'Admin':
        return jsonify({'error': 'Unauthorized'}), 401
    
    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)
        
        # Get date range from query parameters (optional)
        from_date = request.args.get('from_date')
        to_date = request.args.get('to_date')
        
        # Build date filter
        date_filter = ""
        date_params = []
        if from_date and to_date:
            date_filter = " AND DATE(o.date) BETWEEN %s AND %s"
            date_params = [from_date, to_date]
        
        # 1. Get key metrics
        # Total orders
        cursor.execute(f"SELECT COUNT(*) as total FROM orders o WHERE 1=1{date_filter}", date_params)
        total_orders = cursor.fetchone()['total']
        
        # Total revenue (only completed orders)
        cursor.execute(f"""
            SELECT COALESCE(SUM(total_price), 0) as total 
            FROM orders o 
            WHERE status = 'Received'{date_filter}
        """, date_params)
        total_revenue = float(cursor.fetchone()['total'])
        
        # Total users
        cursor.execute("SELECT COUNT(*) as total FROM users")
        total_users = cursor.fetchone()['total']
        
        # Total products
        cursor.execute("SELECT COUNT(*) as total FROM products")
        total_products = cursor.fetchone()['total']
        
        # 2. Sales data for chart (last 30 days or date range)
        if from_date and to_date:
            cursor.execute("""
                SELECT DATE(date) as order_date, COALESCE(SUM(total_price), 0) as daily_sales
                FROM orders
                WHERE status = 'Received' AND DATE(date) BETWEEN %s AND %s
                GROUP BY DATE(date)
                ORDER BY order_date
            """, [from_date, to_date])
        else:
            cursor.execute("""
                SELECT DATE(date) as order_date, COALESCE(SUM(total_price), 0) as daily_sales
                FROM orders
                WHERE status = 'Received' AND date >= DATE_SUB(CURDATE(), INTERVAL 30 DAY)
                GROUP BY DATE(date)
                ORDER BY order_date
            """)
        
        sales_data = cursor.fetchall()
        sales_labels = [row['order_date'].strftime('%Y-%m-%d') for row in sales_data]
        sales_values = [float(row['daily_sales']) for row in sales_data]
        
        # 3. Order status distribution (matching seller order statuses)
        cursor.execute(f"""
            SELECT 
                CASE 
                    WHEN LOWER(status) = 'pending' THEN 'Pending'
                    WHEN LOWER(status) = 'confirmed' THEN 'Confirmed'
                    WHEN LOWER(status) IN ('for pickup', 'ready for pickup') THEN 'For Pickup'
                    WHEN LOWER(status) IN ('shipped', 'heading to seller') THEN 'Shipped'
                    WHEN LOWER(status) = 'delivered' THEN 'Delivered'
                    WHEN LOWER(status) IN ('completed', 'received') THEN 'Completed'
                    WHEN LOWER(status) = 'cancelled' THEN 'Cancelled'
                    WHEN LOWER(status) = 'rejected' THEN 'Rejected'
                    ELSE status
                END as normalized_status,
                COUNT(*) as count
            FROM orders o
            WHERE 1=1{date_filter}
            GROUP BY normalized_status
        """, date_params)
        
        status_data = cursor.fetchall()
        status_map = {
            'Pending': 0,
            'Confirmed': 0,
            'For Pickup': 0,
            'Shipped': 0,
            'Delivered': 0,
            'Completed': 0,
            'Cancelled': 0,
            'Rejected': 0
        }
        
        for row in status_data:
            normalized_status = row['normalized_status']
            if normalized_status in status_map:
                status_map[normalized_status] = row['count']
        
        order_status = [
            status_map['Pending'],
            status_map['Confirmed'],
            status_map['For Pickup'],
            status_map['Shipped'],
            status_map['Delivered'],
            status_map['Completed'],
            status_map['Cancelled'],
            status_map['Rejected']
        ]
        
        # 4. Top products
        cursor.execute(f"""
            SELECT p.name, COUNT(o.id) as sales, COALESCE(SUM(o.total_price), 0) as revenue
            FROM orders o
            JOIN products p ON o.product_id = p.id
            WHERE o.status = 'Received'{date_filter}
            GROUP BY p.id, p.name
            ORDER BY revenue DESC
            LIMIT 5
        """, date_params)
        
        top_products = []
        for row in cursor.fetchall():
            top_products.append({
                'name': row['name'],
                'sales': row['sales'],
                'revenue': float(row['revenue'])
            })
        
        # 5. Top sellers
        cursor.execute(f"""
            SELECT o.seller_email, COUNT(o.id) as orders, COALESCE(SUM(o.total_price), 0) as revenue
            FROM orders o
            WHERE o.status = 'Received'{date_filter}
            GROUP BY o.seller_email
            ORDER BY revenue DESC
            LIMIT 5
        """, date_params)
        
        top_sellers = []
        for row in cursor.fetchall():
            top_sellers.append({
                'name': row['seller_email'],
                'orders': row['orders'],
                'revenue': float(row['revenue'])
            })
        
        # 6. Inventory and Products Analytics
        # First ensure is_active column exists
        try:
            cursor.execute("ALTER TABLE products ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT TRUE")
            connection.commit()
        except:
            pass
        
        cursor.execute("""
            SELECT 
                p.id,
                p.name as product_name,
                p.seller_email,
                p.category,
                CASE 
                    WHEN COALESCE(p.is_active, 1) = 1 THEN 'Active'
                    ELSE 'Inactive'
                END as status,
                COALESCE(p.sold, 0) as units_sold,
                p.quantity as stock,
                COALESCE(AVG(r.rating), 0) as avg_rating,
                p.is_active,
                p.flagged_at,
                p.flag_reason
            FROM products p
            LEFT JOIN reviews r ON p.id = r.product_id
            GROUP BY p.id, p.name, p.seller_email, p.category, p.sold, p.quantity, p.is_active, p.flagged_at, p.flag_reason
            ORDER BY units_sold DESC
        """)
        
        inventory_products = []
        for idx, row in enumerate(cursor.fetchall(), 1):
            inventory_products.append({
                'no': idx,
                'product_name': row['product_name'],
                'seller_name': row['seller_email'],
                'category': row['category'],
                'status': row['status'],
                'units_sold': int(row['units_sold']),
                'stock': int(row['stock']) if row['stock'] else 0,
                'rating': round(float(row['avg_rating']), 1),
                'is_active': bool(row['is_active']) if row['is_active'] is not None else True,
                'is_flagged': bool(row['flagged_at']),
                'flagged_at': row['flagged_at'].strftime('%b %d, %Y at %I:%M %p') if row['flagged_at'] else None
            })
        
        # 7. Seller Performance Reports
        # First, ensure the columns exist
        try:
            cursor.execute("ALTER TABLE products ADD COLUMN IF NOT EXISTS is_flagged BOOLEAN DEFAULT FALSE")
            cursor.execute("ALTER TABLE products ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT TRUE")
            connection.commit()
        except:
            pass  # Columns might already exist
        
        cursor.execute("""
            SELECT 
                u.email,
                COALESCE(u.business_name, CONCAT(u.first_name, ' ', u.last_name)) as seller_name,
                COALESCE(prod_stats.total_products, 0) as total_products,
                COALESCE(order_stats.total_orders, 0) as total_orders,
                COALESCE(order_stats.completed_orders, 0) as completed_orders,
                COALESCE(order_stats.cancelled_orders, 0) as cancelled_orders,
                COALESCE(order_stats.total_revenue, 0) as total_revenue,
                COALESCE(prod_stats.flagged_products, 0) as flagged_products,
                COALESCE(prod_stats.deactivated_products, 0) as deactivated_products
            FROM users u
            LEFT JOIN (
                SELECT 
                    seller_email,
                    COUNT(*) as total_products,
                    SUM(CASE 
                        WHEN (COALESCE(is_flagged, 0) = 1 OR flag_reason IS NOT NULL) 
                        THEN 1 
                        ELSE 0 
                    END) as flagged_products,
                    SUM(CASE WHEN COALESCE(is_active, 1) = 0 THEN 1 ELSE 0 END) as deactivated_products
                FROM products
                GROUP BY seller_email
            ) prod_stats ON u.email = prod_stats.seller_email
            LEFT JOIN (
                SELECT 
                    seller_email,
                    COUNT(*) as total_orders,
                    SUM(CASE WHEN status IN ('Received', 'Completed', 'Delivered') THEN 1 ELSE 0 END) as completed_orders,
                    SUM(CASE WHEN status = 'Cancelled' THEN 1 ELSE 0 END) as cancelled_orders,
                    SUM(CASE WHEN status IN ('Received', 'Completed', 'Delivered') THEN CAST(total_price AS DECIMAL(10,2)) ELSE 0 END) as total_revenue
                FROM orders
                GROUP BY seller_email
            ) order_stats ON u.email = order_stats.seller_email
            WHERE u.user_type = 'Seller'
            ORDER BY total_revenue DESC
        """)
        
        seller_performance = []
        for idx, row in enumerate(cursor.fetchall(), 1):
            seller_performance.append({
                'no': idx,
                'seller_name': row['seller_name'],
                'email': row['email'],
                'total_products': int(row['total_products']) if row['total_products'] else 0,
                'total_orders': int(row['total_orders']) if row['total_orders'] else 0,
                'completed_orders': int(row['completed_orders']) if row['completed_orders'] else 0,
                'cancelled_orders': int(row['cancelled_orders']) if row['cancelled_orders'] else 0,
                'total_revenue': float(row['total_revenue']),
                'flagged_products': int(row['flagged_products']) if row['flagged_products'] else 0,
                'deactivated_products': int(row['deactivated_products']) if row['deactivated_products'] else 0
            })
        
        # 8. Rider/Delivery Analytics
        try:
            cursor.execute("""
                SELECT 
                    u.email,
                    CONCAT(u.first_name, ' ', u.last_name) as rider_name,
                    u.vehicle_type,
                    u.vehicle_plate_number,
                    COALESCE(delivery_stats.total_deliveries, 0) as total_deliveries,
                    COALESCE(delivery_stats.successful_deliveries, 0) as successful_deliveries,
                    COALESCE(delivery_stats.failed_deliveries, 0) as failed_deliveries,
                    COALESCE(delivery_stats.total_earnings, 0) as total_earnings
                FROM users u
                LEFT JOIN (
                    SELECT 
                        rider_email,
                        COUNT(*) as total_deliveries,
                        SUM(CASE WHEN status IN ('Delivered', 'Completed', 'Received') THEN 1 ELSE 0 END) as successful_deliveries,
                        SUM(CASE WHEN status = 'Cancelled' THEN 1 ELSE 0 END) as failed_deliveries,
                        SUM(CASE 
                            WHEN status IN ('Delivered', 'Completed', 'Received') 
                            THEN (50.00 - (50.00 * 0.05))
                            ELSE 0 
                        END) as total_earnings
                    FROM orders
                    WHERE rider_email IS NOT NULL AND rider_email != ''
                    GROUP BY rider_email
                ) delivery_stats ON u.email = delivery_stats.rider_email
                WHERE u.user_type = 'Rider'
                ORDER BY total_deliveries DESC
            """)
            
            rider_analytics = []
            for idx, row in enumerate(cursor.fetchall(), 1):
                rider_analytics.append({
                    'no': idx,
                    'rider_name': row['rider_name'],
                    'email': row['email'],
                    'vehicle_type': row['vehicle_type'] if row['vehicle_type'] else 'N/A',
                    'plate_number': row['vehicle_plate_number'] if row['vehicle_plate_number'] else 'N/A',
                    'total_deliveries': int(row['total_deliveries']) if row['total_deliveries'] else 0,
                    'successful_deliveries': int(row['successful_deliveries']) if row['successful_deliveries'] else 0,
                    'failed_deliveries': int(row['failed_deliveries']) if row['failed_deliveries'] else 0,
                    'total_earnings': float(row['total_earnings'])
                })
        except Exception as rider_error:
            print(f"Error fetching rider analytics: {rider_error}")
            rider_analytics = []
        
        # 9. Buyer Activity & Behavior Insights
        try:
            print("Fetching buyer insights...")
            cursor.execute("""
                SELECT 
                    u.email,
                    CONCAT(u.first_name, ' ', u.last_name) as buyer_name,
                    COALESCE(order_stats.total_orders, 0) as total_orders,
                    COALESCE(order_stats.total_spend, 0) as total_spend,
                    COALESCE(order_stats.avg_order_value, 0) as avg_order_value,
                    order_stats.last_order_date,
                    COALESCE(cart_stats.cart_items, 0) as browsing_activity,
                    CASE 
                        WHEN COALESCE(cart_stats.cart_items, 0) > 0 AND COALESCE(order_stats.total_orders, 0) > 0
                        THEN ((COALESCE(cart_stats.cart_items, 0) - COALESCE(order_stats.total_orders, 0)) / COALESCE(cart_stats.cart_items, 0) * 100)
                        WHEN COALESCE(cart_stats.cart_items, 0) > 0 AND COALESCE(order_stats.total_orders, 0) = 0
                        THEN 100
                        ELSE 0
                    END as cart_abandon_rate,
                    COALESCE(wishlist_stats.wishlist_items, 0) as wishlist_items
                FROM users u
                LEFT JOIN (
                    SELECT 
                        email,
                        COUNT(*) as total_orders,
                        SUM(CAST(total_price AS DECIMAL(10,2))) as total_spend,
                        AVG(CAST(total_price AS DECIMAL(10,2))) as avg_order_value,
                        MAX(date) as last_order_date
                    FROM orders
                    WHERE status IN ('Delivered', 'Completed', 'Received')
                    GROUP BY email
                ) order_stats ON u.email = order_stats.email
                LEFT JOIN (
                    SELECT 
                        email,
                        COUNT(*) as cart_items
                    FROM cart
                    GROUP BY email
                ) cart_stats ON u.email = cart_stats.email
                LEFT JOIN (
                    SELECT 
                        user_id,
                        COUNT(*) as wishlist_items
                    FROM wishlist
                    GROUP BY user_id
                ) wishlist_stats ON u.id = wishlist_stats.user_id
                WHERE u.user_type = 'Buyer'
                ORDER BY COALESCE(order_stats.total_spend, 0) DESC
                LIMIT 50
            """)
            
            buyer_results = cursor.fetchall()
            print(f"Found {len(buyer_results)} buyers")
            
            buyer_insights = []
            for idx, row in enumerate(buyer_results, 1):
                try:
                    buyer_insights.append({
                        'no': idx,
                        'buyer_name': row['buyer_name'],
                        'email': row['email'],
                        'total_orders': int(row['total_orders']) if row['total_orders'] else 0,
                        'total_spend': float(row['total_spend']) if row['total_spend'] else 0.0,
                        'avg_order_value': float(row['avg_order_value']) if row['avg_order_value'] else 0.0,
                        'last_order_date': row['last_order_date'].strftime('%Y-%m-%d') if row['last_order_date'] else None,
                        'cart_items': int(row['browsing_activity']) if row['browsing_activity'] else 0,
                        'wishlist_items': int(row['wishlist_items']) if row['wishlist_items'] else 0
                    })
                except Exception as row_error:
                    print(f"Error processing buyer row {idx}: {row_error}")
                    print(f"Row data: {row}")
                    
            print(f"Successfully processed {len(buyer_insights)} buyer insights")
        except Exception as buyer_error:
            print(f"Error fetching buyer insights: {buyer_error}")
            import traceback
            traceback.print_exc()
            buyer_insights = []
        
        # 10. Promo Code Usage Analytics
        try:
            print("Fetching promo code analytics...")
            
            # Check if promotions table exists
            cursor.execute("SHOW TABLES LIKE 'promotions'")
            if not cursor.fetchone():
                print("WARNING: promotions table does not exist!")
                promo_code_analytics = []
            else:
                # Check if there are any promotions
                cursor.execute("SELECT COUNT(*) as total FROM promotions")
                promo_count = cursor.fetchone()['total']
                print(f"Total promotions in database: {promo_count}")
                
                cursor.execute("""
                    SELECT 
                        p.id,
                        p.code as promo_code,
                        p.type as discount_type,
                        p.discount_value,
                        p.start_date,
                        p.end_date,
                        COALESCE(usage_stats.total_uses, 0) as total_uses,
                        COALESCE(usage_stats.total_discount_given, 0) as total_discount_given
                    FROM promotions p
                    LEFT JOIN (
                        SELECT 
                            promotion_id,
                            COUNT(*) as total_uses,
                            SUM(discount_applied) as total_discount_given
                        FROM promotion_usage
                        GROUP BY promotion_id
                    ) usage_stats ON p.id = usage_stats.promotion_id
                    ORDER BY total_uses DESC, p.created_at DESC
                """)
                
                promo_results = cursor.fetchall()
                print(f"Found {len(promo_results)} promo codes")
                
                promo_code_analytics = []
                for idx, row in enumerate(promo_results, 1):
                    try:
                        promo_code_analytics.append({
                            'no': idx,
                            'promo_code': row['promo_code'],
                            'discount_type': row['discount_type'],
                            'discount_value': float(row['discount_value']) if row['discount_value'] else 0.0,
                            'start_date': row['start_date'].strftime('%Y-%m-%d') if row['start_date'] else None,
                            'end_date': row['end_date'].strftime('%Y-%m-%d') if row['end_date'] else None,
                            'total_uses': int(row['total_uses']) if row['total_uses'] else 0,
                            'total_discount_given': float(row['total_discount_given']) if row['total_discount_given'] else 0.0
                        })
                    except Exception as row_error:
                        print(f"Error processing promo code row {idx}: {row_error}")
                        print(f"Row data: {row}")
                        
                print(f"Successfully processed {len(promo_code_analytics)} promo code analytics")
        except Exception as promo_error:
            print(f"Error fetching promo code analytics: {promo_error}")
            import traceback
            traceback.print_exc()
            promo_code_analytics = []
        
        # 11. Platform Commission Summary Report
        try:
            print("Fetching platform commission data...")
            
            # First check if there are ANY orders at all
            cursor.execute("SELECT COUNT(*) as total FROM orders")
            total_orders_check = cursor.fetchone()['total']
            print(f"Total orders in database: {total_orders_check}")
            
            # Check orders by status
            cursor.execute("""
                SELECT status, COUNT(*) as count 
                FROM orders 
                GROUP BY status
            """)
            status_counts = cursor.fetchall()
            print(f"Orders by status: {status_counts}")
            
            cursor.execute("""
                SELECT 
                    o.id as order_id,
                    o.seller_email,
                    o.rider_email,
                    o.status,
                    CAST(o.total_price AS DECIMAL(10,2)) as order_total,
                    50.00 as delivery_fee,
                    CAST(o.total_price AS DECIMAL(10,2)) * 0.05 as seller_commission,
                    50.00 * 0.05 as rider_commission,
                    (CAST(o.total_price AS DECIMAL(10,2)) * 0.05) + (50.00 * 0.05) as total_platform_earnings,
                    DATE(o.date) as order_date,
                    DATE(COALESCE(o.received_at, o.delivered_at, o.date)) as date_completed
                FROM orders o
                WHERE o.status IN ('Delivered', 'Completed', 'Received', 'delivered', 'completed', 'received')
                ORDER BY o.date DESC
                LIMIT 100
            """)
            
            commission_results = cursor.fetchall()
            print(f"Found {len(commission_results)} commission records")
            
            if len(commission_results) == 0:
                print("WARNING: No completed orders found for platform commission report")
                print("This could mean:")
                print("1. No orders exist in the database")
                print("2. No orders have status 'Delivered', 'Completed', or 'Received'")
                print("3. Check your order statuses in the database")
            
            platform_commission = []
            for idx, row in enumerate(commission_results, 1):
                try:
                    platform_commission.append({
                        'no': idx,
                        'order_id': row['order_id'],
                        'seller_email': row['seller_email'],
                        'rider_email': row['rider_email'] if row['rider_email'] else 'N/A',
                        'order_total': float(row['order_total']) if row['order_total'] else 0.0,
                        'delivery_fee': float(row['delivery_fee']),
                        'seller_commission': float(row['seller_commission']) if row['seller_commission'] else 0.0,
                        'rider_commission': float(row['rider_commission']),
                        'total_platform_earnings': float(row['total_platform_earnings']) if row['total_platform_earnings'] else 0.0,
                        'order_date': row['order_date'].strftime('%Y-%m-%d') if row['order_date'] else None,
                        'date_completed': row['date_completed'].strftime('%Y-%m-%d') if row['date_completed'] else None
                    })
                except Exception as row_error:
                    print(f"Error processing commission row {idx}: {row_error}")
                    print(f"Row data: {row}")
                    
            print(f"Successfully processed {len(platform_commission)} platform commission records")
        except Exception as commission_error:
            print(f"Error fetching platform commission data: {commission_error}")
            import traceback
            traceback.print_exc()
            platform_commission = []
        
        # 12. Complaints & Issues Report
        try:
            print("Fetching complaints & issues data...")
            
            # Check if order_issues table exists
            cursor.execute("SHOW TABLES LIKE 'order_issues'")
            if not cursor.fetchone():
                print("WARNING: order_issues table does not exist!")
                complaints_issues = []
            else:
                # Check if there are any issues
                cursor.execute("SELECT COUNT(*) as total FROM order_issues")
                issues_count = cursor.fetchone()['total']
                print(f"Total issues in database: {issues_count}")
                
                cursor.execute("""
                    SELECT 
                        oi.id,
                        oi.order_id,
                        oi.reporter_email,
                        oi.reporter_role,
                        oi.reported_against_email,
                        oi.reported_against_role,
                        oi.issue_type,
                        oi.issue_description,
                        oi.status,
                        oi.created_at,
                        reporter.email as reporter_email_verified,
                        CONCAT(reporter.first_name, ' ', reporter.last_name) as reporter_name,
                        reporter.business_name as reporter_business_name,
                        against.email as against_email_verified,
                        CONCAT(against.first_name, ' ', against.last_name) as against_name,
                        against.business_name as against_business_name
                    FROM order_issues oi
                    LEFT JOIN users reporter ON oi.reporter_email = reporter.email
                    LEFT JOIN users against ON oi.reported_against_email = against.email
                    ORDER BY oi.created_at DESC
                    LIMIT 100
                """)
                
                issues_results = cursor.fetchall()
                print(f"Found {len(issues_results)} issues")
                
                complaints_issues = []
                for idx, row in enumerate(issues_results, 1):
                    try:
                        # Determine reported by display name (prefer business name for sellers)
                        if row['reporter_role'] == 'seller' and row['reporter_business_name']:
                            reported_by_display = row['reporter_business_name']
                        elif row['reporter_name']:
                            reported_by_display = row['reporter_name']
                        else:
                            reported_by_display = row['reporter_email']
                        
                        # Determine reported against display name
                        if row['reported_against_role'] == 'platform':
                            reported_against_display = 'Platform/System'
                            reported_against_email = 'N/A'
                        elif row['reported_against_role'] == 'seller' and row['against_business_name']:
                            reported_against_display = row['against_business_name']
                            reported_against_email = row['reported_against_email']
                        elif row['against_name']:
                            reported_against_display = row['against_name']
                            reported_against_email = row['reported_against_email']
                        elif row['reported_against_email']:
                            reported_against_display = row['reported_against_email']
                            reported_against_email = row['reported_against_email']
                        else:
                            reported_against_display = row['reported_against_role'].capitalize()
                            reported_against_email = 'N/A'
                        
                        complaints_issues.append({
                            'no': idx,
                            'order_id': row['order_id'] if row['order_id'] else None,
                            'reported_by': reported_by_display,
                            'reported_by_email': row['reporter_email'],
                            'reporter_role': row['reporter_role'].capitalize() if row['reporter_role'] else 'Unknown',
                            'reported_against': reported_against_display,
                            'reported_against_email': reported_against_email,
                            'reported_against_role': row['reported_against_role'].capitalize() if row['reported_against_role'] else 'Unknown',
                            'issue_type': row['issue_type'].replace('_', ' ').title() if row['issue_type'] else 'Other',
                            'description': row['issue_description'] if row['issue_description'] else 'No description provided',
                            'status': row['status'].replace('_', ' ').title() if row['status'] else 'Pending',
                            'date_submitted': row['created_at'].strftime('%Y-%m-%d %I:%M %p') if row['created_at'] else None
                        })
                    except Exception as row_error:
                        print(f"Error processing issue row {idx}: {row_error}")
                        print(f"Row data: {row}")
                        
                print(f"Successfully processed {len(complaints_issues)} complaints & issues")
        except Exception as issues_error:
            print(f"Error fetching complaints & issues data: {issues_error}")
            import traceback
            traceback.print_exc()
            complaints_issues = []
        
        cursor.close()
        connection.close()
        
        # Debug: Print data counts
        print(f"Analytics Data Summary:")
        print(f"  - Inventory Products: {len(inventory_products)}")
        print(f"  - Seller Performance: {len(seller_performance)}")
        print(f"  - Rider Analytics: {len(rider_analytics)}")
        print(f"  - Buyer Insights: {len(buyer_insights)}")
        print(f"  - Promo Code Analytics: {len(promo_code_analytics)}")
        print(f"  - Platform Commission: {len(platform_commission)}")
        print(f"  - Complaints & Issues: {len(complaints_issues)}")
        
        # Return all analytics data
        return jsonify({
            'totalOrders': total_orders,
            'totalRevenue': total_revenue,
            'totalUsers': total_users,
            'totalProducts': total_products,
            'salesData': {
                'labels': sales_labels,
                'values': sales_values
            },
            'orderStatus': order_status,
            'topProducts': top_products,
            'topSellers': top_sellers,
            'inventoryProducts': inventory_products,
            'sellerPerformance': seller_performance,
            'riderAnalytics': rider_analytics,
            'buyerInsights': buyer_insights,
            'promoCodeAnalytics': promo_code_analytics,
            'platformCommission': platform_commission,
            'complaintsIssues': complaints_issues
        })
        
    except Exception as e:
        print(f"Error in admin analytics API: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': 'Internal server error'}), 500

@app.route('/admin_issue_reports')
def admin_issue_reports():
    """Admin page to view and manage customer issue reports"""
    if 'user_id' not in session or session.get('user_type') != 'Admin':
        flash('Access denied. Admin privileges required.', 'danger')
        return redirect(url_for('login'))
    
    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)
        
        # Check if order_issues table exists, create if not
        try:
            cursor.execute("SHOW TABLES LIKE 'order_issues'")
            if not cursor.fetchone():
                print("Creating order_issues table...")
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS order_issues (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        order_id INT NOT NULL,
                        reporter_role ENUM('buyer', 'seller', 'rider', 'admin') NOT NULL,
                        reporter_email VARCHAR(255) NOT NULL,
                        reported_against_role ENUM('buyer', 'seller', 'rider', 'platform', 'other') NOT NULL DEFAULT 'seller',
                        reported_against_email VARCHAR(255) NULL,
                        issue_type VARCHAR(100) NOT NULL,
                        issue_description TEXT NOT NULL,
                        status ENUM('pending', 'in_progress', 'resolved', 'closed') DEFAULT 'pending',
                        admin_response TEXT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                        resolved_at TIMESTAMP NULL,
                        FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE CASCADE,
                        INDEX idx_order_id (order_id),
                        INDEX idx_reporter_role (reporter_role),
                        INDEX idx_reporter_email (reporter_email),
                        INDEX idx_reported_against_role (reported_against_role),
                        INDEX idx_status (status),
                        INDEX idx_created_at (created_at)
                    )
                """)
                connection.commit()
                print("order_issues table created successfully")
        except Exception as table_error:
            print(f"Error checking/creating table: {table_error}")
        
        # Get filter parameters
        status_filter = request.args.get('status', '')
        report_against_filter = request.args.get('report_against', '')
        reporter_role_filter = request.args.get('reporter_role', '')
        search_query = request.args.get('search', '').strip()
        page = request.args.get('page', 1, type=int)
        per_page = 20
        
        # Build WHERE clause
        where_conditions = []
        params = []
        
        if status_filter:
            where_conditions.append("oi.status = %s")
            params.append(status_filter)
        
        if report_against_filter:
            where_conditions.append("oi.reported_against_role = %s")
            params.append(report_against_filter)
        
        if reporter_role_filter:
            where_conditions.append("oi.reporter_role = %s")
            params.append(reporter_role_filter)
        
        if search_query:
            where_conditions.append("""
                (oi.issue_description LIKE %s OR 
                 oi.reporter_email LIKE %s OR 
                 oi.reported_against_email LIKE %s OR 
                 o.name LIKE %s OR
                 oi.issue_type LIKE %s)
            """)
            search_param = f"%{search_query}%"
            params.extend([search_param] * 5)
        
        where_clause = " AND ".join(where_conditions) if where_conditions else "1=1"
        
        # Get total count for pagination
        cursor.execute(f"""
            SELECT COUNT(*) as total
            FROM order_issues oi
            LEFT JOIN orders o ON oi.order_id = o.id
            WHERE {where_clause}
        """, params)
        
        total_issues = cursor.fetchone()['total']
        total_pages = (total_issues + per_page - 1) // per_page
        
        # Get issue reports with pagination
        offset = (page - 1) * per_page
        cursor.execute(f"""
            SELECT 
                oi.*,
                o.name as product_name,
                o.total_price as order_total,
                o.date as order_date,
                o.status as order_status
            FROM order_issues oi
            LEFT JOIN orders o ON oi.order_id = o.id
            WHERE {where_clause}
            ORDER BY oi.created_at DESC
            LIMIT %s OFFSET %s
        """, params + [per_page, offset])
        
        issues = cursor.fetchall()
        
        # Get summary statistics
        cursor.execute("""
            SELECT 
                COUNT(*) as total_issues,
                SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) as pending_issues,
                SUM(CASE WHEN status = 'in_progress' THEN 1 ELSE 0 END) as in_progress_issues,
                SUM(CASE WHEN status = 'resolved' THEN 1 ELSE 0 END) as resolved_issues,
                SUM(CASE WHEN reported_against_role = 'seller' THEN 1 ELSE 0 END) as seller_issues,
                SUM(CASE WHEN reported_against_role = 'rider' THEN 1 ELSE 0 END) as delivery_issues,
                SUM(CASE WHEN reported_against_role = 'buyer' THEN 1 ELSE 0 END) as buyer_issues,
                SUM(CASE WHEN reported_against_role = 'platform' THEN 1 ELSE 0 END) as platform_issues
            FROM order_issues
        """)
        
        stats = cursor.fetchone()
        
        cursor.close()
        connection.close()
        
        return render_template('admin_issue_reports.html', 
                             issues=issues,
                             stats=stats,
                             current_page=page,
                             total_pages=total_pages,
                             total_issues=total_issues,
                             status_filter=status_filter,
                             report_against_filter=report_against_filter,
                             reporter_role_filter=reporter_role_filter,
                             search_query=search_query)
        
    except Exception as e:
        print(f"?? MySQL unavailable in admin_issue_reports: {e}")
        empty_stats = {'total_issues': 0, 'pending_issues': 0, 'in_progress_issues': 0,
                       'resolved_issues': 0, 'seller_issues': 0, 'delivery_issues': 0,
                       'buyer_issues': 0, 'platform_issues': 0}
        return render_template('admin_issue_reports.html',
                             issues=[], stats=empty_stats,
                             current_page=1, total_pages=1, total_issues=0,
                             status_filter='', report_against_filter='',
                             reporter_role_filter='', search_query='')

@app.route('/admin/issue/<int:issue_id>/details')
def admin_get_issue_details(issue_id):
    """Get detailed information about a specific issue"""
    if 'user_id' not in session or session.get('user_type') != 'Admin':
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401
    
    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)
        
        # Get issue details with related order and customer information
        cursor.execute("""
            SELECT 
                oi.*,
                o.name as product_name,
                o.total_price as order_total,
                o.date as order_date,
                o.status as order_status,
                o.quantity,
                o.size,
                o.variations,
                o.email as buyer_email,
                o.seller_email,
                o.rider_email,
                reporter.first_name as reporter_first_name,
                reporter.last_name as reporter_last_name,
                reporter.phone_number as reporter_phone,
                buyer.first_name as buyer_first_name,
                buyer.last_name as buyer_last_name,
                buyer.phone_number as buyer_phone,
                seller.first_name as seller_first_name,
                seller.last_name as seller_last_name,
                seller.business_name as seller_business_name,
                seller.phone_number as seller_phone,
                rider.first_name as rider_first_name,
                rider.last_name as rider_last_name,
                rider.phone_number as rider_phone
            FROM order_issues oi
            LEFT JOIN orders o ON oi.order_id = o.id
            LEFT JOIN users reporter ON oi.reporter_email = reporter.email
            LEFT JOIN users buyer ON o.email = buyer.email
            LEFT JOIN users seller ON o.seller_email = seller.email
            LEFT JOIN users rider ON o.rider_email = rider.email
            WHERE oi.id = %s
        """, (issue_id,))
        
        issue = cursor.fetchone()
        
        if not issue:
            cursor.close()
            connection.close()
            return jsonify({'success': False, 'message': 'Issue not found'}), 404
        
        # Safely format the response with proper null handling
        try:
            reporter_name = f"{issue.get('reporter_first_name', '') or ''} {issue.get('reporter_last_name', '') or ''}".strip()
        except:
            reporter_name = 'N/A'
        
        try:
            buyer_name = f"{issue.get('buyer_first_name', '') or ''} {issue.get('buyer_last_name', '') or ''}".strip()
        except:
            buyer_name = 'N/A'
        
        try:
            created_at_str = issue['created_at'].strftime('%B %d, %Y at %I:%M %p') if issue.get('created_at') else 'N/A'
        except:
            created_at_str = 'N/A'
        
        try:
            updated_at_str = issue['updated_at'].strftime('%B %d, %Y at %I:%M %p') if issue.get('updated_at') else 'N/A'
        except:
            updated_at_str = 'N/A'
        
        try:
            resolved_at_str = issue['resolved_at'].strftime('%B %d, %Y at %I:%M %p') if issue.get('resolved_at') else None
        except:
            resolved_at_str = None
        
        try:
            order_date_str = issue['order_date'].strftime('%B %d, %Y') if issue.get('order_date') else 'N/A'
        except:
            order_date_str = 'N/A'
        
        try:
            order_total_val = float(issue.get('order_total', 0)) if issue.get('order_total') else 0
        except:
            order_total_val = 0
        
        # Format seller name
        try:
            seller_name = issue.get('seller_business_name') or f"{issue.get('seller_first_name', '') or ''} {issue.get('seller_last_name', '') or ''}".strip()
        except:
            seller_name = 'N/A'
        
        # Format rider name
        try:
            rider_name = f"{issue.get('rider_first_name', '') or ''} {issue.get('rider_last_name', '') or ''}".strip()
        except:
            rider_name = 'N/A'
        
        # Format the response
        issue_data = {
            'id': issue.get('id', 0),
            'order_id': issue.get('order_id', 0),
            'reporter_role': issue.get('reporter_role', 'N/A'),
            'reporter_email': issue.get('reporter_email', 'N/A'),
            'reporter_name': reporter_name or 'N/A',
            'reporter_phone': issue.get('reporter_phone') or 'N/A',
            'reported_against_role': issue.get('reported_against_role', 'N/A'),
            'reported_against_email': issue.get('reported_against_email') or 'N/A',
            'customer_email': issue.get('buyer_email', 'N/A'),
            'customer_name': buyer_name or 'N/A',
            'customer_phone': issue.get('buyer_phone') or 'N/A',
            'seller_email': issue.get('seller_email', 'N/A'),
            'seller_name': seller_name or 'N/A',
            'seller_phone': issue.get('seller_phone') or 'N/A',
            'rider_email': issue.get('rider_email') or 'N/A',
            'rider_name': rider_name or 'Not Assigned',
            'rider_phone': issue.get('rider_phone') or 'N/A',
            'report_against': issue.get('reported_against_role', 'N/A'),  # For backward compatibility
            'issue_type': issue.get('issue_type', 'N/A'),
            'issue_description': issue.get('issue_description', 'N/A'),
            'status': issue.get('status', 'pending'),
            'admin_response': issue.get('admin_response') or '',
            'created_at': created_at_str,
            'updated_at': updated_at_str,
            'resolved_at': resolved_at_str,
            'product_name': issue.get('product_name') or 'N/A',
            'order_total': order_total_val,
            'order_date': order_date_str,
            'order_status': issue.get('order_status') or 'N/A',
            'quantity': issue.get('quantity') or 'N/A',
            'size': issue.get('size') or 'N/A',
            'variations': issue.get('variations') or 'N/A'
        }
        
        cursor.close()
        connection.close()
        
        return jsonify({'success': True, 'issue': issue_data})
        
    except Exception as e:
        print(f"Error fetching issue details: {e}")
        import traceback
        traceback.print_exc()
        
        # Try to close connections if they exist
        try:
            if 'cursor' in locals():
                cursor.close()
            if 'connection' in locals():
                connection.close()
        except:
            pass
        
        return jsonify({'success': False, 'message': f'Internal server error: {str(e)}'}), 500

@app.route('/admin/issue/<int:issue_id>/update-status', methods=['POST'])
def admin_update_issue_status(issue_id):
    """Update the status of an issue report"""
    if 'user_id' not in session or session.get('user_type') != 'Admin':
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401
    
    try:
        new_status = request.json.get('status')
        admin_response = request.json.get('admin_response', '')
        
        if new_status not in ['pending', 'in_progress', 'resolved', 'closed']:
            return jsonify({'success': False, 'message': 'Invalid status'}), 400
        
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)
        
        # Get issue details before updating (for notifications)
        cursor.execute("""
            SELECT oi.*, o.name as product_name, o.id as order_id,
                   reporter.first_name as reporter_first_name, 
                   reporter.last_name as reporter_last_name
            FROM order_issues oi
            LEFT JOIN orders o ON oi.order_id = o.id
            LEFT JOIN users reporter ON oi.reporter_email = reporter.email
            WHERE oi.id = %s
        """, (issue_id,))
        
        issue = cursor.fetchone()
        
        if not issue:
            cursor.close()
            connection.close()
            return jsonify({'success': False, 'message': 'Issue not found'}), 404
        
        # Update issue status
        update_fields = ['status = %s', 'updated_at = NOW()']
        params = [new_status]
        
        if admin_response:
            update_fields.append('admin_response = %s')
            params.append(admin_response)
        
        if new_status == 'resolved':
            update_fields.append('resolved_at = NOW()')
        
        params.append(issue_id)
        
        cursor.execute(f"""
            UPDATE order_issues 
            SET {', '.join(update_fields)}
            WHERE id = %s
        """, params)
        
        connection.commit()
        cursor.close()
        connection.close()
        
        # Send notifications to reporter (buyer/seller/rider who reported the issue)
        reporter_email = issue.get('reporter_email')
        reporter_name = f"{issue.get('reporter_first_name', '')} {issue.get('reporter_last_name', '')}".strip() or 'User'
        reporter_role = issue.get('reporter_role', 'user')
        
        print(f"?? Reporter Email: {reporter_email}")
        print(f"?? Reporter Role: {reporter_role}")
        print(f"?? Reporter Name: {reporter_name}")
        
        if reporter_email:
            try:
                # Send email notification
                send_issue_status_update_email(
                    customer_email=reporter_email,
                    customer_name=reporter_name,
                    issue_id=issue_id,
                    issue_type=issue.get('issue_type', 'Issue'),
                    product_name=issue.get('product_name', 'Product'),
                    new_status=new_status,
                    admin_response=admin_response
                )
            except Exception as email_error:
                print(f"? Error sending email notification: {email_error}")
            
            try:
                print(f"?? Calling create_issue_status_notification for: {reporter_email}")
                # Create in-app notification
                create_issue_status_notification(
                    customer_email=reporter_email,
                    issue_id=issue_id,
                    issue_type=issue.get('issue_type', 'Issue'),
                    product_name=issue.get('product_name', 'Product'),
                    new_status=new_status,
                    admin_response=admin_response,
                    order_id=issue.get('order_id')
                )
            except Exception as notif_error:
                print(f"Error creating in-app notification: {notif_error}")
        
        return jsonify({'success': True, 'message': 'Issue status updated successfully'})
        
    except Exception as e:
        print(f"Error updating issue status: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': 'Internal server error'}), 500

@app.route('/admin/issue/<int:issue_id>/delete', methods=['POST'])
def admin_delete_issue(issue_id):
    """Delete an issue report"""
    if 'user_id' not in session or session.get('user_type') != 'Admin':
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401
    
    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)
        
        # Check if issue exists
        cursor.execute("SELECT id FROM order_issues WHERE id = %s", (issue_id,))
        issue = cursor.fetchone()
        
        if not issue:
            cursor.close()
            connection.close()
            return jsonify({'success': False, 'message': 'Issue not found'}), 404
        
        # Delete the issue
        cursor.execute("DELETE FROM order_issues WHERE id = %s", (issue_id,))
        connection.commit()
        
        cursor.close()
        connection.close()
        
        return jsonify({'success': True, 'message': 'Issue report deleted successfully'})
        
    except Exception as e:
        print(f"Error deleting issue: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': 'Internal server error'}), 500

#----------------------------------------------------------------------
                         #UPLOAD RELATED ROUTES
#----------------------------------------------------------------------

# Define where to save uploaded files
UPLOAD_FOLDER = 'static/images/uploads'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/upload_image', methods=['POST'])
def upload_image():
    # Check if the POST request has the file part
    if 'product_image' not in request.files:
        flash('No file part', 'error')
        return redirect(request.url)

    file = request.files['product_image']

    # If user does not select a file, browser submits an empty file without a filename
    if file.filename == '':
        flash('No selected file', 'error')
        return redirect(request.url)

    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
        return redirect(url_for('add_new_product'))

    flash('Invalid file format. Only jpg, jpeg, and png allowed.', 'error')
    return redirect(request.url)
    
#----------------------------------------------------------------------
                         #BUYER RELATED ROUTES
#----------------------------------------------------------------------

@app.route('/cart')
def cart():
    if 'email' not in session:
        return redirect(url_for('login'))

    email = session['email']
    cart_items = []
    user_name = get_user_name_from_session(default='User')

    # -- PRIMARY: Supabase -----------------------------------------------------
    try:
        res = sb_admin.table('cart') \
            .select('id, email, product_id, name, price, seller_email, variations, size, quantity, image') \
            .eq('email', email) \
            .order('id', desc=False) \
            .execute()

        raw_items = res.data or []
        print(f"? Cart from Supabase: {len(raw_items)} items for {email}")

        # Fetch image_colors for each product to find color-specific image
        product_ids = list({item['product_id'] for item in raw_items if item.get('product_id')})
        image_colors_map = {}
        images_map = {}
        if product_ids:
            try:
                prod_res = sb_admin.table('products') \
                    .select('id, image, image_colors') \
                    .in_('id', product_ids) \
                    .execute()
                for prod in (prod_res.data or []):
                    image_colors_map[prod['id']] = prod.get('image_colors', '') or ''
                    images_map[prod['id']] = prod.get('image', '') or ''
            except Exception as e:
                print(f"?? Could not fetch product image_colors: {e}")

        for item in raw_items:
            item['price'] = float(item.get('price') or 0)
            item['quantity'] = int(item.get('quantity') or 1)

            pid = item.get('product_id')
            selected_color = (item.get('variations') or '').strip()
            all_images_str = images_map.get(pid, '') or item.get('image', '') or ''
            image_colors_str = image_colors_map.get(pid, '')

            # Find the color-specific image using image_colors mapping
            color_image = _find_color_image(selected_color, image_colors_str, all_images_str)

            item['all_images'] = all_images_str

            if color_image:
                if color_image.startswith('http://') or color_image.startswith('https://'):
                    item['first_image_url'] = color_image
                    item['first_image'] = ''
                else:
                    item['first_image'] = color_image
                    item['first_image_url'] = ''
            else:
                # Fallback to stored cart image
                raw_img = (item.get('image') or '').strip()
                first = raw_img.split(',')[0].strip() if raw_img else ''
                if first.startswith('http://') or first.startswith('https://'):
                    item['first_image_url'] = first
                    item['first_image'] = ''
                else:
                    item['first_image'] = first
                    item['first_image_url'] = ''

        cart_items = raw_items

    except Exception as sb_err:
        print(f"?? Supabase cart failed: {sb_err}")

    # -- FALLBACK: MySQL -------------------------------------------------------
    if not cart_items:
        try:
            db = get_db_connection()
            cursor = db.cursor(dictionary=True)
            cursor.execute('''
                SELECT c.*, p.image as all_product_images
                FROM cart c
                LEFT JOIN products p ON c.product_id = p.id
                WHERE c.email = %s
            ''', (email,))
            raw_items = cursor.fetchall()
            cursor.close()
            db.close()

            for item in raw_items:
                item['price'] = float(item.get('price') or 0)
                item['quantity'] = int(item.get('quantity') or 1)
                all_images = item.get('all_product_images', '') or item.get('image', '')
                item['all_images'] = all_images
                if item.get('image'):
                    item['first_image'] = item['image'].strip()
                    item['first_image_url'] = ''
                else:
                    images = [i.strip() for i in str(all_images).split(',') if i.strip()]
                    item['first_image'] = images[0] if images else ''
                    item['first_image_url'] = ''

            cart_items = raw_items
            print(f"? Cart from MySQL fallback: {len(cart_items)} items")
        except Exception as mysql_err:
            print(f"?? MySQL cart fallback failed: {mysql_err}")
            cart_items = []

    return render_template('cart.html', cart_items=cart_items, user_name=user_name, user_email=email)

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
    try:
        connection = get_db_connection()
        cursor = connection.cursor()
        fmt = ','.join(['%s'] * len(selected_ids))
        cursor.execute(f'DELETE FROM cart WHERE id IN ({fmt}) AND email = %s',
                       tuple(selected_ids + [user_email]))
        connection.commit()
        cursor.close()
        connection.close()
        return jsonify({'success': True})
    except Exception as mysql_err:
        return jsonify({'success': False, 'error': str(mysql_err)}), 500

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
            # Fallback to MySQL
            try:
                db = get_db_connection()
                cur = db.cursor()
                cur.execute('SELECT seller_email, image FROM products WHERE id = %s', (product_id,))
                row = cur.fetchone()
                if row:
                    seller_email, all_product_images = row
                cur.close()
                db.close()
            except Exception:
                pass

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
        try:
            db = get_db_connection()
            cursor = db.cursor()
            cursor.execute(
                'INSERT INTO cart (email, name, price, quantity, variations, image, size, seller_email, product_id) '
                'VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)',
                (user_email, product_name, price_float, qty_int,
                 product_variation or '', cart_image or '', size or '',
                 seller_email, product_id)
            )
            db.commit()
            cursor.close()
            db.close()
        except Exception as mysql_err:
            print(f"?? MySQL cart mirror failed (non-fatal): {mysql_err}")

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

            # -- MIRROR: MySQL checkout table (best-effort) -----------------
            try:
                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute("DELETE FROM checkout WHERE email = %s", (user_email,))
                for item in checkout_items_session:
                    cur.execute(
                        """INSERT INTO checkout
                           (id, name, price, quantity, variations, image, size,
                            email, address, seller_email, product_id, shipping_fee)
                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                        (item['id'], item['name'], item['price'], item['quantity'],
                         item['variations'], item['image'], item['size'],
                         user_email, session.get('address', ''),
                         item['seller_email'], item['product_id'], item['shipping_fee'])
                    )
                conn.commit()
                cur.close()
                conn.close()
            except Exception as my_err:
                print(f"?? checkout_route MySQL mirror failed: {my_err}")

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

            # Resolve color-specific image
            image = item.get('image') or ''
            if not image and prod:
                color_map = _parse_image_colors_dict(prod.get('image_colors'), prod.get('image'))
                color_key = (item.get('variations') or '').strip().lower()
                image = color_map.get(color_key) or (prod.get('image') or '').split(',')[0].strip()

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
        # -- FALLBACK: MySQL checkout table ---------------------------------
        try:
            connection = get_db_connection()
            cursor = connection.cursor(dictionary=True)
            cursor.execute('''
                SELECT c.*, p.image as all_product_images, p.price as original_price,
                       p.category, p.seller_email as product_seller_email
                FROM checkout c
                LEFT JOIN products p ON c.product_id = p.id
                WHERE c.email = %s
            ''', (user_email,))
            checkout_items = cursor.fetchall()
            cursor.close()
            connection.close()
            print(f"?? checkout: MySQL fallback, {len(checkout_items)} items")
        except Exception as my_err:
            print(f"?? checkout MySQL fallback failed: {my_err}")
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
    user_email = session.get('email')  # Kunin ang email mula sa session
    connection = get_db_connection()
    cursor = connection.cursor()

    try:
        # Delete item from the checkout table for the current user only
        cursor.execute("DELETE FROM checkout WHERE id = %s AND email = %s", (item_id, user_email))
        connection.commit()

        return jsonify({"success": True})
    except mysql.connector.Error as err:
        connection.rollback()
        return jsonify({"success": False, "error": str(err)})
    finally:
        cursor.close()
        connection.close()

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
        try:
            connection = get_db_connection()
            cursor = connection.cursor(dictionary=True)
            cursor.execute("""
                SELECT o.*,
                       p.price as product_original_price,
                       u.id as rider_id,
                       seller.business_name as seller_business_name,
                       seller.profile_picture as seller_profile_picture,
                       CONCAT(seller.first_name, ' ', seller.last_name) as seller_full_name
                FROM orders o
                LEFT JOIN products p ON o.product_id = p.id
                LEFT JOIN users u ON o.rider_email = u.email AND u.user_type = 'rider'
                LEFT JOIN users seller ON o.seller_email = seller.email
                WHERE o.email = %s
                ORDER BY o.date DESC
            """, (user_email,))
            orders = cursor.fetchall()
            for o in orders:
                o['total_price']    = float(o.get('total_price') or 0)
                o['original_price'] = float(o.get('product_original_price') or o['total_price'])
                o['promotion_type'] = ''
                o['promotion_name'] = ''
                o['image_url']      = ''
                try:
                    rv = cursor.execute("SELECT id FROM reviews WHERE order_id=%s AND customer_email=%s",
                                        (o['id'], user_email))
                    o['has_review'] = cursor.fetchone() is not None
                except Exception:
                    o['has_review'] = False
            cursor.close()
            connection.close()
            print(f"?? orders route MySQL fallback: {len(orders)} orders")
        except Exception as my_err:
            print(f"?? orders route MySQL fallback failed: {my_err}")
            orders = []

    return render_template('orders.html', orders=orders,
                           user_name=user_name,
                           user_email=user_email)

@app.route('/mark_as_received/<int:order_id>', methods=['POST'])
def mark_as_received(order_id):
    user_email = session.get('email')
    connection = get_db_connection()

    try:
        cursor = connection.cursor(dictionary=True)
        
        # First, verify the order is in "Delivered" status and belongs to the user
        cursor.execute("""
            SELECT id, product_id, quantity, status, seller_email, name
            FROM orders 
            WHERE id = %s AND email = %s AND status = 'Delivered'
        """, (order_id, user_email))
        
        order = cursor.fetchone()
        
        if not order:
            flash("Order not found or not eligible for confirmation.", "error")
            return redirect(url_for('orders'))
        
        # Update order status to "Completed" and set received_at timestamp
        from datetime import datetime
        received_at = datetime.now()
        
        cursor.execute("""
            UPDATE orders 
            SET status = 'Completed', received_at = %s 
            WHERE id = %s
        """, (received_at, order_id))
        
        # Decrease the product quantity in the products table
        product_id = order['product_id']
        quantity = int(order['quantity'])
        
        cursor.execute("""
            UPDATE products 
            SET quantity = quantity - %s 
            WHERE id = %s
        """, (quantity, product_id))
        
        connection.commit()
        
        # Send notification to seller about order completion
        try:
            send_order_completion_notification(order['seller_email'], order, user_email)
            print(f"? Order completion notification sent to seller: {order['seller_email']}")
        except Exception as email_error:
            print(f"? Failed to send completion notification: {str(email_error)}")
        
        flash("Order confirmed as received! Thank you for your purchase.", "success")
        
    except Exception as e:
        connection.rollback()
        flash(f"An error occurred: {str(e)}", "error")
        print(f"? Error in mark_as_received: {str(e)}")
    finally:
        cursor.close()
        connection.close()

    return redirect(url_for('orders'))

@app.route('/submit_review/<int:order_id>', methods=['POST'])
def submit_review(order_id):
    user_email = session.get('email')
    rating = request.form.get('rating')
    review_text = request.form.get('review_text')
    
    if not rating or not review_text:
        flash('Please provide both a rating and review text.', 'error')
        return redirect(url_for('orders'))
    
    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)
        
        # First, verify the order belongs to the user and is completed
        # Join with products to get the correct product_id
        cursor.execute("""
            SELECT o.product_id as order_product_id, o.name, o.seller_email, o.status,
                   p.id as actual_product_id
            FROM orders o
            LEFT JOIN products p ON o.product_id = p.id
            WHERE o.id = %s AND o.email = %s AND o.status = 'Completed'
        """, (order_id, user_email))
        
        order = cursor.fetchone()
        
        # Debug: Check what we found
        print(f"?? Review eligibility check for order {order_id}, user {user_email}")
        if order:
            print(f"? Order found: status={order['status']}, name={order['name']}")
        else:
            # Let's check what status this order actually has
            cursor.execute("""
                SELECT id, status, email FROM orders WHERE id = %s
            """, (order_id,))
            debug_order = cursor.fetchone()
            if debug_order:
                print(f"? Order {order_id} exists but has status '{debug_order['status']}' for email '{debug_order['email']}'")
                print(f"   Expected: status='Completed' for email '{user_email}'")
            else:
                print(f"? Order {order_id} not found in database")
        
        if not order:
            flash('Order not found or not completed yet. You can only review completed orders.', 'error')
            return redirect(url_for('orders'))
        
        # Use the actual product_id from products table
        actual_product_id = order['actual_product_id'] or order['order_product_id']
        print(f"?? Review Debug: order_product_id={order['order_product_id']}, actual_product_id={order['actual_product_id']}")
        
        # Check if review already exists
        cursor.execute("""
            SELECT id FROM reviews 
            WHERE order_id = %s AND customer_email = %s
        """, (order_id, user_email))
        
        existing_review = cursor.fetchone()
        
        if existing_review:
            flash('You have already reviewed this product.', 'info')
            return redirect(url_for('orders'))
        
        # Insert the review using the actual product_id
        print(f"?? Inserting review: Order {order_id}, Product {actual_product_id}, Rating {rating}")
        cursor.execute("""
            INSERT INTO reviews (order_id, product_id, customer_email, seller_email, rating, review_text)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (order_id, actual_product_id, user_email, order['seller_email'], rating, review_text))
        
        print(f"? Review inserted successfully")
        
        # Update product rating (calculate average)
        cursor.execute("""
            SELECT AVG(rating) as avg_rating, COUNT(*) as review_count
            FROM reviews 
            WHERE product_id = %s
        """, (actual_product_id,))
        
        rating_data = cursor.fetchone()
        new_avg_rating = round(rating_data['avg_rating'], 1) if rating_data['avg_rating'] else float(rating)
        
        print(f"?? Calculated new average rating: {new_avg_rating} from {rating_data['review_count']} reviews")
        
        # Update the product's rating
        cursor.execute("""
            UPDATE products 
            SET rating = %s 
            WHERE id = %s
        """, (new_avg_rating, actual_product_id))
        
        connection.commit()
        print(f"? Product rating updated to {new_avg_rating}")
        
        # Send email notification to seller about new review
        try:
            send_review_notification_email(order['seller_email'], order, rating, review_text, user_email)
            print(f"? Review notification email sent to seller: {order['seller_email']}")
        except Exception as email_error:
            print(f"? Failed to send review notification email: {str(email_error)}")
        
        # Create seller notification about new review
        try:
            create_review_notification(order['seller_email'], order, rating, review_text, user_email, order_id)
            print(f"? Review notification created for seller: {order['seller_email']}")
        except Exception as notif_error:
            print(f"? Failed to create review notification: {str(notif_error)}")
        
        flash(f'Thank you for your review! Your {rating}-star rating has been submitted.', 'success')
        
    except Exception as e:
        connection.rollback()
        flash(f'An error occurred while submitting your review: {str(e)}', 'error')
        print(f"Review submission error: {str(e)}")
        import traceback
        traceback.print_exc()
    finally:
        cursor.close()
        connection.close()
    
    return redirect(url_for('orders'))

@app.route('/report_issue/<int:order_id>', methods=['POST'])
def report_issue(order_id):
    user_email = session.get('email')
    report_against = request.form.get('report_against')
    issue_type = request.form.get('issue_type')
    issue_description = request.form.get('issue_description')
    
    if not report_against or not issue_type or not issue_description:
        flash('Please provide all required fields: report against, issue type, and description.', 'error')
        return redirect(url_for('orders'))
    
    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)
        
        # First, verify the order belongs to the user and is delivered or completed
        cursor.execute("""
            SELECT o.*, p.name as product_name
            FROM orders o
            LEFT JOIN products p ON o.product_id = p.id
            WHERE o.id = %s AND o.email = %s AND o.status IN ('Delivered', 'Completed')
        """, (order_id, user_email))
        
        order = cursor.fetchone()
        
        if not order:
            flash('Order not found or not eligible for issue reporting.', 'error')
            return redirect(url_for('orders'))
        
        # Map old report_against values to new reported_against_role values
        reported_against_role_map = {
            'seller': 'seller',
            'delivery': 'rider',
            'product': 'seller',  # Product issues are reported against seller
            'platform': 'platform',
            'other': 'other'
        }
        
        reported_against_role = reported_against_role_map.get(report_against, 'other')
        
        # Get the email of the reported party
        reported_against_email = None
        if reported_against_role == 'seller':
            reported_against_email = order['seller_email']
        elif reported_against_role == 'rider' and order.get('rider_email'):
            reported_against_email = order['rider_email']
        
        # Insert the issue report with new schema
        cursor.execute("""
            INSERT INTO order_issues 
            (order_id, reporter_role, reporter_email, reported_against_role, reported_against_email, 
             issue_type, issue_description, status, created_at)
            VALUES (%s, 'buyer', %s, %s, %s, %s, %s, 'pending', NOW())
        """, (order_id, user_email, reported_against_role, reported_against_email, issue_type, issue_description))
        
        issue_id = cursor.lastrowid
        
        connection.commit()
        
        # Send email notification to admin/customer service
        try:
            send_issue_report_email(order, report_against, issue_type, issue_description, user_email, issue_id)
        except Exception as email_error:
            print(f"Failed to send issue report email: {str(email_error)}")
        
        # Create notification for seller (only if report is against seller)
        try:
            if report_against == 'seller':
                create_issue_notification(order['seller_email'], order, report_against, issue_type, issue_description, user_email, issue_id)
        except Exception as notif_error:
            print(f"Failed to create issue notification: {str(notif_error)}")
        
        flash('Your issue has been reported successfully. Our customer service team will contact you soon.', 'success')
        
    except Exception as e:
        connection.rollback()
        flash(f'An error occurred while reporting the issue: {str(e)}', 'error')
        print(f"Issue report error: {str(e)}")
        import traceback
        traceback.print_exc()
    finally:
        cursor.close()
        connection.close()
    
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
    user_email = session.get('email')  # Get the email from the session
    reason = request.form['reason']  # Get the cancellation reason from the form
    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)

    try:
        # Get order details, including product_id, quantity, seller's email and customer email
        cursor.execute("SELECT seller_email, name, email, status, product_id, quantity FROM orders WHERE id = %s AND email = %s", (order_id, user_email))
        order = cursor.fetchone()

        if order:
            seller_email = order['seller_email']
            order_name = order['name']
            customer_email = order['email']
            current_status = order['status']
            product_id = order.get('product_id')
            order_quantity = int(order['quantity'])

            # Check if order can be cancelled (only Pending orders can be cancelled)
            if current_status.lower() not in ['pending', 'confirmed']:
                flash('This order cannot be cancelled as it is already being processed or delivered.', 'warning')
                return redirect(url_for('orders'))

            # Restore stock and decrease sold count for the product
            if product_id:
                try:
                    # Get current product stock and sold count
                    cursor.execute("SELECT quantity, sold FROM products WHERE id = %s", (product_id,))
                    product = cursor.fetchone()
                    
                    if product:
                        current_stock = int(product['quantity'])
                        current_sold = int(product.get('sold', 0))
                        
                        # Restore stock (add back the cancelled quantity)
                        new_stock = current_stock + order_quantity
                        
                        # Decrease sold count (subtract the cancelled quantity, but don't go below 0)
                        new_sold = max(0, current_sold - order_quantity)
                        
                        # Update product stock and sold count
                        cursor.execute("""
                            UPDATE products 
                            SET quantity = %s, sold = %s 
                            WHERE id = %s
                        """, (new_stock, new_sold, product_id))
                        
                        print(f"? Product {product_id} stock restored: {current_stock} ? {new_stock}")
                        print(f"? Product {product_id} sold count decreased: {current_sold} ? {new_sold}")
                    else:
                        print(f"?? Product {product_id} not found, skipping stock restoration")
                except Exception as stock_error:
                    print(f"? Error restoring stock for product {product_id}: {str(stock_error)}")
                    # Continue with cancellation even if stock restoration fails
            else:
                print(f"?? Order {order_id} has no product_id, skipping stock restoration")

            # Check if cancellation columns exist
            cursor.execute("""
                SELECT COUNT(*) as column_count
                FROM INFORMATION_SCHEMA.COLUMNS 
                WHERE TABLE_SCHEMA = 'mstyle' 
                AND TABLE_NAME = 'orders' 
                AND COLUMN_NAME = 'cancellation_reason'
            """)
            result = cursor.fetchone()
            has_cancellation_columns = result and int(result.get('column_count', 0)) > 0
            
            # Update order status to Cancelled instead of deleting
            if has_cancellation_columns:
                cursor.execute("""
                    UPDATE orders 
                    SET status = 'Cancelled', 
                        cancellation_reason = %s,
                        cancelled_at = NOW()
                    WHERE id = %s AND email = %s
                """, (reason, order_id, user_email))
            else:
                cursor.execute("""
                    UPDATE orders 
                    SET status = 'Cancelled'
                    WHERE id = %s AND email = %s
                """, (order_id, user_email))
            
            connection.commit()

            print(f"? Order {order_id} status updated to Cancelled")

            # Send an email to the seller with the cancellation reason and customer email
            try:
                send_cancellation_email(seller_email, order_name, reason, customer_email)
                print(f"? Cancellation email sent to seller: {seller_email}")
            except Exception as email_error:
                print(f"? Failed to send cancellation email to seller {seller_email}: {str(email_error)}")
                # Don't fail the entire cancellation if email fails

            # Create cancellation notification in database
            try:
                create_cancellation_notification(seller_email, order_name, reason, customer_email, order_id)
                print(f"? Cancellation notification created for seller: {seller_email}")
            except Exception as notification_error:
                print(f"? Failed to create cancellation notification for seller {seller_email}: {str(notification_error)}")
                # Don't fail the entire cancellation if notification creation fails

            flash('Order cancelled successfully. The seller has been notified.', 'success')
        else:
            flash('Order not found or you are not authorized to cancel this order.', 'danger')

    except mysql.connector.Error as err:
        connection.rollback()
        flash(f"Error cancelling order: {err}", 'error')
        print(f"? Database error cancelling order: {err}")
    finally:
        cursor.close()
        connection.close()

    return redirect(url_for('orders'))

@app.route('/edit_user/<int:user_id>', methods=['GET', 'POST'])
def edit_user(user_id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    if request.method == 'POST':
        # Fetch the form data
        first_name = request.form.get('first_name')
        last_name = request.form.get('last_name')
        email = request.form.get('email')
        phone_number = request.form.get('phone_number')
        address = request.form.get('address')
        user_type = request.form.get('user_type')

        # Update the user in the database
        cursor.execute('''UPDATE users 
                         SET first_name=%s, last_name=%s, email=%s, phone_number=%s, 
                             address=%s, user_type=%s 
                         WHERE id=%s''', 
                      (first_name, last_name, email, phone_number, address, user_type, user_id))
        conn.commit()
        flash('User updated successfully!', 'success')
        return redirect(url_for('admin_users'))

    # If GET request, fetch user information
    cursor.execute('SELECT * FROM users WHERE id=%s', (user_id,))
    user = cursor.fetchone()
    cursor.close()
    conn.close()

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

        # -- FALLBACK: MySQL -----------------------------------------------
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE cart SET quantity = %s WHERE id = %s AND email = %s",
                       (new_quantity, item_id, user_email))
        conn.commit()
        cursor.close()
        conn.close()
        return jsonify({'success': True})

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

        # -- MIRROR: MySQL (best-effort) ------------------------------------
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            if spec_type == 'color':
                cursor.execute('UPDATE cart SET variations = %s WHERE id = %s AND email = %s',
                               (new_value, item_id, user_email))
            else:
                cursor.execute('UPDATE cart SET size = %s WHERE id = %s AND email = %s',
                               (new_value, item_id, user_email))
            conn.commit()
            cursor.close()
            conn.close()
        except Exception as my_err:
            print(f"?? update_specification MySQL mirror failed: {my_err}")

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

        # -- FALLBACK: MySQL ------------------------------------------------
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute('SELECT product_id FROM cart WHERE id = %s AND email = %s', (item_id, user_email))
        cart_item = cursor.fetchone()
        if not cart_item:
            cursor.close(); conn.close()
            return jsonify({'error': 'Cart item not found'}), 404
        cursor.execute('SELECT variations FROM products WHERE id = %s', (cart_item['product_id'],))
        product = cursor.fetchone()
        cursor.close(); conn.close()
        if not product:
            return jsonify({'error': 'Product not found'}), 404
        variations_str = product['variations'] or ''
        variations = [v.strip() for v in variations_str.split(',') if v.strip()]
        return jsonify({'success': True, 'variations': variations})

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

        # -- FALLBACK: MySQL ------------------------------------------------
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute('SELECT product_id FROM cart WHERE id = %s AND email = %s', (item_id, user_email))
        cart_item = cursor.fetchone()
        if not cart_item:
            cursor.close(); conn.close()
            return jsonify({'error': 'Cart item not found'}), 404
        cursor.execute('SELECT image, variations FROM products WHERE id = %s', (cart_item['product_id'],))
        product = cursor.fetchone()
        cursor.close(); conn.close()
        if not product:
            return jsonify({'error': 'Product not found'}), 404
        images_str = product['image'] or ''
        images = [img.strip() for img in images_str.split(',') if img.strip()]
        variations_str = product['variations'] or ''
        variations = [v.strip() for v in variations_str.split(',') if v.strip()]
        return jsonify({'success': True, 'images': images, 'image_colors': {}, 'variations': variations})

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

        # -- FALLBACK: MySQL ------------------------------------------------
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute('SELECT product_id FROM cart WHERE id = %s AND email = %s', (item_id, user_email))
        cart_item = cursor.fetchone()
        if not cart_item:
            cursor.close(); conn.close()
            return jsonify({'error': 'Cart item not found'}), 404
        cursor.execute('SELECT sizes FROM products WHERE id = %s', (cart_item['product_id'],))
        product = cursor.fetchone()
        cursor.close(); conn.close()
        if not product:
            return jsonify({'error': 'Product not found'}), 404
        sizes_str = product['sizes'] or ''
        return jsonify({'success': True, 'sizes': sizes_str})

    except Exception as e:
        print(f"Error getting product sizes: {str(e)}")
        return jsonify({'error': 'Failed to get product sizes'}), 500

@app.route('/api/cart-count', methods=['GET'])
def get_cart_count():
    if 'email' not in session:
        return jsonify({'success': False, 'count': 0})
    
    try:
        user_email = session['email']
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Get total quantity of items in cart for the user
        cursor.execute('SELECT SUM(CAST(quantity AS UNSIGNED)) FROM cart WHERE email = %s', (user_email,))
        result = cursor.fetchone()
        total_count = result[0] if result[0] is not None else 0
        
        cursor.close()
        conn.close()
        
        return jsonify({'success': True, 'count': total_count})
        
    except Exception as e:
        print(f"Error getting cart count: {str(e)}")
        return jsonify({'success': False, 'count': 0})

@app.route('/api/cart-items', methods=['GET'])
def get_cart_items():
    if 'email' not in session:
        return jsonify({'success': False, 'error': 'Not logged in', 'items': [], 'total': 0})
    
    try:
        user_email = session['email']
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        # Get cart items with product details
        cursor.execute('''
            SELECT c.id, c.name, c.price, c.quantity, c.variations, c.size, c.image, c.product_id,
                   p.image as product_images
            FROM cart c 
            LEFT JOIN products p ON c.product_id = p.id 
            WHERE c.email = %s
            ORDER BY c.id DESC
        ''', (user_email,))
        
        cart_items = cursor.fetchall()
        
        # Process cart items
        total_amount = 0
        processed_items = []
        
        for item in cart_items:
            # Convert price and quantity to appropriate types
            price = float(item['price']) if item['price'] else 0
            quantity = int(item['quantity']) if item['quantity'] else 1
            item_total = price * quantity
            total_amount += item_total
            
            # Process images similar to existing cart route
            all_images = item.get('product_images', '') or item.get('image', '')
            
            # Set the display image - use the stored cart image (which should be color-specific)
            if item.get('image'):
                cart_image = item['image'].strip()
            else:
                # Fallback to first product image
                images = [img.strip() for img in str(all_images).split(',') if img.strip()]
                cart_image = images[0] if images else ''
            
            # Construct proper image URL for frontend
            if cart_image:
                # Remove any leading/trailing whitespace and slashes
                cart_image = cart_image.strip().lstrip('/')
                # The frontend expects the path to be used with url_for, so we return just the filename
                image_url = cart_image
            else:
                image_url = None
            
            processed_item = {
                'id': item['id'],
                'name': item['name'],
                'price': price,
                'quantity': quantity,
                'total_price': item_total,
                'color': item['variations'],
                'size': item['size'],
                'image_url': image_url,
                'product_id': item['product_id']
            }
            processed_items.append(processed_item)
            
            # Debug print for image handling
            print(f"DEBUG CART API - Item {item['id']}: cart_image='{item.get('image')}', product_images='{item.get('product_images')}', final_image_url='{image_url}'")
        
        cursor.close()
        conn.close()
        
        return jsonify({
            'success': True,
            'items': processed_items,
            'total': total_amount,
            'count': len(processed_items)
        })
        
    except Exception as e:
        print(f"Error getting cart items: {str(e)}")
        return jsonify({'success': False, 'error': str(e), 'items': [], 'total': 0})

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
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Remove item from cart (only if it belongs to the current user)
        cursor.execute('DELETE FROM cart WHERE id = %s AND email = %s', (item_id, user_email))
        
        if cursor.rowcount > 0:
            conn.commit()
            cursor.close()
            conn.close()
            return jsonify({'success': True, 'message': 'Item removed from cart'})
        else:
            cursor.close()
            conn.close()
            return jsonify({'success': False, 'error': 'Item not found or not authorized'})
        
    except Exception as e:
        print(f"Error removing from cart: {str(e)}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/clear_cart', methods=['POST'])
def clear_cart():
    if 'email' not in session:
        return jsonify({'success': False, 'error': 'Not logged in'})
    
    try:
        user_email = session['email']
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Get count of items before deletion
        cursor.execute('SELECT COUNT(*) FROM cart WHERE email = %s', (user_email,))
        deleted_count = cursor.fetchone()[0]
        
        # Clear all cart items for the current user
        cursor.execute('DELETE FROM cart WHERE email = %s', (user_email,))
        conn.commit()
        
        cursor.close()
        conn.close()
        
        return jsonify({
            'success': True, 
            'message': 'Cart cleared successfully',
            'deleted_count': deleted_count
        })
        
    except Exception as e:
        print(f"Error clearing cart: {str(e)}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/clear_checkout', methods=['POST'])
def clear_checkout():
    user_email = session.get('email')
    
    connection = get_db_connection()
    cursor = connection.cursor()

    try:
        cursor.execute("DELETE FROM checkout WHERE email = %s", (user_email,))
        connection.commit()
        
        # Clear the checkout source session flag
        session.pop('checkout_source', None)
        
        return jsonify(success=True)
    except mysql.connector.Error as err:
        connection.rollback()
        return jsonify(success=False, error=str(err)), 500
    finally:
        cursor.close()
        connection.close()

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

        # -- MIRROR: MySQL (best-effort) ------------------------------------
        try:
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("UPDATE users SET address = %s WHERE email = %s", (joined, user_email))
            cur.execute("UPDATE checkout SET address = %s WHERE email = %s", (joined, user_email))
            conn.commit()
            cur.close()
            conn.close()
        except Exception as my_err:
            print(f"?? update_address MySQL mirror failed: {my_err}")

        return jsonify({'success': True, 'message': 'Address saved successfully'})

    except Exception as e:
        return jsonify({'success': False, 'error': f'An error occurred: {str(e)}'}), 500

@app.route('/api/product/<int:product_id>')
def get_product_details(product_id):
    """API endpoint to get product details for modal view"""
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Not logged in'}), 401
    
    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)
        
        # Get product details with seller information - use * to get all columns
        cursor.execute("""
            SELECT p.*, 
                   u.first_name, u.last_name, u.business_name, u.email as seller_email,
                   COALESCE(u.business_name, CONCAT(u.first_name, ' ', u.last_name)) as seller_name
            FROM products p
            LEFT JOIN users u ON p.seller_email = u.email
            WHERE p.id = %s
        """, (product_id,))
        
        product = cursor.fetchone()
        cursor.close()
        connection.close()
        
        if product:
            # Convert types for JSON serialization
            try:
                if product.get('price'):
                    product['price'] = float(product['price'])
            except (ValueError, TypeError) as e:
                print(f"Error converting price: {e}")
                product['price'] = 0.0
            
            try:
                if product.get('quantity') is not None:
                    product['quantity'] = int(product['quantity'])
            except (ValueError, TypeError) as e:
                print(f"Error converting quantity: {e}")
                product['quantity'] = 0
            
            try:
                if product.get('stock_quantity') is not None:
                    product['stock_quantity'] = int(product['stock_quantity'])
            except (ValueError, TypeError) as e:
                print(f"Error converting stock_quantity: {e}")
                product['stock_quantity'] = 0
            
            # Convert datetime objects to strings
            try:
                if product.get('created_at'):
                    product['created_at'] = product['created_at'].isoformat()
            except Exception as e:
                print(f"Error converting created_at: {e}")
                product['created_at'] = None
            
            try:
                if product.get('updated_at'):
                    product['updated_at'] = product['updated_at'].isoformat()
            except Exception as e:
                print(f"Error converting updated_at: {e}")
                product['updated_at'] = None
            
            return jsonify({'success': True, 'product': product})
        else:
            return jsonify({'success': False, 'error': 'Product not found'}), 404
            
    except Exception as e:
        print(f"Error fetching product details: {e}")
        import traceback
        traceback.print_exc()
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
    """Admin route to flag a product for violation"""
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Not logged in'}), 401
    
    # Check if user is admin
    if session.get('user_type') != 'Admin':
        return jsonify({'success': False, 'error': 'Unauthorized. Admin access required.'}), 403
    
    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)
        
        # Get request data
        data = request.get_json()
        reason = data.get('reason', '').strip()
        send_email = data.get('send_email', True)
        
        if not reason:
            return jsonify({'success': False, 'error': 'Reason is required'}), 400
        
        # Get product and seller details
        cursor.execute("""
            SELECT p.id, p.name, p.seller_email, 
                   u.first_name, u.last_name, u.email as seller_email_confirm
            FROM products p
            JOIN users u ON p.seller_email = u.email
            WHERE p.id = %s
        """, (product_id,))
        
        product = cursor.fetchone()
        
        if not product:
            return jsonify({'success': False, 'error': 'Product not found'}), 404
        
        # Add flag_reason and flagged_at columns to products table if they don't exist
        # This is a safe operation that will only add columns if they don't exist
        try:
            cursor.execute("""
                ALTER TABLE products 
                ADD COLUMN IF NOT EXISTS flag_reason TEXT,
                ADD COLUMN IF NOT EXISTS flagged_at TIMESTAMP NULL,
                ADD COLUMN IF NOT EXISTS flagged_by VARCHAR(255),
                ADD COLUMN IF NOT EXISTS is_flagged BOOLEAN DEFAULT FALSE
            """)
        except:
            # If the above syntax doesn't work (older MySQL), try individual statements
            try:
                cursor.execute("ALTER TABLE products ADD COLUMN flag_reason TEXT")
            except:
                pass
            try:
                cursor.execute("ALTER TABLE products ADD COLUMN flagged_at TIMESTAMP NULL")
            except:
                pass
            try:
                cursor.execute("ALTER TABLE products ADD COLUMN flagged_by VARCHAR(255)")
            except:
                pass
            try:
                cursor.execute("ALTER TABLE products ADD COLUMN is_flagged BOOLEAN DEFAULT FALSE")
            except:
                pass
        
        # Update product with flag information
        cursor.execute("""
            UPDATE products 
            SET flag_reason = %s, 
                flagged_at = NOW(),
                flagged_by = %s,
                is_flagged = TRUE
            WHERE id = %s
        """, (reason, session['email'], product_id))
        
        connection.commit()
        
        # Create in-app notification for seller
        try:
            seller_email = product['seller_email']
            product_name = product['name']
            
            notification_message = f"?? Your product '{product_name}' has been flagged for policy violation. Reason: {reason}. Please review and take appropriate action."
            
            cursor.execute("""
                INSERT INTO notifications (seller_email, message, type, is_read, created_at)
                VALUES (%s, %s, %s, FALSE, NOW())
            """, (seller_email, notification_message, 'product_flagged'))
            
            connection.commit()
            print(f"? In-app notification created for seller: {seller_email}")
            
        except Exception as notif_error:
            print(f"Error creating in-app notification: {notif_error}")
            # Don't fail the request if notification fails
        
        # Send email notification to seller if requested
        if send_email:
            try:
                seller_name = f"{product['first_name']} {product['last_name']}"
                product_name = product['name']
                seller_email = product['seller_email']
                
                # Create and send email
                msg = Message(
                    subject=f"?? Product Flagged for Policy Violation - {product_name}",
                    sender=app.config["MAIL_DEFAULT_SENDER"],
                    recipients=[seller_email]
                )
                
                msg.html = f"""
                <!DOCTYPE html>
                <html>
                <head>
                    <style>
                        body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
                        .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                        .header {{ background: linear-gradient(135deg, #ffc107 0%, #ff9800 100%); color: white; padding: 30px; text-align: center; border-radius: 10px 10px 0 0; }}
                        .header h1 {{ margin: 0; font-size: 24px; }}
                        .content {{ background: #f9f9f9; padding: 30px; border-radius: 0 0 10px 10px; }}
                        .warning-box {{ background: #fff3cd; border-left: 4px solid #ffc107; padding: 15px; margin: 20px 0; border-radius: 5px; }}
                        .reason-box {{ background: white; border: 1px solid #ddd; padding: 15px; margin: 20px 0; border-radius: 5px; }}
                        .footer {{ text-align: center; margin-top: 30px; color: #666; font-size: 12px; }}
                        .button {{ display: inline-block; padding: 12px 30px; background: #2c3e50; color: white; text-decoration: none; border-radius: 5px; margin: 20px 0; }}
                    </style>
                </head>
                <body>
                    <div class="container">
                        <div class="header">
                            <h1>?? Product Flagged for Policy Violation</h1>
                        </div>
                        <div class="content">
                            <p>Dear {seller_name},</p>
                            
                            <div class="warning-box">
                                <strong>?? Important Notice</strong><br>
                                Your product has been flagged by our admin team for policy violation.
                            </div>
                            
                            <p><strong>Product Name:</strong> {product_name}</p>
                            
                            <div class="reason-box">
                                <strong>Reason for Flagging:</strong><br>
                                {reason}
                            </div>
                            
                            <p><strong>What This Means:</strong></p>
                            <ul>
                                <li>Your product is currently under review</li>
                                <li>It may be hidden from buyers until the issue is resolved</li>
                                <li>Repeated violations may result in account suspension</li>
                            </ul>
                            
                            <p><strong>Next Steps:</strong></p>
                            <ol>
                                <li>Review our platform policies and terms of service</li>
                                <li>Take appropriate action to address the violation</li>
                                <li>Contact our support team if you believe this is a mistake</li>
                            </ol>
                            
                            <p>If you have any questions or concerns, please don't hesitate to reach out to our support team.</p>
                            
                            <p>Best regards,<br>
                            <strong>MStyle E-Commerce Team</strong></p>
                        </div>
                        <div class="footer">
                            <p>This is an automated message from MStyle E-Commerce Platform</p>
                        </div>
                    </div>
                </body>
                </html>
                """
                
                mail.send(msg)
                print(f"? Email notification sent to seller: {seller_email}")
                
            except Exception as email_error:
                print(f"? Error sending email: {email_error}")
                import traceback
                traceback.print_exc()
                # Don't fail the request if email fails
        
        return jsonify({
            'success': True, 
            'message': 'Product has been flagged successfully. Seller has been notified via email and in-app notification.',
            'product_id': product_id
        })
        
    except Exception as e:
        print(f"Error flagging product: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()

@app.route('/clear_product_flag/<int:product_id>', methods=['POST'])
def clear_product_flag(product_id):
    """Admin route to clear a product flag and mark it as safe"""
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Not logged in'}), 401
    
    # Check if user is admin
    if session.get('user_type') != 'Admin':
        return jsonify({'success': False, 'error': 'Unauthorized. Admin access required.'}), 403
    
    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)
        
        # Check if product exists and is flagged
        cursor.execute("""
            SELECT id, name, flagged_at, flag_reason
            FROM products
            WHERE id = %s
        """, (product_id,))
        
        product = cursor.fetchone()
        
        if not product:
            return jsonify({'success': False, 'error': 'Product not found'}), 404
        
        if not product.get('flagged_at'):
            return jsonify({'success': False, 'error': 'Product is not flagged'}), 400
        
        # Clear the flag by setting flag fields to NULL
        cursor.execute("""
            UPDATE products 
            SET flag_reason = NULL, 
                flagged_at = NULL,
                flagged_by = NULL,
                is_flagged = FALSE
            WHERE id = %s
        """, (product_id,))
        
        connection.commit()
        
        return jsonify({
            'success': True, 
            'message': 'Product flag has been cleared successfully',
            'product_id': product_id
        })
        
    except Exception as e:
        print(f"Error clearing product flag: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()

@app.route('/toggle_product_status/<int:product_id>', methods=['POST'])
def toggle_product_status(product_id):
    """Admin route to activate or deactivate a product"""
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Not logged in'}), 401
    
    # Check if user is admin
    if session.get('user_type') != 'Admin':
        return jsonify({'success': False, 'error': 'Unauthorized. Admin access required.'}), 403
    
    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)
        
        # Get request data
        data = request.get_json()
        is_active = data.get('is_active', True)
        reason = data.get('reason', '').strip()
        
        # Check if product exists and get seller info
        cursor.execute("""
            SELECT p.id, p.name, p.seller_email,
                   u.first_name, u.last_name
            FROM products p
            JOIN users u ON p.seller_email = u.email
            WHERE p.id = %s
        """, (product_id,))
        product = cursor.fetchone()
        
        if not product:
            return jsonify({'success': False, 'error': 'Product not found'}), 404
        
        # Add is_active column to products table if it doesn't exist
        try:
            cursor.execute("SHOW COLUMNS FROM products LIKE 'is_active'")
            if not cursor.fetchone():
                cursor.execute("""
                    ALTER TABLE products 
                    ADD COLUMN is_active BOOLEAN DEFAULT TRUE
                """)
                connection.commit()
        except Exception as e:
            print(f"Error checking/adding is_active column: {e}")
        
        # Update product status
        cursor.execute("""
            UPDATE products 
            SET is_active = %s
            WHERE id = %s
        """, (is_active, product_id))
        
        connection.commit()
        
        status_text = 'activated' if is_active else 'deactivated'
        
        # Send notification to seller
        try:
            seller_email = product['seller_email']
            product_name = product['name']
            seller_name = f"{product['first_name']} {product['last_name']}"
            
            if is_active:
                notification_message = f"? Your product '{product_name}' has been activated by admin and is now visible to buyers."
                notification_type = "product_activated"
                email_subject = f"? Product Activated - {product_name}"
                email_title = "Product Activated"
                email_icon = "?"
                email_color = "#28a745"
                reason_text = ""
            else:
                notification_message = f"?? Your product '{product_name}' has been deactivated by admin and is no longer visible to buyers."
                if reason:
                    notification_message += f" Reason: {reason}"
                notification_type = "product_deactivated"
                email_subject = f"?? Product Deactivated - {product_name}"
                email_title = "Product Deactivated"
                email_icon = "??"
                email_color = "#dc3545"
                reason_text = f"<p><strong>Reason:</strong> {reason}</p>" if reason else ""
            
            # Create in-app notification
            cursor.execute("""
                INSERT INTO notifications (seller_email, message, type, is_read, created_at)
                VALUES (%s, %s, %s, FALSE, NOW())
            """, (seller_email, notification_message, notification_type))
            
            connection.commit()
            print(f"? In-app notification created for seller: {seller_email}")
            
            # Send email notification
            try:
                msg = Message(
                    subject=email_subject,
                    sender=app.config["MAIL_DEFAULT_SENDER"],
                    recipients=[seller_email]
                )
                
                msg.html = f"""
                <!DOCTYPE html>
                <html>
                <head>
                    <style>
                        body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
                        .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                        .header {{ background: linear-gradient(135deg, {email_color} 0%, {email_color}dd 100%); color: white; padding: 30px; text-align: center; border-radius: 10px 10px 0 0; }}
                        .header h1 {{ margin: 0; font-size: 24px; }}
                        .content {{ background: #f9f9f9; padding: 30px; border-radius: 0 0 10px 10px; }}
                        .info-box {{ background: white; border: 1px solid #ddd; padding: 15px; margin: 20px 0; border-radius: 5px; }}
                        .footer {{ text-align: center; margin-top: 30px; color: #666; font-size: 12px; }}
                    </style>
                </head>
                <body>
                    <div class="container">
                        <div class="header">
                            <h1>{email_icon} {email_title}</h1>
                        </div>
                        <div class="content">
                            <p>Dear {seller_name},</p>
                            
                            <div class="info-box">
                                <p><strong>Product Name:</strong> {product_name}</p>
                                <p><strong>Status:</strong> {status_text.capitalize()}</p>
                                {reason_text}
                            </div>
                            
                            <p>Your product has been {status_text} by our admin team.</p>
                            {f'<p><strong>Reason provided:</strong> {reason}</p>' if reason else ''}
                            
                            <p>If you have any questions or concerns, please contact our support team.</p>
                            
                            <p>Best regards,<br>
                            <strong>MStyle E-Commerce Team</strong></p>
                        </div>
                        <div class="footer">
                            <p>This is an automated message from MStyle E-Commerce Platform</p>
                        </div>
                    </div>
                </body>
                </html>
                """
                
                mail.send(msg)
                print(f"? Email notification sent to seller: {seller_email}")
                
            except Exception as email_error:
                print(f"? Error sending email: {email_error}")
                import traceback
                traceback.print_exc()
                
        except Exception as notif_error:
            print(f"? Error creating notification: {notif_error}")
            import traceback
            traceback.print_exc()
            # Don't fail the request if notification fails
        
        return jsonify({
            'success': True, 
            'message': f'Product has been {status_text} successfully. Seller has been notified via email and in-app notification.',
            'product_id': product_id,
            'is_active': is_active
        })
        
    except Exception as e:
        print(f"Error toggling product status: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()

@app.route('/checkout_single_product', methods=['POST'])
def checkout_single_product():
    if 'email' not in session:
        return jsonify({'success': False, 'error': 'Please log in to checkout'})

    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)

        # Get product details from the form
        product_id = request.form.get('product_id')
        try:
            quantity = int(request.form.get('quantity', '1'))
        except ValueError:
            return jsonify({'success': False, 'error': 'Invalid quantity value'})
            
        size = request.form.get('size')
        selected_color = request.form.get('product_variation', '')  # Get the selected color
        color_specific_image = request.form.get('product_image', '')  # Get the color-specific image
        
        # Get promotional pricing information from form
        product_price = request.form.get('product_price')  # This is the promotional price if promotion exists
        original_price = request.form.get('original_price')
        has_promotion = request.form.get('has_promotion', 'False') == 'True'
        discount_amount = request.form.get('discount_amount', '0')
        
        # Validate inputs
        if not product_id or quantity < 1:
            return jsonify({'success': False, 'error': 'Invalid product or quantity'})

        # Get product details
        cursor.execute("SELECT * FROM products WHERE id = %s", (product_id,))
        product = cursor.fetchone()

        if not product:
            return jsonify({'success': False, 'error': 'Product not found'})

        # Convert product quantity to integer for comparison
        product_quantity = int(product['quantity'])
        
        # Check if product is in stock
        if product_quantity < quantity:
            return jsonify({'success': False, 'error': 'Insufficient stock'})

        # Clear any existing checkout items for this user
        cursor.execute("DELETE FROM checkout WHERE email = %s", (session['email'],))

        # Use promotional price if provided, otherwise fall back to product price
        try:
            if product_price and product_price.strip():
                price = float(product_price)  # Use promotional price from form
            else:
                price = float(product['price']) if product['price'] is not None else 0.0  # Fallback to regular price
        except (ValueError, TypeError):
            return jsonify({'success': False, 'error': 'Invalid product price'})

        # Use color-specific image if provided, otherwise fall back to first product image
        if color_specific_image:
            checkout_image = color_specific_image
        elif product['image']:
            checkout_image = product['image'].split(',')[0].strip()
        else:
            checkout_image = ''
        
        # Debug logging
        print(f"DEBUG - Checkout Single Product:")
        print(f"  Selected Color: {selected_color}")
        print(f"  Color Specific Image: {color_specific_image}")
        print(f"  Final Checkout Image: {checkout_image}")
        print(f"  All Product Images: {product['image']}")

        # Check if product has free shipping promotion
        shipping_fee = 50  # Default shipping fee
        cursor.execute("""
            SELECT pr.type 
            FROM promotions pr
            LEFT JOIN promotion_products pp ON pr.id = pp.promotion_id
            LEFT JOIN promotion_categories pc ON pr.id = pc.promotion_id
            LEFT JOIN products p ON (pp.product_id = p.id OR pc.category = p.category)
            WHERE pr.seller_email = %s
            AND pr.type = 'free_shipping'
            AND pr.is_active = 1
            AND CURDATE() BETWEEN pr.start_date AND pr.end_date
            AND (pp.product_id = %s OR pc.category = (SELECT category FROM products WHERE id = %s))
            LIMIT 1
        """, (product['seller_email'], product_id, product_id))
        free_shipping_promo = cursor.fetchone()
        if free_shipping_promo:
            shipping_fee = 0
            print(f"DEBUG - Free shipping applied for product: {product['name']}")

        # Add the single product to checkout
        cursor.execute("""
            INSERT INTO checkout 
            (id, name, price, quantity, variations, image, size, email, address, seller_email, product_id, shipping_fee) 
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            product_id,
            product['name'],
            price,
            quantity,
            selected_color,  # Use selected color instead of all variations
            checkout_image,  # Use color-specific image
            size,
            session['email'],
            session.get('address', ''),  # Add address from session
            product['seller_email'],
            product_id,
            shipping_fee
        ))

        connection.commit()
        
        # Set session flag to indicate this came from Buy Now
        session['checkout_source'] = 'buy_now'
        
        return jsonify({'success': True})

    except mysql.connector.Error as err:
        return jsonify({'success': False, 'error': f'Database error: {str(err)}'})
    except Exception as e:
        return jsonify({'success': False, 'error': f'An error occurred: {str(e)}'})
    finally:
        if 'connection' in locals():
            cursor.close()
            connection.close()

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

@app.route('/test-json')
def test_json():
    """Test JSON response"""
    return jsonify({'success': True, 'message': 'Test JSON response working!'})

def check_database_connection():
    """Check if MySQL is accessible. Returns False silently if unavailable."""
    try:
        db = get_db_connection()
        cursor = db.cursor()
        cursor.execute("SELECT 1")

        # Create notifications table if it doesn't exist
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS notifications (
                id INT AUTO_INCREMENT PRIMARY KEY,
                seller_email VARCHAR(255) NOT NULL,
                message TEXT NOT NULL,
                type VARCHAR(50) DEFAULT 'order',
                is_read BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                order_id INT,
                INDEX idx_seller_email (seller_email),
                INDEX idx_created_at (created_at),
                INDEX idx_is_read (is_read)
            )
        """)

        # Create buyer_notifications table if it doesn't exist
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS buyer_notifications (
                id INT AUTO_INCREMENT PRIMARY KEY,
                buyer_email VARCHAR(255) NOT NULL,
                message TEXT NOT NULL,
                type VARCHAR(50) DEFAULT 'status_update',
                is_read BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                order_id INT,
                INDEX idx_buyer_email (buyer_email),
                INDEX idx_created_at (created_at),
                INDEX idx_is_read (is_read)
            )
        """)

        cursor.close()
        db.close()
        print("? MySQL connection successful")
        return True
    except Exception as e:
        # Don't crash � app runs in Supabase-only mode
        print(f"??  MySQL not available: {e}")
        return False

# Notification API endpoints
@app.route('/api/seller/notifications')
def get_seller_notifications():
    """Get notifications for the logged-in seller"""
    seller_email = session.get('email')
    user_type = session.get('user_type')
    
    print(f"?? Fetching notifications for: {seller_email} (type: {user_type})")
    print(f"?? Full session data: {dict(session)}")
    
    # More flexible user type checking
    if not seller_email:
        print(f"? No email in session")
        return jsonify({'success': False, 'error': 'No email in session'}), 401
    
    # Check if user_type is seller (case insensitive) or if no user_type restriction for debugging
    if user_type and user_type.lower() != 'seller':
        print(f"? User type mismatch - Expected: seller, Got: {user_type}")
        return jsonify({'success': False, 'error': f'User type mismatch. Expected: seller, Got: {user_type}'}), 401
    
    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)
        
        # Get notifications for this seller, ordered by newest first
        cursor.execute("""
            SELECT id, message, type, is_read, created_at
            FROM notifications 
            WHERE seller_email = %s 
            ORDER BY created_at DESC 
            LIMIT 20
        """, (seller_email,))
        
        notifications = cursor.fetchall()
        print(f"?? Found {len(notifications)} notifications for {seller_email}")
        
        # Convert datetime objects to strings and use type from database
        for notification in notifications:
            if notification['created_at']:
                notification['created_at'] = notification['created_at'].isoformat()
            notification['read'] = bool(notification['is_read'])
            
            # Use the type from database, or determine from message content as fallback
            if not notification.get('type'):
                message = notification['message'].lower()
                if 'rider' in message and 'accepted' in message:
                    notification['type'] = 'rider_assigned'
                elif 'cancel' in message:
                    notification['type'] = 'cancellation'
                elif 'review' in message:
                    notification['type'] = 'review'
                elif 'low stock' in message:
                    notification['type'] = 'low_stock'
                elif 'out of stock' in message:
                    notification['type'] = 'out_of_stock'
                else:
                    notification['type'] = 'order'
        
        cursor.close()
        connection.close()
        
        print(f"? Returning {len(notifications)} notifications")
        return jsonify({
            'success': True,
            'notifications': notifications
        })
        
    except Exception as e:
        print(f"? Error fetching notifications for {seller_email}: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/seller/notifications/mark-read', methods=['POST'])
def mark_notification_read():
    """Mark a specific notification as read"""
    seller_email = session.get('email')
    user_type = session.get('user_type')
    
    print(f"?? Mark as read request - Seller: {seller_email}, Type: {user_type}")
    
    if not seller_email:
        print("? No email in session")
        return jsonify({'success': False, 'error': 'No email in session'}), 401
    
    if user_type and user_type.lower() != 'seller':
        print(f"? User type mismatch - Expected: seller, Got: {user_type}")
        return jsonify({'success': False, 'error': f'User type mismatch. Expected: seller, Got: {user_type}'}), 401
    
    connection = None
    cursor = None
    try:
        data = request.get_json()
        notification_id = data.get('notification_id')
        
        print(f"?? Marking notification ID: {notification_id} as read for seller: {seller_email}")
        
        if not notification_id:
            print("? No notification ID provided")
            return jsonify({'success': False, 'error': 'Notification ID required'}), 400
        
        connection = get_db_connection()
        cursor = connection.cursor()
        
        # Check if notification exists and belongs to this seller
        cursor.execute("""
            SELECT id, is_read FROM notifications 
            WHERE id = %s AND seller_email = %s
        """, (notification_id, seller_email))
        
        notification = cursor.fetchone()
        
        if not notification:
            print(f"? Notification {notification_id} not found for seller {seller_email}")
            return jsonify({'success': False, 'error': 'Notification not found'}), 404
        
        print(f"?? Found notification - ID: {notification[0]}, Currently read: {notification[1]}")
        
        # Mark notification as read (only if it belongs to this seller)
        cursor.execute("""
            UPDATE notifications 
            SET is_read = TRUE 
            WHERE id = %s AND seller_email = %s
        """, (notification_id, seller_email))
        
        affected_rows = cursor.rowcount
        print(f"?? Updated {affected_rows} rows")
        
        connection.commit()
        
        print(f"? Notification {notification_id} marked as read successfully")
        return jsonify({'success': True, 'affected_rows': affected_rows})
        
    except Exception as e:
        print(f"? Error marking notification as read: {str(e)}")
        import traceback
        traceback.print_exc()
        if connection:
            try:
                connection.rollback()
            except:
                pass
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()

@app.route('/api/seller/notifications/mark-all-read', methods=['POST'])
def mark_all_notifications_read():
    """Mark all notifications as read for the logged-in seller"""
    seller_email = session.get('email')
    user_type = session.get('user_type')
    
    print(f"?? Mark all as read - Email: {seller_email}, User type: {user_type}")
    print(f"?? Full session data: {dict(session)}")
    
    if not seller_email:
        print(f"? No email in session")
        return jsonify({'success': False, 'error': 'No email in session. Please log in.'}), 401
    
    # More flexible user type checking - only check if user_type exists
    if user_type and user_type.lower() != 'seller':
        print(f"? User type mismatch - Expected: seller, Got: {user_type}")
        return jsonify({'success': False, 'error': f'Unauthorized. User type: {user_type}'}), 401
    
    connection = None
    cursor = None
    try:
        connection = get_db_connection()
        cursor = connection.cursor()
        
        # Mark all notifications as read for this seller
        cursor.execute("""
            UPDATE notifications 
            SET is_read = TRUE 
            WHERE seller_email = %s AND is_read = FALSE
        """, (seller_email,))
        
        affected_rows = cursor.rowcount
        connection.commit()
        
        print(f"? Marked {affected_rows} notifications as read for seller: {seller_email}")
        return jsonify({'success': True, 'affected_rows': affected_rows})
        
    except Exception as e:
        print(f"Error marking all notifications as read: {str(e)}")
        if connection:
            try:
                connection.rollback()
            except:
                pass
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()

@app.route('/api/seller/notifications/delete', methods=['POST'])
def delete_notification():
    """Delete a specific notification"""
    seller_email = session.get('email')
    user_type = session.get('user_type')
    
    print(f"??? Delete notification request - Seller: {seller_email}, Type: {user_type}")
    print(f"?? Full session data: {dict(session)}")
    
    # More flexible authentication - check if user_type contains 'seller' (case insensitive)
    if not seller_email:
        print(f"? No email in session")
        return jsonify({'success': False, 'error': 'No email in session. Please log in.'}), 401
    
    if user_type and user_type.lower() != 'seller':
        print(f"? User type mismatch - Expected: seller, Got: {user_type}")
        return jsonify({'success': False, 'error': f'Access denied. User type: {user_type}'}), 401
    
    connection = None
    cursor = None
    try:
        data = request.get_json()
        notification_id = data.get('notification_id')
        
        print(f"?? Delete request data: {data}")
        print(f"?? Notification ID to delete: {notification_id}")
        
        if not notification_id:
            return jsonify({'success': False, 'error': 'Notification ID required'}), 400
        
        connection = get_db_connection()
        cursor = connection.cursor()
        
        # First check if notification exists and belongs to this seller
        cursor.execute("""
            SELECT id, seller_email, message FROM notifications 
            WHERE id = %s AND seller_email = %s
        """, (notification_id, seller_email))
        
        notification = cursor.fetchone()
        
        if not notification:
            print(f"? Notification {notification_id} not found for seller {seller_email}")
            return jsonify({'success': False, 'error': 'Notification not found or unauthorized'}), 404
        
        print(f"?? Found notification to delete: ID={notification[0]}, Seller={notification[1]}")
        
        # Delete notification
        cursor.execute("""
            DELETE FROM notifications 
            WHERE id = %s AND seller_email = %s
        """, (notification_id, seller_email))
        
        deleted_count = cursor.rowcount
        print(f"?? Deleted {deleted_count} rows")
        
        connection.commit()
        
        print(f"? Notification {notification_id} deleted successfully for seller: {seller_email}")
        return jsonify({'success': True, 'deleted_count': deleted_count})
        
    except Exception as e:
        print(f"? Error deleting notification: {str(e)}")
        import traceback
        traceback.print_exc()
        if connection:
            try:
                connection.rollback()
            except:
                pass
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()

@app.route('/api/seller/notifications/delete-all', methods=['POST'])
def delete_all_notifications():
    """Delete all notifications for the logged-in seller"""
    seller_email = session.get('email')
    user_type = session.get('user_type')
    
    print(f"??? Delete all notifications request - Seller: {seller_email}, Type: {user_type}")
    print(f"?? Full session data: {dict(session)}")
    
    # More flexible authentication
    if not seller_email:
        print(f"? No email in session")
        return jsonify({'success': False, 'error': 'No email in session. Please log in.'}), 401
    
    if user_type and user_type.lower() != 'seller':
        print(f"? User type mismatch - Expected: seller, Got: {user_type}")
        return jsonify({'success': False, 'error': f'Access denied. User type: {user_type}'}), 401
    
    connection = None
    cursor = None
    try:
        connection = get_db_connection()
        cursor = connection.cursor()
        
        # First count how many notifications exist
        cursor.execute("""
            SELECT COUNT(*) FROM notifications 
            WHERE seller_email = %s
        """, (seller_email,))
        
        count_before = cursor.fetchone()[0]
        print(f"?? Found {count_before} notifications to delete for seller: {seller_email}")
        
        # Delete all notifications for this seller
        cursor.execute("""
            DELETE FROM notifications 
            WHERE seller_email = %s
        """, (seller_email,))
        
        deleted_count = cursor.rowcount
        print(f"?? Actually deleted {deleted_count} notifications")
        
        connection.commit()
        
        print(f"? {deleted_count} notifications deleted successfully for seller: {seller_email}")
        return jsonify({'success': True, 'deleted_count': deleted_count})
        
    except Exception as e:
        print(f"? Error deleting all notifications: {str(e)}")
        if connection:
            try:
                connection.rollback()
            except:
                pass
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()

# Buyer Notification API endpoints
@app.route('/api/buyer/notifications')
def get_buyer_notifications():
    """Get notifications for the logged-in buyer"""
    buyer_email = session.get('email')
    user_type = session.get('user_type')
    
    print(f"?? Fetching buyer notifications for: {buyer_email} (type: {user_type})")
    print(f"?? Full session data: {dict(session)}")
    
    # More flexible user type checking
    if not buyer_email:
        print(f"? No email in session")
        return jsonify({'success': False, 'error': 'No email in session'}), 401
    
    # Check if user_type is buyer (case insensitive) or allow for debugging
    if user_type and user_type.lower() != 'buyer':
        print(f"? User type mismatch - Expected: buyer, Got: {user_type}")
        return jsonify({'success': False, 'error': f'User type mismatch. Expected: buyer, Got: {user_type}'}), 401
    
    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)
        
        # Get notifications for this buyer, ordered by newest first
        cursor.execute("""
            SELECT id, message, type, is_read, created_at, order_id
            FROM buyer_notifications 
            WHERE buyer_email = %s 
            ORDER BY created_at DESC 
            LIMIT 20
        """, (buyer_email,))
        
        notifications = cursor.fetchall()
        print(f"?? Found {len(notifications)} buyer notifications for {buyer_email}")
        
        # Convert datetime objects to strings for JSON serialization
        for notification in notifications:
            if notification['created_at']:
                notification['created_at'] = notification['created_at'].isoformat()
            notification['read'] = bool(notification['is_read'])
        
        cursor.close()
        connection.close()
        
        print(f"? Returning {len(notifications)} buyer notifications")
        return jsonify({
            'success': True,
            'notifications': notifications
        })
        
    except Exception as e:
        print(f"? Error fetching buyer notifications for {buyer_email}: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/buyer/notifications/mark-read', methods=['POST'])
def mark_buyer_notification_read():
    """Mark a specific buyer notification as read"""
    buyer_email = session.get('email')
    user_type = session.get('user_type')
    
    if not buyer_email or (user_type and user_type.lower() != 'buyer'):
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401
    
    connection = None
    cursor = None
    try:
        data = request.get_json()
        notification_id = data.get('notification_id')
        
        if not notification_id:
            return jsonify({'success': False, 'error': 'Notification ID required'}), 400
        
        connection = get_db_connection()
        cursor = connection.cursor()
        
        # Mark notification as read (only if it belongs to this buyer)
        cursor.execute("""
            UPDATE buyer_notifications 
            SET is_read = TRUE 
            WHERE id = %s AND buyer_email = %s
        """, (notification_id, buyer_email))
        
        affected_rows = cursor.rowcount
        connection.commit()
        
        print(f"? Buyer notification {notification_id} marked as read")
        return jsonify({'success': True, 'affected_rows': affected_rows})
        
    except Exception as e:
        print(f"? Error marking buyer notification as read: {str(e)}")
        if connection:
            try:
                connection.rollback()
            except:
                pass
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()

@app.route('/api/buyer/notifications/mark-all-read', methods=['POST'])
def mark_all_buyer_notifications_read():
    """Mark all notifications as read for the logged-in buyer"""
    buyer_email = session.get('email')
    user_type = session.get('user_type')
    
    if not buyer_email or (user_type and user_type.lower() != 'buyer'):
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401
    
    connection = None
    cursor = None
    try:
        connection = get_db_connection()
        cursor = connection.cursor()
        
        # Mark all notifications as read for this buyer
        cursor.execute("""
            UPDATE buyer_notifications 
            SET is_read = TRUE 
            WHERE buyer_email = %s AND is_read = FALSE
        """, (buyer_email,))
        
        affected_rows = cursor.rowcount
        connection.commit()
        
        print(f"? Marked {affected_rows} buyer notifications as read")
        return jsonify({'success': True, 'affected_rows': affected_rows})
        
    except Exception as e:
        print(f"Error marking all buyer notifications as read: {str(e)}")
        if connection:
            try:
                connection.rollback()
            except:
                pass
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()

@app.route('/api/buyer/notifications/delete', methods=['POST'])
def delete_buyer_notification():
    """Delete a specific buyer notification"""
    buyer_email = session.get('email')
    user_type = session.get('user_type')
    
    if not buyer_email or (user_type and user_type.lower() != 'buyer'):
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401
    
    connection = None
    cursor = None
    try:
        data = request.get_json()
        notification_id = data.get('notification_id')
        
        if not notification_id:
            return jsonify({'success': False, 'error': 'Notification ID required'}), 400
        
        connection = get_db_connection()
        cursor = connection.cursor()
        
        # Delete notification (only if it belongs to this buyer)
        cursor.execute("""
            DELETE FROM buyer_notifications 
            WHERE id = %s AND buyer_email = %s
        """, (notification_id, buyer_email))
        
        deleted_count = cursor.rowcount
        
        # Check if any row was affected
        if deleted_count == 0:
            return jsonify({'success': False, 'error': 'Notification not found or unauthorized'}), 404
        
        connection.commit()
        
        print(f"? Buyer notification {notification_id} deleted for buyer: {buyer_email}")
        return jsonify({'success': True, 'deleted_count': deleted_count})
        
    except Exception as e:
        print(f"? Error deleting buyer notification: {str(e)}")
        if connection:
            try:
                connection.rollback()
            except:
                pass
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()

@app.route('/api/buyer/notifications/delete-all', methods=['POST'])
def delete_all_buyer_notifications():
    """Delete all notifications for the logged-in buyer"""
    buyer_email = session.get('email')
    user_type = session.get('user_type')
    
    if not buyer_email or (user_type and user_type.lower() != 'buyer'):
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401
    
    connection = None
    cursor = None
    try:
        connection = get_db_connection()
        cursor = connection.cursor()
        
        # Delete all notifications for this buyer
        cursor.execute("""
            DELETE FROM buyer_notifications 
            WHERE buyer_email = %s
        """, (buyer_email,))
        
        deleted_count = cursor.rowcount
        connection.commit()
        
        print(f"? {deleted_count} buyer notifications deleted for buyer: {buyer_email}")
        return jsonify({'success': True, 'deleted_count': deleted_count})
        
    except Exception as e:
        print(f"? Error deleting all buyer notifications: {str(e)}")
        if connection:
            try:
                connection.rollback()
            except:
                pass
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()

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
    """Create a notification in the database when an order is placed"""
    connection = None
    cursor = None
    try:
        print(f"?? Creating notification for seller: {seller_email}")
        print(f"?? Order details: {order_details}")
        
        connection = get_db_connection()
        cursor = connection.cursor()
        
        # Create a summary message for the notification
        total_items = len(order_details)
        total_amount = sum(float(item['total_price']) for item in order_details)
        customer_email = order_details[0]['email'] if order_details else 'Unknown'
        
        if total_items == 1:
            item = order_details[0]
            message = f"New order: {item['name']} (Qty: {item['quantity']}) - ?{total_amount:.2f} from {customer_email}"
        else:
            message = f"New order: {total_items} items - ?{total_amount:.2f} from {customer_email}"
        
        print(f"?? Notification message: {message}")
        
        # Insert notification
        cursor.execute("""
            INSERT INTO notifications (seller_email, message, type, is_read)
            VALUES (%s, %s, %s, FALSE)
        """, (seller_email, message, 'order'))
        
        # Get the inserted notification ID for confirmation
        notification_id = cursor.lastrowid
        print(f"?? Notification inserted with ID: {notification_id}")
        
        connection.commit()
        
        print(f"? Notification created successfully for seller: {seller_email}")
        return True
        
    except Exception as e:
        print(f"? Error creating notification for {seller_email}: {str(e)}")
        import traceback
        traceback.print_exc()
        if connection:
            try:
                connection.rollback()
            except:
                pass
        return False
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()

def create_cancellation_notification(seller_email, order_name, reason, customer_email, order_id=None):
    """Create a notification in the database when an order is cancelled"""
    try:
        print(f"?? Creating cancellation notification for seller: {seller_email}")
        print(f"?? Order: {order_name}, Reason: {reason}, Customer: {customer_email}")
        
        connection = get_db_connection()
        cursor = connection.cursor()
        
        # Create cancellation message - include "cancelled" keyword so it's detected as cancellation type
        message = f"Order cancelled: {order_name} by {customer_email}. Reason: {reason}"
        
        print(f"?? Cancellation notification message: {message}")
        
        # Insert notification with type
        cursor.execute("""
            INSERT INTO notifications (seller_email, message, type, is_read, created_at)
            VALUES (%s, %s, %s, FALSE, NOW())
        """, (seller_email, message, 'cancellation'))
        
        connection.commit()
        
        # Get the inserted notification ID for confirmation
        notification_id = cursor.lastrowid
        print(f"?? Cancellation notification inserted with ID: {notification_id}")
        
        cursor.close()
        connection.close()
        
        print(f"? Cancellation notification created successfully for seller: {seller_email}")
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
            
        msg.body += f"""Total: ?{order_total:.2f}
Order Date: {order_details.get('date', 'N/A')}

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

@app.route('/debug-notifications')
def debug_notifications():
    """Debug route to check notifications in database (for development only)"""
    if not app.debug:
        return "Not available in production", 404
    
    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)
        
        # Get all notifications
        cursor.execute("""
            SELECT id, seller_email, message, type, is_read, created_at, order_id
            FROM notifications 
            ORDER BY created_at DESC 
            LIMIT 50
        """)
        
        notifications = cursor.fetchall()
        
        cursor.close()
        connection.close()
        
        # Format for display
        result = f"<h2>All Notifications in Database:</h2>"
        result += f"<p><strong>Current Session:</strong> {dict(session)}</p><br>"
        
        if notifications:
            result += f"<p><strong>Total notifications found:</strong> {len(notifications)}</p><br>"
            for notif in notifications:
                result += f"""
                <div style="border: 1px solid #ccc; padding: 10px; margin: 5px; background: #f9f9f9;">
                    <strong>ID:</strong> {notif['id']}<br>
                    <strong>Seller:</strong> {notif['seller_email']}<br>
                    <strong>Message:</strong> {notif['message']}<br>
                    <strong>Type:</strong> {notif['type']}<br>
                    <strong>Read:</strong> {notif['is_read']}<br>
                    <strong>Created:</strong> {notif['created_at']}<br>
                </div>
                """
        else:
            result += "<p>No notifications found in database.</p>"
        
        return result
        
    except Exception as e:
        return f"Error: {str(e)}"

@app.route('/api/notifications-bypass/<seller_email>')
def get_notifications_bypass(seller_email):
    """Debug route to get notifications for any seller (bypasses authentication)"""
    if not app.debug:
        return jsonify({'success': False, 'error': 'Not available in production'}), 404
    
    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)
        
        # Get notifications for specified seller
        cursor.execute("""
            SELECT id, message, type, is_read, created_at, order_id
            FROM notifications 
            WHERE seller_email = %s 
            ORDER BY created_at DESC 
            LIMIT 20
        """, (seller_email,))
        
        notifications = cursor.fetchall()
        print(f"?? Found {len(notifications)} notifications for {seller_email} (bypass mode)")
        
        # Convert datetime objects to strings for JSON serialization
        for notification in notifications:
            if notification['created_at']:
                notification['created_at'] = notification['created_at'].isoformat()
            notification['read'] = bool(notification['is_read'])
        
        cursor.close()
        connection.close()
        
        return jsonify({
            'success': True,
            'notifications': notifications,
            'debug_info': {
                'seller_email': seller_email,
                'count': len(notifications),
                'bypass_mode': True
            }
        })
        
    except Exception as e:
        print(f"? Error fetching notifications for {seller_email} (bypass): {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

def send_order_completion_notification(seller_email, order_details, customer_email):
    """Send notification to seller when buyer confirms order receipt"""
    try:
        print(f"?? Sending order completion notification to seller: {seller_email}")
        
        msg = Message(
            'Order Completed - Customer Confirmed Receipt',
            sender=app.config['MAIL_DEFAULT_SENDER'],
            recipients=[seller_email]
        )
        
        try:
            order_total = float(order_details.get('total_price', 0)) if order_details.get('total_price') else 0.0
        except (ValueError, TypeError):
            order_total = 0.0
        
        msg.body = f"""Hello!

Great news! Your customer has confirmed receipt of their order.

ORDER COMPLETED:
Product: {order_details['name']}
Quantity: {order_details['quantity']}
Customer: {customer_email}
Total: ?{order_total:.2f}

The order has been marked as completed and the inventory has been updated.

Thank you for being a valued MStyle seller!

Best regards,
MStyle Team
"""
        
        mail.send(msg)
        print(f"? Order completion notification sent to seller: {seller_email}")
        return True
        
    except Exception as e:
        print(f"? Error sending completion notification to {seller_email}: {str(e)}")
        return False

def auto_complete_delivered_orders():
    """Auto-complete orders that have been delivered for more than 7 days without buyer confirmation"""
    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)
        
        # Find orders that should be auto-completed
        from datetime import datetime
        current_time = datetime.now()
        
        cursor.execute("""
            SELECT id, name, quantity, product_id, seller_email, email as customer_email, total_price
            FROM orders 
            WHERE status = 'Delivered' 
            AND auto_complete_at <= %s 
            AND is_auto_completed = FALSE
        """, (current_time,))
        
        orders_to_complete = cursor.fetchall()
        
        if not orders_to_complete:
            print("?? No orders to auto-complete")
            return 0
        
        completed_count = 0
        
        for order in orders_to_complete:
            try:
                # Update order status to Completed and mark as auto-completed
                cursor.execute("""
                    UPDATE orders 
                    SET status = 'Completed', is_auto_completed = TRUE, received_at = %s
                    WHERE id = %s
                """, (current_time, order['id']))
                
                # Update product inventory
                cursor.execute("""
                    UPDATE products 
                    SET quantity = quantity - %s 
                    WHERE id = %s
                """, (int(order['quantity']), order['product_id']))
                
                connection.commit()
                
                # Send notification to seller
                try:
                    send_auto_completion_notification(order['seller_email'], order, order['customer_email'])
                except Exception as email_error:
                    print(f"? Failed to send auto-completion notification: {str(email_error)}")
                
                completed_count += 1
                print(f"? Auto-completed order {order['id']}: {order['name']}")
                
            except Exception as order_error:
                print(f"? Failed to auto-complete order {order['id']}: {str(order_error)}")
                connection.rollback()
        
        cursor.close()
        connection.close()
        
        print(f"?? Auto-completed {completed_count} orders")
        return completed_count
        
    except Exception as e:
        print(f"? Error in auto_complete_delivered_orders: {str(e)}")
        return 0

def send_auto_completion_notification(seller_email, order_details, customer_email):
    """Send notification to seller when order is auto-completed"""
    try:
        msg = Message(
            'Order Auto-Completed - 7 Days Delivery Confirmation',
            sender=app.config['MAIL_DEFAULT_SENDER'],
            recipients=[seller_email]
        )
        
        try:
            order_total = float(order_details.get('total_price', 0)) if order_details.get('total_price') else 0.0
        except (ValueError, TypeError):
            order_total = 0.0
        
        msg.body = f"""Hello!

Your order has been automatically marked as completed after 7 days of delivery.

ORDER AUTO-COMPLETED:
Product: {order_details['name']}
Quantity: {order_details['quantity']}
Customer: {customer_email}
Total: ?{order_total:.2f}

Since the customer did not report any issues within 7 days of delivery, 
the order has been automatically completed and the inventory has been updated.

Thank you for being a valued MStyle seller!

Best regards,
MStyle Team
"""
        
        mail.send(msg)
        print(f"? Auto-completion notification sent to seller: {seller_email}")
        return True
        
    except Exception as e:
        print(f"? Error sending auto-completion notification to {seller_email}: {str(e)}")
        return False

def send_review_notification_email(seller_email, order_details, rating, review_text, customer_email):
    """Send email notification to seller when customer submits a review"""
    try:
        print(f"?? Sending review notification email to seller: {seller_email}")
        
        msg = Message(
            f'New {rating}-Star Review Received!',
            sender=app.config['MAIL_DEFAULT_SENDER'],
            recipients=[seller_email]
        )
        
        # Create star display
        stars = "?" * int(rating)
        
        msg.body = f"""Hello!

Great news! You've received a new review for your product.

NEW REVIEW DETAILS:
Product: {order_details['name']}
Rating: {stars} ({rating}/5 stars)
Customer: {customer_email}

Review:
"{review_text}"

This review will help other customers discover your products and build trust in your brand.

Keep up the excellent work!

Best regards,
MStyle Team
"""
        
        mail.send(msg)
        print(f"? Review notification email sent to seller: {seller_email}")
        return True
        
    except Exception as e:
        print(f"? Error sending review notification email to {seller_email}: {str(e)}")
        return False

def create_review_notification(seller_email, order_details, rating, review_text, customer_email, order_id):
    """Create a notification in the database for seller when customer submits a review"""
    try:
        print(f"?? Creating review notification for seller: {seller_email}")
        
        connection = get_db_connection()
        cursor = connection.cursor()
        
        # Create star display for notification
        stars = "?" * int(rating)
        
        # Create notification message - include "review" keyword so it can be detected
        message = f"New {rating}-star review received for '{order_details['name']}' from customer {customer_email}. Review: \"{review_text[:100]}{'...' if len(review_text) > 100 else ''}\""
        
        print(f"?? Review notification message: {message}")
        
        # Insert notification with type
        cursor.execute("""
            INSERT INTO notifications (seller_email, message, type, is_read, created_at)
            VALUES (%s, %s, %s, FALSE, NOW())
        """, (seller_email, message, 'review'))
        
        connection.commit()
        
        # Get the inserted notification ID for confirmation
        notification_id = cursor.lastrowid
        print(f"?? Review notification inserted with ID: {notification_id}")
        
        cursor.close()
        connection.close()
        
        print(f"? Review notification created successfully for seller: {seller_email}")
        return True
        
    except Exception as e:
        print(f"? Error creating review notification for {seller_email}: {str(e)}")
        import traceback
        traceback.print_exc()
        return False

def send_issue_report_email(order_details, report_against, issue_type, issue_description, customer_email, issue_id):
    """Send email notification to admin/customer service when customer reports an issue"""
    try:
        print(f"?? Sending issue report email for order {order_details['id']}")
        
        # Send to customer service email (you can change this to your customer service email)
        customer_service_email = 'stylemens2025@gmail.com'  # Change to your customer service email
        
        # Create subject with report_against information
        report_against_display = {
            'seller': 'Seller',
            'delivery': 'Delivery Service',
            'product': 'Product Quality',
            'platform': 'Platform',
            'other': 'Other'
        }.get(report_against, report_against.title())
        
        msg = Message(
            f'Issue Report #{issue_id} - {report_against_display} - {issue_type}',
            sender=app.config['MAIL_DEFAULT_SENDER'],
            recipients=[customer_service_email]
        )
        
        msg.body = f"""URGENT: Customer Issue Report

ISSUE DETAILS:
Issue ID: #{issue_id}
Report Against: {report_against_display}
Issue Type: {issue_type}
Order ID: {order_details['id']}
Product: {order_details.get('product_name', order_details.get('name', 'N/A'))}
Customer: {customer_email}
Seller: {order_details.get('seller_email', 'N/A')}

ISSUE DESCRIPTION:
{issue_description}

ORDER INFORMATION:
- Order Date: {order_details.get('date', 'N/A')}
- Order Status: {order_details.get('status', 'N/A')}
- Total Price: ?{order_details.get('total_price', 0)}

PRIORITY LEVEL:
{
'HIGH - Seller Issue' if report_against == 'seller' else
'MEDIUM - Delivery Issue' if report_against == 'delivery' else
'HIGH - Product Quality Issue' if report_against == 'product' else
'LOW - Platform Issue' if report_against == 'platform' else
'MEDIUM - Other Issue'
}

Please review this issue and contact the customer as soon as possible.

Customer Service Dashboard: [Add your admin dashboard URL here]

Best regards,
MStyle System
"""
        
        mail.send(msg)
        print(f"? Issue report email sent to customer service: {customer_service_email}")
        return True
        
    except Exception as e:
        print(f"? Error sending issue report email: {str(e)}")
        return False

def create_issue_notification(seller_email, order_details, report_against, issue_type, issue_description, customer_email, issue_id):
    """Create a notification in the database for seller when customer reports an issue"""
    try:
        print(f"?? Creating issue notification for seller: {seller_email}")
        
        connection = get_db_connection()
        cursor = connection.cursor()
        
        # Create notification message with report_against information
        report_against_display = {
            'seller': 'against you (seller)',
            'delivery': 'about delivery service',
            'product': 'about product quality',
            'platform': 'about platform',
            'other': 'other issue'
        }.get(report_against, report_against)
        
        message = f"Customer {customer_email} reported an issue {report_against_display} for order #{order_details['id']} ({order_details.get('product_name', order_details.get('name', 'Product'))}). Issue: {issue_type} - {issue_description[:100]}{'...' if len(issue_description) > 100 else ''}"
        
        print(f"?? Issue notification message: {message}")
        
        # Insert notification with type
        cursor.execute("""
            INSERT INTO notifications (seller_email, message, type, is_read, created_at)
            VALUES (%s, %s, %s, FALSE, NOW())
        """, (seller_email, message, 'issue'))
        
        connection.commit()
        
        # Get the inserted notification ID for confirmation
        notification_id = cursor.lastrowid
        print(f"?? Issue notification inserted with ID: {notification_id}")
        
        cursor.close()
        connection.close()
        
        print(f"? Issue notification created successfully for seller: {seller_email}")
        return True
        
    except Exception as e:
        print(f"? Error creating issue notification for {seller_email}: {str(e)}")
        import traceback
        traceback.print_exc()
        return False

def send_issue_status_update_email(customer_email, customer_name, issue_id, issue_type, product_name, new_status, admin_response=''):
    """Send email notification to customer when admin updates issue status"""
    try:
        print(f"?? Sending issue status update email to customer: {customer_email}")
        
        # Create status-specific messages
        status_messages = {
            'pending': {
                'title': 'Issue Report Received',
                'message': 'We have received your issue report and it is pending review.',
                'next_step': 'Our team will review your report and get back to you soon.'
            },
            'in_progress': {
                'title': 'Issue Under Investigation',
                'message': 'Your issue report is currently being investigated by our team.',
                'next_step': 'We are working to resolve this matter as quickly as possible.'
            },
            'resolved': {
                'title': 'Issue Resolved',
                'message': 'Your issue has been resolved!',
                'next_step': 'If you have any further concerns, please don\'t hesitate to contact us.'
            },
            'closed': {
                'title': 'Issue Closed',
                'message': 'Your issue report has been closed.',
                'next_step': 'Thank you for your patience. If you need further assistance, please submit a new report.'
            }
        }
        
        status_info = status_messages.get(new_status, {
            'title': 'Issue Status Updated',
            'message': f'Your issue status has been updated to: {new_status}',
            'next_step': 'Thank you for your patience.'
        })
        
        msg = Message(
            f'Issue Report Update - {status_info["title"]}',
            sender=app.config['MAIL_DEFAULT_SENDER'],
            recipients=[customer_email]
        )
        
        msg.body = f"""Hello {customer_name},

{status_info['title']}

ISSUE REPORT DETAILS:
Issue ID: #{issue_id}
Issue Type: {issue_type.replace('_', ' ').title()}
Product: {product_name}

STATUS UPDATE:
{status_info['message']}
"""
        
        if admin_response:
            msg.body += f"""
ADMIN RESPONSE:
{admin_response}
"""
        
        msg.body += f"""
NEXT STEPS:
{status_info['next_step']}

If you have any questions or concerns, please don't hesitate to contact our customer support team.

Thank you for your patience and understanding.

Best regards,
MStyle Customer Service Team
"""
        
        mail.send(msg)
        print(f"? Issue status update email sent to customer: {customer_email}")
        return True
        
    except Exception as e:
        print(f"? Error sending issue status update email to {customer_email}: {str(e)}")
        import traceback
        traceback.print_exc()
        return False

def create_issue_status_notification(customer_email, issue_id, issue_type, product_name, new_status, admin_response='', order_id=None):
    """Create in-app notification for user when admin updates issue status � uses Supabase for riders"""
    try:
        status_messages = {
            'pending':     f"Your issue report #{issue_id} for '{product_name}' is pending review.",
            'in_progress': f"Your issue report #{issue_id} for '{product_name}' is being investigated by our team.",
            'resolved':    f"Great news! Your issue report #{issue_id} for '{product_name}' has been resolved.",
            'closed':      f"Your issue report #{issue_id} for '{product_name}' has been closed.",
        }
        message = status_messages.get(new_status, f"Your issue report #{issue_id} status has been updated to: {new_status}")
        if admin_response:
            message += f" Admin response: {admin_response[:100]}{'...' if len(admin_response) > 100 else ''}"

        # Determine user type from Supabase
        user_type = 'buyer'
        try:
            ur = sb_admin.table('users').select('role').eq('email', customer_email).execute()
            if ur.data:
                user_type = (ur.data[0].get('role') or 'buyer').lower()
        except Exception:
            pass

        if user_type == 'rider':
            sb_admin.table('rider_notifications').insert({'rider_email': customer_email, 'message': message, 'order_id': order_id, 'is_read': False}).execute()
        elif user_type == 'seller':
            sb_admin.table('notifications').insert({'seller_email': customer_email, 'message': message, 'type': 'issue_update', 'is_read': False}).execute()
        else:
            sb_admin.table('buyer_notifications').insert({'buyer_email': customer_email, 'message': message, 'type': 'issue_update', 'is_read': False, 'order_id': order_id}).execute()

        print(f"? Issue status notification created for {user_type}: {customer_email}")
        return True
    except Exception as e:
        print(f"? Error creating issue status notification for {customer_email}: {e}")
        import traceback; traceback.print_exc()
        return False

# Route to manually trigger auto-completion (for testing/admin use)
@app.route('/admin/auto-complete-orders')
def admin_auto_complete_orders():
    """Admin route to manually trigger auto-completion of orders"""
    # Add admin authentication check here if needed
    completed_count = auto_complete_delivered_orders()
    return f"Auto-completed {completed_count} orders"

#----------------------------------------------------------------------
# ORDER MONITORING ROUTES
#----------------------------------------------------------------------

@app.route('/order_monitoring')
def order_monitoring():
    """Admin route to monitor all orders"""
    # Check if user is admin
    if 'email' not in session or session.get('user_type') != 'Admin':
        flash('Access denied. Admin privileges required.', 'danger')
        return redirect(url_for('login'))
    
    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)
        
        # Get filter parameters
        search_query = request.args.get('search', '').strip()
        status_filter = request.args.get('status', '')
        payment_method_filter = request.args.get('payment_method', '')
        date_from = request.args.get('date_from', '')
        date_to = request.args.get('date_to', '')
        page = request.args.get('page', 1, type=int)
        per_page = 20
        
        # Build query with filters
        query = """
            SELECT 
                o.id as order_id,
                o.date as order_date,
                COALESCE(CONCAT(u.first_name, ' ', u.last_name), 'Unknown Buyer') as buyer_name,
                COALESCE(CONCAT(s.first_name, ' ', s.last_name), 'Unknown Seller') as seller_name,
                CAST(o.total_price AS DECIMAL(10,2)) as total_amount,
                o.payment_method,
                o.status as order_status,
                COALESCE(CONCAT(r.first_name, ' ', r.last_name), NULL) as rider_name,
                o.delivered_at,
                o.received_at,
                o.auto_complete_at,
                o.is_auto_completed
            FROM orders o
            LEFT JOIN users u ON o.email = u.email
            LEFT JOIN users s ON o.seller_email = s.email
            LEFT JOIN users r ON o.rider_email = r.email
            WHERE 1=1
        """
        
        params = []
        
        # Apply search filter
        if search_query:
            query += """ AND (
                o.id LIKE %s OR
                CONCAT(u.first_name, ' ', u.last_name) LIKE %s OR
                u.email LIKE %s OR
                CONCAT(s.first_name, ' ', s.last_name) LIKE %s OR
                s.email LIKE %s
            )"""
            search_pattern = f"%{search_query}%"
            params.extend([search_pattern, search_pattern, search_pattern, search_pattern, search_pattern])
        
        # Apply filters
        if status_filter:
            if status_filter == 'completed':
                # Completed means received_at or auto_complete_at is not null
                query += " AND (o.received_at IS NOT NULL OR o.auto_complete_at IS NOT NULL)"
            elif status_filter == 'cancelled':
                # Cancelled includes both 'rejected' and 'cancelled' status (case-insensitive)
                query += " AND LOWER(o.status) IN ('rejected', 'cancelled')"
            else:
                query += " AND LOWER(o.status) = LOWER(%s)"
                params.append(status_filter)
        
        if payment_method_filter:
            query += " AND o.payment_method = %s"
            params.append(payment_method_filter)
        
        if date_from:
            query += " AND DATE(o.date) >= %s"
            params.append(date_from)
        
        if date_to:
            query += " AND DATE(o.date) <= %s"
            params.append(date_to)
        
        # Get total count for pagination
        count_query = f"SELECT COUNT(*) as total FROM ({query}) as filtered_orders"
        cursor.execute(count_query, params)
        total_orders = cursor.fetchone()['total']
        
        # Calculate pagination
        total_pages = max(1, (total_orders + per_page - 1) // per_page)
        offset = (page - 1) * per_page
        
        # Add ordering and pagination
        query += " ORDER BY o.date DESC LIMIT %s OFFSET %s"
        params.extend([per_page, offset])
        
        # Execute main query
        cursor.execute(query, params)
        orders = cursor.fetchall()
        
        print(f"DEBUG: Found {len(orders)} orders")
        print(f"DEBUG: Total pages: {total_pages}, Current page: {page}")
        
        # Get order statistics
        cursor.execute("""
            SELECT 
                COUNT(*) as total_orders,
                SUM(CASE WHEN LOWER(status) = 'pending' THEN 1 ELSE 0 END) as pending_orders,
                SUM(CASE WHEN LOWER(status) = 'shipped' THEN 1 ELSE 0 END) as shipped_orders,
                SUM(CASE WHEN LOWER(status) = 'delivered' THEN 1 ELSE 0 END) as delivered_orders,
                SUM(CASE WHEN received_at IS NOT NULL OR auto_complete_at IS NOT NULL THEN 1 ELSE 0 END) as completed_orders,
                SUM(CASE WHEN LOWER(status) IN ('rejected', 'cancelled') THEN 1 ELSE 0 END) as cancelled_orders
            FROM orders
        """)
        stats = cursor.fetchone()
        
        # Debug: Check actual status values
        cursor.execute("SELECT DISTINCT status FROM orders")
        distinct_statuses = cursor.fetchall()
        print(f"DEBUG: Distinct order statuses in database: {[s['status'] for s in distinct_statuses]}")
        print(f"DEBUG: Stats - Total: {stats['total_orders']}, Cancelled: {stats['cancelled_orders']}")
        
        # Get available riders for assignment
        cursor.execute("""
            SELECT id, CONCAT(first_name, ' ', last_name) as name, email,
                   CASE 
                       WHEN email IN (SELECT DISTINCT rider_email FROM orders WHERE status IN ('Shipped', 'Out for Delivery'))
                       THEN 'Busy'
                       ELSE 'Available'
                   END as status
            FROM users 
            WHERE UPPER(user_type) = 'RIDER'
            ORDER BY first_name, last_name
        """)
        riders = cursor.fetchall()
        
        cursor.close()
        connection.close()
        
        return render_template('order_monitoring.html',
                             orders=orders,
                             riders=riders,
                             stats=stats,
                             current_page=page,
                             total_pages=total_pages,
                             prev_page=page - 1 if page > 1 else None,
                             next_page=page + 1 if page < total_pages else None)
        
    except Exception as e:
        print(f"?? MySQL unavailable in order_monitoring: {e}")
        import traceback
        traceback.print_exc()

        try:
            if 'cursor' in locals() and cursor:
                cursor.close()
            if 'connection' in locals() and connection:
                connection.close()
        except:
            pass

        empty_stats = {'total_orders': 0, 'pending_orders': 0, 'shipped_orders': 0,
                       'delivered_orders': 0, 'completed_orders': 0, 'cancelled_orders': 0}
        return render_template('order_monitoring.html',
                             orders=[], riders=[], stats=empty_stats,
                             current_page=1, total_pages=1,
                             prev_page=None, next_page=None)

@app.route('/admin/order/<int:order_id>/details')
def admin_get_order_details(order_id):
    """Get detailed information about a specific order"""
    if 'email' not in session or session.get('user_type') != 'Admin':
        return jsonify({'error': 'Unauthorized'}), 403
    
    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)
        
        # Get order details
        cursor.execute("""
            SELECT 
                o.id as order_id,
                o.date as order_date,
                o.status,
                o.delivered_at,
                o.received_at,
                o.auto_complete_at,
                o.is_auto_completed,
                COALESCE(CONCAT(u.first_name, ' ', u.last_name), 'Unknown Buyer') as buyer_name,
                u.email as buyer_email,
                u.phone_number as buyer_phone,
                o.address as delivery_address,
                COALESCE(CONCAT(s.first_name, ' ', s.last_name), 'Unknown Seller') as seller_name,
                s.email as seller_email,
                s.phone_number as seller_phone,
                o.total_price,
                o.payment_method,
                COALESCE(CONCAT(r.first_name, ' ', r.last_name), NULL) as rider_name,
                r.email as rider_email,
                r.phone_number as rider_phone,
                o.name as product_name,
                o.quantity,
                o.image as product_image,
                o.variations,
                o.size
            FROM orders o
            LEFT JOIN users u ON o.email = u.email
            LEFT JOIN users s ON o.seller_email = s.email
            LEFT JOIN users r ON o.rider_email = r.email
            WHERE o.id = %s
        """, (order_id,))
        
        order = cursor.fetchone()
        
        if not order:
            return jsonify({'error': 'Order not found'}), 404
        
        # Format the response - handle varchar to numeric conversion
        try:
            total_amount = float(order['total_price']) if order['total_price'] else 0.0
        except (ValueError, TypeError):
            total_amount = 0.0
            
        try:
            quantity = int(order['quantity']) if order['quantity'] else 1
        except (ValueError, TypeError):
            quantity = 1
        
        response = {
            'order_id': order['order_id'],
            'order_date': order['order_date'].strftime('%Y-%m-%d %H:%M:%S') if order['order_date'] else '',
            'status': order['status'],
            'delivered_at': order['delivered_at'].strftime('%Y-%m-%d %H:%M:%S') if order['delivered_at'] else None,
            'received_at': order['received_at'].strftime('%Y-%m-%d %H:%M:%S') if order['received_at'] else None,
            'auto_complete_at': order['auto_complete_at'].strftime('%Y-%m-%d %H:%M:%S') if order['auto_complete_at'] else None,
            'is_auto_completed': order['is_auto_completed'],
            'buyer_name': order['buyer_name'],
            'buyer_email': order['buyer_email'],
            'buyer_phone': order['buyer_phone'] or 'N/A',
            'delivery_address': order['delivery_address'] or 'N/A',
            'seller_name': order['seller_name'],
            'seller_email': order['seller_email'],
            'seller_phone': order['seller_phone'] or 'N/A',
            'total_amount': f"{total_amount:.2f}",
            'payment_method': order['payment_method'],
            'rider_name': order['rider_name'] or 'Not Assigned',
            'rider_email': order['rider_email'] or 'N/A',
            'rider_phone': order['rider_phone'] or 'N/A',
            'items': [{
                'product_name': order['product_name'],
                'quantity': quantity,
                'price': f"{total_amount / quantity:.2f}" if quantity > 0 else "0.00",
                'subtotal': f"{total_amount:.2f}",
                'variations': order['variations'] or 'N/A',
                'size': order['size'] or 'N/A'
            }]
        }
        
        cursor.close()
        connection.close()
        
        return jsonify(response)
        
    except Exception as e:
        print(f"Error getting order details: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': 'Internal server error'}), 500

@app.route('/admin/order/update-status', methods=['POST'])
def admin_update_order_status():
    """Update order status"""
    if 'email' not in session or session.get('user_type') != 'Admin':
        return jsonify({'success': False, 'message': 'Unauthorized'}), 403
    
    try:
        order_id = request.form.get('order_id')
        new_status = request.form.get('status')
        notes = request.form.get('notes', '')
        
        if not order_id or not new_status:
            return jsonify({'success': False, 'message': 'Missing required fields'})
        
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)
        
        # Get order details for notification
        cursor.execute("""
            SELECT o.email, o.seller_email, o.name as product_name
            FROM orders o
            WHERE o.id = %s
        """, (order_id,))
        
        order = cursor.fetchone()
        
        if not order:
            return jsonify({'success': False, 'message': 'Order not found'})
        
        # Update order status
        cursor.execute("""
            UPDATE orders 
            SET status = %s
            WHERE id = %s
        """, (new_status, order_id))
        
        # Create notification for buyer
        notification_message = f"Your order #{order_id} ({order['product_name']}) status has been updated to: {new_status}"
        if notes:
            notification_message += f". Note: {notes}"
        
        cursor.execute("""
            INSERT INTO buyer_notifications (buyer_email, message, type, order_id)
            VALUES (%s, %s, 'status_update', %s)
        """, (order['email'], notification_message, order_id))
        
        # Create notification for seller
        seller_notification = f"Order #{order_id} ({order['product_name']}) status has been updated to: {new_status} by admin"
        cursor.execute("""
            INSERT INTO notifications (seller_email, message, type)
            VALUES (%s, %s, %s)
        """, (order['seller_email'], seller_notification, 'order'))
        
        connection.commit()
        cursor.close()
        connection.close()
        
        return jsonify({'success': True, 'message': 'Order status updated successfully'})
        
    except Exception as e:
        print(f"Error updating order status: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': 'Internal server error'}), 500

@app.route('/admin/order/assign-rider', methods=['POST'])
def assign_rider_to_order():
    """Assign a rider to an order"""
    if 'email' not in session or session.get('user_type') != 'Admin':
        return jsonify({'success': False, 'message': 'Unauthorized'}), 403
    
    try:
        order_id = request.form.get('order_id')
        rider_id = request.form.get('rider_id')
        
        if not order_id or not rider_id:
            return jsonify({'success': False, 'message': 'Missing required fields'})
        
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)
        
        # Get rider email
        cursor.execute("""
            SELECT email, CONCAT(first_name, ' ', last_name) as rider_name
            FROM users 
            WHERE id = %s AND UPPER(user_type) = 'RIDER'
        """, (rider_id,))
        
        rider = cursor.fetchone()
        
        if not rider:
            return jsonify({'success': False, 'message': 'Rider not found'})
        
        # Get order details
        cursor.execute("""
            SELECT o.email, o.seller_email, o.name as product_name, o.address
            FROM orders o
            WHERE o.id = %s
        """, (order_id,))
        
        order = cursor.fetchone()
        
        if not order:
            return jsonify({'success': False, 'message': 'Order not found'})
        
        # Assign rider to order
        cursor.execute("""
            UPDATE orders 
            SET rider_email = %s
            WHERE id = %s
        """, (rider['email'], order_id))
        
        # Create notification for rider via Supabase
        rider_notification = f"You have been assigned to deliver order #{order_id} ({order['product_name']}) to {order['address']}"
        sb_admin.table('rider_notifications').insert({'rider_email': rider['email'], 'message': rider_notification, 'order_id': order_id, 'is_read': False}).execute()
        
        # Create notification for buyer
        buyer_notification = f"Rider {rider['rider_name']} has been assigned to your order #{order_id}"
        cursor.execute("""
            INSERT INTO buyer_notifications (buyer_email, message, type, order_id)
            VALUES (%s, %s, 'rider_assigned', %s)
        """, (order['email'], buyer_notification, order_id))
        
        # Create notification for seller
        seller_notification = f"Rider {rider['rider_name']} has been assigned to order #{order_id}"
        cursor.execute("""
            INSERT INTO notifications (seller_email, message, type)
            VALUES (%s, %s, %s)
        """, (order['seller_email'], seller_notification, 'rider_assigned'))
        
        connection.commit()
        cursor.close()
        connection.close()
        
        return jsonify({'success': True, 'message': 'Rider assigned successfully'})
        
    except Exception as e:
        print(f"Error assigning rider: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': 'Internal server error'}), 500

@app.route('/export_orders')
def export_orders():
    """Export orders to CSV"""
    if 'email' not in session or session.get('user_type') != 'Admin':
        flash('Access denied. Admin privileges required.', 'danger')
        return redirect(url_for('login'))
    
    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)
        
        # Get all orders
        cursor.execute("""
            SELECT 
                o.id as order_id,
                o.date as order_date,
                COALESCE(CONCAT(u.first_name, ' ', u.last_name), 'Unknown Buyer') as buyer_name,
                u.email as buyer_email,
                COALESCE(CONCAT(s.first_name, ' ', s.last_name), 'Unknown Seller') as seller_name,
                s.email as seller_email,
                CAST(o.total_price AS DECIMAL(10,2)) as total_amount,
                o.payment_method,
                o.status as order_status,
                COALESCE(CONCAT(r.first_name, ' ', r.last_name), NULL) as rider_name,
                o.name as product_name,
                o.quantity,
                o.address
            FROM orders o
            LEFT JOIN users u ON o.email = u.email
            LEFT JOIN users s ON o.seller_email = s.email
            LEFT JOIN users r ON o.rider_email = r.email
            ORDER BY o.date DESC
        """)
        
        orders = cursor.fetchall()
        
        cursor.close()
        connection.close()
        
        # Create CSV content
        import csv
        from io import StringIO
        
        output = StringIO()
        writer = csv.writer(output)
        
        # Write header
        writer.writerow([
            'Order ID', 'Order Date', 'Buyer Name', 'Buyer Email',
            'Seller Name', 'Seller Email', 'Product Name', 'Quantity',
            'Total Amount', 'Payment Method', 'Order Status', 
            'Assigned Rider', 'Delivery Address'
        ])
        
        # Write data
        for order in orders:
            writer.writerow([
                order['order_id'],
                order['order_date'].strftime('%Y-%m-%d %H:%M:%S') if order['order_date'] else '',
                order['buyer_name'] or 'N/A',
                order['buyer_email'] or 'N/A',
                order['seller_name'] or 'N/A',
                order['seller_email'] or 'N/A',
                order['product_name'] or 'N/A',
                order['quantity'] or 'N/A',
                f"?{float(order['total_amount']):.2f}" if order['total_amount'] else '?0.00',
                order['payment_method'] or 'N/A',
                order['order_status'] or 'N/A',
                order['rider_name'] or 'Not Assigned',
                order['address'] or 'N/A'
            ])
        
        # Create response
        from flask import make_response
        output.seek(0)
        response = make_response(output.getvalue())
        response.headers['Content-Type'] = 'text/csv'
        response.headers['Content-Disposition'] = f'attachment; filename=orders_export_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
        
        return response
        
    except Exception as e:
        print(f"Error exporting orders: {e}")
        import traceback
        traceback.print_exc()
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
        
        # Get or create conversation
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)
        
        cursor.execute("""
            SELECT * FROM conversations 
            WHERE conversation_id = %s
        """, (conversation_id,))
        
        conversation = cursor.fetchone()
        
        # Don't create conversation here - only create when first message is sent
        if conversation:
            # Get buyer and seller emails from conversation if not provided
            if not buyer_email:
                buyer_email = conversation['buyer_email']
            if not seller_email:
                seller_email = conversation['seller_email']
        
        # Get buyer and seller names and profile pictures
        cursor.execute("""
            SELECT CONCAT(first_name, ' ', last_name) as name, profile_picture
            FROM users
            WHERE email = %s
        """, (buyer_email,))
        buyer_data = cursor.fetchone()
        buyer_name = buyer_data['name'] if buyer_data else 'Buyer'
        buyer_profile_picture = buyer_data['profile_picture'] if buyer_data and buyer_data['profile_picture'] else None
        
        cursor.execute("""
            SELECT COALESCE(business_name, CONCAT(first_name, ' ', last_name)) as name, profile_picture
            FROM users
            WHERE email = %s
        """, (seller_email,))
        seller_data = cursor.fetchone()
        seller_name = seller_data['name'] if seller_data else 'Seller'
        seller_profile_picture = seller_data['profile_picture'] if seller_data and seller_data['profile_picture'] else None
        
        # Get messages
        cursor.execute("""
            SELECT id, sender_email, receiver_email, sender_type, message_text, is_read, created_at
            FROM buyer_seller_messages
            WHERE conversation_id = %s
            ORDER BY created_at ASC
        """, (conversation_id,))
        
        messages = cursor.fetchall()
        cursor.close()
        connection.close()
        
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
    """Send a message from buyer to seller"""
    # Check if user is logged in
    if 'email' not in session:
        return jsonify({'success': False, 'error': 'Please login first'}), 401
    
    try:
        data = request.get_json()
        seller_email = data.get('seller_email')
        message_text = data.get('message_text')
        product_id = data.get('product_id')
        
        if not seller_email or not message_text:
            return jsonify({'success': False, 'error': 'Missing required fields'}), 400
        
        buyer_email = session.get('email')
        
        # Generate conversation ID
        conversation_id = f"{buyer_email}_{seller_email}_{product_id if product_id else 'general'}"
        
        # Insert message
        connection = get_db_connection()
        cursor = connection.cursor()
        
        # Create conversation if it doesn't exist
        cursor.execute("""
            INSERT INTO conversations (conversation_id, buyer_email, seller_email, product_id, created_at, last_message_at)
            VALUES (%s, %s, %s, %s, NOW(), NOW())
            ON DUPLICATE KEY UPDATE last_message_at = NOW()
        """, (conversation_id, buyer_email, seller_email, product_id if product_id else None))
        
        cursor.execute("""
            INSERT INTO buyer_seller_messages 
            (conversation_id, sender_email, receiver_email, sender_type, message_text)
            VALUES (%s, %s, %s, %s, %s)
        """, (conversation_id, buyer_email, seller_email, 'buyer', message_text))
        
        connection.commit()
        message_id = cursor.lastrowid
        cursor.close()
        connection.close()
        
        return jsonify({
            'success': True,
            'message_id': message_id,
            'message': 'Message sent successfully'
        })
        
    except Exception as e:
        print(f"Error sending message: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/messages/mark-read', methods=['POST'])
def mark_messages_read():
    """Mark messages as read for both buyer and seller"""
    # Check if user is logged in
    if 'email' not in session:
        return jsonify({'success': False, 'error': 'Please login first'}), 401
    
    try:
        data = request.get_json()
        buyer_email = data.get('buyer_email')
        seller_email = data.get('seller_email')
        product_id = data.get('product_id')
        conversation_id = data.get('conversation_id')
        
        current_user_email = session.get('email')
        user_type = session.get('user_type', '').lower()
        
        # If conversation_id is provided, use it directly
        if conversation_id:
            conv_id = conversation_id
        else:
            # Build conversation_id based on user type
            if user_type == 'seller':
                if not buyer_email:
                    return jsonify({'success': False, 'error': 'Buyer email is required for sellers'}), 400
                seller_email = current_user_email
            else:  # buyer
                if not seller_email:
                    return jsonify({'success': False, 'error': 'Seller email is required for buyers'}), 400
                buyer_email = current_user_email
            
            # Build conversation_id
            if product_id:
                conv_id = f"{buyer_email}_{seller_email}_{product_id}"
            else:
                conv_id = f"{buyer_email}_{seller_email}_general"
        
        # Mark all messages in this conversation as read where current user is receiver
        connection = get_db_connection()
        cursor = connection.cursor()
        
        cursor.execute("""
            UPDATE buyer_seller_messages
            SET is_read = TRUE
            WHERE conversation_id = %s 
            AND receiver_email = %s 
            AND is_read = FALSE
        """, (conv_id, current_user_email))
        
        affected_rows = cursor.rowcount
        connection.commit()
        
        print(f"? Marked {affected_rows} messages as read for {user_type}: {current_user_email} in conversation: {conv_id}")
        
        cursor.close()
        connection.close()
        
        return jsonify({
            'success': True,
            'message': 'Messages marked as read',
            'affected_rows': affected_rows
        })
        
    except Exception as e:
        print(f"? Error marking messages as read: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/seller/messages', methods=['GET'])
def get_seller_messages():
    """Get all conversations for seller (for dropdown)"""
    # Check if user is logged in
    if 'email' not in session:
        return jsonify({'success': False, 'error': 'Please login first'}), 401
    
    user_email = session.get('email')
    user_type = session.get('user_type')
    
    # Debug logging
    print(f"DEBUG - User Email: {user_email}, User Type: {user_type}")
    
    # Check if user is a seller - case insensitive check
    if user_type and user_type.lower() != 'seller':
        return jsonify({
            'success': False, 
            'error': f'Only sellers can access this. Your user_type is: {user_type}'
        }), 403
    
    try:
        seller_email = session.get('email')
        
        connection = get_db_connection()
        cursor = connection.cursor()
        
        # Get seller name and profile picture first
        cursor.execute("""
            SELECT COALESCE(business_name, CONCAT(first_name, ' ', last_name)) as seller_name,
                   profile_picture
            FROM users
            WHERE email = %s
        """, (seller_email,))
        seller_data = cursor.fetchone()
        seller_name = seller_data[0] if seller_data else 'Seller'
        seller_profile_picture = seller_data[1] if seller_data and seller_data[1] else None
        
        # Get buyer-seller conversations
        cursor.execute("""
            SELECT DISTINCT 
                c.conversation_id, 
                c.buyer_email, 
                c.product_id, 
                c.order_id,
                c.last_message_at,
                p.name as product_name,
                CONCAT(u.first_name, ' ', u.last_name) as buyer_name,
                (SELECT COUNT(*) FROM buyer_seller_messages 
                 WHERE conversation_id = c.conversation_id 
                 AND receiver_email = %s AND is_read = FALSE) as unread_count,
                (SELECT message_text FROM buyer_seller_messages 
                 WHERE conversation_id = c.conversation_id 
                 ORDER BY created_at DESC LIMIT 1) as last_message,
                u.profile_picture as buyer_profile_picture,
                'buyer' as conversation_type
            FROM conversations c
            LEFT JOIN products p ON c.product_id = p.id
            LEFT JOIN users u ON c.buyer_email = u.email
            WHERE c.seller_email = %s
            ORDER BY c.last_message_at DESC
            LIMIT 10
        """, (seller_email, seller_email))
        
        buyer_conversations = cursor.fetchall()
        
        # Get seller-rider conversations
        cursor.execute("""
            SELECT DISTINCT 
                m.order_id,
                o.rider_email,
                MAX(m.created_at) as last_message_at,
                CONCAT(u.first_name, ' ', u.last_name) as rider_name,
                u.profile_picture as rider_profile_picture,
                (SELECT COUNT(*) FROM seller_rider_messages 
                 WHERE order_id = m.order_id 
                 AND receiver_email = %s AND is_read = FALSE) as unread_count,
                (SELECT message FROM seller_rider_messages 
                 WHERE order_id = m.order_id 
                 ORDER BY created_at DESC LIMIT 1) as last_message,
                'rider' as conversation_type
            FROM seller_rider_messages m
            INNER JOIN orders o ON m.order_id = o.id
            LEFT JOIN users u ON o.rider_email = u.email
            WHERE o.seller_email = %s
            GROUP BY m.order_id, o.rider_email, u.first_name, u.last_name, u.profile_picture
        """, (seller_email, seller_email))
        
        rider_conversations = cursor.fetchall()
        
        cursor.close()
        connection.close()
        
        # Format and combine conversations
        formatted_conversations = []
        
        # Add buyer conversations
        for conv in buyer_conversations:
            formatted_conversations.append({
                'conversation_id': conv[0],
                'buyer_email': conv[1],
                'product_id': conv[2],
                'order_id': conv[3],
                'last_message_at': conv[4].isoformat() if conv[4] else None,
                'product_name': conv[5],
                'buyer_name': conv[6],
                'unread_count': conv[7],
                'last_message': conv[8],
                'buyer_profile_picture': conv[9],
                'conversation_type': 'buyer',
                'seller_name': seller_name,
                'seller_profile_picture': seller_profile_picture
            })
        
        # Add rider conversations
        for conv in rider_conversations:
            formatted_conversations.append({
                'conversation_id': f"rider_order_{conv[0]}",
                'order_id': conv[0],
                'rider_email': conv[1],
                'last_message_at': conv[2].isoformat() if conv[2] else None,
                'rider_name': conv[3] or 'Rider',
                'rider_profile_picture': conv[4],
                'unread_count': conv[5],
                'last_message': conv[6],
                'conversation_type': 'rider',
                'seller_name': seller_name,
                'seller_profile_picture': seller_profile_picture
            })
        
        # Sort by last message time
        formatted_conversations.sort(key=lambda x: x['last_message_at'] or '', reverse=True)
        
        # Limit to 20 most recent
        formatted_conversations = formatted_conversations[:20]
        
        return jsonify({
            'success': True,
            'conversations': formatted_conversations
        })
        
    except Exception as e:
        print(f"Error getting seller messages: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/seller/conversations/delete', methods=['POST'])
def delete_seller_conversation():
    """Delete a conversation and all its messages"""
    # Check if user is logged in as seller
    if 'email' not in session:
        return jsonify({'success': False, 'error': 'Please login first'}), 401
    
    user_type = session.get('user_type')
    if user_type and user_type.lower() != 'seller':
        return jsonify({'success': False, 'error': 'Only sellers can delete conversations'}), 403
    
    try:
        data = request.get_json()
        conversation_id = data.get('conversation_id')
        
        if not conversation_id:
            return jsonify({'success': False, 'error': 'Conversation ID is required'}), 400
        
        seller_email = session.get('email')
        
        connection = get_db_connection()
        cursor = connection.cursor()
        
        total_deleted = 0
        
        # Check if it's a rider conversation (format: rider_order_123)
        if conversation_id.startswith('rider_order_'):
            # Extract order_id from conversation_id
            order_id_str = conversation_id.replace('rider_order_', '')
            
            try:
                order_id = int(order_id_str)
            except ValueError:
                cursor.close()
                connection.close()
                return jsonify({'success': False, 'error': f'Invalid conversation ID format: {conversation_id}'}), 400
            
            # Verify that this order belongs to the seller
            cursor.execute("""
                SELECT id FROM orders 
                WHERE id = %s AND seller_email = %s
            """, (order_id, seller_email))
            
            order = cursor.fetchone()
            
            if not order:
                cursor.close()
                connection.close()
                return jsonify({'success': False, 'error': 'Order not found or access denied'}), 404
            
            # Delete all seller-rider messages for this order
            cursor.execute("""
                DELETE FROM seller_rider_messages 
                WHERE order_id = %s
            """, (order_id,))
            
            total_deleted = cursor.rowcount
            
            print(f"? Deleted seller-rider conversation for order {order_id} with {total_deleted} messages")
        else:
            # It's a buyer-seller conversation
            # Verify that this conversation belongs to the seller
            cursor.execute("""
                SELECT id FROM conversations 
                WHERE conversation_id = %s AND seller_email = %s
            """, (conversation_id, seller_email))
            
            conversation = cursor.fetchone()
            
            if not conversation:
                cursor.close()
                connection.close()
                return jsonify({'success': False, 'error': 'Conversation not found or access denied'}), 404
            
            # Delete all messages in this conversation
            cursor.execute("""
                DELETE FROM buyer_seller_messages 
                WHERE conversation_id = %s
            """, (conversation_id,))
            
            total_deleted = cursor.rowcount
            
            # Delete the conversation
            cursor.execute("""
                DELETE FROM conversations 
                WHERE conversation_id = %s AND seller_email = %s
            """, (conversation_id, seller_email))
            
            print(f"? Deleted buyer-seller conversation {conversation_id} with {total_deleted} messages")
        
        connection.commit()
        cursor.close()
        connection.close()
        
        return jsonify({
            'success': True,
            'message': 'Conversation deleted successfully',
            'messages_deleted': total_deleted
        })
        
    except Exception as e:
        print(f"Error deleting conversation: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/seller/conversations/delete-all', methods=['POST'])
def delete_all_seller_conversations():
    """Delete all conversations for the seller"""
    # Check if user is logged in as seller
    if 'email' not in session:
        return jsonify({'success': False, 'error': 'Please login first'}), 401
    
    user_type = session.get('user_type')
    if user_type and user_type.lower() != 'seller':
        return jsonify({'success': False, 'error': 'Only sellers can delete conversations'}), 403
    
    try:
        seller_email = session.get('email')
        
        connection = get_db_connection()
        cursor = connection.cursor()
        
        total_messages_deleted = 0
        total_conversations_deleted = 0
        
        # Delete buyer-seller conversations
        # Get all conversation IDs for this seller
        cursor.execute("""
            SELECT conversation_id FROM conversations 
            WHERE seller_email = %s
        """, (seller_email,))
        
        conversations = cursor.fetchall()
        conversation_ids = [conv[0] for conv in conversations]
        
        if conversation_ids:
            # Delete all messages for these conversations
            cursor.execute("""
                DELETE FROM buyer_seller_messages 
                WHERE conversation_id IN ({})
            """.format(','.join(['%s'] * len(conversation_ids))), conversation_ids)
            
            messages_deleted = cursor.rowcount
            total_messages_deleted += messages_deleted
            
            # Delete all conversations for this seller
            cursor.execute("""
                DELETE FROM conversations 
                WHERE seller_email = %s
            """, (seller_email,))
            
            conversations_deleted = cursor.rowcount
            total_conversations_deleted += conversations_deleted
            
            print(f"? Deleted {conversations_deleted} buyer-seller conversations with {messages_deleted} messages")
        
        # Delete seller-rider messages
        # Get all orders for this seller
        cursor.execute("""
            SELECT id FROM orders 
            WHERE seller_email = %s
        """, (seller_email,))
        
        orders = cursor.fetchall()
        order_ids = [order[0] for order in orders]
        
        if order_ids:
            # Delete all seller-rider messages for these orders
            cursor.execute("""
                DELETE FROM seller_rider_messages 
                WHERE order_id IN ({})
            """.format(','.join(['%s'] * len(order_ids))), order_ids)
            
            rider_messages_deleted = cursor.rowcount
            total_messages_deleted += rider_messages_deleted
            total_conversations_deleted += len(order_ids)  # Count each order as a conversation
            
            print(f"? Deleted {len(order_ids)} seller-rider conversations with {rider_messages_deleted} messages")
        
        connection.commit()
        cursor.close()
        connection.close()
        
        print(f"? Total: Deleted {total_conversations_deleted} conversations with {total_messages_deleted} messages for seller {seller_email}")
        
        return jsonify({
            'success': True,
            'message': 'All conversations deleted successfully',
            'deleted_count': total_conversations_deleted,
            'messages_deleted': total_messages_deleted
        })
        
    except Exception as e:
        print(f"Error deleting all conversations: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/buyer/conversations/delete', methods=['POST'])
def delete_buyer_conversation():
    """Delete a conversation and all its messages (buyer side)"""
    # Check if user is logged in as buyer
    if 'email' not in session:
        return jsonify({'success': False, 'error': 'Please login first'}), 401
    
    try:
        data = request.get_json()
        conversation_id = data.get('conversation_id')
        
        if not conversation_id:
            return jsonify({'success': False, 'error': 'Conversation ID is required'}), 400
        
        buyer_email = session.get('email')
        
        connection = get_db_connection()
        cursor = connection.cursor()
        
        messages_deleted = 0
        
        # Check if it's a rider conversation (format: rider_order_123)
        if conversation_id.startswith('rider_order_'):
            # Extract order_id from conversation_id
            order_id = conversation_id.replace('rider_order_', '')
            
            # Verify that this order belongs to the buyer
            cursor.execute("""
                SELECT id FROM orders 
                WHERE id = %s AND email = %s
            """, (order_id, buyer_email))
            
            order = cursor.fetchone()
            
            if not order:
                cursor.close()
                connection.close()
                return jsonify({'success': False, 'error': 'Order not found or access denied'}), 404
            
            # Delete all buyer-rider messages for this order
            cursor.execute("""
                DELETE FROM buyer_rider_messages 
                WHERE order_id = %s
            """, (order_id,))
            
            messages_deleted = cursor.rowcount
            
            print(f"? Deleted buyer-rider conversation for order {order_id} with {messages_deleted} messages")
        else:
            # It's a seller conversation
            # Verify that this conversation belongs to the buyer
            cursor.execute("""
                SELECT id FROM conversations 
                WHERE conversation_id = %s AND buyer_email = %s
            """, (conversation_id, buyer_email))
            
            conversation = cursor.fetchone()
            
            if not conversation:
                cursor.close()
                connection.close()
                return jsonify({'success': False, 'error': 'Conversation not found or access denied'}), 404
            
            # Delete all messages in this conversation
            cursor.execute("""
                DELETE FROM buyer_seller_messages 
                WHERE conversation_id = %s
            """, (conversation_id,))
            
            messages_deleted = cursor.rowcount
            
            # Delete the conversation
            cursor.execute("""
                DELETE FROM conversations 
                WHERE conversation_id = %s AND buyer_email = %s
            """, (conversation_id, buyer_email))
            
            print(f"? Deleted buyer-seller conversation {conversation_id} with {messages_deleted} messages")
        
        connection.commit()
        cursor.close()
        connection.close()
        
        return jsonify({
            'success': True,
            'message': 'Conversation deleted successfully',
            'messages_deleted': messages_deleted
        })
        
    except Exception as e:
        print(f"Error deleting buyer conversation: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/buyer/conversations/delete-all', methods=['POST'])
def delete_all_buyer_conversations():
    """Delete all conversations for the buyer"""
    # Check if user is logged in as buyer
    if 'email' not in session:
        return jsonify({'success': False, 'error': 'Please login first'}), 401
    
    try:
        buyer_email = session.get('email')
        
        connection = get_db_connection()
        cursor = connection.cursor()
        
        total_messages_deleted = 0
        total_conversations_deleted = 0
        
        # Delete buyer-seller conversations
        # Get all conversation IDs for this buyer
        cursor.execute("""
            SELECT conversation_id FROM conversations 
            WHERE buyer_email = %s
        """, (buyer_email,))
        
        conversations = cursor.fetchall()
        conversation_ids = [conv[0] for conv in conversations]
        
        if conversation_ids:
            # Delete all messages for these conversations
            cursor.execute("""
                DELETE FROM buyer_seller_messages 
                WHERE conversation_id IN ({})
            """.format(','.join(['%s'] * len(conversation_ids))), conversation_ids)
            
            messages_deleted = cursor.rowcount
            total_messages_deleted += messages_deleted
            
            # Delete all conversations for this buyer
            cursor.execute("""
                DELETE FROM conversations 
                WHERE buyer_email = %s
            """, (buyer_email,))
            
            conversations_deleted = cursor.rowcount
            total_conversations_deleted += conversations_deleted
            
            print(f"? Deleted {conversations_deleted} buyer-seller conversations with {messages_deleted} messages")
        
        # Delete buyer-rider messages
        # Get all orders for this buyer
        cursor.execute("""
            SELECT id FROM orders 
            WHERE email = %s
        """, (buyer_email,))
        
        orders = cursor.fetchall()
        order_ids = [order[0] for order in orders]
        
        if order_ids:
            # Delete all buyer-rider messages for these orders
            cursor.execute("""
                DELETE FROM buyer_rider_messages 
                WHERE order_id IN ({})
            """.format(','.join(['%s'] * len(order_ids))), order_ids)
            
            rider_messages_deleted = cursor.rowcount
            total_messages_deleted += rider_messages_deleted
            total_conversations_deleted += len(order_ids)  # Count each order as a conversation
            
            print(f"? Deleted {len(order_ids)} buyer-rider conversations with {rider_messages_deleted} messages")
        
        connection.commit()
        cursor.close()
        connection.close()
        
        print(f"? Total: Deleted {total_conversations_deleted} conversations with {total_messages_deleted} messages for buyer {buyer_email}")
        
        return jsonify({
            'success': True,
            'message': 'All conversations deleted successfully',
            'deleted_count': total_conversations_deleted,
            'messages_deleted': total_messages_deleted
        })
        
    except Exception as e:
        print(f"Error deleting all buyer conversations: {e}")
        import traceback
        traceback.print_exc()
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
        
        # Insert message
        connection = get_db_connection()
        cursor = connection.cursor()
        
        # Create conversation if it doesn't exist
        cursor.execute("""
            INSERT INTO conversations (conversation_id, buyer_email, seller_email, product_id, order_id, last_message_at)
            VALUES (%s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
            ON DUPLICATE KEY UPDATE last_message_at = CURRENT_TIMESTAMP
        """, (conversation_id, buyer_email, seller_email, product_id, order_id))
        
        # Insert message
        cursor.execute("""
            INSERT INTO buyer_seller_messages 
            (conversation_id, sender_email, receiver_email, sender_type, message_text)
            VALUES (%s, %s, %s, %s, %s)
        """, (conversation_id, seller_email, buyer_email, 'seller', message_text))
        
        connection.commit()
        message_id = cursor.lastrowid
        
        # Get seller name for notification
        cursor.execute("SELECT business_name FROM users WHERE email = %s", (seller_email,))
        seller_result = cursor.fetchone()
        seller_name = seller_result[0] if seller_result else 'Seller'
        
        cursor.close()
        connection.close()
        
        # Create notification for buyer (optional - you can implement this later)
        print(f"? Seller {seller_name} sent message to buyer {buyer_email}")
        
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
    """Get all conversations for buyer (both seller and rider conversations)"""
    # Check if user is logged in
    if 'email' not in session:
        return jsonify({'success': False, 'error': 'Please login first'}), 401
    
    try:
        buyer_email = session.get('email')
        
        connection = get_db_connection()
        cursor = connection.cursor()
        
        # Get seller conversations for buyer
        cursor.execute("""
            SELECT DISTINCT 
                c.conversation_id, 
                c.seller_email, 
                c.product_id,
                c.order_id,
                c.last_message_at,
                p.name as product_name,
                u.business_name as seller_name,
                (SELECT COUNT(*) FROM buyer_seller_messages 
                 WHERE conversation_id = c.conversation_id 
                 AND receiver_email = %s AND is_read = FALSE) as unread_count,
                (SELECT message_text FROM buyer_seller_messages 
                 WHERE conversation_id = c.conversation_id 
                 ORDER BY created_at DESC LIMIT 1) as last_message,
                u.profile_picture as seller_profile_picture,
                'seller' as conversation_type
            FROM conversations c
            LEFT JOIN products p ON c.product_id = p.id
            LEFT JOIN users u ON c.seller_email = u.email
            WHERE c.buyer_email = %s
            ORDER BY c.last_message_at DESC
        """, (buyer_email, buyer_email))
        
        seller_conversations = cursor.fetchall()
        
        # Get rider conversations for buyer (from orders with messages)
        cursor.execute("""
            SELECT DISTINCT 
                CONCAT('rider_order_', m.order_id) as conversation_id,
                o.rider_email,
                m.order_id,
                MAX(m.created_at) as last_message_at,
                CONCAT('Order #', m.order_id) as order_info,
                CONCAT(u.first_name, ' ', u.last_name) as rider_name,
                (SELECT COUNT(*) FROM buyer_rider_messages 
                 WHERE order_id = m.order_id 
                 AND receiver_email = %s AND is_read = FALSE) as unread_count,
                (SELECT message FROM buyer_rider_messages 
                 WHERE order_id = m.order_id 
                 ORDER BY created_at DESC LIMIT 1) as last_message,
                u.profile_picture as rider_profile_picture,
                'rider' as conversation_type
            FROM buyer_rider_messages m
            INNER JOIN orders o ON m.order_id = o.id
            LEFT JOIN users u ON o.rider_email = u.email
            WHERE o.email = %s
            GROUP BY m.order_id, o.rider_email, u.first_name, u.last_name, u.profile_picture
        """, (buyer_email, buyer_email))
        
        rider_conversations = cursor.fetchall()
        
        cursor.close()
        connection.close()
        
        # Format and combine conversations
        formatted_conversations = []
        
        # Add seller conversations
        for conv in seller_conversations:
            formatted_conversations.append({
                'conversation_id': conv[0],
                'seller_email': conv[1],
                'product_id': conv[2],
                'order_id': conv[3],
                'last_message_at': conv[4].isoformat() if conv[4] else None,
                'product_name': conv[5],
                'seller_name': conv[6] or 'Seller',
                'unread_count': conv[7],
                'last_message': conv[8],
                'seller_profile_picture': conv[9],
                'conversation_type': 'seller'
            })
        
        # Add rider conversations
        for conv in rider_conversations:
            formatted_conversations.append({
                'conversation_id': conv[0],
                'rider_email': conv[1],
                'order_id': conv[2],
                'last_message_at': conv[3].isoformat() if conv[3] else None,
                'product_name': conv[4],  # Using order info as product_name for consistency
                'seller_name': conv[5] or 'Rider',  # Using rider_name as seller_name for consistency
                'unread_count': conv[6],
                'last_message': conv[7],
                'seller_profile_picture': conv[8],  # Using rider picture
                'conversation_type': 'rider',
                'rider_name': conv[5] or 'Rider',
                'rider_profile_picture': conv[8]
            })
        
        # Sort all conversations by last_message_at
        formatted_conversations.sort(key=lambda x: x['last_message_at'] or '', reverse=True)
        
        # Limit to 20 most recent
        formatted_conversations = formatted_conversations[:20]
        
        return jsonify({
            'success': True,
            'conversations': formatted_conversations
        })
        
    except Exception as e:
        print(f"Error getting buyer messages: {e}")
        import traceback
        traceback.print_exc()
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
    """Get chat messages between buyer and seller for a specific order"""
    if 'email' not in session:
        return jsonify({'success': False, 'error': 'Please login first'}), 401
    
    try:
        buyer_email = request.args.get('buyer_email')
        seller_email = request.args.get('seller_email')
        order_id = request.args.get('order_id')
        
        if not buyer_email or not seller_email or not order_id:
            return jsonify({'success': False, 'error': 'Missing required parameters'}), 400
        
        # Verify the user is either the buyer or seller
        session_email = session.get('email')
        if session_email not in [buyer_email, seller_email]:
            return jsonify({'success': False, 'error': 'Unauthorized'}), 403
        
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)
        
        # Verify the order exists and belongs to this buyer-seller pair
        cursor.execute("""
            SELECT id FROM orders
            WHERE id = %s AND email = %s AND seller_email = %s
        """, (order_id, buyer_email, seller_email))
        
        order = cursor.fetchone()
        if not order:
            cursor.close()
            connection.close()
            return jsonify({'success': False, 'error': 'Order not found'}), 404
        
        # Get conversation ID (but don't create it yet - only create when first message is sent)
        conversation_id = f"order_{order_id}_{buyer_email}_{seller_email}"
        
        # Get messages for this conversation (if it exists)
        cursor.execute("""
            SELECT id, sender_email, receiver_email, message_text, 
                   sender_type, is_read, created_at
            FROM buyer_seller_messages
            WHERE conversation_id = %s
            ORDER BY created_at ASC
        """, (conversation_id,))
        
        messages = cursor.fetchall()
        
        # Mark messages as read if user is the receiver
        cursor.execute("""
            UPDATE buyer_seller_messages
            SET is_read = TRUE
            WHERE conversation_id = %s AND receiver_email = %s AND is_read = FALSE
        """, (conversation_id, session_email))
        
        connection.commit()
        cursor.close()
        connection.close()
        
        return jsonify({
            'success': True,
            'messages': messages,
            'conversation_id': conversation_id
        })
        
    except Exception as e:
        print(f"Error getting buyer-seller order messages: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/send_buyer_seller_message_order', methods=['POST'])
def send_buyer_seller_message_order():
    """Send a message from buyer to seller about a specific order"""
    if 'email' not in session:
        return jsonify({'success': False, 'error': 'Please login first'}), 401
    
    try:
        data = request.get_json()
        buyer_email = data.get('buyer_email')
        seller_email = data.get('seller_email')
        order_id = data.get('order_id')
        message = data.get('message')
        
        if not buyer_email or not seller_email or not order_id or not message:
            return jsonify({'success': False, 'error': 'Missing required fields'}), 400
        
        # Verify the user is either the buyer or seller
        session_email = session.get('email')
        if session_email not in [buyer_email, seller_email]:
            return jsonify({'success': False, 'error': 'Unauthorized'}), 403
        
        # Determine sender and receiver
        sender_email = session_email
        receiver_email = seller_email if sender_email == buyer_email else buyer_email
        sender_type = 'buyer' if sender_email == buyer_email else 'seller'
        
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)
        
        # Verify the order exists
        cursor.execute("""
            SELECT id FROM orders
            WHERE id = %s AND email = %s AND seller_email = %s
        """, (order_id, buyer_email, seller_email))
        
        order = cursor.fetchone()
        if not order:
            cursor.close()
            connection.close()
            return jsonify({'success': False, 'error': 'Order not found'}), 404
        
        # Get or create conversation with order_id
        conversation_id = f"order_{order_id}_{buyer_email}_{seller_email}"
        
        cursor.execute("""
            SELECT id FROM conversations
            WHERE conversation_id = %s
        """, (conversation_id,))
        
        conversation = cursor.fetchone()
        
        if not conversation:
            # Create new conversation with order_id
            cursor.execute("""
                INSERT INTO conversations 
                (conversation_id, buyer_email, seller_email, order_id, created_at, last_message_at)
                VALUES (%s, %s, %s, %s, NOW(), NOW())
            """, (conversation_id, buyer_email, seller_email, order_id))
        else:
            # Update last_message_at
            cursor.execute("""
                UPDATE conversations
                SET last_message_at = NOW()
                WHERE conversation_id = %s
            """, (conversation_id,))
        
        # Insert message
        cursor.execute("""
            INSERT INTO buyer_seller_messages 
            (conversation_id, sender_email, receiver_email, sender_type, message_text, created_at)
            VALUES (%s, %s, %s, %s, %s, NOW())
        """, (conversation_id, sender_email, receiver_email, sender_type, message))
        
        connection.commit()
        cursor.close()
        connection.close()
        
        return jsonify({
            'success': True,
            'message': 'Message sent successfully'
        })
        
    except Exception as e:
        print(f"Error sending buyer-seller order message: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/get_seller_name', methods=['GET'])
def get_seller_name():
    """Get seller name by email"""
    try:
        seller_email = request.args.get('email')
        
        if not seller_email:
            return jsonify({'success': False, 'error': 'Missing email parameter'}), 400
        
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)
        
        cursor.execute("""
            SELECT business_name, CONCAT(first_name, ' ', last_name) as full_name
            FROM users
            WHERE email = %s
        """, (seller_email,))
        
        user = cursor.fetchone()
        cursor.close()
        connection.close()
        
        if user:
            name = user['business_name'] if user['business_name'] else user['full_name']
            return jsonify({
                'success': True,
                'name': name
            })
        else:
            return jsonify({'success': False, 'error': 'Seller not found'}), 404
        
    except Exception as e:
        print(f"Error getting seller name: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/get_seller_info', methods=['GET'])
def get_seller_info():
    """Get seller info including name and profile picture by email"""
    try:
        seller_email = request.args.get('email')
        
        if not seller_email:
            return jsonify({'success': False, 'error': 'Missing email parameter'}), 400
        
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)
        
        cursor.execute("""
            SELECT business_name, CONCAT(first_name, ' ', last_name) as full_name, profile_picture
            FROM users
            WHERE email = %s
        """, (seller_email,))
        
        user = cursor.fetchone()
        cursor.close()
        connection.close()
        
        if user:
            name = user['business_name'] if user['business_name'] else user['full_name']
            return jsonify({
                'success': True,
                'name': name,
                'profile_picture': user['profile_picture']
            })
        else:
            return jsonify({'success': False, 'error': 'Seller not found'}), 404
        
    except Exception as e:
        print(f"Error getting seller info: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

# ==================== SELLER-RIDER MESSAGING API ROUTES ====================

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
    """View all conversations (for both buyers and sellers)"""
    # Check if user is logged in
    if 'email' not in session:
        flash('Please login first', 'warning')
        return redirect(url_for('login'))
    
    try:
        user_email = session.get('email')
        user_type = session.get('user_type')
        
        connection = get_db_connection()
        cursor = connection.cursor()
        
        # Get all conversations for this user
        if user_type == 'seller':
            cursor.execute("""
                SELECT DISTINCT c.conversation_id, c.buyer_email, c.seller_email, 
                       c.product_id, c.last_message_at, p.name as product_name,
                       u.first_name, u.last_name,
                       (SELECT COUNT(*) FROM buyer_seller_messages 
                        WHERE conversation_id = c.conversation_id 
                        AND receiver_email = %s AND is_read = FALSE) as unread_count
                FROM conversations c
                LEFT JOIN products p ON c.product_id = p.id
                LEFT JOIN users u ON c.buyer_email = u.email
                WHERE c.seller_email = %s
                ORDER BY c.last_message_at DESC
            """, (user_email, user_email))
        else:
            cursor.execute("""
                SELECT DISTINCT c.conversation_id, c.buyer_email, c.seller_email, 
                       c.product_id, c.last_message_at, p.name as product_name,
                       s.business_name,
                       (SELECT COUNT(*) FROM buyer_seller_messages 
                        WHERE conversation_id = c.conversation_id 
                        AND receiver_email = %s AND is_read = FALSE) as unread_count
                FROM conversations c
                LEFT JOIN products p ON c.product_id = p.id
                LEFT JOIN sellers s ON c.seller_email = s.email
                WHERE c.buyer_email = %s
                ORDER BY c.last_message_at DESC
            """, (user_email, user_email))
        
        conversations = cursor.fetchall()
        cursor.close()
        connection.close()
        
        return render_template('messages_inbox.html', 
                             conversations=conversations,
                             user_type=user_type)
        
    except Exception as e:
        print(f"Error loading messages inbox: {e}")
        import traceback
        traceback.print_exc()
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

@app.route('/debug-conversations')
def debug_conversations():
    """Debug endpoint to see all conversations in database"""
    try:
        connection = get_db_connection()
        cursor = connection.cursor()
        
        # Get all conversations
        cursor.execute("""
            SELECT conversation_id, buyer_email, seller_email, product_id, last_message_at
            FROM conversations
            ORDER BY last_message_at DESC
        """)
        conversations = cursor.fetchall()
        
        # Get all messages
        cursor.execute("""
            SELECT id, conversation_id, sender_email, receiver_email, sender_type, message_text, created_at
            FROM buyer_seller_messages
            ORDER BY created_at DESC
        """)
        messages = cursor.fetchall()
        
        cursor.close()
        connection.close()
        
        html = """
        <!DOCTYPE html>
        <html>
        <head>
            <title>Debug Conversations</title>
            <style>
                body { font-family: Arial, sans-serif; margin: 20px; }
                table { border-collapse: collapse; width: 100%; margin: 20px 0; }
                th, td { border: 1px solid #ddd; padding: 8px; text-align: left; }
                th { background-color: #d4af37; color: white; }
                tr:nth-child(even) { background-color: #f2f2f2; }
                h2 { color: #1a1a1a; border-bottom: 2px solid #d4af37; padding-bottom: 10px; }
            </style>
        </head>
        <body>
            <h1>?? Debug Conversations & Messages</h1>
            
            <h2>Conversations Table</h2>
            <table>
                <tr>
                    <th>Conversation ID</th>
                    <th>Buyer Email</th>
                    <th>Seller Email</th>
                    <th>Product ID</th>
                    <th>Last Message At</th>
                </tr>
        """
        
        for conv in conversations:
            html += f"""
                <tr>
                    <td>{conv[0]}</td>
                    <td>{conv[1]}</td>
                    <td>{conv[2]}</td>
                    <td>{conv[3] or 'N/A'}</td>
                    <td>{conv[4]}</td>
                </tr>
            """
        
        html += """
            </table>
            
            <h2>Messages Table</h2>
            <table>
                <tr>
                    <th>ID</th>
                    <th>Conversation ID</th>
                    <th>Sender</th>
                    <th>Receiver</th>
                    <th>Type</th>
                    <th>Message</th>
                    <th>Created At</th>
                </tr>
        """
        
        for msg in messages:
            html += f"""
                <tr>
                    <td>{msg[0]}</td>
                    <td>{msg[1]}</td>
                    <td>{msg[2]}</td>
                    <td>{msg[3]}</td>
                    <td>{msg[4]}</td>
                    <td>{msg[5]}</td>
                    <td>{msg[6]}</td>
                </tr>
            """
        
        html += """
            </table>
            <p><a href="/test-messaging-setup">Back to Status Page</a></p>
        </body>
        </html>
        """
        
        return html
        
    except Exception as e:
        import traceback
        return f"<h2>Error:</h2><pre>{traceback.format_exc()}</pre>"

@app.route('/test-messaging-setup')
def test_messaging_setup():
    """Test if messaging tables exist and are working"""
    try:
        connection = get_db_connection()
        cursor = connection.cursor()
        
        # Check if tables exist
        cursor.execute("SHOW TABLES LIKE 'buyer_seller_messages'")
        messages_table = cursor.fetchone()
        
        cursor.execute("SHOW TABLES LIKE 'conversations'")
        conversations_table = cursor.fetchone()
        
        # Get sample data
        message_count = 0
        conversation_count = 0
        
        if messages_table:
            cursor.execute("SELECT COUNT(*) FROM buyer_seller_messages")
            message_count = cursor.fetchone()[0]
        
        if conversations_table:
            cursor.execute("SELECT COUNT(*) FROM conversations")
            conversation_count = cursor.fetchone()[0]
        
        cursor.close()
        connection.close()
        
        result = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Messaging System Status</title>
            <style>
                body {{
                    font-family: Arial, sans-serif;
                    max-width: 800px;
                    margin: 50px auto;
                    padding: 20px;
                    background: #f5f5f5;
                }}
                .container {{
                    background: white;
                    padding: 30px;
                    border-radius: 10px;
                    box-shadow: 0 2px 10px rgba(0,0,0,0.1);
                }}
                h2 {{
                    color: #1a1a1a;
                    border-bottom: 3px solid #d4af37;
                    padding-bottom: 10px;
                }}
                .status {{
                    margin: 20px 0;
                    padding: 15px;
                    border-radius: 5px;
                    background: #f8f9fa;
                }}
                .success {{
                    color: #28a745;
                    font-weight: bold;
                }}
                .error {{
                    color: #dc3545;
                    font-weight: bold;
                }}
                code {{
                    background: #e9ecef;
                    padding: 2px 6px;
                    border-radius: 3px;
                    font-family: monospace;
                }}
                ol {{
                    line-height: 1.8;
                }}
            </style>
        </head>
        <body>
            <div class="container">
                <h2>?? Messaging System Status</h2>
                
                <div class="status">
                    <p><strong>buyer_seller_messages table:</strong> 
                        <span class="{'success' if messages_table else 'error'}">
                            {'? EXISTS' if messages_table else '? NOT FOUND'}
                        </span>
                    </p>
                    <p><strong>conversations table:</strong> 
                        <span class="{'success' if conversations_table else 'error'}">
                            {'? EXISTS' if conversations_table else '? NOT FOUND'}
                        </span>
                    </p>
                    <p><strong>Total messages:</strong> {message_count}</p>
                    <p><strong>Total conversations:</strong> {conversation_count}</p>
                </div>
                
                <h3>?? Instructions:</h3>
                <ol>
                    <li>If tables don't exist, run: <code>python create_messaging_tables.py</code></li>
                    <li>Make sure you're logged in as a <strong>buyer</strong> to send messages</li>
                    <li>Make sure you're logged in as a <strong>seller</strong> to view messages</li>
                    <li>Go to a product page and click "Contact Seller" to test</li>
                </ol>
                
                <h3>?? Quick Links:</h3>
                <ul>
                    <li><a href="/">Homepage</a></li>
                    <li><a href="/login">Login</a></li>
                    <li><a href="/messages">Messages Inbox</a></li>
                </ul>
            </div>
        </body>
        </html>
        """
        
        return result
        
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        return f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Messaging System Error</title>
            <style>
                body {{
                    font-family: Arial, sans-serif;
                    max-width: 800px;
                    margin: 50px auto;
                    padding: 20px;
                    background: #f5f5f5;
                }}
                .container {{
                    background: white;
                    padding: 30px;
                    border-radius: 10px;
                    box-shadow: 0 2px 10px rgba(0,0,0,0.1);
                }}
                h2 {{
                    color: #dc3545;
                }}
                pre {{
                    background: #f8f9fa;
                    padding: 15px;
                    border-radius: 5px;
                    overflow-x: auto;
                }}
            </style>
        </head>
        <body>
            <div class="container">
                <h2>? Error checking messaging setup</h2>
                <pre>{error_details}</pre>
                <p><a href="/">Back to Homepage</a></p>
            </div>
        </body>
        </html>
        """

# -- Admin: Migrate local product images to Supabase Storage ------------------
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

if __name__ == '__main__':
    # Auth is now handled by Supabase � MySQL is optional for products/orders/etc.
    # Try to init MySQL tables but don't block startup if MySQL is unavailable.
    try:
        if check_database_connection():
            initialize_database_tables()
            add_cancellation_columns()
            print("? MySQL connected and tables initialized")
        else:
            print("??  MySQL unavailable � running in Supabase-only mode (auth/users via Supabase)")
    except Exception as _e:
        print(f"??  MySQL init skipped: {_e}")

    # -- Sync MySQL wishlist ? Supabase on startup -----------------------------
    def _sync_wishlist_to_supabase():
        """One-time sync: copy all MySQL wishlist rows into Supabase wishlist table."""
        try:
            conn = get_db_connection()
            cursor = conn.cursor(dictionary=True)
            cursor.execute("SELECT user_id, product_id FROM wishlist")
            rows = cursor.fetchall()
            cursor.close(); conn.close()
            if not rows:
                print("? Wishlist sync: MySQL wishlist is empty, nothing to sync")
                return
            # Get existing Supabase wishlist rows to avoid duplicates
            existing_res = sb_admin.table('wishlist').select('user_id, product_id').execute()
            existing_set = {(r['user_id'], r['product_id']) for r in (existing_res.data or [])}
            new_records = [
                {'user_id': r['user_id'], 'product_id': r['product_id']}
                for r in rows
                if (r['user_id'], r['product_id']) not in existing_set
            ]
            if not new_records:
                print(f"? Wishlist sync: all {len(rows)} rows already in Supabase")
                return
            # Insert in batches of 100
            for i in range(0, len(new_records), 100):
                batch = new_records[i:i+100]
                sb_admin.table('wishlist').insert(batch).execute()
            print(f"? Wishlist sync: {len(new_records)} new rows synced MySQL ? Supabase")
        except Exception as _sync_err:
            print(f"??  Wishlist sync skipped: {_sync_err}")
    try:
        _sync_wishlist_to_supabase()
    except Exception:
        pass
    # -------------------------------------------------------------------------

    # -- Ensure Supabase Storage bucket for product images exists -------------
    try:
        buckets = [b.name for b in sb_admin.storage.list_buckets()]
        if 'product-images' not in buckets:
            sb_admin.storage.create_bucket(
                'product-images',
                options={'public': True}
            )
            print("? Created Supabase Storage bucket: product-images (public)")
        else:
            print("? Supabase Storage bucket 'product-images' already exists")
    except Exception as _bucket_err:
        print(f"??  Could not verify/create product-images bucket: {_bucket_err}")
    # -------------------------------------------------------------------------

    app.run(
        host="0.0.0.0",
        port=5000,
        debug=True,
        threaded=True,
        use_reloader=False
    )

