"""Contrato da harmonização de nomes de cliente por sufixo de origem."""

import json

import pandas as pd

import harmonizar_clientes as hc


def _regra(**kwargs) -> hc.RegraClientes:
    base = {"unificar_por_sufixo": True, "sufixos": ("CM", "SA", "ERRO"), "mapa": {}}
    base.update(kwargs)
    return hc.RegraClientes(**base)


def _df(pares: list[tuple[str, str]]) -> pd.DataFrame:
    return pd.DataFrame(
        {"Loja": [loja for loja, _ in pares], "Cliente": [cli for _, cli in pares]}
    )


def test_unifica_variantes_que_convivem_na_mesma_loja():
    df = _df([
        ("Matriz", "JHONE TEIXEIRA COSTA (CM)"),
        ("Matriz", "JHONE TEIXEIRA COSTA (SA)"),
    ])

    hc.aplicar_em_cliente(df, _regra())

    assert df["Cliente"].tolist() == ["JHONE TEIXEIRA COSTA"] * 2


def test_nao_unifica_variantes_de_lojas_diferentes():
    # Mesmo nome com sufixos diferentes em lojas diferentes pode ser gente
    # diferente; somar receita seria pior do que deixar duplicado.
    df = _df([("Matriz", "MARIA SOUZA (CM)"), ("Filial", "MARIA SOUZA (SA)")])

    hc.aplicar_em_cliente(df, _regra())

    assert df["Cliente"].tolist() == ["MARIA SOUZA (CM)", "MARIA SOUZA (SA)"]


def test_variante_unica_mantem_o_sufixo():
    # Preserva as tags e exclusões já gravadas por nome.
    df = _df([("Matriz", "CONSUMIDOR ITABORAI (SA)")])

    hc.aplicar_em_cliente(df, _regra())

    assert df["Cliente"].tolist() == ["CONSUMIDOR ITABORAI (SA)"]


def test_nome_sem_sufixo_conta_como_variante():
    df = _df([("Matriz", "ADRIANO SOUZA"), ("Matriz", "ADRIANO SOUZA (SA)")])

    hc.aplicar_em_cliente(df, _regra())

    assert set(df["Cliente"]) == {"ADRIANO SOUZA"}


def test_remove_sufixos_encadeados_e_preserva_parenteses_que_nao_sao_sufixo():
    df = _df([
        ("Matriz", "OTONIEL REIS (ZOCA) (CM)"),
        ("Matriz", "OTONIEL REIS (ZOCA) (SA) (ERRO)"),
    ])

    hc.aplicar_em_cliente(df, _regra())

    assert set(df["Cliente"]) == {"OTONIEL REIS (ZOCA)"}


def test_nome_diferente_antes_do_sufixo_nao_e_unificado():
    df = _df([
        ("Matriz", "A.L LAGOAS COMERCIO (SA)"),
        ("Matriz", "A.L.LAGOAS COMERCIO (CM)"),
    ])

    hc.aplicar_em_cliente(df, _regra())

    assert df["Cliente"].nunique() == 2


def test_mapa_manual_vence_a_regra_automatica():
    df = _df([
        ("Matriz", "A.L LAGOAS COMERCIO (SA)"),
        ("Matriz", "A.L.LAGOAS COMERCIO (CM)"),
        ("Matriz", "JHONE TEIXEIRA COSTA (CM)"),
        ("Matriz", "JHONE TEIXEIRA COSTA (SA)"),
    ])
    regra = _regra(mapa={
        "A.L LAGOAS COMERCIO (SA)": "A.L.LAGOAS COMERCIO",
        "A.L.LAGOAS COMERCIO (CM)": "A.L.LAGOAS COMERCIO",
        # Redireciona também o canônico derivado pela regra automática.
        "JHONE TEIXEIRA COSTA": "JHONE T. COSTA",
    })

    hc.aplicar_em_cliente(df, regra)

    assert set(df["Cliente"]) == {"A.L.LAGOAS COMERCIO", "JHONE T. COSTA"}


def test_sem_arquivo_de_regra_nada_muda(tmp_path):
    assert hc.carregar_regra(tmp_path) is None
    assert hc.mtime_regra(tmp_path) == 0.0

    df = _df([("Matriz", "JHONE (CM)"), ("Matriz", "JHONE (SA)")])
    hc.aplicar_em_cliente(df, None)

    assert df["Cliente"].tolist() == ["JHONE (CM)", "JHONE (SA)"]


def test_arquivo_invalido_nao_derruba_a_carga(tmp_path):
    (tmp_path / hc.NOME_ARQUIVO_REGRA).write_text("{isso nao e json", encoding="utf-8")

    assert hc.carregar_regra(tmp_path) is None
    assert hc.mtime_regra(tmp_path) > 0.0


def test_le_regra_do_arquivo_da_pasta_de_trabalho(tmp_path):
    (tmp_path / hc.NOME_ARQUIVO_REGRA).write_text(
        json.dumps({
            "unificar_por_sufixo": True,
            "sufixos": ["CM", "SA"],
            "mapa": {"X (CM)": "X CANONICO"},
        }),
        encoding="utf-8",
    )

    regra = hc.carregar_regra(tmp_path)

    assert regra is not None
    assert regra.sufixos == ("CM", "SA")
    assert regra.mapa == {"X (CM)": "X CANONICO"}


def test_regra_desligada_so_aplica_o_mapa_manual(tmp_path):
    df = _df([("Matriz", "JHONE (CM)"), ("Matriz", "JHONE (SA)")])
    regra = _regra(unificar_por_sufixo=False, mapa={"JHONE (CM)": "JHONE"})

    hc.aplicar_em_cliente(df, regra)

    assert df["Cliente"].tolist() == ["JHONE", "JHONE (SA)"]


def test_base_sem_coluna_loja_trata_tudo_como_uma_loja():
    df = pd.DataFrame({"Cliente": ["JHONE (CM)", "JHONE (SA)"]})

    hc.aplicar_em_cliente(df, _regra())

    assert set(df["Cliente"]) == {"JHONE"}
