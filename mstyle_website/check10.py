PATH = "c:/Users/Sel/Desktop/MSTYLE_ECOMMERCE/mstyle_website/mstyle.py"
src = open(PATH, encoding="utf-8").read()

def rb(text, start, end, repl):
    si = text.find(start)
    if si == -1:
        print(f"  WARN start not found: {start[:55]!r}")
        return text
    ei = text.find(end, si)
    if ei == -1:
        print(f"  WARN end not found: {end[:55]!r}")
        return text
    ei += len(end)
    return text[:si] + repl + text[ei:]

#  search-suggestions: already replaced but still has a call 
# Find the remaining call
idx = src.find("@app.route('/api/search-suggestions')")
snippet = src[idx:idx+500]
print("search-suggestions snippet:", repr(snippet[:200]))
