"""
normalizar_base.py
===================

Script generalista de normalização de dados de empresas: lê os exports de
movimento e produto de um PDV/ERP (pasta `BI/` dentro da pasta da empresa) e
gera o `Base.csv` no schema que o motor de análise do projeto
(`backend/engine/analise_funil.py`, função `carregar_csv`) já espera:

    Loja;NOME_FABRICANTE;Cliente;descricao;Ano;Mês;Código Interno;
    Código de referêcia;Receita Acumulada 11 Meses;QTD

Layout de pastas — dois papéis (pastas distintas):

    <pasta_fonte>/                         (somente leitura)
        BI/
            <nome>_MOVIMENTO_ATUAL.<ext>   (preferido)
            <nome>_MOVIMENTO.<ext>         (fallback, se não houver _ATUAL)
            <nome>_PRODUTO.<ext>

    <pasta_trabalho>/                      (escrita: Base.csv, harm, backups)
        harm.xlsx                          (opcional, aplicado automaticamente)
        Base.csv                           (gerado por este script)

A fonte nunca recebe escrita. `--trabalho` é obrigatório no CLI.

Onde `<nome>` é o nome da pasta da empresa (ex.: pasta "teste" -> arquivos
"teste_MOVIMENTO_ATUAL.dw_2d" e "teste_PRODUTO.dw_2d") e `<ext>` pode ser
`.dw_2d` (export nativo do PDV) ou `.csv` (mesmo layout de colunas e
separador) — a busca por arquivo é case-insensitive e não fixa a extensão.

Uso via linha de comando:
    python normalizar_base.py "C:/fonte/teste" --trabalho "C:/trabalho/teste"
    python normalizar_base.py "C:/fonte/teste" --trabalho "C:/trabalho/teste" --sem-harmonizacao
    python normalizar_base.py "C:/fonte/teste" --trabalho "C:/trabalho/teste" --sem-validacao

Uso programático (ex.: backend/main.py, ao selecionar a empresa no dash):
    from normalizar_base import normalizar_pasta_empresa
    caminho_base_csv = normalizar_pasta_empresa(
        Path("fonte/teste"), pasta_trabalho=Path("trabalho/teste"),
    )

DECISÕES DE NEGÓCIO ASSUMIDAS (revisar/ajustar se necessário) — herdadas e
generalizadas de base-clientes/teste/normalizar_lupi.py, que originou este
script a partir do caso da rede Lupi:
---------------------------------------------------------------------------
1. TIPO_MOVIMENTO / MOV:
   - "VENDA"      -> soma positiva de receita (TOTAL) e quantidade (QUANTIDADE).
     No DW, vendas saem tipicamente com MOV="S" (saída).
   - "DEVOLUCAO"  -> SUBTRAÍDA da receita e da quantidade do mesmo agrupamento
     (Loja, Cliente, Produto, Ano, Mês), mas só quando MOV="E" (entrada de
     mercadoria). Linhas de DEVOLUCAO com MOV="S" são documento espelho /
     contrapartida fiscal e NÃO devem reduzir a receita de novo — incluí-las
     duplicava a baixa (ex.: Frandiesel jun/2026 ficava em ~442k em vez de
     ~650k). Se a coluna MOV não existir no arquivo, mantém-se o comportamento
     antigo (todas as DEVOLUCAO entram).
   - "COMPRA" e "TRANSFER" -> EXCLUÍDOS por completo (não são vendas a
     cliente final, são movimentos de estoque/logística entre lojas ou com
     fornecedores).

2. Linhas cuja soma líquida de QTD e Receita, dentro do agrupamento final,
   dá exatamente zero (ex.: uma venda totalmente cancelada por devolução no
   mesmo agrupamento) são DESCARTADAS do CSV final - é só para não poluir a
   base com ruído que não representa nem receita nem volume.

3. `Loja` é derivada de `ID_LOJA` (ex.: "lupi_curicica" -> "Lupi Curicica",
   trocando "_" por espaço e aplicando title case) em vez de usar o código
   bruto - só para ficar mais legível nos relatórios; é 1:1 com o ID_LOJA
   original, então não há perda de informação nem ambiguidade.

4. Produtos sem correspondência no join (ID_LOJA, CODIGO_PRODUTO) contra o
   arquivo de produtos ficam com NOME_FABRICANTE, descricao e Código de
   referêcia em branco (NaN) - o motor de análise já trata isso
   automaticamente como "Não informado" / "Não harmonizados".

5. Nenhum cliente é filtrado ou excluído aqui (incluindo "BALCAO") - a
   aplicação já trata esse filtro como opcional na interface do Analisador.

6. JANELA DE ANÁLISE: somente o ano ATUAL e o ano ANTERIOR (relativos ao
   momento em que o script é executado) entram no CSV final. Movimentos de
   anos mais antigos são descartados no processamento de cada chunk.

7. HARMONIZAÇÃO AUTOMÁTICA: se existir `harm.xlsx` (ou `.xls`) na pasta de
   trabalho, `normalizar_pasta_empresa` aplica `harmonizar_descricoes.py`
   automaticamente sobre o Base.csv recém-gerado, substituindo a descrição
   bruta do catálogo pela descrição harmonizada. Sem a planilha, a
   `descricao` fica com o texto bruto vindo do arquivo de PRODUTO (o motor
   de análise não rotula isso como "Não harmonizados" - só rotula assim
   quando a descrição está vazia). A planilha e o backup
   `Base.antes-harm.csv` ficam sempre na pasta de trabalho.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
import warnings
from datetime import date
from pathlib import Path

import pandas as pd

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

# Colunas lidas do MOVIMENTO (MOV é opcional — ver decisão de negócio 1).
COLS_MOVIMENTO = {
    "ID_LOJA", "TIPO_MOVIMENTO", "DATA_MOVIMENTO", "NOME_CLIENTE",
    "CODIGO_PRODUTO", "QUANTIDADE", "TOTAL", "MOV",
}

NOME_ARQUIVO_HARM_PADRAO = "harm.xlsx"


class ErroNormalizacao(Exception):
    """Erro amigável quando os arquivos de origem (BI/) não são encontrados ou são inválidos."""
    pass


# ---------------------------------------------------------------------------
# Localização dos arquivos de origem em BI/
# ---------------------------------------------------------------------------

def _buscar_arquivo(pasta_bi: Path, nome_empresa: str, sufixos: list[str]) -> Path | None:
    """Procura, em ordem de preferência dos sufixos, um arquivo cujo nome
    (sem extensão) seja "<nome_empresa>_<sufixo>" - comparação case-insensitive,
    extensão livre (.dw_2d, .csv etc.)."""
    if not pasta_bi.is_dir():
        return None
    arquivos = [a for a in pasta_bi.iterdir() if a.is_file()]
    for sufixo in sufixos:
        alvo = f"{nome_empresa}_{sufixo}".lower()
        for arquivo in arquivos:
            if arquivo.stem.lower() == alvo:
                return arquivo
    return None


def resolver_arquivos_bi(pasta_empresa: Path) -> tuple[Path, Path]:
    """Localiza os arquivos de movimento e produto em <pasta_empresa>/BI/.

    Levanta ErroNormalizacao com mensagem amigável se algum dos dois não for
    encontrado.
    """
    nome_empresa = pasta_empresa.name
    pasta_bi = pasta_empresa / "BI"

    caminho_movimento = _buscar_arquivo(pasta_bi, nome_empresa, ["MOVIMENTO_ATUAL", "MOVIMENTO"])
    caminho_produto = _buscar_arquivo(pasta_bi, nome_empresa, ["PRODUTO"])

    faltando = []
    if caminho_movimento is None:
        faltando.append(f"{nome_empresa}_MOVIMENTO_ATUAL ou {nome_empresa}_MOVIMENTO")
    if caminho_produto is None:
        faltando.append(f"{nome_empresa}_PRODUTO")
    if faltando:
        raise ErroNormalizacao(
            f"Não foi possível localizar em {pasta_bi}: " + " e ".join(faltando) + "."
        )

    return caminho_movimento, caminho_produto


def obter_data_ultimo_movimento(caminho_movimento: Path, *, chunksize: int = CHUNKSIZE) -> date | None:
    """Data exata (calendário) do último movimento de VENDA no arquivo BI (somente leitura)."""
    max_data: date | None = None
    leitor = pd.read_csv(
        caminho_movimento,
        sep=";",
        quotechar='"',
        encoding="utf-8-sig",
        dtype=str,
        usecols=["TIPO_MOVIMENTO", "DATA_MOVIMENTO"],
        chunksize=chunksize,
    )
    for chunk in leitor:
        vendas = chunk[chunk["TIPO_MOVIMENTO"] == "VENDA"]
        if vendas.empty:
            continue
        datas = pd.to_datetime(
            vendas["DATA_MOVIMENTO"].str.slice(0, 10),
            format="%d/%m/%Y",
            errors="coerce",
        )
        candidata = datas.max()
        if pd.isna(candidata):
            continue
        dia = candidata.date()
        if max_data is None or dia > max_data:
            max_data = dia
    return max_data


# ---------------------------------------------------------------------------
# Normalização (movimento + produto -> DataFrame no schema do Base.csv)
# ---------------------------------------------------------------------------

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


def carregar_produtos(caminho_produto: Path) -> pd.DataFrame:
    """Carrega o catálogo de produtos e prepara a chave de join (ID_LOJA, CODIGO_PRODUTO)."""
    produtos = pd.read_csv(
        caminho_produto, sep=";", quotechar='"', encoding="utf-8-sig", dtype=str,
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


def processar_chunk(chunk: pd.DataFrame, produtos: pd.DataFrame, anos_permitidos: tuple[int, int]) -> pd.DataFrame | None:
    """
    Filtra, ajusta sinais (VENDA soma / DEVOLUCAO subtrai), faz o join com
    produtos e agrega o chunk pelas colunas de agrupamento finais. Retorna
    None se, após os filtros, o chunk não tiver nenhuma linha aproveitável.
    """
    chunk = chunk[chunk["TIPO_MOVIMENTO"].isin(MOVIMENTOS_VALIDOS)].copy()
    if chunk.empty:
        return None

    # DEVOLUCAO + MOV=S = espelho documental; a baixa de receita é só MOV=E.
    if "MOV" in chunk.columns:
        mov = chunk["MOV"].fillna("").astype(str).str.strip().str.upper()
        espelho = (chunk["TIPO_MOVIMENTO"] == "DEVOLUCAO") & mov.eq("S")
        chunk = chunk.loc[~espelho].copy()
        if chunk.empty:
            return None

    chunk["QUANTIDADE"] = _parse_numero_br(chunk["QUANTIDADE"]).fillna(0.0)
    chunk["TOTAL"] = _parse_numero_br(chunk["TOTAL"]).fillna(0.0)

    eh_devolucao = chunk["TIPO_MOVIMENTO"] == "DEVOLUCAO"
    chunk.loc[eh_devolucao, "QUANTIDADE"] *= -1
    chunk.loc[eh_devolucao, "TOTAL"] *= -1

    # Fatiamento de string em vez de pd.to_datetime: formato fixo
    # "dd/mm/yyyy HH:MM:SS" sem nulos - muito mais rápido que parsing de data
    # completo em bases com milhões de linhas.
    mes_num = chunk["DATA_MOVIMENTO"].str.slice(3, 5).astype(int)
    ano_num = chunk["DATA_MOVIMENTO"].str.slice(6, 10).astype(int)
    chunk["Ano"] = ano_num
    chunk["Mês"] = mes_num.map(MESES_PT)

    # Decisão de negócio (6): mantém só o ano atual e o anterior.
    chunk = chunk[chunk["Ano"].isin(anos_permitidos)]
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


def normalizar(caminho_movimento: Path, caminho_produto: Path) -> pd.DataFrame:
    """Lê os dois arquivos de origem em chunks e retorna o DataFrame final já formatado."""
    ano_atual = date.today().year
    anos_permitidos = (ano_atual - 1, ano_atual)

    print(f"Carregando catálogo de produtos: {caminho_produto.name}")
    produtos = carregar_produtos(caminho_produto)
    print(f"  {len(produtos):,} produtos carregados (ID_LOJA + CODIGO_PRODUTO únicos).")

    print(f"Lendo movimentação em chunks de {CHUNKSIZE:,} linhas: {caminho_movimento.name}")
    partes = []
    total_linhas_lidas = 0
    inicio = time.time()

    leitor = pd.read_csv(
        caminho_movimento, sep=";", quotechar='"', encoding="utf-8-sig", dtype=str,
        usecols=lambda c: c in COLS_MOVIMENTO,
        chunksize=CHUNKSIZE,
    )
    for i, chunk in enumerate(leitor, start=1):
        total_linhas_lidas += len(chunk)
        agregado = processar_chunk(chunk, produtos, anos_permitidos)
        if agregado is not None and not agregado.empty:
            partes.append(agregado)
        decorrido = time.time() - inicio
        print(f"  chunk {i:>3}: {len(chunk):>9,} linhas lidas | "
              f"{total_linhas_lidas:>10,} acumuladas | {decorrido:6.1f}s")

    print(f"Leitura concluída em {time.time() - inicio:.1f}s. Consolidando agregações parciais...")
    if not partes:
        raise ErroNormalizacao(
            f"Nenhuma linha de VENDA/DEVOLUCAO encontrada no arquivo de movimento "
            f"para os anos {anos_permitidos[0]} ou {anos_permitidos[1]}."
        )

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


def validar(caminho_saida: Path, total_linhas_gravadas: int) -> None:
    """Sanity check leve do resultado gravado: leitura de volta e tipos.

    Não tenta importar backend/engine aqui (evita acoplamento de sys.path
    quando chamado programaticamente pelo próprio backend, que já tem esse
    módulo importado) - só confere se o CSV é reabrível e consistente.
    """
    print("\n" + "=" * 70)
    print("VALIDAÇÃO")
    print("=" * 70)

    relido = pd.read_csv(caminho_saida, sep=";", encoding="utf-8-sig")
    if list(relido.columns) != COLUNAS_SAIDA:
        print("[AVISO] Cabeçalho lido não corresponde ao esperado!")
        print(f"  Esperado: {COLUNAS_SAIDA}")
        print(f"  Obtido:   {list(relido.columns)}")
    else:
        print("  Cabeçalho OK, corresponde exatamente ao esperado.")
    print(f"  Linhas gravadas: {total_linhas_gravadas:,} | Linhas relidas: {len(relido):,}")

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


# ---------------------------------------------------------------------------
# Orquestração: pasta da empresa -> Base.csv (+ harmonização automática)
# ---------------------------------------------------------------------------

def normalizar_pasta_empresa(
    pasta_fonte: Path,
    pasta_trabalho: Path | None = None,
    aplicar_harmonizacao: bool = True,
    validar_resultado: bool = True,
) -> Path:
    """Lê BI/ em `pasta_fonte` e gera `Base.csv` em `pasta_trabalho`.

    `pasta_trabalho` é obrigatória e deve ser distinta da fonte (e não pode
    estar dentro dela). A fonte é somente leitura — este módulo nunca grava
    sob `pasta_fonte`.

    Se `aplicar_harmonizacao` for True e existir harm.xlsx/harm.xls na pasta
    de trabalho, aplica `harmonizar_descricoes.harmonizar` sobre o Base.csv
    (decisão de negócio 7). Backup e planilha ficam só no trabalho.

    Retorna o caminho do Base.csv gerado.
    """
    pasta_fonte = Path(pasta_fonte).resolve()
    if pasta_trabalho is None:
        raise ErroNormalizacao(
            "pasta_trabalho é obrigatória. A pasta fonte (BI/) é somente leitura — "
            "informe uma pasta de trabalho distinta para gravar o Base.csv "
            "(CLI: --trabalho <pasta>)."
        )
    pasta_trabalho = Path(pasta_trabalho).resolve()

    # Comparar via realpath/resolve (já feito acima) + normcase para Windows.
    fonte_s = os.path.normcase(os.path.realpath(str(pasta_fonte)))
    trab_s = os.path.normcase(os.path.realpath(str(pasta_trabalho)))
    if trab_s == fonte_s or trab_s.startswith(fonte_s + os.sep):
        raise ErroNormalizacao(
            f"Escrita proibida na pasta fonte. pasta_trabalho ({pasta_trabalho}) "
            f"não pode ser igual a pasta_fonte nem estar dentro dela ({pasta_fonte})."
        )

    caminho_movimento, caminho_produto = resolver_arquivos_bi(pasta_fonte)

    df_saida = normalizar(caminho_movimento, caminho_produto)

    pasta_trabalho.mkdir(parents=True, exist_ok=True)
    caminho_saida = pasta_trabalho / "Base.csv"
    print(f"\nGravando {caminho_saida}...")
    df_saida.to_csv(caminho_saida, sep=";", index=False, encoding="utf-8-sig")
    print(f"Arquivo gravado: {caminho_saida} ({len(df_saida):,} linhas).")

    if validar_resultado:
        validar(caminho_saida, len(df_saida))

    if aplicar_harmonizacao:
        caminho_harm = _localizar_planilha_harmonizacao(pasta_trabalho)
        if caminho_harm is not None:
            print(f"\nPlanilha de harmonização encontrada: {caminho_harm.name} — aplicando...")
            # Import tardio para não criar dependência circular quando este
            # módulo é importado só para normalizar (sem harmonizar.py em uso).
            import harmonizar_descricoes

            harmonizar_descricoes.harmonizar(
                str(pasta_trabalho), caminho_harm.name, caminho_saida.name, dry_run=False,
            )
        else:
            print("\nNenhuma planilha de harmonização encontrada (harm.xlsx) - "
                  "mantendo a descrição bruta do catálogo de produtos.")

    # Bases do relatório Liquidez (estoque + vendas) — mesmo BI, pasta trabalho.
    try:
        from normalizar_liquidez import normalizar_liquidez_pasta
        normalizar_liquidez_pasta(pasta_fonte, pasta_trabalho)
    except Exception as exc:
        # Não impede o Base.csv; Liquidez falha de forma explícita no log.
        print(f"[AVISO] Falha ao gerar bases Liquidez: {exc}")

    return caminho_saida


def _localizar_planilha_harmonizacao(pasta_trabalho: Path) -> Path | None:
    for nome in (NOME_ARQUIVO_HARM_PADRAO, "harm.xls"):
        candidato = pasta_trabalho / nome
        if candidato.exists():
            return candidato
    return None


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Normaliza os exports de movimento/produto (BI/) de uma empresa em Base.csv."
    )
    parser.add_argument("pasta_fonte", help="Pasta da empresa com BI/ (somente leitura)")
    parser.add_argument(
        "--trabalho",
        required=True,
        help="Pasta de escrita distinta da fonte (Base.csv, harm.xlsx). Obrigatória.",
    )
    parser.add_argument("--sem-harmonizacao", action="store_true",
                        help="Não aplica harm.xlsx automaticamente, mesmo que exista")
    parser.add_argument("--sem-validacao", action="store_true",
                        help="Pula a validação do CSV gerado (leitura de volta)")
    args = parser.parse_args()

    try:
        normalizar_pasta_empresa(
            Path(args.pasta_fonte),
            pasta_trabalho=Path(args.trabalho),
            aplicar_harmonizacao=not args.sem_harmonizacao,
            validar_resultado=not args.sem_validacao,
        )
    except ErroNormalizacao as exc:
        print(f"ERRO: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        main()
