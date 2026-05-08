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

#  register: remove MySQL pending_users mirror block 
src = rb(src,
    "        # -- Also try MySQL pending_users (optional",
    "                except Exception: pass\n",
    "        # MySQL mirror removed\n"
)
print("register MySQL block:", src.count("get_db_connection()"))

#  seller_register: remove MySQL pending_sellers mirror block 
src = rb(src,
    "            # -- Also try MySQL pending_sellers (optional",
    "                    try: db.close()\n                    except Exception: pass\n",
    "            # MySQL mirror removed\n"
)
print("seller_register MySQL block:", src.count("get_db_connection()"))

open(PATH, "w", encoding="utf-8").write(src)
print("saved")
