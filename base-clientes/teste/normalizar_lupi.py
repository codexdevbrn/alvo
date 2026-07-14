"""
normalizar_lupi.py
===================

Normaliza os dois exports do PDV/ERP da rede Lupi (3 lojas: lupi_curicica,
lupi, lupi_pm) em uma única planilha `Base.csv` no schema que o motor de
análise do projeto (`backend/engine/analise_funil.py`, função
`carregar_csv`) já espera:

    Loja;NOME_FABRICANTE;Cliente;descricao;Ano;Mês;Código Interno;
    Código de referêcia;Receita Acumulada 11 Meses;QTD

Arquivos de entrada (nesta mesma pasta):
    - Lupi_MOVIMENTO_ATUAL.dw_2d  (~3,24M linhas de movimentação)
    - Lupi_PRODUTO.dw_2d          (~100k linhas = 33.546 produtos x 3 lojas)

Uso:
    python normalizar_lupi.py

Gera `Base.csv` nesta mesma pasta e imprime um relatório de validação ao
final (linhas geradas, produtos sem join, receita total por loja, e uma
tentativa de importar o resultado com `carregar_csv` do motor de análise).

DECISÕES DE NEGÓCIO ASSUMIDAS (revisar/ajustar se necessário)
---------------------------------------------------------------------------
1. TIPO_MOVIMENTO:
   - "VENDA"      -> soma positiva de receita (TOTAL) e quantidade (QUANTIDADE).
   - "DEVOLUCAO"  -> SUBTRAÍDA da receita e da quantidade do mesmo agrupamento
     (Loja, Cliente, Produto, Ano, Mês). Assume-se que uma devolução reduz a
     receita líquida que o cliente efetivamente gerou naquele produto/mês -
     é a leitura mais comum em motores de análise de funil de vendas B2B,
     mas é uma ESCOLHA: se a devolução no sistema de origem já se referir a
     um mês diferente da venda original, o efeito líquido pode "vazar" para
     o mês da devolução em vez do mês da venda. Se isso não for o desejado
     (ex.: quiser ignorar devoluções, ou tratá-las só como redução de
     quantidade sem afetar receita), ajustar a função `processar_chunk`.
   - "COMPRA" e "TRANSFER" -> EXCLUÍDOS por completo (não são vendas a
     cliente final, são movimentos de estoque/logística entre lojas ou com
     fornecedores).

2. Linhas cuja soma líquida de QTD e Receita, dentro do agrupamento final,
   dá exatamente zero (ex.: uma venda totalmente cancelada por devolução no
   mesmo agrupamento) são DESCARTADAS do CSV final - é só para não poluir a
   base com ruído que não representa nem receita nem volume; é opcional e
   pode ser desativado comentando a linha correspondente em `main()`.

3. `Loja` é derivada de `ID_LOJA` (ex.: "lupi_curicica" -> "Lupi Curicica",
   trocando "_" por espaço e aplicando title case) em vez de usar o código
   bruto - só para ficar mais legível nos relatórios; é 1:1 com o ID_LOJA
   original, então não há perda de informação nem ambiguidade.

4. Produtos sem correspondência no join (ID_LOJA, CODIGO_PRODUTO) contra o
   arquivo de produtos ficam com NOME_FABRICANTE, descricao e Código de
   referêcia em branco (NaN) - o motor de análise já trata isso
   automaticamente como "Não informado" / "Não harmonizados", então não
   inventamos nenhum valor aqui.

5. Nenhum cliente é filtrado ou excluído aqui (incluindo "BALCAO") - a
   aplicação já trata esse filtro como opcional na interface (regex
   `balc[aã]o`), então excluir aqui seria duplicar/antecipar uma decisão que
   é do usuário final na tela do Analisador.

6. JANELA DE ANÁLISE: somente o ano ATUAL e o ano ANTERIOR (relativos à data
   em que o script é executado) entram no CSV final. Movimentos de anos mais
   antigos são descartados logo no início do processamento de cada chunk.
   Ex.: rodando em 2026, ficam apenas 2025 e 2026.
"""

from __future__ import annotations

import sys
import time
from datetime import date
from pathlib import Path

import pandas as pd

PASTA = Path(__file__).resolve().parent
ARQ_MOVIMENTO = PASTA / "Lupi_MOVIMENTO_ATUAL.dw_2d"
ARQ_PRODUTO = PASTA / "Lupi_PRODUTO.dw_2d"
ARQ_SAIDA = PASTA / "Base.csv"

CHUNKSIZE = 300_000

MESES_PT = {
    1: "janeiro", 2: "fevereiro", 3: "março", 4: "abril", 5: "maio", 6: "junho",
    7: "julho", 8: "agosto", 9: "setembro", 10: "outubro", 11: "novembro", 12: "dezembro",
}

COLUNAS_SAIDA = [
    "Loja", "NOME_FABRICANTE", "Cliente", "descricao", "Ano", "Mês",
    "Código Interno", "Código de referêcia", "Receita Acumulada 11 Meses", "QTD",
]

COLUNAS_GRUPO = [
    "Loja", "NOME_FABRICANTE", "Cliente", "descricao", "Ano", "Mês",
    "Código Interno", "Código de referêcia",
]

MOVIMENTOS_VALIDOS = ("VENDA", "DEVOLUCAO")

# Decisão de negócio (6), ver docstring: só o ano atual e o anterior entram
# na base final.
ANO_ATUAL = date.today().year
ANOS_PERMITIDOS = (ANO_ATUAL - 1, ANO_ATUAL)


def _parse_numero_br(serie: pd.Series) -> pd.Series:
    """Converte texto BR ('1.234,56' ou '395,00') para float.

    Remove primeiro o ponto de milhar (se houver) e só depois troca a
    vírgula decimal por ponto - a ordem é importante, senão um valor como
    "1.234,56" viraria "1.234.56" e quebraria o to_numeric.
    """
    texto = serie.astype(str).str.strip()
    texto = texto.str.replace(".", "", regex=False)
    texto = texto.str.replace(",", ".", regex=False)
    return pd.to_numeric(texto, errors="coerce")


def carregar_produtos() -> pd.DataFrame:
    """Carrega o catálogo de produtos e prepara a chave de join (ID_LOJA, CODIGO_PRODUTO)."""
    produtos = pd.read_csv(
        ARQ_PRODUTO, sep=";", quotechar='"', encoding="utf-8-sig", dtype=str,
        usecols=["ID_LOJA", "CODIGO_INTERNO_PRODUTO", "CODIGO_REFERENCIA_PRODUTO",
                 "DESCRICAO_PRODUTO", "NOME_FABRICANTE"],
    )
    produtos = produtos.rename(columns={"CODIGO_INTERNO_PRODUTO": "CODIGO_PRODUTO"})
    produtos["CODIGO_REFERENCIA_PRODUTO"] = produtos["CODIGO_REFERENCIA_PRODUTO"].replace("", pd.NA)

    duplicados = produtos.duplicated(subset=["ID_LOJA", "CODIGO_PRODUTO"]).sum()
    if duplicados:
        print(
            f"[AVISO] {duplicados} linha(s) duplicada(s) em (ID_LOJA, CODIGO_PRODUTO) no "
            "arquivo de produtos - mantendo a última ocorrência de cada uma."
        )
        produtos = produtos.drop_duplicates(subset=["ID_LOJA", "CODIGO_PRODUTO"], keep="last")

    return produtos[["ID_LOJA", "CODIGO_PRODUTO", "CODIGO_REFERENCIA_PRODUTO",
                      "DESCRICAO_PRODUTO", "NOME_FABRICANTE"]]


def formatar_loja(id_loja_serie: pd.Series) -> pd.Series:
    """'lupi_curicica' -> 'Lupi Curicica' (1:1 com ID_LOJA, só para legibilidade)."""
    return id_loja_serie.str.replace("_", " ", regex=False).str.title()


def processar_chunk(chunk: pd.DataFrame, produtos: pd.DataFrame) -> pd.DataFrame | None:
    """
    Filtra, ajusta sinais (VENDA soma / DEVOLUCAO subtrai), faz o join com
    produtos e agrega o chunk pelas colunas de agrupamento finais. Retorna
    None se, após o filtro de TIPO_MOVIMENTO, o chunk não tiver nenhuma
    linha aproveitável.
    """
    chunk = chunk[chunk["TIPO_MOVIMENTO"].isin(MOVIMENTOS_VALIDOS)].copy()
    if chunk.empty:
        return None

    chunk["QUANTIDADE"] = _parse_numero_br(chunk["QUANTIDADE"]).fillna(0.0)
    chunk["TOTAL"] = _parse_numero_br(chunk["TOTAL"]).fillna(0.0)

    eh_devolucao = chunk["TIPO_MOVIMENTO"] == "DEVOLUCAO"
    chunk.loc[eh_devolucao, "QUANTIDADE"] *= -1
    chunk.loc[eh_devolucao, "TOTAL"] *= -1

    # Fatiamento de string em vez de pd.to_datetime: formato fixo
    # "dd/mm/yyyy HH:MM:SS" sem nulos (confirmado pelo usuário) - muito mais
    # rápido que parsing de data completo em 3M+ linhas.
    mes_num = chunk["DATA_MOVIMENTO"].str.slice(3, 5).astype(int)
    ano_num = chunk["DATA_MOVIMENTO"].str.slice(6, 10).astype(int)
    chunk["Ano"] = ano_num
    chunk["Mês"] = mes_num.map(MESES_PT)

    # Decisão de negócio (6): mantém só o ano atual e o anterior.
    chunk = chunk[chunk["Ano"].isin(ANOS_PERMITIDOS)]
    if chunk.empty:
        return None

    chunk["Loja"] = formatar_loja(chunk["ID_LOJA"])
    chunk["Cliente"] = chunk["NOME_CLIENTE"]
    chunk["Código Interno"] = chunk["CODIGO_PRODUTO"]

    chunk = chunk.merge(produtos, how="left", on=["ID_LOJA", "CODIGO_PRODUTO"])
    chunk["descricao"] = chunk["DESCRICAO_PRODUTO"]
    chunk["Código de referêcia"] = chunk["CODIGO_REFERENCIA_PRODUTO"]

    agregado = (
        chunk.groupby(COLUNAS_GRUPO, dropna=False, as_index=False)
        .agg(Receita=("TOTAL", "sum"), QTD=("QUANTIDADE", "sum"))
    )
    return agregado


def formatar_qtd(valor: float) -> str:
    """QTD sem separador BR: inteiro puro, ou decimal com ponto se houver fração residual."""
    valor_round = round(float(valor), 4)
    if abs(valor_round - round(valor_round)) < 1e-6:
        return str(int(round(valor_round)))
    texto = f"{valor_round:.4f}".rstrip("0").rstrip(".")
    return texto


def formatar_receita(valor: float) -> str:
    """Receita em formato BR (vírgula decimal), sem separador de milhar."""
    return f"{float(valor):.2f}".replace(".", ",")


def normalizar() -> pd.DataFrame:
    """Lê os dois arquivos de entrada em chunks e retorna o DataFrame final já formatado."""
    print(f"Carregando catálogo de produtos: {ARQ_PRODUTO.name}")
    produtos = carregar_produtos()
    print(f"  {len(produtos):,} produtos carregados (ID_LOJA + CODIGO_PRODUTO únicos).")

    print(f"Lendo movimentação em chunks de {CHUNKSIZE:,} linhas: {ARQ_MOVIMENTO.name}")
    partes = []
    total_linhas_lidas = 0
    total_linhas_aproveitadas = 0
    inicio = time.time()

    leitor = pd.read_csv(
        ARQ_MOVIMENTO, sep=";", quotechar='"', encoding="utf-8-sig", dtype=str,
        usecols=["ID_LOJA", "TIPO_MOVIMENTO", "DATA_MOVIMENTO", "NOME_CLIENTE",
                 "CODIGO_PRODUTO", "QUANTIDADE", "TOTAL"],
        chunksize=CHUNKSIZE,
    )
    for i, chunk in enumerate(leitor, start=1):
        total_linhas_lidas += len(chunk)
        agregado = processar_chunk(chunk, produtos)
        if agregado is not None and not agregado.empty:
            total_linhas_aproveitadas += len(agregado)
            partes.append(agregado)
        decorrido = time.time() - inicio
        print(f"  chunk {i:>3}: {len(chunk):>9,} linhas lidas | "
              f"{total_linhas_lidas:>10,} acumuladas | {decorrido:6.1f}s")

    print(f"Leitura concluída em {time.time() - inicio:.1f}s. Consolidando agregações parciais...")
    if not partes:
        raise RuntimeError("Nenhuma linha de VENDA/DEVOLUCAO encontrada no arquivo de movimento.")

    consolidado = pd.concat(partes, ignore_index=True)
    final = (
        consolidado.groupby(COLUNAS_GRUPO, dropna=False, as_index=False)
        .agg(Receita=("Receita", "sum"), QTD=("QTD", "sum"))
    )

    antes = len(final)
    # Decisão de negócio (2), ver docstring do módulo: descarta ruído de
    # agrupamentos com receita E quantidade líquidas exatamente zero.
    mascara_zero = (final["Receita"].round(2) == 0) & (final["QTD"].round(4) == 0)
    final = final[~mascara_zero].copy()
    descartadas = antes - len(final)
    print(f"Agrupamentos consolidados: {antes:,} -> {len(final):,} "
          f"({descartadas:,} descartados por receita e quantidade líquidas = 0).")

    final["Ano"] = final["Ano"].astype(int)
    final["QTD"] = final["QTD"].apply(formatar_qtd)
    final["Receita Acumulada 11 Meses"] = final["Receita"].apply(formatar_receita)

    final = final[COLUNAS_SAIDA]
    return final


def validar(df_saida: pd.DataFrame) -> None:
    """Sanity check do resultado: leitura de volta, tipos, join e importação pelo motor."""
    print("\n" + "=" * 70)
    print("VALIDAÇÃO")
    print("=" * 70)

    print(f"Linhas no CSV final: {len(df_saida):,}")

    sem_fabricante = df_saida["NOME_FABRICANTE"].isna().sum()
    sem_descricao = df_saida["descricao"].isna().sum()
    print(f"Linhas sem NOME_FABRICANTE (produto não encontrado no join): {sem_fabricante:,} "
          f"({sem_fabricante / len(df_saida) * 100:.2f}%)")
    print(f"Linhas sem descricao (produto não encontrado no join): {sem_descricao:,} "
          f"({sem_descricao / len(df_saida) * 100:.2f}%)")

    print("\nReceita líquida total por loja (sanity check):")
    receita_num = pd.to_numeric(
        df_saida["Receita Acumulada 11 Meses"].str.replace(",", ".", regex=False), errors="coerce"
    )
    resumo_loja = (
        df_saida.assign(_receita_num=receita_num)
        .groupby("Loja")["_receita_num"].sum()
        .sort_values(ascending=False)
    )
    for loja, receita in resumo_loja.items():
        print(f"  {loja:<20} R$ {receita:>16,.2f}")
    print(f"  {'TOTAL':<20} R$ {resumo_loja.sum():>16,.2f}")

    print("\nRelendo o arquivo gerado com pandas.read_csv(sep=';', encoding='utf-8-sig')...")
    relido = pd.read_csv(ARQ_SAIDA, sep=";", encoding="utf-8-sig")
    cabecalho_esperado = COLUNAS_SAIDA
    if list(relido.columns) != cabecalho_esperado:
        print("[ERRO] Cabeçalho lido não corresponde ao esperado!")
        print(f"  Esperado: {cabecalho_esperado}")
        print(f"  Obtido:   {list(relido.columns)}")
    else:
        print("  Cabeçalho OK, corresponde exatamente ao esperado.")
    print(f"  Linhas relidas: {len(relido):,}")

    ano_numerico = pd.to_numeric(relido["Ano"], errors="coerce")
    qtd_numerico = pd.to_numeric(relido["QTD"], errors="coerce")
    receita_numerico = pd.to_numeric(
        relido["Receita Acumulada 11 Meses"].astype(str).str.replace(",", ".", regex=False),
        errors="coerce",
    )
    print(f"  Ano: {ano_numerico.isna().sum()} valor(es) não numérico(s) "
          f"(min={ano_numerico.min()}, max={ano_numerico.max()})")
    print(f"  QTD: {qtd_numerico.isna().sum()} valor(es) não numérico(s)")
    print(f"  Receita: {receita_numerico.isna().sum()} valor(es) não parseável(is)")

    print("\nTentando importar o CSV com o motor de análise (backend/engine/analise_funil.py)...")
    backend_path = str((PASTA / ".." / ".." / "backend").resolve())
    if backend_path not in sys.path:
        sys.path.insert(0, backend_path)
    try:
        from engine.analise_funil import carregar_csv, contar_produtos_nao_harmonizados, ErroCarregamentoCSV
    except Exception as exc:
        print(f"[ERRO] Não foi possível importar o motor de análise: {exc}")
        return

    try:
        df_motor, linhas_vazias = carregar_csv(str(ARQ_SAIDA))
    except ErroCarregamentoCSV as exc:
        print(f"[ERRO] carregar_csv levantou ErroCarregamentoCSV: {exc}")
        return
    except Exception as exc:
        print(f"[ERRO] carregar_csv levantou uma exceção inesperada: {exc}")
        return

    if df_motor.empty:
        print("[ERRO] DataFrame retornado por carregar_csv está vazio!")
        return

    nao_harmonizados = contar_produtos_nao_harmonizados(df_motor)
    print("  OK - carregar_csv importou o arquivo sem levantar ErroCarregamentoCSV.")
    print(f"  Linhas no DataFrame final do motor: {len(df_motor):,}")
    print(f"  Linhas descartadas por Ano/Mês vazio: {linhas_vazias}")
    print(f"  Linhas com produto 'Não harmonizados' (sem descrição no join): {nao_harmonizados:,}")
    print(f"  Receita total (coluna 'Receita' já convertida pelo motor): "
          f"R$ {df_motor['Receita'].sum():,.2f}")
    print(f"  Período coberto: {df_motor['Data_Venda'].min().date()} a {df_motor['Data_Venda'].max().date()}")


def main() -> None:
    df_saida = normalizar()
    print(f"\nGravando {ARQ_SAIDA}...")
    df_saida.to_csv(ARQ_SAIDA, sep=";", index=False, encoding="utf-8-sig")
    print(f"Arquivo gravado: {ARQ_SAIDA} ({len(df_saida):,} linhas).")
    validar(df_saida)


if __name__ == "__main__":
    main()
