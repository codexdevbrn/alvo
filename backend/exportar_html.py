"""Exportação HTML dos relatórios do motor — um arquivo único, estático e autocontido.

Pensado para ENVIAR (e-mail, WhatsApp, drive): o destinatário abre no navegador
sem instalar nada, sem servidor e sem internet. CSS e o pequeno script de
ordenação ficam embutidos; não há imagem, biblioteca ou link externo.

Visual = o do app (tema escuro, acento dourado, cards, abas por relatório). As
abas são CSS puro (`input[type=radio]:checked ~ painel`): trocar de relatório sem
uma linha de JavaScript mantém o arquivo estático de verdade — abre igual em
navegador com script bloqueado, em cliente de e-mail e em modo offline.

Na impressão (`@media print`) o documento vira claro, mostra TODOS os
relatórios (as abas esconderiam o resto do conteúdo no papel) e some com a barra
de abas — assim "Imprimir → Salvar como PDF" gera um PDF completo e legível.

Fontes: stack do sistema. O app usa Inter/Outfit via Google Fonts, mas embutir
webfont estouraria o tamanho do arquivo e baixar da rede quebraria a premissa de
funcionar offline.

As regras de coluna (moeda, percentual, delta, perda) espelham
`dashboard/src/components/analisador/ResultTable.tsx`. Hoje a duplicação é
assumida: são duas listas curtas em dois lugares. Se elas crescerem, o certo é o
backend publicar os metadados de coluna e a tela consumir.
"""

from datetime import datetime
from html import escape

import pandas as pd

from engine.recursos import NOME_EMPRESA, NOME_SISTEMA
from exportar_excel import (
    CATALOGO_RELATORIOS,
    COLUNAS_MOEDA_POR_ANALISE,
    calcular_faixa_totais,
    _eh_coluna_percentual,
)

#: Título de negócio por chave de análise (o mesmo que aparece na tela).
TITULOS_RELATORIOS = {
    chave: titulo
    for _categoria, itens in CATALOGO_RELATORIOS
    for chave, titulo in itens
}
TITULOS_RELATORIOS.update({
    "liquidez_estoque": "Liquidez — Estoque",
    "liquidez_vendas": "Liquidez — Vendas",
    "abc_produtos": "ABC de Produtos",
    "migracao_resumo": "Migração de Grupo — Resumo",
    "migracao_score_clientes": "Migração de Grupo — Score por cliente",
})

#: Variação de verdade: positivo é bom (verde ▲), negativo é ruim (vermelho ▼).
COLUNAS_DELTA = {
    "Desempenho_Pct",
    "Ganho_Perda",
    "Diferenca_QTD",
    "Variacao_Percentual",
    "Variacao_Global_Periodo_Pct",
    "Tendencia_Pct",
}

#: Perda registrada como número POSITIVO. Aqui positivo é ruim: vermelho ▼, nunca verde.
COLUNAS_PERDA = {
    "Reducao_Receita",
    "Reducao_Percentual",
    "Renuncia",
    "Renuncia_Acumulada",
    "Renuncia_Percentual",
    "Perda_Receita",
    "Receita_Sob_Risco",
    "Impacto_Financeiro_Churn",
    "Maior_Retracao_Individual_Pct",
}

#: Texto que já diz a direção (coluna `Direcao` da migração de grupo).
TEXTO_DIRECAO = {"Subiu": "pos", "Desceu": "neg"}

#: Colunas com o mesmo valor em toda linha viram informação do topo em vez de
#: coluna repetida — igual à tela. Só sai da tabela se o valor for constante.
COLUNAS_INFORMACIONAIS_POR_ANALISE = {
    "comparativo_receita": ["Periodo_Ano_Anterior", "Periodo_Ano_Atual"],
}

ESTILO = """
/* Paleta espelhada de dashboard/src/index.css (:root) — mesma marca do app. */
:root {
  --bg-main: #0b0b0d;
  --bg-card: #131316;
  --border: #222226;
  --border-strong: #2c2c31;
  --text-primary: #f4f4f2;
  --text-secondary: #a6a6ad;
  --text-muted: #6d6d76;
  --accent: #dabb6c;
  --accent-soft: rgba(218, 187, 108, 0.16);
  --accent-contrast: #0b0b0d;
  --success: #4cae7a;
  --danger: #e0645c;
  color-scheme: dark;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  padding: 2rem 1.5rem 3rem;
  background: var(--bg-main);
  color: var(--text-primary);
  font: 14px/1.45 "Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Arial, sans-serif;
  -webkit-font-smoothing: antialiased;
}
.doc { max-width: 1240px; margin: 0 auto; }

/* Cabeçalho: mesma ideia do header do app (marca + acento dourado). */
.capa {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-left: 3px solid var(--accent);
  border-radius: 0.9rem;
  padding: 1.4rem 1.6rem;
  margin-bottom: 1.25rem;
}
.capa h1 { margin: 0; font-size: 1.5rem; font-weight: 700; letter-spacing: -0.02em; }
.capa h1 em { color: var(--accent); font-style: normal; }
.capa p { margin: 0.2rem 0 0; color: var(--text-secondary); font-size: 0.82rem; }
.capa dl {
  display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
  gap: 0.75rem 1.5rem; margin: 1.25rem 0 0;
}
/* Cada par rótulo/valor é uma célula do grid — sem o wrapper, dt e dd viram
   itens independentes e o valor cai numa coluna diferente do próprio rótulo. */
.capa dl > div { min-width: 0; }
.capa dt {
  font-size: 0.62rem; text-transform: uppercase; letter-spacing: 0.08em;
  color: var(--text-muted);
}
.capa dd { margin: 0.15rem 0 0; font-weight: 600; }

/* ---------- Abas (CSS puro: radio + irmão :checked) ---------- */
.abas-radio { position: absolute; opacity: 0; pointer-events: none; }
.abas {
  display: flex; flex-wrap: wrap; gap: 0.4rem;
  margin-bottom: 1rem;
}
.abas label {
  padding: 0.5rem 0.9rem;
  border: 1px solid var(--border);
  border-radius: 0.6rem;
  background: var(--bg-card);
  color: var(--text-secondary);
  font-size: 0.78rem; font-weight: 600;
  cursor: pointer;
  user-select: none;
}
.abas label:hover { border-color: var(--border-strong); color: var(--text-primary); }
.painel { display: none; }

/* ---------- Card de relatório ---------- */
.relatorio {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 0.9rem;
  padding: 1.25rem;
}
.relatorio h2 { margin: 0; font-size: 1.05rem; font-weight: 700; }
.relatorio .meta {
  margin: 0.2rem 0 1rem; font-size: 0.72rem; color: var(--text-muted);
  text-transform: uppercase; letter-spacing: 0.06em;
}

/* ---------- Faixa de totais / informações ---------- */
.faixa {
  display: flex; flex-wrap: wrap; align-items: center; gap: 0.5rem 1.75rem;
  padding: 0.75rem 1rem; margin-bottom: 0.9rem;
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid var(--border);
  border-radius: 0.6rem;
}
.faixa-rotulo {
  font-size: 0.72rem; font-weight: 700; text-transform: uppercase;
  letter-spacing: 0.05em; color: var(--accent);
}
.faixa-item { display: flex; flex-direction: column; }
.faixa-item.is-info { padding-right: 1.75rem; border-right: 1px solid var(--border); }
.faixa-item > span { font-size: 0.68rem; color: var(--text-muted); }
.faixa-item > strong { font-size: 0.98rem; font-variant-numeric: tabular-nums; }
.faixa-item.is-info > strong { color: var(--accent); }

/* ---------- Tabela (igual à do Analisador) ---------- */
.tabela-wrap {
  max-height: 70vh; overflow: auto;
  border: 1px solid var(--border); border-radius: 0.75rem;
  background: #121216;
}
table { width: 100%; border-collapse: separate; border-spacing: 0; font-size: 0.8rem; }
th {
  position: sticky; top: 0; z-index: 2;
  background: #1e1e25; color: #fff;
  text-align: left; font-weight: 700; font-size: 0.7rem;
  text-transform: uppercase; letter-spacing: 0.06em;
  padding: 0.6rem 0.5rem; white-space: nowrap;
  border-bottom: 2px solid rgba(218, 187, 108, 0.45);
}
.sort-btn {
  display: flex; align-items: center; gap: 0.35rem; width: 100%;
  padding: 0; border: 0; background: transparent; color: inherit;
  font: inherit; letter-spacing: inherit; text-transform: inherit;
  cursor: pointer; text-align: inherit;
}
th.num .sort-btn { justify-content: flex-end; }
.sort-btn:hover, .sort-btn:focus-visible { color: var(--accent); }
.sort-btn:focus-visible { outline: 2px solid var(--accent); outline-offset: 3px; }
.sort-indicator { color: var(--accent); min-width: 0.8rem; text-align: center; }
td {
  padding: 0.5rem 0.75rem; color: var(--text-secondary);
  border-bottom: 1px solid var(--border); white-space: nowrap;
}
tbody tr:nth-child(even) td { background: rgba(255, 255, 255, 0.032); }
tbody tr:hover td { background: rgba(255, 255, 255, 0.075); }
td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; }
.delta { display: inline-flex; align-items: center; gap: 0.3rem; font-weight: 600; }
.delta.is-pos { color: var(--success); }
.delta.is-neg { color: var(--danger); }
.delta .seta { font-size: 0.6rem; line-height: 1; }
.vazio { color: var(--text-muted); font-style: italic; margin: 0; }
footer {
  color: var(--text-muted); font-size: 0.7rem; text-align: center; padding-top: 1.25rem;
}

/* ---------- Impressão ----------
   No papel não existe "clicar na aba": mostra todos os relatórios, um por
   página, e volta pro claro (tema escuro gasta tinta e sai ilegível). */
@media print {
  body { background: #fff; color: #000; padding: 0; }
  .capa { background: #fff; border-color: #ccc; }
  .capa p, .capa dt { color: #555; }
  .capa h1 em { color: #8a6d1f; }
  .abas { display: none; }
  .painel { display: block !important; break-after: page; }
  .painel:last-of-type { break-after: auto; }
  .relatorio { background: #fff; border-color: #ccc; border-radius: 0; }
  .relatorio h2, td { color: #000; }
  .tabela-wrap { max-height: none; overflow: visible; border-color: #ccc; background: #fff; }
  th { position: static; background: #25252c; }
  tbody tr:nth-child(even) td { background: #f4f4f2; }
  .faixa { background: #f7f5f0; border-color: #ddd; }
  .faixa-item > span { color: #555; }
  .delta.is-pos { color: #157347; }
  .delta.is-neg { color: #b42318; }
  .sort-indicator { display: none; }
}
"""


SCRIPT_ORDENACAO = r"""
document.addEventListener('click', function (evento) {
  const botao = evento.target.closest('.sort-btn');
  if (!botao) return;
  const tabela = botao.closest('table[data-sortable]');
  if (!tabela) return;
  const coluna = Number(botao.dataset.column);
  const tipo = botao.dataset.type;
  const cabecalho = botao.closest('th');
  const direcao = cabecalho.getAttribute('aria-sort') === 'ascending'
    ? 'descending' : 'ascending';
  const linhas = Array.from(tabela.tBodies[0].rows);

  linhas.sort(function (linhaA, linhaB) {
    const celulaA = linhaA.cells[coluna];
    const celulaB = linhaB.cells[coluna];
    const vazioA = celulaA.dataset.sortEmpty === '1';
    const vazioB = celulaB.dataset.sortEmpty === '1';
    if (vazioA || vazioB) {
      if (vazioA !== vazioB) return vazioA ? 1 : -1;
      return Number(linhaA.dataset.originalIndex) - Number(linhaB.dataset.originalIndex);
    }

    let comparacao;
    if (tipo === 'number') {
      comparacao = Number(celulaA.dataset.sortValue) - Number(celulaB.dataset.sortValue);
    } else {
      comparacao = celulaA.dataset.sortValue.localeCompare(
        celulaB.dataset.sortValue, 'pt-BR', { numeric: true, sensitivity: 'base' }
      );
    }
    if (comparacao === 0) {
      return Number(linhaA.dataset.originalIndex) - Number(linhaB.dataset.originalIndex);
    }
    return direcao === 'ascending' ? comparacao : -comparacao;
  });

  tabela.querySelectorAll('th').forEach(function (th) {
    th.setAttribute('aria-sort', 'none');
    const indicador = th.querySelector('.sort-indicator');
    if (indicador) indicador.textContent = '↕';
  });
  cabecalho.setAttribute('aria-sort', direcao);
  cabecalho.querySelector('.sort-indicator').textContent =
    direcao === 'ascending' ? '▲' : '▼';
  linhas.forEach(function (linha) { tabela.tBodies[0].appendChild(linha); });
});
"""


def _css_abas(quantidade):
    """Regras que ligam cada radio ao seu painel e ao estado ativo do rótulo.

    Precisa ser gerado: o seletor cita o id de cada aba, então o número de
    regras acompanha o número de relatórios do arquivo.
    """
    regras = []
    for indice in range(quantidade):
        regras.append(
            f"#aba-{indice}:checked ~ .painel-{indice} {{ display: block; }}\n"
            f'#aba-{indice}:checked ~ .abas label[for="aba-{indice}"] {{'
            " background: var(--accent); border-color: var(--accent);"
            " color: var(--accent-contrast); }"
        )
    return "\n".join(regras)


def _formatar_numero(valor, coluna):
    """Mesmo critério da tela: percentual, moeda, inteiro, decimal — em pt-BR."""
    if _eh_coluna_percentual(coluna):
        return f"{valor:,.2f}%".replace(",", "\x00").replace(".", ",").replace("\x00", ".")
    if float(valor).is_integer():
        return f"{int(valor):,}".replace(",", ".")
    return f"{valor:,.2f}".replace(",", "\x00").replace(".", ",").replace("\x00", ".")


def _formatar_moeda(valor):
    texto = f"{abs(valor):,.2f}".replace(",", "\x00").replace(".", ",").replace("\x00", ".")
    return f"-R$ {texto}" if valor < 0 else f"R$ {texto}"


def _formatar_valor(valor, coluna, colunas_moeda):
    if valor is None or (isinstance(valor, float) and pd.isna(valor)) or valor is pd.NaT:
        return "—"
    if isinstance(valor, bool):
        return "Sim" if valor else "Não"
    if isinstance(valor, (int, float)):
        if pd.isna(valor):
            return "—"
        if coluna in colunas_moeda:
            return _formatar_moeda(float(valor))
        return _formatar_numero(float(valor), coluna)
    return str(valor)


def _tom(valor, coluna):
    """'pos' | 'neg' | None — ver COLUNAS_DELTA / COLUNAS_PERDA."""
    if isinstance(valor, str):
        return TEXTO_DIRECAO.get(valor.strip())
    if isinstance(valor, bool) or not isinstance(valor, (int, float)):
        return None
    if pd.isna(valor) or valor == 0:
        return None
    if coluna in COLUNAS_DELTA:
        return "pos" if valor > 0 else "neg"
    if coluna in COLUNAS_PERDA:
        return "neg" if valor > 0 else None
    return None


def _celula(valor, coluna, colunas_moeda):
    texto = escape(_formatar_valor(valor, coluna, colunas_moeda))
    tom = _tom(valor, coluna)
    if not tom:
        return texto
    seta = "▲" if tom == "pos" else "▼"
    return f'<span class="delta is-{tom}"><span class="seta">{seta}</span> {texto}</span>'


def _eh_coluna_numerica(df, coluna, colunas_moeda):
    return (
        coluna in colunas_moeda
        or _eh_coluna_percentual(coluna)
        or pd.api.types.is_numeric_dtype(df[coluna])
    )


def _atributos_ordenacao(valor):
    """Valor bruto seguro para o sorter, sem depender do texto pt-BR exibido."""
    vazio = valor is None or valor is pd.NaT
    if not vazio:
        try:
            vazio = bool(pd.isna(valor))
        except (TypeError, ValueError):
            vazio = False
    if vazio:
        return 'data-sort-empty="1" data-sort-value=""'
    if isinstance(valor, bool):
        bruto = "1" if valor else "0"
    elif isinstance(valor, (int, float)) or pd.api.types.is_number(valor):
        bruto = str(float(valor))
    elif hasattr(valor, "isoformat"):
        bruto = valor.isoformat()
    else:
        bruto = str(valor)
    return f'data-sort-empty="0" data-sort-value="{escape(bruto, quote=True)}"'


def _informacionais(chave, df):
    """[(coluna, texto)] das colunas constantes que saem da tabela."""
    itens = []
    for coluna in COLUNAS_INFORMACIONAIS_POR_ANALISE.get(chave, []):
        if coluna not in df.columns or df.empty:
            continue
        valores = df[coluna].dropna().unique()
        if len(valores) == 1:
            itens.append((coluna, str(valores[0])))
    return itens


def _faixa_html(chave, df, colunas_moeda):
    info = _informacionais(chave, df)
    totais = calcular_faixa_totais(chave, df) or {}
    partes = []

    for coluna, valor in info:
        partes.append(
            f'<span class="faixa-item is-info"><span>{escape(coluna)}</span>'
            f"<strong>{escape(valor)}</strong></span>"
        )

    numericos = [
        (coluna, valor) for coluna, valor in totais.items()
        if isinstance(valor, (int, float)) and not isinstance(valor, bool)
    ]
    if numericos:
        partes.append('<span class="faixa-rotulo">Totais</span>')
        for coluna, valor in numericos:
            partes.append(
                f'<span class="faixa-item"><span>{escape(coluna)}</span>'
                f"<strong>{_celula(valor, coluna, colunas_moeda)}</strong></span>"
            )

    if not partes:
        return ""
    return f'<div class="faixa">{"".join(partes)}</div>'


def _tabela_html(chave, df, colunas_moeda):
    info_colunas = {coluna for coluna, _valor in _informacionais(chave, df)}
    colunas = [c for c in df.columns if c not in info_colunas]
    if not colunas:
        return '<p class="vazio">Sem colunas para exibir.</p>'

    numericas = {c: _eh_coluna_numerica(df, c, colunas_moeda) for c in colunas}
    cabecalhos = []
    for indice, coluna in enumerate(colunas):
        tipo = "number" if numericas[coluna] else "text"
        cabecalhos.append(
            f'<th class="{"num" if numericas[coluna] else ""}" aria-sort="none">'
            f'<button type="button" class="sort-btn" data-column="{indice}" data-type="{tipo}"'
            f' aria-label="Ordenar por {escape(str(coluna), quote=True)}">'
            f'{escape(str(coluna))}<span class="sort-indicator" aria-hidden="true">↕</span>'
            f'</button></th>'
        )
    cabecalho = "".join(cabecalhos)

    linhas = []
    for indice_linha, registro in enumerate(df[colunas].itertuples(index=False, name=None)):
        celulas = "".join(
            f'<td class="{"num" if numericas[coluna] else ""}" {_atributos_ordenacao(valor)}>'
            f"{_celula(valor, coluna, colunas_moeda)}</td>"
            for coluna, valor in zip(colunas, registro)
        )
        linhas.append(f'<tr data-original-index="{indice_linha}">{celulas}</tr>')

    return (
        '<div class="tabela-wrap"><table data-sortable="true">'
        f"<thead><tr>{cabecalho}</tr></thead>"
        f'<tbody>{"".join(linhas)}</tbody>'
        "</table></div>"
    )


def exportar_relatorio_html(
    caminho_saida,
    resultados,
    *,
    nome_usuario=None,
    nome_empresa=None,
    colunas_moeda_por_analise=None,
):
    """Grava um HTML único com os relatórios de `resultados`.

    `resultados` tem o mesmo formato do Excel/PDF: {granularidade: {chave: DataFrame}}.
    """
    colunas_moeda_por_analise = colunas_moeda_por_analise or COLUNAS_MOEDA_POR_ANALISE
    gerado_em = datetime.now().strftime("%d/%m/%Y %H:%M")

    radios = []
    abas = []
    paineis = []
    for granularidade, analises in resultados.items():
        for chave, df in analises.items():
            if df is None:
                continue
            df = df.reset_index() if (df.index.name or isinstance(df.index, pd.MultiIndex)) else df
            titulo = TITULOS_RELATORIOS.get(chave, chave)
            rotulo = titulo if granularidade == "Alvos" else f"{titulo} ({granularidade})"
            indice = len(paineis)

            colunas_moeda = colunas_moeda_por_analise.get(chave, [])
            if df.empty:
                corpo = '<p class="vazio">Nenhuma linha para os parâmetros usados.</p>'
            else:
                corpo = _faixa_html(chave, df, colunas_moeda) + _tabela_html(chave, df, colunas_moeda)

            qtd = len(df)
            # Os radios vêm ANTES da barra de abas e dos painéis porque o seletor
            # de irmão (~) só alcança elementos seguintes.
            radios.append(
                f'<input class="abas-radio" type="radio" name="aba" id="aba-{indice}"'
                f'{" checked" if indice == 0 else ""}>'
            )
            abas.append(f'<label for="aba-{indice}">{escape(rotulo)}</label>')
            paineis.append(
                f'<div class="painel painel-{indice}">'
                f'<section class="relatorio">'
                f"<h2>{escape(rotulo)}</h2>"
                f'<p class="meta">{qtd} linha{"" if qtd == 1 else "s"}</p>'
                f"{corpo}</section></div>"
            )

    itens_capa = [("Gerado em", gerado_em)]
    if nome_empresa:
        itens_capa.insert(0, ("Empresa", str(nome_empresa)))
    if nome_usuario:
        itens_capa.append(("Gerado por", str(nome_usuario)))
    itens_capa.append(("Relatórios", str(len(paineis))))
    capa_dl = "".join(
        f"<div><dt>{escape(rotulo)}</dt><dd>{escape(valor)}</dd></div>"
        for rotulo, valor in itens_capa
    )

    if paineis:
        # Barra de abas só faz sentido com mais de um relatório; com um só, o
        # painel já vem visível (o primeiro radio nasce `checked`).
        barra = f'<nav class="abas">{"".join(abas)}</nav>' if len(paineis) > 1 else ""
        conteudo = f'{"".join(radios)}{barra}{"".join(paineis)}'
    else:
        conteudo = '<p class="vazio">Nenhum relatório selecionado.</p>'

    documento = f"""<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(NOME_SISTEMA)} — Relatórios{f" — {escape(str(nome_empresa))}" if nome_empresa else ""}</title>
<style>{ESTILO}
{_css_abas(len(paineis))}</style>
</head>
<body>
<div class="doc">
<header class="capa">
<h1>{escape(NOME_SISTEMA)} — <em>Relatórios</em></h1>
<p>Visualização estática · {escape(NOME_EMPRESA)}</p>
<dl>{capa_dl}</dl>
</header>
{conteudo}
<footer>Documento estático gerado pelo {escape(NOME_SISTEMA)} em {gerado_em}. Os números refletem os parâmetros usados nesta geração.</footer>
</div>
<script>{SCRIPT_ORDENACAO}</script>
</body>
</html>
"""

    with open(caminho_saida, "w", encoding="utf-8") as arquivo:
        arquivo.write(documento)
