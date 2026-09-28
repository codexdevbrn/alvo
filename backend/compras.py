"""Tela Compras: quanto repor por produto, a partir da venda dos últimos 12 meses
e do estoque atual. Substitui a planilha `5544 - Alvo Inteligência de Compras.xlsm`
(aba BaseUnificada, colunas AM–AQ) e reproduz as fórmulas dela:

- venda e estoque negativos contam como zero;
- **12 meses**: 11 fechados + o corrente (parcial, só para exibir, fora da média);
- **média** = (maior dos 11 fechados + 2 × média dos 3 últimos fechados + último fechado) / 4;
- **estoque alvo** = média × multiplicador (`MULTIPLICADORES`). Mínimo e máximo não
  são faixa: é um ou outro conforme o giro;
- **sugestão** = arred(alvo − estoque, 0), meio pra cima como o Excel — o `round`
  do Python é bancário e daria 22 no lugar de 23 com 22,5. ≤ 0 = "Não recomendado";
- **valor** = sugestão × arred(custo, 2).

Não impulsionado + caixa apertado nunca compra: na planilha a fórmula compara
`AP − AP`, sempre zero. Mantido como regra.

O cálculo é **por loja** e as sugestões somam no produto: sobra na loja A não cobre
falta na B. Com uma loja só, dá idêntico à planilha. Média, alvo e venda mensal do
produto são as somas das lojas — a média não é linear (tem um `max`), então a média
do produto somado daria outro número.

Custo = CMV ÷ QTD dos 3 últimos meses fechados, somando as lojas do escopo ("custo
médio recente"). A fonte não tem o "último custo" da planilha; o CMV médio do
período inteiro defasaria num reajuste. Sem venda nesses 3 meses, fica sem custo:
valor nulo, fora do total, contado em `produtos_sem_custo`.

Duas etapas, e o corte entre elas é o cache: `preparar_base_compras` faz a parte
cara (pivô de 12 meses, estoque e custo por loja × produto) e não depende dos
parâmetros; `calcular_compras` é aritmética em cima dela. Mudar prazo, giro ou
filtro não relê a base.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Optional

import numpy as np
import pandas as pd

from estoque_cobertura import _mes_como_numero

COLUNA_PRODUTO = "CODIGO_INTERNO_PRODUTO"
MESES_JANELA = 12

PRAZOS = ("imediato", "regular", "industria")
GIROS = ("impulsionado", "nao_impulsionado")

# (giro, caixa_apertado) -> (coluna, multiplicador por prazo). `None` = nunca compra.
MULTIPLICADORES: dict[tuple[str, bool], Optional[tuple[str, dict[str, float]]]] = {
    ("impulsionado", False): ("minimo", {"imediato": 0.60, "regular": 1.00, "industria": 1.40}),
    ("impulsionado", True): ("minimo", {"imediato": 0.45, "regular": 0.75, "industria": 1.00}),
    ("nao_impulsionado", False): ("maximo", {"imediato": 0.90, "regular": 1.40, "industria": 2.10}),
    ("nao_impulsionado", True): None,
}


def mes_corrente_indice(corte: date) -> int:
    """Mês corrente = o mês de (corte + 1 dia), em Ano*12 + Mês − 1.

    Do dia 2 ao 31 é o mês de hoje, parcial até ontem. No dia 1º (corte = último
    dia do mês anterior) é o mês novo, ainda vazio — e o que acabou de fechar entra
    inteiro nos 11 fechados. "O mês do corte" tiraria da média um mês completo.
    """
    ref = corte + timedelta(days=1)
    return ref.year * 12 + ref.month - 1


def _rotulo_mes(indice: int) -> str:
    return f"{indice // 12:04d}-{indice % 12 + 1:02d}"


def meio_pra_cima(valor, casas: int = 0):
    """Arredondamento do Excel (meio pra cima) para valores ≥ 0, escalar ou array.

    O `round` do Python e o `np.round` são bancários (22,5 → 22). O arredondamento
    prévio em 6 casas tira o resíduo do ponto flutuante: 54,1666… × 0,6 − 10 sai
    22,4999999…, que precisa virar 22,5 antes de ir para 23.
    """
    fator = 10 ** casas
    return np.floor(np.round(np.asarray(valor, dtype=float) * fator, 6) + 0.5) / fator


def media_ponderada(meses_fechados: np.ndarray) -> np.ndarray:
    """(maior dos 11 fechados + 2 × média dos 3 últimos + último) / 4, por linha."""
    fechados = np.asarray(meses_fechados, dtype=float)
    return (
        fechados.max(axis=1)
        + 2 * fechados[:, -3:].mean(axis=1)
        + fechados[:, -1]
    ) / 4


def validar_parametros(prazo_entrega: str, giro: str) -> tuple[str, str]:
    prazo = (prazo_entrega or "").strip().lower()
    giro_norm = (giro or "").strip().lower()
    if prazo not in PRAZOS:
        raise ValueError(f"prazo_entrega deve ser um de: {', '.join(PRAZOS)}.")
    if giro_norm not in GIROS:
        raise ValueError(f"giro deve ser um de: {', '.join(GIROS)}.")
    return prazo, giro_norm


def _texto_ou_nulo(serie: Optional[pd.Series]) -> Optional[pd.Series]:
    """Texto sem espaço nas pontas; vazio e "nan" viram nulo, para o `first()`
    do groupby pular até o primeiro valor de verdade."""
    if serie is None:
        return None
    texto = serie.astype("string").str.strip()
    return texto.mask(texto.isna() | (texto == "") | (texto.str.lower() == "nan"))


def _base_vazia(corrente: int) -> dict[str, Any]:
    colunas = ["Loja", COLUNA_PRODUTO, "estoque", *range(MESES_JANELA)]
    return {
        "linhas": pd.DataFrame(columns=colunas),
        "produtos": pd.DataFrame(columns=[COLUNA_PRODUTO, "descricao", "fabricante", "referencia", "custo"]),
        "meses": [_rotulo_mes(corrente - MESES_JANELA + 1 + i) for i in range(MESES_JANELA)],
    }


def preparar_base_compras(estoque: pd.DataFrame, vendas: pd.DataFrame, *, corte: date) -> dict[str, Any]:
    """Parte cara, sem parâmetros: 12 meses de QTD e estoque por loja × produto,
    e descrição/fabricante/custo por produto.

    `estoque` e `vendas` no schema de `montar_estoque_e_vendas` (estoque por
    `Loja`, vendas por `Nome_Loja`/`Ano`/`Mês`, com `CMV` quando a base tem).
    Entram só as linhas loja × produto com estoque ou venda na janela — o `_PRODUTO`
    de empresa grande tem milhões de linhas sem nada, que só inflariam o
    "Não recomendado".
    """
    corrente = mes_corrente_indice(corte)
    inicio = corrente - MESES_JANELA + 1
    base = _base_vazia(corrente)

    est = pd.DataFrame({
        "Loja": estoque.get("Loja", pd.Series(dtype=str)).fillna("").astype(str).str.strip(),
        COLUNA_PRODUTO: estoque.get(COLUNA_PRODUTO, pd.Series(dtype=str)).fillna("").astype(str).str.strip(),
        "estoque": pd.to_numeric(estoque.get("Qtd_estoque", 0), errors="coerce"),
    })
    est["estoque"] = est["estoque"].fillna(0.0).clip(lower=0)
    est = est[est[COLUNA_PRODUTO] != ""]
    est = est.groupby(["Loja", COLUNA_PRODUTO], as_index=False)["estoque"].sum()

    pivo = pd.DataFrame(columns=["Loja", COLUNA_PRODUTO, *range(MESES_JANELA)])
    custo = pd.Series(dtype=float, name="custo")
    if vendas is not None and not vendas.empty:
        mes_origem = vendas.get("Mês", pd.Series(index=vendas.index, dtype=object))
        mapa_mes = {valor: _mes_como_numero(valor) for valor in pd.unique(mes_origem)}
        ven = pd.DataFrame({
            "Loja": vendas.get("Nome_Loja", pd.Series(index=vendas.index, dtype=str)).fillna("").astype(str).str.strip(),
            COLUNA_PRODUTO: vendas.get(COLUNA_PRODUTO, pd.Series(index=vendas.index, dtype=str))
            .fillna("").astype(str).str.strip(),
            "Ano": pd.to_numeric(vendas.get("Ano"), errors="coerce"),
            "Mês": mes_origem.map(mapa_mes),
            "QTD": pd.to_numeric(vendas.get("QTD", 0), errors="coerce").fillna(0.0),
            "CMV": pd.to_numeric(vendas["CMV"], errors="coerce").fillna(0.0) if "CMV" in vendas.columns else np.nan,
        })
        ven = ven.dropna(subset=["Ano", "Mês"])
        ven = ven[(ven[COLUNA_PRODUTO] != "") & ven["Mês"].between(1, 12)].copy()
        ven["_off"] = ven["Ano"].astype(int) * 12 + ven["Mês"].astype(int) - 1 - inicio
        ven = ven[ven["_off"].between(0, MESES_JANELA - 1)]
        if not ven.empty:
            mensal = ven.groupby(["Loja", COLUNA_PRODUTO, "_off"], as_index=False)[["QTD", "CMV"]].sum(min_count=1)
            # Negativo (devolução maior que a venda no mês) conta como zero, por loja e mês.
            mensal["QTD"] = mensal["QTD"].clip(lower=0)
            pivo = (
                mensal.pivot_table(index=["Loja", COLUNA_PRODUTO], columns="_off", values="QTD",
                                   aggfunc="sum", fill_value=0.0)
                .reindex(columns=range(MESES_JANELA), fill_value=0.0)
                .reset_index()
            )
            pivo.columns = ["Loja", COLUNA_PRODUTO, *range(MESES_JANELA)]
            # Custo médio recente: CMV ÷ QTD dos 3 últimos fechados, somando as lojas.
            recentes = ven[ven["_off"].between(MESES_JANELA - 4, MESES_JANELA - 2)]
            if "CMV" in vendas.columns and not recentes.empty:
                somas = recentes.groupby(COLUNA_PRODUTO)[["CMV", "QTD"]].sum()
                custo = (somas["CMV"] / somas["QTD"].where(somas["QTD"] > 0)).where(lambda s: s > 0)
                custo = custo.dropna().rename("custo")

    linhas = est.merge(pivo, on=["Loja", COLUNA_PRODUTO], how="outer")
    for i in range(MESES_JANELA):
        linhas[i] = pd.to_numeric(linhas[i], errors="coerce").fillna(0.0)
    linhas["estoque"] = linhas["estoque"].fillna(0.0)
    tem_venda = linhas[list(range(MESES_JANELA))].sum(axis=1) > 0
    linhas = linhas[(linhas["estoque"] > 0) | tem_venda].reset_index(drop=True)
    if linhas.empty:
        return base

    codigos = set(linhas[COLUNA_PRODUTO])
    if estoque is not None and COLUNA_PRODUTO in estoque.columns:
        cadastro = estoque[estoque[COLUNA_PRODUTO].astype(str).str.strip().isin(codigos)]
    else:
        cadastro = pd.DataFrame()
    if cadastro.empty:
        produtos = pd.DataFrame({COLUNA_PRODUTO: sorted(codigos)})
        produtos["descricao"] = ""
        produtos["fabricante"] = "Não informado"
        produtos["referencia"] = ""
    else:
        produtos = pd.DataFrame({
            COLUNA_PRODUTO: cadastro[COLUNA_PRODUTO].astype(str).str.strip(),
            "descricao": _texto_ou_nulo(cadastro.get("descricao")),
            "fabricante": _texto_ou_nulo(cadastro.get("NOME_FABRICANTE")),
            "referencia": _texto_ou_nulo(cadastro.get("CODIGO_REFERENCIA_PRODUTO")),
        }).groupby(COLUNA_PRODUTO, as_index=False).first()
        produtos["descricao"] = produtos["descricao"].fillna("")
        produtos["fabricante"] = produtos["fabricante"].fillna("Não informado")
        produtos["referencia"] = produtos["referencia"].fillna("")
        faltando = sorted(codigos - set(produtos[COLUNA_PRODUTO]))
        if faltando:
            produtos = pd.concat([produtos, pd.DataFrame({
                COLUNA_PRODUTO: faltando, "descricao": "", "fabricante": "Não informado", "referencia": "",
            })], ignore_index=True)
    produtos = produtos.merge(custo, left_on=COLUNA_PRODUTO, right_index=True, how="left")

    base["linhas"] = linhas
    base["produtos"] = produtos
    return base


TABELAS_BASE = ("linhas", "produtos")
#: Entra na chave do cache da base (RAM e disco). Mudou `preparar_base_compras`,
#: suba o número: a base gravada pelo lote com a regra velha deixa de ser lida.
VERSAO_BASE = 1


def base_para_disco(base: dict[str, Any]) -> tuple[dict[str, pd.DataFrame], dict[str, Any]]:
    """Base preparada → (tabelas, extra) para `cache_telas.gravar_tabelas`."""
    return {nome: base[nome] for nome in TABELAS_BASE}, {"meses": list(base["meses"])}


def base_do_disco(tabelas: dict[str, pd.DataFrame], extra: dict[str, Any]) -> dict[str, Any]:
    """Inverso de `base_para_disco`: os 12 meses voltam a ser as colunas 0…11."""
    linhas = tabelas["linhas"].rename(columns={str(i): i for i in range(MESES_JANELA)})
    return {"linhas": linhas, "produtos": tabelas["produtos"], "meses": list(extra.get("meses") or [])}


def _numero(valor, casas: int = 4) -> Optional[float]:
    if valor is None or pd.isna(valor):
        return None
    return round(float(valor), casas)


# ---------------------------------------------------------------------------
# Exceções de prazo e giro (`compras_parametros.json` na pasta de trabalho da
# empresa, valendo para todas as lojas). Vale SKU > produto > tela, campo a
# campo; caixa apertado é sempre o da tela. Produto = descrição × fabricante.
# ---------------------------------------------------------------------------

NOME_ARQUIVO_PARAMETROS = "compras_parametros.json"
FORMATO_PARAMETROS = 1
CAMPOS_EXCECAO = ("prazo", "giro")


def _campos_excecao(bruto: Any) -> dict[str, str]:
    """Só os campos válidos; o resto é descartado em silêncio (arquivo editado à mão)."""
    if not isinstance(bruto, dict):
        return {}
    saida: dict[str, str] = {}
    prazo = str(bruto.get("prazo") or "").strip().lower()
    giro = str(bruto.get("giro") or "").strip().lower()
    if prazo in PRAZOS:
        saida["prazo"] = prazo
    if giro in GIROS:
        saida["giro"] = giro
    return saida


def normalizar_excecoes(bruto: Any) -> dict[str, dict]:
    """Arquivo → `{"produtos": {(descricao, fabricante): campos}, "skus": {codigo: campos}}`."""
    produtos: dict[tuple[str, str], dict[str, str]] = {}
    skus: dict[str, dict[str, str]] = {}
    if isinstance(bruto, dict):
        for item in bruto.get("produtos") or []:
            if not isinstance(item, dict):
                continue
            campos = _campos_excecao(item)
            chave = (str(item.get("descricao") or "").strip(), str(item.get("fabricante") or "").strip())
            if campos and (chave[0] or chave[1]):
                produtos[chave] = campos
        brutos_sku = bruto.get("skus")
        if isinstance(brutos_sku, dict):
            for codigo, item in brutos_sku.items():
                campos = _campos_excecao(item)
                if campos and str(codigo).strip():
                    skus[str(codigo).strip()] = campos
    return {"produtos": produtos, "skus": skus}


def excecoes_para_arquivo(excecoes: dict[str, dict]) -> dict[str, Any]:
    produtos = [
        {"descricao": d, "fabricante": f, **campos}
        for (d, f), campos in sorted(excecoes["produtos"].items())
    ]
    return {
        "_formato": FORMATO_PARAMETROS,
        "produtos": produtos,
        "skus": {codigo: excecoes["skus"][codigo] for codigo in sorted(excecoes["skus"])},
    }


def definir_excecao(
    excecoes: dict[str, dict],
    *,
    nivel: str,
    prazo: Optional[str],
    giro: Optional[str],
    descricao: str = "",
    fabricante: str = "",
    codigo: str = "",
) -> dict[str, dict]:
    """Grava o estado inteiro de um nível (`None` = herda). Sem campo, a entrada sai."""
    campos = {}
    if prazo is not None:
        if prazo not in PRAZOS:
            raise ValueError(f"prazo deve ser um de: {', '.join(PRAZOS)}.")
        campos["prazo"] = prazo
    if giro is not None:
        if giro not in GIROS:
            raise ValueError(f"giro deve ser um de: {', '.join(GIROS)}.")
        campos["giro"] = giro
    novo = {"produtos": dict(excecoes["produtos"]), "skus": dict(excecoes["skus"])}
    if nivel == "produto":
        chave = (descricao.strip(), fabricante.strip())
        if not (chave[0] or chave[1]):
            raise ValueError("Produto sem descrição e fabricante.")
        destino, chave_final = novo["produtos"], chave
    elif nivel == "sku":
        if not codigo.strip():
            raise ValueError("SKU sem código.")
        destino, chave_final = novo["skus"], codigo.strip()
    else:
        raise ValueError("nivel deve ser 'produto' ou 'sku'.")
    if campos:
        destino[chave_final] = campos
    else:
        destino.pop(chave_final, None)
    return novo


def limpar_excecoes_produto(
    excecoes: dict[str, dict], *, descricao: str, fabricante: str, codigos: list[str],
) -> dict[str, dict]:
    """Tira a exceção do produto e a de cada SKU dele."""
    fora = {str(c).strip() for c in codigos}
    return {
        "produtos": {k: v for k, v in excecoes["produtos"].items() if k != (descricao.strip(), fabricante.strip())},
        "skus": {k: v for k, v in excecoes["skus"].items() if k not in fora},
    }


def _regra_linha(giro: str, prazo: str, caixa_apertado: bool) -> tuple[Optional[str], float]:
    """(coluna, fator) de um par giro × prazo; coluna `None` = nunca compra."""
    regra = MULTIPLICADORES[(giro, caixa_apertado)]
    if regra is None:
        return None, float("nan")
    coluna, fatores = regra
    return coluna, fatores[prazo]


def calcular_compras(
    base: dict[str, Any],
    *,
    prazo_entrega: str = "imediato",
    giro: str = "impulsionado",
    caixa_apertado: bool = False,
    fabricante: Optional[str] = None,
    busca: Optional[str] = None,
    somente_recomendados: bool = True,
    limite: int = 1000,
    excecoes: Optional[dict[str, dict]] = None,
    produto: Optional[tuple[str, str]] = None,
) -> dict[str, Any]:
    """Sugestão por SKU (somando as lojas) sobre a base preparada, agrupada em
    produto = descrição × fabricante. `itens` são os produtos, cada um com os
    seus SKUs em `skus`; `limite` corta produtos.

    KPIs são de SKU (`itens_a_comprar`, `nao_recomendados`, `produtos_sem_custo`),
    mais `produtos_a_comprar`, e saem de todos os que passam nos filtros de texto, antes do
    `limite` — o corte da lista não muda o total. `nao_recomendados` é contado
    antes do `somente_recomendados`. `produtos_sem_custo` conta só quem tem
    sugestão: item sem custo que não seria comprado não pesa no pedido.

    `excecoes` (de `normalizar_excecoes`) troca prazo e giro por SKU ou produto;
    `produto` restringe a um par descrição × fabricante (o modal pede todos os
    SKUs dele, com `somente_recomendados=False`).
    """
    prazo, giro_norm = validar_parametros(prazo_entrega, giro)
    parametros = {"prazo_entrega": prazo, "giro": giro_norm, "caixa_apertado": bool(caixa_apertado)}

    linhas: pd.DataFrame = base["linhas"]
    produtos: pd.DataFrame = base["produtos"]
    resposta: dict[str, Any] = {
        "itens": [],
        "total_compra": 0.0,
        "itens_a_comprar": 0,
        "produtos_a_comprar": 0,
        "produtos_sem_custo": 0,
        "nao_recomendados": 0,
        "itens_total": 0,
        "itens_exibidos": 0,
        "limitado": False,
        "fabricantes": sorted({str(f) for f in produtos.get("fabricante", []) if str(f)}),
        "meses": list(base["meses"]),
        "parametros_aplicados": parametros,
    }
    if linhas.empty:
        return resposta

    excecoes = excecoes or {"produtos": {}, "skus": {}}
    caixa = bool(caixa_apertado)
    cadastro = produtos.drop_duplicates(COLUNA_PRODUTO).set_index(COLUNA_PRODUTO)
    codigos = linhas[COLUNA_PRODUTO]
    desc_linha = codigos.map(cadastro["descricao"]).fillna("").astype(str)
    fab_linha = codigos.map(cadastro["fabricante"]).fillna("Não informado").astype(str)

    # Parâmetro efetivo por linha, campo a campo: SKU > produto > tela.
    chave_linha = desc_linha + "\0" + fab_linha
    efetivo: dict[str, pd.Series] = {}
    for campo, global_ in (("prazo", prazo), ("giro", giro_norm)):
        do_produto = {f"{d}\0{f}": c[campo] for (d, f), c in excecoes["produtos"].items() if campo in c}
        do_sku = {k: c[campo] for k, c in excecoes["skus"].items() if campo in c}
        serie = pd.Series(global_, index=linhas.index, dtype=object)
        if do_produto:
            serie = chave_linha.map(do_produto).fillna(serie)
        if do_sku:
            serie = codigos.astype(str).map(do_sku).fillna(serie)
        efetivo[campo] = serie

    regras = {
        (g, p): _regra_linha(g, p, caixa) for g in GIROS for p in PRAZOS
    }
    par = list(zip(efetivo["giro"], efetivo["prazo"]))
    fator = np.array([regras[k][1] for k in par], dtype=float)
    coluna_linha = np.array([regras[k][0] for k in par], dtype=object)

    meses = linhas[list(range(MESES_JANELA))].to_numpy(dtype=float)
    estoque = linhas["estoque"].to_numpy(dtype=float)
    media = media_ponderada(meses[:, :MESES_JANELA - 1])
    alvo = media * fator  # NaN onde nunca compra
    falta = np.nan_to_num(alvo - estoque, nan=0.0)
    sugestao = np.where(falta > 0, meio_pra_cima(np.clip(falta, 0, None)), 0.0)

    calc = pd.DataFrame({
        "loja": linhas["Loja"].to_numpy(),
        COLUNA_PRODUTO: codigos.to_numpy(),
        "estoque": estoque,
        "media": media,
        "alvo": alvo,
        "sugestao": sugestao,
        "coluna": coluna_linha,
        "prazo": efetivo["prazo"].to_numpy(),
        "giro": efetivo["giro"].to_numpy(),
    })
    calc[[f"m{i}" for i in range(MESES_JANELA)]] = meses
    grupos_sku = calc.groupby(COLUNA_PRODUTO)
    agregado = grupos_sku.agg(
        estoque=("estoque", "sum"),
        media=("media", "sum"),
        sugestao=("sugestao", "sum"),
        coluna=("coluna", "first"),
        prazo=("prazo", "first"),
        giro=("giro", "first"),
        **{f"m{i}": (f"m{i}", "sum") for i in range(MESES_JANELA)},
    )
    # min_count=1: SKU que nunca compra em nenhuma loja fica sem alvo, não com 0.
    agregado["alvo"] = grupos_sku["alvo"].sum(min_count=1)
    agregado = agregado.reset_index().merge(produtos, on=COLUNA_PRODUTO, how="left")
    agregado["fabricante"] = agregado["fabricante"].fillna("Não informado")
    agregado["descricao"] = agregado["descricao"].fillna("")
    agregado["referencia"] = agregado["referencia"].fillna("")

    if produto is not None:
        agregado = agregado[(agregado["descricao"] == produto[0]) & (agregado["fabricante"] == produto[1])]

    if fabricante and fabricante.strip():
        alvo_fab = fabricante.strip().casefold()
        agregado = agregado[agregado["fabricante"].astype(str).str.strip().str.casefold() == alvo_fab]
    if busca and busca.strip():
        termo = busca.strip().casefold()
        texto = (
            agregado[COLUNA_PRODUTO].astype(str) + " " + agregado["descricao"].astype(str)
            + " " + agregado["referencia"].astype(str)
        ).str.casefold()
        agregado = agregado[texto.str.contains(termo, regex=False)]

    recomendado = agregado["sugestao"] > 0
    custo_arred = pd.Series(meio_pra_cima(agregado["custo"].to_numpy(dtype=float), 2), index=agregado.index)
    agregado = agregado.assign(
        custo=custo_arred.where(agregado["custo"].notna()),
        sugestao=agregado["sugestao"].where(recomendado),
    )
    agregado["valor"] = (agregado["sugestao"] * agregado["custo"]).round(2)

    resposta["itens_a_comprar"] = int(recomendado.sum())
    resposta["nao_recomendados"] = int((~recomendado).sum())
    resposta["produtos_sem_custo"] = int((recomendado & agregado["custo"].isna()).sum())
    resposta["total_compra"] = round(float(agregado["valor"].sum()), 2)

    if somente_recomendados:
        agregado = agregado[recomendado]
    resposta["produtos_a_comprar"] = int(
        agregado.loc[agregado["sugestao"] > 0, ["descricao", "fabricante"]].drop_duplicates().shape[0]
    )

    # Produto = descrição × fabricante (o grão da tela A precificar); os SKUs
    # abrem embaixo dele. A conta continua por SKU e loja: o produto só soma.
    meses_cols = [f"m{i}" for i in range(MESES_JANELA)]
    produtos_df = agregado.groupby(["descricao", "fabricante"], as_index=False).agg(
        estoque=("estoque", "sum"),
        media=("media", "sum"),
        sugestao=("sugestao", "sum"),
        valor=("valor", "sum"),
        skus=(COLUNA_PRODUTO, "size"),
        **{c: (c, "sum") for c in meses_cols},
    )
    grupos_produto = agregado.groupby(["descricao", "fabricante"])
    produtos_df = produtos_df.join(
        grupos_produto["alvo"].sum(min_count=1).rename("alvo"), on=["descricao", "fabricante"],
    )
    com_valor = grupos_produto["valor"].count().rename("_com_valor")
    sem_custo = (
        agregado[agregado["sugestao"].notna() & agregado["custo"].isna()]
        .groupby(["descricao", "fabricante"]).size().rename("sem_custo")
    )
    produtos_df = (
        produtos_df.join(com_valor, on=["descricao", "fabricante"])
        .join(sem_custo, on=["descricao", "fabricante"])
    )
    produtos_df["sem_custo"] = produtos_df["sem_custo"].fillna(0).astype(int)
    produtos_df["valor"] = produtos_df["valor"].where(produtos_df["_com_valor"] > 0)
    produtos_df["sugestao"] = produtos_df["sugestao"].where(produtos_df["sugestao"] > 0)
    produtos_df = produtos_df.sort_values(
        ["valor", "sugestao", "descricao", "fabricante"],
        ascending=[False, False, True, True], na_position="last",
    )
    total = len(produtos_df)
    topo = produtos_df.head(limite)

    chaves_topo = set(zip(topo["descricao"], topo["fabricante"]))
    skus_topo = agregado[
        pd.Series(list(zip(agregado["descricao"], agregado["fabricante"])), index=agregado.index).isin(chaves_topo)
    ].sort_values(["valor", "sugestao", COLUNA_PRODUTO], ascending=[False, False, True], na_position="last")

    por_loja = calc[calc[COLUNA_PRODUTO].isin(set(skus_topo[COLUNA_PRODUTO]))].sort_values(["loja"])
    lojas_sku: dict[str, list[dict[str, Any]]] = {}
    for linha in por_loja.itertuples(index=False):
        lojas_sku.setdefault(getattr(linha, COLUNA_PRODUTO), []).append({
            "loja": linha.loja,
            "estoque": _numero(linha.estoque),
            "sugestao": int(linha.sugestao) if linha.sugestao > 0 else None,
        })

    skus_produto: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for linha in skus_topo.to_dict("records"):
        codigo = linha[COLUNA_PRODUTO]
        skus_produto.setdefault((linha["descricao"], linha["fabricante"]), []).append({
            "codigo": codigo,
            "referencia": linha["referencia"] or None,
            "descricao": linha["descricao"],
            "fabricante": linha["fabricante"],
            "venda_mensal": [_numero(linha[c]) for c in meses_cols],
            "media": _numero(linha["media"]),
            "estoque": _numero(linha["estoque"]),
            "estoque_alvo": _numero(linha["alvo"]),
            "coluna": linha["coluna"] if isinstance(linha["coluna"], str) else None,
            "prazo": linha["prazo"],
            "giro": linha["giro"],
            "excecao": excecoes["skus"].get(str(codigo)),
            "sugestao": _inteiro(linha["sugestao"]),
            "custo": _numero(linha["custo"], 2),
            "valor": _numero(linha["valor"], 2),
            "lojas": lojas_sku.get(codigo, []),
        })

    itens = []
    for linha in topo.to_dict("records"):
        chave = (linha["descricao"], linha["fabricante"])
        skus = skus_produto.get(chave, [])
        propria = excecoes["produtos"].get(chave)
        prazo_prod = (propria or {}).get("prazo", prazo)
        giro_prod = (propria or {}).get("giro", giro_norm)
        itens.append({
            "descricao": linha["descricao"],
            "fabricante": linha["fabricante"],
            "venda_mensal": [_numero(linha[c]) for c in meses_cols],
            "media": _numero(linha["media"]),
            "estoque": _numero(linha["estoque"]),
            "estoque_alvo": _numero(linha["alvo"]),
            # Coluna do produto inteiro; SKU com exceção própria traz a dele.
            "coluna": regras[(giro_prod, prazo_prod)][0],
            "prazo": prazo_prod,
            "giro": giro_prod,
            "excecao": propria,
            "skus_com_excecao": sum(1 for sku in skus if sku["excecao"]),
            "sugestao": _inteiro(linha["sugestao"]),
            "valor": _numero(linha["valor"], 2),
            "skus_sem_custo": int(linha["sem_custo"]),
            "lojas": _somar_lojas(skus),
            "skus": skus,
        })

    resposta.update({
        "itens": itens,
        "itens_total": total,
        "itens_exibidos": len(itens),
        "limitado": total > len(itens),
    })
    return resposta


def _inteiro(valor) -> Optional[int]:
    return None if valor is None or pd.isna(valor) else int(valor)


def _somar_lojas(skus: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Estoque e sugestão do produto por loja, somando os SKUs."""
    por_loja: dict[str, dict[str, Any]] = {}
    for sku in skus:
        for loja in sku["lojas"]:
            atual = por_loja.setdefault(loja["loja"], {"loja": loja["loja"], "estoque": 0.0, "sugestao": None})
            atual["estoque"] = round(atual["estoque"] + (loja["estoque"] or 0), 4)
            if loja["sugestao"]:
                atual["sugestao"] = (atual["sugestao"] or 0) + loja["sugestao"]
    return [por_loja[nome] for nome in sorted(por_loja)]
