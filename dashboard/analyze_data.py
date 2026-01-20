import json
with open(r'c:\Users\bruno\OneDrive\Área de Trabalho\alvo\dashboard\src\data\summary.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

years = [m['year'] for m in data['monthly']]
from collections import Counter
print(Counter(years))
