import json, re
from pathlib import Path

library = Path(__file__).resolve().parents[1] / "library" / "libreria_Ausarta_JUN_2026.xml"
text = open(library, encoding='utf-8', errors='ignore').read()
m = re.search(r'<mxlibrary>(.*)</mxlibrary>', text, re.DOTALL)
entries = json.loads(m.group(1))
for i, e in enumerate(entries, 1):
    print(f'{i:3}. {e.get("title", "(sin titulo)")}')
print(f'\nTotal: {len(entries)} entradas')
