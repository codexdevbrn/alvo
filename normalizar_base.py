"""
normalizar_base.py
===================

Localiza os arquivos de origem de uma empresa na pasta fonte (somente
leitura). O parsing/limpeza fica em `backend/engine/analise_funil.py`
(`carregar_csv_base_empresa`) — este módulo só resolve caminhos.

Layout da fonte (uma subpasta por empresa, direto nela, sem `BI/`):

    <pasta_fonte>/<empresa>/<empresa>_MOVIMENTO_ATUAL.parquet   (obrigatório)
    <pasta_fonte>/<empresa>/<empresa>_PRODUTO.parquet           (obrigatório)
    <pasta_fonte>/<empresa>/Dados_Estoque_<empresa>.*           (opcional, só Liquidez)
    <pasta_fonte>/<empresa>/Dados_Vendas_<empresa>.*            (opcional, só Liquidez)
    <pasta_fonte>/<empresa>/{empresa}_CONTROLADORIA.parquet     (opcional, Despesas)

    <pasta_trabalho>/<empresa>/{empresa}_PRECIFICACAO.parquet   (opcional, gerado pelo lote)

Só parquet: a fonte deixou de vir em CSV, e manter os dois caminhos obrigava o
leitor a imitar a inferência de tipo do `read_csv`. O esquema é o mesmo nas
empresas, mas a leitura é sempre por nome, nunca por posição (ver `analise_funil`).
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd


class ErroNormalizacao(Exception):
    """Erro amigável quando os arquivos de origem não são encontrados ou são inválidos."""
    pass


def ler_csv_robusto(filepath_or_buffer, **kwargs):
    """Tenta ler com utf-8-sig. Se der erro de Unicode, tenta com latin1.

    Usado hoje só pelo pipeline Liquidez (normalizar_liquidez.py) — o
    movimento/produto da empresa é lido por `analise_funil.carregar_csv_base_empresa`.
    """
    kwargs.pop("encoding", None)  # Remove se foi passado para forçar o nosso fallback
    try:
        return pd.read_csv(filepath_or_buffer, encoding="utf-8-sig", **kwargs)
    except UnicodeDecodeError:
        return pd.read_csv(filepath_or_buffer, encoding="latin1", **kwargs)


def parse_numero_flexivel(serie: pd.Series) -> pd.Series:
    """Converte texto numérico para float, aceitando formato BR ('1.234,56')
    ou internacional ('1234.56') - decide por valor, olhando qual separador
    (',' ou '.') aparece mais à direita no texto (esse é o decimal; o outro,
    se houver, é separador de milhar e é descartado)."""
    texto = serie.fillna("").astype(str).str.strip()

    pos_virgula = texto.str.rfind(",")
    pos_ponto = texto.str.rfind(".")
    tem_virgula = pos_virgula >= 0
    tem_ponto = pos_ponto >= 0

    virgula_e_decimal = (tem_virgula & ~tem_ponto) | (tem_virgula & tem_ponto & (pos_virgula > pos_ponto))
    ponto_e_decimal = (tem_ponto & ~tem_virgula) | (tem_virgula & tem_ponto & (pos_ponto > pos_virgula))

    saida = texto.copy()
    saida = saida.mask(
        virgula_e_decimal,
        texto.str.replace(".", "", regex=False).str.replace(",", ".", regex=False),
    )
    saida = saida.mask(ponto_e_decimal, texto.str.replace(",", "", regex=False))

    return pd.to_numeric(saida, errors="coerce")


def serie_texto_limpa(serie: pd.Series) -> pd.Series:
    """Strip; '' / 'nan' viram NA."""
    texto = serie.fillna("").astype(str).str.strip()
    return texto.mask(texto.str.lower().isin(("", "nan", "none", "<na>")), other=pd.NA)


MESES_PT = {
    1: "janeiro", 2: "fevereiro", 3: "março", 4: "abril", 5: "maio", 6: "junho",
    7: "julho", 8: "agosto", 9: "setembro", 10: "outubro", 11: "novembro", 12: "dezembro",
}


def normalizar_mes(serie: pd.Series) -> pd.Series:
    """Aceita Mês como número (1-12) ou já por extenso em PT-BR; sempre
    devolve o nome por extenso (o que o pipeline Liquidez espera)."""
    texto = serie_texto_limpa(serie)
    numerico = pd.to_numeric(texto, errors="coerce")
    eh_numerico = numerico.notna()
    convertido = texto.copy()
    convertido = convertido.mask(eh_numerico, numerico.map(MESES_PT))
    return convertido


def formatar_qtd(valor: float) -> str:
    """QTD sem separador BR: inteiro puro, ou decimal com ponto se houver fração residual."""
    if pd.isna(valor):
        return "0"
    valor_round = round(float(valor), 4)
    if abs(valor_round - round(valor_round)) < 1e-6:
        return str(int(round(valor_round)))
    texto = f"{valor_round:.4f}".rstrip("0").rstrip(".")
    return texto


def validar_colunas(df: pd.DataFrame, esperadas: set[str], nome_arquivo: str) -> None:
    """Levanta ErroNormalizacao se alguma coluna de `esperadas` não estiver em `df`."""
    faltando = sorted(esperadas - set(df.columns))
    if faltando:
        raise ErroNormalizacao(f"Arquivo {nome_arquivo} sem colunas: {', '.join(faltando)}.")


def _resolver_arquivo_fonte(arquivos: list[Path], nome_base: str) -> Path | None:
    """`{nome_base}.parquet` entre `arquivos`, sem diferenciar caixa (Windows)."""
    alvo = f"{nome_base}.parquet".casefold()
    return next((a for a in arquivos if a.name.casefold() == alvo), None)


def _arquivos_da_pasta(pasta: Path) -> list[Path]:
    try:
        return [a for a in pasta.iterdir() if a.is_file()]
    except OSError:
        return []


def resolver_arquivos_dados(pasta_empresa: Path) -> tuple[Path, Path, Path | None, Path | None]:
    """Localiza os arquivos da empresa na fonte.

    Retorna `(caminho_movimento, caminho_produto, caminho_estoque, caminho_vendas)`.
    Movimento e Produto têm nome fixo `{nome_empresa}_MOVIMENTO_ATUAL` /
    `{nome_empresa}_PRODUTO`, em parquet, e são obrigatórios. Estoque e Vendas (Liquidez)
    continuam usando os nomes legados com o nome da empresa e extensão livre, e
    são opcionais — só necessários quando a análise de Liquidez for solicitada.
    Comparação case-insensitive para funcionar no Windows.
    """
    nome_empresa = pasta_empresa.name
    alvos_opcionais = {
        f"dados_estoque_{nome_empresa}".lower(): "estoque",
        f"dados_vendas_{nome_empresa}".lower(): "vendas",
    }

    arquivos = _arquivos_da_pasta(pasta_empresa) if pasta_empresa.is_dir() else []
    encontrados: dict[str, Path] = {}
    for papel, nome_base in (
        ("movimento", f"{nome_empresa}_MOVIMENTO_ATUAL"),
        ("produto", f"{nome_empresa}_PRODUTO"),
    ):
        achado = _resolver_arquivo_fonte(arquivos, nome_base)
        if achado is not None:
            encontrados[papel] = achado
    for arquivo in arquivos:
        papel = alvos_opcionais.get(arquivo.stem.lower())
        if papel is not None:
            encontrados[papel] = arquivo

    faltando = []
    if "movimento" not in encontrados:
        faltando.append(f"{nome_empresa}_MOVIMENTO_ATUAL.parquet")
    if "produto" not in encontrados:
        faltando.append(f"{nome_empresa}_PRODUTO.parquet")
    if faltando:
        raise ErroNormalizacao(
            f"Não foi possível localizar em {pasta_empresa}: " + ", ".join(faltando) + "."
        )

    return (
        encontrados["movimento"],
        encontrados["produto"],
        encontrados.get("estoque"),
        encontrados.get("vendas"),
    )


def resolver_caminho_controladoria(pasta_empresa: Path) -> Path | None:
    """Localiza `{empresa}_CONTROLADORIA.parquet` na fonte, se existir.

    Despesas (tela Controladoria) é opcional e independente de Movimento/Produto
    — arquivo próprio, nome fixo, sem join. Empresa sem o arquivo simplesmente
    não tem a tela; não é um `ErroNormalizacao` como movimento/produto.
    """
    if not pasta_empresa.is_dir():
        return None
    return _resolver_arquivo_fonte(
        _arquivos_da_pasta(pasta_empresa), f"{pasta_empresa.name}_CONTROLADORIA",
    )


def resolver_caminho_precificacao(pasta_trabalho: Path | None) -> Path | None:
    """Localiza `{empresa}_PRECIFICACAO.parquet` na pasta de trabalho da empresa.

    Pós precificação é opcional e independente de Movimento/Produto — dump
    próprio, nome fixo. Empresa sem o arquivo não tem a tela; não é
    `ErroNormalizacao`. Quem grava é `precificacao_do_postgres.py`, a partir do
    banco; a reserva na pasta fonte (CSV exportado à mão) saiu junto com o CSV.
    """
    if pasta_trabalho is None or not Path(pasta_trabalho).is_dir():
        return None
    pasta_trabalho = Path(pasta_trabalho)
    return _resolver_arquivo_fonte(
        _arquivos_da_pasta(pasta_trabalho), f"{pasta_trabalho.name}_PRECIFICACAO",
    )
