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

#  profile POST: remove MySQL mirror block 
src = rb(src,
    "            # -- Also update MySQL users table (by email) ------------------\n            user_type = session.get('user_type', '').lower()\n            try:\n                connection = get_db_connection()",
    "            except Exception as mysql_err:\n                print(f\"?? MySQL profile update skipped (unavailable): {mysql_err}\")",
    "            # MySQL mirror removed"
)
print("profile POST MySQL done, remaining:", src.count("get_db_connection()"))

#  profile GET: remove MySQL supplement block 
src = rb(src,
    "        # -- Supplement with MySQL data (profile_picture, business_name, vehicle) --\n        try:\n            conn = get_db_connection()",
    "        except Exception as mysql_err:\n            print(f\"?? MySQL profile supplement skipped: {mysql_err}\")",
    "        # MySQL supplement removed  data comes from Supabase only"
)
print("profile GET MySQL done, remaining:", src.count("get_db_connection()"))

#  upload_profile_picture: remove MySQL update ─
src = rb(src,
    "            try:\n                connection = get_db_connection()\n                cursor = connection.cursor()\n                cursor.execute(\n                    \"UPDATE users SET profile_picture = %s WHERE email = %s\",\n                    (filename, session.get('email'))\n                )\n                connection.commit()\n            except Exception as mysql_err:",
    "            finally:\n                if 'cursor' in locals():\n                    cursor.close()\n                if 'connection' in locals():\n                    connection.close()",
    "            # MySQL update removed"
)
print("upload_profile_picture MySQL done, remaining:", src.count("get_db_connection()"))

open(PATH, "w", encoding="utf-8").write(src)
print("saved")
