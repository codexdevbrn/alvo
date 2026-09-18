"""Painel analítico da carteira de clientes.

Mesmo recorte das demais telas: mês de referência = último `Periodo_Mensal` da
base, comparado à média dos 6 meses anteriores (`periodo_mensal`).

Movimento da carteira usa uma única janela de inatividade
(`JANELA_INATIVIDADE_MESES`), e cada evento é contado **uma vez**:

| Evento | Regra |
|---|---|
| Novo | primeira compra da base cai no mês |
| Recuperado | comprou no mês depois de ficar a janela inteira parado |
| Perdido | comprou há exatamente uma janela e não comprou desde então |

Contar "perdido" como "estava ativo na janela e sumiu no mês" repetiria o mesmo
cliente em três meses seguidos — por isso a régua é a última compra, não a
presença na janela.

A curva ABC reaproveita `curva_pareto`/`faixa_por_curva` do motor com os cortes
do `config.json` da empresa: a tela não pode classificar por uma régua
diferente da do Analisador.

Cliente marcado com a tag de balcão fica **fora de todo o painel**. Consumidor
final costuma ser uma linha só, com receita de centenas de clientes: dentro da
curva ele afunda o Pareto, e dentro do movimento vira um "cliente" que nunca
entra nem sai. A contagem excluída volta em `balcao_excluidos` para o número
não sumir sem aviso.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from engine.analise_funil import (
    _causa_provavel_migracao,
    _preparar_contexto_causa_provavel,
    classificar_abc,
    curva_pareto,
    faixa_por_curva,
    nomes_faixas,
    poder_compra_agregado,
)
from periodo_mensal import (
    COLUNA_DATA_DIARIA,
    converter_periodo,
    deslocar_mes,
    dia_corte_mes_aberto,
    filtrar_ate_o_dia,
    inicio_mes,
    modo_periodo_valido,
    numero,
    referencia_efetiva,
    rotulo_periodo,
    variacao,
)


MESES_HISTORICO = 6
JANELA_INATIVIDADE_MESES = 3
MESES_MOVIMENTO = 12
JANELA_ABC_MESES = 12
LIMITE_TOP_CLIENTES = 20
LIMITE_EVENTOS = 20
LIMITE_ALERTA_PCT = 20.0
CORTES_PADRAO = (30.0, 50.0, 60.0)
NOME_SEM_CLIENTE = "Não informado"

# Score de migração entre faixas ABC — mesmos pesos de
# engine.analise_funil.pontuacao_migracao_clientes (a régua "oficial" já
# testada no Analisador). Reimplementado aqui em vez de chamar
# migracao_abc/pontuacao_migracao_clientes direto: aquelas funções também
# calculam a causa provável de cada migração (não usada nesta tela) e para
# isso exigem colunas — descricao, QTD por produto — que o painel do
# Dashboard não carrega e que custariam caro (groupby produto a produto)
# sem gerar nenhum dado exibido aqui.
JANELA_SCORE_MESES = JANELA_ABC_MESES
LIMITE_RANKING_SCORE = 20
LIMITE_SCORE_POR_CAUDA = -5
PONTOS_SUBIU_FAIXA = 3
PONTOS_DESCEU_FAIXA = -2

# Potencial de compra: média dos 3 meses-calendário de maior receita de cada
# cliente na mesma janela de 12 meses da Concentração da carteira/Score de
# migração — reaproveita engine.analise_funil.poder_compra_agregado, que já
# usa só Cliente/Receita/Periodo_Mensal (sem o custo da causa provável da
# migração, que precisa de descricao/QTD por produto).
JANELA_POTENCIAL_MESES = JANELA_ABC_MESES
LIMITE_RANKING_POTENCIAL = 20
LIMITE_TOP_PRODUTOS_POTENCIAL = 3
MESES_PICO_POTENCIAL = 3


class ErroPainelClientes(ValueError):
    """Erro de dados que a API pode mostrar direto."""


def _arredondar(valor: float | None) -> float | None:
    return None if valor is None else round(valor, 2)


def _resposta_vazia(mensagem: str) -> dict:
    return {
        "disponivel": False,
        "mensagem": mensagem,
        "periodo_atual": None,
        "rotulo_periodo": None,
        "meses_media": 0,
        "periodo_media_inicio": None,
        "periodo_media_fim": None,
        "janela_inatividade_meses": JANELA_INATIVIDADE_MESES,
        "janela_abc_meses": JANELA_ABC_MESES,
        "balcao_excluidos": 0,
        "resumo": {
            "clientes_ativos": 0,
            "clientes_media": 0.0,
            "variacao_clientes": None,
            "receita_atual": 0.0,
            "receita_media": 0.0,
            "variacao_receita": None,
            "ticket_medio": 0.0,
            "ticket_medio_media": 0.0,
            "variacao_ticket": None,
            "novos": 0,
            "recuperados": 0,
            "perdidos": 0,
            "saldo": 0,
        },
        "concentracao": {
            "clientes": 0,
            "receita": 0.0,
            "clientes_80": 0,
            "participacao_clientes_80": 0.0,
            "faixas": [],
        },
        "movimento": [],
        "eventos": {"novos": [], "recuperados": [], "perdidos": []},
        "top_clientes": [],
        "tags": [],
        "score_migracao": _score_migracao_vazio(),
        "potencial_compra": _potencial_compra_vazio(),
    }


def _sem_balcao(dados: pd.DataFrame, clientes_balcao) -> tuple[pd.DataFrame, int]:
    """Remove os clientes de balcão e diz quantos saíram."""
    nomes = {
        str(nome).strip() for nome in (clientes_balcao or []) if str(nome).strip()
    }
    if not nomes:
        return dados, 0
    fora = dados["Cliente"].isin(nomes)
    return dados.loc[~fora], int(dados.loc[fora, "Cliente"].nunique())


def _normalizar_cliente(serie: pd.Series) -> pd.Series:
    textos = serie.fillna("").astype(str).str.strip()
    textos = textos.mask(textos.str.lower().isin(("nan", "none", "<na>")), "")
    return textos.replace("", NOME_SEM_CLIENTE)


def _preparar(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.Timestamp]:
    if df is None or df.empty:
        raise ErroPainelClientes("A base está vazia.")
    faltantes = sorted({"Cliente", "Receita"} - set(df.columns))
    if faltantes:
        raise ErroPainelClientes("Base sem colunas necessárias: " + ", ".join(faltantes))

    colunas = [
        coluna for coluna in (
            "Cliente", "Receita", "QTD", "Periodo_Mensal", "Data_Venda", COLUNA_DATA_DIARIA,
        )
        if coluna in df.columns
    ]
    dados = df.loc[:, colunas].copy()
    dados["_periodo"] = converter_periodo(dados)
    cobertura = float(dados["_periodo"].notna().mean() * 100)
    if cobertura < 95:
        raise ErroPainelClientes(
            f"Período mensal incompleto: {cobertura:.1f}% das linhas possuem mês válido."
        )
    dados = dados.dropna(subset=["_periodo"])
    if dados.empty:
        raise ErroPainelClientes("A base não tem nenhum mês válido.")
    dados["Cliente"] = _normalizar_cliente(dados["Cliente"])
    dados["Receita"] = pd.to_numeric(dados["Receita"], errors="coerce").fillna(0.0)
    if "QTD" in dados.columns:
        dados["QTD"] = pd.to_numeric(dados["QTD"], errors="coerce").fillna(0.0)
    else:
        dados["QTD"] = 0.0
    return dados, inicio_mes(dados["_periodo"].max())


def _meses_ate(referencia: pd.Timestamp, quantidade: int) -> list[pd.Timestamp]:
    """Sequência de calendário terminando em `referencia`, do mais antigo ao mês."""
    return [deslocar_mes(referencia, -passo) for passo in range(quantidade - 1, -1, -1)]


def _presenca_por_mes(dados: pd.DataFrame) -> dict[pd.Timestamp, set[str]]:
    pares = dados.loc[:, ["Cliente", "_periodo"]].drop_duplicates()
    return {
        periodo: set(grupo["Cliente"].tolist())
        for periodo, grupo in pares.groupby("_periodo", sort=False)
    }


def _movimento_da_carteira(
    dados: pd.DataFrame,
    referencia: pd.Timestamp,
) -> tuple[list[dict], dict[str, set[str]]]:
    """Novos, recuperados e perdidos mês a mês (janela de inatividade fixa).

    Devolve também os nomes por evento do mês de referência — a tela lista quem
    entrou e quem saiu, e recalcular isso no navegador exigiria a base inteira.
    """
    presenca = _presenca_por_mes(dados)
    primeira_compra = dados.groupby("Cliente")["_periodo"].min()
    primeiro_mes_base = inicio_mes(dados["_periodo"].min())
    receita_por_mes = dados.groupby("_periodo")["Receita"].sum()
    janela = JANELA_INATIVIDADE_MESES

    linhas: list[dict] = []
    eventos: dict[str, set[str]] = {"novos": set(), "recuperados": set(), "perdidos": set()}
    for mes in _meses_ate(referencia, MESES_MOVIMENTO):
        if mes < primeiro_mes_base:
            continue
        ativos = presenca.get(mes, set())
        anteriores: set[str] = set()
        for passo in range(1, janela + 1):
            anteriores |= presenca.get(deslocar_mes(mes, -passo), set())

        e_primeiro_mes = mes == primeiro_mes_base
        novos = set() if e_primeiro_mes else {
            cliente for cliente in ativos if primeira_compra.get(cliente) == mes
        }
        recuperados = {
            cliente for cliente in ativos
            if cliente not in anteriores and cliente not in novos
        } if not e_primeiro_mes else set()

        # Perdido = comprou há exatamente uma janela e não voltou desde então.
        desde_o_corte: set[str] = set()
        for passo in range(0, janela):
            desde_o_corte |= presenca.get(deslocar_mes(mes, -passo), set())
        perdidos = presenca.get(deslocar_mes(mes, -janela), set()) - desde_o_corte
        if mes == referencia:
            eventos = {"novos": novos, "recuperados": recuperados, "perdidos": perdidos}

        linhas.append({
            "periodo": mes.strftime("%Y-%m"),
            "rotulo": rotulo_periodo(mes),
            "ativos": len(ativos),
            "novos": len(novos),
            "recuperados": len(recuperados),
            "perdidos": len(perdidos),
            "saldo": len(novos) + len(recuperados) - len(perdidos),
            "receita": round(numero(receita_por_mes.get(mes, 0.0)), 2),
        })
    return linhas, eventos


def _lista_eventos(
    dados: pd.DataFrame,
    nomes: set[str],
    referencia: pd.Timestamp,
    usar_ultima_compra: bool,
) -> list[dict]:
    """Nomes de um evento, do maior valor para o menor.

    `usar_ultima_compra` = perdido: o valor que interessa é o do último mês em
    que ele comprou, não o do mês de referência (onde ele é zero).
    """
    if not nomes:
        return []
    recorte = dados.loc[dados["Cliente"].isin(nomes)]
    if usar_ultima_compra:
        ultimo = recorte.groupby("Cliente")["_periodo"].max()
        chaves = list(zip(ultimo.index, ultimo.to_numpy()))
        por_mes = recorte.groupby(["Cliente", "_periodo"])["Receita"].sum()
        itens = [
            {
                "cliente": str(cliente),
                "receita": round(numero(por_mes.get((cliente, mes), 0.0)), 2),
                "ultimo_mes": rotulo_periodo(inicio_mes(pd.Timestamp(mes))),
            }
            for cliente, mes in chaves
        ]
    else:
        no_mes = recorte.loc[recorte["_periodo"] == referencia].groupby("Cliente")["Receita"].sum()
        itens = [
            {
                "cliente": str(cliente),
                "receita": round(numero(no_mes.get(cliente, 0.0)), 2),
                "ultimo_mes": None,
            }
            for cliente in nomes
        ]
    itens.sort(key=lambda item: item["receita"], reverse=True)
    return itens[:LIMITE_EVENTOS]


def _curva_abc(
    dados: pd.DataFrame,
    referencia: pd.Timestamp,
    cortes: tuple[float, ...],
) -> tuple[dict, pd.Series]:
    """Faixas da curva sobre a janela ABC; devolve o resumo e a receita por cliente."""
    meses = set(_meses_ate(referencia, JANELA_ABC_MESES))
    recorte = dados.loc[dados["_periodo"].isin(meses)]
    receita = recorte.groupby("Cliente")["Receita"].sum().sort_values(ascending=False)
    receita = receita[receita > 0]
    total = float(receita.sum())
    vazio = {
        "clientes": 0,
        "receita": 0.0,
        "clientes_80": 0,
        "participacao_clientes_80": 0.0,
        "faixas": [],
    }
    if receita.empty or total <= 0:
        return vazio, receita

    curva = curva_pareto(receita)
    faixa = faixa_por_curva(curva, cortes)
    acumulado = curva["Percentual_Acumulado"].to_numpy(dtype=float)
    clientes_80 = min(int(np.searchsorted(acumulado, 80.0, side="left")) + 1, len(acumulado))

    faixas = []
    for nome in nomes_faixas(cortes):
        recorte_faixa = curva.loc[faixa == nome]
        if recorte_faixa.empty:
            continue
        receita_faixa = float(recorte_faixa["Receita"].sum())
        faixas.append({
            "nome": nome,
            "clientes": int(len(recorte_faixa)),
            "receita": round(receita_faixa, 2),
            "participacao": round(receita_faixa / total * 100, 2),
        })

    return {
        "clientes": int(len(receita)),
        "receita": round(total, 2),
        "clientes_80": clientes_80,
        "participacao_clientes_80": round(clientes_80 / len(receita) * 100, 2),
        "faixas": faixas,
    }, receita


def _top_clientes(
    dados: pd.DataFrame,
    referencia: pd.Timestamp,
    historico: list[pd.Timestamp],
    dia_corte: int | None = None,
) -> list[dict]:
    """Maiores clientes do mês contra a média do histórico, como o ranking de vendedores."""
    divisor = max(len(historico), 1)
    atual = dados.loc[dados["_periodo"] == referencia]
    hist = filtrar_ate_o_dia(dados.loc[dados["_periodo"].isin(historico)], dia_corte)
    receita_atual = atual.groupby("Cliente")["Receita"].sum()
    qtd_atual = atual.groupby("Cliente")["QTD"].sum()
    receita_hist = hist.groupby("Cliente")["Receita"].sum() / divisor

    itens = []
    for nome in receita_atual.sort_values(ascending=False).head(LIMITE_TOP_CLIENTES).index:
        valor_atual = numero(receita_atual.get(nome, 0.0))
        valor_media = numero(receita_hist.get(nome, 0.0))
        var = variacao(valor_atual, valor_media)
        itens.append({
            "cliente": str(nome),
            "receita_atual": round(valor_atual, 2),
            "receita_media": round(valor_media, 2),
            "variacao": _arredondar(var),
            "qtd_atual": round(numero(qtd_atual.get(nome, 0.0)), 2),
            "alerta": var is not None and var <= -LIMITE_ALERTA_PCT,
        })
    return itens


def _resumo_por_tag(
    tags: dict | None,
    catalogo: list | None,
    receita_por_cliente: pd.Series,
    receita_total: float,
) -> list[dict]:
    """Contagem e receita (janela ABC) de cada tag ativa do catálogo."""
    if not catalogo:
        return []
    por_tag: dict[str, list[str]] = {}
    for cliente, marcadas in (tags or {}).items():
        nome = str(cliente or "").strip()
        if not nome:
            continue
        for tag in marcadas or []:
            por_tag.setdefault(str(tag), []).append(nome)

    linhas = []
    for item in catalogo:
        if not isinstance(item, dict) or not item.get("ativa"):
            continue
        tag_id = str(item.get("id") or "").strip()
        if not tag_id:
            continue
        clientes = por_tag.get(tag_id, [])
        receita = float(sum(numero(receita_por_cliente.get(nome, 0.0)) for nome in clientes))
        linhas.append({
            "id": tag_id,
            "rotulo": str(item.get("rotulo") or tag_id),
            "cor": item.get("cor"),
            "clientes": len(clientes),
            "receita": round(receita, 2),
            "participacao": round(receita / receita_total * 100, 2) if receita_total > 0 else 0.0,
        })
    linhas.sort(key=lambda linha: (linha["receita"], linha["clientes"]), reverse=True)
    return linhas


def _cortes_validos(cortes) -> tuple[float, ...]:
    """Cortes crescentes entre 0 e 100; qualquer coisa fora disso vira o padrão."""
    try:
        valores = tuple(float(valor) for valor in cortes)
    except (TypeError, ValueError):
        return CORTES_PADRAO
    if not valores or any(not 0 < valor <= 100 for valor in valores):
        return CORTES_PADRAO
    if list(valores) != sorted(valores):
        return CORTES_PADRAO
    return valores


def _ordem_faixas(faixas_unicas: list[str]) -> dict[str, int]:
    """Faixa mais valiosa = maior ordem; "Demais" sempre a menor.

    Mesma heurística de engine.analise_funil.migracao_abc: a ordem vem da
    própria numeração da faixa ("Grupo 1" > "Grupo 2" > ...), com "Demais"
    fixado no fim.
    """
    nomeadas = sorted(
        (f for f in faixas_unicas if f != "Demais"),
        key=lambda nome: int(nome.split()[-1]) if nome.split()[-1].isdigit() else 99,
    )
    ordenadas = nomeadas + (["Demais"] if "Demais" in faixas_unicas else [])
    return {nome: len(ordenadas) - indice for indice, nome in enumerate(ordenadas)}


def _score_migracao_vazio() -> dict:
    return {
        "disponivel": False,
        "janela_meses": JANELA_SCORE_MESES,
        "clientes_score_diferente_zero": 0,
        "clientes_pior_cauda": 0,
        "saldo_ultimo_periodo": None,
        "distribuicao": [],
        "saldo_por_periodo": [],
        "pior_cauda": [],
        "melhores": [],
    }


def _faixa_score(score: int) -> str:
    if score <= LIMITE_SCORE_POR_CAUDA:
        return "≤ -5"
    if score < 0:
        return "-4 a -1"
    return "+1 ou mais"


def _linhas_ranking_score(recorte: pd.DataFrame) -> list[dict]:
    return [
        {
            "cliente": str(linha.Cliente),
            "score": int(linha.Score),
            "subiu": int(linha.Qtd_Subiu),
            "desceu": int(linha.Qtd_Desceu),
            "permanencia": round(float(linha.Percentual_Permanencia), 1),
        }
        for linha in recorte.itertuples()
    ]


def _score_migracao(
    dados: pd.DataFrame,
    referencia: pd.Timestamp,
    cortes: tuple[float, ...],
) -> dict:
    """Score de migração entre faixas ABC nos últimos JANELA_SCORE_MESES
    meses: +3 por subida de faixa, -2 por descida (acumulado no período),
    e % de permanência (meses em que o cliente não migrou, das vezes em que
    apareceu em dois meses seguidos). Ver o comentário de PONTOS_SUBIU_FAIXA.
    """
    meses = _meses_ate(referencia, JANELA_SCORE_MESES)
    recorte = dados.loc[dados["_periodo"].isin(meses)]
    if recorte.empty:
        return _score_migracao_vazio()

    abc = classificar_abc(
        recorte, granularidade="Mensal", clientes_excluidos=None,
        cortes_clientes=cortes, desconsiderar_balcao=False, top_clientes_por_grupo=None,
    )
    if abc.empty:
        return _score_migracao_vazio()

    periodos = sorted(abc["Periodo"].unique())
    if len(periodos) < 2:
        return _score_migracao_vazio()

    ordem_faixa = _ordem_faixas(list(abc["Faixa_ABC"].unique()))
    abc = abc[["Cliente", "Periodo", "Faixa_ABC"]].copy()
    abc["Ordem"] = abc["Faixa_ABC"].map(ordem_faixa)

    pares_comuns: list[pd.DataFrame] = []
    saldo_por_periodo: list[dict] = []
    for anterior, atual in zip(periodos, periodos[1:]):
        tabela_anterior = abc.loc[abc["Periodo"] == anterior, ["Cliente", "Ordem"]]
        tabela_atual = abc.loc[abc["Periodo"] == atual, ["Cliente", "Ordem"]]
        par = tabela_anterior.merge(tabela_atual, on="Cliente", suffixes=("_ant", "_atu"))

        rotulo_curto = rotulo_periodo(pd.Timestamp(atual))
        rotulo = f"{rotulo_periodo(pd.Timestamp(anterior))}→{rotulo_curto}"
        if par.empty:
            saldo_por_periodo.append({
                "periodo_anterior": anterior, "periodo_atual": atual,
                "rotulo": rotulo, "rotulo_curto": rotulo_curto,
                "subiu": 0, "desceu": 0, "saldo": 0,
            })
            continue

        par["Direcao"] = np.where(
            par["Ordem_atu"] == par["Ordem_ant"], "Igual",
            np.where(par["Ordem_atu"] > par["Ordem_ant"], "Subiu", "Desceu"),
        )
        qtd_subiu = int((par["Direcao"] == "Subiu").sum())
        qtd_desceu = int((par["Direcao"] == "Desceu").sum())
        saldo_por_periodo.append({
            "periodo_anterior": anterior, "periodo_atual": atual,
            "rotulo": rotulo, "rotulo_curto": rotulo_curto,
            "subiu": qtd_subiu, "desceu": qtd_desceu, "saldo": qtd_subiu - qtd_desceu,
        })
        pares_comuns.append(par[["Cliente", "Direcao"]])

    if not pares_comuns:
        return _score_migracao_vazio()

    todas_transicoes = pd.concat(pares_comuns, ignore_index=True)
    transicoes_por_cliente = todas_transicoes["Cliente"].value_counts()
    transicoes_por_cliente.index.name = "Cliente"

    migrou = todas_transicoes.loc[todas_transicoes["Direcao"] != "Igual"]
    contagem = migrou.groupby(["Cliente", "Direcao"]).size().unstack(fill_value=0)
    for direcao in ("Subiu", "Desceu"):
        if direcao not in contagem.columns:
            contagem[direcao] = 0

    resultado = transicoes_por_cliente.rename("Transicoes").reset_index()
    resultado = resultado.merge(
        contagem[["Subiu", "Desceu"]].reset_index(), on="Cliente", how="left",
    )
    resultado[["Subiu", "Desceu"]] = resultado[["Subiu", "Desceu"]].fillna(0).astype(int)
    resultado.rename(columns={"Subiu": "Qtd_Subiu", "Desceu": "Qtd_Desceu"}, inplace=True)
    resultado["Score"] = (
        resultado["Qtd_Subiu"] * PONTOS_SUBIU_FAIXA + resultado["Qtd_Desceu"] * PONTOS_DESCEU_FAIXA
    )
    migracoes_totais = resultado["Qtd_Subiu"] + resultado["Qtd_Desceu"]
    resultado["Percentual_Permanencia"] = np.where(
        resultado["Transicoes"] > 0,
        (resultado["Transicoes"] - migracoes_totais) / resultado["Transicoes"] * 100,
        100.0,
    )

    quem_migrou = resultado.loc[resultado["Score"] != 0].copy()
    quem_migrou["Faixa_Score"] = quem_migrou["Score"].map(_faixa_score)
    distribuicao = [
        {"faixa": faixa, "clientes": int((quem_migrou["Faixa_Score"] == faixa).sum())}
        for faixa in ("≤ -5", "-4 a -1", "+1 ou mais")
    ]

    pior_cauda = resultado.loc[resultado["Score"] < 0].sort_values("Score").head(LIMITE_RANKING_SCORE)
    melhores = resultado.loc[resultado["Score"] > 0].sort_values("Score", ascending=False).head(LIMITE_RANKING_SCORE)

    return {
        "disponivel": True,
        "janela_meses": JANELA_SCORE_MESES,
        "clientes_score_diferente_zero": int(len(quem_migrou)),
        "clientes_pior_cauda": int((resultado["Score"] <= LIMITE_SCORE_POR_CAUDA).sum()),
        "saldo_ultimo_periodo": saldo_por_periodo[-1] if saldo_por_periodo else None,
        "distribuicao": distribuicao,
        "saldo_por_periodo": saldo_por_periodo,
        "pior_cauda": _linhas_ranking_score(pior_cauda),
        "melhores": _linhas_ranking_score(melhores),
    }


def _causa_migracao_vazia(cliente: str) -> dict:
    return {
        "disponivel": False,
        "cliente": cliente,
        "eventos": [],
    }


def causa_migracao_cliente(
    df: pd.DataFrame | None,
    cliente: str,
    cortes=None,
    modo_periodo: str = "fechados",
) -> dict:
    """Os eventos de migração de faixa ABC (subiu/desceu) de UM cliente na
    mesma janela do Score de migração, cada um com a causa provável — o
    "porquê" por trás do score de `_score_migracao`.

    Reclassifica a empresa inteira (ABC depende da posição relativa de todo
    mundo, não dá pra escopar isso a um cliente), mas só entra em transição
    "Subiu"/"Desceu" as que este cliente de fato teve — mesma régua de
    `_score_migracao` (par de períodos ADJACENTES no calendário da empresa
    toda, cliente presente nos dois; um mês sem compra no meio não gera uma
    transição "salteada"). A causa provável (`engine.analise_funil`,
    heurística já testada no Analisador: produto abandonado, frequência,
    ticket médio) só roda pra este cliente — reclassificar todo mundo já é
    caro, mas o groupby produto a produto da causa é o que o docstring de
    `migracao_abc` chama de gargalo real, e por isso não roda pro painel
    inteiro (só sob demanda, aqui).

    Recebe o df ORIGINAL (com `descricao`), como `top_produtos_potencial_cliente`.
    """
    vazio = _causa_migracao_vazia(cliente)
    if df is None or df.empty:
        return vazio
    faltantes = sorted({"Cliente", "Receita", "Periodo_Mensal", "descricao"} - set(df.columns))
    if faltantes:
        return vazio

    alvo = _normalizar_cliente(pd.Series([cliente])).iloc[0]
    colunas = [c for c in ("Cliente", "Receita", "QTD", "Periodo_Mensal", "descricao") if c in df.columns]
    base = df.loc[:, colunas].copy()
    base["Cliente"] = _normalizar_cliente(base["Cliente"])
    base["_periodo"] = converter_periodo(base)
    base = base.dropna(subset=["_periodo"])
    if base.empty:
        return vazio

    modo_periodo = modo_periodo_valido(modo_periodo)
    referencia = referencia_efetiva(inicio_mes(base["_periodo"].max()), modo_periodo == "fechados")

    meses = set(_meses_ate(referencia, JANELA_SCORE_MESES))
    recorte = base.loc[base["_periodo"].isin(meses)].copy()
    if recorte.empty:
        return vazio
    recorte["Receita"] = pd.to_numeric(recorte["Receita"], errors="coerce").fillna(0.0)
    if "QTD" in recorte.columns:
        recorte["QTD"] = pd.to_numeric(recorte["QTD"], errors="coerce").fillna(0.0)
    else:
        recorte["QTD"] = 0.0

    abc = classificar_abc(
        recorte, granularidade="Mensal", clientes_excluidos=None,
        cortes_clientes=_cortes_validos(cortes), desconsiderar_balcao=False, top_clientes_por_grupo=None,
    )
    if abc.empty or alvo not in set(abc["Cliente"]):
        return vazio

    periodos = sorted(abc["Periodo"].unique())
    if len(periodos) < 2:
        return vazio

    ordem_faixa = _ordem_faixas(list(abc["Faixa_ABC"].unique()))
    abc_cliente = abc.loc[abc["Cliente"] == alvo, ["Periodo", "Faixa_ABC"]].copy()
    abc_cliente["Ordem"] = abc_cliente["Faixa_ABC"].map(ordem_faixa)
    faixa_por_periodo = abc_cliente.set_index("Periodo")[["Faixa_ABC", "Ordem"]]

    recorte_cliente = recorte.loc[recorte["Cliente"] == alvo]
    contexto = _preparar_contexto_causa_provavel(recorte_cliente, "Periodo_Mensal") if not recorte_cliente.empty else None

    eventos = []
    for anterior, atual in zip(periodos, periodos[1:]):
        if anterior not in faixa_por_periodo.index or atual not in faixa_por_periodo.index:
            continue
        linha_anterior = faixa_por_periodo.loc[anterior]
        linha_atual = faixa_por_periodo.loc[atual]
        if linha_atual["Ordem"] == linha_anterior["Ordem"]:
            continue
        direcao = "Subiu" if linha_atual["Ordem"] > linha_anterior["Ordem"] else "Desceu"
        causa = _causa_provavel_migracao(contexto, alvo, anterior, atual, direcao) if contexto else ""
        eventos.append({
            "periodo_anterior": rotulo_periodo(pd.Timestamp(anterior)),
            "periodo_atual": rotulo_periodo(pd.Timestamp(atual)),
            "direcao": direcao,
            "faixa_anterior": str(linha_anterior["Faixa_ABC"]),
            "faixa_atual": str(linha_atual["Faixa_ABC"]),
            "causa": causa,
        })

    return {
        "disponivel": True,
        "cliente": cliente,
        "eventos": eventos,
    }


def _potencial_compra_vazio() -> dict:
    return {
        "disponivel": False,
        "janela_meses": JANELA_POTENCIAL_MESES,
        "potencial_total": 0.0,
        "potencial_medio": 0.0,
        "atual_total": 0.0,
        "variacao_total": None,
        "por_grupo": [],
        "ranking": [],
    }


def _potencial_compra(
    dados: pd.DataFrame,
    referencia: pd.Timestamp,
    cortes: tuple[float, ...],
) -> dict:
    """Potencial de compra de cada cliente: média dos 3 meses-calendário de
    MAIOR receita na janela (não a média corrida) — a capacidade de compra no
    melhor momento do cliente, igual à métrica homônima do Analisador (ver
    engine.analise_funil.poder_compra_agregado).
    """
    meses = _meses_ate(referencia, JANELA_POTENCIAL_MESES)
    recorte = dados.loc[dados["_periodo"].isin(meses)]
    if recorte.empty:
        return _potencial_compra_vazio()

    resultado = poder_compra_agregado(recorte, clientes_excluidos=None, cortes=cortes, desconsiderar_balcao=False)
    if resultado.empty:
        return _potencial_compra_vazio()

    potencial_total = float(resultado["Poder_De_Compra"].sum())
    potencial_medio = float(resultado["Poder_De_Compra"].mean())
    atual_total = float(resultado["Receita_Media_Mensal"].sum())

    # Média por cliente do grupo, não soma: Grupo 1 tem 11 clientes e "Demais"
    # pode ter dezenas de milhares — somar faria "Demais" dominar o gráfico só
    # por ter mais gente, não por ter potencial individual maior (é o oposto).
    estatisticas_por_grupo = resultado.groupby("Grupo")["Poder_De_Compra"].agg(["mean", "count"])
    por_grupo = [
        {
            "nome": nome,
            "potencial_medio": round(float(estatisticas_por_grupo.loc[nome, "mean"]), 2),
            "clientes": int(estatisticas_por_grupo.loc[nome, "count"]),
        }
        for nome in nomes_faixas(cortes)
        if nome in estatisticas_por_grupo.index
    ]

    ranking_df = resultado.sort_values("Poder_De_Compra", ascending=False).head(LIMITE_RANKING_POTENCIAL)
    ranking = [
        {
            "cliente": str(linha.Cliente),
            "potencial": round(float(linha.Poder_De_Compra), 2),
            "atual": round(float(linha.Receita_Media_Mensal), 2),
            # variacao(atual, potencial): mesma convenção do resto do painel
            # (atual contra uma referência) — negativo quando o cliente
            # compra abaixo do potencial, o caso comum e que é a má notícia.
            "variacao": _arredondar(variacao(float(linha.Receita_Media_Mensal), float(linha.Poder_De_Compra))),
            "grupo": str(linha.Grupo),
        }
        for linha in ranking_df.itertuples()
    ]

    return {
        "disponivel": True,
        "janela_meses": JANELA_POTENCIAL_MESES,
        "potencial_total": round(potencial_total, 2),
        "potencial_medio": round(potencial_medio, 2),
        "atual_total": round(atual_total, 2),
        "variacao_total": _arredondar(variacao(atual_total, potencial_total)),
        "por_grupo": por_grupo,
        "ranking": ranking,
    }


def _top_produtos_potencial_vazio(cliente: str) -> dict:
    return {
        "disponivel": False,
        "cliente": cliente,
        "meses": [],
        "receita_total": 0.0,
        "potencial": 0.0,
        "produtos": [],
    }


def top_produtos_potencial_cliente(
    df: pd.DataFrame | None,
    cliente: str,
    modo_periodo: str = "fechados",
) -> dict:
    """Nos MESES_PICO_POTENCIAL meses de maior receita do cliente, dentro da
    mesma janela de JANELA_POTENCIAL_MESES usada em `_potencial_compra`, os
    produtos que mais venderam pra ele — o "porquê" por trás do número de
    potencial de compra daquele cliente.

    Recebe o df ORIGINAL (não o `dados` já preparado por `_preparar`, que
    descarta a coluna `descricao` por não precisar dela no resto do painel).
    """
    vazio = _top_produtos_potencial_vazio(cliente)
    if df is None or df.empty:
        return vazio
    faltantes = sorted({"Cliente", "Receita", "Periodo_Mensal", "descricao"} - set(df.columns))
    if faltantes:
        return vazio

    alvo = _normalizar_cliente(pd.Series([cliente])).iloc[0]
    colunas = [c for c in ("Cliente", "Receita", "QTD", "Periodo_Mensal", "descricao") if c in df.columns]
    base = df.loc[:, colunas].copy()
    base["Cliente"] = _normalizar_cliente(base["Cliente"])
    base["_periodo"] = converter_periodo(base)
    base = base.dropna(subset=["_periodo"])
    if base.empty:
        return vazio

    modo_periodo = modo_periodo_valido(modo_periodo)
    referencia = referencia_efetiva(inicio_mes(base["_periodo"].max()), modo_periodo == "fechados")

    recorte_cliente = base.loc[base["Cliente"] == alvo]
    if recorte_cliente.empty:
        return vazio

    meses_janela = set(_meses_ate(referencia, JANELA_POTENCIAL_MESES))
    recorte_janela = recorte_cliente.loc[recorte_cliente["_periodo"].isin(meses_janela)].copy()
    if recorte_janela.empty:
        return vazio

    recorte_janela["Receita"] = pd.to_numeric(recorte_janela["Receita"], errors="coerce").fillna(0.0)
    if "QTD" in recorte_janela.columns:
        recorte_janela["QTD"] = pd.to_numeric(recorte_janela["QTD"], errors="coerce").fillna(0.0)
    else:
        recorte_janela["QTD"] = 0.0

    receita_por_mes = recorte_janela.groupby("_periodo")["Receita"].sum().sort_values(ascending=False)
    top_meses = receita_por_mes.head(MESES_PICO_POTENCIAL)
    receita_total = float(top_meses.sum())
    if top_meses.empty or receita_total <= 0:
        return vazio

    recorte_pico = recorte_janela.loc[recorte_janela["_periodo"].isin(top_meses.index)].copy()
    recorte_pico["descricao"] = recorte_pico["descricao"].fillna("").astype(str).str.strip()
    recorte_pico = recorte_pico.loc[recorte_pico["descricao"] != ""]

    produtos: list[dict] = []
    if not recorte_pico.empty:
        por_produto = (
            recorte_pico.groupby("descricao")
            .agg(receita=("Receita", "sum"), qtd=("QTD", "sum"))
            .sort_values("receita", ascending=False)
            .head(LIMITE_TOP_PRODUTOS_POTENCIAL)
        )
        produtos = [
            {
                "descricao": str(nome),
                "receita": round(float(linha.receita), 2),
                "qtd": round(float(linha.qtd), 2),
                "participacao": round(float(linha.receita) / receita_total * 100, 2),
            }
            for nome, linha in por_produto.iterrows()
        ]

    meses_rotulos = [rotulo_periodo(periodo) for periodo in sorted(top_meses.index)]

    return {
        "disponivel": True,
        "cliente": cliente,
        "meses": meses_rotulos,
        "receita_total": round(receita_total, 2),
        "potencial": round(receita_total / len(top_meses), 2),
        "produtos": produtos,
    }


def montar_painel_clientes(
    df: pd.DataFrame | None,
    tags: dict | None = None,
    catalogo: list | None = None,
    cortes=None,
    clientes_balcao=None,
    modo_periodo: str = "fechados",
) -> dict:
    """Visão geral da carteira: KPIs, curva ABC, movimento mensal, top e tags."""
    modo_periodo = modo_periodo_valido(modo_periodo)
    usar_mes_fechado = modo_periodo == "fechados"
    try:
        dados, referencia = _preparar(df)
    except ErroPainelClientes as exc:
        return _resposta_vazia(str(exc))

    dados, balcao_excluidos = _sem_balcao(dados, clientes_balcao)
    if dados.empty:
        return _resposta_vazia("Todos os clientes da base estão marcados como balcão.")
    referencia = inicio_mes(dados["_periodo"].max())
    referencia = referencia_efetiva(referencia, usar_mes_fechado)

    primeiro_mes_base = inicio_mes(dados["_periodo"].min())
    historico = [
        mes for mes in _meses_ate(deslocar_mes(referencia, -1), MESES_HISTORICO)
        if mes >= primeiro_mes_base
    ]
    divisor = max(len(historico), 1)

    atual = dados.loc[dados["_periodo"] == referencia]
    hist = dados.loc[dados["_periodo"].isin(historico)]
    dia_corte = None
    if modo_periodo == "mesmo_periodo":
        dia_corte = dia_corte_mes_aberto(atual.get(COLUNA_DATA_DIARIA))
        hist = filtrar_ate_o_dia(hist, dia_corte)
    receita_atual = round(float(atual["Receita"].sum()), 2)
    receita_media = round(float(hist["Receita"].sum()) / divisor, 2)
    clientes_ativos = int(atual["Cliente"].nunique())
    clientes_media = (
        float(hist.groupby("_periodo")["Cliente"].nunique().sum()) / divisor
        if not hist.empty else 0.0
    )
    ticket_medio = receita_atual / clientes_ativos if clientes_ativos else 0.0
    ticket_medio_media = receita_media / clientes_media if clientes_media else 0.0

    movimento, eventos = _movimento_da_carteira(dados, referencia)
    ultimo = movimento[-1] if movimento else {
        "novos": 0, "recuperados": 0, "perdidos": 0, "saldo": 0,
    }
    concentracao, receita_por_cliente = _curva_abc(dados, referencia, _cortes_validos(cortes))
    score_migracao = _score_migracao(dados, referencia, _cortes_validos(cortes))
    potencial_compra = _potencial_compra(dados, referencia, _cortes_validos(cortes))

    return {
        "disponivel": True,
        "mensagem": None,
        "periodo_atual": referencia.strftime("%Y-%m"),
        "rotulo_periodo": rotulo_periodo(referencia),
        "meses_media": len(historico),
        "periodo_media_inicio": historico[0].strftime("%Y-%m") if historico else None,
        "periodo_media_fim": historico[-1].strftime("%Y-%m") if historico else None,
        "janela_inatividade_meses": JANELA_INATIVIDADE_MESES,
        "janela_abc_meses": JANELA_ABC_MESES,
        "balcao_excluidos": balcao_excluidos,
        "resumo": {
            "clientes_ativos": clientes_ativos,
            "clientes_media": round(clientes_media, 1),
            "variacao_clientes": _arredondar(variacao(clientes_ativos, clientes_media)),
            "receita_atual": receita_atual,
            "receita_media": receita_media,
            "variacao_receita": _arredondar(variacao(receita_atual, receita_media)),
            "ticket_medio": round(ticket_medio, 2),
            "ticket_medio_media": round(ticket_medio_media, 2),
            "variacao_ticket": _arredondar(variacao(ticket_medio, ticket_medio_media)),
            "novos": ultimo["novos"],
            "recuperados": ultimo["recuperados"],
            "perdidos": ultimo["perdidos"],
            "saldo": ultimo["saldo"],
        },
        "concentracao": concentracao,
        "movimento": movimento,
        "eventos": {
            "novos": _lista_eventos(dados, eventos["novos"], referencia, False),
            "recuperados": _lista_eventos(dados, eventos["recuperados"], referencia, False),
            "perdidos": _lista_eventos(dados, eventos["perdidos"], referencia, True),
        },
        "top_clientes": _top_clientes(dados, referencia, historico, dia_corte),
        "tags": _resumo_por_tag(
            tags, catalogo, receita_por_cliente, float(concentracao["receita"]),
        ),
        "score_migracao": score_migracao,
        "potencial_compra": potencial_compra,
    }
