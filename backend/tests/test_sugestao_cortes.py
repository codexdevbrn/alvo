"""Sugestão automática de cortes: o "máximo por grupo" precisa PREENCHER.

A versão anterior só sabia diminuir o corte inicial, então o máximo virava um
teto que quase nunca era atingido — e, quando um cliente sozinho pulava a faixa
inteira, o grupo seguinte saía vazio no relatório.
"""

import os
import sys

import pandas as pd

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import engine.analise_funil as af


def _base_clientes(receitas):
    return pd.DataFrame(
        {
            "Cliente": [f"Cliente {i:04d}" for i in range(len(receitas))],
            "Receita": list(receitas),
        }
    )


def test_preenche_ate_o_maximo_em_vez_de_parar_no_corte_inicial():
    # 100 clientes iguais: cada um vale 1% da receita, então os 30% iniciais
    # comportariam 30 clientes. Com máximo 20, cada grupo deve levar 20.
    df = _base_clientes([100.0] * 100)

    cortes, contagens = af.sugerir_cortes_grupos(
        df, cortes_iniciais=(30.0, 50.0, 60.0), max_por_grupo=20,
    )

    assert contagens[:3] == [20, 20, 20]
    assert cortes == sorted(cortes)
    assert contagens[-1] == 40


def test_cliente_dominante_nao_deixa_grupo_vazio():
    # O primeiro cliente sozinho passa dos 50%: com a régua antiga o Grupo 1
    # ficava com ele, o Grupo 2 nascia vazio e só o 3 enchia.
    df = _base_clientes([6000.0] + [10.0] * 400)

    _, contagens = af.sugerir_cortes_grupos(
        df, cortes_iniciais=(30.0, 50.0, 60.0), max_por_grupo=10,
    )

    assert all(quantidade > 0 for quantidade in contagens[:3])
    assert all(quantidade <= 10 for quantidade in contagens[:3])


def test_nenhum_grupo_passa_do_maximo():
    df = _base_clientes([1000.0 / (i + 1) for i in range(500)])

    for maximo in (5, 10, 20, 50):
        cortes, contagens = af.sugerir_cortes_grupos(
            df, cortes_iniciais=(30.0, 50.0, 60.0), max_por_grupo=maximo,
        )
        assert all(q <= maximo for q in contagens[:3]), (maximo, contagens)
        # Cortes precisam continuar estritamente crescentes: faixa invertida
        # geraria grupo negativo na classificação.
        assert cortes[0] < cortes[1] < cortes[2], (maximo, cortes)


def test_menos_entidades_que_o_maximo_nao_sobra_demais():
    df = _base_clientes([100.0] * 4)

    cortes, contagens = af.sugerir_cortes_grupos(
        df, cortes_iniciais=(30.0, 50.0, 60.0), max_por_grupo=20,
    )

    assert contagens[-1] == 0
    assert sum(contagens[:3]) == 4
    assert cortes[-1] == 100.0


def test_base_vazia_devolve_os_cortes_iniciais():
    df = _base_clientes([])

    cortes, contagens = af.sugerir_cortes_grupos(
        df, cortes_iniciais=(30.0, 50.0, 60.0), max_por_grupo=20,
    )

    assert cortes == [30.0, 50.0, 60.0]
    assert contagens == [0, 0, 0, 0]


def test_sugestao_de_produtos_usa_a_mesma_regua():
    df = pd.DataFrame(
        {
            "descricao": [f"Produto {i:03d}" for i in range(100)],
            "Receita": [100.0] * 100,
        }
    )

    corte, contagens = af.sugerir_corte_produtos(df, 90.0, max_por_grupo=20)

    assert contagens == [20, 80]
    assert corte == 20.0


def test_sugestao_de_produtos_com_base_sem_receita():
    df = pd.DataFrame({"descricao": ["Produto A"], "Receita": [0.0]})

    corte, contagens = af.sugerir_corte_produtos(df, 90.0, max_por_grupo=20)

    assert corte == 90.0
    assert contagens == [0, 0]
