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

#  reports_analytics: replace entire MySQL body with Supabase 
REPORTS_START = "    try:\n        connection = get_db_connection()\n        cursor = connection.cursor(dictionary=True)\n    except Exception as db_err:\n        print(f\"?? MySQL unavailable in reports_analytics: {db_err}\")"
REPORTS_END   = "                         user_email=session.get('email', 'Seller'))"

REPORTS_NEW = """    seller_email = session['email']
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
                         user_email=session.get('email', 'Seller'))"""

src = rb(src, REPORTS_START, REPORTS_END, REPORTS_NEW)
print("reports_analytics done, remaining:", src.count("get_db_connection()"))

open(PATH, "w", encoding="utf-8").write(src)
print("saved")
