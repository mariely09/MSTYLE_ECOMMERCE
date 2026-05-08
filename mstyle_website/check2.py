PATH = "c:/Users/Sel/Desktop/MSTYLE_ECOMMERCE/mstyle_website/mstyle.py"
src = open(PATH, encoding="utf-8").read()
# Find the actual start of the MySQL block in reports_analytics
idx = src.find("reports_analytics")
# Find get_db_connection near reports_analytics
import re
matches = [(m.start(), src[max(0,m.start()-200):m.start()+50]) for m in re.finditer(r'get_db_connection\(\)', src)]
# Show first few after reports_analytics route definition
ra_idx = src.find("def reports_analytics()")
for start, ctx in matches:
    if start > ra_idx:
        print(f"pos {start}:")
        print(repr(ctx[-100:]))
        print()
        break
