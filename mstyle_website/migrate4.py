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

#  view_product: remove MySQL fallback block 
src = rb(src,
    "    # -- FALLBACK: MySQL -------------------------------------------------------\n    if product is None:",
    "        except Exception as mysql_err:\n            print(f\"?? MySQL view_product fallback failed: {mysql_err}\")",
    "    # MySQL fallback removed  Supabase is the only source"
)
print("view_product MySQL fallback done, remaining:", src.count("get_db_connection()"))

open(PATH, "w", encoding="utf-8").write(src)
print("saved")
