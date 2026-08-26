"""Painel PDF individual para clientes monitorados.

O relatório replica o escopo do painel comercial de referência: compara o mês
mais recente com os meses anteriores, resume receita/itens, mostra evolução,
lojas e produtos que subiram, mantiveram ou caíram. A dimensão de vendedor fica
deliberadamente fora enquanto a base não oferecer esse campo.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import pandas as pd


COLUNA_PERIODO = "Periodo_Mensal"
COLUNA_PERIODO_INTERNA = "_Periodo_Painel"
MESES_PT = (
    "janeiro", "fevereiro", "março", "abril", "maio", "junho",
    "julho", "agosto", "setembro", "outubro", "novembro", "dezembro",
)
MESES_ABREV = (
    "jan", "fev", "mar", "abr", "mai", "jun",
    "jul", "ago", "set", "out", "nov", "dez",
)


class ErroPainelCliente(ValueError):
    """Erro de dados que pode ser mostrado diretamente ao usuário."""


def _inicio_mes(valor: pd.Timestamp) -> pd.Timestamp:
    return valor.normalize().replace(day=1)


def _deslocar_mes(inicio: pd.Timestamp, quantidade: int) -> pd.Timestamp:
    return (inicio + pd.DateOffset(months=quantidade)).normalize().replace(day=1)


def _variacao(atual: float, base: float) -> float | None:
    if not math.isfinite(base) or base <= 0:
        return None
    return (atual - base) / base * 100


def _numero(valor: Any) -> float:
    try:
        numero = float(valor)
    except (TypeError, ValueError):
        return 0.0
    return numero if math.isfinite(numero) else 0.0


def _converter_periodo_mensal(df: pd.DataFrame) -> pd.Series:
    """Normaliza o período mensal canônico sem exigir uma data de venda diária."""
    if COLUNA_PERIODO in df.columns:
        textos = df[COLUNA_PERIODO].astype("string").str.strip()
        return pd.to_datetime(textos + "-01", format="%Y-%m-%d", errors="coerce")
    if "Data_Venda" in df.columns:
        return (
            pd.to_datetime(df["Data_Venda"], errors="coerce")
            .dt.to_period("M").dt.to_timestamp()
        )
    return pd.Series(pd.NaT, index=df.index, dtype="datetime64[ns]")


def _produto_item(
    produto: str,
    receita_atual: float,
    receita_media: float,
    qtd_atual: float,
) -> dict:
    return {
        "produto": produto,
        "receita_atual": round(receita_atual, 2),
        "receita_media": round(receita_media, 2),
        "variacao": _variacao(receita_atual, receita_media),
        "qtd_atual": round(qtd_atual, 2),
        "diferenca": round(receita_atual - receita_media, 2),
    }


def montar_dados_painel_cliente(
    df: pd.DataFrame,
    cliente: str,
    *,
    data_referencia: Any = None,
    meses_historico: int = 10,
    top_n: int = 5,
) -> dict:
    """Calcula o painel por mês, sem depender de data diária.

    O período de referência vem da base inteira, não da última compra do cliente.
    Assim um cliente sem venda no mês mais recente aparece com zero e queda, em
    vez de o relatório recuar silenciosamente para sua última compra.
    """
    if df is None or df.empty:
        raise ErroPainelCliente("A base está vazia.")
    obrigatorias = {"Cliente", "Receita", "QTD", "descricao"}
    faltantes = sorted(obrigatorias - set(df.columns))
    if faltantes:
        raise ErroPainelCliente("Base sem colunas necessárias: " + ", ".join(faltantes))
    if COLUNA_PERIODO not in df.columns and "Data_Venda" not in df.columns:
        raise ErroPainelCliente("A base precisa informar o período mensal da venda.")

    dados = df.loc[:, [
        coluna for coluna in (
            "Cliente", "Receita", "QTD", "descricao", "Loja", COLUNA_PERIODO,
            "Data_Venda",
        ) if coluna in df.columns
    ]].copy()
    dados[COLUNA_PERIODO_INTERNA] = _converter_periodo_mensal(dados)
    cobertura = float(dados[COLUNA_PERIODO_INTERNA].notna().mean() * 100)
    if cobertura < 95:
        raise ErroPainelCliente(
            f"Período mensal incompleto: {cobertura:.1f}% das linhas possuem mês válido."
        )
    dados = dados.dropna(subset=[COLUNA_PERIODO_INTERNA])
    dados["Cliente"] = dados["Cliente"].fillna("").astype(str).str.strip()
    dados["Receita"] = pd.to_numeric(dados["Receita"], errors="coerce").fillna(0.0)
    dados["QTD"] = pd.to_numeric(dados["QTD"], errors="coerce").fillna(0.0)
    dados["descricao"] = (
        dados["descricao"].fillna("Não informado").astype(str).str.strip()
        .replace("", "Não informado")
    )
    if "Loja" in dados.columns:
        dados["Loja"] = (
            dados["Loja"].fillna("Não informada").astype(str).str.strip()
            .replace("", "Não informada")
        )

    cliente_limpo = str(cliente or "").strip()
    if not cliente_limpo:
        raise ErroPainelCliente("Informe o cliente.")
    if cliente_limpo not in set(dados["Cliente"].unique().tolist()):
        raise ErroPainelCliente(f"Cliente '{cliente_limpo}' não encontrado na base.")

    referencia = (
        pd.Timestamp(data_referencia).normalize()
        if data_referencia is not None
        else dados[COLUNA_PERIODO_INTERNA].max()
    )
    if pd.isna(referencia):
        raise ErroPainelCliente("A base não possui período mensal válido.")
    referencia = _inicio_mes(referencia)

    meses_historico = max(2, min(int(meses_historico or 10), 24))
    top_n = max(1, min(int(top_n or 5), 10))
    inicio_atual = _inicio_mes(referencia)
    inicio_minimo_base = _inicio_mes(dados[COLUNA_PERIODO_INTERNA].min())
    cliente_df = dados.loc[dados["Cliente"] == cliente_limpo].copy()

    inicios = [
        _deslocar_mes(inicio_atual, deslocamento)
        for deslocamento in range(-meses_historico, 1)
    ]
    inicios = [inicio for inicio in inicios if inicio >= inicio_minimo_base]
    if not inicios or inicios[-1] != inicio_atual:
        inicios.append(inicio_atual)

    serie: list[dict] = []
    recortes: dict[pd.Timestamp, pd.DataFrame] = {}
    for inicio in inicios:
        recorte = cliente_df.loc[cliente_df[COLUNA_PERIODO_INTERNA] == inicio]
        recortes[inicio] = recorte
        serie.append({
            "periodo": inicio.strftime("%Y-%m"),
            "rotulo": f"{MESES_ABREV[inicio.month - 1]}/{str(inicio.year)[-2:]}",
            "receita": round(float(recorte["Receita"].sum()), 2),
            "qtd": round(float(recorte["QTD"].sum()), 2),
            "atual": inicio == inicio_atual,
        })

    historicos = [item for item in serie if not item["atual"]]
    meses_media = len(historicos)
    atual = serie[-1]
    anterior = historicos[-1] if historicos else {"receita": 0.0, "qtd": 0.0, "periodo": ""}
    receita_media = (
        sum(item["receita"] for item in historicos) / meses_media if meses_media else 0.0
    )
    qtd_media = sum(item["qtd"] for item in historicos) / meses_media if meses_media else 0.0

    historico_frames = [recortes[inicio] for inicio in inicios if inicio != inicio_atual]
    historico_df = (
        pd.concat(historico_frames, ignore_index=True)
        if historico_frames else cliente_df.iloc[0:0].copy()
    )
    atual_df = recortes[inicio_atual]
    atual_prod = atual_df.groupby("descricao", dropna=False).agg(
        receita_atual=("Receita", "sum"), qtd_atual=("QTD", "sum"),
    )
    hist_prod = historico_df.groupby("descricao", dropna=False)["Receita"].sum()
    produtos = sorted(set(atual_prod.index.astype(str)) | set(hist_prod.index.astype(str)))

    grupos_produtos: dict[str, list[dict]] = {
        "subiram": [], "mantiveram": [], "cairam": [],
    }
    divisor = max(meses_media, 1)
    for produto in produtos:
        receita_atual = _numero(
            atual_prod.loc[produto, "receita_atual"] if produto in atual_prod.index else 0,
        )
        qtd_atual = _numero(
            atual_prod.loc[produto, "qtd_atual"] if produto in atual_prod.index else 0,
        )
        receita_media_produto = _numero(hist_prod.get(produto, 0)) / divisor
        if receita_atual == 0 and receita_media_produto == 0:
            continue
        item = _produto_item(produto, receita_atual, receita_media_produto, qtd_atual)
        variacao = item["variacao"]
        if receita_media_produto <= 0 and receita_atual > 0:
            grupos_produtos["subiram"].append(item)
        elif variacao is not None and variacao > 20:
            grupos_produtos["subiram"].append(item)
        elif variacao is not None and variacao < -20:
            grupos_produtos["cairam"].append(item)
        else:
            grupos_produtos["mantiveram"].append(item)

    grupos_produtos["subiram"].sort(
        key=lambda item: (item["receita_atual"], item["diferenca"]), reverse=True,
    )
    grupos_produtos["mantiveram"].sort(
        key=lambda item: item["receita_atual"], reverse=True,
    )
    grupos_produtos["cairam"].sort(
        key=lambda item: (item["receita_media"] - item["receita_atual"], item["receita_media"]),
        reverse=True,
    )
    contagens_produtos = {chave: len(itens) for chave, itens in grupos_produtos.items()}
    grupos_produtos = {
        chave: itens[:top_n] for chave, itens in grupos_produtos.items()
    }

    lojas: list[dict] = []
    if "Loja" in atual_df.columns:
        agregado_lojas = (
            atual_df.groupby("Loja", dropna=False)
            .agg(receita=("Receita", "sum"), qtd=("QTD", "sum"))
            .reset_index()
            .sort_values("receita", ascending=False)
        )
        total_lojas = float(agregado_lojas["receita"].sum())
        lojas = [
            {
                "loja": str(linha.Loja),
                "receita": round(float(linha.receita), 2),
                "qtd": round(float(linha.qtd), 2),
                "participacao": (
                    float(linha.receita) / total_lojas * 100 if total_lojas > 0 else 0.0
                ),
            }
            for linha in agregado_lojas.itertuples(index=False)
        ]

    return {
        "cliente": cliente_limpo,
        "data_referencia": referencia.strftime("%Y-%m-%d"),
        "periodo_atual": atual["periodo"],
        "periodo_anterior": anterior["periodo"],
        "meses_media": meses_media,
        "receita_atual": atual["receita"],
        "receita_anterior": anterior["receita"],
        "receita_media": round(receita_media, 2),
        "variacao_receita_anterior": _variacao(atual["receita"], anterior["receita"]),
        "variacao_receita_media": _variacao(atual["receita"], receita_media),
        "delta_receita_anterior": round(atual["receita"] - anterior["receita"], 2),
        "qtd_atual": atual["qtd"],
        "qtd_anterior": anterior["qtd"],
        "qtd_media": round(qtd_media, 2),
        "variacao_qtd_anterior": _variacao(atual["qtd"], anterior["qtd"]),
        "variacao_qtd_media": _variacao(atual["qtd"], qtd_media),
        "serie": serie,
        "produtos": grupos_produtos,
        "contagens_produtos": contagens_produtos,
        "lojas": lojas,
    }


def _fmt_numero(valor: float, casas: int = 0) -> str:
    texto = f"{_numero(valor):,.{casas}f}"
    return texto.replace(",", "X").replace(".", ",").replace("X", ".")


def _fmt_moeda(valor: float, casas: int = 0) -> str:
    return f"R$ {_fmt_numero(valor, casas)}"


def _fmt_pct(valor: float | None) -> str:
    if valor is None or not math.isfinite(valor):
        return "novo"
    sinal = "+" if valor > 0 else ""
    return f"{sinal}{_fmt_numero(valor, 1)}%"


def _hex(valor: str):
    from reportlab.lib.colors import HexColor
    return HexColor(valor)


def _texto_cortado(texto: str, largura: float, fonte: str, tamanho: float) -> str:
    from reportlab.pdfbase.pdfmetrics import stringWidth

    texto = str(texto)
    if stringWidth(texto, fonte, tamanho) <= largura:
        return texto
    sufixo = "..."
    while texto and stringWidth(texto + sufixo, fonte, tamanho) > largura:
        texto = texto[:-1]
    return texto + sufixo


def _linha_texto(canvas, x: float, y: float, texto: str, *, tamanho=7, cor="#f4f4f5",
                 fonte="Helvetica", alinhamento="left") -> None:
    canvas.setFont(fonte, tamanho)
    canvas.setFillColor(_hex(cor))
    if alinhamento == "right":
        canvas.drawRightString(x, y, texto)
    elif alinhamento == "center":
        canvas.drawCentredString(x, y, texto)
    else:
        canvas.drawString(x, y, texto)


def _painel(canvas, x: float, y: float, largura: float, altura: float, *, destaque=False) -> None:
    canvas.setFillColor(_hex("#151515"))
    canvas.setStrokeColor(_hex("#caa61a" if destaque else "#303030"))
    canvas.setLineWidth(0.9 if destaque else 0.55)
    canvas.rect(x, y, largura, altura, fill=1, stroke=1)
    if destaque:
        canvas.setFillColor(_hex("#d8b323"))
        canvas.rect(x, y + altura - 2.5, largura, 2.5, fill=1, stroke=0)


def _desenhar_kpi(canvas, x: float, y: float, largura: float, titulo: str,
                  valor: str, anterior: str, media: str,
                  var_anterior: float | None, var_media: float | None) -> None:
    _painel(canvas, x, y, largura, 68, destaque=True)
    _linha_texto(canvas, x + 12, y + 49, titulo.upper(), tamanho=7.5, cor="#a3a3a3")
    _linha_texto(canvas, x + 12, y + 31, valor, tamanho=15, fonte="Helvetica-Bold")
    cor_var = "#efca35" if (var_anterior or 0) >= 0 else "#e59a9a"
    _linha_texto(
        canvas, x + largura - 12, y + 33, _fmt_pct(var_anterior), tamanho=10,
        fonte="Helvetica-Bold", cor=cor_var, alinhamento="right",
    )
    _linha_texto(canvas, x + 12, y + 15, anterior, tamanho=6.5, cor="#a3a3a3")
    _linha_texto(canvas, x + 12, y + 5, media, tamanho=6.5, cor="#a3a3a3")
    _linha_texto(
        canvas, x + largura - 12, y + 5, _fmt_pct(var_media), tamanho=6.5,
        fonte="Helvetica-Bold", cor="#efca35" if (var_media or 0) >= 0 else "#e59a9a",
        alinhamento="right",
    )


def _desenhar_grafico(canvas, dados: dict, x: float, y: float, largura: float, altura: float) -> None:
    _linha_texto(
        canvas, x, y + altura + 13,
        "RECEITA E ITENS · EVOLUÇÃO MENSAL",
        tamanho=8, fonte="Helvetica-Bold", cor="#d8b323",
    )
    serie = dados["serie"]
    if not serie:
        _linha_texto(canvas, x, y + altura / 2, "Sem histórico disponível.", cor="#a3a3a3")
        return
    margem_esq, margem_dir, margem_inf, margem_sup = 31, 25, 22, 10
    gx, gy = x + margem_esq, y + margem_inf
    gw, gh = largura - margem_esq - margem_dir, altura - margem_inf - margem_sup
    max_receita = max(max(item["receita"] for item in serie), 1.0)
    max_qtd = max(max(item["qtd"] for item in serie), 1.0)
    max_receita *= 1.12
    max_qtd *= 1.12
    for indice in range(5):
        yy = gy + gh * indice / 4
        canvas.setStrokeColor(_hex("#2a2a2a"))
        canvas.setLineWidth(0.45)
        canvas.line(gx, yy, gx + gw, yy)
        _linha_texto(
            canvas, gx - 5, yy - 2, _fmt_numero(max_receita * indice / 4),
            tamanho=5.5, cor="#9a9a9a", alinhamento="right",
        )
        _linha_texto(
            canvas, gx + gw + 5, yy - 2, _fmt_numero(max_qtd * indice / 4),
            tamanho=5.5, cor="#9a9a9a",
        )
    passo = gw / len(serie)
    barra = min(24, passo * 0.62)
    pontos: list[tuple[float, float]] = []
    for indice, item in enumerate(serie):
        centro = gx + passo * (indice + 0.5)
        h_barra = gh * item["receita"] / max_receita
        canvas.setFillColor(_hex("#d8b323" if item["atual"] else "#b9b9bb"))
        canvas.rect(centro - barra / 2, gy, barra, h_barra, fill=1, stroke=0)
        _linha_texto(
            canvas, centro, gy - 12, item["rotulo"], tamanho=5.4, cor="#a3a3a3",
            alinhamento="center",
        )
        if h_barra > 8:
            _linha_texto(
                canvas, centro, gy + h_barra - 7, _fmt_numero(item["receita"]),
                tamanho=5, cor="#090909", fonte="Helvetica-Bold", alinhamento="center",
            )
        pontos.append((centro, gy + gh * item["qtd"] / max_qtd))
    canvas.setStrokeColor(_hex("#f4f4f5"))
    canvas.setLineWidth(1.7)
    for primeiro, segundo in zip(pontos, pontos[1:]):
        canvas.line(primeiro[0], primeiro[1], segundo[0], segundo[1])
    for px, py in pontos:
        canvas.setFillColor(_hex("#f4f4f5"))
        canvas.circle(px, py, 2.2, fill=1, stroke=0)
    legenda_x = x + largura / 2 - 38
    canvas.setFillColor(_hex("#b9b9bb"))
    canvas.rect(legenda_x, y + 1, 7, 4, fill=1, stroke=0)
    _linha_texto(canvas, legenda_x + 10, y + 0.5, "Receita R$", tamanho=5.8, cor="#b9b9bb")
    canvas.setFillColor(_hex("#f4f4f5"))
    canvas.circle(legenda_x + 70, y + 3, 2, fill=1, stroke=0)
    _linha_texto(canvas, legenda_x + 76, y + 0.5, "Itens", tamanho=5.8, cor="#f4f4f5")


def _desenhar_lojas(canvas, dados: dict, x: float, y: float, largura: float, altura: float) -> None:
    _linha_texto(canvas, x, y + altura + 12, "LOJAS", tamanho=8, fonte="Helvetica-Bold", cor="#d8b323")
    _painel(canvas, x, y, largura, altura)
    lojas = list(dados.get("lojas") or [])
    if not lojas:
        _linha_texto(canvas, x + 12, y + altura / 2, "Loja não disponível na base.", cor="#a3a3a3")
        return
    exibidas = lojas[:4]
    if len(lojas) > 4:
        restantes = lojas[4:]
        exibidas.append({
            "loja": "Outras lojas",
            "receita": sum(item["receita"] for item in restantes),
            "qtd": sum(item["qtd"] for item in restantes),
            "participacao": sum(item["participacao"] for item in restantes),
        })
    _linha_texto(canvas, x + 12, y + altura - 15, "LOJA", tamanho=5.6, cor="#8f8f8f", fonte="Helvetica-Bold")
    _linha_texto(canvas, x + largura - 115, y + altura - 15, "RECEITA", tamanho=5.6, cor="#8f8f8f", fonte="Helvetica-Bold")
    _linha_texto(canvas, x + largura - 58, y + altura - 15, "% CLIENTE", tamanho=5.6, cor="#8f8f8f", fonte="Helvetica-Bold")
    for indice, item in enumerate(exibidas):
        yy = y + altura - 31 - indice * 14
        _linha_texto(canvas, x + 12, yy, _texto_cortado(item["loja"], largura - 150, "Helvetica", 6.5), tamanho=6.5)
        _linha_texto(canvas, x + largura - 70, yy, _fmt_moeda(item["receita"]), tamanho=6.5, alinhamento="right")
        participacao = f"{_fmt_numero(item['participacao'], 1)}%"
        _linha_texto(canvas, x + largura - 12, yy, participacao, tamanho=6.5, cor="#b9b9bb", alinhamento="right")


def _desenhar_tabela_produtos(
    canvas, dados: dict, chave: str, titulo: str, x: float, topo: float,
    largura: float, cor_titulo: str,
) -> None:
    itens = dados["produtos"][chave]
    total = dados["contagens_produtos"][chave]
    rotulo_total = f"{total} produto" if total == 1 else f"{total} produtos"
    _linha_texto(
        canvas, x, topo, f"{titulo.upper()}  ·  {rotulo_total}",
        tamanho=8, fonte="Helvetica-Bold", cor=cor_titulo,
    )
    y_header = topo - 17
    row_h = 17
    col_prod = largura * 0.43
    col_atual = largura * 0.18
    col_media = largura * 0.17
    col_var = largura * 0.12
    canvas.setFillColor(_hex("#242424"))
    canvas.rect(x, y_header, largura, row_h, fill=1, stroke=0)
    cabecalhos = (
        (x + 5, "PRODUTO", "left"),
        (x + col_prod + col_atual - 5, "ATUAL R$", "right"),
        (x + col_prod + col_atual + col_media - 5, "MÉDIA R$", "right"),
        (x + col_prod + col_atual + col_media + col_var - 5, "VAR.", "right"),
        (x + largura - 5, "UN", "right"),
    )
    for cx, texto, alinhamento in cabecalhos:
        _linha_texto(canvas, cx, y_header + 5.5, texto, tamanho=5.2, cor="#9a9a9a", fonte="Helvetica-Bold", alinhamento=alinhamento)
    if not itens:
        _painel(canvas, x, y_header - row_h, largura, row_h)
        _linha_texto(canvas, x + 6, y_header - row_h + 5.5, "Nenhum produto neste grupo.", tamanho=6, cor="#8f8f8f")
        return
    for indice, item in enumerate(itens):
        yy = y_header - row_h * (indice + 1)
        canvas.setFillColor(_hex("#121212" if indice % 2 == 0 else "#171717"))
        canvas.setStrokeColor(_hex("#2a2a2a"))
        canvas.setLineWidth(0.4)
        canvas.rect(x, yy, largura, row_h, fill=1, stroke=1)
        nome = _texto_cortado(item["produto"], col_prod - 10, "Helvetica", 6.2)
        _linha_texto(canvas, x + 5, yy + 5.3, nome, tamanho=6.2)
        _linha_texto(canvas, x + col_prod + col_atual - 5, yy + 5.3, _fmt_numero(item["receita_atual"]), tamanho=6.2, alinhamento="right")
        _linha_texto(canvas, x + col_prod + col_atual + col_media - 5, yy + 5.3, _fmt_numero(item["receita_media"]), tamanho=6.2, cor="#b0b0b0", alinhamento="right")
        cor_var = "#efca35" if chave == "subiram" else ("#e59a9a" if chave == "cairam" else "#b0b0b0")
        _linha_texto(canvas, x + col_prod + col_atual + col_media + col_var - 5, yy + 5.3, _fmt_pct(item["variacao"]), tamanho=6.1, fonte="Helvetica-Bold", cor=cor_var, alinhamento="right")
        _linha_texto(canvas, x + largura - 5, yy + 5.3, _fmt_numero(item["qtd_atual"]), tamanho=6.2, alinhamento="right")


def gerar_painel_cliente_pdf(
    caminho_saida: str | Path,
    dados: dict,
    *,
    empresa: str = "",
    loja: str | None = None,
    posicao: int | None = None,
    total: int | None = None,
) -> None:
    """Renderiza o painel em uma página PDF 16:9 pronta para download."""
    from reportlab.pdfgen import canvas as pdf_canvas

    largura, altura = 960.0, 540.0
    canvas = pdf_canvas.Canvas(str(caminho_saida), pagesize=(largura, altura), pageCompression=1)
    canvas.setTitle(f"Painel do cliente - {dados['cliente']}")
    canvas.setAuthor("2D Prisma - Analisador de Monitoria")
    canvas.setFillColor(_hex("#090909"))
    canvas.rect(0, 0, largura, altura, fill=1, stroke=0)

    referencia = pd.Timestamp(dados["data_referencia"])
    prefixo = "CLIENTE MONITORADO"
    if posicao and total and posicao > 0 and total > 0:
        prefixo = f"CLIENTE {min(posicao, total)} DE {total}"
    escopo = (
        f"{prefixo}  ·  {MESES_PT[referencia.month - 1].upper()} "
        f"{referencia.year}  ·  ANÁLISE MENSAL"
    )
    _linha_texto(canvas, 40, 511, escopo, tamanho=8, fonte="Helvetica-Bold", cor="#d8b323")
    _linha_texto(canvas, 40, 485, dados["cliente"], tamanho=18, fonte="Helvetica-Bold")
    contexto = " · ".join(parte for parte in (empresa, loja or "Todas as lojas") if parte)
    if contexto:
        _linha_texto(canvas, 40, 470, contexto, tamanho=6.5, cor="#8f8f8f")

    delta = dados["delta_receita_anterior"]
    _painel(canvas, 760, 480, 160, 43, destaque=True)
    _linha_texto(canvas, 772, 496, "Dif. vs mês anterior", tamanho=6.5, cor="#a3a3a3")
    _linha_texto(
        canvas, 908, 495, ("+" if delta > 0 else "") + _fmt_moeda(delta),
        tamanho=12, fonte="Helvetica-Bold",
        cor="#efca35" if delta >= 0 else "#e59a9a", alinhamento="right",
    )

    media_rotulo = f"média {dados['meses_media']}M" if dados["meses_media"] else "sem média"
    periodo_anterior = dados["periodo_anterior"] or "mês anterior"
    partes_periodo = periodo_anterior.split("-")
    if (
        len(partes_periodo) == 2
        and partes_periodo[0].isdigit()
        and partes_periodo[1].isdigit()
        and 1 <= int(partes_periodo[1]) <= 12
    ):
        periodo_anterior = (
            f"{MESES_ABREV[int(partes_periodo[1]) - 1]}/{partes_periodo[0][-2:]}"
        )
    _desenhar_kpi(
        canvas, 40, 390, 210, "Receita", _fmt_moeda(dados["receita_atual"]),
        f"{periodo_anterior} {_fmt_moeda(dados['receita_anterior'])}",
        f"{media_rotulo} {_fmt_moeda(dados['receita_media'])}",
        dados["variacao_receita_anterior"], dados["variacao_receita_media"],
    )
    _desenhar_kpi(
        canvas, 265, 390, 210, "Itens", _fmt_numero(dados["qtd_atual"]),
        f"{periodo_anterior} {_fmt_numero(dados['qtd_anterior'])}",
        f"{media_rotulo} {_fmt_numero(dados['qtd_media'])}",
        dados["variacao_qtd_anterior"], dados["variacao_qtd_media"],
    )
    _desenhar_grafico(canvas, dados, 40, 205, 435, 150)
    _desenhar_lojas(canvas, dados, 40, 54, 435, 105)

    _desenhar_tabela_produtos(canvas, dados, "subiram", "Produtos que subiram", 510, 452, 410, "#d8b323")
    _desenhar_tabela_produtos(canvas, dados, "mantiveram", "Produtos que mantiveram o padrão", 510, 315, 410, "#b9b9bb")
    _desenhar_tabela_produtos(canvas, dados, "cairam", "Produtos que caíram", 510, 178, 410, "#e59a9a")

    _linha_texto(
        canvas, 40, 22,
        "Critério de produtos: acima de +20% sobe; entre -20% e +20% mantém; abaixo de -20% cai.",
        tamanho=5.8, cor="#777777",
    )
    _linha_texto(canvas, 920, 22, "2D Prisma - Clientes", tamanho=5.8, cor="#777777", alinhamento="right")
    canvas.showPage()
    canvas.save()
