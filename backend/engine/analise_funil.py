"""
Motor de análise do funil de vendas B2B.

Sem dependência de GUI - pode ser testado isoladamente via linha de comando
ou testes automatizados. Todas as funções recebem/retornam DataFrames do pandas.
"""

import unicodedata

import pandas as pd
import numpy as np

# ---------------------------------------------------------------------------
# Constantes de domínio
# ---------------------------------------------------------------------------

import re

REGEX_BALCAO = re.compile(
    r"(?i)(?:cliente sem cadastro|cliente final|venda externa|consumidor.*|.*balc[aã]o.*)"
)

TAG_CLIENTE_BALCAO = "cliente_balcao"
TAGS_CLIENTE_VALIDAS = frozenset({"inadimplente", "cliente_balcao", "encerrou_operacao"})


def mascara_clientes_balcao(serie_clientes, clientes_balcao_extra=None):
    """True onde o nome casa REGEX_BALCAO OU está na lista explícita (tags da empresa).

    A lista extras só é aplicada quando o caller liga desconsiderar_balcao —
    a tag apenas cadastra o nome; o checkbox decide se o filtro roda.
    """
    mascara = serie_clientes.astype(str).str.contains(REGEX_BALCAO, na=False)
    extras = [nome for nome in (clientes_balcao_extra or []) if nome]
    if extras:
        mascara = mascara | serie_clientes.isin(extras)
    return mascara


MESES_PT = {
    "janeiro": 1, "fevereiro": 2, "março": 3, "marco": 3, "abril": 4,
    "maio": 5, "junho": 6, "julho": 7, "agosto": 8, "setembro": 9,
    "outubro": 10, "novembro": 11, "dezembro": 12,
}

COLUNAS_OBRIGATORIAS = [
    "Loja", "NOME_FABRICANTE", "Cliente", "descricao", "Ano", "Mês",
    "Código Interno", "Código de referêcia", "Receita Acumulada 11 Meses", "QTD",
]

# Mapeia os nomes de coluna do base_de_dados.xlsx (export do Power BI/Excel,
# com o padrão Tabela[Coluna]) para o schema canônico usado pelo motor de
# análise (o mesmo schema do CSV do app desktop original).
MAPA_COLUNAS_BASE_PADRAO = {
    "Nome_Loja[Loja]": "Loja",
    "PRODUTO[NOME_FABRICANTE]": "NOME_FABRICANTE",
    "MOVIMENTO[NOME_CLIENTE]": "Cliente",
    "GABARITO HARM[descricao]": "descricao",
    "Dcalendario[Ano]": "Ano",
    "Dcalendario[Mês]": "Mês",
    "PRODUTO[CODIGO_INTERNO_PRODUTO]": "Código Interno",
    "PRODUTO[CODIGO_REFERENCIA_PRODUTO]": "Código de referêcia",
    "[Receita_Líquida]": "Receita Acumulada 11 Meses",
    "[QTD]": "QTD",
}

# O arquivo por empresa já chega pronto para leitura, mas usa nomes de
# exportação próprios. O mapeamento acontece em memória; a fonte nunca recebe
# escrita nem arquivo intermediário.
MAPA_COLUNAS_BASE_EMPRESA = {
    "ID_LOJA": "Loja",
    "NOME_CLIENTE": "Cliente",
    "DESCRICAO_PRODUTO": "descricao",
    "ANO": "Ano",
    "MÊS": "Mês",
    "CODIGO_INTERNO_PRODUTO": "Código Interno",
    "CODIGO_REFERENCIA_PRODUTO": "Código de referêcia",
    "NOME_FABRICANTE": "NOME_FABRICANTE",
    "Receita Acumulada 11 Meses": "Receita Acumulada 11 Meses",
    "QTD": "QTD",
}

GRANULARIDADES = ["Mensal", "Trimestral", "Semestral", "Anual"]

DESCRICAO_NAO_HARMONIZADA = "Não harmonizados"


class ErroCarregamentoCSV(Exception):
    """Erro amigável para falhas ao carregar/validar o CSV de vendas."""
    pass


def mapa_cliente_para_grupo_manual(grupos_manuais):
    """Cliente -> nome do grupo. Em sobreposição, o primeiro grupo da lista vence."""
    mapa = {}
    for grupo in grupos_manuais or []:
        if not isinstance(grupo, dict):
            continue
        nome = str(grupo.get("nome") or "").strip()
        if not nome:
            continue
        for cliente in grupo.get("clientes") or []:
            chave = str(cliente).strip()
            if chave and chave not in mapa:
                mapa[chave] = nome
    return mapa


def aplicar_grupos_manuais_em_cliente(df, grupos_manuais):
    """Substitui Cliente pelo nome do grupo manual (agrega membros no concentrado/ABC).

    Clientes fora de qualquer grupo permanecem individuais. Retorna cópia só
    quando há mapeamento; caso contrário devolve o mesmo DataFrame.
    """
    mapa = mapa_cliente_para_grupo_manual(grupos_manuais)
    if not mapa or df is None or df.empty or "Cliente" not in df.columns:
        return df
    out = df.copy()
    # replace vetorizado (sem lambda por linha) + strip para casar com o mapa
    out["Cliente"] = out["Cliente"].astype(str).str.strip().replace(mapa)
    return out


# ---------------------------------------------------------------------------
# Carregamento e limpeza
# ---------------------------------------------------------------------------

def carregar_csv(caminho_arquivo):
    """
    Carrega o CSV de vendas, valida colunas obrigatórias, trata nulos,
    converte a receita (formato BR com vírgula) e constrói a coluna Data_Venda.

    Retorna um DataFrame limpo e pronto para análise.
    """
    try:
        df = pd.read_csv(caminho_arquivo, sep=";", encoding="utf-8-sig")
    except Exception as exc:
        raise ErroCarregamentoCSV(f"Não foi possível ler o arquivo CSV: {exc}") from exc

    # No CSV a receita vem em formato BR (vírgula decimal, ponto de milhar),
    # ex: "1.234,56" — diferente do Excel padrão, onde a coluna já é numérica.
    return validar_e_limpar(df, receita_em_texto_br=True)


def carregar_excel_base(caminho_arquivo):
    """
    Carrega a base padrão (base_de_dados.xlsx na raiz do projeto), no formato
    de export do Power BI/Excel (colunas "Tabela[Coluna]"), remapeia os nomes
    para o schema canônico e aplica a mesma limpeza usada pelo CSV.

    Retorna um DataFrame limpo e pronto para análise.
    """
    try:
        df = pd.read_excel(caminho_arquivo, usecols=list(MAPA_COLUNAS_BASE_PADRAO.keys()))
    except Exception as exc:
        raise ErroCarregamentoCSV(f"Não foi possível ler a base de dados: {exc}") from exc

    df = df.rename(columns=MAPA_COLUNAS_BASE_PADRAO)

    # A receita nesta base já vem numérica (float), não precisa da conversão
    # de formato BR usada no CSV.
    return validar_e_limpar(df, receita_em_texto_br=False)


def _normalizar_numero_excel(serie):
    """Converte número Excel ou texto BR sem perder células numéricas."""
    if pd.api.types.is_numeric_dtype(serie):
        return pd.to_numeric(serie, errors="coerce")

    texto = serie.astype(str).str.strip()
    tem_virgula = texto.str.contains(",", regex=False)
    tem_ponto = texto.str.contains(".", regex=False)
    virgula_decimal = tem_virgula & (~tem_ponto | (texto.str.rfind(",") > texto.str.rfind(".")))
    convertido = texto.copy()
    convertido = convertido.mask(
        virgula_decimal,
        texto.str.replace(".", "", regex=False).str.replace(",", ".", regex=False),
    )
    convertido = convertido.mask(
        ~virgula_decimal,
        texto.str.replace(",", "", regex=False),
    )
    return pd.to_numeric(convertido, errors="coerce")


def carregar_excel_base_empresa(caminho_arquivo):
    """Lê ``Dados Mais Atacado.xlsx`` no schema pronto da empresa.

    Identificadores são lidos como texto para preservar zeros à esquerda.
    Receita e QTD aceitam células numéricas do Excel e texto decimal BR.
    Retorna o DataFrame bruto já com nomes canônicos; a validação final fica
    em ``validar_e_limpar`` no backend.
    """
    tipos_texto = {
        "ID_LOJA": str,
        "NOME_CLIENTE": str,
        "DESCRICAO_PRODUTO": str,
        "CODIGO_INTERNO_PRODUTO": str,
        "CODIGO_REFERENCIA_PRODUTO": str,
        "NOME_FABRICANTE": str,
    }
    try:
        df = pd.read_excel(caminho_arquivo, sheet_name=0, dtype=tipos_texto)
    except Exception as exc:
        raise ErroCarregamentoCSV(
            f"Não foi possível ler Dados Mais Atacado.xlsx: {exc}"
        ) from exc

    colunas_faltando = [c for c in MAPA_COLUNAS_BASE_EMPRESA if c not in df.columns]
    if colunas_faltando:
        raise ErroCarregamentoCSV(
            "Dados Mais Atacado.xlsx sem colunas: " + ", ".join(colunas_faltando)
        )

    df = df.rename(columns=MAPA_COLUNAS_BASE_EMPRESA)
    df["Receita Acumulada 11 Meses"] = _normalizar_numero_excel(
        df["Receita Acumulada 11 Meses"]
    )
    df["QTD"] = _normalizar_numero_excel(df["QTD"])
    return df


def validar_e_limpar(df, receita_em_texto_br):
    """Validação de colunas e limpeza compartilhada entre carregar_csv, carregar_excel_base
    e qualquer chamador que já tenha um DataFrame em memória no schema canônico (ex.:
    backend/main.py, ao ler a base direto da fonte sem passar por um CSV em disco)."""
    colunas_faltando = [c for c in COLUNAS_OBRIGATORIAS if c not in df.columns]
    if colunas_faltando:
        raise ErroCarregamentoCSV(
            "A base não tem as colunas esperadas. Faltando: "
            + ", ".join(colunas_faltando)
        )

    df = df.copy()

    # Descarta linhas com Ano ou Mês vazio (comuns em exports com uma linha
    # em branco no final) — contadas para avisar o usuário, em vez de
    # virarem "Mês" == NaN e quebrar a validação abaixo.
    linhas_antes = len(df)
    df = df.dropna(subset=["Ano", "Mês"])
    linhas_vazias = linhas_antes - len(df)

    # Tratamento de nulos em texto. Produtos sem descrição ficam agrupados sob
    # um rótulo próprio ("Não harmonizados") para que o usuário decida, na
    # interface, se quer considerá-los na análise ou não.
    # Strip em Cliente/descrição evita chaves divergentes nas tags (ex.:
    # "MARCIO GONCALVES " na prévia vs "MARCIO GONCALVES" no clientes_tags.json).
    df["NOME_FABRICANTE"] = df["NOME_FABRICANTE"].fillna("Não informado").astype(str).str.strip()
    df["Cliente"] = df["Cliente"].fillna("Não informado").astype(str).str.strip()
    df["descricao"] = df["descricao"].fillna(DESCRICAO_NAO_HARMONIZADA).astype(str).str.strip()
    df["Código de referêcia"] = df["Código de referêcia"].fillna("").astype(str).str.strip()
    df.loc[df["Cliente"] == "", "Cliente"] = "Não informado"
    df.loc[df["descricao"] == "", "descricao"] = DESCRICAO_NAO_HARMONIZADA

    if receita_em_texto_br:
        # Conversão da receita: formato BR com vírgula decimal.
        # CRÍTICO: usar .str.replace(',', '.') antes de to_numeric, senão
        # valores com centavos (ex: "33,65") viram 0 silenciosamente.
        receita_texto = df["Receita Acumulada 11 Meses"].astype(str).str.strip()
        receita_texto = receita_texto.str.replace(".", "", regex=False)  # milhar, se houver
        receita_texto = receita_texto.str.replace(",", ".", regex=False)
        df["Receita"] = pd.to_numeric(receita_texto, errors="coerce").fillna(0.0)
    else:
        df["Receita"] = pd.to_numeric(df["Receita Acumulada 11 Meses"], errors="coerce").fillna(0.0)

    df["QTD"] = pd.to_numeric(df["QTD"], errors="coerce").fillna(0).astype(int)

    # Ano pode vir como texto, float ("2024.0") ou com ruído — normaliza antes
    # de usar em pd.to_datetime, senão um valor inesperado quebra com um erro
    # genérico do pandas (sem mensagem amigável pro usuário).
    df["_ano_num"] = pd.to_numeric(df["Ano"], errors="coerce")
    if df["_ano_num"].isnull().any():
        anos_invalidos = df.loc[df["_ano_num"].isnull(), "Ano"].unique()
        raise ErroCarregamentoCSV(
            "Valores de Ano não reconhecidos: " + ", ".join(map(str, anos_invalidos))
        )

    # Construção da Data_Venda a partir de Ano + Mês (nome por extenso em PT-BR)
    mes_normalizado = (
        df["Mês"].astype(str).str.strip().str.lower()
        .str.replace("é", "e").str.replace("ê", "e")
    )
    df["_mes_num"] = mes_normalizado.map(MESES_PT)
    if df["_mes_num"].isnull().any():
        meses_invalidos = df.loc[df["_mes_num"].isnull(), "Mês"].unique()
        raise ErroCarregamentoCSV(
            "Valores de mês não reconhecidos: " + ", ".join(map(str, meses_invalidos))
        )

    try:
        df["Data_Venda"] = pd.to_datetime(
            dict(year=df["_ano_num"].astype(int), month=df["_mes_num"].astype(int), day=1)
        )
    except Exception as exc:
        raise ErroCarregamentoCSV(f"Não foi possível montar as datas de venda: {exc}") from exc
    df.drop(columns=["_ano_num", "_mes_num"], inplace=True)

    # Campos de período (calculados) para todas as granularidades
    df["Periodo_Mensal"] = df["Data_Venda"].dt.to_period("M").astype(str)
    df["Periodo_Trimestral"] = (
        df["Data_Venda"].dt.year.astype(str) + "-T" + df["Data_Venda"].dt.quarter.astype(str)
    )
    semestre = np.where(df["Data_Venda"].dt.month <= 6, 1, 2)
    df["Periodo_Semestral"] = df["Data_Venda"].dt.year.astype(str) + "-S" + semestre.astype(str)
    df["Periodo_Anual"] = df["Data_Venda"].dt.year.astype(str)

    return df, linhas_vazias


def contar_produtos_nao_harmonizados(df):
    """Quantidade de linhas cujo produto não tinha descrição no CSV original."""
    return int((df["descricao"] == DESCRICAO_NAO_HARMONIZADA).sum())


def eh_produto_nao_harmonizado(nome):
    """Produto sem descrição harmonizada.

    Critério por texto normalizado (sem acento, minúsculo) contendo
    "harmonizad": além do rótulo que o próprio motor cria para descrição vazia
    ("Não harmonizados"), a fonte manda variações próprias — "NÃO HARMONIZADO",
    "Nao Harmonizados" etc. Fonte única desta regra: o backend e o frontend
    espelham este mesmo critério.
    """
    normalizado = unicodedata.normalize("NFD", str(nome))
    sem_acento = "".join(c for c in normalizado if unicodedata.category(c) != "Mn")
    return "harmonizad" in sem_acento.lower()


def mascara_produtos_nao_harmonizados(serie_descricao):
    """Versão vetorizada de `eh_produto_nao_harmonizado` para uma coluna inteira."""
    return (
        serie_descricao.astype(str)
        .str.normalize("NFD")
        .str.encode("ascii", "ignore")
        .str.decode("ascii")
        .str.lower()
        .str.contains("harmonizad", na=False)
    )


COLUNA_PERIODO = {
    "Mensal": "Periodo_Mensal",
    "Trimestral": "Periodo_Trimestral",
    "Semestral": "Periodo_Semestral",
    "Anual": "Periodo_Anual",
}

MESES_ABREV = {
    1: "jan", 2: "fev", 3: "mar", 4: "abr", 5: "mai", 6: "jun",
    7: "jul", 8: "ago", 9: "set", 10: "out", 11: "nov", 12: "dez",
}


def _formatar_rotulo_periodo(periodo, granularidade):
    """
    Rótulo legível de um período para exibição em relatórios (não usado para
    ordenação/agrupamento — isso continua sendo feito com o valor original de
    Periodo, via _ordenar_periodos/COLUNA_PERIODO).

    Mensal "2025-08" -> "ago/25" | Trimestral "2025-T3" -> "T3/25"
    Semestral "2025-S1" -> "S1/25" | Anual "2025" -> "2025"
    """
    if granularidade == "Mensal":
        ano, mes = periodo.split("-")
        return f"{MESES_ABREV[int(mes)]}/{ano[-2:]}"
    if granularidade == "Trimestral":
        ano, tri = periodo.split("-T")
        return f"T{tri}/{ano[-2:]}"
    if granularidade == "Semestral":
        ano, sem = periodo.split("-S")
        return f"S{sem}/{ano[-2:]}"
    return periodo  # Anual: já é só o ano


COLUNAS_ALERTAS_QUEDA = [
    "descricao", "Periodos_Consecutivos_Em_Queda",
    "Receita_Ultimo_Periodo", "Receita_Primeiro_Periodo",
]


def _completar_periodos_sem_venda(agregado, campo, periodos_ordenados):
    """Preenche com 0 os períodos sem venda de cada entidade, da 1ª venda em diante.

    Sem isso o `shift(1)` compara com o período anterior *em que houve venda* —
    então um mês zerado no meio desaparece e dois períodos distantes viram
    "consecutivos". Só completa a partir da primeira venda de cada entidade:
    preencher antes disso inventaria queda em produto/cliente novo.

    Espera `agregado` com as colunas `campo`, "Periodo", "_ordem", "Receita" e
    "QTD"; devolve o mesmo formato, já com as linhas faltantes zeradas.
    """
    if agregado.empty:
        return agregado

    primeiro = agregado.groupby(campo)["_ordem"].min()
    grade = pd.MultiIndex.from_product(
        [primeiro.index, range(len(periodos_ordenados))], names=[campo, "_ordem"],
    ).to_frame(index=False)
    grade = grade[grade["_ordem"] >= grade[campo].map(primeiro)]

    completo = grade.merge(agregado.drop(columns=["Periodo"]), on=[campo, "_ordem"], how="left")
    colunas_valor = [c for c in ("Receita", "QTD") if c in completo.columns]
    completo[colunas_valor] = completo[colunas_valor].fillna(0)
    completo["Periodo"] = completo["_ordem"].map(dict(enumerate(periodos_ordenados)))
    return completo[list(agregado.columns)]


def _ordenar_periodos(periodos, granularidade):
    """Ordena rótulos de período (strings) na ordem cronológica correta."""
    def chave(p):
        if granularidade == "Mensal":
            return p  # "YYYY-MM" já ordena lexicograficamente
        if granularidade == "Trimestral":
            ano, tri = p.split("-T")
            return (int(ano), int(tri))
        if granularidade == "Semestral":
            ano, sem = p.split("-S")
            return (int(ano), int(sem))
        return (int(p),)  # Anual
    return sorted(periodos, key=chave)


# ---------------------------------------------------------------------------
# Top produtos e top clientes
# ---------------------------------------------------------------------------

def top_produtos(df, n=20):
    resultado = (
        df.groupby("descricao", as_index=False)
        .agg(Receita=("Receita", "sum"), QTD=("QTD", "sum"))
        .sort_values("Receita", ascending=False)
        .head(n)
        .reset_index(drop=True)
    )
    return resultado


def top_fabricantes(df, n=20):
    resultado = (
        df.groupby("NOME_FABRICANTE", as_index=False)
        .agg(Receita=("Receita", "sum"), QTD=("QTD", "sum"))
        .sort_values("Receita", ascending=False)
        .head(n)
        .reset_index(drop=True)
    )
    return resultado


def poder_compra_agregado(df, clientes_excluidos=None, cortes=(30.0, 50.0, 60.0), desconsiderar_balcao=False, top_n=None,
                          clientes_balcao_extra=None):
    """
    Poder de compra "de pico" de cada cliente: média dos 3 meses-calendário
    de MAIOR receita (não a média corrida, nem o total agregado) — reflete a
    capacidade de compra do cliente no seu melhor momento, não o
    comportamento típico do dia a dia. Sempre por Periodo_Mensal, independente
    da granularidade escolhida na tela (um "pico" é um conceito mensal).

    Grupo e Percentual_Acumulado vêm de classificar_clientes_agregado — ou
    seja, do tamanho do cliente pela receita TOTAL, não pelo poder de compra.
    Decisão deliberada: a segmentação em grupos continua refletindo o
    cliente como um todo; poder de compra é uma métrica complementar, não
    substitui a segmentação por receita.

    Retorna (sem período, uma linha por cliente): Cliente, Poder_De_Compra,
    Percentual_Acumulado, Grupo.
    """
    excluidos = set(clientes_excluidos or [])
    base = df[~df["Cliente"].isin(excluidos)] if excluidos else df

    receita_mensal = base.groupby(["Cliente", "Periodo_Mensal"], as_index=False)["Receita"].sum()
    top3_por_cliente = (
        receita_mensal.sort_values("Receita", ascending=False)
        .groupby("Cliente")["Receita"].apply(lambda serie: serie.head(3).mean())
        .rename("Poder_De_Compra")
    )

    classificacao = classificar_clientes_agregado(
        df, clientes_excluidos, cortes, desconsiderar_balcao,
        clientes_balcao_extra=clientes_balcao_extra,
    )
    resultado = classificacao[["Cliente", "Percentual_Acumulado", "Faixa"]].rename(columns={"Faixa": "Grupo"})
    resultado = resultado.merge(top3_por_cliente, on="Cliente", how="left")
    resultado["Poder_De_Compra"] = resultado["Poder_De_Compra"].fillna(0.0)

    resultado = resultado[["Cliente", "Poder_De_Compra", "Percentual_Acumulado", "Grupo"]]
    resultado.sort_values("Poder_De_Compra", ascending=False, inplace=True)
    if top_n is not None:
        resultado = resultado.head(int(top_n))
    resultado.reset_index(drop=True, inplace=True)
    return resultado


# ---------------------------------------------------------------------------
# Tendência de produtos
# ---------------------------------------------------------------------------

def _tendencia_percentual(receitas_ordenadas):
    """
    Tendência de uma série de receitas (já em ordem cronológica): compara a
    média dos últimos períodos com a média dos primeiros. Usa 3 pontos de
    cada ponta; com menos de 6 pontos ao todo, divide a série ao meio (mínimo
    1 ponto de cada lado) em vez de deixar as duas janelas se sobreporem.

    Preferido a CAGR ponto-a-ponto (1º vs último) porque um único período
    fora da curva em qualquer ponta não distorce o resultado sozinho, e a
    regressão linear (outra opção avaliada) dá um número por período mais
    difícil de explicar num relatório do que "média dos últimos vs primeiros".
    """
    n = len(receitas_ordenadas)
    if n < 2:
        return 0.0
    tamanho_janela = 3 if n >= 6 else max(1, n // 2)
    primeiros = receitas_ordenadas[:tamanho_janela]
    ultimos = receitas_ordenadas[-tamanho_janela:]
    media_primeiros = primeiros.mean()
    media_ultimos = ultimos.mean()
    if media_primeiros == 0:
        return 0.0
    return (media_ultimos / media_primeiros - 1) * 100


def tendencia_produtos(df, granularidade="Mensal", periodos_queda_consecutiva=2, top_n=None,
                       queda_minima_rs=0.0):
    """
    Evolução de receita/quantidade por produto ao longo dos períodos.
    Sinaliza produtos com queda em N períodos consecutivos (parametrizável).

    top_n: se informado, mantém só os N produtos com maior tendência em
    evolucao_df (todos os períodos desses produtos) e as N linhas com maior
    Periodos_Consecutivos_Em_Queda em alertas_df. None = todos os produtos.

    queda_minima_rs: piso em R$ da queda na janela do alerta
    (Receita_Primeiro_Periodo - Receita_Ultimo_Periodo). 0 = sem piso.

    Retorna (evolucao_df, alertas_df):
      - evolucao_df: uma linha por (produto, período), ordenada por tendência
        (Tendencia_Pct) descendente — ver _tendencia_percentual. "Periodo" é
        um rótulo legível (ex.: "ago/25"); a ordem cronológica já foi
        aplicada antes dessa conversão.
      - alertas_df: uma linha por produto em queda AGORA — a sequência de
        quedas precisa terminar no período mais recente (queda atual, não
        um histórico antigo já recuperado). Receita_Primeiro_Periodo/
        Receita_Ultimo_Periodo se referem à janela dessa sequência (o
        período-base antes da primeira queda até o último período), não aos
        extremos de todo o histórico do produto.
    """
    col_periodo = COLUNA_PERIODO[granularidade]
    periodos_ordenados = _ordenar_periodos(df[col_periodo].unique(), granularidade)

    evolucao = (
        df.groupby(["descricao", col_periodo], as_index=False)
        .agg(Receita=("Receita", "sum"), QTD=("QTD", "sum"))
        .rename(columns={col_periodo: "Periodo"})
    )
    ordem_periodo = {p: i for i, p in enumerate(periodos_ordenados)}
    evolucao["_ordem"] = evolucao["Periodo"].map(ordem_periodo)
    evolucao = _completar_periodos_sem_venda(evolucao, "descricao", periodos_ordenados)
    evolucao.sort_values(["descricao", "_ordem"], inplace=True)

    evolucao["Receita_Periodo_Anterior"] = evolucao.groupby("descricao")["Receita"].shift(1)
    # Receita negativa (devoluções/estornos líquidos no mês) quebra a leitura
    # de "queda"/"alta" da variação percentual — período anterior negativo ou
    # zero já não entra no cálculo; período atual negativo também não, pois
    # o percentual resultante não tem leitura de magnitude coerente.
    anterior_valido = evolucao["Receita_Periodo_Anterior"].notnull() & (evolucao["Receita_Periodo_Anterior"] > 0)
    atual_valido = evolucao["Receita"] >= 0
    evolucao["Variacao_Percentual"] = np.where(
        anterior_valido & atual_valido,
        (evolucao["Receita"] - evolucao["Receita_Periodo_Anterior"]) / evolucao["Receita_Periodo_Anterior"] * 100,
        np.nan,
    )
    # "Em queda" para a contagem de períodos consecutivos: queda normal, OU
    # período zerado depois de já ter havido venda. Sem a segunda parte, um
    # produto que morreu (100 -> 0 -> 0 -> 0) contava uma queda só e saía do
    # alerta justamente no caso mais grave — o percentual do 2º zero em diante
    # é indefinido (anterior = 0), mas a queda continua acontecendo.
    houve_venda_antes = (
        evolucao.groupby("descricao")["Receita"].cummax().groupby(evolucao["descricao"]).shift(1) > 0
    )
    evolucao["_em_queda"] = (
        (anterior_valido & atual_valido & (evolucao["Receita"] < evolucao["Receita_Periodo_Anterior"]))
        | ((evolucao["Receita"] == 0) & houve_venda_antes.fillna(False))
    )

    # Detecta queda em N períodos consecutivos terminando no período mais
    # recente (queda atual) e calcula a tendência geral (mesma passada pelos
    # grupos, evita repetir o groupby).
    alertas = []
    tendencia_por_produto = {}
    for produto, grupo in evolucao.groupby("descricao"):
        grupo = grupo.sort_values("_ordem")
        tendencia_por_produto[produto] = _tendencia_percentual(grupo["Receita"].to_numpy())

        quedas_seguidas = 0
        for em_queda in grupo["_em_queda"]:
            quedas_seguidas = quedas_seguidas + 1 if em_queda else 0
        if quedas_seguidas >= periodos_queda_consecutiva:
            janela = grupo.tail(quedas_seguidas + 1)
            alertas.append({
                "descricao": produto,
                "Periodos_Consecutivos_Em_Queda": quedas_seguidas,
                "Receita_Ultimo_Periodo": grupo["Receita"].iloc[-1],
                "Receita_Primeiro_Periodo": janela["Receita"].iloc[0],
            })

    evolucao["Tendencia_Pct"] = evolucao["descricao"].map(tendencia_por_produto)

    if top_n is not None:
        produtos_top = (
            evolucao[["descricao", "Tendencia_Pct"]].drop_duplicates("descricao")
            .sort_values("Tendencia_Pct", ascending=False).head(top_n)["descricao"]
        )
        evolucao = evolucao[evolucao["descricao"].isin(produtos_top)]

    evolucao.sort_values(["Tendencia_Pct", "descricao", "_ordem"], ascending=[False, True, True], inplace=True)
    evolucao["Periodo"] = evolucao["Periodo"].apply(lambda p: _formatar_rotulo_periodo(p, granularidade))
    evolucao.drop(columns=["_ordem", "_em_queda"], inplace=True)
    evolucao.reset_index(drop=True, inplace=True)

    alertas_df = pd.DataFrame(alertas, columns=COLUNAS_ALERTAS_QUEDA)
    if not alertas_df.empty:
        if queda_minima_rs and queda_minima_rs > 0:
            queda_rs = alertas_df["Receita_Primeiro_Periodo"] - alertas_df["Receita_Ultimo_Periodo"]
            alertas_df = alertas_df[queda_rs >= float(queda_minima_rs)]
        alertas_df.sort_values("Periodos_Consecutivos_Em_Queda", ascending=False, inplace=True)
        if top_n is not None:
            alertas_df = alertas_df.head(top_n)
        alertas_df.reset_index(drop=True, inplace=True)

    return evolucao, alertas_df


COLUNAS_COMPARATIVO_RECEITA = [
    "descricao", "Periodo_Ano_Anterior", "Periodo_Ano_Atual",
    "Receita_Ano_Anterior", "Receita_Ano_Atual", "Ganho_Perda",
    "Desempenho_Pct", "Participacao_Ano_Anterior_Pct", "Participacao_Ano_Atual_Pct",
]

ROTULO_TOTAIS = "Totais"


def _periodo_ano_anterior(periodo, granularidade):
    """Mesmo período, um ano antes ("2026-07" -> "2025-07", "2026-T3" -> "2025-T3")."""
    if granularidade == "Mensal":
        ano, mes = periodo.split("-")
        return f"{int(ano) - 1}-{mes}"
    if granularidade == "Trimestral":
        ano, tri = periodo.split("-T")
        return f"{int(ano) - 1}-T{tri}"
    if granularidade == "Semestral":
        ano, sem = periodo.split("-S")
        return f"{int(ano) - 1}-S{sem}"
    return str(int(periodo) - 1)  # Anual


def comparativo_receita_ano_anterior(df, granularidade="Mensal"):
    """Receita por produto no período mais recente vs. o MESMO período do ano anterior.

    O período comparado acompanha a granularidade escolhida: Mensal compara
    jul/26 com jul/25, Trimestral compara T3/26 com T3/25, e assim por diante.

    Produtos sem descrição harmonizada ficam de fora (ver
    `eh_produto_nao_harmonizado`, que cobre as variações que a fonte manda) — o
    relatório é lido produto a produto e um balde genérico distorce tanto o
    ranking quanto a participação.

    Entram os produtos dos DOIS lados (quem não vendeu num deles aparece com 0),
    ordenados pela receita do período atual. A primeira linha é o total.

    Colunas: receita dos dois períodos, ganho/perda em R$, desempenho % e a
    participação de cada produto na receita do seu próprio período.
    Desempenho fica vazio quando não havia receita antes (não existe variação
    percentual a partir de zero).
    """
    col_periodo = COLUNA_PERIODO[granularidade]
    periodos = _ordenar_periodos(df[col_periodo].unique(), granularidade)
    if not periodos:
        return pd.DataFrame(columns=COLUNAS_COMPARATIVO_RECEITA)

    periodo_atual = periodos[-1]
    periodo_anterior = _periodo_ano_anterior(periodo_atual, granularidade)

    base = df[~mascara_produtos_nao_harmonizados(df["descricao"])]
    base = base[base[col_periodo].isin([periodo_anterior, periodo_atual])]

    receita = (
        base.groupby(["descricao", col_periodo])["Receita"].sum()
        .unstack(fill_value=0.0)
        .reindex(columns=[periodo_anterior, periodo_atual], fill_value=0.0)
    )
    if receita.empty:
        return pd.DataFrame(columns=COLUNAS_COMPARATIVO_RECEITA)

    anterior = receita[periodo_anterior]
    atual = receita[periodo_atual]
    total_anterior = float(anterior.sum())
    total_atual = float(atual.sum())

    resultado = pd.DataFrame({
        "descricao": receita.index,
        "Receita_Ano_Anterior": anterior.to_numpy(),
        "Receita_Ano_Atual": atual.to_numpy(),
    })
    resultado["Ganho_Perda"] = resultado["Receita_Ano_Atual"] - resultado["Receita_Ano_Anterior"]
    resultado["Desempenho_Pct"] = np.where(
        resultado["Receita_Ano_Anterior"] > 0,
        resultado["Ganho_Perda"] / resultado["Receita_Ano_Anterior"] * 100,
        np.nan,
    )
    resultado["Participacao_Ano_Anterior_Pct"] = (
        resultado["Receita_Ano_Anterior"] / total_anterior * 100 if total_anterior > 0 else 0.0
    )
    resultado["Participacao_Ano_Atual_Pct"] = (
        resultado["Receita_Ano_Atual"] / total_atual * 100 if total_atual > 0 else 0.0
    )
    resultado.sort_values(
        ["Receita_Ano_Atual", "descricao"], ascending=[False, True], inplace=True,
    )

    totais = pd.DataFrame([{
        "descricao": ROTULO_TOTAIS,
        "Receita_Ano_Anterior": total_anterior,
        "Receita_Ano_Atual": total_atual,
        "Ganho_Perda": total_atual - total_anterior,
        "Desempenho_Pct": (
            (total_atual - total_anterior) / total_anterior * 100 if total_anterior > 0 else np.nan
        ),
        "Participacao_Ano_Anterior_Pct": np.nan,
        "Participacao_Ano_Atual_Pct": np.nan,
    }])

    resultado = pd.concat([totais, resultado], ignore_index=True)
    resultado["Periodo_Ano_Anterior"] = _formatar_rotulo_periodo(periodo_anterior, granularidade)
    resultado["Periodo_Ano_Atual"] = _formatar_rotulo_periodo(periodo_atual, granularidade)
    return resultado[COLUNAS_COMPARATIVO_RECEITA]


def produtos_alta_e_queda(df, granularidade="Mensal", top_n=10):
    """
    Compara os dois períodos mais recentes da granularidade escolhida e monta
    duas listas (estilo "boletim executivo"): produtos em alta e em queda,
    com quantidade período anterior/atual, variação % e total acumulado no
    ano corrente (YTD).
    """
    col_periodo = COLUNA_PERIODO[granularidade]
    periodos_ordenados = _ordenar_periodos(df[col_periodo].unique(), granularidade)
    colunas_vazias = ["descricao", "QTD_Periodo_Anterior", "QTD_Periodo_Atual",
                       "Receita_Periodo_Anterior", "Receita_Periodo_Atual",
                       "Variacao_Percentual", "Total_Ano_Atual"]
    if len(periodos_ordenados) < 2:
        vazio = pd.DataFrame(columns=colunas_vazias)
        return vazio, vazio.copy()

    periodo_anterior, periodo_atual = periodos_ordenados[-2], periodos_ordenados[-1]

    agrupado = (
        df[df[col_periodo].isin([periodo_anterior, periodo_atual])]
        .groupby(["descricao", col_periodo], as_index=False)
        .agg(Receita=("Receita", "sum"), QTD=("QTD", "sum"))
    )
    pivot_receita = agrupado.pivot(index="descricao", columns=col_periodo, values="Receita").fillna(0)
    pivot_qtd = agrupado.pivot(index="descricao", columns=col_periodo, values="QTD").fillna(0)

    ano_referencia = df.loc[df[col_periodo] == periodo_atual, "Data_Venda"].dt.year.max()
    total_ano = (
        df[df["Data_Venda"].dt.year == ano_referencia]
        .groupby("descricao")["Receita"].sum()
    )

    resultado = pd.DataFrame({
        "descricao": pivot_receita.index,
        "QTD_Periodo_Anterior": pivot_qtd.get(periodo_anterior, 0).values,
        "QTD_Periodo_Atual": pivot_qtd.get(periodo_atual, 0).values,
        "Receita_Periodo_Anterior": pivot_receita.get(periodo_anterior, 0).values,
        "Receita_Periodo_Atual": pivot_receita.get(periodo_atual, 0).values,
    })
    resultado["Variacao_Percentual"] = np.where(
        resultado["Receita_Periodo_Anterior"] > 0,
        (resultado["Receita_Periodo_Atual"] - resultado["Receita_Periodo_Anterior"])
        / resultado["Receita_Periodo_Anterior"] * 100,
        np.nan,
    )
    resultado["Total_Ano_Atual"] = resultado["descricao"].map(total_ano).fillna(0)

    em_alta = (
        resultado[resultado["Variacao_Percentual"] > 0]
        .sort_values("Variacao_Percentual", ascending=False)
        .head(top_n).reset_index(drop=True)
    )
    em_queda = (
        resultado[resultado["Variacao_Percentual"] < 0]
        .sort_values("Variacao_Percentual", ascending=True)
        .head(top_n).reset_index(drop=True)
    )
    return em_alta, em_queda


# ---------------------------------------------------------------------------
# Erosão de clientes por produto
# ---------------------------------------------------------------------------

def erosao_clientes_por_produto(df, granularidade="Mensal", produtos_alvo=None,
                                reducao_minima_percentual=50.0, queda_minima_rs=0.0):
    """
    Para cada produto (ou apenas os informados em produtos_alvo), compara a
    receita/qtd de cada cliente entre os DOIS períodos mais recentes (não o
    histórico inteiro — mesmo padrão de "boletim" usado em
    produtos_alta_e_queda/clientes_queda_quantidade) e lista quem reduziu ou
    parou de comprar aquele produto.

    reducao_minima_percentual: só entram no resultado clientes cuja queda,
    na transição mais recente, foi de pelo menos esse percentual (padrão
    50% — ajustável; use 0 para ver toda e qualquer redução).
    queda_minima_rs: piso em R$ da redução absoluta (Reducao_Receita). 0 = sem piso.
    """
    col_periodo = COLUNA_PERIODO[granularidade]
    periodos_ordenados = _ordenar_periodos(df[col_periodo].unique(), granularidade)
    colunas_vazias = ["Cliente", "descricao", "Periodo", "Receita", "QTD",
                       "Receita_Periodo_Anterior", "QTD_Periodo_Anterior",
                       "Reducao_Receita", "Reducao_Percentual", "Parou_De_Comprar"]
    if len(periodos_ordenados) < 2:
        return pd.DataFrame(columns=colunas_vazias)

    periodo_anterior, periodo_atual = periodos_ordenados[-2], periodos_ordenados[-1]

    base = df
    if produtos_alvo is not None:
        # Lista vazia = nenhum produto no escopo, e não "todos" — o `None` é o
        # único jeito de pedir a base inteira. Antes, uma lista vazia (nenhum
        # alerta de queda) alargava o escopo para toda a base em vez de zerar.
        base = base[base["descricao"].isin(produtos_alvo)]
    base = base[base[col_periodo].isin([periodo_anterior, periodo_atual])]
    if base.empty:
        return pd.DataFrame(columns=colunas_vazias)

    agrupado = (
        base.groupby(["descricao", "Cliente", col_periodo], as_index=False)
        .agg(Receita=("Receita", "sum"), QTD=("QTD", "sum"))
        .rename(columns={col_periodo: "Periodo"})
    )
    pivot_receita = agrupado.pivot_table(index=["descricao", "Cliente"], columns="Periodo", values="Receita", fill_value=0)
    pivot_qtd = agrupado.pivot_table(index=["descricao", "Cliente"], columns="Periodo", values="QTD", fill_value=0)
    # Com produtos_alvo, a base filtrada pode não ter linhas em um dos dois
    # períodos (ex.: todos os produtos do alerta sem venda no período atual)
    # — sem o reindex, pivot.get(periodo, 0) devolve o escalar 0 e o .values
    # abaixo quebra com AttributeError.
    pivot_receita = pivot_receita.reindex(columns=[periodo_anterior, periodo_atual], fill_value=0)
    pivot_qtd = pivot_qtd.reindex(columns=[periodo_anterior, periodo_atual], fill_value=0)

    erosao = pivot_receita.index.to_frame(index=False)
    erosao["Receita"] = pivot_receita.get(periodo_atual, 0).values
    erosao["Receita_Periodo_Anterior"] = pivot_receita.get(periodo_anterior, 0).values
    erosao["QTD"] = pivot_qtd.get(periodo_atual, 0).values
    erosao["QTD_Periodo_Anterior"] = pivot_qtd.get(periodo_anterior, 0).values
    erosao["Periodo"] = periodo_atual

    erosao = erosao[
        (erosao["Receita_Periodo_Anterior"] > 0) & (erosao["Receita"] < erosao["Receita_Periodo_Anterior"])
    ].copy()

    erosao["Reducao_Receita"] = erosao["Receita_Periodo_Anterior"] - erosao["Receita"]
    erosao["Reducao_Percentual"] = erosao["Reducao_Receita"] / erosao["Receita_Periodo_Anterior"] * 100
    erosao["Parou_De_Comprar"] = erosao["Receita"] == 0

    erosao = erosao[erosao["Reducao_Percentual"] >= reducao_minima_percentual]
    if queda_minima_rs and queda_minima_rs > 0:
        erosao = erosao[erosao["Reducao_Receita"] >= float(queda_minima_rs)]
    erosao = erosao[["Cliente", "descricao", "Periodo", "Receita", "QTD",
                      "Receita_Periodo_Anterior", "QTD_Periodo_Anterior",
                      "Reducao_Receita", "Reducao_Percentual", "Parou_De_Comprar"]]
    erosao.sort_values("Reducao_Receita", ascending=False, inplace=True)
    erosao.reset_index(drop=True, inplace=True)

    return erosao


def sem_venda_clientes(df, granularidade="Mensal", reducao_minima_percentual=90.0):
    """
    Clientes que praticamente pararam de comprar (queda >= reducao_minima_percentual
    ou receita zerada no período atual), sem piso em R$ — pega também baixo volume.
    Agregado por cliente (não por produto).
    """
    col_periodo = COLUNA_PERIODO[granularidade]
    periodos_ordenados = _ordenar_periodos(df[col_periodo].unique(), granularidade)
    colunas = ["Cliente", "Periodo", "Receita", "Receita_Periodo_Anterior",
               "Reducao_Receita", "Reducao_Percentual", "Parou_De_Comprar"]
    if len(periodos_ordenados) < 2:
        return pd.DataFrame(columns=colunas)

    periodo_anterior, periodo_atual = periodos_ordenados[-2], periodos_ordenados[-1]
    base = df[df[col_periodo].isin([periodo_anterior, periodo_atual])]
    agrupado = (
        base.groupby(["Cliente", col_periodo], as_index=False)["Receita"].sum()
        .rename(columns={col_periodo: "Periodo"})
    )
    pivot = agrupado.pivot_table(index="Cliente", columns="Periodo", values="Receita", fill_value=0)
    resultado = pivot.index.to_frame(index=False)
    resultado["Receita"] = pivot.get(periodo_atual, 0).values
    resultado["Receita_Periodo_Anterior"] = pivot.get(periodo_anterior, 0).values
    resultado["Periodo"] = periodo_atual
    resultado = resultado[
        (resultado["Receita_Periodo_Anterior"] > 0) & (resultado["Receita"] < resultado["Receita_Periodo_Anterior"])
    ].copy()
    resultado["Reducao_Receita"] = resultado["Receita_Periodo_Anterior"] - resultado["Receita"]
    resultado["Reducao_Percentual"] = resultado["Reducao_Receita"] / resultado["Receita_Periodo_Anterior"] * 100
    resultado["Parou_De_Comprar"] = resultado["Receita"] == 0
    resultado = resultado[resultado["Reducao_Percentual"] >= float(reducao_minima_percentual)]
    resultado = resultado[colunas]
    resultado.sort_values("Reducao_Receita", ascending=False, inplace=True)
    resultado.reset_index(drop=True, inplace=True)
    return resultado


def clientes_queda_quantidade(df, granularidade="Mensal", top_n=10):
    """
    Compara os dois períodos mais recentes: para cada cliente, quantidade
    anterior/atual, variação %, perda financeira (receita atual - anterior,
    negativa) e o "produto crítico" (produto que mais contribuiu para a queda
    de quantidade daquele cliente na transição).
    """
    col_periodo = COLUNA_PERIODO[granularidade]
    periodos_ordenados = _ordenar_periodos(df[col_periodo].unique(), granularidade)
    if len(periodos_ordenados) < 2:
        return pd.DataFrame(columns=[
            "Cliente", "QTD_Periodo_Anterior", "QTD_Periodo_Atual", "Variacao_Percentual",
            "Perda_Receita", "Produto_Critico",
        ])

    periodo_anterior, periodo_atual = periodos_ordenados[-2], periodos_ordenados[-1]
    base = df[df[col_periodo].isin([periodo_anterior, periodo_atual])]

    por_cliente = (
        base.groupby(["Cliente", col_periodo], as_index=False)
        .agg(Receita=("Receita", "sum"), QTD=("QTD", "sum"))
    )
    pivot_qtd = por_cliente.pivot(index="Cliente", columns=col_periodo, values="QTD").fillna(0)
    pivot_receita = por_cliente.pivot(index="Cliente", columns=col_periodo, values="Receita").fillna(0)

    resultado = pd.DataFrame({
        "Cliente": pivot_qtd.index,
        "QTD_Periodo_Anterior": pivot_qtd.get(periodo_anterior, 0).values,
        "QTD_Periodo_Atual": pivot_qtd.get(periodo_atual, 0).values,
    })
    resultado["Variacao_Percentual"] = np.where(
        resultado["QTD_Periodo_Anterior"] > 0,
        (resultado["QTD_Periodo_Atual"] - resultado["QTD_Periodo_Anterior"])
        / resultado["QTD_Periodo_Anterior"] * 100,
        np.nan,
    )
    resultado["Perda_Receita"] = (
        pivot_receita.get(periodo_atual, 0).values - pivot_receita.get(periodo_anterior, 0).values
    )

    por_produto = (
        base.groupby(["Cliente", "descricao", col_periodo], as_index=False)["QTD"].sum()
        .pivot_table(index=["Cliente", "descricao"], columns=col_periodo, values="QTD", fill_value=0)
    )
    if periodo_anterior in por_produto.columns and periodo_atual in por_produto.columns:
        por_produto["Queda_QTD"] = por_produto[periodo_anterior] - por_produto[periodo_atual]
        produto_critico = (
            por_produto.reset_index().sort_values("Queda_QTD", ascending=False)
            .groupby("Cliente").first()["descricao"]
        )
        resultado["Produto_Critico"] = resultado["Cliente"].map(produto_critico).fillna("-")
    else:
        resultado["Produto_Critico"] = "-"

    resultado = resultado[resultado["Variacao_Percentual"] < 0]
    resultado.sort_values("Variacao_Percentual", ascending=True, inplace=True)
    resultado = resultado.head(top_n).reset_index(drop=True)
    return resultado


def correlacao_produto_cliente(df, erosao_df, alertas_queda_df, granularidade="Mensal", top_n=15):
    """
    Classifica os principais eventos de erosão (cliente que reduziu compra de
    um produto) com um status heurístico e transparente, no estilo de um
    relatório executivo:

      - "Abandono de Categoria": vários clientes abandonaram o mesmo produto
        no mesmo período (queda sistêmica, não isolada).
      - "Ruptura Estratégica": o cliente parou de comprar um produto que
        respondia por boa parte do que ele comprava daquele produto.
      - "Fim de Ciclo": o produto já está listado entre os alertas de queda
        consecutiva (tendência estrutural, não pontual).
      - "Caso Específico": nenhum dos padrões acima foi identificado.
    """
    if erosao_df.empty:
        return pd.DataFrame(columns=["Cliente", "descricao", "Periodo", "Reducao_Percentual", "Status"])

    top_eventos = erosao_df.head(top_n).copy()

    contagem_clientes_por_produto_periodo = (
        erosao_df.groupby(["descricao", "Periodo"])["Cliente"].nunique()
    )
    produtos_em_alerta = set(alertas_queda_df["descricao"]) if not alertas_queda_df.empty else set()

    def classificar(linha):
        chave = (linha["descricao"], linha["Periodo"])
        clientes_afetados = contagem_clientes_por_produto_periodo.get(chave, 1)
        if clientes_afetados >= 3:
            return "Abandono de Categoria"
        if linha["descricao"] in produtos_em_alerta:
            return "Fim de Ciclo"
        if linha["Parou_De_Comprar"] and linha["Reducao_Percentual"] >= 70:
            return "Ruptura Estratégica"
        return "Caso Específico"

    top_eventos["Status"] = top_eventos.apply(classificar, axis=1)
    colunas = ["Cliente", "descricao", "Periodo", "Reducao_Receita", "Reducao_Percentual",
               "Parou_De_Comprar", "Status"]
    return top_eventos[colunas].reset_index(drop=True)


def impacto_financeiro_churn(df, erosao_df, granularidade="Mensal"):
    """
    KPIs resumidos de impacto financeiro da erosão/churn: maior retração
    individual (%), receita total sob risco (soma das reduções observadas) e
    a variação global de receita entre os dois últimos períodos.
    """
    col_periodo = COLUNA_PERIODO[granularidade]
    periodos_ordenados = _ordenar_periodos(df[col_periodo].unique(), granularidade)

    maior_retracao_percentual = (
        erosao_df["Reducao_Percentual"].max() if not erosao_df.empty else 0.0
    )
    receita_sob_risco = erosao_df["Reducao_Receita"].sum() if not erosao_df.empty else 0.0

    variacao_global = None
    if len(periodos_ordenados) >= 2:
        receita_anterior = df.loc[df[col_periodo] == periodos_ordenados[-2], "Receita"].sum()
        receita_atual = df.loc[df[col_periodo] == periodos_ordenados[-1], "Receita"].sum()
        if receita_anterior > 0:
            variacao_global = (receita_atual - receita_anterior) / receita_anterior * 100

    return pd.DataFrame([{
        "Maior_Retracao_Individual_Pct": maior_retracao_percentual,
        "Receita_Sob_Risco": receita_sob_risco,
        "Variacao_Global_Periodo_Pct": variacao_global,
    }])


# ---------------------------------------------------------------------------
# Frequência e Renúncia (poder de compra)
# ---------------------------------------------------------------------------

def calcular_frequencia(df, granularidade="Mensal", campo="Cliente", desconsiderar_balcao=False,
                        clientes_balcao_extra=None):
    """
    Frequência de compra por (campo, período):
      - Frequencia_Simples: nº de meses-calendário distintos com receita > 0
        dentro daquele período (para Mensal, é 0 ou 1).
      - Frequencia_Acumulada: soma cumulativa da Frequencia_Simples ao longo
        dos períodos, na ordem cronológica, por entidade (cliente/produto).
    """
    col_periodo = COLUNA_PERIODO[granularidade]
    periodos_ordenados = _ordenar_periodos(df[col_periodo].unique(), granularidade)
    ordem_periodo = {p: i for i, p in enumerate(periodos_ordenados)}

    vendas_positivas = df[df["Receita"] > 0]
    contagem_meses = (
        vendas_positivas.groupby([campo, col_periodo])["Periodo_Mensal"]
        .nunique().rename("Frequencia_Simples")
    )
    frequencia = contagem_meses.reset_index().rename(columns={col_periodo: "Periodo"})
    frequencia["_ordem"] = frequencia["Periodo"].map(ordem_periodo)
    frequencia.sort_values([campo, "_ordem"], inplace=True)

    if desconsiderar_balcao and campo == "Cliente":
        mascara = mascara_clientes_balcao(frequencia[campo], clientes_balcao_extra)
        frequencia.loc[mascara, "Frequencia_Simples"] = 0

    frequencia["Frequencia_Acumulada"] = frequencia.groupby(campo)["Frequencia_Simples"].cumsum()
    frequencia.drop(columns=["_ordem"], inplace=True)
    frequencia.reset_index(drop=True, inplace=True)
    return frequencia


def calcular_renuncia(df, granularidade="Mensal", campo="Cliente"):
    """
    "Renúncia" mede o poder de compra que a entidade (cliente, tipicamente)
    abriu mão: soma das quedas de receita entre períodos consecutivos
    (aumentos não compensam quedas anteriores - é o total de receita
    efetivamente "deixado na mesa" ao longo do tempo).

      - Renuncia: valor da queda no período (0 se não houve queda).
      - Renuncia_Acumulada: soma cumulativa da renúncia por entidade.
      - Renuncia_Percentual: a queda do período como % da receita do período
        anterior.
    """
    col_periodo = COLUNA_PERIODO[granularidade]
    periodos_ordenados = _ordenar_periodos(df[col_periodo].unique(), granularidade)
    ordem_periodo = {p: i for i, p in enumerate(periodos_ordenados)}

    agrupado = (
        df.groupby([campo, col_periodo], as_index=False)["Receita"].sum()
        .rename(columns={col_periodo: "Periodo"})
    )
    agrupado["_ordem"] = agrupado["Periodo"].map(ordem_periodo)
    # Período sem venda entra como 0 (da 1ª venda em diante): renúncia é a
    # receita deixada na mesa, e parar de comprar é exatamente isso.
    agrupado = _completar_periodos_sem_venda(agrupado, campo, periodos_ordenados)
    agrupado.sort_values([campo, "_ordem"], inplace=True)

    agrupado["Receita_Anterior"] = agrupado.groupby(campo)["Receita"].shift(1)
    agrupado["Renuncia"] = (agrupado["Receita_Anterior"] - agrupado["Receita"]).clip(lower=0).fillna(0)
    agrupado["Renuncia_Percentual"] = np.where(
        (agrupado["Receita_Anterior"].notnull()) & (agrupado["Receita_Anterior"] > 0),
        agrupado["Renuncia"] / agrupado["Receita_Anterior"] * 100,
        0.0,
    )
    agrupado["Renuncia_Acumulada"] = agrupado.groupby(campo)["Renuncia"].cumsum()

    agrupado.drop(columns=["_ordem", "Receita_Anterior"], inplace=True)
    agrupado.reset_index(drop=True, inplace=True)
    return agrupado


# ---------------------------------------------------------------------------
# Regra de corte (curva de Pareto -> faixas) — FONTE ÚNICA
#
# Toda classificação em faixas do projeto passa por aqui: relatório por período
# (classificar_faixas), prévias agregadas da tela (classificar_clientes_agregado
# / classificar_produtos_agregado), os contadores (contar_clientes_por_grupo) e
# os sugeridores de corte (sugerir_cortes_grupos / sugerir_corte_produtos).
#
# Mantê-la em um só lugar é o que garante que a prévia da tela e o relatório
# final classifiquem exatamente igual. Mudar a régua de corte = mexer só em
# `faixa_por_curva`/`contar_por_faixa`, nunca em cada chamador.
# ---------------------------------------------------------------------------

NOME_FAIXA_DEMAIS = "Demais"
NOME_FAIXA_BALCAO = "Balcão"


def nomes_faixas(cortes, nomes=None):
    """Nomes das faixas para `cortes`, sempre com "Demais" no fim (1 a mais que os cortes)."""
    base = list(nomes) if nomes else [f"Grupo {i + 1}" for i in range(len(cortes))]
    return base + [NOME_FAIXA_DEMAIS]


def curva_pareto(receita_por_entidade):
    """Ordena a receita (desc) e devolve a curva de Pareto usada na classificação.

    Recebe uma Series indexada pela entidade (cliente/produto) e devolve um
    DataFrame com Receita, Percentual_Individual e Percentual_Acumulado (este
    último inclusivo: soma até a entidade, ela incluída).

    Receita total <= 0 zera os percentuais em vez de dividir por zero.
    """
    receita = receita_por_entidade.sort_values(ascending=False)
    total = receita.sum()
    if total <= 0:
        individual = pd.Series(0.0, index=receita.index)
        acumulado = pd.Series(0.0, index=receita.index)
    else:
        individual = receita / total * 100
        acumulado = receita.cumsum() / total * 100
    return pd.DataFrame({
        "Receita": receita,
        "Percentual_Individual": individual,
        "Percentual_Acumulado": acumulado,
    })


def faixa_por_curva(curva, cortes, nomes=None):
    """Faixa de cada entidade a partir da curva de Pareto. Vetorizado.

    Régua: a entidade pertence à faixa em que ela ENTRA, ou seja, decidida pelo
    acumulado ANTES dela (`acumulado - individual`). O maior cliente entra com
    0% acumulado e portanto sempre cai na primeira faixa; quem começa depois do
    último corte cai em "Demais".

    Comparar o acumulado INCLUSIVO com o corte (régua anterior) deixava a
    primeira faixa vazia sempre que a maior entidade sozinha já passava do
    primeiro corte — caso comum quando um cliente concentra o faturamento.
    """
    rotulos = nomes_faixas(cortes, nomes)
    acumulado_anterior = pd.Series(
        curva["Percentual_Acumulado"] - curva["Percentual_Individual"]
    )
    faixa = pd.Series(rotulos[-1], index=acumulado_anterior.index, dtype=object)
    # De trás para frente: o corte menor sobrescreve o maior, então cada
    # entidade termina com a primeira faixa em que cabe.
    for corte, rotulo in zip(reversed(list(cortes)), reversed(rotulos[:-1])):
        faixa = faixa.mask(acumulado_anterior < corte, rotulo)
    return faixa


def contar_por_faixa(curva, cortes):
    """Quantas entidades caem em cada faixa — mesma régua de `faixa_por_curva`.

    Devolve uma lista com um item a mais que `cortes` (o último é "Demais").
    """
    faixa = faixa_por_curva(curva, cortes)
    rotulos = nomes_faixas(cortes)
    contagem = faixa.value_counts()
    return [int(contagem.get(rotulo, 0)) for rotulo in rotulos]


def _reduzir_corte_ate_caber(curva, cortes, indice, limite_inferior,
                             max_por_grupo, passo):
    """Reduz cortes[indice] até a faixa correspondente ter <= max_por_grupo entidades.

    Para de reduzir ao encostar no corte anterior (não inverte a ordem dos cortes).
    """
    corte = cortes[indice]
    while True:
        quantidade = contar_por_faixa(curva, cortes[: indice + 1])[indice]
        if quantidade <= max_por_grupo or corte <= limite_inferior + passo:
            return corte
        corte -= passo
        cortes = list(cortes)
        cortes[indice] = corte


# ---------------------------------------------------------------------------
# Classificação em faixas por representatividade no faturamento (genérica)
# ---------------------------------------------------------------------------

def classificar_faixas(df, granularidade="Mensal", campo="Cliente", excluidos=None,
                        cortes=(30.0, 50.0, 60.0), nomes_grupos=None, desconsiderar_balcao=False,
                        clientes_balcao_extra=None):
    """
    Classifica entidades (clientes ou produtos) em faixas por representatividade
    acumulada no faturamento, período a período.

    cortes: percentuais cumulativos crescentes (ex.: (30, 50, 60)). A última
    faixa (nome "Demais") recebe tudo que ultrapassar o último corte.
    excluidos: valores da entidade a remover do cálculo (ex.: clientes fora
    da análise). O faturamento de referência é recalculado sem eles.

    Clientes balcão (quando desconsiderar_balcao=True e campo="Cliente")
    saem do cálculo de grupos/percentual acumulado e ficam numa faixa
    "Balcão" própria, com Percentual_Individual real (não zerado) — mesma
    regra usada na prévia da tela (classificar_clientes_agregado).

    Retorna um DataFrame com: campo, Receita, Percentual_Acumulado,
    Percentual_Individual, Periodo, Faixa_ABC, Frequencia_Simples,
    Frequencia_Acumulada, Renuncia, Renuncia_Acumulada, Renuncia_Percentual.
    """
    excluidos = set(excluidos or [])
    cortes = list(cortes)
    nomes_grupos_base = list(nomes_grupos) if nomes_grupos else None

    col_periodo = COLUNA_PERIODO[granularidade]
    base = df[~df[campo].isin(excluidos)] if excluidos else df

    resultados = []
    for periodo, grupo in base.groupby(col_periodo):
        if campo == "Cliente" and desconsiderar_balcao:
            mascara_balcao = mascara_clientes_balcao(grupo[campo], clientes_balcao_extra)
            grupo_normal = grupo[~mascara_balcao]
            grupo_balcao = grupo[mascara_balcao]
        else:
            grupo_normal = grupo
            grupo_balcao = pd.DataFrame(columns=grupo.columns)

        receita_entidade = (
            curva_pareto(grupo_normal.groupby(campo)["Receita"].sum())
            .reset_index()
            .rename(columns={"index": campo})
            # Ordem histórica das colunas: o export Excel e a tabela da tela
            # consomem esta ordem.
            [[campo, "Receita", "Percentual_Acumulado", "Percentual_Individual"]]
        )
        receita_total = receita_entidade["Receita"].sum()
        receita_entidade["Periodo"] = periodo
        receita_entidade["Faixa_ABC"] = faixa_por_curva(
            receita_entidade, cortes, nomes_grupos_base,
        )

        if not grupo_balcao.empty:
            # Balcão fica de fora da classificação em grupos (o corte acima
            # é calculado só com grupo_normal), mas o % individual mostrado
            # é real — não faz sentido excluir da conta E mostrar receita
            # zerada. Fica sempre em faixa "Balcão" própria, nunca misturado
            # com "Grupo 1" (que deve refletir só quem participa de fato da
            # segmentação por receita).
            receita_balcao = (
                grupo_balcao.groupby(campo, as_index=False)["Receita"].sum()
                .sort_values("Receita", ascending=False)
                .reset_index(drop=True)
            )
            receita_balcao["Percentual_Acumulado"] = float("nan")
            receita_balcao["Percentual_Individual"] = (
                receita_balcao["Receita"] / receita_total * 100 if receita_total > 0 else 0.0
            )
            receita_balcao["Periodo"] = periodo
            receita_balcao["Faixa_ABC"] = NOME_FAIXA_BALCAO
            receita_entidade = pd.concat([receita_balcao, receita_entidade], ignore_index=True)

        resultados.append(receita_entidade)

    colunas_base = [campo, "Receita", "Percentual_Acumulado", "Percentual_Individual", "Periodo", "Faixa_ABC"]
    if not resultados:
        classificado = pd.DataFrame(columns=colunas_base)
    else:
        classificado = pd.concat(resultados, ignore_index=True)

    frequencia = calcular_frequencia(
        base, granularidade, campo,
        desconsiderar_balcao=desconsiderar_balcao,
        clientes_balcao_extra=clientes_balcao_extra,
    )
    renuncia = calcular_renuncia(base, granularidade, campo)

    classificado = classificado.merge(frequencia, on=[campo, "Periodo"], how="left")
    classificado = classificado.merge(
        renuncia[[campo, "Periodo", "Renuncia", "Renuncia_Acumulada", "Renuncia_Percentual"]],
        on=[campo, "Periodo"], how="left",
    )
    classificado[["Frequencia_Simples", "Frequencia_Acumulada", "Renuncia",
                  "Renuncia_Acumulada", "Renuncia_Percentual"]] = classificado[[
        "Frequencia_Simples", "Frequencia_Acumulada", "Renuncia",
        "Renuncia_Acumulada", "Renuncia_Percentual",
    ]].fillna(0)

    periodos_ordenados = _ordenar_periodos(classificado["Periodo"].unique(), granularidade)
    ordem_periodo = {p: i for i, p in enumerate(periodos_ordenados)}
    classificado["_ordem"] = classificado["Periodo"].map(ordem_periodo)
    classificado.sort_values(["_ordem", "Percentual_Acumulado", "Receita"], ascending=[True, True, False], inplace=True)
    classificado.drop(columns=["_ordem"], inplace=True)
    classificado.reset_index(drop=True, inplace=True)
    return classificado


def _limitar_top_por_grupo(classificado, top_por_grupo):
    """Mantém só as `top_por_grupo` linhas de maior Receita em cada (Periodo, Faixa_ABC). None = sem corte."""
    if top_por_grupo is None or classificado.empty:
        return classificado
    limitado = (
        classificado.sort_values("Receita", ascending=False)
        .groupby(["Periodo", "Faixa_ABC"], group_keys=False)
        .head(top_por_grupo)
    )
    limitado.sort_values(["Periodo", "Faixa_ABC", "Receita"], ascending=[True, True, False], inplace=True)
    limitado.reset_index(drop=True, inplace=True)
    return limitado


def classificar_abc(df, granularidade="Mensal", clientes_excluidos=None, cortes_clientes=(30.0, 50.0, 60.0),
                     desconsiderar_balcao=False, top_clientes_por_grupo=5, clientes_balcao_extra=None):
    """
    Classificação de clientes por representatividade no faturamento (ver
    classificar_faixas) — recorte "executivo" pro relatório final:

      - mantém só os `top_clientes_por_grupo` clientes de maior receita em
        cada (Período, Faixa) — None mantém todos, sem corte. IMPORTANTE:
        quem depende da classificação COMPLETA (migração de faixa, poder de
        compra) deve chamar com top_clientes_por_grupo=None — um corte de
        top 5 aqui faria a migração só enxergar 5 clientes por grupo.
      - descarta Frequencia_Simples/Frequencia_Acumulada: não fazem sentido
        junto de um corte "top N por grupo" (a frequência de compra do
        cliente não muda por causa do corte, e a coluna ao lado de "top 5"
        sugere o contrário).
    """
    classificado = classificar_faixas(
        df, granularidade, campo="Cliente", excluidos=clientes_excluidos,
        cortes=cortes_clientes, desconsiderar_balcao=desconsiderar_balcao,
        clientes_balcao_extra=clientes_balcao_extra,
    )
    classificado = classificado.drop(columns=["Frequencia_Simples", "Frequencia_Acumulada"])
    return _limitar_top_por_grupo(classificado, top_clientes_por_grupo)


def classificar_produtos_por_receita(df, granularidade="Mensal", corte_percentual=80.0):
    """
    Classificação de produtos por representatividade no faturamento: faixa
    "Grupo 1" concentra o corte_percentual (padrão 80%) inicial de receita
    acumulada; o restante cai em "Demais" (cauda longa).
    """
    return classificar_faixas(df, granularidade, campo="descricao", excluidos=None,
                               cortes=(corte_percentual,), nomes_grupos=["Grupo 1"])


def classificar_clientes_agregado(df, clientes_excluidos=None, cortes=(30.0, 50.0, 60.0), desconsiderar_balcao=False,
                                  clientes_balcao_extra=None):
    """
    Classificação RÁPIDA (não por período) de cada cliente em um grupo, usando
    a receita agregada de todo o CSV como referência — pensada para a prévia
    na interface (a classificação "oficial" do relatório, por período, é
    feita por classificar_faixas/classificar_abc).

    Se desconsiderar_balcao=True, clientes tipo "consumidor final"/"balcão"
    (REGEX_BALCAO) e nomes em clientes_balcao_extra (tags da empresa) ficam
    de fora do cálculo dos grupos. Com o flag desligado, todos entram —
    a tag só cadastra o nome na lista do filtro.

    Retorna DataFrame: Cliente, Receita, Percentual_Individual,
    Percentual_Acumulado (NaN para linhas de Balcão), Faixa.
    """
    excluidos = set(clientes_excluidos or [])
    base = df[~df["Cliente"].isin(excluidos)] if excluidos else df

    if desconsiderar_balcao:
        mascara_balcao = mascara_clientes_balcao(base["Cliente"], clientes_balcao_extra)
        base_normal = base[~mascara_balcao]
        base_balcao = base[mascara_balcao]
    else:
        base_normal = base
        base_balcao = pd.DataFrame(columns=base.columns)

    resultado = curva_pareto(base_normal.groupby("Cliente")["Receita"].sum()).reset_index()
    resultado = resultado.rename(columns={"index": "Cliente"})
    total = resultado["Receita"].sum()
    resultado = resultado[["Cliente", "Receita", "Percentual_Individual", "Percentual_Acumulado"]]
    resultado["Faixa"] = faixa_por_curva(resultado, cortes)

    frequencia_normal = (
        base_normal[base_normal["Receita"] > 0].groupby("Cliente")["Periodo_Mensal"].nunique().rename("Frequencia")
    )
    resultado = resultado.merge(frequencia_normal, on="Cliente", how="left")
    resultado["Frequencia"] = resultado["Frequencia"].fillna(0).astype(int)

    if not base_balcao.empty:
        # Balcão fica de fora da classificação em grupos (por isso o corte é
        # calculado só com base_normal), mas o % individual mostrado é real
        # — não faz sentido excluir da conta E mentir que a receita é 0.
        # Fica sempre na faixa "Balcão", nunca misturado com "Grupo 1" (que
        # deve refletir só quem participa de fato da segmentação por receita).
        receita_balcao = base_balcao.groupby("Cliente")["Receita"].sum().sort_values(ascending=False).reset_index()
        receita_balcao.columns = ["Cliente", "Receita"]
        receita_balcao["Percentual_Individual"] = (receita_balcao["Receita"] / total * 100) if total > 0 else 0.0
        receita_balcao["Percentual_Acumulado"] = None
        receita_balcao["Faixa"] = NOME_FAIXA_BALCAO
        receita_balcao["Frequencia"] = 0
        resultado = pd.concat([receita_balcao, resultado], ignore_index=True)

    return resultado


def classificar_produtos_agregado(df, corte_percentual=80.0):
    """
    Classificação RÁPIDA (não por período) de cada produto em "Grupo 1"
    (top corte_percentual% da receita) ou "Demais", com a participação na
    receita: Freq_Simples é o % individual daquele produto na receita total,
    Freq_Acumulado é o % acumulado (curva de Pareto/ABC — mesmo valor que
    decide a Faixa). Pensada para a prévia na interface — ver
    classificar_produtos_por_receita para a versão por período usada no
    relatório final.
    """
    curva = curva_pareto(df.groupby("descricao")["Receita"].sum()).reset_index()
    curva = curva.rename(columns={
        "index": "descricao",
        "Percentual_Individual": "Freq_Simples",
        "Percentual_Acumulado": "Freq_Acumulado",
    })
    curva["Faixa"] = faixa_por_curva(
        curva.rename(columns={
            "Freq_Simples": "Percentual_Individual",
            "Freq_Acumulado": "Percentual_Acumulado",
        }),
        (corte_percentual,),
    )
    return curva[["descricao", "Receita", "Freq_Simples", "Freq_Acumulado", "Faixa"]]


def contar_clientes_por_grupo(df, clientes_excluidos=None, cortes=(30.0, 50.0, 60.0), desconsiderar_balcao=False,
                              clientes_balcao_extra=None):
    """
    Conta quantos clientes caem em cada grupo para os cortes informados
    (sem ajustar automaticamente), usando a receita agregada total como
    referência. Útil para pré-visualizar o efeito dos parâmetros antes de
    rodar o relatório completo.

    Retorna uma lista de contagens com um item a mais que `cortes` (o
    último item é a contagem do grupo "Demais").
    """
    excluidos = set(clientes_excluidos or [])
    base = df[~df["Cliente"].isin(excluidos)] if excluidos else df

    if desconsiderar_balcao:
        mascara_balcao = mascara_clientes_balcao(base["Cliente"], clientes_balcao_extra)
        base_normal = base[~mascara_balcao]
    else:
        base_normal = base

    receita_cliente = base_normal.groupby("Cliente")["Receita"].sum()
    if receita_cliente.empty or receita_cliente.sum() <= 0:
        return [0] * (len(cortes) + 1)

    return contar_por_faixa(curva_pareto(receita_cliente), cortes)


def sugerir_cortes_grupos(df, clientes_excluidos=None, cortes_iniciais=(30.0, 50.0, 60.0),
                           max_por_grupo=10, passo=0.5, desconsiderar_balcao=False,
                           clientes_balcao_extra=None):
    """
    Ajusta (reduz) os cortes percentuais cumulativos até que cada grupo não
    ultrapasse max_por_grupo clientes, usando a receita agregada total (soma
    de todos os períodos) como referência. Não altera a ordem/quantidade de
    grupos, apenas os percentuais de corte.

    Retorna (cortes_ajustados, contagens) onde contagens tem um item a mais
    que cortes_ajustados (o último é a contagem do grupo "Demais").
    """
    excluidos = set(clientes_excluidos or [])
    base = df[~df["Cliente"].isin(excluidos)] if excluidos else df

    if desconsiderar_balcao:
        mascara_balcao = mascara_clientes_balcao(base["Cliente"], clientes_balcao_extra)
        base_normal = base[~mascara_balcao]
    else:
        base_normal = base

    receita_cliente = base_normal.groupby("Cliente")["Receita"].sum()

    cortes = list(cortes_iniciais)
    if receita_cliente.empty or receita_cliente.sum() <= 0:
        return cortes, [0] * (len(cortes) + 1)

    curva = curva_pareto(receita_cliente)

    limite_inferior = 0.0
    for i in range(len(cortes)):
        cortes[i] = round(
            _reduzir_corte_ate_caber(
                curva, cortes, i, limite_inferior, max_por_grupo, passo,
            ),
            1,
        )
        limite_inferior = cortes[i]

    return cortes, contar_por_faixa(curva, cortes)


def sugerir_corte_produtos(df, corte_inicial=80.0, max_por_grupo=20, passo=0.5):
    """
    Reduz o corte percentual cumulativo de produtos até o Grupo 1 (alto giro)
    não ultrapassar max_por_grupo itens — mesmo espírito de sugerir_cortes_grupos.

    Retorna (corte_ajustado, [qtd_grupo1, qtd_demais]).
    """
    receita_produto = df.groupby("descricao")["Receita"].sum()
    corte = float(corte_inicial)
    if receita_produto.empty or receita_produto.sum() <= 0:
        return round(corte, 1), [0, 0]

    curva = curva_pareto(receita_produto)
    corte = round(
        _reduzir_corte_ate_caber(
            curva, [corte], 0, 0.0, max_por_grupo, passo,
        ),
        1,
    )
    return corte, contar_por_faixa(curva, (corte,))


# ---------------------------------------------------------------------------
# Migração de clientes entre grupos + causa provável
# ---------------------------------------------------------------------------

def migracao_abc(df, abc_df, granularidade="Mensal"):
    """
    Compara períodos consecutivos e identifica clientes que subiram ou
    desceram de faixa, com uma causa provável heurística e transparente.
    A ordem de "importância" das faixas é inferida pela ordem de aparição
    (a primeira faixa encontrada nos dados é a mais valiosa; "Demais" é
    sempre a menos valiosa).
    """
    col_periodo = COLUNA_PERIODO[granularidade]
    periodos_ordenados = _ordenar_periodos(abc_df["Periodo"].unique(), granularidade)

    faixas_em_ordem = [f for f in abc_df["Faixa_ABC"].unique() if f != "Demais"]
    faixas_em_ordem = sorted(faixas_em_ordem, key=lambda nome: int(nome.split()[-1]) if nome.split()[-1].isdigit() else 99)
    faixas_em_ordem.append("Demais")
    ordem_faixa = {nome: (len(faixas_em_ordem) - i) for i, nome in enumerate(faixas_em_ordem)}

    contexto = _preparar_contexto_causa_provavel(df, col_periodo)

    migracoes = []

    for periodo_anterior, periodo_atual in zip(periodos_ordenados, periodos_ordenados[1:]):
        faixa_anterior = abc_df[abc_df["Periodo"] == periodo_anterior].set_index("Cliente")["Faixa_ABC"]
        faixa_atual = abc_df[abc_df["Periodo"] == periodo_atual].set_index("Cliente")["Faixa_ABC"]

        clientes_comuns = faixa_anterior.index.intersection(faixa_atual.index)
        for cliente in clientes_comuns:
            de = faixa_anterior[cliente]
            para = faixa_atual[cliente]
            if de == para:
                continue

            direcao = "Subiu" if ordem_faixa.get(para, 0) > ordem_faixa.get(de, 0) else "Desceu"
            causa = _causa_provavel_migracao(contexto, cliente, periodo_anterior, periodo_atual, direcao)

            migracoes.append({
                "Cliente": cliente,
                "Periodo_Anterior": periodo_anterior,
                "Periodo_Atual": periodo_atual,
                "Faixa_Anterior": de,
                "Faixa_Atual": para,
                "Direcao": direcao,
                "Causa_Provavel": causa,
            })

    return pd.DataFrame(migracoes)


def resumo_migracao(migracao_df):
    """
    Uma linha por transição de período, com a contagem de clientes que
    subiram vs. desceram de faixa nela — visão executiva rápida (ver
    migracao_abc para o detalhe por cliente).
    """
    colunas = ["Periodo_Anterior", "Periodo_Atual", "Qtd_Subiu", "Qtd_Desceu"]
    if migracao_df.empty:
        return pd.DataFrame(columns=colunas)

    resumo = (
        migracao_df.groupby(["Periodo_Anterior", "Periodo_Atual", "Direcao"])
        .size().unstack(fill_value=0).reset_index()
    )
    for direcao in ("Subiu", "Desceu"):
        if direcao not in resumo.columns:
            resumo[direcao] = 0
    resumo.rename(columns={"Subiu": "Qtd_Subiu", "Desceu": "Qtd_Desceu"}, inplace=True)
    return resumo[colunas]


PONTOS_SUBIU_FAIXA = 3
PONTOS_DESCEU_FAIXA = -2


def _transicoes_adjacentes_por_cliente(abc_df, granularidade):
    """Nº de transições em que o cliente aparece nos DOIS períodos vizinhos.

    É a mesma base que `migracao_abc` percorre. Contar simplesmente
    "períodos - 1" inflava o denominador de quem tem buraco no histórico
    (transição que ninguém avaliou entrava como período sem migração).
    """
    posicao = {
        p: i for i, p in enumerate(_ordenar_periodos(abc_df["Periodo"].unique(), granularidade))
    }

    def contar(periodos):
        indices = sorted({posicao[p] for p in periodos})
        return sum(1 for a, b in zip(indices, indices[1:]) if b - a == 1)

    return abc_df.groupby("Cliente")["Periodo"].apply(contar)


def pontuacao_migracao_clientes(migracao_df, abc_df, granularidade="Mensal"):
    """
    Score de migração por cliente, acumulado ao longo de TODO o histórico de
    transições disponível (não só a mais recente): +3 por subida de faixa,
    -2 por queda. Clientes que só sobem acumulam pontos rápido; quem cai com
    frequência tende a score negativo.

    Percentual_Permanencia: das transições de período em que o cliente
    aparece nos dois lados (a mesma base contada por migracao_abc), qual %
    ele NÃO migrou de faixa. 100% = nunca mudou de faixa desde que aparece
    na base.
    """
    colunas = ["Cliente", "Qtd_Subiu", "Qtd_Desceu", "Score", "Percentual_Permanencia"]
    if abc_df.empty:
        return pd.DataFrame(columns=colunas)

    if migracao_df.empty:
        contagem_migracoes = pd.DataFrame(columns=["Subiu", "Desceu"])
    else:
        contagem_migracoes = migracao_df.groupby(["Cliente", "Direcao"]).size().unstack(fill_value=0)
    for direcao in ("Subiu", "Desceu"):
        if direcao not in contagem_migracoes.columns:
            contagem_migracoes[direcao] = 0

    # "Oportunidades de migrar" por cliente = nº de transições em que ele
    # aparece nos dois períodos vizinhos (mesma base usada por migracao_abc).
    transicoes_por_cliente = _transicoes_adjacentes_por_cliente(abc_df, granularidade)

    resultado = transicoes_por_cliente.rename("Transicoes").reset_index()
    resultado = resultado.merge(
        contagem_migracoes[["Subiu", "Desceu"]].reset_index(), on="Cliente", how="left"
    )
    resultado[["Subiu", "Desceu"]] = resultado[["Subiu", "Desceu"]].fillna(0).astype(int)
    resultado["Score"] = resultado["Subiu"] * PONTOS_SUBIU_FAIXA + resultado["Desceu"] * PONTOS_DESCEU_FAIXA

    migracoes_totais = resultado["Subiu"] + resultado["Desceu"]
    resultado["Percentual_Permanencia"] = np.where(
        resultado["Transicoes"] > 0,
        (resultado["Transicoes"] - migracoes_totais) / resultado["Transicoes"] * 100,
        100.0,
    )

    resultado.rename(columns={"Subiu": "Qtd_Subiu", "Desceu": "Qtd_Desceu"}, inplace=True)
    resultado = resultado[colunas]
    resultado.sort_values("Score", ascending=False, inplace=True)
    resultado.reset_index(drop=True, inplace=True)
    return resultado


def _preparar_contexto_causa_provavel(df, col_periodo):
    """
    Pré-calcula, uma única vez para todo o DataFrame, os agregados por
    (Cliente, Período) usados pela heurística de causa provável. Sem isso,
    _causa_provavel_migracao precisaria refiltrar o DataFrame inteiro para
    cada cliente que migrou de faixa — com milhares de clientes e dezenas de
    milhares de linhas, isso é o gargalo de performance da geração de
    relatório (a etapa mais lenta, de longe).
    """
    vendas_positivas = df[df["Receita"] > 0]
    return {
        "receita": df.groupby(["Cliente", col_periodo])["Receita"].sum().to_dict(),
        "qtd": df.groupby(["Cliente", col_periodo])["QTD"].sum().to_dict(),
        "meses": vendas_positivas.groupby(["Cliente", col_periodo])["Periodo_Mensal"].nunique().to_dict(),
        "produtos": vendas_positivas.groupby(["Cliente", col_periodo])["descricao"].apply(set).to_dict(),
        "receita_produto": vendas_positivas.groupby(["Cliente", col_periodo, "descricao"])["Receita"].sum().to_dict(),
    }


def _listar_produtos_por_receita(contexto, cliente, periodo, produtos, limite=3):
    """Os `limite` produtos de maior receita do cliente no período, como texto.

    Ordena por receita (desc) e desempata pelo nome: `produtos` chega como set,
    cuja ordem de iteração muda entre execuções — sem isso a mesma base gera
    textos de causa diferentes a cada relatório.
    """
    receitas = contexto["receita_produto"]
    ordenados = sorted(
        produtos,
        key=lambda p: (-receitas.get((cliente, periodo, p), 0.0), p),
    )
    return ", ".join(ordenados[:limite])


def _causa_provavel_migracao(contexto, cliente, periodo_anterior, periodo_atual, direcao):
    """
    Heurísticas para explicar a migração de faixa, usando os agregados
    pré-calculados em `contexto` (ver _preparar_contexto_causa_provavel) em
    vez de refiltrar o DataFrame. Critérios propositalmente rígidos: só
    retorna uma causa quando uma regra bate com folga (limiares bem acima do
    "só um pouco mais que zero"); caso contrário retorna string vazia — não
    força um "Caso Específico"/genérico só para preencher a célula. Sem
    linguagem de "estimativa": o que aparece aqui é apresentado como fato,
    não como palpite hedgeado.
    """
    chave_anterior = (cliente, periodo_anterior)
    chave_atual = (cliente, periodo_atual)

    receita_anterior = contexto["receita"].get(chave_anterior, 0.0)
    receita_atual = contexto["receita"].get(chave_atual, 0.0)

    if receita_atual == 0:
        return "Cliente parou de comprar no período atual."

    # Produto abandonado respondia por boa parte da receita (>=70%, não 40%)
    produtos_anterior = contexto["produtos"].get(chave_anterior, set())
    produtos_atual = contexto["produtos"].get(chave_atual, set())
    produtos_abandonados = produtos_anterior - produtos_atual
    if direcao == "Desceu" and produtos_abandonados:
        receita_produtos_abandonados = sum(
            contexto["receita_produto"].get((cliente, periodo_anterior, produto), 0.0)
            for produto in produtos_abandonados
        )
        if receita_anterior > 0 and receita_produtos_abandonados / receita_anterior >= 0.7:
            principal = _listar_produtos_por_receita(
                contexto, cliente, periodo_anterior, produtos_abandonados,
            )
            return f"Deixou de comprar produto(s) que respondiam por {receita_produtos_abandonados / receita_anterior * 100:.0f}% da receita anterior ({principal})."

    # Frequência de compra caiu pela metade ou mais (não só "caiu um pouco")
    meses_anterior = contexto["meses"].get(chave_anterior, 0)
    meses_atual = contexto["meses"].get(chave_atual, 0)
    if direcao == "Desceu" and meses_anterior > 0 and (meses_anterior - meses_atual) / meses_anterior >= 0.5:
        return f"Redução de pelo menos metade na frequência de compra ({meses_anterior} período(s) com compra antes, {meses_atual} depois)."

    # Ticket médio caiu 40%+ mantendo os mesmos produtos (não só 20%)
    qtd_anterior = contexto["qtd"].get(chave_anterior, 0)
    qtd_atual = contexto["qtd"].get(chave_atual, 0)
    ticket_anterior = receita_anterior / qtd_anterior if qtd_anterior else 0
    ticket_atual = receita_atual / qtd_atual if qtd_atual else 0
    if direcao == "Desceu" and ticket_anterior > 0 and ticket_atual <= ticket_anterior * 0.6:
        return f"Redução de {(1 - ticket_atual / ticket_anterior) * 100:.0f}% no ticket médio mantendo os mesmos produtos."

    if direcao == "Subiu":
        produtos_novos = produtos_atual - produtos_anterior
        if produtos_novos:
            receita_produtos_novos = sum(
                contexto["receita_produto"].get((cliente, periodo_atual, produto), 0.0)
                for produto in produtos_novos
            )
            if receita_atual > 0 and receita_produtos_novos / receita_atual >= 0.5:
                principal = _listar_produtos_por_receita(
                    contexto, cliente, periodo_atual, produtos_novos,
                )
                return f"Novo(s) produto(s) já respondem por {receita_produtos_novos / receita_atual * 100:.0f}% da receita atual ({principal})."

    return ""


# ---------------------------------------------------------------------------
# Orquestração: gera todas as análises para um conjunto de granularidades
# ---------------------------------------------------------------------------

def gerar_analises_completas(df, granularidades, clientes_excluidos=None,
                              cortes_clientes=(30.0, 50.0, 60.0), corte_produtos=80.0,
                              periodos_queda_consecutiva=2, callback_log=None, chaves_solicitadas=None,
                              desconsiderar_balcao=False, excluir_periodo_atual=True,
                              top_n_produtos=None, reducao_minima_erosao=50.0,
                              queda_minima_alerta_rs=0.0, queda_minima_erosao_rs=0.0,
                              reducao_minima_sem_venda=90.0, top_n_poder_compra=None,
                              clientes_balcao_extra=None, grupos_manuais=None,
                              erosao_somente_produtos_em_alerta=False):
    """
    Roda as análises solicitadas para cada granularidade escolhida.

    chaves_solicitadas: conjunto/lista de chaves do catálogo a calcular (ex.:
    {"top_produtos", "migracao_abc"}). Se None, calcula tudo. Análises caras
    (como migração entre faixas, que precisa da segmentação ABC) só rodam se
    pedidas — ou se outra análise pedida depender delas — evitando gastar
    tempo em algo que não vai para o relatório final. Com bases grandes
    (centenas de milhares de linhas), isso faz diferença real no tempo total.

    excluir_periodo_atual: por padrão, o período mais recente de cada
    granularidade é descartado antes de rodar qualquer análise "por
    período" (o mês/trimestre/etc. corrente costuma estar incompleto na
    base). Não afeta top_produtos/top_fabricantes, que somam a base inteira
    e não fatiam por período.

    top_n_produtos: limite de produtos em evolucao_produtos/alertas_queda e
    também em top_produtos/top_fabricantes (None = todos — ver
    tendencia_produtos). reducao_minima_erosao: % mínimo de queda para um
    cliente aparecer em erosao_clientes (ver erosao_clientes_por_produto).

    desconsiderar_balcao: tira os clientes balcão das análises POR CLIENTE
    (erosão, sem venda, queda de quantidade, correlação, churn). Em abc e
    poder de compra eles continuam aparecendo, na faixa "Balcão" própria. Os
    relatórios por produto sempre somam a receita de balcão: é venda real, só
    não é cliente rastreável.

    erosao_somente_produtos_em_alerta: por padrão erosão/correlação/churn olham
    a base inteira (os pisos reducao_minima_erosao/queda_minima_erosao_rs fazem
    o recorte), o que mantém "Receita Sob Risco" comparável entre períodos. Com
    True, o escopo fica restrito aos produtos que entraram em alertas_queda —
    visão mais estreita, e sensível ao top_n_produtos.

    callback_log: função opcional callback_log(mensagem) chamada a cada etapa
    concluída, para permitir feedback de progresso na interface.

    Retorna um dicionário: { granularidade: { nome_analise: DataFrame } }
    (só contém as chaves efetivamente calculadas).
    """
    def logar(mensagem):
        if callback_log:
            callback_log(mensagem)

    # Grupos manuais: unem membros numa entidade antes de qualquer análise
    # por Cliente (cortes ABC, concentrado, poder de compra, erosão, etc.).
    # Exclusões de membros individuais passam a excluir o nome do grupo.
    if grupos_manuais:
        mapa_grupos = mapa_cliente_para_grupo_manual(grupos_manuais)
        df = aplicar_grupos_manuais_em_cliente(df, grupos_manuais)
        if clientes_excluidos:
            clientes_excluidos = list({
                mapa_grupos.get(c, c) for c in clientes_excluidos
            })
        if clientes_balcao_extra:
            clientes_balcao_extra = list({
                mapa_grupos.get(c, c) for c in clientes_balcao_extra
            })

    # Exclusões da prévia de clientes aplicam a TODAS as análises.
    if clientes_excluidos:
        df = df[~df["Cliente"].isin(set(clientes_excluidos))]

    todas_as_chaves = {
        "top_produtos", "top_fabricantes", "comparativo_receita", "poder_compra_clientes",
        "evolucao_produtos", "alertas_queda", "erosao_clientes", "sem_venda", "abc", "abc_produtos",
        "migracao_abc", "migracao_resumo", "migracao_score_clientes",
        "produtos_em_alta", "produtos_em_queda", "clientes_queda_qtd",
        "correlacao_produto_cliente", "impacto_financeiro_churn",
    }
    pedidas = todas_as_chaves if chaves_solicitadas is None else set(chaves_solicitadas)

    def precisa(*chaves):
        return any(chave in pedidas for chave in chaves)

    # Resolve dependências entre análises (ex.: migração depende da
    # segmentação ABC completa, não do recorte top-5 exibido no relatório;
    # correlação e impacto de churn dependem da erosão de clientes) para
    # nunca pular um cálculo que outro item pedido ainda precisa, mas também
    # nunca calcular o que ninguém pediu.
    precisa_tendencia = precisa(
        "evolucao_produtos", "alertas_queda", "erosao_clientes",
        "correlacao_produto_cliente", "impacto_financeiro_churn",
    )
    precisa_erosao = precisa("erosao_clientes", "correlacao_produto_cliente", "impacto_financeiro_churn")
    precisa_migracao = precisa("migracao_abc", "migracao_resumo", "migracao_score_clientes")
    precisa_abc = precisa("abc") or precisa_migracao

    resultados = {}
    for granularidade in granularidades:
        analises = {}

        col_periodo = COLUNA_PERIODO[granularidade]
        periodos_ordenados = _ordenar_periodos(df[col_periodo].unique(), granularidade)
        if excluir_periodo_atual and len(periodos_ordenados) > 1:
            df_periodo = df[df[col_periodo] != periodos_ordenados[-1]]
            logar(f"[{granularidade}] Período mais recente ({periodos_ordenados[-1]}) excluído por padrão (provavelmente incompleto).")
        else:
            df_periodo = df

        # Análises POR CLIENTE respeitam o filtro de balcão; as por produto
        # continuam com a base cheia (ver docstring).
        if desconsiderar_balcao:
            df_cliente = df_periodo[
                ~mascara_clientes_balcao(df_periodo["Cliente"], clientes_balcao_extra)
            ]
        else:
            df_cliente = df_periodo

        evolucao, alertas = (None, None)
        if precisa_tendencia:
            logar(f"[{granularidade}] Calculando tendência de produtos...")
            evolucao, alertas = tendencia_produtos(
                df_periodo, granularidade, periodos_queda_consecutiva, top_n=top_n_produtos,
                queda_minima_rs=queda_minima_alerta_rs,
            )
            if precisa("evolucao_produtos"):
                analises["evolucao_produtos"] = evolucao
            if precisa("alertas_queda"):
                analises["alertas_queda"] = alertas

        erosao = None
        if precisa_erosao:
            logar(f"[{granularidade}] Calculando erosão de clientes por produto...")
            # None = base inteira. Com o escopo restrito, uma lista vazia
            # (nenhum alerta) resulta em erosão vazia — nunca em "todos".
            produtos_alvo = None
            if erosao_somente_produtos_em_alerta:
                produtos_alvo = alertas["descricao"].tolist() if alertas is not None else []
            erosao = erosao_clientes_por_produto(
                df_cliente, granularidade, produtos_alvo=produtos_alvo,
                reducao_minima_percentual=reducao_minima_erosao,
                queda_minima_rs=queda_minima_erosao_rs,
            )
            if precisa("erosao_clientes"):
                analises["erosao_clientes"] = erosao

        if precisa("sem_venda"):
            logar(f"[{granularidade}] Calculando clientes sem venda...")
            analises["sem_venda"] = sem_venda_clientes(
                df_cliente, granularidade, reducao_minima_percentual=reducao_minima_sem_venda,
            )

        abc = None
        if precisa_abc:
            logar(f"[{granularidade}] Classificando clientes por faixa de faturamento...")
            # Sempre sem corte aqui (top_clientes_por_grupo=None): migração
            # precisa ver TODOS os clientes/grupos pra detectar corretamente quem
            # mudou de faixa. O corte "top 5" é aplicado só na hora de expor
            # a chave "abc" do relatório, não na classificação em si.
            # Grupos manuais já foram aplicados no df no início desta função.
            abc = classificar_abc(
                df_periodo, granularidade, clientes_excluidos, cortes_clientes,
                desconsiderar_balcao=desconsiderar_balcao, top_clientes_por_grupo=None,
                clientes_balcao_extra=clientes_balcao_extra,
            )
            if precisa("abc"):
                analises["abc"] = _limitar_top_por_grupo(abc, 5)

        if precisa("poder_compra_clientes"):
            logar(f"[{granularidade}] Calculando poder de compra agregado dos clientes...")
            analises["poder_compra_clientes"] = poder_compra_agregado(
                df_periodo, clientes_excluidos, cortes_clientes,
                desconsiderar_balcao=desconsiderar_balcao, top_n=top_n_poder_compra,
                clientes_balcao_extra=clientes_balcao_extra,
            )

        if precisa("abc_produtos"):
            logar(f"[{granularidade}] Classificando produtos por faixa de faturamento...")
            analises["abc_produtos"] = classificar_produtos_por_receita(df_periodo, granularidade, corte_produtos)

        if precisa_migracao:
            logar(f"[{granularidade}] Calculando migração de clientes entre faixas...")
            migracao = migracao_abc(df_periodo, abc, granularidade)
            if precisa("migracao_abc"):
                analises["migracao_abc"] = migracao
                # Resumo e score não têm checkbox próprio no catálogo — são
                # subprodutos automáticos sempre que "migracao_abc" é pedido.
                analises["migracao_resumo"] = resumo_migracao(migracao)
                analises["migracao_score_clientes"] = pontuacao_migracao_clientes(migracao, abc, granularidade)

        if precisa("produtos_em_alta", "produtos_em_queda"):
            logar(f"[{granularidade}] Montando boletim de produtos em alta/queda...")
            produtos_alta, produtos_queda = produtos_alta_e_queda(df_periodo, granularidade)
            if precisa("produtos_em_alta"):
                analises["produtos_em_alta"] = produtos_alta
            if precisa("produtos_em_queda"):
                analises["produtos_em_queda"] = produtos_queda

        if precisa("clientes_queda_qtd"):
            logar(f"[{granularidade}] Montando boletim de clientes em queda de quantidade...")
            analises["clientes_queda_qtd"] = clientes_queda_quantidade(df_cliente, granularidade)

        if precisa("correlacao_produto_cliente"):
            logar(f"[{granularidade}] Calculando correlação produto x cliente...")
            analises["correlacao_produto_cliente"] = correlacao_produto_cliente(df_cliente, erosao, alertas, granularidade)

        if precisa("impacto_financeiro_churn"):
            logar(f"[{granularidade}] Calculando impacto financeiro do churn...")
            analises["impacto_financeiro_churn"] = impacto_financeiro_churn(df_cliente, erosao, granularidade)

        # Alinhados ao resto do relatório: mesmo recorte de período
        # (excluir_periodo_atual) e mesmo limite de itens (top_n_produtos).
        limite_top = 20 if top_n_produtos is None else int(top_n_produtos)
        if precisa("comparativo_receita"):
            logar(f"[{granularidade}] Montando comparativo de receita com o ano anterior...")
            analises["comparativo_receita"] = comparativo_receita_ano_anterior(df_periodo, granularidade)

        if precisa("top_produtos"):
            analises["top_produtos"] = top_produtos(df_periodo, limite_top)
        if precisa("top_fabricantes"):
            analises["top_fabricantes"] = top_fabricantes(df_periodo, limite_top)

        resultados[granularidade] = analises
        logar(f"[{granularidade}] Concluído.")
    return resultados
