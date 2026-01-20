import json
with open(r'c:\Users\bruno\OneDrive\Área de Trabalho\alvo\dashboard\src\data\summary.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

clients = data['maps']['c']
for i, c in enumerate(clients):
    if "Consumidor Final" in c:
        print(f"Index: {i}, Name: '{c}'")
