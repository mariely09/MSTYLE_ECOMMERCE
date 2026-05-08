PATH = "c:/Users/Sel/Desktop/MSTYLE_ECOMMERCE/mstyle_website/mstyle.py"
src = open(PATH, encoding="utf-8").read()
import re
ra_idx = src.find("def reports_analytics()")
# Show 200 chars after the function def to see if it still has MySQL
print(repr(src[ra_idx:ra_idx+400]))
