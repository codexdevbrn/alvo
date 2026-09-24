"""Acompanhamento pós-precificação.

O dump `{empresa}_PRECIFICACAO.csv` diz *quem* entrou na rodada e *qual* alvo
de margem foi gravado. O movimento da empresa diz *como* a loja vendeu antes
e depois da data do dump.

Sem código de produto no dump: o join é `descricao` (= DESCRICAO_HARMONIZADA)
+ `fabricante`. Com `apenas_precificados`, só os pares do dump entram no
movimento; sem ele, entra o catálogo inteiro e família/fabricante fora do
dump vira item `nao_precificado` (sem alvo). O alvo geral só existe no
recorte precificado — comparar a margem da loja inteira com o alvo de uma
parte dela seria número sem significado.

A série mensal cobre as duas janelas (antes + depois) para o gráfico parecer
com o da tela de precificação: margem, lucro bruto / dia com venda e
quantidade / dia com venda. `lucro_dia` e `qtd_dia` são as mesmas medidas do
monitor — valor do mês ÷ dias com venda real, não ÷ dias úteis de calendário.
"""

from __future__ import annotations

import math
from collections import Counter
from typing import Any

import pandas as pd

from periodo_mensal import (
    deslocar_mes,
    inicio_mes,
    numero,
    rotulo_periodo,
    variacao,
)

COLUNA_DATA_DIARIA = "Data_Venda_Diaria"
COLUNA_DATA_MES = "Data_Venda"
COLUNA_RECEITA = "Receita"
COLUNA_CMV = "CMV"
COLUNA_QTD = "QTD"

SITUACOES = ("acima", "abaixo", "no_alvo", "sem_venda", "sem_alvo", "nao_precificado")

# Janela da visão "Detalhada": dia a dia, não mês a mês. Fixa e pequena de
# propósito — é um zoom no entorno do corte, não outra forma de ver a janela
# antes/depois inteira (que já é o gráfico mensal).
JANELA_DETALHE_DIAS = 20


def _chave_texto(serie: pd.Series) -> pd.Series:
    return serie.fillna("").astype(str).str.strip().str.casefold()


def _margem_pct(receita: float, cmv: float) -> float | None:
    if receita <= 0:
        return None
    return (receita - cmv) / receita * 100


def _por_dia(valor: float, dias: int) -> float | None:
    if dias <= 0:
        return None
    return valor / dias


def _ponderar(valores: pd.Series, pesos: pd.Series) -> float | None:
    validos = valores.notna() & pesos.notna() & (pesos > 0)
    if not bool(validos.any()):
        return None
    peso = float(pesos.loc[validos].sum())
    if peso <= 0:
        return None
    return float((valores.loc[validos] * pesos.loc[validos]).sum() / peso)


def _json_num(valor: Any) -> float:
    return round(numero(valor), 4)


def _json_opt(valor: Any) -> float | None:
    if valor is None:
        return None
    try:
        if pd.isna(valor):
            return None
    except (TypeError, ValueError):
        return None
    try:
        convertido = float(valor)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(convertido):
        return None
    return round(convertido, 4)


def _iso(valor: pd.Timestamp | None) -> str | None:
    if valor is None or pd.isna(valor):
        return None
    return pd.Timestamp(valor).strftime("%Y-%m-%d")


def _datas_movimento(movimento: pd.DataFrame) -> pd.Series:
    if COLUNA_DATA_DIARIA in movimento.columns:
        datas = pd.to_datetime(movimento[COLUNA_DATA_DIARIA], errors="coerce")
        if bool(datas.notna().any()):
            return datas
    if COLUNA_DATA_MES in movimento.columns:
        return pd.to_datetime(movimento[COLUNA_DATA_MES], errors="coerce")
    return pd.Series(pd.NaT, index=movimento.index, dtype="datetime64[ns]")


def _contar_dias_venda(df: pd.DataFrame) -> int:
    if df.empty or "_data" not in df.columns:
        return 0
    tem_data = df["_data"].notna()
    ativo = pd.Series(False, index=df.index)
    if COLUNA_RECEITA in df.columns:
        ativo = ativo | (df[COLUNA_RECEITA].fillna(0) != 0)
    if COLUNA_QTD in df.columns:
        ativo = ativo | (df[COLUNA_QTD].fillna(0) != 0)
    validos = df.loc[tem_data & ativo, "_data"]
    if validos.empty:
        return 0
    # `_data` já é datetime64 (ver `_datas_movimento`) — `pd.to_datetime` aqui era
    # reconversão redundante, chamada centenas de vezes (uma por família/fabricante
    # × janela), com overhead fixo de dispatch do pandas somando no total.
    return int(validos.dt.normalize().nunique())


def _montar_agregado(receita: float, cmv: float, qtd: float, dias: int) -> dict[str, Any]:
    lucro = receita - cmv
    return {
        "receita": receita,
        "cmv": cmv,
        "qtd": qtd,
        "lucro": lucro,
        "margem": _margem_pct(receita, cmv),
        "dias_venda": dias,
        "lucro_dia": _por_dia(lucro, dias),
        "qtd_dia": _por_dia(qtd, dias),
    }


def _agregar(df: pd.DataFrame) -> dict[str, Any]:
    if df.empty:
        return _montar_agregado(0.0, 0.0, 0.0, 0)
    receita = float(df[COLUNA_RECEITA].sum())
    cmv = float(df[COLUNA_CMV].sum()) if COLUNA_CMV in df.columns else 0.0
    qtd = float(df[COLUNA_QTD].sum()) if COLUNA_QTD in df.columns else 0.0
    return _montar_agregado(receita, cmv, qtd, _contar_dias_venda(df))


def _agregar_por_chave(df: pd.DataFrame, coluna: str) -> dict[str, dict[str, Any]]:
    """`_agregar` de cada família/fabricante num groupby só.

    No recorte "todos" são ~700 itens; chamar `_agregar` por item (e por
    janela fixa) fatiava o movimento milhares de vezes e levava a tela a
    ~17 s. Mesmas regras de `_agregar`/`_contar_dias_venda`."""
    if df.empty or coluna not in df.columns or "_data" not in df.columns:
        return {}
    chave = _chave_texto(df[coluna])
    somas = df.groupby(chave)[[COLUNA_RECEITA, COLUNA_CMV, COLUNA_QTD]].sum()
    ativo = df["_data"].notna() & (
        (df[COLUNA_RECEITA].fillna(0) != 0) | (df[COLUNA_QTD].fillna(0) != 0)
    )
    dias = df.loc[ativo, "_data"].dt.normalize().groupby(chave[ativo]).nunique()
    return {
        k: _montar_agregado(float(rec), float(cmv), float(qtd), int(dias.get(k, 0)))
        for k, rec, cmv, qtd in zip(
            somas.index, somas[COLUNA_RECEITA], somas[COLUNA_CMV], somas[COLUNA_QTD],
        )
    }


# Cartões "semana / quinzena / mês pós precificação": comparação de mesmo
# comprimento (N dias antes do corte vs N dias depois), não a janela
# antes/depois inteira — essa responde "melhorou no total", os cartões
# respondem "melhorou logo na largada, e continuou melhorando".
JANELAS_FIXAS: tuple[tuple[str, int], ...] = (("semana", 7), ("quinzena", 15), ("mes", 30))


def _fatia_por_dias(
    mov_pares: pd.DataFrame,
    data_corte: pd.Timestamp | None,
    dias: int,
    lado: str,
) -> pd.DataFrame:
    if mov_pares.empty or "_data" not in mov_pares.columns or data_corte is None:
        return mov_pares.iloc[0:0]
    if lado == "depois":
        ini, fim = data_corte, data_corte + pd.Timedelta(days=dias)
    else:
        ini, fim = data_corte - pd.Timedelta(days=dias), data_corte
    mascara = (mov_pares["_data"] >= ini) & (mov_pares["_data"] < fim)
    return mov_pares.loc[mascara]


def _variacoes_por_dia(ant: dict[str, Any], dep: dict[str, Any]) -> dict[str, float | None]:
    """Variação antes → depois pela média por dia com venda, não pelo total.

    "Antes" vai do primeiro dado até o corte e "depois" do corte ao último —
    comprimentos diferentes, então o total inflava a variação (IBAD mostrava
    +210% de lucro com 47 dias de um lado e 133 do outro). As janelas fixas
    (semana/mês) têm o mesmo comprimento dos dois lados e seguem no total."""
    def var(chave: str) -> float | None:
        atual = _por_dia(dep[chave], dep["dias_venda"])
        base = _por_dia(ant[chave], ant["dias_venda"])
        if atual is None or base is None:
            return None
        return _json_opt(variacao(atual, base))

    return {
        "variacao_receita_pct": var("receita"),
        "variacao_lucro_pct": var("lucro"),
        "variacao_qtd_pct": var("qtd"),
    }


def _janela_completa(
    data_corte: pd.Timestamp | None, dias: int, ultimo_disponivel: pd.Timestamp | None,
) -> bool:
    return bool(
        data_corte is not None
        and ultimo_disponivel is not None
        and ultimo_disponivel >= data_corte + pd.Timedelta(days=dias - 1)
    )


def _janela_fixa(
    ant: dict[str, Any], dep: dict[str, Any], alvo: float | None, dias: int, completa: bool,
) -> dict:
    gap = None if dep["margem"] is None or alvo is None else dep["margem"] - alvo
    return {
        "dias": dias,
        "completa": completa,
        "receita_antes": _json_num(ant["receita"]),
        "receita_depois": _json_num(dep["receita"]),
        "lucro_antes": _json_num(ant["lucro"]),
        "lucro_depois": _json_num(dep["lucro"]),
        "qtd_antes": _json_num(ant["qtd"]),
        "qtd_depois": _json_num(dep["qtd"]),
        "margem_antes": _json_opt(ant["margem"]),
        "margem_depois": _json_opt(dep["margem"]),
        "dias_venda_antes": int(ant["dias_venda"]),
        "dias_venda_depois": int(dep["dias_venda"]),
        "lucro_dia_antes": _json_opt(ant["lucro_dia"]),
        "lucro_dia_depois": _json_opt(dep["lucro_dia"]),
        "qtd_dia_antes": _json_opt(ant["qtd_dia"]),
        "qtd_dia_depois": _json_opt(dep["qtd_dia"]),
        "variacao_receita_pct": _json_opt(variacao(dep["receita"], ant["receita"])),
        "variacao_lucro_pct": _json_opt(variacao(dep["lucro"], ant["lucro"])),
        "variacao_qtd_pct": _json_opt(variacao(dep["qtd"], ant["qtd"])),
        "margem_alvo": _json_opt(alvo),
        "gap_alvo_pp": _json_opt(gap),
    }


def _resumo_janela_fixa(
    dump_grupo: pd.DataFrame,
    mov_pares: pd.DataFrame,
    data_corte: pd.Timestamp | None,
    dias: int,
    ultimo_disponivel: pd.Timestamp | None,
) -> dict:
    return _janela_fixa(
        _agregar(_fatia_por_dias(mov_pares, data_corte, dias, "antes")),
        _agregar(_fatia_por_dias(mov_pares, data_corte, dias, "depois")),
        _ponderar(dump_grupo["margem_alvo"], dump_grupo["receita"]),
        dias,
        _janela_completa(data_corte, dias, ultimo_disponivel),
    )


def _janela_fixa_vazia(dias: int) -> dict:
    return {
        "dias": dias,
        "completa": False,
        "receita_antes": 0.0,
        "receita_depois": 0.0,
        "lucro_antes": 0.0,
        "lucro_depois": 0.0,
        "qtd_antes": 0.0,
        "qtd_depois": 0.0,
        "margem_antes": None,
        "margem_depois": None,
        "dias_venda_antes": 0,
        "dias_venda_depois": 0,
        "lucro_dia_antes": None,
        "lucro_dia_depois": None,
        "qtd_dia_antes": None,
        "qtd_dia_depois": None,
        "variacao_receita_pct": None,
        "variacao_lucro_pct": None,
        "variacao_qtd_pct": None,
        "margem_alvo": None,
        "gap_alvo_pp": None,
    }


def _janelas_fixas(
    dump_grupo: pd.DataFrame,
    mov_pares: pd.DataFrame,
    data_corte: pd.Timestamp | None,
    ultimo_disponivel: pd.Timestamp | None,
) -> dict[str, dict]:
    return {
        chave: _resumo_janela_fixa(dump_grupo, mov_pares, data_corte, dias, ultimo_disponivel)
        for chave, dias in JANELAS_FIXAS
    }


def _item_entidade(
    nome: str,
    dump_grupo: pd.DataFrame,
    alvo: float | None,
    ant: dict[str, Any],
    dep: dict[str, Any],
    serie: list[dict],
    serie_diaria: list[dict],
    janelas: dict[str, dict],
) -> dict:
    precificado = not dump_grupo.empty
    gap = None if dep["margem"] is None or alvo is None else dep["margem"] - alvo
    if not precificado:
        situacao = "nao_precificado"
    elif dep["receita"] <= 0:
        situacao = "sem_venda"
    elif gap is None:
        situacao = "sem_alvo"
    elif abs(gap) <= 1.0:
        situacao = "no_alvo"
    elif gap > 0:
        situacao = "acima"
    else:
        situacao = "abaixo"
    return {
        "nome": nome,
        "precificado": precificado,
        "skus_dump": int(len(dump_grupo)),
        "receita_dump": _json_num(dump_grupo["receita"].sum()),
        "margem_anterior_dump": _json_opt(_ponderar(dump_grupo["margem_anterior"], dump_grupo["receita"])),
        "margem_alvo": _json_opt(alvo),
        "receita_antes": _json_num(ant["receita"]),
        "receita_depois": _json_num(dep["receita"]),
        "lucro_antes": _json_num(ant["lucro"]),
        "lucro_depois": _json_num(dep["lucro"]),
        "qtd_antes": _json_num(ant["qtd"]),
        "qtd_depois": _json_num(dep["qtd"]),
        "margem_antes": _json_opt(ant["margem"]),
        "margem_depois": _json_opt(dep["margem"]),
        "dias_venda_antes": int(ant["dias_venda"]),
        "dias_venda_depois": int(dep["dias_venda"]),
        "lucro_dia_antes": _json_opt(ant["lucro_dia"]),
        "lucro_dia_depois": _json_opt(dep["lucro_dia"]),
        "qtd_dia_antes": _json_opt(ant["qtd_dia"]),
        "qtd_dia_depois": _json_opt(dep["qtd_dia"]),
        **_variacoes_por_dia(ant, dep),
        "gap_alvo_pp": _json_opt(gap),
        "situacao": situacao,
        "serie_mensal": serie,
        "serie_diaria": serie_diaria,
        "janelas": janelas,
    }


def listar_rodadas_dump(dump: pd.DataFrame) -> list[dict]:
    """Rodadas dentro do dump, da mais recente para a mais antiga.

    Rodada é o **dia** de `data_exportacao`, não o timestamp: o exportador grava
    linha a linha em microssegundo, então uma exportação de 3804 linhas tem 3804
    timestamps distintos. `linhas` e `pares` vão junto porque o tamanho varia de
    3 a ~15 mil linhas entre rodadas da mesma empresa — sem esse número, uma
    rodada minúscula na tela parece defeito em vez de escolha.
    """
    if dump is None or dump.empty or "data_exportacao" not in dump.columns:
        return []
    datas = pd.to_datetime(dump["data_exportacao"], errors="coerce")
    validas = datas.notna()
    if not bool(validas.any()):
        return []

    base = dump.loc[validas].assign(_dia=datas.loc[validas].dt.date)
    chave = _chave_texto(base["descricao"]) + "\x1f" + _chave_texto(base["fabricante"])
    base = base.assign(_par=chave)
    agrupado = base.groupby("_dia").agg(linhas=("_par", "size"), pares=("_par", "nunique"))
    return [
        {"dia": dia.isoformat(), "linhas": int(linha.linhas), "pares": int(linha.pares)}
        for dia, linha in agrupado.sort_index(ascending=False).iterrows()
    ]


def filtrar_rodada(dump: pd.DataFrame, dia: str | None = None) -> pd.DataFrame:
    """Recorta o dump em **uma** rodada; sem `dia`, a mais recente.

    Necessário porque `montar_pos_precificacao` deriva `data_corte` do máximo de
    `data_exportacao` e monta o universo de pares com todas as linhas recebidas:
    passar várias rodadas de uma vez faria par de rodada antiga contar como se
    fosse da última, e `margem_alvo` ponderaria o mesmo produto uma vez por
    rodada. `dia` desconhecido devolve vazio, e a tela mostra o estado vazio em
    vez de silenciosamente exibir outra rodada.
    """
    if dump is None or dump.empty or "data_exportacao" not in dump.columns:
        return dump if dump is not None else pd.DataFrame()
    datas = pd.to_datetime(dump["data_exportacao"], errors="coerce")
    if not bool(datas.notna().any()):
        return dump.iloc[0:0]

    dias = datas.dt.date
    if dia is None:
        alvo = dias.max()
    else:
        try:
            alvo = pd.Timestamp(dia).date()
        except (ValueError, TypeError):
            return dump.iloc[0:0]
    return dump.loc[dias == alvo]


def montar_pos_precificacao(
    dump: pd.DataFrame,
    movimento: pd.DataFrame,
    *,
    apenas_precificados: bool = True,
) -> dict:
    """Resumo da última rodada de precificação + desempenho no movimento.

    `dump` já vem de `carregar_csv_precificacao`. `movimento` é a base canônica
    (com `descricao`, `NOME_FABRICANTE`, `Receita`, `CMV`, `QTD` e data).

    Sem toggle de mês fechado/completo: a janela usada é sempre o que o
    movimento trouxer, ponta a ponta — pro `margem_price` (fonte padrão) isso
    já é o período certo, porque o parquet em si já vem recortado (ver
    `margem_price.py`); não há corte extra a aplicar aqui.
    """
    vazio = _resposta_vazia()
    if dump is None or dump.empty:
        return vazio

    dump = dump.copy()
    dump = dump[dump["descricao"].astype(str).str.strip() != ""]
    dump = dump[dump["fabricante"].astype(str).str.strip() != ""]
    if dump.empty:
        return vazio

    data_corte = dump["data_exportacao"].max()
    if pd.isna(data_corte):
        data_corte = None
    else:
        data_corte = pd.Timestamp(data_corte).normalize()

    pares = dump.assign(
        _d=_chave_texto(dump["descricao"]),
        _f=_chave_texto(dump["fabricante"]),
    )
    pares["_chave"] = pares["_d"] + "\x1f" + pares["_f"]
    chaves = set(pares["_chave"])

    if movimento is None or movimento.empty or COLUNA_RECEITA not in movimento.columns:
        mov_pares = pd.DataFrame()
        primeiro = None
        ultimo = None
    elif "descricao" not in movimento.columns or "NOME_FABRICANTE" not in movimento.columns:
        mov_pares = pd.DataFrame()
        primeiro = None
        ultimo = None
    else:
        colunas = [coluna for coluna in (
            "descricao", "NOME_FABRICANTE", COLUNA_RECEITA, COLUNA_CMV, COLUNA_QTD,
            COLUNA_DATA_DIARIA, COLUNA_DATA_MES, "Periodo_Mensal",
        ) if coluna in movimento.columns]
        # `mov_pares` é o movimento do recorte: só os pares do dump, ou tudo.
        if apenas_precificados:
            chave_mov = _chave_texto(movimento["descricao"]) + "\x1f" + _chave_texto(movimento["NOME_FABRICANTE"])
            mov_pares = movimento.loc[chave_mov.isin(chaves), colunas].copy()
        else:
            mov_pares = movimento[colunas].copy()
        if COLUNA_CMV not in mov_pares.columns:
            mov_pares[COLUNA_CMV] = 0.0
        if COLUNA_QTD not in mov_pares.columns:
            mov_pares[COLUNA_QTD] = 0.0
        datas = _datas_movimento(mov_pares)
        mov_pares["_data"] = datas
        tem_data = bool(datas.notna().any())
        primeiro = datas.min() if tem_data else None
        ultimo = datas.max() if tem_data else None

    # "Antes" cobre do primeiro dado real até a precificação, "depois" da
    # precificação até o último dado real — sem espelhar duração um do outro
    # (isso fazia a janela "antes" encolher/crescer artificialmente conforme
    # o tempo desde a rodada).
    inicio_depois = data_corte
    fim_depois = pd.Timestamp(ultimo) if ultimo is not None and not pd.isna(ultimo) else None
    inicio_antes = pd.Timestamp(primeiro) if primeiro is not None and not pd.isna(primeiro) else None
    fim_antes = data_corte
    if inicio_depois is not None and fim_depois is not None and fim_depois < inicio_depois:
        fim_depois = None

    if "_data" in mov_pares.columns and not mov_pares.empty:
        mascara_depois = pd.Series(False, index=mov_pares.index)
        mascara_antes = pd.Series(False, index=mov_pares.index)
        if inicio_depois is not None and fim_depois is not None:
            mascara_depois = (mov_pares["_data"] >= inicio_depois) & (mov_pares["_data"] <= fim_depois)
        if inicio_antes is not None and fim_antes is not None:
            mascara_antes = (mov_pares["_data"] >= inicio_antes) & (mov_pares["_data"] < fim_antes)
        depois = mov_pares.loc[mascara_depois]
        antes = mov_pares.loc[mascara_antes]
    else:
        depois = mov_pares.iloc[0:0]
        antes = mov_pares.iloc[0:0]

    ant = _agregar(antes)
    dep = _agregar(depois)
    # Dump vazio no lugar do real tira o alvo (geral e das janelas fixas) do
    # recorte "todos": o alvo só descreve a parte precificada.
    dump_alvo = dump if apenas_precificados else dump.iloc[0:0]
    alvo_geral = _ponderar(dump_alvo["margem_alvo"], dump_alvo["receita"])
    gap_geral = None if dep["margem"] is None or alvo_geral is None else dep["margem"] - alvo_geral

    precos = dump["preco_sugerido"] if "preco_sugerido" in dump.columns else pd.Series(dtype=float)
    skus_com_preco = int(precos.notna().sum()) if not precos.empty else 0

    janela = pd.concat([antes, depois]) if not antes.empty or not depois.empty else depois

    # "Antes" já cobre do primeiro dado real, então antes+depois é a janela
    # inteira sem buraco — mas `_meses_entre` ainda é ponta a ponta pela data
    # mínima/máxima *da linha*, e uma linha isolada com data avulsa (estorno,
    # ajuste, timestamp errado) esticaria o eixo até um mês sem venda nenhuma.
    # `_recortar_meses_com_dado` corta essas pontas pelo que a agregação
    # mensal realmente tem, não pela data crua — o gráfico se ajusta ao dado.
    inicio_serie = inicio_antes if inicio_antes is not None else inicio_depois
    fim_serie = fim_depois if fim_depois is not None else fim_antes
    meses = _meses_entre(inicio_serie, fim_serie)
    totais_geral = _totais_mensais(janela)
    mes_corte = inicio_mes(data_corte) if data_corte is not None else None
    meses = _recortar_meses_com_dado(meses, totais_geral, mes_corte)
    serie_geral = _pontos_serie(totais_geral, meses)
    nomes_prod = dump["descricao"]
    nomes_fab = dump["fabricante"]
    if not apenas_precificados and not mov_pares.empty:
        nomes_prod = pd.concat([nomes_prod, mov_pares["descricao"]]).drop_duplicates()
        nomes_fab = pd.concat([nomes_fab, mov_pares["NOME_FABRICANTE"]]).drop_duplicates()
    series_prod = _series_por_nome(janela, "descricao", nomes_prod, meses)
    series_fab = _series_por_nome(janela, "NOME_FABRICANTE", nomes_fab, meses)

    janela_dia_ini = None if data_corte is None else data_corte - pd.Timedelta(days=JANELA_DETALHE_DIAS)
    janela_dia_fim = None if data_corte is None else data_corte + pd.Timedelta(days=JANELA_DETALHE_DIAS)
    if janela_dia_ini is not None and inicio_antes is not None:
        janela_dia_ini = max(janela_dia_ini, inicio_antes)
    if janela_dia_fim is not None and fim_depois is not None:
        janela_dia_fim = min(janela_dia_fim, fim_depois)
    dias_detalhe = _dias_entre(janela_dia_ini, janela_dia_fim)
    serie_diaria_geral = _pontos_serie_diaria(_totais_diarios(janela), dias_detalhe)
    series_prod_dia = _series_por_nome_dia(janela, "descricao", nomes_prod, dias_detalhe)
    series_fab_dia = _series_por_nome_dia(janela, "NOME_FABRICANTE", nomes_fab, dias_detalhe)

    janelas_geral = _janelas_fixas(dump_alvo, mov_pares, data_corte, fim_depois)
    produtos = _rollup(
        dump, antes, depois, "descricao", "descricao", series_prod, series_prod_dia,
        mov_pares, data_corte, fim_depois,
        incluir_nao_precificados=not apenas_precificados,
    )
    fabricantes = _rollup(
        dump, antes, depois, "fabricante", "NOME_FABRICANTE", series_fab, series_fab_dia,
        mov_pares, data_corte, fim_depois,
        incluir_nao_precificados=not apenas_precificados,
    )

    return {
        "data_precificacao": _iso(data_corte),
        "periodo_corte": inicio_mes(data_corte).strftime("%Y-%m") if data_corte is not None else None,
        "periodo_antes": {"inicio": _iso(inicio_antes), "fim": _iso(fim_antes)},
        "periodo_depois": {"inicio": _iso(inicio_depois), "fim": _iso(fim_depois)},
        "dias": int((fim_depois - inicio_depois).days) if inicio_depois is not None and fim_depois is not None else 0,
        "linhas_dump": int(len(dump)),
        "familias": int(dump["descricao"].nunique()),
        "fabricantes_qtd": int(dump["fabricante"].nunique()),
        "pares": int(len(chaves)),
        "skus_com_preco_sugerido": skus_com_preco,
        "tem_movimento_depois": dep["receita"] > 0,
        "resumo": {
            "receita_dump": _json_num(dump["receita"].sum()),
            "margem_anterior_dump": _json_opt(_ponderar(dump["margem_anterior"], dump["receita"])),
            "margem_alvo": _json_opt(alvo_geral),
            "receita_antes": _json_num(ant["receita"]),
            "receita_depois": _json_num(dep["receita"]),
            "lucro_antes": _json_num(ant["lucro"]),
            "lucro_depois": _json_num(dep["lucro"]),
            "qtd_antes": _json_num(ant["qtd"]),
            "qtd_depois": _json_num(dep["qtd"]),
            "margem_antes": _json_opt(ant["margem"]),
            "margem_depois": _json_opt(dep["margem"]),
            "dias_venda_antes": int(ant["dias_venda"]),
            "dias_venda_depois": int(dep["dias_venda"]),
            "lucro_dia_antes": _json_opt(ant["lucro_dia"]),
            "lucro_dia_depois": _json_opt(dep["lucro_dia"]),
            "qtd_dia_antes": _json_opt(ant["qtd_dia"]),
            "qtd_dia_depois": _json_opt(dep["qtd_dia"]),
            **_variacoes_por_dia(ant, dep),
            "gap_alvo_pp": _json_opt(gap_geral),
            "situacoes": _contar_situacoes(produtos),
            "janelas": janelas_geral,
        },
        "serie_mensal": serie_geral,
        "serie_diaria": serie_diaria_geral,
        "produtos": produtos,
        "fabricantes": fabricantes,
    }


def _meses_entre(inicio: pd.Timestamp | None, fim: pd.Timestamp | None) -> list[pd.Timestamp]:
    if inicio is None or fim is None or pd.isna(inicio) or pd.isna(fim) or fim < inicio:
        return []
    cursor = inicio_mes(pd.Timestamp(inicio))
    ultimo = inicio_mes(pd.Timestamp(fim))
    meses: list[pd.Timestamp] = []
    while cursor <= ultimo and len(meses) < 36:
        meses.append(cursor)
        cursor = deslocar_mes(cursor, 1)
    return meses


def _recortar_meses_com_dado(
    meses: list[pd.Timestamp], totais: pd.DataFrame, mes_corte: pd.Timestamp | None,
) -> list[pd.Timestamp]:
    """Corta as pontas do eixo mensal sem dado real. `meses` nasce ponta a
    ponta pela data mínima/máxima *da linha* em `mov_pares`; uma linha isolada
    com data avulsa (estorno, ajuste, timestamp de origem errado) esticaria o
    gráfico até um mês sem nenhuma venda de verdade. O mês da precificação
    sempre entra, mesmo vazio — é a referência do corte no gráfico."""
    if totais.empty or "dias_venda" not in totais.columns:
        com_dado = set()
    else:
        # `totais` tem uma linha por mês que apareceu em `mov_pares`, mesmo
        # que só com um lançamento de valor zero (ajuste/estorno pontual) —
        # `dias_venda > 0` é o mesmo critério de "mês ativo" usado no resto
        # do módulo (`_agregar`/`_contar_dias_venda`), não só "teve linha".
        com_dado = set(totais.index[totais["dias_venda"] > 0])
    if mes_corte is not None:
        com_dado.add(mes_corte)
    presentes = [mes for mes in meses if mes in com_dado]
    if not presentes:
        return meses
    primeiro, ultimo = presentes[0], presentes[-1]
    return [mes for mes in meses if primeiro <= mes <= ultimo]


def _totais_mensais(df: pd.DataFrame, extra_grupo: str | None = None) -> pd.DataFrame:
    if df.empty or "_data" not in df.columns:
        return pd.DataFrame()
    tmp = df.loc[df["_data"].notna()].copy()
    if tmp.empty:
        return pd.DataFrame()
    # Truncar pra início do mês vetorizado (numpy), não `.map(lambda ...)` linha a
    # linha: numa empresa com movimento grande (centenas de milhares de linhas na
    # janela antes+depois), o `.map` chamando `inicio_mes` por linha era o maior
    # custo isolado da tela — o mesmo resultado de `inicio_mes` (normaliza e crava
    # dia 1), só que em lote.
    tmp["_mes"] = tmp["_data"].values.astype("datetime64[M]").astype("datetime64[ns]")
    tmp["_dia"] = pd.to_datetime(tmp["_data"]).dt.normalize()
    if COLUNA_QTD not in tmp.columns:
        tmp[COLUNA_QTD] = 0.0
    if COLUNA_CMV not in tmp.columns:
        tmp[COLUNA_CMV] = 0.0
    ativo = (tmp[COLUNA_RECEITA].fillna(0) != 0) | (tmp[COLUNA_QTD].fillna(0) != 0)
    grupos = ["_mes"] if extra_grupo is None else [extra_grupo, "_mes"]
    totais = tmp.groupby(grupos, sort=True).agg(
        receita=(COLUNA_RECEITA, "sum"),
        cmv=(COLUNA_CMV, "sum"),
        qtd=(COLUNA_QTD, "sum"),
    )
    dias = tmp.loc[ativo].groupby(grupos)["_dia"].nunique()
    totais["dias_venda"] = dias.reindex(totais.index).fillna(0).astype(int)
    return totais


def _pontos_serie(totais: pd.DataFrame, meses: list[pd.Timestamp]) -> list[dict]:
    linhas = {} if totais.empty else totais.to_dict("index")
    pontos = []
    for mes in meses:
        linha = linhas.get(mes)
        rec, cmv, qtd, dias = (
            (0.0, 0.0, 0.0, 0) if linha is None
            else (float(linha["receita"]), float(linha["cmv"]), float(linha["qtd"]), int(linha["dias_venda"]))
        )
        lucro = rec - cmv
        pontos.append({
            "periodo": mes.strftime("%Y-%m"),
            "rotulo": rotulo_periodo(mes),
            "receita": _json_num(rec),
            "lucro": _json_num(lucro),
            "qtd": _json_num(qtd),
            "margem": _json_opt(_margem_pct(rec, cmv)),
            "dias_venda": int(dias),
            "lucro_dia": _json_opt(_por_dia(lucro, int(dias))),
            "qtd_dia": _json_opt(_por_dia(qtd, int(dias))),
        })
    return pontos


def _dias_entre(inicio: pd.Timestamp | None, fim: pd.Timestamp | None, limite: int = 90) -> list[pd.Timestamp]:
    if inicio is None or fim is None or pd.isna(inicio) or pd.isna(fim) or fim < inicio:
        return []
    cursor = pd.Timestamp(inicio).normalize()
    ultimo = pd.Timestamp(fim).normalize()
    dias: list[pd.Timestamp] = []
    while cursor <= ultimo and len(dias) < limite:
        dias.append(cursor)
        cursor = cursor + pd.Timedelta(days=1)
    return dias


def _totais_diarios(df: pd.DataFrame, extra_grupo: str | None = None) -> pd.DataFrame:
    if df.empty or "_data" not in df.columns:
        return pd.DataFrame()
    tmp = df.loc[df["_data"].notna()].copy()
    if tmp.empty:
        return pd.DataFrame()
    tmp["_dia"] = pd.to_datetime(tmp["_data"]).dt.normalize()
    if COLUNA_QTD not in tmp.columns:
        tmp[COLUNA_QTD] = 0.0
    if COLUNA_CMV not in tmp.columns:
        tmp[COLUNA_CMV] = 0.0
    grupos = ["_dia"] if extra_grupo is None else [extra_grupo, "_dia"]
    return tmp.groupby(grupos, sort=True).agg(
        receita=(COLUNA_RECEITA, "sum"),
        cmv=(COLUNA_CMV, "sum"),
        qtd=(COLUNA_QTD, "sum"),
    )


def _pontos_serie_diaria(totais: pd.DataFrame, dias: list[pd.Timestamp]) -> list[dict]:
    """Um ponto por dia *com venda* da janela de detalhe.

    Fim de semana e feriado sem movimento não entram — não é dado zero, é
    ausência de loja aberta, e plotar isso quebrava o gráfico em dentes de
    serra. A granularidade já é o dia, então `lucro_dia`/`qtd_dia` são o
    próprio lucro/qtd do dia."""
    linhas = {} if totais.empty else totais.to_dict("index")
    pontos = []
    for dia in dias:
        linha = linhas.get(dia)
        if linha is None:
            continue
        rec, cmv, qtd = float(linha["receita"]), float(linha["cmv"]), float(linha["qtd"])
        if rec == 0 and qtd == 0:
            continue
        lucro = rec - cmv
        pontos.append({
            "periodo": dia.strftime("%Y-%m-%d"),
            "rotulo": dia.strftime("%d/%m"),
            "receita": _json_num(rec),
            "lucro": _json_num(lucro),
            "qtd": _json_num(qtd),
            "margem": _json_opt(_margem_pct(rec, cmv)),
            "dias_venda": 1,
            "lucro_dia": _json_opt(lucro),
            "qtd_dia": _json_opt(qtd),
        })
    return pontos


def _series_por_nome_dia(
    df: pd.DataFrame,
    coluna: str,
    nomes: pd.Series,
    dias: list[pd.Timestamp],
) -> dict[str, list[dict]]:
    unicos: list[str] = []
    vistos: set[str] = set()
    for nome in nomes:
        rotulo = "—" if pd.isna(nome) or str(nome).strip() == "" else str(nome).strip()
        if rotulo in vistos:
            continue
        vistos.add(rotulo)
        unicos.append(rotulo)
    if not unicos:
        return {}
    if df.empty or coluna not in df.columns:
        return {nome: _pontos_serie_diaria(pd.DataFrame(), dias) for nome in unicos}
    tmp = df.copy()
    tmp["_ent"] = _chave_texto(tmp[coluna])
    totais = _totais_diarios(tmp, extra_grupo="_ent")
    fatias = {} if totais.empty else {
        chave: fatia.droplevel(0) for chave, fatia in totais.groupby(level=0, sort=False)
    }
    vazio = pd.DataFrame()
    return {nome: _pontos_serie_diaria(fatias.get(nome.casefold(), vazio), dias) for nome in unicos}


def _series_por_nome(
    df: pd.DataFrame,
    coluna: str,
    nomes: pd.Series,
    meses: list[pd.Timestamp],
) -> dict[str, list[dict]]:
    unicos: list[str] = []
    vistos: set[str] = set()
    for nome in nomes:
        rotulo = "—" if pd.isna(nome) or str(nome).strip() == "" else str(nome).strip()
        if rotulo in vistos:
            continue
        vistos.add(rotulo)
        unicos.append(rotulo)
    if not unicos:
        return {}
    if df.empty or coluna not in df.columns:
        return {nome: _pontos_serie(pd.DataFrame(), meses) for nome in unicos}
    tmp = df.copy()
    tmp["_ent"] = _chave_texto(tmp[coluna])
    totais = _totais_mensais(tmp, extra_grupo="_ent")
    fatias = {} if totais.empty else {
        chave: fatia.droplevel(0) for chave, fatia in totais.groupby(level=0, sort=False)
    }
    vazio = pd.DataFrame()
    return {nome: _pontos_serie(fatias.get(nome.casefold(), vazio), meses) for nome in unicos}


def _rollup(
    dump: pd.DataFrame,
    antes: pd.DataFrame,
    depois: pd.DataFrame,
    coluna_dump: str,
    coluna_mov: str,
    series: dict[str, list[dict]],
    series_dia: dict[str, list[dict]],
    mov_pares: pd.DataFrame,
    data_corte: pd.Timestamp | None,
    ultimo_disponivel: pd.Timestamp | None,
    *,
    incluir_nao_precificados: bool = False,
) -> list[dict]:
    zero = _agregar(pd.DataFrame())
    vazia = series.get("", [])
    vazia_dia = series_dia.get("", [])
    ant_por_chave = _agregar_por_chave(antes, coluna_mov)
    dep_por_chave = _agregar_por_chave(depois, coluna_mov)
    janelas_por_chave = [
        (
            nome_janela,
            dias,
            _agregar_por_chave(_fatia_por_dias(mov_pares, data_corte, dias, "antes"), coluna_mov),
            _agregar_por_chave(_fatia_por_dias(mov_pares, data_corte, dias, "depois"), coluna_mov),
            _janela_completa(data_corte, dias, ultimo_disponivel),
        )
        for nome_janela, dias in JANELAS_FIXAS
    ]

    def item(rotulo: str, chave: str, grupo: pd.DataFrame) -> dict:
        alvo = _ponderar(grupo["margem_alvo"], grupo["receita"])
        janelas = {
            nome_janela: _janela_fixa(j_ant.get(chave, zero), j_dep.get(chave, zero), alvo, dias, completa)
            for nome_janela, dias, j_ant, j_dep, completa in janelas_por_chave
        }
        return _item_entidade(
            rotulo, grupo, alvo,
            ant_por_chave.get(chave, zero), dep_por_chave.get(chave, zero),
            series.get(rotulo, vazia), series_dia.get(rotulo, vazia_dia), janelas,
        )

    itens = []
    vistos: set[str] = set()
    for nome, grupo in dump.groupby(coluna_dump, dropna=False):
        chave = str(nome).strip().casefold()
        vistos.add(chave)
        itens.append(item(str(nome).strip() or "—", chave, grupo))
    if incluir_nao_precificados and not mov_pares.empty and coluna_mov in mov_pares.columns:
        dump_vazio = dump.iloc[0:0]
        coluna = mov_pares[coluna_mov]
        rotulos = coluna.groupby(_chave_texto(coluna).values, sort=False).first()
        for chave, valor in rotulos.items():
            if chave in vistos:
                continue
            rotulo = "—" if pd.isna(valor) or not str(valor).strip() else str(valor).strip()
            itens.append(item(rotulo, chave, dump_vazio))
    itens.sort(key=lambda it: (it["lucro_depois"], it["receita_depois"]), reverse=True)
    return itens


def _contar_situacoes(itens: list[dict]) -> dict[str, int]:
    contagem = Counter(item["situacao"] for item in itens)
    return {chave: int(contagem.get(chave, 0)) for chave in SITUACOES}


def _resumo_vazio() -> dict:
    return {
        "receita_dump": 0.0,
        "margem_anterior_dump": None,
        "margem_alvo": None,
        "receita_antes": 0.0,
        "receita_depois": 0.0,
        "lucro_antes": 0.0,
        "lucro_depois": 0.0,
        "qtd_antes": 0.0,
        "qtd_depois": 0.0,
        "margem_antes": None,
        "margem_depois": None,
        "dias_venda_antes": 0,
        "dias_venda_depois": 0,
        "lucro_dia_antes": None,
        "lucro_dia_depois": None,
        "qtd_dia_antes": None,
        "qtd_dia_depois": None,
        "variacao_receita_pct": None,
        "variacao_lucro_pct": None,
        "variacao_qtd_pct": None,
        "gap_alvo_pp": None,
        "situacoes": {chave: 0 for chave in SITUACOES},
        "janelas": {chave: _janela_fixa_vazia(dias) for chave, dias in JANELAS_FIXAS},
    }


def _resposta_vazia() -> dict:
    return {
        "data_precificacao": None,
        "periodo_corte": None,
        "periodo_antes": {"inicio": None, "fim": None},
        "periodo_depois": {"inicio": None, "fim": None},
        "dias": 0,
        "linhas_dump": 0,
        "familias": 0,
        "fabricantes_qtd": 0,
        "pares": 0,
        "skus_com_preco_sugerido": 0,
        "tem_movimento_depois": False,
        "resumo": _resumo_vazio(),
        "serie_mensal": [],
        "serie_diaria": [],
        "produtos": [],
        "fabricantes": [],
    }
