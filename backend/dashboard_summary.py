"""
Geração do "summary" do Dashboard (rota /) a partir de um DataFrame limpo.

Produz um dict com EXATAMENTE o mesmo shape do dashboard/public/data/summary.json
gerado por process_data.py na raiz do projeto (contrato consumido por
dashboard/src/types/dashboard.ts e DashboardPage.tsx):

    {
      "maps": {"s": [...], "c": [...], "m": [...], "d": [...], "r": [...], "p": [...]},
      "rows": [[p, s, c, m, d, r, rev, qty], ...],   # índices nos maps + valores
      "monthly": [{"name": "jan/24", "rev": ..., "cmv": ..., "pid": 202401, "year": 2024}, ...],
      "yoy": {"2024": ..., "2025": ...},
      "updated_at": "dd/mm/aaaa hh:mm",
      "kpis": {"rev": ..., "qty": ..., "avg": ..., "cnt": ..., "cmv": ...}
    }

`cmv` em `monthly`/`kpis` é o Custo da Mercadoria Vendida somado no período — base
para "Lucro bruto" (receita - CMV) na tela de Monitoramento. Empresa cuja fonte
não preenche a coluna chega com `cmv` zerado; `kpis.cmv == 0` sinaliza "sem CMV"
para quem consome o summary (`monitor_empresas.py` usa isso para esconder a
métrica de lucro dessa empresa, em vez de mostrar lucro == receita).

A diferença em relação a process_data.py é a origem dos dados: aqui o
DataFrame vem de engine.analise_funil.carregar_csv() (Base.csv por empresa,
schema canônico do Analisador), que já entrega Receita como float, QTD como
int e Data_Venda como datetime — então a lógica foi adaptada para essas
colunas e vetorizada (o iterrows do script original seria lento com 647k
linhas por requisição).

Cache em disco: `summary_dashboard.json` na pasta de trabalho da empresa,
invalidado quando Base.csv fica mais novo (mtime).
"""

from __future__ import annotations

import gzip
import json
import os
import tempfile
from collections import defaultdict
from datetime import date
from pathlib import Path

import pandas as pd

from engine.analise_funil import (
    MESES_ABREV,
    classificar_produtos_agregado,
    curva_pareto,
    eh_produto_nao_harmonizado,
    faixa_por_curva,
    mascara_clientes_balcao,
)

MESES_NOME = {
    1: "janeiro", 2: "fevereiro", 3: "março", 4: "abril", 5: "maio", 6: "junho",
    7: "julho", 8: "agosto", 9: "setembro", 10: "outubro", 11: "novembro", 12: "dezembro",
}

NOME_SUMMARY_DASHBOARD = "summary_dashboard.json"
NOME_SUMMARY_DASHBOARD_GZ = "summary_dashboard.json.gz"
NOME_VERSAO_SUMMARY = "summary_dashboard.versao"

#: Muda quando o shape do summary muda — sem isso, um summary já gravado com
#: mtime >= fonte é lido como fresco pra sempre, mesmo depois de um campo novo
#: (ex.: `cmv`, versão 2) entrar no código: a fonte não muda só porque o app
#: atualizou, e reprocessar 45 MB por requisição só pra checar versão anularia
#: o ganho do cache. Por isso o número mora num arquivo à parte, poucos bytes,
#: e não dentro do JSON grande. Bumpar aqui invalida os summaries já gravados;
#: eles regeneram na próxima leitura. 2: passou a somar CMV em kpis/monthly.
VERSAO_SUMMARY = 2


def caminho_summary_dashboard(pasta_trabalho: str | Path) -> Path:
    return Path(pasta_trabalho) / NOME_SUMMARY_DASHBOARD


def caminho_summary_dashboard_gz(pasta_trabalho: str | Path) -> Path:
    return Path(pasta_trabalho) / NOME_SUMMARY_DASHBOARD_GZ


def caminho_versao_summary(pasta_trabalho: str | Path) -> Path:
    return Path(pasta_trabalho) / NOME_VERSAO_SUMMARY


def _versao_summary_gravada(pasta_trabalho: str | Path) -> int:
    """Lê a versão gravada junto do summary; 0 (sempre desatualizada) se ausente/inválida."""
    try:
        return int(caminho_versao_summary(pasta_trabalho).read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return 0


def summary_dashboard_atualizado(
    pasta_trabalho: str | Path,
    caminho_base_csv: str | Path,
    *,
    mtime_minimo: float = 0.0,
) -> bool:
    """True se o JSON (ou .gz) em disco existe, não é mais antigo que a fonte e
    foi gravado com o shape atual do summary (ver `VERSAO_SUMMARY`).

    `mtime_minimo` acrescenta outras entradas que também invalidam o summary
    quando mudam sem a fonte mudar — hoje, a regra de harmonização de clientes.
    """
    if _versao_summary_gravada(pasta_trabalho) != VERSAO_SUMMARY:
        return False
    caminho_csv = Path(caminho_base_csv)
    if not caminho_csv.is_file():
        return False
    mtime_fonte = max(os.path.getmtime(caminho_csv), mtime_minimo)
    for caminho in (
        caminho_summary_dashboard_gz(pasta_trabalho),
        caminho_summary_dashboard(pasta_trabalho),
    ):
        if caminho.is_file() and os.path.getmtime(caminho) >= mtime_fonte:
            return True
    return False


def gravar_summary_dashboard(pasta_trabalho: str | Path, summary: dict) -> Path:
    """Grava summary_dashboard.json e .json.gz (atômico) na pasta de trabalho.

    Retorna o caminho do .json.gz (preferido para FileResponse).
    """
    pasta = Path(pasta_trabalho)
    pasta.mkdir(parents=True, exist_ok=True)
    destino = caminho_summary_dashboard(pasta)
    destino_gz = caminho_summary_dashboard_gz(pasta)
    payload = json.dumps(summary, ensure_ascii=False, separators=(",", ":")).encode("utf-8")

    fd, tmp_nome = tempfile.mkstemp(
        prefix="summary_dashboard_",
        suffix=".json.tmp",
        dir=str(pasta),
    )
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(payload)
        os.replace(tmp_nome, destino)
    except Exception:
        try:
            os.unlink(tmp_nome)
        except OSError:
            pass
        raise

    fd_gz, tmp_gz = tempfile.mkstemp(
        prefix="summary_dashboard_",
        suffix=".json.gz.tmp",
        dir=str(pasta),
    )
    try:
        os.close(fd_gz)
        with gzip.open(tmp_gz, "wb", compresslevel=4) as f:
            f.write(payload)
        os.replace(tmp_gz, destino_gz)
    except Exception:
        try:
            os.unlink(tmp_gz)
        except OSError:
            pass
        raise

    # Grava por último: se o processo cair antes daqui, a próxima leitura vê
    # versão ausente (0) e regenera em vez de servir um JSON possivelmente
    # incompleto como se fosse da versão atual.
    caminho_versao_summary(pasta).write_text(str(VERSAO_SUMMARY), encoding="utf-8")

    return destino_gz


def invalidar_summary_dashboard(pasta_trabalho: str | Path) -> None:
    for caminho in (
        caminho_summary_dashboard(pasta_trabalho),
        caminho_summary_dashboard_gz(pasta_trabalho),
        caminho_versao_summary(pasta_trabalho),
    ):
        try:
            caminho.unlink(missing_ok=True)
        except OSError:
            pass


def gerar_e_gravar_summary_dashboard(
    pasta_trabalho: str | Path,
    df: pd.DataFrame,
    *,
    data_ultimo_movimento: date | None = None,
    updated_at: str | None = None,
) -> Path:
    """Gera o summary a partir do DataFrame e grava summary_dashboard.json(+.gz)."""
    summary = gerar_summary(
        df,
        updated_at=updated_at,
        data_ultimo_movimento=data_ultimo_movimento,
    )
    return gravar_summary_dashboard(pasta_trabalho, summary)


def formatar_ultimo_movimento(
    df: pd.DataFrame,
    data_exata: date | None = None,
) -> str:
    """Rótulo do último movimento — data exata (BI) ou mês/ano (fallback da Base.csv)."""
    if data_exata is not None:
        return data_exata.strftime("%d/%m/%Y")
    ultimo = df["Data_Venda"].max()
    if pd.isna(ultimo):
        return "—"
    return f"{MESES_NOME[int(ultimo.month)]}/{int(ultimo.year)}"


def gerar_summary(
    df: pd.DataFrame,
    updated_at: str | None = None,
    data_ultimo_movimento: date | None = None,
) -> dict:
    """Gera o dict do summary do dashboard a partir do DataFrame limpo do motor.

    `df` deve ser a saída de analise_funil.carregar_csv()/carregar_excel_base()
    (colunas Loja, Cliente, NOME_FABRICANTE, descricao, Código de referêcia,
    Receita, QTD, Data_Venda).
    """
    colunas_base: dict = {
            "store": df["Loja"].astype(str),
            "client": df["Cliente"].astype(str),
            "mfr": df["NOME_FABRICANTE"].astype(str),
            "desc": df["descricao"].astype(str),
            # carregar_csv preenche referência vazia com "" — o dashboard
            # estático usa o rótulo "S/ REF" (ver process_data.py).
            "ref": df["Código de referêcia"].astype(str).replace("", "S/ REF"),
            "year": df["Data_Venda"].dt.year,
            "m_num": df["Data_Venda"].dt.month,
            "rev": df["Receita"].astype(float),
            "qty": df["QTD"].astype(int),
            "cmv": df["CMV"].astype(float).fillna(0.0) if "CMV" in df.columns else 0.0,
    }

    # Data diária real (quando a fonte tem coluna de dia) — usada para contar
    # quantos dias distintos tiveram venda em cada período. Permite calcular
    # média diária dividindo pela realidade da base em vez dos dias úteis do
    # calendário (que superestima quando a empresa não vende todo dia útil).
    tem_data_diaria = "Data_Venda_Diaria" in df.columns and df["Data_Venda_Diaria"].notna().any()
    if tem_data_diaria:
        colunas_base["data_diaria"] = pd.to_datetime(df["Data_Venda_Diaria"], errors="coerce")

    base = pd.DataFrame(colunas_base)
    base["p_p_id"] = base["year"] * 100 + base["m_num"]

    # Dias distintos com venda por período — só quando a fonte informa o dia.
    dias_com_venda_por_periodo: dict[int, int] = {}
    if tem_data_diaria:
        _datas_validas = base.dropna(subset=["data_diaria"])
        if len(_datas_validas):
            dias_com_venda_por_periodo = (
                _datas_validas.groupby("p_p_id")["data_diaria"]
                .apply(lambda s: s.dt.date.nunique())
                .to_dict()
            )

    agg = (
        base.groupby(["p_p_id", "store", "client", "mfr", "desc", "ref"], sort=False)
        .agg(rev=("rev", "sum"), qty=("qty", "sum"))
        .reset_index()
    )

    # Dimensões ordenadas por receita decrescente (mesma UX do summary estático)
    def _mapa_ordenado(coluna: str) -> list:
        return base.groupby(coluna)["rev"].sum().sort_values(ascending=False).index.tolist()

    maps = {
        "s": _mapa_ordenado("store"),
        "c": _mapa_ordenado("client"),
        "m": _mapa_ordenado("mfr"),
        "d": _mapa_ordenado("desc"),
        "r": _mapa_ordenado("ref"),
        "p": sorted(int(p) for p in base["p_p_id"].unique()),
    }
    indices = {chave: {valor: i for i, valor in enumerate(valores)} for chave, valores in maps.items()}

    rows = [
        [p, s, c, m, d, r, round(float(rev), 2), int(qty)]
        for p, s, c, m, d, r, rev, qty in zip(
            agg["p_p_id"].map(indices["p"]),
            agg["store"].map(indices["s"]),
            agg["client"].map(indices["c"]),
            agg["mfr"].map(indices["m"]),
            agg["desc"].map(indices["d"]),
            agg["ref"].map(indices["r"]),
            agg["rev"],
            agg["qty"],
        )
    ]

    mensal = (
        base.groupby(["p_p_id", "year", "m_num"])[["rev", "cmv"]]
        .sum()
        .reset_index()
        .sort_values("p_p_id")
    )
    monthly = []
    for linha in mensal.itertuples():
        entrada: dict = {
            "name": f"{MESES_ABREV[int(linha.m_num)]}/{str(int(linha.year))[2:]}",
            "rev": round(float(linha.rev), 2),
            "cmv": round(float(linha.cmv), 2),
            "pid": int(linha.p_p_id),
            "year": int(linha.year),
        }
        dias = dias_com_venda_por_periodo.get(int(linha.p_p_id))
        if dias is not None:
            entrada["dias_com_venda"] = int(dias)
        monthly.append(entrada)

    yoy = {str(int(ano)): round(float(total), 2) for ano, total in base.groupby("year")["rev"].sum().items()}

    return {
        "maps": maps,
        "rows": rows,
        "monthly": monthly,
        "yoy": yoy,
        # "Atualizado" no dashboard = último movimento da base, não o mtime do arquivo.
        "updated_at": (
            updated_at
            if updated_at is not None
            else formatar_ultimo_movimento(df, data_ultimo_movimento)
        ),
        "kpis": {
            "rev": round(float(base["rev"].sum()), 2),
            "qty": int(base["qty"].sum()),
            "avg": round(float(base["rev"].mean()), 2) if len(base) else 0.0,
            "cnt": int(len(base)),
            "cmv": round(float(base["cmv"].sum()), 2),
        },
    }


def aplicar_cortes_no_summary(summary: dict, cortes: dict) -> dict:
    """Recorta o summary pré-agregado com as mesmas exclusões do Relatórios.

    Não relê a base: filtra `rows` por cliente/produto e reconstrói monthly/yoy/kpis.
    O arquivo em disco continua o summary cheio, compartilhado.
    """
    if not isinstance(summary, dict):
        return summary
    maps = summary.get("maps") or {}
    rows = summary.get("rows") or []
    clientes = list(maps.get("c") or [])
    produtos = list(maps.get("d") or [])
    if not rows:
        return summary

    drop_c = {str(n).strip() for n in (cortes.get("clientes_excluidos") or []) if str(n).strip()}
    drop_d = {str(n).strip() for n in (cortes.get("produtos_excluidos") or []) if str(n).strip()}
    if cortes.get("desconsiderar_balcao") and clientes:
        mascara_balcao_geral = mascara_clientes_balcao(
            pd.Series(clientes), cortes.get("clientes_balcao_extra") or [],
        )
        drop_c |= set(pd.Series(clientes)[mascara_balcao_geral])
    if cortes.get("desconsiderar_nao_harmonizados"):
        drop_d |= {nome for nome in produtos if eh_produto_nao_harmonizado(nome)}

    if cortes.get("desconsiderar_demais_produtos") and produtos:
        rev_por_produto: dict[str, float] = defaultdict(float)
        for row in rows:
            try:
                nome = produtos[int(row[4])]
            except (IndexError, TypeError, ValueError):
                continue
            if nome in drop_d:
                continue
            rev_por_produto[nome] += float(row[6] or 0)
        if rev_por_produto:
            frame = pd.DataFrame(
                {"descricao": list(rev_por_produto.keys()), "Receita": list(rev_por_produto.values())}
            )
            classificado = classificar_produtos_agregado(
                frame, float(cortes.get("corte_produtos") or 80.0),
            )
            drop_d |= {
                str(nome)
                for nome in classificado.loc[classificado["Faixa"] == "Demais", "descricao"]
            }

    grupos_clientes = cortes.get("grupos_clientes")
    if grupos_clientes and clientes:
        rev_por_cliente: dict[str, float] = defaultdict(float)
        for row in rows:
            try:
                nome = clientes[int(row[2])]
            except (IndexError, TypeError, ValueError):
                continue
            if nome in drop_c:
                continue
            try:
                nome_produto = produtos[int(row[4])]
            except (IndexError, TypeError, ValueError):
                nome_produto = None
            if nome_produto is not None and nome_produto in drop_d:
                continue
            rev_por_cliente[nome] += float(row[6] or 0)
        if rev_por_cliente:
            desconsiderar_balcao = bool(cortes.get("desconsiderar_balcao"))
            balcao_extra = cortes.get("clientes_balcao_extra") or []
            cortes_pct = cortes.get("cortes_clientes") or [30.0, 50.0, 60.0]
            nomes_serie = pd.Series(list(rev_por_cliente.keys()))
            if desconsiderar_balcao:
                mascara = mascara_clientes_balcao(nomes_serie, balcao_extra)
                balcao_nomes = set(nomes_serie[mascara])
            else:
                balcao_nomes = set()
            normais = {n: v for n, v in rev_por_cliente.items() if n not in balcao_nomes}
            mapa_faixa: dict[str, str] = {}
            if normais:
                curva = curva_pareto(pd.Series(normais))
                faixas = faixa_por_curva(curva, cortes_pct)
                mapa_faixa = dict(zip(curva.index, faixas))
            mantidos: set[str] = set()
            for nome in normais:
                faixa = mapa_faixa.get(nome, "Demais")
                token = "X" if faixa == "Demais" else (
                    faixa.split(" ")[-1] if faixa.startswith("Grupo ") else "X"
                )
                if token in grupos_clientes:
                    mantidos.add(nome)
            if "B" in grupos_clientes:
                mantidos |= balcao_nomes
            drop_c |= set(rev_por_cliente.keys()) - mantidos

    if not drop_c and not drop_d:
        return summary

    drop_c_idx = {i for i, nome in enumerate(clientes) if nome in drop_c}
    drop_d_idx = {i for i, nome in enumerate(produtos) if nome in drop_d}
    kept = [
        row for row in rows
        if int(row[2]) not in drop_c_idx and int(row[4]) not in drop_d_idx
    ]
    if len(kept) == len(rows):
        return summary

    pids = list(maps.get("p") or [])
    rev_pid: dict[int, float] = defaultdict(float)
    qty_pid: dict[int, float] = defaultdict(float)
    total_rev = 0.0
    total_qty = 0.0
    for row in kept:
        try:
            pid = int(pids[int(row[0])])
        except (IndexError, TypeError, ValueError):
            continue
        rev = float(row[6] or 0)
        qty = float(row[7] or 0)
        rev_pid[pid] += rev
        qty_pid[pid] += qty
        total_rev += rev
        total_qty += qty

    monthly = []
    for item in summary.get("monthly") or []:
        pid = int(item.get("pid") or 0)
        if pid not in rev_pid:
            continue
        orig_rev = float(item.get("rev") or 0)
        orig_cmv = float(item.get("cmv") or 0)
        novo = dict(item)
        novo["rev"] = round(rev_pid[pid], 2)
        novo["cmv"] = round(orig_cmv * (novo["rev"] / orig_rev), 2) if orig_rev else 0.0
        monthly.append(novo)

    yoy: dict[str, float] = defaultdict(float)
    for pid, rev in rev_pid.items():
        yoy[str(pid // 100)] += rev
    yoy_out = {ano: round(valor, 2) for ano, valor in yoy.items()}

    orig_kpis = summary.get("kpis") or {}
    orig_rev = float(orig_kpis.get("rev") or 0)
    orig_cmv = float(orig_kpis.get("cmv") or 0)
    kpis = {
        "rev": round(total_rev, 2),
        "qty": int(total_qty),
        "avg": round(total_rev / len(kept), 2) if kept else 0.0,
        "cnt": int(len(kept)),
        "cmv": round(orig_cmv * (total_rev / orig_rev), 2) if orig_rev else 0.0,
    }

    remap_keys = (("p", 0), ("s", 1), ("c", 2), ("m", 3), ("d", 4), ("r", 5))
    novos_maps: dict[str, list] = {}
    remaps: dict[str, dict[int, int]] = {}
    usados: dict[str, set[int]] = {chave: set() for chave, _ in remap_keys}
    for row in kept:
        for chave, pos in remap_keys:
            try:
                usados[chave].add(int(row[pos]))
            except (IndexError, TypeError, ValueError):
                continue
    for chave, _pos in remap_keys:
        velho = list(maps.get(chave) or [])
        ordem = [i for i in range(len(velho)) if i in usados[chave]]
        novos_maps[chave] = [velho[i] for i in ordem]
        remaps[chave] = {antigo: novo for novo, antigo in enumerate(ordem)}

    novas_rows = []
    for row in kept:
        try:
            novas_rows.append([
                remaps["p"][int(row[0])],
                remaps["s"][int(row[1])],
                remaps["c"][int(row[2])],
                remaps["m"][int(row[3])],
                remaps["d"][int(row[4])],
                remaps["r"][int(row[5])],
                round(float(row[6] or 0), 2),
                int(row[7] or 0),
            ])
        except (KeyError, IndexError, TypeError, ValueError):
            continue

    saida = dict(summary)
    saida["maps"] = novos_maps
    saida["rows"] = novas_rows
    saida["monthly"] = monthly
    saida["yoy"] = yoy_out
    saida["kpis"] = kpis
    return saida

