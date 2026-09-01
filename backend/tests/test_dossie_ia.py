"""Contrato do gerador diário de análises da carteira."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import date, datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from openpyxl import Workbook

import dossie_ia
from dossie_ia import (
    ClienteCarteira,
    ErroDossieIA,
    ErroOllama,
    carregar_clientes,
    chamar_ollama,
    documento_sucesso,
    executar_lote,
    montar_contexto_prisma,
    normalizar_chave_empresa,
    validar_markdown_ia,
)


NARRATIVA_VALIDA = """## Risco executivo
**Nível:** Médio

## Resumo
Receita exige acompanhamento [PRISMA].

## Evidências
- Histórico comercial oscilou [PRISMA].
- Dossiê registra pauta pendente [CRM].

## Tendência comercial
Tendência estável, com ressalvas [PRISMA].

## Estoque e liquidez
- Estoque exige revisão por cobertura [PRISMA].

## Qualidade dos dados
- Nenhuma anomalia comprovada no contexto [PRISMA].

## Alertas
- Validar queda recente [PRISMA].

## Oportunidades
- Revisar mix [CRM+PRISMA].

## Ações recomendadas
- Confirmar plano em reunião [CRM].

## Próxima pauta
- Receita, mix e responsáveis [CRM+PRISMA].
"""


def _criar_database(caminho: Path, clientes: list[tuple[str, str]]) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "Clientes"
    ws.append(["id", "empresa", "status"])
    for client_id, empresa in clientes:
        ws.append([client_id, empresa, "Ativo"])
    wb.save(caminho)
    wb.close()


def _summary() -> dict:
    periodos = [202507, 202508, 202607, 202608]
    return {
        "maps": {
            "p": periodos,
            "s": ["Matriz"],
            "c": ["Comprador A", "Comprador B"],
            "m": ["Fabricante A", "Fabricante B"],
            "d": ["Produto A", "Produto B"],
            "r": ["A", "B"],
        },
        "rows": [
            [0, 0, 0, 0, 0, 0, 100.0, 10],
            [1, 0, 1, 1, 1, 1, 80.0, 8],
            [2, 0, 0, 0, 0, 0, 200.0, 20],
            [2, 0, 1, 1, 1, 1, 50.0, 5],
            [3, 0, 0, 0, 0, 0, 30.0, 3],
        ],
        "monthly": [
            {"name": "jul/25", "rev": 100.0, "pid": 202507, "year": 2025},
            {"name": "ago/25", "rev": 80.0, "pid": 202508, "year": 2025},
            {"name": "jul/26", "rev": 250.0, "pid": 202607, "year": 2026},
            {"name": "ago/26", "rev": 30.0, "pid": 202608, "year": 2026},
        ],
        "updated_at": "27/08/2026 02:30",
        "kpis": {"rev": 460.0, "qty": 46, "avg": 92.0, "cnt": 5},
    }


def _criar_empresa(trabalho: Path, nome: str = "Empresa Ágil") -> Path:
    pasta = trabalho / nome
    pasta.mkdir(parents=True)
    (pasta / "summary_dashboard.json").write_text(
        json.dumps(_summary(), ensure_ascii=False), encoding="utf-8",
    )
    return pasta


def _criar_liquidez(pasta: Path) -> None:
    (pasta / "Liquidez_Estoque.csv").write_text(
        "\n".join([
            "Loja;NOME_FABRICANTE;descricao;CODIGO_INTERNO_PRODUTO;CODIGO_REFERENCIA_PRODUTO;Qtd_estoque;Preço_médio_de_venda;Preço_médio_cmv;Último_custo",
            "Matriz;Fab A;Produto crítico;1;SKU-1;0;20;10;8",
            "Matriz;Fab B;Produto parado;2;SKU-2;100;30;15;12",
        ]),
        encoding="utf-8",
    )
    (pasta / "Liquidez_Vendas.csv").write_text(
        "\n".join([
            "Nome_Loja;NOME_FABRICANTE;descricao;CODIGO_INTERNO_PRODUTO;CODIGO_REFERENCIA_PRODUTO;Ano;Mês;QTD",
            "Matriz;Fab A;Produto crítico;1;SKU-1;2026;julho;12",
            "Matriz;Fab B;Produto parado;2;SKU-2;2026;julho;1",
        ]),
        encoding="utf-8",
    )


def _montar_cenario(tmp_path: Path):
    client_id = str(uuid4())
    database = tmp_path / "database_dev.xlsx"
    dossie = tmp_path / "dossie"
    trabalho = tmp_path / "trabalho"
    dossie.mkdir()
    trabalho.mkdir()
    _criar_database(database, [(client_id, "Empresa Ágil")])
    empresa = _criar_empresa(trabalho)
    (dossie / f"{client_id}-crm.md").write_text("# CRM\nPauta pendente.", encoding="utf-8")
    return client_id, database, dossie, trabalho, empresa


def test_normalizacao_e_leitura_do_workbook(tmp_path):
    client_id = str(uuid4())
    database = tmp_path / "database.xlsx"
    _criar_database(database, [(client_id, "  Empresa Ágil / SP ")])

    clientes = carregar_clientes(database)

    assert clientes == [ClienteCarteira(client_id, "Empresa Ágil / SP")]
    assert normalizar_chave_empresa("Empresa Ágil / SP") == "empresaagilsp"


def test_rejeita_client_id_duplicado(tmp_path):
    client_id = str(uuid4())
    database = tmp_path / "database.xlsx"
    _criar_database(database, [(client_id, "A"), (client_id, "B")])

    with pytest.raises(ErroDossieIA, match="duplicado") as erro:
        carregar_clientes(database)

    assert erro.value.codigo == "client_id_duplicado"


def test_contexto_usa_ultimo_mes_fechado(tmp_path):
    empresa = _criar_empresa(tmp_path)
    mtime = (empresa / "summary_dashboard.json").stat().st_mtime

    contexto = montar_contexto_prisma(
        "Empresa Ágil",
        empresa,
        fresh_since=datetime.fromtimestamp(mtime - 1, tz=timezone.utc),
        hoje=date(2026, 8, 27),
    )

    assert contexto["periodo_ranking"] == 202607
    assert contexto["periodo_ranking_parcial"] is False
    assert contexto["top_clientes_compradores"][0]["nome"] == "Comprador A"
    assert contexto["top_clientes_compradores"][0]["receita"] == 200.0
    assert contexto["qualidade_dados"]["ultimo_periodo_parcial"] is True


def test_contexto_inclui_estoque_liquidez_compacto(tmp_path):
    empresa = _criar_empresa(tmp_path)
    _criar_liquidez(empresa)

    contexto = montar_contexto_prisma("Empresa Ágil", empresa, hoje=date(2026, 8, 27))
    estoque = contexto["estoque_liquidez"]
    documento = documento_sucesso(
        ClienteCarteira(str(uuid4()), "Empresa Ágil"),
        NARRATIVA_VALIDA,
        contexto,
        modelo="teste",
        crm_mtime=0,
    )

    assert estoque["disponivel"] is True
    assert estoque["resumo"]["produtos"] == 2
    assert estoque["resumo"]["ruptura"] == 1
    assert estoque["rupturas_prioritarias"][0]["sku"] == "SKU-1"
    assert "### Estoque e liquidez" in documento
    assert "Rupturas prioritárias" in documento
    assert "SKU-1" in documento


def test_contexto_recusa_summary_antigo(tmp_path):
    empresa = _criar_empresa(tmp_path)
    futuro = datetime.now(timezone.utc).timestamp() + 60

    with pytest.raises(ErroDossieIA) as erro:
        montar_contexto_prisma(
            "Empresa Ágil", empresa,
            fresh_since=datetime.fromtimestamp(futuro, tz=timezone.utc),
        )

    assert erro.value.codigo == "summary_desatualizado"


def test_validador_recusa_html_e_aceita_contrato():
    validar_markdown_ia(NARRATIVA_VALIDA)

    with pytest.raises(ErroDossieIA) as erro:
        validar_markdown_ia(NARRATIVA_VALIDA + "\n<script>alert(1)</script>")

    assert erro.value.codigo == "saida_insegura"


def test_validador_recusa_citacao_crm_quando_fonte_indisponivel():
    with pytest.raises(ErroDossieIA) as erro:
        validar_markdown_ia(NARRATIVA_VALIDA, crm_disponivel=False)

    assert erro.value.codigo == "saida_fonte_indisponivel"


def test_dry_run_nao_chama_api_nem_grava(tmp_path):
    client_id, database, dossie, trabalho, _empresa = _montar_cenario(tmp_path)

    resultados = executar_lote(
        database=database, dossie=dossie, trabalho=trabalho,
        api_key=None, dry_run=True,
    )

    assert resultados[0].status == "pronto"
    assert not (dossie / f"{client_id}-analise.md").exists()


def test_lote_gera_md_e_preserva_workbook(tmp_path):
    client_id, database, dossie, trabalho, _empresa = _montar_cenario(tmp_path)
    hash_antes = hashlib.sha256(database.read_bytes()).hexdigest()

    def enviar(_mensagens, _api_key, **_kwargs):
        return NARRATIVA_VALIDA

    resultados = executar_lote(
        database=database, dossie=dossie, trabalho=trabalho,
        api_key="segredo-de-teste", enviar=enviar,
    )

    saida = (dossie / f"{client_id}-analise.md").read_text(encoding="utf-8")
    assert resultados[0].status == "ok"
    assert "status: ok" in saida
    assert "## Dados Prisma usados" in saida
    assert "segredo-de-teste" not in saida
    assert hashlib.sha256(database.read_bytes()).hexdigest() == hash_antes


def test_falha_substitui_md_por_marcador_seguro(tmp_path):
    client_id, database, dossie, trabalho, _empresa = _montar_cenario(tmp_path)
    destino = dossie / f"{client_id}-analise.md"
    destino.write_text("conteúdo anterior", encoding="utf-8")

    def falhar(_mensagens, _api_key, **_kwargs):
        raise ErroOllama("ollama_auth", "Credencial recusada.")

    resultados = executar_lote(
        database=database, dossie=dossie, trabalho=trabalho,
        api_key="segredo-de-teste", enviar=falhar,
    )

    saida = destino.read_text(encoding="utf-8")
    assert resultados[0].status == "erro"
    assert "status: erro" in saida
    assert "erro_codigo: \"ollama_auth\"" in saida
    assert "conteúdo anterior" not in saida


def test_cliente_sem_match_e_ignorado(tmp_path):
    client_id = str(uuid4())
    database = tmp_path / "database.xlsx"
    dossie = tmp_path / "dossie"
    trabalho = tmp_path / "trabalho"
    dossie.mkdir()
    trabalho.mkdir()
    _criar_database(database, [(client_id, "Sem Pasta")])

    resultados = executar_lote(
        database=database, dossie=dossie, trabalho=trabalho,
        api_key=None, dry_run=True,
    )

    assert resultados[0].status == "ignorado"
    assert resultados[0].codigo == "sem_match_prisma"


def test_chave_ausente_falha_antes_de_gravar(tmp_path):
    client_id, database, dossie, trabalho, _empresa = _montar_cenario(tmp_path)

    with pytest.raises(ErroDossieIA) as erro:
        executar_lote(
            database=database, dossie=dossie, trabalho=trabalho,
            api_key=None,
        )

    assert erro.value.codigo == "ollama_key_ausente"
    assert not (dossie / f"{client_id}-analise.md").exists()


def test_ollama_repete_falhas_temporarias(monkeypatch):
    chamadas = 0
    esperas: list[float] = []

    def post_temporario(*_args, **_kwargs):
        nonlocal chamadas
        chamadas += 1
        if chamadas < 3:
            raise ErroOllama("ollama_http", "Temporário.", repetivel=True)
        return NARRATIVA_VALIDA

    monkeypatch.setattr(dossie_ia, "_post_ollama", post_temporario)

    resposta = chamar_ollama([], "segredo-de-teste", dormir=esperas.append)

    assert resposta == NARRATIVA_VALIDA
    assert chamadas == 3
    assert esperas == [2.0, 8.0]


def test_ollama_nao_repete_erro_de_autenticacao(monkeypatch):
    chamadas = 0

    def post_auth(*_args, **_kwargs):
        nonlocal chamadas
        chamadas += 1
        raise ErroOllama("ollama_auth", "Credencial recusada.")

    monkeypatch.setattr(dossie_ia, "_post_ollama", post_auth)

    with pytest.raises(ErroOllama) as erro:
        chamar_ollama([], "segredo-de-teste", dormir=lambda _segundos: None)

    assert erro.value.codigo == "ollama_auth"
    assert chamadas == 1


def test_documento_sucesso_nao_inclui_segredo():
    cliente = ClienteCarteira(str(uuid4()), "Empresa")
    contexto = {
        "updated_at": "agora",
        "periodo_ranking": 202607,
        "periodo_ranking_parcial": False,
        "metricas_12_meses": {},
        "top_clientes_compradores": [],
        "top_fabricantes": [],
        "top_produtos": [],
    }

    texto = documento_sucesso(
        cliente, NARRATIVA_VALIDA, contexto, modelo="gpt-oss:120b",
        crm_mtime=os.path.getmtime(__file__),
    )

    assert cliente.client_id in texto
    assert "api_key" not in texto.lower()
