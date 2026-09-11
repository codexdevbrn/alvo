"""Referência efetiva: recua para o mês fechado quando o mês corrente ainda
está em aberto (poucos dias de movimento não podem parecer queda)."""

from datetime import date

import pandas as pd

from periodo_mensal import inicio_mes, referencia_efetiva


def test_referencia_efetiva_recua_quando_mes_corrente_em_aberto():
    hoje = date(2026, 9, 10)
    referencia = inicio_mes(pd.Timestamp("2026-09-02"))
    resultado = referencia_efetiva(referencia, usar_mes_fechado=True, ref=hoje)
    assert resultado == inicio_mes(pd.Timestamp("2026-08-01"))


def test_referencia_efetiva_mantem_mes_ja_fechado():
    hoje = date(2026, 9, 10)
    referencia = inicio_mes(pd.Timestamp("2026-08-01"))
    resultado = referencia_efetiva(referencia, usar_mes_fechado=True, ref=hoje)
    assert resultado == referencia


def test_referencia_efetiva_ignora_quando_desligado():
    hoje = date(2026, 9, 10)
    referencia = inicio_mes(pd.Timestamp("2026-09-02"))
    resultado = referencia_efetiva(referencia, usar_mes_fechado=False, ref=hoje)
    assert resultado == referencia
