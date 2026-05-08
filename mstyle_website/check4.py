PATH = "c:/Users/Sel/Desktop/MSTYLE_ECOMMERCE/mstyle_website/mstyle.py"
src = open(PATH, encoding="utf-8").read()
import re
ra_idx = src.find("def reports_analytics()")
print("reports_analytics at:", ra_idx)
# Find all get_db_connection after that
for m in re.finditer(r'get_db_connection\(\)', src):
    if m.start() > ra_idx:
        print(f"  first get_db_connection at pos {m.start()}")
        print(repr(src[m.start()-100:m.start()+50]))
        break
