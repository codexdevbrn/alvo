"""
Harmoniza nomes de cliente de uma empresa: variantes que só diferem pelo sufixo
de origem — "(SA)", "(CM)", … — passam a contar como um cliente só.

Por que existe
--------------
A fonte de algumas empresas (alianca_itaborai é o caso original) grava o mesmo
cliente uma vez por origem, distinguindo pelo sufixo entre parênteses no fim do
nome: "JHONE TEIXEIRA COSTA (CM)" e "JHONE TEIXEIRA COSTA (SA)" são a mesma
pessoa, e apareciam como dois clientes no ABC, no concentrado e no Dashboard.
O sufixo NÃO é a loja: as duas variantes ocorrem dentro da mesma loja, então
filtrar por loja não resolvia.

Onde é aplicado
---------------
Na carga da base da empresa (`main._carregar_base_empresa_sem_trava`), antes do
cache — logo vale para tudo que lê a base: Dashboard, Analisador, Explorar e
exports. É o mesmo desenho do harm.xlsx de produto, só que para `Cliente`.

A regra é um arquivo por empresa
--------------------------------
`clientes_harm.json`, opcional, na pasta de TRABALHO da empresa:

    {
      "unificar_por_sufixo": true,
      "sufixos": ["CM", "CS", "CQ", "SA", "SS", "SM", "ERRO"],
      "mapa": {"NOME COMO VEM DA FONTE": "NOME CANONICO"}
    }

Sem o arquivo, nada muda — nenhuma empresa altera comportamento por causa deste
módulo. Arquivo ilegível também não quebra a carga: vira aviso no log e a base
segue com os nomes crus.

`unificar_por_sufixo` só unifica quando o nome antes do sufixo é IDÊNTICO e as
variantes convivem DENTRO DE UMA MESMA LOJA — duas lojas usando o mesmo nome com
sufixos diferentes podem ser dois clientes distintos, e somar receita de quem
não é a mesma pessoa é pior do que deixar duplicado. Outras consequências
propositais:

- nome com sufixo único fica como está. Isso mantém válidas as tags e exclusões
  já gravadas por nome (ex.: "CONSUMIDOR ITABORAI (SA)" continua com esse nome)
  e limita o efeito da regra a quem de fato duplica;
- diferença de pontuação antes do sufixo ("A.L LAGOAS" vs "A.L.LAGOAS") não é
  unificada automaticamente — juntar nomes só parecidos é decisão de negócio,
  não de regex. Esses casos vão no `mapa`.

`mapa` é a exceção manual: aplicado por último e sempre, inclusive sobre o
resultado da regra automática.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping, Optional

import pandas as pd

logger = logging.getLogger(__name__)

NOME_ARQUIVO_REGRA = "clientes_harm.json"

#: Sufixos de origem observados na fonte. Só valem os listados no arquivo da
#: empresa; esta tupla é apenas o padrão quando a chave `sufixos` está ausente.
SUFIXOS_PADRAO: tuple[str, ...] = ("CM", "CS", "CQ", "SA", "SS", "SM", "ERRO")


@dataclass(frozen=True)
class RegraClientes:
    """Conteúdo já validado de um `clientes_harm.json`."""

    unificar_por_sufixo: bool = True
    sufixos: tuple[str, ...] = SUFIXOS_PADRAO
    mapa: dict[str, str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.mapa is None:
            object.__setattr__(self, "mapa", {})

    @property
    def vazia(self) -> bool:
        return not self.mapa and not (self.unificar_por_sufixo and self.sufixos)


def caminho_regra(pasta_trabalho: str | Path) -> Path:
    return Path(pasta_trabalho) / NOME_ARQUIVO_REGRA


def mtime_regra(pasta_trabalho: str | Path) -> float:
    """mtime do arquivo de regra, ou 0.0 se não existir.

    Entra na chave de cache da base e no frescor do summary do Dashboard: sem
    isso, editar a regra não teria efeito até a fonte mudar."""
    caminho = caminho_regra(pasta_trabalho)
    try:
        return os.path.getmtime(caminho)
    except OSError:
        return 0.0


def carregar_regra(pasta_trabalho: str | Path) -> Optional[RegraClientes]:
    """Lê o `clientes_harm.json` da pasta de trabalho. None se não houver regra.

    Arquivo ausente, ilegível ou malformado nunca derruba a carga da base — a
    empresa simplesmente fica sem harmonização de cliente.
    """
    caminho = caminho_regra(pasta_trabalho)
    if not caminho.is_file():
        return None
    try:
        bruto = json.loads(caminho.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.warning("Regra de clientes ignorada (%s): %s", caminho, exc)
        return None
    if not isinstance(bruto, dict):
        logger.warning("Regra de clientes ignorada (%s): raiz não é objeto.", caminho)
        return None

    sufixos_bruto = bruto.get("sufixos")
    if isinstance(sufixos_bruto, list):
        sufixos = tuple(
            texto for texto in (str(s).strip() for s in sufixos_bruto) if texto
        )
    else:
        sufixos = SUFIXOS_PADRAO

    mapa_bruto = bruto.get("mapa")
    mapa: dict[str, str] = {}
    if isinstance(mapa_bruto, dict):
        for origem, destino in mapa_bruto.items():
            de = str(origem).strip()
            para = str(destino).strip()
            if de and para and de != para:
                mapa[de] = para

    regra = RegraClientes(
        unificar_por_sufixo=bool(bruto.get("unificar_por_sufixo", True)),
        sufixos=sufixos,
        mapa=mapa,
    )
    return None if regra.vazia else regra


def _regex_sufixos(sufixos: Iterable[str]) -> Optional[re.Pattern[str]]:
    alternativas = [re.escape(s) for s in sufixos if s]
    if not alternativas:
        return None
    return re.compile(r"\s*\((?:" + "|".join(alternativas) + r")\)\s*$", re.IGNORECASE)


def nome_sem_sufixo(nome: str, rx: re.Pattern[str]) -> str:
    """Remove os sufixos de origem do fim do nome, quantos houver.

    Repete porque a fonte já produziu nome com dois — "FULANO (SA) (ERRO)".
    Parênteses que não estão na lista de sufixos são parte do nome e ficam:
    "OTONIEL REIS GOULART (ZOCA) (CM)" -> "OTONIEL REIS GOULART (ZOCA)".
    """
    atual = nome.strip()
    while True:
        reduzido = rx.sub("", atual).strip()
        if reduzido == atual or not reduzido:
            return atual
        atual = reduzido


def montar_mapa(
    nomes_por_loja: Mapping[str, Iterable[str]],
    regra: RegraClientes,
) -> dict[str, str]:
    """Constrói {nome_da_fonte: nome_canônico} a partir dos nomes de cada loja.

    Só entram nomes que de fato mudam. A comparação entre variantes ignora
    caixa (a fonte é toda em maiúsculas, mas nada garante isso), e o canônico é
    o nome sem sufixo da primeira variante em ordem alfabética — determinístico,
    para o nome do cliente não oscilar entre execuções.

    A unificação exige que as variantes convivam DENTRO DE UMA MESMA LOJA. Duas
    lojas usando o mesmo nome com sufixos diferentes podem ser dois clientes
    distintos, e juntá-los somaria receita de quem não é a mesma pessoa; quando
    é a mesma, o par vai no `mapa` manual. Confirmada a convivência em alguma
    loja, a troca vale para a base inteira — o nome canônico do cliente não pode
    depender do filtro de loja em uso.
    """
    mapa: dict[str, str] = {}

    rx = _regex_sufixos(regra.sufixos) if regra.unificar_por_sufixo else None
    if rx is not None:
        # Chave (nome sem sufixo, em caixa neutra) -> variantes que dividem loja
        # com pelo menos uma outra variante da mesma chave.
        convivem: dict[str, set[str]] = {}
        for nomes in nomes_por_loja.values():
            da_loja: dict[str, set[str]] = {}
            for nome in nomes:
                limpo = str(nome).strip()
                if limpo:
                    da_loja.setdefault(nome_sem_sufixo(limpo, rx).casefold(), set()).add(limpo)
            for chave, variantes in da_loja.items():
                if len(variantes) > 1:
                    convivem.setdefault(chave, set()).update(variantes)

        for variantes in convivem.values():
            grupo = sorted(variantes)
            canonico = nome_sem_sufixo(grupo[0], rx)
            for nome in grupo:
                if nome != canonico:
                    mapa[nome] = canonico

    # Exceções manuais por último: valem sobre o resultado da regra automática,
    # tanto como origem quanto como destino (o canônico derivado pode ser a
    # origem de um par manual).
    if regra.mapa:
        for origem, destino in mapa.items():
            final = regra.mapa.get(destino)
            if final and final != origem:
                mapa[origem] = final
        for origem, destino in regra.mapa.items():
            if origem != destino:
                mapa[origem] = destino

    return mapa


def aplicar_em_cliente(df: pd.DataFrame, regra: Optional[RegraClientes]) -> pd.DataFrame:
    """Reescreve a coluna `Cliente` conforme a regra. Devolve o mesmo df.

    Sem regra, sem coluna ou sem nada a trocar, é no-op. Chamado uma vez por
    carga de base (o resultado vai para o cache), não por request.
    """
    if regra is None or df is None or df.empty or "Cliente" not in df.columns:
        return df

    clientes = df["Cliente"].astype("string").fillna("").str.strip()
    if "Loja" in df.columns:
        lojas = df["Loja"].astype("string").fillna("").str.strip()
        nomes_por_loja = {
            str(loja): grupo.unique().tolist()
            for loja, grupo in clientes.groupby(lojas, dropna=False)
        }
    else:
        # Base sem coluna Loja (Excel padrão): tudo é uma loja só.
        nomes_por_loja = {"": clientes.unique().tolist()}
    mapa = montar_mapa(nomes_por_loja, regra)
    if not mapa:
        return df

    convertidos = clientes.map(mapa)
    df["Cliente"] = convertidos.where(convertidos.notna(), clientes)
    logger.info("Clientes harmonizados: %d nome(s) unificado(s).", len(mapa))
    return df
