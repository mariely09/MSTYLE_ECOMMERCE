PATH = "c:/Users/Sel/Desktop/MSTYLE_ECOMMERCE/mstyle_website/mstyle.py"
src = open(PATH, encoding="utf-8").read()
import re
# Count how many times search_suggestions is defined
matches = [m.start() for m in re.finditer(r"def search_suggestions\(\)", src)]
print("search_suggestions defined at:", matches)
for pos in matches:
    print(repr(src[pos:pos+100]))
