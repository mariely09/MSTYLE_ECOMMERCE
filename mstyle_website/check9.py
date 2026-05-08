PATH = "c:/Users/Sel/Desktop/MSTYLE_ECOMMERCE/mstyle_website/mstyle.py"
src = open(PATH, encoding="utf-8").read()
import re

# List all routes that still have get_db_connection
routes = [(m.start(), m.group()) for m in re.finditer(r"@app\.route\('[^']+'\)", src)]
db_calls = [m.start() for m in re.finditer(r'get_db_connection\(\)', src)]

for db_pos in db_calls:
    # Find the last route before this db call
    route = None
    for rpos, rname in routes:
        if rpos < db_pos:
            route = (rpos, rname)
        else:
            break
    if route:
        print(f"  {route[1]} (pos {route[0]}) -> db call at {db_pos}")
