src = open("c:/Users/Sel/Desktop/MSTYLE_ECOMMERCE/mstyle_website/mstyle.py", encoding="utf-8").read()
lines = src.split('\n')
for i, line in enumerate(lines):
    if 'get_db_connection()' in line:
        print(f"L{i+1}: {line.strip()[:80]}")
