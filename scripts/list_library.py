import json, re
text = open('libreria_Ausarta_JUN_2026.xml', encoding='utf-8', errors='ignore').read()
m = re.search(r'<mxlibrary>(.*)</mxlibrary>', text, re.DOTALL)
entries = json.loads(m.group(1))
for i, e in enumerate(entries, 1):
    print(f'{i:3}. {e.get("title", "(sin titulo)")}')
print(f'\nTotal: {len(entries)} entradas')
