PATH = "c:/Users/Sel/Desktop/MSTYLE_ECOMMERCE/mstyle_website/mstyle.py"
src = open(PATH, encoding="utf-8").read()
# Show what route is at pos 152819
# Find the last @app.route before pos 152819
import re
routes = [(m.start(), m.group()) for m in re.finditer(r"@app\.route\('[^']+'\)", src)]
for i, (pos, route) in enumerate(routes):
    if pos > 152819:
        print(f"Route after: {route} at {pos}")
        print(f"Route before: {routes[i-1]}")
        break
