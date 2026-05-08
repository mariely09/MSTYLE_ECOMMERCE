PATH = "c:/Users/Sel/Desktop/MSTYLE_ECOMMERCE/mstyle_website/mstyle.py"
src = open(PATH, encoding="utf-8").read()
import re

# Show the full search-suggestions route
idx = src.find("@app.route('/api/search-suggestions')")
end_idx = src.find("\n@app.route(", idx+10)
print(repr(src[idx:end_idx]))
