"""Leitura do banco de margem por transação (sistema PRICE, mantido fora do
Prisma) — um parquet por CNPJ em `caminhos_padrao.margem_price()`, cada linha
uma venda: `data, cnpj, codigo_produto, fabricante, descricao, segmento, cmv,
receita, quantidade`.

Fórmula de margem validada manualmente contra a tela de referência do PRICE
(Lubrificante, IBAD, mar-set/26 — bateu exato abr-set): soma `receita` e `cmv`
de TODAS as lojas da empresa primeiro, `margem = (receita-cmv)/receita` só
depois. Nunca a média das margens por loja nem por código isolado — as duas
divergem do valor real por não ponderar pelo volume de cada loja/código.

Empresa -> CNPJs vem da base oficial `<trabalho>/base_empresas.parquet`
(`base_empresas`, montada do `_EMPRESA.dw_2d` do DW, loja a loja), com o
`precificacao_cnpj.json` de reserva para empresa que o DW não cobre — a mesma
ordem do lote de precificação. Uma pasta pode ter várias lojas (matriz e
filiais, às vezes com raiz de CNPJ diferente): o mapa antigo trazia só a matriz
de várias empresas, e a margem somava uma loja só. Com a base, 15 empresas
passaram a somar todas as lojas e 8 ganharam margem (set/2026).

Serve hoje a Pós-Precificação (`para_movimento_precificacao` renomeia as
colunas pro formato que `precificacao.montar_pos_precificacao` já espera, sem
tocar a lógica de janelas) e a margem geral do Dashboard (`margem_mensal`).
Pensado também para a futura Pré-Precificação: `carregar_bruto` devolve o grão
original por código e por dia, que uma tela de simulação de preço vai
precisar sem o dump de pares família×fabricante que a Pós-Precificação exige.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

import base_empresas

NOME_MAPA_CNPJ = "precificacao_cnpj.json"


class ErroMargemPrice(RuntimeError):
    """Mapa ausente, parquet ilegível, ou nenhuma loja da empresa com dado."""


def _normalizar_cnpjs(cnpjs) -> list[str]:
    vistos: dict[str, None] = {}
    for bruto in cnpjs:
        digitos = "".join(c for c in str(bruto) if c.isdigit())
        if digitos:
            vistos.setdefault(digitos, None)
    return list(vistos)


def carregar_mapa_cnpj(trabalho: Path) -> dict[str, list[str]]:
    """Lê o `precificacao_cnpj.json` gravado por `precificacao_do_postgres.py`.

    Arquivo ausente ou ilegível devolve mapa vazio (não levanta) — o chamador
    trata isso como "empresa sem cobertura ainda" e cai no fallback de base
    atual, em vez da tela quebrar por um arquivo opcional.
    """
    caminho = Path(trabalho) / NOME_MAPA_CNPJ
    if not caminho.is_file():
        return {}
    try:
        bruto = json.loads(caminho.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(bruto, dict):
        return {}
    mapa: dict[str, list[str]] = {}
    for empresa, valor in bruto.items():
        lista = [valor] if isinstance(valor, str) else list(valor or [])
        cnpjs = _normalizar_cnpjs(lista)
        if cnpjs:
            mapa[str(empresa)] = cnpjs
    return mapa


def resolver_cnpjs(empresa: str, trabalho: Path) -> list[str]:
    """CNPJs das lojas da empresa: base oficial do DW primeiro, mapa manual depois."""
    try:
        base = base_empresas.cnpjs_por_empresa(base_empresas.carregar_base(trabalho))
    except Exception:  # noqa: BLE001 — base ilegível não pode derrubar a tela
        base = {}
    return base.get(empresa) or carregar_mapa_cnpj(trabalho).get(empresa, [])


def _caminho_parquet(pasta_margem: Path, cnpj: str) -> Path:
    return Path(pasta_margem) / f"margem_{cnpj}.parquet"


def assinatura(empresa: str, trabalho: Path, pasta_margem: Path) -> tuple | None:
    """(cnpj, mtime, tamanho) por loja com parquet — para cache por mtime.

    `None` quando a empresa não tem mapa ou nenhum parquet existe: sinal para
    o chamador cair no fallback (base atual) em vez de expor erro na tela.
    """
    cnpjs = resolver_cnpjs(empresa, trabalho)
    if not cnpjs:
        return None
    pasta = Path(pasta_margem)
    partes = []
    for cnpj in cnpjs:
        try:
            st = _caminho_parquet(pasta, cnpj).stat()
        except OSError:
            continue
        partes.append((cnpj, st.st_mtime_ns, st.st_size))
    return tuple(partes) if partes else None


def carregar_bruto(empresa: str, trabalho: Path, pasta_margem: Path) -> pd.DataFrame:
    """Todas as transações de todas as lojas da empresa, schema original do parquet.

    Ponto de entrada genérico — quem precisa do grão por código (ex.: futura
    Pré-Precificação) parte daqui; quem precisa do formato de `precificacao.py`
    usa `para_movimento_precificacao` logo abaixo.
    """
    cnpjs = resolver_cnpjs(empresa, trabalho)
    if not cnpjs:
        raise ErroMargemPrice(f"Empresa '{empresa}' sem CNPJ na base de empresas nem em {NOME_MAPA_CNPJ}.")
    pasta = Path(pasta_margem)
    partes = []
    for cnpj in cnpjs:
        caminho = _caminho_parquet(pasta, cnpj)
        if not caminho.is_file():
            continue
        partes.append(pd.read_parquet(caminho))
    if not partes:
        raise ErroMargemPrice(f"Nenhum parquet encontrado para '{empresa}' em {pasta}.")
    df = pd.concat(partes, ignore_index=True)
    df["data"] = pd.to_datetime(df["data"], errors="coerce")
    return df


def para_movimento_precificacao(bruto: pd.DataFrame) -> pd.DataFrame:
    """Renomeia para o contrato que `precificacao.montar_pos_precificacao` já lê.

    Sem isso a Pós-Precificação teria que aprender uma segunda fonte de
    movimento; renomear aqui deixa toda a lógica de janelas antes/depois,
    `_agregar` e o rollup por produto/fabricante intocados.

    Linha sem `segmento` (o balde "NÃO HARMONIZADO") fica fora, como na tela
    do PRICE: com ela o total da loja ficava ~1,5% acima em lucro/dia e
    qtd/dia; sem ela bate no centavo (IBAD, abr-set/26).
    """
    if "segmento" in bruto.columns:
        bruto = bruto.loc[bruto["segmento"].notna()]
    return bruto.rename(columns={
        "fabricante": "NOME_FABRICANTE",
        "receita": "Receita",
        "cmv": "CMV",
        "quantidade": "QTD",
        "data": "Data_Venda_Diaria",
    })


_MESES_PT = ("jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez")


def _rotulo_mes(periodo: pd.Period) -> str:
    return f"{_MESES_PT[periodo.month - 1]}/{periodo.year % 100:02d}"


def margem_mensal(bruto: pd.DataFrame, descricao: str | None = None) -> list[dict]:
    """Série mensal ponderada — soma receita/cmv de todas as linhas do mês antes
    de dividir, nunca a média das margens já calculadas por loja ou código.

    `descricao=None` agrega a empresa inteira (margem geral do Dashboard);
    passar uma descrição isola 1 produto (mesmo cálculo que valida a tela do
    PRICE, útil também para a futura Pré-Precificação).
    """
    df = bruto if descricao is None else bruto.loc[bruto["descricao"] == descricao]
    if df.empty:
        return []
    pontos = []
    for periodo, grupo in df.assign(_mes=df["data"].dt.to_period("M")).groupby("_mes"):
        receita = float(grupo["receita"].sum())
        cmv = float(grupo["cmv"].sum())
        qtd = float(grupo["quantidade"].sum())
        lucro = receita - cmv
        dias_venda = int(grupo.loc[grupo["receita"] != 0, "data"].dt.normalize().nunique())
        pontos.append({
            "periodo": str(periodo),
            "rotulo": _rotulo_mes(periodo),
            "receita": round(receita, 2),
            "cmv": round(cmv, 2),
            "lucro": round(lucro, 2),
            "margem": round(lucro / receita * 100, 4) if receita > 0 else None,
            "qtd": qtd,
            "dias_venda": dias_venda,
            "lucro_dia": round(lucro / dias_venda, 2) if dias_venda else None,
            "qtd_dia": round(qtd / dias_venda, 2) if dias_venda else None,
        })
    return pontos


def margem_geral(bruto: pd.DataFrame) -> dict | None:
    """Margem ponderada do recorte inteiro (sem quebra mensal) — usada como o
    número único de "margem média da empresa" no Dashboard.
    """
    if bruto.empty:
        return None
    receita = float(bruto["receita"].sum())
    cmv = float(bruto["cmv"].sum())
    if receita <= 0:
        return None
    return {
        "receita": round(receita, 2),
        "cmv": round(cmv, 2),
        "lucro": round(receita - cmv, 2),
        "margem": round((receita - cmv) / receita * 100, 4),
    }
