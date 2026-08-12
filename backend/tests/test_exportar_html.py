import os
import sys

import pandas as pd

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from exportar_html import exportar_relatorio_html


def test_html_exportado_tem_ordenacao_offline_e_valores_brutos(tmp_path):
    caminho = tmp_path / "relatorio.html"
    tabela = pd.DataFrame(
        {
            "Cliente": ["Cliente 10", "Cliente 2", None],
            "Receita": [10.5, 2.25, None],
        }
    )

    exportar_relatorio_html(
        caminho,
        {"Mensal": {"top_clientes": tabela}},
    )

    html = caminho.read_text(encoding="utf-8")
    assert '<table data-sortable="true">' in html
    assert 'class="sort-btn" data-column="1" data-type="number"' in html
    assert 'data-sort-value="10.5"' in html
    assert 'data-sort-empty="1"' in html
    assert "localeCompare" in html
    assert "aria-sort" in html


def test_html_exportado_usa_pagina_larga_sem_rolagem_horizontal(tmp_path):
    caminho = tmp_path / "relatorio-largo.html"
    tabela = pd.DataFrame(
        {
            "Cliente com identificação extensa": ["Cliente com um nome muito comprido"],
            "Receita do período anterior": [1234.56],
            "Receita do período atual": [1456.78],
        }
    )

    exportar_relatorio_html(
        caminho,
        {"Mensal": {"comparativo_receita": tabela}},
    )

    html = caminho.read_text(encoding="utf-8")
    assert "max-width: 1920px" in html
    assert "overflow-y: auto; overflow-x: hidden" in html
    assert "overflow-wrap: anywhere" in html
