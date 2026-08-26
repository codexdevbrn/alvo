"""Cálculos e contrato do painel PDF individual de cliente."""

from pathlib import Path

import pandas as pd
import pytest
from fastapi import HTTPException

import main
from relatorio_cliente import (
    gerar_painel_cliente_pdf,
    montar_dados_painel_cliente,
)


def _linha(
    periodo: str,
    produto: str,
    receita: float,
    qtd: int,
    *,
    cliente: str = "Cliente A",
    loja: str = "Matriz",
) -> dict:
    return {
        "Cliente": cliente,
        "Periodo_Mensal": periodo,
        "Receita": receita,
        "QTD": qtd,
        "descricao": produto,
        "Loja": loja,
    }


def _base_painel() -> pd.DataFrame:
    linhas: list[dict] = []
    for mes in ("2026-06", "2026-07"):
        linhas += [
            _linha(mes, "Shampoo", 100, 2),
            _linha(mes, "Estável", 100, 2),
            _linha(mes, "Caiu", 100, 2),
        ]
    linhas += [
        _linha("2026-08", "Shampoo", 150, 3),
        _linha("2026-08", "Estável", 90, 2),
        _linha("2026-08", "Novo", 80, 1, loja="Filial"),
        # Outra pessoa confirma agosto como último período global.
        _linha("2026-08", "Outro", 10, 1, cliente="Cliente B"),
    ]
    return pd.DataFrame(linhas)


def test_painel_compara_meses_e_classifica_produtos():
    dados = montar_dados_painel_cliente(_base_painel(), "Cliente A", meses_historico=10)

    assert dados["data_referencia"] == "2026-08-01"
    assert dados["meses_media"] == 2
    assert dados["receita_atual"] == 320
    assert dados["receita_anterior"] == 300
    assert dados["receita_media"] == 300
    subiram = {item["produto"]: item for item in dados["produtos"]["subiram"]}
    mantiveram = {item["produto"]: item for item in dados["produtos"]["mantiveram"]}
    cairam = {item["produto"]: item for item in dados["produtos"]["cairam"]}
    assert subiram["Shampoo"]["variacao"] == 50
    assert subiram["Novo"]["variacao"] is None
    assert mantiveram["Estável"]["variacao"] == -10
    assert cairam["Caiu"]["variacao"] == -100
    assert {item["loja"] for item in dados["lojas"]} == {"Matriz", "Filial"}


def test_painel_funciona_sem_data_diaria():
    base = pd.DataFrame({
        "Cliente": ["Cliente A"],
        "Receita": [100],
        "QTD": [1],
        "descricao": ["Produto"],
        "Periodo_Mensal": ["2026-08"],
    })

    dados = montar_dados_painel_cliente(base, "Cliente A")

    assert dados["periodo_atual"] == "2026-08"
    assert dados["receita_atual"] == 100


def test_pdf_gera_uma_pagina_valida(tmp_path):
    dados = montar_dados_painel_cliente(_base_painel(), "Cliente A")
    saida = tmp_path / "painel-cliente.pdf"

    gerar_painel_cliente_pdf(
        saida, dados, empresa="Empresa Teste", loja="Todas as lojas", posicao=1, total=3,
    )

    conteudo = saida.read_bytes()
    assert conteudo.startswith(b"%PDF")
    assert len(conteudo) > 3_000


def test_endpoint_recusa_cliente_sem_tag_monitorada(monkeypatch):
    monkeypatch.setattr(main, "_ler_tags_clientes", lambda *_args, **_kwargs: {
        "tags": {},
        "catalogo": [{
            "id": "alerta", "ativa": True, "entra_na_analise": True,
        }],
    })

    with pytest.raises(HTTPException) as erro:
        main.exportar_painel_cliente(
            main.PainelClienteBody(empresa="Empresa Teste", cliente="Cliente A"),
            usuario="teste",
        )

    assert erro.value.status_code == 400
    assert "tag de monitoramento" in erro.value.detail


def test_endpoint_gera_pdf_para_cliente_monitorado(monkeypatch):
    monkeypatch.setattr(main, "_ler_tags_clientes", lambda *_args, **_kwargs: {
        "tags": {"Cliente A": ["alerta"]},
        "catalogo": [{
            "id": "alerta", "ativa": True, "entra_na_analise": True,
        }],
    })
    monkeypatch.setattr(main, "_carregar_base", lambda *_args, **_kwargs: (_base_painel(), 0))

    resposta = main.exportar_painel_cliente(
        main.PainelClienteBody(
            empresa="Empresa Teste", cliente="Cliente A", posicao=1, total=1,
        ),
        usuario="teste",
    )
    caminho = Path(resposta.path)
    try:
        assert resposta.media_type == "application/pdf"
        assert caminho.read_bytes().startswith(b"%PDF")
    finally:
        caminho.unlink(missing_ok=True)
