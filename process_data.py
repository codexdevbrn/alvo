import pandas as pd
import json
import os

def process_data():
    print("Loading data from Excel...")
    cols = {
        'Nome_Loja[Loja]': 'store',
        'PRODUTO[NOME_FABRICANTE]': 'mfr',
        'MOVIMENTO[NOME_CLIENTE]': 'client',
        'GABARITO HARM[descricao]': 'desc',
        'PRODUTO[CODIGO_REFERENCIA_PRODUTO]': 'ref',
        'Dcalendario[Ano]': 'year',
        'Dcalendario[Mês]': 'month',
        '[Receita_Líquida]': 'rev',
        '[QTD]': 'qty'
    }
    
    try:
        df = pd.read_excel('base_de_dados.xlsx', usecols=list(cols.keys()))
        df.rename(columns=cols, inplace=True)
    except Exception as e:
        print(f"Error reading Excel: {e}")
        return

    month_map = {
        'janeiro': 1, 'fevereiro': 2, 'março': 3, 'abril': 4, 'maio': 5, 'junho': 6,
        'julho': 7, 'agosto': 8, 'setembro': 9, 'outubro': 10, 'novembro': 11, 'dezembro': 12
    }
    df['m_num'] = df['month'].str.lower().map(month_map)
    df['p_p_id'] = df['year'] * 100 + df['m_num']
    df['client'] = df['client'].fillna('Consumidor Final')
    df['mfr'] = df['mfr'].fillna('Não Inf.')
    df['desc'] = df['desc'].fillna('Outros')
    df['ref'] = df['ref'].fillna('S/ REF')

    print("Aggregating...")
    # Including 'ref' in aggregation to allow product-level view
    agg = df.groupby(['p_p_id', 'store', 'client', 'mfr', 'desc', 'ref']).agg({'rev': 'sum', 'qty': 'sum'}).reset_index()
    
    print("Sorting dimensions by revenue...")
    # Sorting maps by revenue descending for better UX
    def get_sorted_map(df, col):
        return df.groupby(col)['rev'].sum().sort_values(ascending=False).index.tolist()

    maps = {
        "s": get_sorted_map(df, 'store'),
        "c": get_sorted_map(df, 'client'),
        "m": get_sorted_map(df, 'mfr'),
        "d": get_sorted_map(df, 'desc'),
        "r": get_sorted_map(df, 'ref'), # Reference/Product map
        "p": sorted(df['p_p_id'].unique().tolist())
    }

    s_map = {v: i for i, v in enumerate(maps['s'])}
    c_map = {v: i for i, v in enumerate(maps['c'])}
    m_map = {v: i for i, v in enumerate(maps['m'])}
    d_map = {v: i for i, v in enumerate(maps['d'])}
    r_map = {v: i for i, v in enumerate(maps['r'])}
    p_map = {v: i for i, v in enumerate(maps['p'])}

    print("Encoding rows...")
    rows = []
    for _, row in agg.iterrows():
        rows.append([
            p_map[row['p_p_id']],
            s_map[row['store']],
            c_map[row['client']],
            m_map[row['mfr']],
            d_map[row['desc']],
            r_map[row['ref']],
            round(float(row['rev']), 2),
            int(row['qty'])
        ])

    # Pre-calculated monthly summary for baseline chart
    monthly_summary = df.groupby(['p_p_id', 'year', 'month'])['rev'].sum().reset_index().sort_values('p_p_id')
    monthly_data = [
        {"name": f"{row['month'][:3]}/{str(row['year'])[2:]}", "rev": round(row['rev'], 2), "pid": int(row['p_p_id']), "year": int(row['year'])}
        for _, row in monthly_summary.iterrows()
    ]

    # Pre-calculate YoY KPIs (Total 2024 vs Total 2025)
    yoy_stats = df.groupby('year')['rev'].sum().to_dict()

    import datetime
    mtime = os.path.getmtime('base_de_dados.xlsx')
    file_date = datetime.datetime.fromtimestamp(mtime).strftime("%d/%m/%Y %H:%M")

    result = {
        "maps": maps,
        "rows": rows,
        "monthly": monthly_data,
        "yoy": yoy_stats,
        "updated_at": file_date,
        "kpis": {
            "rev": round(df['rev'].sum(), 2),
            "qty": int(df['qty'].sum()),
            "avg": round(df['rev'].mean(), 2),
            "cnt": len(df)
        }
    }

    os.makedirs('dashboard/src/data', exist_ok=True)
    print("Saving optimized JSON...")
    with open('dashboard/src/data/summary.json', 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False)
    
    print(f"Done! Raw rows: {len(rows)}")

if __name__ == "__main__":
    process_data()
