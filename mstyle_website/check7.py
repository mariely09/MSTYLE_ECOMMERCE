PATH = "c:/Users/Sel/Desktop/MSTYLE_ECOMMERCE/mstyle_website/mstyle.py"
src = open(PATH, encoding="utf-8").read()
import re
ra_idx = src.find("def reports_analytics()")
# Find get_db_connection in reports_analytics
for m in re.finditer(r'get_db_connection\(\)', src[ra_idx:ra_idx+5000]):
    print(f"  found at offset {m.start()} from func start")
    print(repr(src[ra_idx+m.start()-50:ra_idx+m.start()+100]))
    break
else:
    print("No get_db_connection in reports_analytics - already clean!")
