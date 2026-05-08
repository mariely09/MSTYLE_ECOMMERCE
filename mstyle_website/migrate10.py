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

#  search-suggestions: replace MySQL with Supabase 
src = rb(src,
    "@app.route('/api/search-suggestions')\ndef search_suggestions():",
    "    except mysql.connector.Error as err:\n        print(f\"Database error in search suggestions: {err}\")\n        return jsonify({'success': False, 'suggestions': []})",
    """@app.route('/api/search-suggestions')
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
        return jsonify({'success': False, 'suggestions': []})"""
)
print("search-suggestions done, remaining:", src.count("get_db_connection()"))

open(PATH, "w", encoding="utf-8").write(src)
print("saved")
