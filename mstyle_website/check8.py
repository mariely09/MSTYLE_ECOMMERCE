PATH = "c:/Users/Sel/Desktop/MSTYLE_ECOMMERCE/mstyle_website/mstyle.py"
src = open(PATH, encoding="utf-8").read()
import re

# Find get_promotion and update_promotion routes
for route in ["get_promotion", "update_promotion"]:
    idx = src.find(f"def {route}(")
    if idx == -1:
        print(f"{route}: NOT FOUND")
        continue
    # Show 200 chars around the get_db_connection call
    for m in re.finditer(r'get_db_connection\(\)', src[idx:idx+3000]):
        print(f"{route}: get_db_connection at offset {m.start()}")
        print(repr(src[idx+m.start()-80:idx+m.start()+80]))
        break
    else:
        print(f"{route}: already clean")
