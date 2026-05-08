PATH = "c:/Users/Sel/Desktop/MSTYLE_ECOMMERCE/mstyle_website/mstyle.py"
src = open(PATH, encoding="utf-8").read()

def rb(text, start, end, repl):
    si = text.find(start)
    if si == -1:
        print(f"  WARN start: {start[:55]!r}")
        return text
    ei = text.find(end, si)
    if ei == -1:
        print(f"  WARN end: {end[:55]!r}")
        return text
    ei += len(end)
    return text[:si] + repl + text[ei:]

#  get_promotions: replace MySQL with Supabase 
src = rb(src,
    "@app.route('/api/get_promotions')\ndef get_promotions():",
    "    finally:\n        if cursor:\n            cursor.close()\n        if connection:\n            connection.close()\n        print(\"DEBUG: Database connection closed\")",
    """@app.route('/api/get_promotions')
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
        return jsonify({'success': False, 'message': f'Server error: {str(e)}'}), 500"""
)
print("get_promotions done, remaining:", src.count("get_db_connection()"))

#  toggle_promotion: replace MySQL with Supabase 
src = rb(src,
    "@app.route('/api/toggle_promotion/<int:promotion_id>', methods=['POST'])\ndef toggle_promotion(promotion_id):",
    "    except Exception as e:\n        print(f\"Error toggling promotion: {str(e)}\")\n        return jsonify({'success': False, 'message': 'Failed to toggle promotion'}), 500",
    """@app.route('/api/toggle_promotion/<int:promotion_id>', methods=['POST'])
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
        return jsonify({'success': False, 'message': 'Failed to toggle promotion'}), 500"""
)
print("toggle_promotion done, remaining:", src.count("get_db_connection()"))

#  delete_promotion: replace MySQL with Supabase 
src = rb(src,
    "@app.route('/api/delete_promotion/<int:promotion_id>', methods=['DELETE'])\ndef delete_promotion(promotion_id):",
    "    except Exception as e:\n        print(f\"Error deleting promotion: {str(e)}\")\n        return jsonify({'success': False, 'message': 'Failed to delete promotion'}), 500",
    """@app.route('/api/delete_promotion/<int:promotion_id>', methods=['DELETE'])
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
        return jsonify({'success': False, 'message': 'Failed to delete promotion'}), 500"""
)
print("delete_promotion done, remaining:", src.count("get_db_connection()"))

#  apply_promotion: replace MySQL with Supabase 
src = rb(src,
    "@app.route('/api/apply_promotion', methods=['POST'])\ndef apply_promotion():",
    "    except Exception as e:\n        print(f\"Error applying promotion: {str(e)}\")\n        return jsonify({'success': False, 'message': 'Failed to apply promotion'}), 500",
    """@app.route('/api/apply_promotion', methods=['POST'])
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
        return jsonify({'success': False, 'message': 'Failed to apply promotion'}), 500"""
)
print("apply_promotion done, remaining:", src.count("get_db_connection()"))

open(PATH, "w", encoding="utf-8").write(src)
print("saved")
