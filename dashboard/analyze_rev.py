import json
with open(r'c:\Users\bruno\OneDrive\Área de Trabalho\alvo\dashboard\src\data\summary.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

rev_2024 = 0
rev_2025 = 0

for r in data['rows']:
    month_idx = r[0]
    year = data['monthly'][month_idx]['year']
    rev = r[6]
    if year == 2024:
        rev_2024 += rev
    elif year == 2025:
        rev_2025 += rev

print(f"2024: {rev_2024}")
print(f"2025: {rev_2025}")
print(f"Delta: {(rev_2025 - rev_2024) / rev_2024 * 100:.2f}%")
