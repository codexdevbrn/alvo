"""Painel de diagnóstico: tensão do período, cascata ano a ano e tornado."""

import pandas as pd

from painel_diagnostico import montar_painel_diagnostico


def _linha(periodo: str, produto: str, receita: float, cliente: str = "Cliente A", *, qtd: float = 1) -> dict:
    return {
        "Cliente": cliente,
        "descricao": produto,
        "Periodo_Mensal": periodo,
        "Receita": receita,
        "QTD": qtd,
    }


def _base() -> pd.DataFrame:
    """13 meses: ago/25 como base do ano anterior, jul e ago/26 como o par recente.

    Lubrificante cai (−400 no mês, −300 no ano) e Bateria sobe (+150 no mês),
    para que cascata e tornado tenham um lado de cada.
    """
    linhas = [
        _linha("2025-08", "Lubrificante", 1000),
        _linha("2025-08", "Bateria", 200),
    ]
    for mes in ("2025-09", "2025-10", "2025-11", "2025-12",
                "2026-01", "2026-02", "2026-03", "2026-04", "2026-05", "2026-06"):
        linhas.append(_linha(mes, "Lubrificante", 900))
    linhas += [
        _linha("2026-07", "Lubrificante", 1100),
        _linha("2026-07", "Bateria", 100),
        _linha("2026-08", "Lubrificante", 700),
        _linha("2026-08", "Bateria", 250),
    ]
    return pd.DataFrame(linhas)


def test_tensao_compara_com_mes_anterior_e_com_o_ano_anterior():
    painel = montar_painel_diagnostico(_base(), modo_periodo="completo")
    tensao = painel["tensao"]

    assert painel["disponivel"] is True
    assert painel["periodo_atual"] == "2026-08"
    assert tensao["receita_periodo"] == 950.0          # 700 + 250
    assert tensao["receita_anterior"] == 1200.0        # jul/26: 1100 + 100
    assert tensao["variacao_pct"] == -20.83
    assert tensao["delta_receita"] == -250.0
    assert tensao["receita_ano_anterior"] == 1200.0    # ago/25: 1000 + 200
    assert tensao["rotulo_anterior"] == "jul/26"
    assert tensao["rotulo_ano_anterior"] == "ago/25"


def test_tensao_mede_concentracao_da_queda_entre_produtos():
    tensao = montar_painel_diagnostico(_base(), modo_periodo="completo")["tensao"]

    # Só Lubrificante caiu (−400); Bateria subiu, então não entra na queda.
    assert tensao["produtos_em_queda"] == 1
    assert tensao["concentracao_queda_pct"] == 100.0


def test_cascata_sai_do_ano_anterior_e_fecha_no_periodo_atual():
    cascata = montar_painel_diagnostico(_base(), modo_periodo="completo")["cascata"]
    passos = cascata["passos"]

    assert passos[0]["tipo"] == "inicio" and passos[0]["rotulo"] == "ago/25"
    assert passos[0]["delta"] == 1200.0
    assert passos[-1]["tipo"] == "fim" and passos[-1]["rotulo"] == "ago/26"
    assert passos[-1]["delta"] == 950.0

    # Os degraus do meio somam exatamente a diferença entre as duas pontas.
    meio = [p for p in passos if p["tipo"] in ("ganho", "perda")]
    assert round(sum(p["delta"] for p in meio), 2) == -250.0
    # Geometria da barra flutuante: a base é sempre o menor extremo do degrau.
    perda = next(p for p in meio if p["tipo"] == "perda")
    assert perda["base"] == perda["acumulado"]
    assert perda["altura"] == abs(perda["delta"])


def test_tornado_ordena_por_impacto_em_reais():
    tornado = montar_painel_diagnostico(_base(), modo_periodo="completo")["tornado"]

    assert [linha["descricao"] for linha in tornado] == ["Bateria", "Lubrificante"]
    assert tornado[0]["delta_receita"] == 150.0     # 250 - 100
    assert tornado[-1]["delta_receita"] == -400.0   # 700 - 1100
    assert tornado[-1]["variacao_pct"] == -36.36


def test_base_sem_colunas_responde_indisponivel():
    painel = montar_painel_diagnostico(_base().drop(columns=["descricao"]))

    assert painel["disponivel"] is False
    assert "descricao" in painel["mensagem"]
    assert painel["cascata"] == {"passos": [], "cobertura_pct": None}


def test_base_vazia_nao_quebra():
    painel = montar_painel_diagnostico(pd.DataFrame())

    assert painel["disponivel"] is False
    assert painel["tornado"] == []


def _base_fluxo() -> pd.DataFrame:
    """Dois trimestres: mar-mai/26 contra jun-ago/26.

    ANA domina o trimestre anterior e despenca; BRUNO faz o caminho inverso;
    CARLA some e DUDA aparece — os dois últimos existem para separar "mudou de
    faixa" de "entrou/saiu da carteira".
    """
    linhas = []
    for mes in ("2026-03", "2026-04", "2026-05"):
        linhas += [_linha(mes, "Lubrificante", 1000, "ANA"),
                   _linha(mes, "Lubrificante", 100, "BRUNO"),
                   _linha(mes, "Bateria", 50, "CARLA")]
    for mes in ("2026-06", "2026-07", "2026-08"):
        linhas += [_linha(mes, "Lubrificante", 100, "ANA"),
                   _linha(mes, "Lubrificante", 1000, "BRUNO"),
                   _linha(mes, "Bateria", 50, "DUDA")]
    return pd.DataFrame(linhas)


def test_fluxo_faixas_troca_de_grupo_entre_trimestres():
    fluxo = montar_painel_diagnostico(_base_fluxo(), modo_periodo="completo")["fluxo_faixas"]

    assert fluxo["disponivel"] is True
    assert fluxo["rotulo_anterior"] == "mar/26–mai/26"
    assert fluxo["rotulo_atual"] == "jun/26–ago/26"

    por_par = {(f["de"], f["para"]): f for f in fluxo["fluxos"]}
    # BRUNO sobe (100 -> 1000/mês) e ANA desce; o passo carrega o sinal, porque
    # a ordem das faixas não é alfabética ("Demais" é a última, não a quarta).
    assert por_par[("Grupo 2", "Grupo 1")]["clientes"] == 1
    assert por_par[("Grupo 2", "Grupo 1")]["passo"] == 1
    assert por_par[("Grupo 2", "Grupo 1")]["receita"] == 3000.0
    assert por_par[("Grupo 1", "Grupo 2")]["passo"] == -1


def test_fluxo_faixas_separa_migracao_de_entrada_e_saida():
    resumo = montar_painel_diagnostico(_base_fluxo(), modo_periodo="completo")["fluxo_faixas"]["resumo"]

    assert resumo["subiram"] == 1 and resumo["desceram"] == 1
    # CARLA e DUDA não viram fluxo: só quem comprou nos dois lados migra.
    assert resumo["entraram"] == 1 and resumo["sairam"] == 1


def _base_streak() -> pd.DataFrame:
    """Lubrificante cai três meses seguidos; Bateria só no último; Pneu oscila;
    Filtro sobe três meses seguidos (espelho do Lubrificante, para testar a
    pílula "maior ganho")."""
    meses = ("2026-03", "2026-04", "2026-05", "2026-06", "2026-07", "2026-08")
    series = {
        "Lubrificante": [1000, 1000, 1000, 900, 700, 400],
        "Bateria": [500, 500, 500, 500, 500, 300],
        "Pneu": [300, 200, 300, 200, 300, 200],
        "Filtro": [200, 200, 200, 240, 300, 400],
    }
    return pd.DataFrame([
        _linha(mes, produto, valores[i])
        for produto, valores in series.items()
        for i, mes in enumerate(meses)
    ])


def test_streak_perda_traz_so_quem_cai_de_forma_consecutiva_ate_agora():
    streak = montar_painel_diagnostico(_base_streak(), modo_periodo="completo")["streak"]

    assert streak["periodos"][-1] == "ago/26"
    # Bateria caiu uma vez só e Pneu oscila: nenhum dos dois é queda consecutiva.
    assert [produto["descricao"] for produto in streak["perda"]] == ["Lubrificante"]

    lubrificante = streak["perda"][0]
    assert lubrificante["periodos_consecutivos"] == 3
    # Perda medida na janela da própria sequência: 1000 (antes da 1ª queda) - 400.
    assert lubrificante["valor"] == 600.0
    assert [celula["variacao_pct"] for celula in lubrificante["celulas"][-3:]] == [-10.0, -22.22, -42.86]


def test_streak_ganho_traz_so_quem_sobe_de_forma_consecutiva_ate_agora():
    streak = montar_painel_diagnostico(_base_streak(), modo_periodo="completo")["streak"]

    # Só Filtro sobe 3 meses seguidos; os outros três não têm alta consecutiva.
    assert [produto["descricao"] for produto in streak["ganho"]] == ["Filtro"]

    filtro = streak["ganho"][0]
    assert filtro["periodos_consecutivos"] == 3
    # Ganho medido na janela da própria sequência: 400 (ago) - 200 (antes da 1ª alta).
    assert filtro["valor"] == 200.0
    assert filtro["receita_atual"] == 400.0


def test_streak_receita_ranqueia_por_participacao_sem_olhar_tendencia():
    streak = montar_painel_diagnostico(_base_streak(), modo_periodo="completo")["streak"]

    # ago/26: Lubrificante 400, Filtro 400, Bateria 300, Pneu 200 — total 1300.
    nomes = [produto["descricao"] for produto in streak["receita"]]
    assert nomes[0] in ("Lubrificante", "Filtro")  # empate técnico em receita_atual
    assert set(nomes) == {"Lubrificante", "Filtro", "Bateria", "Pneu"}

    bateria = next(produto for produto in streak["receita"] if produto["descricao"] == "Bateria")
    assert bateria["valor"] == 300.0
    assert bateria["participacao_pct"] == round(300 / 1300 * 100, 2)


def _base_risco() -> pd.DataFrame:
    """Dois meses (jul/26, ago/26): ANA cai em receita e quantidade no mesmo
    produto (Lubrificante), CARLA para de comprar Pneu. BRUNO fica estável e
    DUDA cresce — nenhum dos dois deve entrar em nenhum dos três blocos,
    provando que o corte é por quem caiu, não por todo mundo."""
    linhas = [
        _linha("2026-07", "Lubrificante", 1000, "ANA", qtd=10),
        _linha("2026-07", "Bateria", 200, "ANA", qtd=4),
        _linha("2026-07", "Lubrificante", 500, "BRUNO", qtd=5),
        _linha("2026-07", "Pneu", 300, "CARLA", qtd=3),
        _linha("2026-07", "Lubrificante", 100, "DUDA", qtd=2),
        _linha("2026-08", "Lubrificante", 400, "ANA", qtd=4),
        _linha("2026-08", "Bateria", 200, "ANA", qtd=4),
        _linha("2026-08", "Lubrificante", 500, "BRUNO", qtd=5),
        _linha("2026-08", "Lubrificante", 300, "DUDA", qtd=3),
        # CARLA não aparece em ago: parou de comprar.
    ]
    return pd.DataFrame(linhas)


def test_risco_clientes_traz_quem_caiu_ordenado_por_perda_em_reais():
    risco = montar_painel_diagnostico(_base_risco(), modo_periodo="completo")["risco"]

    assert risco["disponivel"] is True
    nomes = [cliente["cliente"] for cliente in risco["clientes"]]
    assert nomes == ["ANA", "CARLA"]  # ordenado por perda em R$, não por %

    ana = risco["clientes"][0]
    assert ana["perda_rs"] == 600.0
    assert ana["variacao_pct"] == -50.0
    assert ana["parou_de_comprar"] is False

    carla = risco["clientes"][1]
    assert carla["perda_rs"] == 300.0
    assert carla["variacao_pct"] == -100.0
    assert carla["parou_de_comprar"] is True


def test_queda_quantidade_ordena_pela_maior_queda_percentual_e_aponta_produto_critico():
    queda = montar_painel_diagnostico(_base_risco(), modo_periodo="completo")["queda_quantidade"]

    assert queda["disponivel"] is True
    nomes = [cliente["cliente"] for cliente in queda["clientes"]]
    assert nomes == ["CARLA", "ANA"]  # -100% de CARLA é queda maior que a de ANA

    ana = next(cliente for cliente in queda["clientes"] if cliente["cliente"] == "ANA")
    assert ana["qtd_anterior"] == 14.0 and ana["qtd_atual"] == 8.0
    # Bateria não caiu (4->4); só o Lubrificante explica a queda de ANA.
    assert ana["produto_critico"] == "Lubrificante"


def test_matriz_erosao_cruza_cliente_e_produto_que_causou_a_queda():
    matriz = montar_painel_diagnostico(_base_risco(), modo_periodo="completo")["matriz_erosao"]

    assert matriz["disponivel"] is True
    assert matriz["produtos"] == ["Lubrificante", "Pneu"]  # ranqueado por R$ perdido

    por_cliente = {cliente["cliente"]: cliente for cliente in matriz["clientes"]}
    celulas_ana = {celula["produto"]: celula["perda_rs"] for celula in por_cliente["ANA"]["celulas"]}
    assert celulas_ana["Lubrificante"] == 600.0
    assert celulas_ana["Pneu"] is None  # ANA nunca comprou Pneu

    celulas_carla = {celula["produto"]: celula["perda_rs"] for celula in por_cliente["CARLA"]["celulas"]}
    assert celulas_carla["Pneu"] == 300.0
    assert celulas_carla["Lubrificante"] is None


def _base_margem_giro() -> pd.DataFrame:
    """Dois produtos, jul/ago-2026: Lubrificante (código A) com giro normal,
    Bateria (código B) sem venda nenhuma no `_vendas_margem_giro`."""
    linhas = [
        {"Cliente": "Cliente A", "descricao": "Lubrificante", "Código Interno": "A",
         "Periodo_Mensal": "2026-07", "Receita": 900, "CMV": 300, "QTD": 10},
        {"Cliente": "Cliente A", "descricao": "Lubrificante", "Código Interno": "A",
         "Periodo_Mensal": "2026-08", "Receita": 900, "CMV": 300, "QTD": 10},
        {"Cliente": "Cliente B", "descricao": "Bateria", "Código Interno": "B",
         "Periodo_Mensal": "2026-07", "Receita": 200, "CMV": 160, "QTD": 4},
        {"Cliente": "Cliente B", "descricao": "Bateria", "Código Interno": "B",
         "Periodo_Mensal": "2026-08", "Receita": 250, "CMV": 200, "QTD": 5},
    ]
    return pd.DataFrame(linhas)


def _estoque_margem_giro() -> pd.DataFrame:
    return pd.DataFrame([
        {"Loja": "Matriz", "NOME_FABRICANTE": "Marca A", "descricao": "Lubrificante",
         "CODIGO_INTERNO_PRODUTO": "A", "CODIGO_REFERENCIA_PRODUTO": "REF-A",
         "Qtd_estoque": 60, "Preço_médio_de_venda": 20, "Preço_médio_cmv": 5, "Último_custo": 0},
        {"Loja": "Matriz", "NOME_FABRICANTE": "Marca B", "descricao": "Bateria",
         "CODIGO_INTERNO_PRODUTO": "B", "CODIGO_REFERENCIA_PRODUTO": "REF-B",
         "Qtd_estoque": 300, "Preço_médio_de_venda": 30, "Preço_médio_cmv": 8, "Último_custo": 0},
    ])


def _vendas_margem_giro() -> pd.DataFrame:
    # Só o produto A vende nos últimos 6 meses; B fica sem giro nenhum.
    return pd.DataFrame([
        {"Nome_Loja": "Matriz", "CODIGO_INTERNO_PRODUTO": "A", "Ano": 2026, "Mês": mes, "QTD": 10}
        for mes in range(1, 7)
    ])


def test_margem_giro_cruza_margem_do_movimento_com_cobertura_do_estoque():
    painel = montar_painel_diagnostico(
        _base_margem_giro(), modo_periodo="completo",
        estoque=_estoque_margem_giro(), vendas=_vendas_margem_giro(),
    )
    margem_giro = painel["margem_giro"]
    assert margem_giro["disponivel"] is True

    produtos = {item["descricao"]: item for item in margem_giro["produtos"]}
    lubrificante = produtos["Lubrificante"]
    assert lubrificante["margem_pct"] == round((900 - 300) / 900 * 100, 2)
    assert lubrificante["valor_estoque"] == 60 * 5
    assert lubrificante["cobertura_meses"] == round(60 / 10, 2)
    assert lubrificante["status"] == "normal"

    bateria = produtos["Bateria"]
    assert bateria["margem_pct"] == round((250 - 200) / 250 * 100, 2)
    assert bateria["cobertura_meses"] is None
    assert bateria["status"] == "no_sales"  # sem venda em `_vendas_margem_giro`

    bullet = {item["status"]: item for item in margem_giro["bullet"]}
    assert bullet["normal"]["produtos"] == 1
    assert bullet["no_sales"]["produtos"] == 1
    assert bullet["no_sales"]["valor_estoque"] == 300 * 8


def test_margem_giro_indisponivel_sem_estoque():
    painel = montar_painel_diagnostico(_base_margem_giro(), modo_periodo="completo")
    assert painel["margem_giro"]["disponivel"] is False


def test_margem_giro_indisponivel_quando_base_nao_tem_cmv():
    painel = montar_painel_diagnostico(
        _base_risco(), modo_periodo="completo", estoque=_estoque_margem_giro(),
    )
    assert painel["margem_giro"]["disponivel"] is False
