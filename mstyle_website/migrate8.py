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

#  create_promotion: replace MySQL body with Supabase 
CREATE_START = "@app.route('/api/create_promotion', methods=['POST'])\ndef create_promotion():"
CREATE_END   = "        try:\n            if 'connection' in locals() and connection:\n                connection.close()\n                print(f\"DEBUG: Connection closed\")\n        except Exception as conn_error:\n            print(f\"DEBUG: Error closing connection: {conn_error}\")"

CREATE_NEW = """@app.route('/api/create_promotion', methods=['POST'])
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
        return jsonify({'success': False, 'message': f'Server error: {str(e)}'}), 500"""

src = rb(src, CREATE_START, CREATE_END, CREATE_NEW)
print("create_promotion done, remaining:", src.count("get_db_connection()"))

open(PATH, "w", encoding="utf-8").write(src)
print("saved")
