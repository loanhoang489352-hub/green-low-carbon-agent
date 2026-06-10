"""临时: 看 raw HTML 里的最大 div"""
from bs4 import BeautifulSoup
from pathlib import Path
import sys

if len(sys.argv) < 2:
    print("Usage: inspect_raw.py <html-file>")
    sys.exit(1)

fpath = Path(sys.argv[1])
html = fpath.read_text(encoding='utf-8')
soup = BeautifulSoup(html, 'html.parser')

divs = soup.find_all('div')
candidates = []
for d in divs:
    text = d.get_text(separator=' ', strip=True)
    if len(text) > 500:
        cls = d.get('class', ['?'])
        idd = d.get('id', '?')
        candidates.append((len(text), cls, idd, text))

candidates.sort(key=lambda x: -x[0])
print(f'File: {fpath.name}')
print(f'Candidates: {len(candidates)}')
for i, (sz, cls, idd, text) in enumerate(candidates[:5]):
    print(f'\n--- #{i} len={sz} class={cls} id={idd} ---')
    print(text[:500])
