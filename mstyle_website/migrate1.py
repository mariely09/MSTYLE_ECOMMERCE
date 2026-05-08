import re

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

# 1. Remove /test-db route
src = rb(src,
    "@app.route('/test-db')",
    "return f\"Database connection failed: {str(e)}\"",
    "# /test-db route removed"
)
print("1 done, remaining:", src.count("get_db_connection()"))

# 2. Remove /otp_verification route
src = rb(src,
    "@app.route('/otp_verification', methods=['GET', 'POST'])",
    "return render_template('otp_verification.html')",
    "# /otp_verification route removed"
)
print("2 done, remaining:", src.count("get_db_connection()"))

# 3. Remove best-effort MySQL update in reset_password
old3 = "        # Best-effort MySQL update\n        if email:\n            try:\n                update_password_in_db(email, new_password)\n            except Exception:\n                pass\n"
if old3 in src:
    src = src.replace(old3, "        # Password updated in Supabase auth above\n")
    print("3 done")
else:
    print("3 WARN not found")
print("  remaining:", src.count("get_db_connection()"))

open(PATH, "w", encoding="utf-8").write(src)
print("saved")
