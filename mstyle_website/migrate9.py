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

#  get_promotion: replace MySQL with Supabase ─
src = rb(src,
    "@app.route('/api/get_promotion/<int:promotion_id>')\ndef get_promotion(promotion_id):",
    "        try:\n            if 'connection' in locals() and connection:\n                connection.close()\n        except Exception as conn_error:\n            print(f\"DEBUG: Error closing connection in get_promotion: {conn_error}\")",
    """@app.route('/api/get_promotion/<int:promotion_id>')
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
        import traceback; traceback.print_exc()
        return jsonify({'success': False, 'message': f'Server error: {str(e)}'}), 500"""
)
print("get_promotion done, remaining:", src.count("get_db_connection()"))

#  update_promotion: replace MySQL with Supabase 
src = rb(src,
    "@app.route('/api/update_promotion/<int:promotion_id>', methods=['PUT'])\ndef update_promotion(promotion_id):",
    "        except Exception as update_error:\n            cursor.close()\n            connection.close()\n            return jsonify({'success': False, 'message': f'Error updating promotion: {str(update_error)}'}), 500\n        \n    except Exception as e:\n        print(f\"Error updating promotion: {str(e)}\")\n        return jsonify({'success': False, 'message': f'Server error: {str(e)}'}), 500",
    """@app.route('/api/update_promotion/<int:promotion_id>', methods=['PUT'])
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
            if not data.get('discountValue'):
                return jsonify({'success': False, 'message': 'Discount value is required'}), 400
            discount_value = float(data['discountValue'])
        # Check exists
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
        import traceback; traceback.print_exc()
        return jsonify({'success': False, 'message': f'Server error: {str(e)}'}), 500"""
)
print("update_promotion done, remaining:", src.count("get_db_connection()"))

open(PATH, "w", encoding="utf-8").write(src)
print("saved")
