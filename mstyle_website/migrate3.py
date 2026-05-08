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

#  change_password: replace entire MySQL block 
src = rb(src,
    "@app.route('/change-password', methods=['POST'])\ndef change_password():",
    "    finally:\n        if 'cursor' in locals():\n            cursor.close()\n        if 'connection' in locals():\n            connection.close()",
    """@app.route('/change-password', methods=['POST'])
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
        return jsonify({'success': False, 'message': f'An error occurred: {str(e)}'}), 500"""
)
print("change_password done, remaining:", src.count("get_db_connection()"))

#  check_old_password: replace with Supabase 
src = rb(src,
    "@app.route('/check-old-password', methods=['POST'])\ndef check_old_password():",
    "    finally:\n        cursor.close()\n        connection.close()",
    """@app.route('/check-old-password', methods=['POST'])
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
        return jsonify(valid=False)"""
)
print("check_old_password done, remaining:", src.count("get_db_connection()"))

open(PATH, "w", encoding="utf-8").write(src)
print("saved")
