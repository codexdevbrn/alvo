"""
Exportação Excel dos relatórios do motor de análise — extraído de
analisador-monitoria-2d/app.py (mesmas funções, sem nada de Tkinter).
"""

import os
from datetime import datetime

import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter
from openpyxl.drawing.image import Image as ImagemExcel

from engine.recursos import CAMINHO_LOGO, CAMINHO_LOGO_ICONE, NOME_SISTEMA, NOME_EMPRESA

COR_CABECALHO = "1F4E78"

# Catálogo de relatórios prontos, agrupados por categoria. Cada item mapeia um
# título de negócio para as chaves internas calculadas por
# analise_funil.gerar_analises_completas.
CATALOGO_RELATORIOS = [
    ("Vendas", [
        ("top_fabricantes", "Venda por Fabricante (Top Fabricantes)"),
        ("top_produtos", "Venda por Produto (Top Produtos)"),
    ]),
    ("Segmentação e Poder de Compra", [
        ("abc", "Faturamento e Segmentação de Clientes (ABC)"),
        ("poder_compra_clientes", "Poder de Compra por Cliente (3 maiores meses)"),
        ("migracao_abc", "Migração de Grupo (inclui resumo e score por cliente)"),
    ]),
    ("Tendências e Alertas", [
        ("evolucao_produtos", "Tendência de Produtos"),
        ("alertas_queda", "Alertas de Queda Consecutiva"),
        ("erosao_clientes", "Erosão de Clientes por Produto"),
        ("sem_venda", "Sem Venda"),
    ]),
    ("Boletins", [
        ("produtos_em_alta", "Boletim: Produtos em Alta"),
        ("produtos_em_queda", "Boletim: Produtos em Queda"),
        ("clientes_queda_qtd", "Boletim: Clientes em Queda de Quantidade"),
        ("correlacao_produto_cliente", "Boletim: Correlação Produto x Cliente"),
        ("impacto_financeiro_churn", "Boletim: Impacto Financeiro do Churn"),
    ]),
]

NOMES_ANALISE = {
    "top_produtos": "Top_Produtos",
    "top_fabricantes": "Top_Fabricantes",
    "poder_compra_clientes": "Poder_Compra_Clientes",
    "evolucao_produtos": "Evolucao_Produtos",
    "alertas_queda": "Alertas_Queda",
    "erosao_clientes": "Erosao_Clientes",
    "sem_venda": "Sem_Venda",
    "abc": "ABC_Clientes",
    "abc_produtos": "ABC_Produtos",
    "migracao_abc": "Migracao_ABC",
    "migracao_resumo": "Migracao_Resumo",
    "migracao_score_clientes": "Migracao_Score_Clientes",
    "produtos_em_alta": "Produtos_Em_Alta",
    "produtos_em_queda": "Produtos_Em_Queda",
    "clientes_queda_qtd": "Clientes_Queda_Qtd",
    "correlacao_produto_cliente": "Correlacao_Prod_Cliente",
    "impacto_financeiro_churn": "Impacto_Financeiro_Churn",
}

COLUNAS_MOEDA_POR_ANALISE = {
    "top_produtos": ["Receita"],
    "top_fabricantes": ["Receita"],
    "poder_compra_clientes": ["Poder_De_Compra"],
    "evolucao_produtos": ["Receita", "Receita_Periodo_Anterior"],
    "alertas_queda": ["Receita_Ultimo_Periodo", "Receita_Primeiro_Periodo"],
    "erosao_clientes": ["Receita", "Receita_Periodo_Anterior", "Reducao_Receita"],
    "sem_venda": ["Receita", "Receita_Periodo_Anterior", "Reducao_Receita"],
    "abc": ["Receita", "Renuncia", "Renuncia_Acumulada"],
    "abc_produtos": ["Receita", "Renuncia", "Renuncia_Acumulada"],
    "migracao_abc": [],
    "migracao_resumo": [],
    "migracao_score_clientes": [],
    "produtos_em_alta": ["Receita_Periodo_Anterior", "Receita_Periodo_Atual", "Total_Ano_Atual"],
    "produtos_em_queda": ["Receita_Periodo_Anterior", "Receita_Periodo_Atual", "Total_Ano_Atual"],
    "clientes_queda_qtd": ["Perda_Receita"],
    "correlacao_produto_cliente": ["Reducao_Receita"],
    "impacto_financeiro_churn": ["Receita_Sob_Risco"],
}


def _ajustar_largura_colunas(planilha):
    for coluna in planilha.columns:
        maior_comprimento = 0
        letra_coluna = get_column_letter(coluna[0].column)
        for celula in coluna:
            valor = str(celula.value) if celula.value is not None else ""
            maior_comprimento = max(maior_comprimento, len(valor))
        planilha.column_dimensions[letra_coluna].width = min(maior_comprimento + 2, 45)


def _formatar_cabecalho(planilha):
    preenchimento = PatternFill(start_color=COR_CABECALHO, end_color=COR_CABECALHO, fill_type="solid")
    fonte = Font(color="FFFFFF", bold=True)
    for celula in planilha[1]:
        celula.fill = preenchimento
        celula.font = fonte
        celula.alignment = Alignment(horizontal="center")


def _inserir_logo(planilha, coluna_ancora, linha_ancora=1, altura_pixels=34):
    """Insere a marca da 2D Consultores em miniatura, sem sobrepor os dados."""
    if not os.path.exists(CAMINHO_LOGO_ICONE):
        return
    try:
        imagem = ImagemExcel(CAMINHO_LOGO_ICONE)
        proporcao = imagem.width / imagem.height
        imagem.height = altura_pixels
        imagem.width = altura_pixels * proporcao
        planilha.add_image(imagem, f"{get_column_letter(coluna_ancora)}{linha_ancora}")
    except Exception:
        pass  # ausência da logo não deve impedir a geração do relatório


def _escrever_dataframe(workbook, nome_aba, df, colunas_moeda=None):
    if nome_aba in workbook.sheetnames:
        planilha = workbook[nome_aba]
    else:
        planilha = workbook.create_sheet(nome_aba)

    colunas_moeda = colunas_moeda or []
    df_para_exportar = df.reset_index() if df.index.name or isinstance(df.index, pd.MultiIndex) else df

    planilha.append(list(map(str, df_para_exportar.columns)))
    for _, linha in df_para_exportar.iterrows():
        planilha.append(list(linha))

    for indice_coluna, nome_coluna in enumerate(df_para_exportar.columns, start=1):
        if nome_coluna in colunas_moeda:
            for linha in range(2, planilha.max_row + 1):
                planilha.cell(row=linha, column=indice_coluna).number_format = 'R$ #,##0.00'

    _formatar_cabecalho(planilha)
    _ajustar_largura_colunas(planilha)
    _inserir_logo(planilha, coluna_ancora=len(df_para_exportar.columns) + 2)
    return planilha


def _criar_capa(workbook, resultados_analise, nome_usuario="", nome_empresa=""):
    """Primeira aba do relatório: logo, identidade da empresa e sumário do que foi gerado."""
    capa = workbook.create_sheet("Capa", 0)
    capa.sheet_view.showGridLines = False
    capa.column_dimensions["A"].width = 4
    capa.column_dimensions["B"].width = 60

    if os.path.exists(CAMINHO_LOGO):
        try:
            imagem = ImagemExcel(CAMINHO_LOGO)
            proporcao = imagem.width / imagem.height
            imagem.height = 130
            imagem.width = 130 * proporcao
            capa.add_image(imagem, "B2")
        except Exception:
            pass

    capa["B10"] = NOME_SISTEMA
    capa["B10"].font = Font(size=20, bold=True, color=COR_CABECALHO)
    capa["B11"] = NOME_EMPRESA
    capa["B11"].font = Font(size=12, color="666666")

    linha_info = 13
    if nome_empresa:
        capa[f"B{linha_info}"] = f"Empresa analisada: {nome_empresa}"
        capa[f"B{linha_info}"].font = Font(size=13, bold=True, color=COR_CABECALHO)
        linha_info += 1
    if nome_usuario:
        capa[f"B{linha_info}"] = f"Gerado por: {nome_usuario}"
        capa[f"B{linha_info}"].font = Font(size=10, italic=True, color="666666")
        linha_info += 1
    capa[f"B{linha_info}"] = f"Relatório gerado em {datetime.now().strftime('%d/%m/%Y às %H:%M')}"
    capa[f"B{linha_info}"].font = Font(size=10, italic=True, color="666666")

    linha = linha_info + 3
    capa[f"B{linha}"] = "Granularidades incluídas neste relatório:"
    capa[f"B{linha}"].font = Font(bold=True)
    for granularidade in resultados_analise.keys():
        linha += 1
        capa[f"B{linha}"] = f"•  {granularidade}"
    return capa


def exportar_relatorio_excel(caminho_saida, resultados_analise, relatorios_personalizados=None, nome_usuario="", nome_empresa=""):
    """
    Gera o arquivo .xlsx com uma aba por (análise x granularidade), formatado
    com cabeçalhos destacados, moeda BRL, largura de coluna automática e a
    logo da empresa em cada aba (mais uma capa de apresentação).
    """
    workbook = Workbook()
    workbook.remove(workbook.active)  # remove a aba padrão vazia
    _criar_capa(workbook, resultados_analise, nome_usuario, nome_empresa)

    for granularidade, analises in resultados_analise.items():
        for chave_analise, df_analise in analises.items():
            nome_base = NOMES_ANALISE.get(chave_analise, chave_analise)
            nome_aba = f"{nome_base}_{granularidade}"[:31]  # limite do Excel
            if df_analise is None or df_analise.empty:
                planilha = workbook.create_sheet(nome_aba)
                planilha.append(["Sem dados para esta análise/granularidade."])
                continue
            _escrever_dataframe(workbook, nome_aba, df_analise, COLUNAS_MOEDA_POR_ANALISE.get(chave_analise))

    if relatorios_personalizados:
        for nome_relatorio, tabela in relatorios_personalizados.items():
            nome_aba = f"Custom_{nome_relatorio}"[:31]
            _escrever_dataframe(workbook, nome_aba, tabela)

    if len(workbook.sheetnames) <= 1:
        workbook.create_sheet("Sem_Dados")

    workbook.save(caminho_saida)
