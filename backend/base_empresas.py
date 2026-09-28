"""
Base empresa / loja / CNPJ, montada a partir do `{empresa}_EMPRESA.dw_2d` do DW.

Por que existe: a precificação (Postgres do PRICE) e a margem por transação
(`DB/PRICE/margem_price`) são indexadas por CNPJ, e o Prisma por pasta de
empresa e `ID_LOJA`. Até aqui a ponte era o `precificacao_cnpj.json`,
preenchido à mão ou inferido pelo código de produto
(`sugerir_cnpj_precificacao.py`). O DW já tem essa ligação, oficial, loja a
loja: `DB/DW/{empresa}/BI/{empresa}_EMPRESA.dw_2d`, CSV `;` com
`ID_LOJA;CNPJ;NOME;CEP;TIPO_TRIBUTACAO;...`. A inferência por código conferiu
com ela em todas as 28 empresas em que as duas existiam.

O nome da pasta no DW é o mesmo da pasta da empresa na fonte (`Peca.com`,
`alianca_itaborai`), e o `ID_LOJA` é o mesmo do movimento (`ibad_dc`) — então a
base casa com o resto do Prisma sem tabela de tradução.

Gravada em `{trabalho}/base_empresas.parquet`, uma linha por loja. O DW é
somente leitura; a escrita vai só para a pasta de trabalho.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Iterable

import pandas as pd

NOME_BASE = "base_empresas.parquet"

#: Colunas do arquivo do DW que a base guarda, e o nome que elas ganham.
COLUNAS = {
    "ID_LOJA": "id_loja",
    "CNPJ": "cnpj",
    "NOME": "nome",
    "CEP": "cep",
    "TIPO_TRIBUTACAO": "tipo_tributacao",
    "DATA_ATT": "data_att",
}

COLUNAS_BASE = ["empresa", *COLUNAS.values()]


class ErroBaseEmpresas(RuntimeError):
    """Arquivo do DW ausente ou fora do formato esperado."""


def caminho_arquivo_empresa(dw: Path, empresa: str) -> Path:
    return Path(dw) / empresa / "BI" / f"{empresa}_EMPRESA.dw_2d"


def so_digitos(valor) -> str:
    return re.sub(r"\D", "", "" if valor is None or pd.isna(valor) else str(valor))


def ler_arquivo_empresa(caminho: Path, empresa: str) -> pd.DataFrame:
    """Lojas de uma empresa. CNPJ sai só com dígitos; loja sem CNPJ fica com ""."""
    caminho = Path(caminho)
    if not caminho.is_file():
        raise ErroBaseEmpresas(f"{caminho.name} não encontrado em {caminho.parent}")
    df = None
    for encoding in ("utf-8-sig", "latin1"):
        try:
            df = pd.read_csv(caminho, sep=";", quotechar='"', dtype=str, encoding=encoding)
            break
        except UnicodeDecodeError:
            continue
    if df is None:
        raise ErroBaseEmpresas(f"{caminho.name}: encoding não reconhecido")
    # Só ID_LOJA é obrigatório: a Cativo exporta as lojas sem coluna de CNPJ, e
    # ela entra na base assim mesmo (CNPJ vazio vira aviso em `montar_base`).
    if "ID_LOJA" not in df.columns:
        raise ErroBaseEmpresas(f"{caminho.name} sem coluna ID_LOJA")

    saida = pd.DataFrame(index=df.index)
    for origem, destino in COLUNAS.items():
        valores = df[origem] if origem in df.columns else pd.Series("", index=df.index)
        saida[destino] = valores.fillna("").astype(str).str.strip()
    saida["empresa"] = empresa
    saida["cnpj"] = saida["cnpj"].map(so_digitos)
    # Linha sem loja é resto de exportação (a Cativo manda uma em branco).
    saida = saida[saida["id_loja"] != ""]
    return saida[COLUNAS_BASE].reset_index(drop=True)


def montar_base(dw: Path, empresas: Iterable[str]) -> tuple[pd.DataFrame, list[str]]:
    """(base, avisos). Empresa sem arquivo vira aviso, não erro: as outras seguem."""
    partes, avisos = [], []
    for empresa in empresas:
        try:
            partes.append(ler_arquivo_empresa(caminho_arquivo_empresa(dw, empresa), empresa))
        except (ErroBaseEmpresas, OSError) as exc:
            avisos.append(f"{empresa}: {exc}")
    base = pd.concat(partes, ignore_index=True) if partes else pd.DataFrame(columns=COLUNAS_BASE)
    for linha in base[base["cnpj"] == ""].itertuples():
        avisos.append(f"{linha.empresa}: loja {linha.id_loja!r} sem CNPJ no DW")
    return base, avisos


def atualizar_base(
    atual: pd.DataFrame, dw: Path, empresas: Iterable[str],
) -> tuple[pd.DataFrame, list[str], list[str], list[str]]:
    """Mantém o mapa salvo e só busca no DW quem entrou na fonte.

    Devolve (base, novas, removidas, avisos). O universo é a pasta fonte (Dados
    Alvos): empresa nova ganha a leitura do `_EMPRESA.dw_2d`; empresa que saiu
    da fonte sai do mapa; as demais ficam como estavam, sem reler o DW. Empresa
    nova sem arquivo no DW não entra — e por isso é tentada de novo na próxima
    execução, até o arquivo aparecer.
    """
    empresas = list(empresas)
    ja_mapeadas = set(atual["empresa"]) if not atual.empty else set()
    novas_pedidas = [e for e in empresas if e not in ja_mapeadas]
    removidas = sorted(ja_mapeadas - set(empresas), key=str.casefold)

    mantidas = atual[atual["empresa"].isin(empresas)] if not atual.empty else atual
    lidas, avisos = montar_base(dw, novas_pedidas)
    novas = sorted(set(lidas["empresa"]), key=str.casefold)
    partes = [p for p in (mantidas, lidas) if not p.empty]
    base = pd.concat(partes, ignore_index=True) if partes else pd.DataFrame(columns=COLUNAS_BASE)
    base = base.sort_values(["empresa", "id_loja"], key=lambda s: s.str.casefold()).reset_index(drop=True)
    return base[COLUNAS_BASE], novas, removidas, avisos


NOME_COMPLEMENTO = "base_empresas_complemento.json"


def carregar_complemento(trabalho: Path | None) -> dict[str, dict[str, tuple[str, bool]]]:
    """`{trabalho}/base_empresas_complemento.json`: empresa → {loja: CNPJ ou
    {"cnpj": ..., "forcar": true}}.

    Para empresa cujo `_EMPRESA.dw_2d` vem sem CNPJ (a Cativo exporta só as
    lojas) — CNPJ como texto simples, o caso comum. `forcar: true` é para
    quando o DW *tem* CNPJ mas ele está errado (ex.: Viannax — a Estética
    Automotiva está com um CNPJ no `_EMPRESA.dw_2d` e outro no parquet do
    PRICE, e corrigir o DW não é opção): o valor vira dict em vez de string.
    Ausente = vazio.
    """
    if trabalho is None:
        return {}
    caminho = Path(trabalho) / NOME_COMPLEMENTO
    if not caminho.is_file():
        return {}
    import json

    def _entrada(valor) -> tuple[str, bool]:
        if isinstance(valor, dict):
            return so_digitos(valor.get("cnpj")), bool(valor.get("forcar"))
        return so_digitos(valor), False

    bruto = json.loads(caminho.read_text(encoding="utf-8"))
    return {
        str(empresa): {str(loja).strip(): _entrada(valor) for loja, valor in (lojas or {}).items()}
        for empresa, lojas in bruto.items()
    }


def aplicar_complemento(
    base: pd.DataFrame, complemento: dict[str, dict[str, tuple[str, bool]]], empresas: Iterable[str],
) -> tuple[pd.DataFrame, list[str]]:
    """Preenche CNPJ de loja que o DW trouxe vazio e acrescenta loja que o DW não
    lista (só de empresa que está na fonte). CNPJ que o DW já trouxe só é
    sobrescrito com `forcar: true` — sem isso o DW continua sendo a fonte
    oficial. Devolve (base, mudanças)."""
    empresas = set(empresas)
    base = base.copy()
    mudancas: list[str] = []
    for empresa, lojas in complemento.items():
        if empresa not in empresas:
            continue
        for loja, entrada in lojas.items():
            loja, (cnpj, forcar) = str(loja).strip(), entrada
            if not cnpj:
                continue
            achou = (base["empresa"] == empresa) & (base["id_loja"].str.casefold() == loja.casefold())
            if not achou.any():
                linha = {c: "" for c in COLUNAS_BASE} | {"empresa": empresa, "id_loja": loja, "cnpj": cnpj}
                base = pd.concat([base, pd.DataFrame([linha])], ignore_index=True)
                mudancas.append(f"{empresa}/{loja}: loja acrescentada, CNPJ {cnpj}")
                continue
            vazio = achou & (base["cnpj"].fillna("") == "")
            if vazio.any():
                base.loc[vazio, "cnpj"] = cnpj
                mudancas.append(f"{empresa}/{loja}: CNPJ {cnpj}")
                continue
            if forcar:
                diferente = achou & (base["cnpj"] != cnpj)
                if diferente.any():
                    antigo = base.loc[diferente, "cnpj"].iloc[0]
                    base.loc[achou, "cnpj"] = cnpj
                    mudancas.append(f"{empresa}/{loja}: CNPJ {antigo} -> {cnpj} (forçado)")
    return base[COLUNAS_BASE], mudancas


def gravar_base(base: pd.DataFrame, trabalho: Path) -> Path:
    """Troca atômica (tmp + replace): app e lote podem ler ao mesmo tempo."""
    trabalho = Path(trabalho)
    destino = trabalho / NOME_BASE
    tmp = trabalho / f".{NOME_BASE}.tmp"
    base.to_parquet(tmp, index=False)
    os.replace(tmp, destino)
    return destino


def carregar_base(trabalho: Path | None) -> pd.DataFrame:
    """Base gravada, ou vazia se ainda não foi montada."""
    if trabalho is None:
        return pd.DataFrame(columns=COLUNAS_BASE)
    caminho = Path(trabalho) / NOME_BASE
    if not caminho.is_file():
        return pd.DataFrame(columns=COLUNAS_BASE)
    return pd.read_parquet(caminho)


def cnpjs_por_empresa(base: pd.DataFrame) -> dict[str, list[str]]:
    """Empresa → CNPJs das lojas (sem vazios, sem repetição, ordenados)."""
    com_cnpj = base[base["cnpj"].fillna("") != ""]
    return {
        empresa: sorted(set(grupo["cnpj"]))
        for empresa, grupo in com_cnpj.groupby("empresa", sort=True)
    }


def lojas_sem_parquet_price(base: pd.DataFrame, pasta_margem: Path | None) -> list[str]:
    """Lojas com CNPJ na base cujo `margem_{cnpj}.parquet` não existe em
    `pasta_margem`, só nas empresas em que *outra* loja tem o parquet.

    Sinal de margem por transação incompleta sem ninguém perceber: a Viannax
    (set/2026) tinha a Estética Automotiva com um CNPJ no `_EMPRESA.dw_2d` e
    outro no PRICE — a loja ficava de fora da margem em silêncio, e a matriz
    sozinha bastava para a tela nunca dar erro (`ErroMargemPrice` só dispara
    sem nenhum parquet). Empresa sem nenhum parquet no PRICE não entra aqui:
    ela ainda não foi precificada, e isso não é aviso, é o normal.
    """
    if pasta_margem is None or base.empty:
        return []
    pasta = Path(pasta_margem)
    com_cnpj = base[base["cnpj"].fillna("") != ""].copy()
    if com_cnpj.empty:
        return []
    com_cnpj["tem_parquet"] = com_cnpj["cnpj"].map(lambda c: (pasta / f"margem_{c}.parquet").is_file())
    avisos = []
    for empresa, grupo in com_cnpj.groupby("empresa", sort=True):
        if not grupo["tem_parquet"].any():
            continue
        for linha in grupo[~grupo["tem_parquet"]].itertuples():
            avisos.append(
                f"{linha.empresa}/{linha.id_loja}: CNPJ {linha.cnpj} sem parquet em {pasta.name} "
                "(outra loja da empresa tem — a margem por transação fica incompleta)"
            )
    return avisos
