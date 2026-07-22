"""
normalizar_base.py
===================

Script generalista de normalização de dados de empresas: lê os 3 CSVs
exportados pelo PDV/ERP para a pasta da empresa na fonte —

    Dados_Atacado_<empresa>.csv   (arquivo base — vendas já agregadas)
    Dados_Estoque_<empresa>.csv
    Dados_Vendas_<empresa>.csv

— e gera o `Base.csv` no schema que o motor de análise do projeto
(`backend/engine/analise_funil.py`, função `carregar_csv`) já espera:

    Loja;NOME_FABRICANTE;Cliente;descricao;Ano;Mês;Código Interno;
    Código de referêcia;Receita Acumulada 11 Meses;QTD

Layout de pastas — dois papéis (pastas distintas):

    <pasta_fonte>/                         (somente leitura)
        <nome>/
            Dados_Atacado_<nome>.<ext>
            Dados_Estoque_<nome>.<ext>
            Dados_Vendas_<nome>.<ext>

    <pasta_trabalho>/                      (escrita: Base.csv, harm, backups)
        harm.xlsx                          (opcional, aplicado automaticamente)
        Base.csv                           (gerado por este script)

A fonte nunca recebe escrita. `--trabalho` é obrigatório no CLI.

Onde `<nome>` é o nome da pasta da empresa (ex.: pasta "teste" -> arquivo
"Dados_Atacado_teste.csv") e `<ext>` pode variar (`.csv` é o esperado, mas a
busca é case-insensitive e não fixa a extensão).

A ordem das colunas em cada CSV pode variar de empresa para empresa — os
nomes de coluna, não. A leitura é sempre por nome, nunca por posição.

Uso via linha de comando:
    python normalizar_base.py "C:/fonte/teste" --trabalho "C:/trabalho/teste"
    python normalizar_base.py "C:/fonte/teste" --trabalho "C:/trabalho/teste" --sem-harmonizacao
    python normalizar_base.py "C:/fonte/teste" --trabalho "C:/trabalho/teste" --sem-validacao

Uso programático (ex.: backend/main.py, ao selecionar a empresa no dash):
    from normalizar_base import normalizar_pasta_empresa
    caminho_base_csv = normalizar_pasta_empresa(
        Path("fonte/teste"), pasta_trabalho=Path("trabalho/teste"),
    )

DECISÕES DE NEGÓCIO ASSUMIDAS (revisar/ajustar se necessário)
---------------------------------------------------------------------------
1. O arquivo Atacado já vem pré-agregado por (Loja, Fabricante, Cliente,
   Produto, Ano, Mês) — diferente do antigo export bruto de movimento, não
   há mais join com catálogo de produto nem filtro de tipo de movimento
   (VENDA/DEVOLUCAO/MOV) a fazer aqui: é leitura + validação de colunas +
   renomeação para o schema canônico.

2. Números (Receita, QTD) podem vir em formato BR (vírgula decimal) ou com
   ponto decimal — o formato exato ainda não estava confirmado quando este
   script foi escrito, então o parser (`parse_numero_flexivel`) decide por
   valor, olhando qual separador aparece mais à direita no texto.

3. JANELA DE ANÁLISE: somente o ano ATUAL e o ano ANTERIOR (relativos ao
   momento em que o script é executado) entram no CSV final — mesma regra
   de negócio do formato antigo, mantida por consistência com o resto da
   aplicação (filtros de período, etc.), não por limitação da fonte.

4. Linhas cuja soma líquida de QTD e Receita, dentro do agrupamento final,
   dá exatamente zero são DESCARTADAS do CSV final - só para não poluir a
   base com ruído que não representa nem receita nem volume.

5. HARMONIZAÇÃO AUTOMÁTICA: se existir `harm.xlsx` (ou `.xls`) na pasta de
   trabalho, `normalizar_pasta_empresa` aplica `harmonizar_descricoes.py`
   automaticamente sobre o Base.csv recém-gerado, substituindo a descrição
   bruta do catálogo pela descrição harmonizada. Sem a planilha, a
   `descricao` fica com o texto bruto vindo do arquivo Atacado. A planilha
   e o backup `Base.antes-harm.csv` ficam sempre na pasta de trabalho.
"""

from __future__ import annotations

import argparse
import os
import sys
import warnings
from datetime import date
from pathlib import Path

import pandas as pd

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

NOME_ARQUIVO_HARM_PADRAO = "harm.xlsx"

# Colunas esperadas em Dados_Atacado_<empresa>.csv (nomes fixos; ordem livre).
COLUNAS_ATACADO_ESPERADAS = {
    "Loja", "NOME_FABRICANTE", "NOME_CLIENTE", "descricao", "Ano", "Mês",
    "CODIGO_INTERNO_PRODUTO", "CODIGO_REFERENCIA_PRODUTO",
    "Receita Acumulada 11 Meses", "QTD",
}

RENAME_ATACADO = {
    "NOME_CLIENTE": "Cliente",
    "CODIGO_INTERNO_PRODUTO": "Código Interno",
    "CODIGO_REFERENCIA_PRODUTO": "Código de referêcia",
}


class ErroNormalizacao(Exception):
    """Erro amigável quando os arquivos de origem não são encontrados ou são inválidos."""
    pass


def ler_csv_robusto(filepath_or_buffer, **kwargs):
    """Tenta ler com utf-8-sig. Se der erro de Unicode, tenta com latin1."""
    kwargs.pop("encoding", None)  # Remove se foi passado para forçar o nosso fallback
    try:
        return pd.read_csv(filepath_or_buffer, encoding="utf-8-sig", **kwargs)
    except UnicodeDecodeError:
        return pd.read_csv(filepath_or_buffer, encoding="latin1", **kwargs)


# ---------------------------------------------------------------------------
# Localização dos 3 arquivos de origem na pasta da empresa
# ---------------------------------------------------------------------------

def resolver_arquivos_dados(pasta_empresa: Path) -> tuple[Path, Path, Path]:
    """Localiza (Atacado, Estoque, Vendas) em <pasta_empresa>.

    Um único `iterdir()` sobre a pasta, casando os três prefixos por nome
    (sem extensão) - comparação case-insensitive, extensão livre (.csv etc.).
    Levanta ErroNormalizacao com mensagem amigável se algum dos três não for
    encontrado.
    """
    nome_empresa = pasta_empresa.name
    alvos = {
        f"dados_atacado_{nome_empresa}".lower(): "atacado",
        f"dados_estoque_{nome_empresa}".lower(): "estoque",
        f"dados_vendas_{nome_empresa}".lower(): "vendas",
    }
    encontrados: dict[str, Path] = {}
    if pasta_empresa.is_dir():
        for arquivo in pasta_empresa.iterdir():
            if not arquivo.is_file():
                continue
            papel = alvos.get(arquivo.stem.lower())
            if papel is not None:
                encontrados[papel] = arquivo

    caminho_atacado = encontrados.get("atacado")
    caminho_estoque = encontrados.get("estoque")
    caminho_vendas = encontrados.get("vendas")

    faltando = []
    if caminho_atacado is None:
        faltando.append(f"Dados_Atacado_{nome_empresa}")
    if caminho_estoque is None:
        faltando.append(f"Dados_Estoque_{nome_empresa}")
    if caminho_vendas is None:
        faltando.append(f"Dados_Vendas_{nome_empresa}")
    if faltando:
        raise ErroNormalizacao(
            f"Não foi possível localizar em {pasta_empresa}: " + ", ".join(faltando) + "."
        )

    return caminho_atacado, caminho_estoque, caminho_vendas


# ---------------------------------------------------------------------------
# Parsing numérico flexível (formato do CSV novo ainda não 100% confirmado)
# ---------------------------------------------------------------------------

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


def normalizar_mes(serie: pd.Series) -> pd.Series:
    """Aceita Mês como número (1-12) ou já por extenso em PT-BR; sempre
    devolve o nome por extenso (o que `carregar_csv` espera)."""
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


def formatar_receita(valor: float) -> str:
    """Receita em formato BR (vírgula decimal), sem separador de milhar."""
    if pd.isna(valor):
        valor = 0.0
    return f"{float(valor):.2f}".replace(".", ",")


def validar_colunas(df: pd.DataFrame, esperadas: set[str], nome_arquivo: str) -> None:
    """Levanta ErroNormalizacao se alguma coluna de `esperadas` não estiver em `df`."""
    faltando = sorted(esperadas - set(df.columns))
    if faltando:
        raise ErroNormalizacao(f"Arquivo {nome_arquivo} sem colunas: {', '.join(faltando)}.")


def _pct_vazio(serie: pd.Series) -> float:
    if serie.empty:
        return 100.0
    texto = serie.astype(str).str.strip()
    vazios = serie.isna() | texto.isin(("", "nan", "None", "<NA>"))
    return float(vazios.mean() * 100)


# ---------------------------------------------------------------------------
# Normalização (Dados_Atacado -> DataFrame no schema do Base.csv)
# ---------------------------------------------------------------------------

def normalizar(caminho_atacado: Path) -> pd.DataFrame:
    """Lê Dados_Atacado_<empresa>.csv e retorna o DataFrame final já formatado."""
    ano_atual = date.today().year
    anos_permitidos = (ano_atual - 1, ano_atual)

    print(f"Lendo {caminho_atacado.name}...")
    df = ler_csv_robusto(caminho_atacado, sep=";", quotechar='"', dtype=str)

    validar_colunas(df, COLUNAS_ATACADO_ESPERADAS, caminho_atacado.name)

    df = df.rename(columns=RENAME_ATACADO)

    for col in ("Loja", "NOME_FABRICANTE", "Cliente", "descricao",
                "Código Interno", "Código de referêcia"):
        df[col] = serie_texto_limpa(df[col])

    df["Ano"] = pd.to_numeric(serie_texto_limpa(df["Ano"]), errors="coerce")
    df["Mês"] = normalizar_mes(df["Mês"])
    df["Receita"] = parse_numero_flexivel(df["Receita Acumulada 11 Meses"]).fillna(0.0)
    df["QTD"] = parse_numero_flexivel(df["QTD"]).fillna(0.0)

    antes = len(df)
    df = df.dropna(subset=["Ano", "Mês"])
    if antes - len(df):
        print(f"  [AVISO] {antes - len(df):,} linha(s) descartada(s) por Ano/Mês inválido.")

    df["Ano"] = df["Ano"].astype(int)
    df = df[df["Ano"].isin(anos_permitidos)]
    if df.empty:
        raise ErroNormalizacao(
            f"Nenhuma linha para os anos {anos_permitidos[0]} ou {anos_permitidos[1]} "
            f"em {caminho_atacado.name}."
        )

    agregado = (
        df.groupby(COLUNAS_GRUPO, dropna=False, as_index=False)
        .agg(Receita=("Receita", "sum"), QTD=("QTD", "sum"))
    )

    antes = len(agregado)
    mascara_zero = (agregado["Receita"].round(2) == 0) & (agregado["QTD"].round(4) == 0)
    agregado = agregado[~mascara_zero].copy()
    descartadas = antes - len(agregado)
    print(f"Agrupamentos: {antes:,} -> {len(agregado):,} "
          f"({descartadas:,} descartados por receita e quantidade líquidas = 0).")

    for col in ("Cliente", "NOME_FABRICANTE", "descricao", "Código de referêcia"):
        pct = _pct_vazio(agregado[col])
        nuniq = int(agregado[col].nunique(dropna=True))
        marca = " [ATENÇÃO]" if pct >= 95 else ""
        print(f"  {col}: {pct:.1f}% vazio | {nuniq:,} distintos{marca}")

    agregado["QTD"] = agregado["QTD"].apply(formatar_qtd)
    agregado["Receita Acumulada 11 Meses"] = agregado["Receita"].apply(formatar_receita)

    return agregado[COLUNAS_SAIDA]


MARCADOR_NAO_HARMONIZADO = "NÃO HARMONIZADO"


def _eh_descricao_nao_harmonizada(serie_descricao: pd.Series) -> pd.Series:
    """True onde `descricao` é o marcador "NÃO HARMONIZADO" da fonte (comparação
    tolerante a maiúsculas/acentos/espaço nas pontas)."""
    normalizado = (
        serie_descricao.fillna("").astype(str).str.strip().str.upper()
        .str.normalize("NFKD").str.encode("ascii", "ignore").str.decode("ascii")
    )
    return normalizado == "NAO HARMONIZADO"


def aplicar_harmonizacao_em_memoria(df: pd.DataFrame, pasta_trabalho: Path) -> pd.DataFrame:
    """Corrige, em memória, só as linhas marcadas como "NÃO HARMONIZADO" pela fonte.

    A base já vem harmonizada por padrão (a fonte faz isso) — harm.xlsx aqui é só um
    ajuste pontual por "Código Interno" para as linhas que a fonte não conseguiu
    harmonizar sozinha. Sem harm.xlsx na pasta de trabalho, ou sem código com match na
    planilha, a linha fica como veio (com o marcador). Nenhum CSV é lido/escrito em
    disco — é o mesmo dicionário {codigo: descricao} de `harmonizar_descricoes`."""
    caminho_harm = _localizar_planilha_harmonizacao(Path(pasta_trabalho))
    if caminho_harm is None:
        return df

    alvo = _eh_descricao_nao_harmonizada(df["descricao"])
    if not alvo.any():
        return df

    import harmonizar_descricoes

    mapa = harmonizar_descricoes.carregar_harmonizacao(str(caminho_harm))
    df = df.copy()
    codigos = df.loc[alvo, "Código Interno"].astype(str).str.strip()
    harmonizadas = codigos.map(mapa)
    df.loc[alvo, "descricao"] = harmonizadas.where(harmonizadas.notna(), df.loc[alvo, "descricao"])
    return df


def validar(caminho_saida: Path, total_linhas_gravadas: int) -> None:
    """Sanity check leve do resultado gravado: leitura de volta e tipos.

    Não tenta importar backend/engine aqui (evita acoplamento de sys.path
    quando chamado programaticamente pelo próprio backend, que já tem esse
    módulo importado) - só confere se o CSV é reabrível e consistente.
    """
    print("\n" + "=" * 70)
    print("VALIDAÇÃO")
    print("=" * 70)

    relido = ler_csv_robusto(caminho_saida, sep=";")
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
    for col in ("Cliente", "NOME_FABRICANTE", "descricao", "Código de referêcia"):
        pct = _pct_vazio(relido[col])
        print(f"  {col}: {pct:.1f}% vazio | {relido[col].nunique(dropna=True):,} distintos")


# ---------------------------------------------------------------------------
# Orquestração: pasta da empresa -> Base.csv (+ harmonização automática)
# ---------------------------------------------------------------------------

def normalizar_pasta_empresa(
    pasta_fonte: Path,
    pasta_trabalho: Path | None = None,
    aplicar_harmonizacao: bool = True,
    validar_resultado: bool = True,
) -> Path:
    """Lê os 3 CSVs em `pasta_fonte` e gera `Base.csv` em `pasta_trabalho`.

    `pasta_trabalho` é obrigatória e deve ser distinta da fonte (e não pode
    estar dentro dela). A fonte é somente leitura — este módulo nunca grava
    sob `pasta_fonte`.

    Se `aplicar_harmonizacao` for True e existir harm.xlsx/harm.xls na pasta
    de trabalho, aplica `harmonizar_descricoes.harmonizar` sobre o Base.csv
    (decisão de negócio 5). Backup e planilha ficam só no trabalho.

    Retorna o caminho do Base.csv gerado.
    """
    pasta_fonte = Path(pasta_fonte).resolve()
    if pasta_trabalho is None:
        raise ErroNormalizacao(
            "pasta_trabalho é obrigatória. A pasta fonte é somente leitura — "
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

    caminho_atacado, _caminho_estoque, _caminho_vendas = resolver_arquivos_dados(pasta_fonte)

    df_saida = normalizar(caminho_atacado)

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

    # Bases do relatório Liquidez (estoque + vendas) — mesma fonte, pasta trabalho.
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
        description="Normaliza os CSVs (Atacado/Estoque/Vendas) de uma empresa em Base.csv."
    )
    parser.add_argument("pasta_fonte", help="Pasta da empresa com os 3 CSVs (somente leitura)")
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
