"""Resumo leve por empresa para a tela de monitoramento.

Por que existe: o summary do Dashboard (`summary_dashboard.json`) vai de 0,2 MB a
45 MB por empresa — ~450 MB somando as 59 da base. A tela de monitoramento precisa
de 59 gráficos pequenos, o que daria ~60 KB de dados se cada empresa mandasse só a
série mensal e alguns totais. Baixar (ou reprocessar) os summaries inteiros a cada
abertura da tela seria duas ordens de grandeza mais caro do que o necessário.

Então este módulo derruba o summary para um resumo de poucos KB e o guarda em
`resumo_monitor.json` na pasta de trabalho da empresa. O cache é invalidado pelo
mtime do summary de origem: enquanto o summary não mudar, ler o resumo é instantâneo.
A primeira leitura de cada empresa paga o custo de abrir o summary uma vez.

O resumo carrega as TRÊS métricas (receita, quantidade e clientes distintos) por
período, não só a que a tela está mostrando: recalcular o cache a cada troca de
métrica no filtro anularia o ganho, e o custo em bytes é irrelevante.
"""

from __future__ import annotations

import gzip
import json
import logging
import calendar
from datetime import date, datetime
from pathlib import Path

from dashboard_summary import (
    caminho_summary_dashboard,
    caminho_summary_dashboard_gz,
)
from engine.analise_funil import eh_produto_nao_harmonizado

logger = logging.getLogger(__name__)

NOME_RESUMO_MONITOR = "resumo_monitor.json"

#: Muda quando o formato do resumo muda — cache de versão antiga é descartado em
#: vez de ser lido torto.
#: Bumpar invalida todo `resumo_monitor.json` já gravado, que é regerado do
#: summary na primeira leitura. 2: passou a carregar a lista de lojas.
#: 3: passou a carregar CMV/lucro bruto por período. 4: passou a carregar dias
#: com venda real por período (`dias_venda`). 5: passou a carregar receita não
#: harmonizada (total e por loja) e série por loja de receita/quantidade/clientes.
VERSAO_RESUMO = 5

#: Métricas oferecidas pela tela. A chave é o que vem do filtro; o valor é o campo
#: correspondente na série do resumo. `receita_dia`/`lucro_dia` são DERIVADAS
#: (valor ÷ dias com venda real no período, ver `_dias_venda_do_ponto`): ficam
#: fora do cache de propósito, o cálculo é feito na hora a partir de `rev`/`lucro`
#: e `dias_venda`, ambos já presentes na série cacheada.
METRICAS_MONITOR = {
    "receita": "rev",
    "qtd": "qty",
    "clientes": "clientes",
    "receita_dia": "rev",
    "lucro": "lucro",
    "lucro_dia": "lucro",
}

#: Métrica calculada à parte (ver `_montar_card_nao_harmonizado`) — não tem campo
#: fixo na série porque o valor exibido é uma razão (receita não harmonizada ÷
#: receita total da janela), não um campo somável ponto a ponto.
METRICA_NAO_HARMONIZADO = "nao_harmonizado"

#: Todas as métricas que o endpoint aceita — usado só para validar o parâmetro.
METRICAS_VALIDAS = frozenset(METRICAS_MONITOR) | {METRICA_NAO_HARMONIZADO}

#: Métricas cuja soma não faz sentido (média não se soma) — o card mostra a média
#: ponderada da janela em vez do total.
METRICAS_MEDIA = {"receita_dia", "lucro_dia"}

#: Métricas que exigem CMV na base — empresa sem a coluna some do card em vez de
#: mostrar lucro == receita (CMV ausente vira 0 no summary, o que mascararia o
#: dado em vez de sinalizar a ausência). Também são as métricas que não podem
#: ser filtradas por loja: o summary só soma CMV por período no agregado geral
#: (`dashboard_summary.gerar_summary`), sem dimensão de loja.
METRICAS_COM_CMV = {"lucro", "lucro_dia"}


def dias_uteis_do_mes(ano: int, mes: int) -> int:
    """Dias do mês menos sábados e domingos.

    Feriado NÃO é descontado: o pedido foi "dias menos finais de semana", e um
    calendário de feriados (nacional + estadual + municipal, variando por loja)
    seria uma fonte de dado que o projeto não tem. A tela declara isso.
    """
    _, total_dias = calendar.monthrange(ano, mes)
    return sum(
        1
        for dia in range(1, total_dias + 1)
        if date(ano, mes, dia).weekday() < 5
    )


def _eh_mes_corrente(periodo: int | None, hoje: date | None = None) -> bool:
    """True quando o período (YYYYMM) é o mês do calendário que está correndo."""
    if not periodo:
        return False
    ref = hoje or date.today()
    return int(periodo) == ref.year * 100 + ref.month


def _dias_uteis_do_periodo(periodo: int | None) -> int:
    """Dias úteis de um período YYYYMM. 0 quando o período não é reconhecível."""
    if not periodo:
        return 0
    ano, mes = int(periodo) // 100, int(periodo) % 100
    if not 1 <= mes <= 12 or ano < 1900:
        return 0
    return dias_uteis_do_mes(ano, mes)


def _dias_venda_do_ponto(ponto: dict) -> int:
    """Dias com venda real no período; cai para dias úteis do mês na ausência.

    O fallback só é acionado quando a fonte não tem coluna de data diária
    (`dashboard_summary.gerar_summary` não populou `dias_venda`) — empresa sem
    essa granularidade continua com a estimativa por calendário em vez de ficar
    sem a métrica.
    """
    dias_venda = ponto.get("dias_venda")
    if dias_venda:
        return int(dias_venda)
    return _dias_uteis_do_periodo(ponto.get("periodo"))


def caminho_resumo_monitor(pasta_trabalho: str | Path) -> Path:
    return Path(pasta_trabalho) / NOME_RESUMO_MONITOR


def caminho_summary_existente(pasta_trabalho: str | Path) -> Path | None:
    """O summary da empresa, preferindo o `.gz`. None se a empresa não tem base."""
    gz = caminho_summary_dashboard_gz(pasta_trabalho)
    if gz.is_file():
        return gz
    json_puro = caminho_summary_dashboard(pasta_trabalho)
    return json_puro if json_puro.is_file() else None


def _ler_summary(caminho: Path) -> dict:
    abrir = gzip.open if caminho.suffix == ".gz" else open
    with abrir(caminho, "rt", encoding="utf-8") as arquivo:
        return json.load(arquivo)


def _resumo_de_summary(summary: dict) -> dict:
    """Extrai a série por período (geral e por loja) e os totais do summary completo.

    `monthly` já traz receita/CMV por mês (agregado geral, sem dimensão de loja).
    Quantidade, clientes distintos e os números de "não harmonizado" saem de
    `rows` ([p, s, c, m, d, r, rev, qty]), varrendo linha a linha — é o único
    lugar onde esses cruzamentos (por loja, por produto) existem.

    A dimensão de loja cobre receita/quantidade/clientes/não-harmonizado, mas
    NÃO cmv/lucro: `dashboard_summary.gerar_summary` só soma CMV por período no
    agregado geral, então lucro por loja não é uma conta possível com o summary
    atual (ver `METRICAS_COM_CMV` e `montar_card`).
    """
    monthly = summary.get("monthly") or []
    periodos = summary.get("maps", {}).get("p") or []
    lojas_mapa = [str(nome) for nome in (summary.get("maps", {}).get("s") or [])]
    produtos_mapa = summary.get("maps", {}).get("d") or []
    rows = summary.get("rows") or []

    # Regra única de harmonização (mesma do Analisador/Dashboard), calculada uma
    # vez por produto do catálogo (índice `d`), não por linha da base.
    produto_nao_harmonizado = [eh_produto_nao_harmonizado(nome) for nome in produtos_mapa]

    qtd_por_periodo: dict[int, int] = {}
    clientes_por_periodo: dict[int, set] = {}

    produtos_vistos: set[int] = set()
    produtos_nh_vistos: set[int] = set()
    rev_total = 0.0
    rev_nh_total = 0.0
    rev_nh_por_periodo: dict[int, float] = {}

    produtos_vistos_por_loja: dict[str, set[int]] = {}
    produtos_nh_vistos_por_loja: dict[str, set[int]] = {}
    rev_por_loja: dict[str, float] = {}
    rev_nh_por_loja: dict[str, float] = {}
    rev_por_loja_periodo: dict[tuple[str, int], float] = {}
    rev_nh_por_loja_periodo: dict[tuple[str, int], float] = {}
    qtd_por_loja_periodo: dict[tuple[str, int], int] = {}
    clientes_por_loja_periodo: dict[tuple[str, int], set] = {}

    for linha in rows:
        indice_periodo = linha[0]
        periodo = periodos[indice_periodo] if indice_periodo < len(periodos) else None
        if periodo is None:
            continue

        indice_loja = linha[1]
        loja_nome = lojas_mapa[indice_loja] if indice_loja < len(lojas_mapa) else None
        indice_produto = linha[4]
        rev_linha = float(linha[6] or 0)
        # Linhas curtas (formato antigo) não têm qty: conta cliente/receita e ignora qty.
        qty_linha = int(linha[7]) if len(linha) > 7 else 0
        nao_harmonizado = (
            indice_produto < len(produto_nao_harmonizado)
            and produto_nao_harmonizado[indice_produto]
        )

        if len(linha) > 7:
            qtd_por_periodo[periodo] = qtd_por_periodo.get(periodo, 0) + qty_linha
        clientes_por_periodo.setdefault(periodo, set()).add(linha[2])

        produtos_vistos.add(indice_produto)
        rev_total += rev_linha
        if nao_harmonizado:
            produtos_nh_vistos.add(indice_produto)
            rev_nh_total += rev_linha
            rev_nh_por_periodo[periodo] = rev_nh_por_periodo.get(periodo, 0.0) + rev_linha

        if loja_nome is not None:
            chave = (loja_nome, periodo)
            if len(linha) > 7:
                qtd_por_loja_periodo[chave] = qtd_por_loja_periodo.get(chave, 0) + qty_linha
            clientes_por_loja_periodo.setdefault(chave, set()).add(linha[2])
            rev_por_loja_periodo[chave] = rev_por_loja_periodo.get(chave, 0.0) + rev_linha
            rev_por_loja[loja_nome] = rev_por_loja.get(loja_nome, 0.0) + rev_linha
            produtos_vistos_por_loja.setdefault(loja_nome, set()).add(indice_produto)
            if nao_harmonizado:
                produtos_nh_vistos_por_loja.setdefault(loja_nome, set()).add(indice_produto)
                rev_nh_por_loja[loja_nome] = rev_nh_por_loja.get(loja_nome, 0.0) + rev_linha
                rev_nh_por_loja_periodo[chave] = rev_nh_por_loja_periodo.get(chave, 0.0) + rev_linha

    serie = []
    for mes in monthly:
        periodo = mes.get("pid")
        rev = round(float(mes.get("rev") or 0.0), 2)
        cmv = round(float(mes.get("cmv") or 0.0), 2)
        rev_nh_mes = round(rev_nh_por_periodo.get(periodo, 0.0), 2)
        entrada = {
            "periodo": periodo,
            "rotulo": mes.get("name"),
            "rev": rev,
            "qty": int(qtd_por_periodo.get(periodo, 0)),
            "clientes": len(clientes_por_periodo.get(periodo, ())),
            "cmv": cmv,
            "lucro": round(rev - cmv, 2),
            "rev_nao_harmonizada": rev_nh_mes,
            "pct_nao_harmonizado": round(rev_nh_mes / rev * 100, 2) if rev else 0.0,
        }
        dias_venda = mes.get("dias_com_venda")
        if dias_venda is not None:
            entrada["dias_venda"] = int(dias_venda)
        serie.append(entrada)
    serie.sort(key=lambda item: item["periodo"] or 0)

    # Série por loja: mesmo grão temporal do agregado, sem cmv/lucro (ver
    # docstring). `rotulo` vem do mesmo `monthly`, casado pelo período.
    rotulo_por_periodo = {mes.get("pid"): mes.get("name") for mes in monthly}
    series_por_loja: dict[str, list[dict]] = {}
    for loja_nome in lojas_mapa:
        pontos = []
        for periodo in periodos:
            chave = (loja_nome, periodo)
            if chave not in rev_por_loja_periodo and chave not in qtd_por_loja_periodo:
                continue
            rev_ponto = round(rev_por_loja_periodo.get(chave, 0.0), 2)
            rev_nh_ponto = round(rev_nh_por_loja_periodo.get(chave, 0.0), 2)
            pontos.append({
                "periodo": periodo,
                "rotulo": rotulo_por_periodo.get(periodo, str(periodo)),
                "rev": rev_ponto,
                "qty": int(qtd_por_loja_periodo.get(chave, 0)),
                "clientes": len(clientes_por_loja_periodo.get(chave, ())),
                "rev_nao_harmonizada": rev_nh_ponto,
                "pct_nao_harmonizado": round(rev_nh_ponto / rev_ponto * 100, 2) if rev_ponto else 0.0,
            })
        pontos.sort(key=lambda item: item["periodo"] or 0)
        series_por_loja[loja_nome] = pontos

    nao_harmonizado_por_loja = {
        loja_nome: {
            "produtos_total": len(produtos_vistos_por_loja.get(loja_nome, ())),
            "produtos_nao_harmonizados": len(produtos_nh_vistos_por_loja.get(loja_nome, ())),
            "receita_total": round(rev_por_loja.get(loja_nome, 0.0), 2),
            "receita_nao_harmonizada": round(rev_nh_por_loja.get(loja_nome, 0.0), 2),
        }
        for loja_nome in lojas_mapa
    }

    kpis = summary.get("kpis") or {}
    cmv_total = round(float(kpis.get("cmv") or 0.0), 2)
    rev_total_kpi = round(float(kpis.get("rev") or 0.0), 2)
    return {
        "versao": VERSAO_RESUMO,
        "updated_at": summary.get("updated_at"),
        # `maps.s` é a lista de lojas ordenada por receita. Vem junto porque o
        # seletor de loja (sidebar e, agora, o card do Monitoramento) precisa
        # dela sem carregar o XLSX/summary inteiro para preencher um combobox.
        "lojas": lojas_mapa,
        "serie": serie,
        "series_por_loja": series_por_loja,
        # Empresa sem coluna CMV no CSV chega com cmv == 0 em todo período (ver
        # dashboard_summary.py) — sem essa flag, lucro apareceria == receita, o
        # que é dado errado apresentado como se fosse certo.
        "tem_cmv": cmv_total > 0,
        "totais": {
            "rev": rev_total_kpi,
            "qty": int(kpis.get("qty") or 0),
            "clientes": len(set().union(*clientes_por_periodo.values())) if clientes_por_periodo else 0,
            "cmv": cmv_total,
            "lucro": round(rev_total_kpi - cmv_total, 2),
        },
        "nao_harmonizado": {
            "produtos_total": len(produtos_vistos),
            "produtos_nao_harmonizados": len(produtos_nh_vistos),
            "receita_total": round(rev_total, 2),
            "receita_nao_harmonizada": round(rev_nh_total, 2),
        },
        "nao_harmonizado_por_loja": nao_harmonizado_por_loja,
    }


def _resumo_valido(resumo: object, mtime_fonte: float) -> bool:
    if not isinstance(resumo, dict):
        return False
    if resumo.get("versao") != VERSAO_RESUMO:
        return False
    # Tolerância de 1s: alguns sistemas de arquivo guardam mtime com menos precisão.
    return abs(float(resumo.get("fonte_mtime") or 0) - mtime_fonte) < 1.0


def obter_resumo_monitor(
    pasta_trabalho: str | Path,
    *,
    forcar: bool = False,
) -> dict | None:
    """Resumo da empresa, do cache quando ele está fresco.

    Retorna None quando a empresa não tem summary (base ainda não gerada) — quem
    chama decide o que mostrar, este módulo não inventa dado vazio.
    """
    pasta_trabalho = Path(pasta_trabalho)
    caminho_fonte = caminho_summary_existente(pasta_trabalho)
    if caminho_fonte is None:
        return None

    mtime_fonte = caminho_fonte.stat().st_mtime
    caminho_cache = caminho_resumo_monitor(pasta_trabalho)

    if not forcar and caminho_cache.is_file():
        try:
            with open(caminho_cache, "r", encoding="utf-8") as arquivo:
                cache = json.load(arquivo)
            if _resumo_valido(cache, mtime_fonte):
                return cache
        except (OSError, json.JSONDecodeError):
            # Cache corrompido não pode derrubar a tela: recalcula.
            logger.warning("Resumo de monitoramento ilegível em %s; recalculando.", caminho_cache)

    summary = _ler_summary(caminho_fonte)
    resumo = _resumo_de_summary(summary)
    # Libera o summary (até 45 MB de listas) antes de gravar o resumo.
    del summary
    resumo["fonte_mtime"] = mtime_fonte
    resumo["gerado_em"] = datetime.now().isoformat(timespec="seconds")

    try:
        with open(caminho_cache, "w", encoding="utf-8") as arquivo:
            json.dump(resumo, arquivo, ensure_ascii=False)
    except OSError as exc:
        # Sem permissão de escrita a tela ainda funciona, só fica lenta.
        logger.warning("Não foi possível gravar %s: %s", caminho_cache, exc)

    return resumo


def _janela(serie: list[dict], meses: int | None) -> list[dict]:
    if not meses or meses <= 0 or meses >= len(serie):
        return serie
    return serie[-meses:]


def _serie_da_janela(
    resumo: dict, *, loja: str | None,
) -> list[dict]:
    """Série-fonte para `montar_card`: agregado geral ou de uma loja específica.

    Loja sem dado no período (ou nome que não existe mais na fonte) devolve
    série vazia — o card mostra "sem período no intervalo" em vez de quebrar.
    """
    if loja:
        return (resumo.get("series_por_loja") or {}).get(loja) or []
    return resumo.get("serie") or []


def montar_card(
    empresa: str,
    resumo: dict,
    *,
    metrica: str = "receita",
    meses: int | None = 12,
    hoje: date | None = None,
    loja: str | None = None,
) -> dict:
    """Dados de um minicard: série da métrica pedida, total e variação vs ano anterior.

    A variação compara a janela exibida com os MESMOS meses do ano anterior (jan–ago
    contra jan–ago, não contra o ano fechado). Comparar janela parcial com ano cheio
    faz o ano anterior parecer maior só por ter mais meses — erro que já apareceu no
    explorador do Analisador.

    `loja`, quando informada, restringe a série a uma loja (ver `_serie_da_janela`).
    Lucro/lucro bruto por dia não são filtráveis por loja — o summary só soma CMV
    por período no agregado geral — e o card volta com `indisponivel_por_loja`
    em vez de mostrar lucro == receita da loja (dado errado disfarçado de certo).
    """
    if metrica == METRICA_NAO_HARMONIZADO:
        return _montar_card_nao_harmonizado(empresa, resumo, meses=meses, hoje=hoje, loja=loja)

    if loja and metrica in METRICAS_COM_CMV:
        return {
            "empresa": empresa,
            "estado": "ok",
            "metrica": metrica,
            "indisponivel_por_loja": True,
            "detalhe": "Lucro bruto não é calculado por loja — o CMV só existe agregado por empresa.",
            "updated_at": resumo.get("updated_at"),
            "lojas": resumo.get("lojas") or [],
        }

    campo = METRICAS_MONITOR.get(metrica, "rev")
    inteiro = campo in ("qty", "clientes")
    eh_media = metrica in METRICAS_MEDIA
    serie = _serie_da_janela(resumo, loja=loja)
    janela = _janela(serie, meses)

    def valor(ponto: dict) -> float | int:
        bruto = ponto.get(campo) or 0
        if eh_media:
            dias_venda = _dias_venda_do_ponto(ponto)
            return round(float(bruto) / dias_venda, 2) if dias_venda else 0.0
        return int(bruto) if inteiro else round(float(bruto), 2)

    valores = [valor(ponto) for ponto in janela]
    rotulos = [ponto.get("rotulo") for ponto in janela]
    dias_venda_janela = sum(_dias_venda_do_ponto(ponto) for ponto in janela)
    bruto_janela = sum(float(ponto.get(campo) or 0) for ponto in janela)
    total = None if eh_media else (
        sum(valores) if inteiro else round(sum(valores), 2)
    )
    media = (
        round(bruto_janela / dias_venda_janela, 2)
        if eh_media and dias_venda_janela
        else round(float(total) / len(valores), 2) if valores and total is not None
        else 0
    )

    # Variação: SÓ os meses do ano mais recente da janela contra os MESMOS meses do
    # ano anterior. Somar a janela inteira (que pode atravessar dois anos) contra
    # alguns meses do ano anterior dava variação absurda — "1100 MG: +528.540%",
    # porque o lado "atual" tinha 9 meses de dois anos e o "anterior" tinha 3.
    periodos_janela = [int(p["periodo"]) for p in janela if p.get("periodo")]
    ano_atual = max((p // 100 for p in periodos_janela), default=None)
    meses_atuais = {p % 100 for p in periodos_janela if p // 100 == ano_atual}

    pontos_atuais: list[dict] = []
    pontos_anteriores: list[dict] = []
    tem_anterior = False
    if ano_atual is not None:
        for ponto in serie:
            periodo = int(ponto.get("periodo") or 0)
            ano, mes = periodo // 100, periodo % 100
            if mes not in meses_atuais:
                continue
            if ano == ano_atual:
                pontos_atuais.append(ponto)
            elif ano == ano_atual - 1:
                pontos_anteriores.append(ponto)
                tem_anterior = True

    def agregar_comparacao(pontos: list[dict]) -> float:
        if not eh_media:
            return sum(float(ponto.get(campo) or 0) for ponto in pontos)
        dias = sum(_dias_venda_do_ponto(ponto) for ponto in pontos)
        bruto = sum(float(ponto.get(campo) or 0) for ponto in pontos)
        return bruto / dias if dias else 0.0

    total_atual = agregar_comparacao(pontos_atuais)
    total_anterior = agregar_comparacao(pontos_anteriores)

    # Bases menores que 1% do valor atual produzem percentuais gigantes que não
    # ajudam decisão (caso real: R$ 1.073 contra R$ 3,5 mi). O dado permanece nos
    # lados da comparação, mas o card sinaliza que a base não é comparável.
    base_comparavel = (
        total_anterior > 0
        and not (total_atual > total_anterior and total_anterior < total_atual * 0.01)
        if tem_anterior
        else None
    )

    variacao = (
        round((total_atual - total_anterior) / total_anterior * 100, 2)
        if base_comparavel
        else None
    )

    return {
        "empresa": empresa,
        "estado": "ok",
        "metrica": metrica,
        "rotulos": rotulos,
        "valores": valores,
        # `total` é a soma do que o gráfico mostra; os dois totais abaixo são os
        # lados da comparação anual, que cobrem só os meses do ano mais recente.
        "total": total,
        "media": media,
        "variacao_pct": variacao,
        "base_comparavel": base_comparavel,
        "total_comparado": round(total_atual, 2) if tem_anterior else None,
        "total_ano_anterior": round(total_anterior, 2) if tem_anterior else None,
        "ano_comparado": ano_atual if tem_anterior else None,
        "meses_comparados": len(meses_atuais) if tem_anterior else 0,
        "updated_at": resumo.get("updated_at"),
        "ultimo_periodo": janela[-1].get("periodo") if janela else None,
        # Parcial = o último período da janela é o mês corrente, que ainda não
        # fechou. Vale para qualquer métrica (o total do mês em curso também está
        # incompleto), mas pesa mais na média por dia: o mês em curso conta só os
        # dias com venda já ocorridos, então a média tende a subir ao longo do mês.
        "ultimo_periodo_parcial": _eh_mes_corrente(
            janela[-1].get("periodo") if janela else None, hoje
        ),
        "dias_venda_janela": dias_venda_janela if eh_media else None,
        "meses_serie": len(serie),
        "lojas": resumo.get("lojas") or [],
    }


def _montar_card_nao_harmonizado(
    empresa: str,
    resumo: dict,
    *,
    meses: int | None,
    hoje: date | None,
    loja: str | None = None,
) -> dict:
    """Card da métrica "% receita não harmonizada" (ver `METRICA_NAO_HARMONIZADO`).

    O valor exibido é receita não harmonizada ÷ receita total da janela — uma
    razão entre duas somas, não um campo que se soma ponto a ponto — por isso o
    card é montado à parte em vez de reaproveitar a matemática genérica de
    `montar_card`. "Não harmonizado" segue a MESMA regra do Analisador/Dashboard
    (`engine.analise_funil.eh_produto_nao_harmonizado`), aplicada por produto do
    catálogo (`maps.d`), não por linha de venda.
    """
    serie = _serie_da_janela(resumo, loja=loja)
    if loja:
        nh_info = (resumo.get("nao_harmonizado_por_loja") or {}).get(loja) or {}
    else:
        nh_info = resumo.get("nao_harmonizado") or {}

    janela = _janela(serie, meses)
    valores = [round(float(p.get("pct_nao_harmonizado") or 0.0), 2) for p in janela]
    rotulos = [p.get("rotulo") for p in janela]

    rev_nh_janela = sum(float(p.get("rev_nao_harmonizada") or 0.0) for p in janela)
    rev_janela = sum(float(p.get("rev") or 0.0) for p in janela)
    total = round(rev_nh_janela / rev_janela * 100, 2) if rev_janela else 0.0

    periodos_janela = [int(p["periodo"]) for p in janela if p.get("periodo")]
    ano_atual = max((p // 100 for p in periodos_janela), default=None)
    meses_atuais = {p % 100 for p in periodos_janela if p // 100 == ano_atual}

    pontos_atuais: list[dict] = []
    pontos_anteriores: list[dict] = []
    tem_anterior = False
    if ano_atual is not None:
        for ponto in serie:
            periodo = int(ponto.get("periodo") or 0)
            ano, mes = periodo // 100, periodo % 100
            if mes not in meses_atuais:
                continue
            if ano == ano_atual:
                pontos_atuais.append(ponto)
            elif ano == ano_atual - 1:
                pontos_anteriores.append(ponto)
                tem_anterior = True

    def pct_agregado(pontos: list[dict]) -> float:
        rev = sum(float(p.get("rev") or 0) for p in pontos)
        nh = sum(float(p.get("rev_nao_harmonizada") or 0) for p in pontos)
        return round(nh / rev * 100, 2) if rev else 0.0

    # Variação em PONTOS percentuais (18% − 14% = +4), não variação relativa: a
    # métrica já é um percentual, então "subiu 4 pontos" é a leitura certa —
    # diferente de tratar 14%→18% como "+28%", que é o que a fórmula genérica
    # (usada por receita/qtd/etc.) daria.
    variacao = round(pct_agregado(pontos_atuais) - pct_agregado(pontos_anteriores), 2) if tem_anterior else None

    return {
        "empresa": empresa,
        "estado": "ok",
        "metrica": METRICA_NAO_HARMONIZADO,
        "rotulos": rotulos,
        "valores": valores,
        "total": total,
        "media": total,
        "variacao_pct": variacao,
        "base_comparavel": tem_anterior or None,
        "updated_at": resumo.get("updated_at"),
        "ultimo_periodo": janela[-1].get("periodo") if janela else None,
        "ultimo_periodo_parcial": _eh_mes_corrente(
            janela[-1].get("periodo") if janela else None, hoje
        ),
        "meses_serie": len(serie),
        "produtos_total": int(nh_info.get("produtos_total") or 0),
        "produtos_nao_harmonizados": int(nh_info.get("produtos_nao_harmonizados") or 0),
        "receita_nao_harmonizada": round(float(nh_info.get("receita_nao_harmonizada") or 0.0), 2),
        "receita_total": round(float(nh_info.get("receita_total") or 0.0), 2),
        "lojas": resumo.get("lojas") or [],
    }
