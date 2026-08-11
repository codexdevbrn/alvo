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

logger = logging.getLogger(__name__)

NOME_RESUMO_MONITOR = "resumo_monitor.json"

#: Muda quando o formato do resumo muda — cache de versão antiga é descartado em
#: vez de ser lido torto.
VERSAO_RESUMO = 1

#: Métricas oferecidas pela tela. A chave é o que vem do filtro; o valor é o campo
#: correspondente na série do resumo. `receita_dia` é DERIVADA (receita ÷ dias úteis
#: do mês): fica fora do cache de propósito, porque depende só do calendário — assim
#: os resumos já gravados continuam valendo sem bump de versão.
METRICAS_MONITOR = {
    "receita": "rev",
    "qtd": "qty",
    "clientes": "clientes",
    "receita_dia": "rev",
}

#: Métricas cuja soma não faz sentido (média não se soma) — o card mostra a média
#: ponderada da janela em vez do total.
METRICAS_MEDIA = {"receita_dia"}


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
    """Extrai a série por período e os totais do summary completo.

    `monthly` já traz receita por mês. Quantidade e clientes distintos saem de
    `rows` ([p, s, c, m, d, r, rev, qty]), agregando pelo índice de período — é o
    único lugar onde esses valores existem por mês.
    """
    monthly = summary.get("monthly") or []
    periodos = summary.get("maps", {}).get("p") or []
    rows = summary.get("rows") or []

    qtd_por_periodo: dict[int, int] = {}
    clientes_por_periodo: dict[int, set[int]] = {}
    for linha in rows:
        # Linhas curtas (formato antigo) não têm qty: conta cliente e ignora qty.
        indice_periodo = linha[0]
        periodo = periodos[indice_periodo] if indice_periodo < len(periodos) else None
        if periodo is None:
            continue
        if len(linha) > 7:
            qtd_por_periodo[periodo] = qtd_por_periodo.get(periodo, 0) + int(linha[7])
        clientes_por_periodo.setdefault(periodo, set()).add(linha[2])

    serie = []
    for mes in monthly:
        periodo = mes.get("pid")
        serie.append({
            "periodo": periodo,
            "rotulo": mes.get("name"),
            "rev": round(float(mes.get("rev") or 0.0), 2),
            "qty": int(qtd_por_periodo.get(periodo, 0)),
            "clientes": len(clientes_por_periodo.get(periodo, ())),
        })
    serie.sort(key=lambda item: item["periodo"] or 0)

    kpis = summary.get("kpis") or {}
    return {
        "versao": VERSAO_RESUMO,
        "updated_at": summary.get("updated_at"),
        "serie": serie,
        "totais": {
            "rev": round(float(kpis.get("rev") or 0.0), 2),
            "qty": int(kpis.get("qty") or 0),
            "clientes": len(set().union(*clientes_por_periodo.values())) if clientes_por_periodo else 0,
        },
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


def montar_card(
    empresa: str,
    resumo: dict,
    *,
    metrica: str = "receita",
    meses: int | None = 12,
) -> dict:
    """Dados de um minicard: série da métrica pedida, total e variação vs ano anterior.

    A variação compara a janela exibida com os MESMOS meses do ano anterior (jan–ago
    contra jan–ago, não contra o ano fechado). Comparar janela parcial com ano cheio
    faz o ano anterior parecer maior só por ter mais meses — erro que já apareceu no
    explorador do Analisador.
    """
    campo = METRICAS_MONITOR.get(metrica, "rev")
    inteiro = campo in ("qty", "clientes")
    eh_media = metrica in METRICAS_MEDIA
    serie = resumo.get("serie") or []
    janela = _janela(serie, meses)

    def valor(ponto: dict) -> float | int:
        bruto = ponto.get(campo) or 0
        if metrica == "receita_dia":
            dias_uteis = _dias_uteis_do_periodo(ponto.get("periodo"))
            return round(float(bruto) / dias_uteis, 2) if dias_uteis else 0.0
        return int(bruto) if inteiro else round(float(bruto), 2)

    valores = [valor(ponto) for ponto in janela]
    rotulos = [ponto.get("rotulo") for ponto in janela]
    dias_uteis_janela = sum(
        _dias_uteis_do_periodo(ponto.get("periodo")) for ponto in janela
    )
    receita_janela = sum(float(ponto.get("rev") or 0) for ponto in janela)
    total = None if eh_media else (
        sum(valores) if inteiro else round(sum(valores), 2)
    )
    media = (
        round(receita_janela / dias_uteis_janela, 2)
        if eh_media and dias_uteis_janela
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
        if metrica != "receita_dia":
            return sum(float(ponto.get(campo) or 0) for ponto in pontos)
        dias = sum(_dias_uteis_do_periodo(ponto.get("periodo")) for ponto in pontos)
        receita = sum(float(ponto.get("rev") or 0) for ponto in pontos)
        return receita / dias if dias else 0.0

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
        # incompleto), mas pesa mais na média por dia útil: o summary só informa
        # mês/ano de atualização, sem o dia, então não há como dividir apenas
        # pelos dias úteis já transcorridos.
        "ultimo_periodo_parcial": _eh_mes_corrente(
            janela[-1].get("periodo") if janela else None
        ),
        "dias_uteis_janela": dias_uteis_janela if metrica == "receita_dia" else None,
        "meses_serie": len(serie),
    }
