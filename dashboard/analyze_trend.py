import json
with open(r'c:\Users\bruno\OneDrive\Área de Trabalho\alvo\dashboard\src\data\summary.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

# Select all months of 2025
months_2025 = [i for i, m in enumerate(data['monthly']) if m['year'] == 2025]

# Aggregate revenue per month
rev_per_month = {i: 0 for i in months_2025}
for r in data['rows']:
    if r[0] in months_2025:
        rev_per_month[r[0]] += r[6]

# Trend Mode logic: last 3 vs first 9
pB = months_2025[-3:]
pA = months_2025[:-3]

avgB = sum(rev_per_month[i] for i in pB) / len(pB)
avgA = sum(rev_per_month[i] for i in pA) / len(pA)

print(f"Avg A (indices {pA}): {avgA}")
print(f"Avg B (indices {pB}): {avgB}")
print(f"Delta: {(avgB / avgA - 1) * 100:.2f}%")
