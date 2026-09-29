"""Recortes das telas do Prisma para a análise diária da carteira.

A análise (``dossie_ia``) nasceu lendo só o summary: receita, quantidade e o
estoque de um CSV que o lote deixou de gerar em jul/2026. As telas novas já
calculam o que um gerente quer ler — lucro, churn, rupturas, o que precificar,
o que repor — e o lote da manhã as deixa prontas em disco (``preparar_telas``)
antes das análises rodarem.

Três decisões:

- **Chamar a rota, com os parâmetros do lote da manhã.** É o que garante que o
  número da análise é o da tela, e que a leitura cai no cache em disco (< 1 s).
  Parâmetro diferente vira outra chave de cache e recalcula a tela.
- **Recortar aqui, não no prompt.** Cada bloco leva o resumo e os 3–5 primeiros
  itens, com variações e percentuais já calculados: o LLM não faz conta, e a
  tela de 500 SKUs não vira 500 KB de prompt.
- **Tela que falha não derruba a análise.** O bloco sai ``disponivel: false`` e
  o prompt manda dizer que o dado não está disponível, sem estimar.

Despesas na margem: a Controladoria lança compra de mercadoria como despesa
("Mercadoria Revenda"). Ela já está no CMV, e em várias empresas é a maior
parte do lançado (Gomec 85%, Comkit 74%, Renocar 66% em 2026). Fica fora, como
no GPS (``gps_dispersao.CATEGORIA_FORA_DA_DESPESA``).
"""

from __future__ import annotations

import logging
import math
from datetime import date
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

TOPO = 5
MESES_RENTABILIDADE = 12

# Mesmos parâmetros de preparar_telas.TELAS (escopo "todas as lojas", período
# fechado): é o que faz a leitura cair no cache em disco. Compras guarda em
# disco só a base de 12 meses; o cenário por cima dela custa ~0,2 s.
TELAS: dict[str, tuple[str, dict[str, Any]]] = {
    "clientes": ("/api/clientes/{e}/painel", {"modo_periodo": "fechados"}),
    "diagnostico": ("/api/diagnostico/{e}", {"modo_periodo": "fechados"}),
    "vendedores": ("/api/vendedores/{e}", {"modo_periodo": "fechados"}),
    "estoque": ("/api/estoque/resumo/{e}", {"meses": 6}),
    "a_precificar": ("/api/precificacao/{e}/a-precificar", {}),
    "pos_precificacao": ("/api/precificacao/{e}/historico", {"periodo": 180, "nivel": "familia"}),
    "compras": ("/api/compras/{e}", {"limite": TOPO}),
}

BuscarTelas = Callable[[str], dict[str, dict | None]]


def _num(valor: Any, casas: int = 2) -> float | None:
    try:
        numero = float(valor)
    except (TypeError, ValueError):
        return None
    return round(numero, casas) if math.isfinite(numero) else None


def _int(valor: Any) -> int | None:
    numero = _num(valor, 0)
    return None if numero is None else int(numero)


def _pct(parte: float | None, todo: float | None) -> float | None:
    if parte is None or not todo:
        return None
    return round(parte / todo * 100, 2)


def _indisponivel(motivo: str) -> dict:
    return {"disponivel": False, "motivo": motivo}


# ---------------------------------------------------------------------------
# Leitura das telas
# ---------------------------------------------------------------------------

def buscar_telas(empresa: str) -> dict[str, dict | None]:
    """Chama as rotas das telas como o lote da manhã; ``None`` = tela sem dado.

    Import tardio de ``main``: este módulo é importado pelo ``dossie_ia``, que o
    ``main`` também importa.
    """
    from fastapi.testclient import TestClient

    import auth
    import main

    cliente = TestClient(main.app)
    cabecalho = {"Authorization": f"Bearer {auth.criar_token('lote-analise')}"}
    respostas: dict[str, dict | None] = {}
    for nome, (rota, params) in TELAS.items():
        try:
            resposta = cliente.get(rota.format(e=empresa), params=params, headers=cabecalho)
        except Exception as exc:  # noqa: BLE001 — uma tela não pode derrubar a análise
            logger.warning("Tela %s falhou para análise empresa=%s tipo=%s", nome, empresa, type(exc).__name__)
            respostas[nome] = None
            continue
        if resposta.status_code != 200:
            if resposta.status_code != 404:
                logger.warning("Tela %s HTTP %s para análise empresa=%s", nome, resposta.status_code, empresa)
            respostas[nome] = None
            continue
        respostas[nome] = resposta.json()
    return respostas


def despesas_mensais(empresa: str, meses: list[tuple[int, int]]) -> dict[str, float] | None:
    """Despesa da Controladoria por mês (``AAAA-MM``), sem "Mercadoria Revenda".

    ``None`` quando a empresa não tem Controladoria.
    """
    import consulta_parquet
    import main
    from gps_dispersao import CATEGORIA_FORA_DA_DESPESA, _filtro_meses

    fonte = main._resolver_caminho_fonte()
    if not fonte or not meses:
        return None
    caminho = Path(fonte) / empresa / f"{empresa}_CONTROLADORIA.parquet"
    if not caminho.is_file():
        return None
    filtro, valores = _filtro_meses(meses)
    tabela = consulta_parquet.consultar(
        "select ANO, MES, sum(VALOR) as despesa from read_parquet(?) "
        f"where {filtro} and lower(trim(coalesce(DESCRICAO_HARMONIZADA, ''))) <> ? group by ANO, MES",
        [str(caminho), *valores, CATEGORIA_FORA_DA_DESPESA],
    )
    return {
        f"{int(linha.ANO):04d}-{int(linha.MES):02d}": float(linha.despesa or 0.0)
        for linha in tabela.itertuples()
    }


# ---------------------------------------------------------------------------
# Recortes (funções puras: payload da tela → bloco pequeno)
# ---------------------------------------------------------------------------

def recortar_rentabilidade(
    summary: dict,
    despesas: dict[str, float] | None,
    *,
    hoje: date,
    meses: int = MESES_RENTABILIDADE,
) -> dict:
    """Lucro bruto e margem mês a mês (meses fechados), e o resultado após despesas."""
    corrente = hoje.year * 100 + hoje.month
    mensal = sorted(
        (m for m in summary.get("monthly") or [] if int(m.get("pid") or 0) < corrente),
        key=lambda m: int(m["pid"]),
    )[-meses:]
    if not mensal or not any(m.get("cmv") for m in mensal):
        return _indisponivel("sem_cmv")

    serie = []
    for m in mensal:
        pid = int(m["pid"])
        chave = f"{pid // 100:04d}-{pid % 100:02d}"
        receita = float(m.get("rev") or 0.0)
        lucro = receita - float(m.get("cmv") or 0.0)
        despesa = None if despesas is None else despesas.get(chave)
        resultado = None if despesa is None else lucro - despesa
        serie.append({
            "mes": m.get("name"),
            "receita": _num(receita),
            "lucro_bruto": _num(lucro),
            "margem_bruta_pct": _pct(lucro, receita),
            "despesas": _num(despesa),
            "resultado_apos_despesas": _num(resultado),
            "margem_apos_despesas_pct": _pct(resultado, receita),
        })

    receita_total = sum(float(m.get("rev") or 0.0) for m in mensal)
    lucro_total = sum(float(m.get("rev") or 0.0) - float(m.get("cmv") or 0.0) for m in mensal)
    com_despesa = [p for p in serie if p["despesas"] is not None]
    ultimo = serie[-1]
    margem_12m = _pct(lucro_total, receita_total)
    bloco: dict[str, Any] = {
        "disponivel": True,
        "janela": f"{serie[0]['mes']} a {ultimo['mes']}",
        "receita_periodo": _num(receita_total),
        "lucro_bruto_periodo": _num(lucro_total),
        "margem_bruta_periodo_pct": margem_12m,
        "ultimo_mes": ultimo,
        "margem_ultimo_mes_vs_periodo_pp": (
            None if ultimo["margem_bruta_pct"] is None or margem_12m is None
            else round(ultimo["margem_bruta_pct"] - margem_12m, 2)
        ),
        "serie_mensal": serie,
        "despesas_disponiveis": bool(com_despesa),
        "regra_despesas": "Despesas da Controladoria sem a categoria Mercadoria Revenda, que já está no CMV.",
    }
    if com_despesa:
        receita_desp = sum(p["receita"] or 0.0 for p in com_despesa)
        resultado_desp = sum(p["resultado_apos_despesas"] or 0.0 for p in com_despesa)
        bloco["meses_com_despesa"] = len(com_despesa)
        bloco["resultado_apos_despesas_periodo"] = _num(resultado_desp)
        bloco["margem_apos_despesas_periodo_pct"] = _pct(resultado_desp, receita_desp)
        bloco["meses_sem_lancamento_de_despesa"] = [p["mes"] for p in serie if p["despesas"] is None]
    return bloco


def recortar_clientes(painel: dict | None, diagnostico: dict | None) -> dict:
    """Carteira: ativos, novos/perdidos, concentração 80/20, pior cauda, potencial e risco."""
    if not painel or not painel.get("disponivel", True):
        return _indisponivel("tela_clientes_indisponivel")
    resumo = painel.get("resumo") or {}
    concentracao = painel.get("concentracao") or {}
    score = painel.get("score_migracao") or {}
    potencial = painel.get("potencial_compra") or {}
    bloco: dict[str, Any] = {
        "disponivel": True,
        "periodo": painel.get("rotulo_periodo"),
        "comparacao": f"contra a média dos {painel.get('meses_media') or 6} meses anteriores",
        "clientes_ativos": _int(resumo.get("clientes_ativos")),
        "variacao_clientes_pct": _num(resumo.get("variacao_clientes")),
        "receita": _num(resumo.get("receita_atual")),
        "variacao_receita_pct": _num(resumo.get("variacao_receita")),
        "ticket_medio": _num(resumo.get("ticket_medio")),
        "variacao_ticket_pct": _num(resumo.get("variacao_ticket")),
        "novos": _int(resumo.get("novos")),
        "recuperados": _int(resumo.get("recuperados")),
        "perdidos": _int(resumo.get("perdidos")),
        "saldo_clientes": _int(resumo.get("saldo")),
        "clientes_que_fazem_80pct_receita": _int(concentracao.get("clientes_80")),
        "participacao_desses_clientes_na_base_pct": _num(concentracao.get("participacao_clientes_80")),
        "maiores_perdidos": [
            {"cliente": e.get("cliente"), "receita": _num(e.get("receita")), "ultima_compra": e.get("ultimo_mes")}
            for e in ((painel.get("eventos") or {}).get("perdidos") or [])[:TOPO]
        ],
        "maiores_clientes_em_queda": [
            {"cliente": c.get("cliente"), "receita": _num(c.get("receita_atual")), "variacao_pct": _num(c.get("variacao"))}
            for c in painel.get("top_clientes") or [] if c.get("alerta")
        ][:TOPO],
    }
    if score.get("disponivel"):
        saldo = score.get("saldo_ultimo_periodo") or {}
        bloco["migracao_de_faixa"] = {
            "periodo": saldo.get("rotulo"),
            "subiram": _int(saldo.get("subiu")),
            "desceram": _int(saldo.get("desceu")),
            "pior_cauda": [
                {"cliente": c.get("cliente"), "faixas_descidas_12m": _int(c.get("desceu"))}
                for c in (score.get("pior_cauda") or [])[:TOPO]
            ],
        }
    if potencial.get("disponivel"):
        bloco["potencial_de_compra"] = {
            "regra": "média dos 3 melhores meses de cada cliente em 12 meses",
            "potencial_total": _num(potencial.get("potencial_total")),
            "compra_atual_total": _num(potencial.get("atual_total")),
            "variacao_pct": _num(potencial.get("variacao_total")),
            "maiores_lacunas": [
                {"cliente": c.get("cliente"), "potencial": _num(c.get("potencial")), "atual": _num(c.get("atual")),
                 "variacao_pct": _num(c.get("variacao"))}
                for c in sorted(
                    potencial.get("ranking") or [],
                    key=lambda c: (float(c.get("potencial") or 0) - float(c.get("atual") or 0)),
                    reverse=True,
                )[:TOPO]
            ],
        }
    if diagnostico and diagnostico.get("disponivel", True):
        impacto = diagnostico.get("impacto_churn") or {}
        risco = diagnostico.get("risco") or {}
        bloco["risco_de_churn"] = {
            "receita_sob_risco": _num(impacto.get("receita_sob_risco")),
            "nota": "Exposição de clientes em queda, não perda confirmada.",
            "clientes_com_maior_perda": [
                {"cliente": c.get("cliente"), "perda": _num(c.get("perda_rs")), "variacao_pct": _num(c.get("variacao_pct")),
                 "parou_de_comprar": bool(c.get("parou_de_comprar")), "faixa": c.get("faixa")}
                for c in (risco.get("clientes") or [])[:TOPO]
            ] if risco.get("disponivel") else [],
        }
    return bloco


def recortar_diagnostico(diagnostico: dict | None) -> dict:
    """Onde a receita mudou: tensão do mês, produtos que mais moveram e sinais precoces."""
    if not diagnostico or not diagnostico.get("disponivel", True):
        return _indisponivel("tela_diagnostico_indisponivel")
    tensao = diagnostico.get("tensao") or {}
    tornado = diagnostico.get("tornado") or []
    radar = diagnostico.get("radar_percentual") or {}
    fluxo = (diagnostico.get("fluxo_faixas") or {}).get("resumo") or {}

    def produto(p: dict) -> dict:
        return {"produto": p.get("descricao"), "receita": _num(p.get("receita_atual")),
                "variacao_rs": _num(p.get("delta_receita")), "variacao_pct": _num(p.get("variacao_pct"))}

    return {
        "disponivel": True,
        "periodo": diagnostico.get("rotulo_periodo"),
        "receita": _num(tensao.get("receita_periodo")),
        "variacao_vs_mes_anterior_pct": _num(tensao.get("variacao_pct")),
        "mes_anterior": tensao.get("rotulo_anterior"),
        "variacao_vs_mesmo_mes_ano_anterior_pct": _num(tensao.get("variacao_ano_pct")),
        "produtos_em_queda": _int(tensao.get("produtos_em_queda")),
        "parcela_da_queda_nos_3_maiores_pct": _num(tensao.get("concentracao_queda_pct")),
        "produtos_que_mais_cairam": [produto(p) for p in sorted(
            (p for p in tornado if float(p.get("delta_receita") or 0) < 0), key=lambda p: float(p["delta_receita"]),
        )[:3]],
        "produtos_que_mais_subiram": [produto(p) for p in sorted(
            (p for p in tornado if float(p.get("delta_receita") or 0) > 0), key=lambda p: -float(p["delta_receita"]),
        )[:3]],
        "sinais_precoces": {
            "nota": "Produtos pequenos mudando de patamar rápido; sinal, não tendência confirmada.",
            "alta": [produto(p) for p in (radar.get("alta") or [])[:3]],
            "queda": [produto(p) for p in (radar.get("queda") or [])[:3]],
        } if radar.get("disponivel") else None,
        "clientes_entre_faixas": {
            "subiram": _int(fluxo.get("subiram")),
            "desceram": _int(fluxo.get("desceram")),
            "receita_dos_que_desceram": _num(fluxo.get("receita_desceram")),
        } if fluxo else None,
    }


def recortar_vendedores(tela: dict | None) -> dict:
    if not tela or not tela.get("disponivel", True) or not tela.get("itens"):
        return _indisponivel("tela_vendedores_indisponivel")
    resumo = tela.get("resumo") or {}
    itens = [i for i in tela.get("itens") or [] if i.get("vendedor")]

    def vendedor(i: dict) -> dict:
        return {"vendedor": i.get("vendedor"), "receita": _num(i.get("receita_atual")),
                "variacao_pct": _num(i.get("variacao")), "clientes": _int(i.get("clientes_atual"))}

    return {
        "disponivel": True,
        "periodo": tela.get("rotulo_periodo"),
        "comparacao": f"contra a média dos {tela.get('meses_media') or 6} meses anteriores",
        "vendedores": _int(resumo.get("vendedores")),
        "maiores_receitas": [vendedor(i) for i in sorted(itens, key=lambda i: -float(i.get("receita_atual") or 0))[:TOPO]],
        "em_alerta_de_queda": [vendedor(i) for i in itens if i.get("alerta")][:TOPO],
    }


STATUS_ESTOQUE = {
    "rupture": "Ruptura",
    "out_of_stock": "Sem estoque",
    "negative": "Estoque negativo",
    "excess": "Excesso",
    "stalled": "Venda em queda",
    "no_sales": "Sem giro",
    "normal": "Normal",
}


def recortar_estoque(tela: dict | None, compras: dict | None) -> dict:
    """Estoque da tela (parquet de produto) e quanto repor segundo a tela Compras."""
    if not tela or not tela.get("disponivel", True):
        return _indisponivel("tela_estoque_indisponivel")
    resumo = tela.get("resumo") or {}

    def item(i: dict) -> dict:
        return {"sku": i.get("sku"), "produto": i.get("nome"), "fabricante": i.get("fabricante"),
                "estoque": _int(i.get("estoque")), "venda_media_mes": _int(i.get("venda_media")),
                "cobertura_meses": _num(i.get("cobertura")), "valor_estoque": _num(i.get("valor_estoque")),
                "situacao": STATUS_ESTOQUE.get(str(i.get("status")), i.get("status"))}

    bloco: dict[str, Any] = {
        "disponivel": True,
        "janela_vendas": f"{tela.get('periodo_inicio')} a {tela.get('periodo_fim')}",
        "regras": "Cobertura < 0,5 mês = ruptura; > 6 meses = excesso; sem venda na janela = sem giro.",
        "produtos": _int(resumo.get("produtos")),
        "valor_estoque": _num(resumo.get("valor_estoque")),
        "em_ruptura": _int(resumo.get("ruptura")),
        "em_excesso": _int(resumo.get("excesso")),
        "sem_giro": _int(resumo.get("sem_giro")),
        "valor_parado": _num(resumo.get("valor_parado")),
        "parcela_parada_pct": _pct(_num(resumo.get("valor_parado")), _num(resumo.get("valor_estoque"))),
        "cobertura_media_meses": _num(resumo.get("cobertura_media")),
        "ruptura_iminente": [item(i) for i in (tela.get("ruptura_iminente") or [])[:TOPO]],
        "maior_capital_parado": [item(i) for i in (tela.get("dinheiro_dormindo") or [])[:TOPO]],
        "fabricantes_com_mais_capital_parado": [
            {"fabricante": f.get("fabricante"), "valor_estoque": _num(f.get("valor_estoque")), "produtos": _int(f.get("produtos"))}
            for f in (tela.get("capital_parado_fabricante") or [])[:TOPO]
        ],
    }
    if compras:
        parametros = compras.get("parametros_aplicados") or {}
        bloco["compras_sugeridas"] = {
            "cenario": f"prazo {parametros.get('prazo_entrega') or 'imediato'}, giro {parametros.get('giro') or 'impulsionado'}",
            "valor_total": _num(compras.get("total_compra")),
            "produtos": _int(compras.get("produtos_a_comprar")),
            "skus": _int(compras.get("itens_a_comprar")),
            "produtos_sem_custo": _int(compras.get("produtos_sem_custo")),
            "maiores_itens": [
                {"produto": c.get("descricao"), "fabricante": c.get("fabricante"), "sugestao_unidades": _int(c.get("sugestao")),
                 "valor": _num(c.get("valor")), "estoque": _int(c.get("estoque")), "venda_media_mes": _int(c.get("media"))}
                for c in (compras.get("itens") or [])[:TOPO]
            ],
        }
    return bloco


def recortar_precificacao(a_precificar: dict | None, pos: dict | None) -> dict:
    """O que precisa de preço novo (lucro perdido/dia), perfil GPS e efeito da última rodada."""
    if not a_precificar and not pos:
        return _indisponivel("sem_dados_do_price")
    bloco: dict[str, Any] = {"disponivel": True}
    if a_precificar:
        resumo = a_precificar.get("resumo") or {}
        janela = a_precificar.get("janela") or {}
        gps = a_precificar.get("gps") or {}
        perfil = gps.get("perfil") or {}
        bloco["a_precificar"] = {
            "janelas": f"recente {janela.get('inicio_recente')} a {janela.get('fim')} contra base desde {janela.get('inicio_base')}",
            "produtos_sinalizados": _int(resumo.get("produtos")),
            "skus_sinalizados": _int(resumo.get("skus")),
            "produtos_curva_a": _int(resumo.get("curva_a")),
            "receita_em_jogo": _num(resumo.get("receita_em_jogo")),
            "parcela_da_receita_pct": _num(resumo.get("part_receita")),
            "lucro_perdido_por_dia": _num(resumo.get("perdido_dia")),
            "skus_com_custo_sem_repasse": _int(resumo.get("custo_sem_repasse")),
            "maiores_perdas": [
                {"produto": p.get("descricao"), "curva": p.get("curva"), "margem_base_pct": _num(p.get("margem_base")),
                 "margem_recente_pct": _num(p.get("margem_recente")), "alvo_pct": _num(p.get("referencia")),
                 "reajuste_sugerido_pct": _num(p.get("reajuste")), "lucro_perdido_por_dia": _num(p.get("perdido_dia")),
                 "variacao_custo_pct": _num(p.get("var_custo")), "variacao_preco_pct": _num(p.get("var_preco"))}
                for p in sorted(
                    (p for p in a_precificar.get("produtos") or [] if p.get("sinalizado")),
                    key=lambda p: -float(p.get("perdido_dia") or 0),
                )[:TOPO]
            ],
            "fabricantes_com_maior_perda": [
                {"fabricante": f.get("nome"), "lucro_perdido_por_dia": _num(f.get("perdido_dia"))}
                for f in (a_precificar.get("fabricantes") or [])[:TOPO]
            ],
        }
        if gps.get("disponivel") and perfil:
            bloco["gps"] = {
                "meses": perfil.get("meses"),
                "margem_pct": _num(perfil.get("margem")),
                "despesas_pct": _num(perfil.get("despesas")),
                "taxa_de_retorno_pct": _num(perfil.get("taxa_retorno")),
                "perfil": perfil.get("rotulo"),
                "recomendacoes": [
                    {"recomendacao": r.get("rotulo"), "produtos": _int(r.get("produtos")),
                     "lucro_perdido_por_dia": _num(r.get("perdido_dia"))}
                    for r in gps.get("recomendacoes") or [] if r.get("produtos")
                ],
            }
    if pos and pos.get("kpis"):
        kpis = pos["kpis"]
        situacoes = kpis.get("situacoes") or {}
        bloco["pos_precificacao"] = {
            "rodadas_no_periodo": _int(kpis.get("rodadas")),
            "skus_precificados": _int(kpis.get("skus")),
            "receita_coberta_pct": _num(kpis.get("receita_coberta_pct")),
            "margem_alvo_pct": _num(kpis.get("alvo")),
            "margem_antes_pct": _num(kpis.get("margem_antes")),
            "margem_depois_pct": _num(kpis.get("margem_depois")),
            "distancia_do_alvo_pp": _num(kpis.get("gap_pp")),
            "efeito_no_lucro_por_dia_pct": _num(kpis.get("efeito_lucro_pct")),
            "efeito_no_volume_por_dia_pct": _num(kpis.get("efeito_qtd_pct")),
            "skus_acima_do_alvo": _int(situacoes.get("acima")),
            "skus_no_alvo": _int(situacoes.get("no_alvo")),
            "skus_abaixo_do_alvo": _int(situacoes.get("abaixo")),
            "skus_sem_venda_depois": _int(situacoes.get("sem_venda")),
            "familias_mais_abaixo_do_alvo": [
                {"familia": linha.get("nome"), "alvo_pct": _num(linha.get("alvo")), "margem_depois_pct": _num(linha.get("margem_depois")),
                 "distancia_do_alvo_pp": _num(linha.get("gap_pp")), "efeito_no_lucro_pct": _num(linha.get("efeito_lucro_pct"))}
                for linha in sorted(
                    (linha for linha in pos.get("linhas") or [] if linha.get("gap_pp") is not None),
                    key=lambda linha: float(linha["gap_pp"]),
                )[:TOPO]
                if float(linha.get("gap_pp") or 0) < 0
            ],
        }
    return bloco


def montar_blocos_telas(
    empresa: str,
    summary: dict,
    *,
    hoje: date | None = None,
    buscar: BuscarTelas | None = None,
    despesas: Callable[[str, list[tuple[int, int]]], dict[str, float] | None] | None = None,
) -> dict:
    """Todos os blocos de uma empresa (nome da pasta de trabalho/fonte)."""
    referencia = hoje or date.today()
    telas = (buscar or buscar_telas)(empresa)
    corrente = referencia.year * 100 + referencia.month
    meses = [
        (int(m["pid"]) // 100, int(m["pid"]) % 100)
        for m in sorted(summary.get("monthly") or [], key=lambda m: int(m.get("pid") or 0))
        if int(m.get("pid") or 0) < corrente
    ][-MESES_RENTABILIDADE:]
    try:
        mensal_despesas = (despesas or despesas_mensais)(empresa, meses)
    except Exception as exc:  # noqa: BLE001 — sem despesa a margem bruta ainda vale
        logger.warning("Despesas indisponíveis para análise empresa=%s tipo=%s", empresa, type(exc).__name__)
        mensal_despesas = None
    return {
        "rentabilidade": recortar_rentabilidade(summary, mensal_despesas, hoje=referencia),
        "clientes": recortar_clientes(telas.get("clientes"), telas.get("diagnostico")),
        "diagnostico_receita": recortar_diagnostico(telas.get("diagnostico")),
        "vendedores": recortar_vendedores(telas.get("vendedores")),
        "estoque_e_compras": recortar_estoque(telas.get("estoque"), telas.get("compras")),
        "precificacao": recortar_precificacao(telas.get("a_precificar"), telas.get("pos_precificacao")),
    }
