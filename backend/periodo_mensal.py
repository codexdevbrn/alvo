"""Helpers de período mensal compartilhados pelas análises da base.

Nasceu de `analise_vendedores.py`: `analise_clientes.py` precisa do mesmo
recorte (mês de referência = último `Periodo_Mensal` da base, comparado à média
dos N anteriores) e a mesma conversão de período tolerante a base sem
`Periodo_Mensal`. Duplicar essas seis funções faria as duas telas divergirem no
dia em que uma delas mudasse a régua.
"""

from __future__ import annotations

import math
from datetime import date
from typing import Any

import pandas as pd


COLUNA_PERIODO = "Periodo_Mensal"
COLUNA_DATA_DIARIA = "Data_Venda_Diaria"
MESES_ABREV = (
    "jan", "fev", "mar", "abr", "mai", "jun",
    "jul", "ago", "set", "out", "nov", "dez",
)
MODOS_PERIODO = ("fechados", "completo", "mesmo_periodo")


def numero(valor: Any) -> float:
    """Converte para float finito; qualquer coisa inválida vira 0.0."""
    try:
        convertido = float(valor)
    except (TypeError, ValueError):
        return 0.0
    return convertido if math.isfinite(convertido) else 0.0


def variacao(atual: float, base: float) -> float | None:
    """Variação percentual contra `base`. Base zero/negativa devolve None."""
    if not math.isfinite(base) or base <= 0:
        return None
    return (atual - base) / base * 100


def inicio_mes(valor: pd.Timestamp) -> pd.Timestamp:
    return valor.normalize().replace(day=1)


def deslocar_mes(inicio: pd.Timestamp, quantidade: int) -> pd.Timestamp:
    return (inicio + pd.DateOffset(months=quantidade)).normalize().replace(day=1)


def rotulo_periodo(inicio: pd.Timestamp) -> str:
    return f"{MESES_ABREV[inicio.month - 1]}/{str(inicio.year)[-2:]}"


def mes_atual_calendario(ref: date | None = None) -> pd.Timestamp:
    """Início do mês corrente do calendário real — não o último mês da base."""
    return inicio_mes(pd.Timestamp(ref or date.today()))


def referencia_efetiva(
    referencia_bruta: pd.Timestamp,
    usar_mes_fechado: bool,
    ref: date | None = None,
) -> pd.Timestamp:
    """Recua a referência um mês quando ela cair no mês corrente, ainda aberto.

    Sem isso, um mês com poucos dias de movimento (ex.: dia 2) compara contra a
    média de meses completos e aparece como queda — não é queda, é mês
    incompleto. `usar_mes_fechado=False` mantém o comportamento antigo (sempre
    o último mês presente na base, mesmo em aberto).
    """
    if not usar_mes_fechado:
        return referencia_bruta
    if referencia_bruta == mes_atual_calendario(ref):
        return deslocar_mes(referencia_bruta, -1)
    return referencia_bruta


def modo_periodo_valido(modo: Any) -> str:
    """Normaliza o modo do controle global "período dos cálculos".

    Qualquer valor desconhecido vira "fechados" (padrão mais conservador),
    em vez de rejeitar a requisição — a tela é quem oferece as 3 opções, então
    valor fora do enum só pode vir de um cliente desatualizado/manual.
    """
    texto = str(modo or "").strip()
    return texto if texto in MODOS_PERIODO else "fechados"


def dia_corte_mes_aberto(datas_diarias: pd.Series | None) -> int | None:
    """Último dia (1-31) com movimento na série de datas diárias passada.

    None sem dado diário utilizável — quem chama trata como "nada a cortar".
    """
    if datas_diarias is None:
        return None
    dias = pd.to_datetime(datas_diarias, errors="coerce").dropna()
    if dias.empty:
        return None
    return int(dias.dt.day.max())


def filtrar_ate_o_dia(frame: pd.DataFrame, dia_corte: int | None) -> pd.DataFrame:
    """Corta o histórico de comparação no mesmo dia do mês que a referência
    (parcial) já tem — modo "mesmo período".

    Sem isso, um mês corrente com poucos dias de movimento (ex.: dia 2)
    compara contra meses inteiros anteriores e sai sempre como queda: não é
    queda, é mês incompleto. Sem coluna de data diária ou sem corte a aplicar,
    devolve o frame como veio — o modo vira, na prática, "completo".
    """
    if dia_corte is None or COLUNA_DATA_DIARIA not in frame.columns:
        return frame
    dia = pd.to_datetime(frame[COLUNA_DATA_DIARIA], errors="coerce").dt.day
    return frame.loc[dia.isna() | (dia <= dia_corte)]


def converter_periodo(df: pd.DataFrame) -> pd.Series:
    """Série de timestamps no 1º dia do mês, de `Periodo_Mensal` ou `Data_Venda`."""
    if COLUNA_PERIODO in df.columns:
        textos = df[COLUNA_PERIODO].astype("string").str.strip()
        return pd.to_datetime(textos + "-01", format="%Y-%m-%d", errors="coerce")
    if "Data_Venda" in df.columns:
        return (
            pd.to_datetime(df["Data_Venda"], errors="coerce")
            .dt.to_period("M").dt.to_timestamp()
        )
    return pd.Series(pd.NaT, index=df.index, dtype="datetime64[ns]")
