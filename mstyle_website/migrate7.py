PATH = "c:/Users/Sel/Desktop/MSTYLE_ECOMMERCE/mstyle_website/mstyle.py"
src = open(PATH, encoding="utf-8").read()

def rb(text, start, end, repl):
    si = text.find(start)
    if si == -1:
        print(f"  WARN start not found: {start[:60]!r}")
        return text
    ei = text.find(end, si)
    if ei == -1:
        print(f"  WARN end not found: {end[:60]!r}")
        return text
    ei += len(end)
    return text[:si] + repl + text[ei:]

#  promotions route: replace MySQL body with Supabase 
PROMO_START = "    # Ensure promotion tables exist\n    try:\n        ensure_promotion_tables_exist()\n    except Exception:\n        pass\n\n    try:\n        connection = get_db_connection()\n        cursor = connection.cursor(dictionary=True)\n    except Exception as db_err:\n        print(f\"?? MySQL unavailable in promotions: {db_err}\")\n        return render_template('promotions.html', products=[], active_promotions=[],\n                             user_name=seller_name, user_email=session.get('email', 'Seller'))"
PROMO_END   = "    return render_template('promotions.html',\n                         products=products,\n                         active_promotions=active_promotions,\n                         user_name=seller_name,\n                         user_email=session.get('email', 'Seller'))"

PROMO_NEW = """    seller_email = session['email']
    try:
        from datetime import date as _date
        today = _date.today().isoformat()

        # Products for promotion management
        prod_res = sb_admin.table('products').select('id, name, price, image, quantity, category').eq('seller_email', seller_email).gt('quantity', 0).order('name').execute()
        products = []
        for p in (prod_res.data or []):
            products.append({'id': p['id'], 'name': p['name'],
                'price': float(p.get('price') or 0), 'image': p.get('image',''),
                'quantity': int(p.get('quantity') or 0), 'category': p.get('category','')})

        # Active promotions
        ap_res = sb_admin.table('promotions').select('*').eq('seller_email', seller_email).eq('is_active', True).lte('start_date', today).gte('end_date', today).order('created_at', desc=True).limit(10).execute()
        active_promotions = []
        for p in (ap_res.data or []):
            sd = str(p.get('start_date') or '')[:10]
            ed = str(p.get('end_date') or '')[:10]
            active_promotions.append({**p, 'start_date': sd, 'end_date': ed,
                'total_uses': int(p.get('current_usage_count') or 0),
                'total_discount_given': 0.0})

    except Exception as e:
        print(f"promotions Supabase error: {e}")
        products = []
        active_promotions = []

    return render_template('promotions.html',
                         products=products,
                         active_promotions=active_promotions,
                         user_name=seller_name,
                         user_email=session.get('email', 'Seller'))"""

src = rb(src, PROMO_START, PROMO_END, PROMO_NEW)
print("promotions done, remaining:", src.count("get_db_connection()"))

#  admin_backfill_promotion_usage: remove MySQL ─
src = rb(src,
    "@app.route('/admin/backfill-promotion-usage')\ndef admin_backfill_promotion_usage():",
    "    except Exception as e:\n        return jsonify({'success': False, 'message': f'Error: {str(e)}'}), 500",
    """@app.route('/admin/backfill-promotion-usage')
def admin_backfill_promotion_usage():
    if 'email' not in session:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401
    return jsonify({'success': True, 'message': 'No backfill needed (Supabase-only)'})"""
)
print("admin_backfill done, remaining:", src.count("get_db_connection()"))

open(PATH, "w", encoding="utf-8").write(src)
print("saved")
