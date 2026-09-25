"""GPS (aba Dispersão do Power BI) dentro da tela A precificar.

As métricas são as do GPS, sem mudança de cálculo:

- **Taxa de Retorno** = Margem % − Despesas %, com despesa = Controladoria sem
  "Mercadoria Revenda" (compra de mercadoria já está no CMV; Dividendos entram —
  é o que o Export da planilha do GPS soma). Sempre os **3 últimos meses
  fechados**: o mês corrente chega parcial e a Controladoria atrasa.
- **Perfil** pela taxa: ≤ 1% Muito Conservador, até 3,5% Conservador, até 5,5%
  Moderado, até 7,5% Agressivo, acima Muito Agressivo.
- **Dispersão** = margem da descrição − margem geral da empresa, na janela do A
  precificar. A margem geral e o total da participação usam a receita inteira
  (no DAX, `ALL` no produto) — os itens fora da tabela entram só como base.
- **Participação** = receita da descrição ÷ receita total, classificada pelas
  faixas de mercado da tabela 2D (Abaixo / Dentro / Acima da Média).
- **Cenário**: perfil × participação → "Seguir a MENOR/MAIOR Dispersão 2D" ou
  "Aumentar a MC em até X%".

O que o GPS não dizia e foi decidido para a tela (set/2026):

- MAIOR é o limite da faixa **mais longe de zero**; MENOR, o **mais perto**.
- O ajuste é a **distância da posição correta**: limite-alvo − dispersão atual.
  Somar o limite à margem fazia metade dos itens se afastar da faixa.
- "Acima da Média" também usa a distância: alvo = borda mais próxima da faixa;
  para subir, o teto é o "até X" do cenário; já dentro da faixa, nada muda.
- **Teto** = largura da faixa do perfil: um degrau de perfil por rodada.

Só as 36 descrições de `gps_logica.PRODUTOS` têm GPS.
"""

from __future__ import annotations

import math
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

import consulta_parquet
import gps_logica

MESES_PERFIL = 3
CATEGORIA_FORA_DA_DESPESA = "mercadoria revenda"
# O DAX aceita o valor encostado no limite com esta folga.
TOLERANCIA = 1e-7

ROTULO_PERFIL = {
    "muito_agressivo": "Muito Agressivo",
    "agressivo": "Agressivo",
    "moderado": "Moderado",
    "conservador": "Conservador",
    "muito_conservador": "Muito Conservador",
}

# Perfil → participação → ("menor" | "maior", acréscimo) ou ("ate", X).
# Espelha o SWITCH do "Cenário Recomendado" e o bloco U:X da aba Lógica.
MATRIZ: dict[str, dict[str, tuple[str, float]]] = {
    "muito_conservador": {"abaixo": ("menor", 0.0), "dentro": ("menor", 0.0), "acima": ("ate", 1.30)},
    "conservador": {"abaixo": ("maior", 0.0), "dentro": ("menor", 0.0), "acima": ("ate", 1.00)},
    "moderado": {"abaixo": ("maior", 0.0), "dentro": ("maior", 0.0), "acima": ("ate", 0.80)},
    "agressivo": {"abaixo": ("maior", 0.50), "dentro": ("maior", 0.0), "acima": ("ate", 0.60)},
    "muito_agressivo": {"abaixo": ("maior", 0.50), "dentro": ("maior", 0.50), "acima": ("ate", 0.40)},
}

# Cruzamento com as provas do A precificar (limites aceitos em set/2026).
QUEDA_VOLUME_PCT = -15.0
CUSTO_SEM_REPASSE_PP = 2.0
FRACAO_ETAPA = 0.5

# Ordem de exibição: sobe, desce, fica.
RECOMENDACOES = (
    ("reajustar", "Reajustar", "subir"),
    ("etapas", "Subir em etapas", "subir"),
    ("oportunidade", "Oportunidade", "subir"),
    ("divergencia", "Divergência", "descer"),
    ("reduzir", "Reduzir", "descer"),
    ("segurar", "Segurar preço", "descer"),
    ("manter", "Manter", "manter"),
)


def perfil_por_taxa(taxa: float) -> str:
    if taxa <= 1.0:
        return "muito_conservador"
    if taxa <= 3.5:
        return "conservador"
    if taxa <= 5.5:
        return "moderado"
    if taxa <= 7.5:
        return "agressivo"
    return "muito_agressivo"


def meses_fechados(hoje: date, quantidade: int = MESES_PERFIL) -> list[tuple[int, int]]:
    """Os `quantidade` meses antes do mês de `hoje`, do mais antigo ao mais novo."""
    meses = []
    ano, mes = hoje.year, hoje.month
    for _ in range(quantidade):
        mes -= 1
        if mes == 0:
            ano, mes = ano - 1, 12
        meses.append((ano, mes))
    return meses[::-1]


def _filtro_meses(meses: list[tuple[int, int]]) -> tuple[str, list[int]]:
    condicao = " or ".join("(ANO = ? and MES = ?)" for _ in meses)
    return f"({condicao})", [v for par in meses for v in par]


def taxa_retorno(caminho_movimento: Path, caminho_controladoria: Path | None, hoje: date) -> dict[str, Any] | None:
    """Margem, despesas e Taxa de Retorno dos 3 meses fechados, direto nos parquet.

    `None` quando não há Controladoria ou venda no período: sem taxa não há perfil,
    e sem perfil o GPS não recomenda nada.
    """
    if caminho_controladoria is None:
        return None
    meses = meses_fechados(hoje)
    filtro, valores = _filtro_meses(meses)
    venda = consulta_parquet.consultar(
        f"select sum(TOTAL) as receita, sum(CMV) as cmv from read_parquet(?) where {filtro}",
        [str(caminho_movimento), *valores],
    ).iloc[0]
    despesa = consulta_parquet.consultar(
        "select sum(VALOR) as despesa from read_parquet(?) "
        f"where {filtro} and lower(trim(coalesce(DESCRICAO_HARMONIZADA, ''))) <> ?",
        [str(caminho_controladoria), *valores, CATEGORIA_FORA_DA_DESPESA],
    ).iloc[0]
    receita = float(venda["receita"]) if pd.notna(venda["receita"]) else 0.0
    if receita <= 0:
        return None
    margem = (receita - float(venda["cmv"] or 0.0)) / receita * 100
    despesas = float(despesa["despesa"] or 0.0) / receita * 100
    taxa = margem - despesas
    perfil = perfil_por_taxa(taxa)
    return {
        "meses": [f"{ano:04d}-{mes:02d}" for ano, mes in meses],
        "margem": margem,
        "despesas": despesas,
        "taxa_retorno": taxa,
        "perfil": perfil,
        "rotulo": ROTULO_PERFIL[perfil],
    }


def agregar_descricoes(bruto: pd.DataFrame, inicio: pd.Timestamp, fim: pd.Timestamp) -> dict[str, Any]:
    """Receita e CMV por descrição na janela, com os totais da empresa inteira.

    Usa o movimento cru do PRICE — inclusive o que não tem segmento — porque a
    margem geral e o total da participação do GPS são sobre toda a receita.
    """
    dias = pd.to_datetime(bruto["data"], errors="coerce").dt.normalize()
    janela = bruto.loc[(dias >= inicio) & (dias <= fim)]
    receita = janela["receita"].astype(float)
    cmv = janela["cmv"].astype(float)
    descricao = janela["descricao"].fillna("").astype(str).str.strip()
    por_descricao = pd.DataFrame({"descricao": descricao, "receita": receita, "cmv": cmv})
    por_descricao = por_descricao.loc[por_descricao["descricao"].isin(gps_logica.PRODUTOS)]
    return {
        "receita_total": float(receita.sum()),
        "cmv_total": float(cmv.sum()),
        "por_descricao": por_descricao.groupby("descricao")[["receita", "cmv"]].sum(),
    }


def _classe_participacao(participacao: float, limites: tuple[float, float]) -> str:
    abaixo_ate, dentro_ate = limites
    if participacao <= abaixo_ate + TOLERANCIA:
        return "abaixo"
    if participacao <= dentro_ate + TOLERANCIA:
        return "dentro"
    return "acima"


def _perfil_do_item(dispersao: float, faixas: tuple[gps_logica.Faixa, ...]) -> str | None:
    """Perfil em que o preço atual do item cai (a "Dispersão MC Sugerida")."""
    for perfil, (minimo, maximo) in zip(gps_logica.PERFIS, faixas):
        if (minimo is None or dispersao >= minimo - TOLERANCIA) and dispersao <= maximo + TOLERANCIA:
            return perfil
    return None


def _faixa_e_teto(faixas: tuple[gps_logica.Faixa, ...], perfil: str) -> tuple[float | None, float, float]:
    """(mínimo, máximo, largura) da faixa do perfil.

    A faixa Muito Agressivo é "Até X", aberta para baixo: largura infinita não
    serve de teto, então vale a da faixa vizinha (Agressivo).
    """
    indice = gps_logica.PERFIS.index(perfil)
    minimo, maximo = faixas[indice]
    if minimo is None:
        vizinho_min, vizinho_max = faixas[indice + 1]
        return None, maximo, vizinho_max - vizinho_min
    return minimo, maximo, maximo - minimo


def _limitar(valor: float, teto_subida: float, teto_descida: float) -> float:
    if valor > 0:
        return min(valor, teto_subida)
    if valor < 0:
        return max(valor, -teto_descida)
    return 0.0


def calcular_descricao(
    nome: str, receita: float, cmv: float, receita_total: float, margem_geral: float, perfil: str,
) -> dict[str, Any]:
    """Métricas do GPS de uma descrição e o ajuste de margem que ele pede."""
    faixas, limites_part = gps_logica.PRODUTOS[nome]
    margem = (receita - cmv) / receita * 100
    dispersao = margem - margem_geral
    participacao = receita / receita_total * 100
    classe = _classe_participacao(participacao, limites_part)
    minimo, maximo, teto = _faixa_e_teto(faixas, perfil)
    tipo, valor = MATRIZ[perfil][classe]

    if tipo == "ate":
        # Acima da Média: vai até a borda mais próxima da faixa; a subida para no X do cenário.
        if (minimo is None or dispersao >= minimo) and dispersao <= maximo:
            distancia = 0.0
        elif minimo is not None and dispersao < minimo:
            distancia = minimo - dispersao
        else:
            distancia = maximo - dispersao
        limite_alvo = None
        regra = f"até +{valor:.2f}".replace(".", ",")
        aplicado = _limitar(distancia, valor, teto)
        teto_subida = valor
    else:
        candidatos = [maximo] if minimo is None else [minimo, maximo]
        longe = max(candidatos, key=abs)
        perto = min(candidatos, key=abs)
        limite_alvo = (longe if tipo == "maior" else perto) + valor
        regra = ("MAIOR" if tipo == "maior" else "MENOR") + (f" + {valor:.2f}".replace(".", ",") if valor else "")
        distancia = limite_alvo - dispersao
        aplicado = _limitar(distancia, teto, teto)
        teto_subida = teto

    if abs(aplicado) < 0.005:
        aplicado = 0.0
    return {
        "margem": margem,
        "participacao": participacao,
        "classe": classe,
        "dispersao": dispersao,
        "perfil_item": _perfil_do_item(dispersao, faixas),
        "faixa": [minimo, maximo],
        "regra": regra,
        "limite_alvo": limite_alvo,
        "distancia": distancia,
        "teto": teto_subida if aplicado > 0 else teto,
        "aplicado": aplicado,
    }


def calcular(agregado: dict[str, Any], perfil: str) -> dict[str, Any]:
    """Margem geral e o GPS de cada uma das 36 descrições com venda na janela."""
    receita_total = agregado["receita_total"]
    if receita_total <= 0:
        return {"margem_geral": None, "descricoes": {}}
    margem_geral = (receita_total - agregado["cmv_total"]) / receita_total * 100
    descricoes = {}
    for nome, linha in agregado["por_descricao"].iterrows():
        if linha["receita"] > 0:
            descricoes[nome] = calcular_descricao(
                nome, float(linha["receita"]), float(linha["cmv"]), receita_total, margem_geral, perfil,
            )
    return {"margem_geral": margem_geral, "descricoes": descricoes}


def recomendar(aplicado: float, var_qtd: float | None, sem_repasse: float | None, sinalizado: bool) -> str:
    """Cruza o ajuste do GPS com as provas do A precificar. A ordem importa."""
    volume_caiu = var_qtd is not None and not math.isnan(var_qtd) and var_qtd <= QUEDA_VOLUME_PCT
    custo_sem_repasse = sem_repasse is not None and not math.isnan(sem_repasse) and sem_repasse >= CUSTO_SEM_REPASSE_PP
    if aplicado > 0:
        if volume_caiu:
            return "etapas"
        if sinalizado or custo_sem_repasse:
            return "reajustar"
        return "oportunidade"
    if aplicado < 0:
        if custo_sem_repasse:
            return "segurar"
        if volume_caiu:
            return "reduzir"
        if sinalizado:
            return "divergencia"
    return "manter"


def ajuste_agora(recomendacao: str, aplicado: float) -> float:
    """Quanto mexer na margem nesta rodada."""
    if recomendacao in ("reajustar", "oportunidade", "reduzir"):
        return aplicado
    if recomendacao == "etapas":
        return aplicado * FRACAO_ETAPA
    # Segurar: mantém a margem (o preço acompanha o custo). Divergência: revisar antes.
    return 0.0
