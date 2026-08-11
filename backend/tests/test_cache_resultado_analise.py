"""Testes do cache curto usado entre gerar e exportar relatórios."""

import os
import sys
from pathlib import Path

import pandas as pd
import pytest
from fastapi import Response

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import main as api


@pytest.fixture(autouse=True)
def limpar_cache():
    """Cada teste começa sem resultado herdado de outro cenário."""
    with api._cache_resultado_analise_lock:
        api._cache_resultado_analise.clear()
    yield
    with api._cache_resultado_analise_lock:
        api._cache_resultado_analise.clear()


def parametros(chaves=None, **alteracoes):
    """Monta parâmetros mínimos, iguais entre gerar e exportar."""
    dados = {
        "granularidades": ["Mensal"],
        "chaves_selecionadas": chaves or ["top_produtos"],
        "empresa": "Empresa Teste",
    }
    dados.update(alteracoes)
    return api.ParametrosAnalise(**dados)


def resultados_exemplo():
    """Inclui relatórios comuns e subprodutos automáticos da migração."""
    tabela = pd.DataFrame({"nome": ["A"], "receita": [100.0]})
    return {
        "Mensal": {
            "top_produtos": tabela,
            "top_fabricantes": tabela,
            "migracao_abc": tabela,
            "migracao_resumo": tabela,
            "migracao_score_clientes": tabela,
        }
    }


def test_reutiliza_subconjunto_sem_copiar_dataframe():
    origem = resultados_exemplo()
    geracao = parametros(["top_produtos", "top_fabricantes"])
    token = api._guardar_resultado_analise("admin", geracao, origem)

    exportacao = parametros(["top_produtos"])
    obtido = api._obter_resultado_analise(token, "admin", exportacao)

    assert list(obtido["Mensal"]) == ["top_produtos"]
    assert obtido["Mensal"]["top_produtos"] is origem["Mensal"]["top_produtos"]


def test_mantem_subprodutos_automaticos_da_migracao():
    origem = resultados_exemplo()
    geracao = parametros(["migracao_abc"])
    token = api._guardar_resultado_analise("admin", geracao, origem)

    obtido = api._obter_resultado_analise(token, "admin", geracao)

    assert set(obtido["Mensal"]) == {
        "migracao_abc", "migracao_resumo", "migracao_score_clientes",
    }


def test_recusa_token_de_outro_usuario_ou_parametros_alterados():
    geracao = parametros(["top_produtos"])
    token = api._guardar_resultado_analise("admin", geracao, resultados_exemplo())

    assert api._obter_resultado_analise(token, "outro", geracao) is None
    assert api._obter_resultado_analise(
        token, "admin", parametros(["top_produtos"], corte_produtos=70.0),
    ) is None


def test_recusa_relatorio_que_nao_foi_calculado():
    geracao = parametros(["top_produtos"])
    token = api._guardar_resultado_analise("admin", geracao, resultados_exemplo())

    assert api._obter_resultado_analise(
        token, "admin", parametros(["top_fabricantes"]),
    ) is None


def test_nao_cacheia_resultado_acima_do_teto(monkeypatch):
    monkeypatch.setattr(api, "_CACHE_RESULTADO_ANALISE_MAX_BYTES", 1)

    token = api._guardar_resultado_analise(
        "admin", parametros(), resultados_exemplo(),
    )

    assert token is None
    assert not api._cache_resultado_analise


def test_analisar_entrega_token_e_exportar_evitaria_recalculo(monkeypatch):
    """Cobre o contrato HTTP usado pelo frontend entre as duas chamadas."""
    geracao = parametros(["top_produtos"])
    origem = resultados_exemplo()
    monkeypatch.setattr(api, "_rodar_analises", lambda _: origem)

    resposta_http = Response()
    api.analisar(geracao, resposta_http, "admin")
    token = resposta_http.headers.get("X-Resultado-Analise")
    assert token

    def nao_pode_recalcular(_):
        raise AssertionError("exportação tentou recalcular uma análise cacheada")

    def exportar_html_falso(caminho, resultados, **_):
        assert resultados["Mensal"]["top_produtos"] is origem["Mensal"]["top_produtos"]
        Path(caminho).write_text("ok", encoding="utf-8")

    monkeypatch.setattr(api, "_rodar_analises", nao_pode_recalcular)
    monkeypatch.setattr(api, "exportar_relatorio_html", exportar_html_falso)

    arquivo = api.exportar("html", geracao, "admin", token)
    try:
        assert arquivo.headers["x-resultado-cache"] == "HIT"
    finally:
        Path(arquivo.path).unlink(missing_ok=True)


def test_carregar_base_somente_leitura_nao_duplica_dataframe(monkeypatch):
    """Rotas de abertura podem compartilhar a base; callers mutáveis seguem isolados."""
    origem = pd.DataFrame({"Loja": ["A"], "Receita": [100.0]})
    monkeypatch.setattr(api, "_carregar_base_empresa", lambda _: (origem, 0))

    compartilhado, _ = api._carregar_base("Empresa Teste", copiar=False)
    defensivo, _ = api._carregar_base("Empresa Teste")

    assert compartilhado is origem
    assert defensivo is not origem


def test_cache_de_base_mantem_so_empresa_mais_recente():
    """Limite de uma base evita acumular vários DataFrames gigantes em RAM."""
    cache = api.OrderedDict()
    api._lru_set(cache, "A", {"df": object()}, max_size=api._CACHE_BASE_EMPRESA_MAX)
    api._lru_set(cache, "B", {"df": object()}, max_size=api._CACHE_BASE_EMPRESA_MAX)

    assert list(cache) == ["B"]
