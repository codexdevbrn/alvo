"""Tabela 2D do GPS (aba "Lógica" de `Logica do GPS.xlsx`, Marco Flores).

É a mesma tabela que o Power BI consulta (`Logica_Tabela_Estruturada`) nas
medidas da aba Dispersão do GPS. Vale só para as 36 descrições daqui — os itens
que somam 70% do mercado de varejo. Descrição fora da lista não tem GPS.

Unidades em pontos percentuais (−6,50% da planilha vira -6.5):

- `faixas`: dispersão (margem do item − margem geral) por perfil, do mais
  agressivo ao mais conservador. `None` é o lado aberto do "Até X".
- `participacao`: até onde vai "Abaixo da Média" e até onde vai "Dentro da
  Média"; acima disso é "Acima da Média".

Mudou a planilha? `ler_planilha` lê o xlsx no mesmo formato, e
`tests/test_gps_dispersao.py` confere a planilha contra esta tabela quando o
arquivo está na máquina.
"""

from __future__ import annotations

import re
from pathlib import Path

PERFIS = ("muito_agressivo", "agressivo", "moderado", "conservador", "muito_conservador")

Faixa = tuple[float | None, float | None]

# nome: (faixas por perfil, (abaixo até, dentro até))
PRODUTOS: dict[str, tuple[tuple[Faixa, ...], tuple[float, float]]] = {
    "Lubrificante": (((None, -6.5), (-6.5, -5.25), (-5.25, -4.25), (-4.25, -3.25), (-3.25, -2.25)), (9.7, 11.6)),
    "Amortecedor Suspensão": (((None, -9.5), (-9.5, -7.9), (-7.9, -6.7), (-6.7, -5.7), (-5.7, -4.5)), (5.9, 6.9)),
    "Kit Embreagem": (((None, -9.85), (-9.85, -8.0), (-8.0, -6.95), (-6.95, -5.9), (-5.9, -4.75)), (4.1, 4.7)),
    "Kit Amortecedor": (((None, -2.7), (-2.7, -0.5), (-0.5, 1.0), (1.0, 2.3), (2.3, 3.3)), (3.3, 4.0)),
    "Vela Ignição": (((None, -6.0), (-6.0, -4.5), (-4.5, -3.5), (-3.5, -2.8), (-2.8, -2.0)), (2.6, 3.0)),
    "Bateria": (((None, -6.0), (-6.0, -4.5), (-4.5, -3.5), (-3.5, -2.8), (-2.8, -2.0)), (2.1, 2.6)),
    "Pastilha Freio": (((None, -2.5), (-2.5, -1.5), (-1.5, 2.0), (2.0, 3.8), (3.8, 4.9)), (1.9, 2.4)),
    "Cabo Vela": (((None, -9.5), (-9.5, -8.0), (-8.0, -6.5), (-6.5, -5.0), (-5.0, -3.5)), (1.6, 2.1)),
    "Tensor": (((None, -2.5), (-2.5, -1.25), (-1.25, 0.0), (0.0, 1.8), (1.8, 2.9)), (1.6, 2.1)),
    "Radiador": (((None, -3.5), (-3.5, -2.3), (-2.3, -1.2), (-1.2, 0.5), (0.5, 1.8)), (1.5, 1.9)),
    "Bobina Ignição": (((None, -3.5), (-3.5, -2.3), (-2.3, -1.2), (-1.2, 0.5), (0.5, 1.8)), (1.4, 1.8)),
    "Bandeja": (((None, -2.7), (-2.7, -0.5), (-0.5, 1.0), (1.0, 2.3), (2.3, 3.3)), (1.3, 1.7)),
    "Coxim Motor": (((None, -1.0), (-1.0, 1.5), (1.5, 3.0), (3.0, 5.0), (5.0, 6.7)), (1.25, 1.65)),
    "Aditivo": (((None, -2.7), (-2.7, -0.5), (-0.5, 1.0), (1.0, 2.3), (2.3, 3.3)), (1.2, 1.6)),
    "Ponta Homocinética": (((None, -2.5), (-2.5, -1.25), (-1.25, 0.0), (0.0, 1.8), (1.8, 2.9)), (1.05, 1.45)),
    "Disco Freio": (((None, -3.5), (-3.5, -2.0), (-2.0, -0.9), (-0.9, 1.5), (1.5, 2.8)), (1.05, 1.45)),
    "Bomba D Água": (((None, -2.5), (-2.5, -1.5), (-1.5, 2.0), (2.0, 3.8), (3.8, 4.9)), (1.0, 1.4)),
    "Kit Corrêia Dentada": (((None, -2.5), (-2.5, -1.25), (-1.25, 0.0), (0.0, 1.8), (1.8, 2.9)), (0.85, 1.25)),
    "Corrêia Dentada": (((None, -2.5), (-2.5, -1.25), (-1.25, 0.0), (0.0, 1.8), (1.8, 2.9)), (0.8, 1.2)),
    "Bucha Borracha": (((None, 6.0), (6.0, 7.5), (7.5, 8.8), (8.8, 10.0), (10.0, 12.0)), (0.65, 1.1)),
    "Mola Suspensão": (((None, -2.7), (-2.7, -0.5), (-0.5, 1.0), (1.0, 2.3), (2.3, 3.3)), (0.65, 1.1)),
    "Pivô Suspensão": (((None, 1.5), (1.5, 3.0), (3.0, 4.3), (4.3, 5.7), (5.7, 6.5)), (0.65, 1.1)),
    "Filtro Lubrificante": (((None, 2.8), (2.8, 3.9), (3.9, 5.3), (5.3, 6.7), (6.7, 7.8)), (0.65, 1.1)),
    "Bieleta": (((None, 2.8), (2.8, 3.9), (3.9, 5.3), (5.3, 6.7), (6.7, 7.8)), (0.6, 1.05)),
    "Rolamento Roda": (((None, -2.5), (-2.5, -1.25), (-1.25, 0.0), (0.0, 1.8), (1.8, 2.9)), (0.55, 1.0)),
    "Filtro Ar": (((None, 5.0), (5.0, 6.3), (6.3, 7.5), (7.5, 8.5), (8.5, 10.0)), (0.55, 1.0)),
    "Cubo Roda": (((None, -2.7), (-2.7, -0.5), (-0.5, 1.0), (1.0, 2.3), (2.3, 3.3)), (0.45, 0.95)),
    "Caixa Direção Mecânica": (((None, -5.5), (-5.5, -4.0), (-4.0, -2.9), (-2.9, -0.5), (-0.5, 0.8)), (0.45, 0.95)),
    "Corrêia": (((None, 2.8), (2.8, 3.9), (3.9, 5.3), (5.3, 6.7), (6.7, 7.8)), (0.4, 0.9)),
    "Mangueira": (((None, 9.0), (9.0, 10.5), (10.5, 11.8), (11.8, 13.0), (13.0, 15.0)), (0.4, 0.9)),
    "Reservatório": (((None, 1.5), (1.5, 3.0), (3.0, 4.3), (4.3, 5.7), (5.7, 6.5)), (0.4, 0.8)),
    "Bico Injetor": (((None, -1.5), (-1.5, -0.5), (-0.5, 2.8), (2.8, 4.2), (4.2, 6.0)), (0.4, 0.8)),
    "Motor Partida": (((None, -2.7), (-2.7, -0.5), (-0.5, 1.0), (1.0, 2.3), (2.3, 3.3)), (0.4, 0.75)),
    "Válvula Termostática": (((None, 1.5), (1.5, 3.0), (3.0, 4.3), (4.3, 5.7), (5.7, 6.5)), (0.4, 0.7)),
    "Retentor": (((None, 0.5), (0.5, 2.5), (2.5, 3.8), (3.8, 5.2), (5.2, 6.7)), (0.4, 0.7)),
    "Bomba Óleo": (((None, -3.5), (-3.5, -2.3), (-2.3, -1.2), (-1.2, 0.5), (0.5, 1.8)), (0.4, 0.7)),
}


def _numeros(texto: str) -> list[float]:
    # A planilha mistura "- 9,50%", "-5.25%" e "10,00 a 12,00%".
    limpo = str(texto).replace("- ", "-").replace(" ", "")
    return [float(n.replace(",", ".")) for n in re.findall(r"-?\d+(?:[.,]\d+)?", limpo)]


def _faixa(texto: str) -> Faixa:
    numeros = _numeros(texto)
    inicio = str(texto).strip().lower()
    if inicio.startswith("até"):
        return (None, numeros[0])
    if inicio.startswith("acima"):
        return (numeros[0], None)
    return (numeros[0], numeros[1])


def ler_planilha(caminho: Path) -> dict[str, tuple[tuple[Faixa, ...], tuple[float, float]]]:
    """Lê a aba "Lógica" (linhas 4–39: descrição em B, faixas MC em F–J,
    participação em K–M) no formato de `PRODUTOS`."""
    import openpyxl

    planilha = openpyxl.load_workbook(caminho, data_only=True, read_only=True)["Lógica"]
    produtos = {}
    for linha in planilha.iter_rows(min_row=4, max_row=39, min_col=2, max_col=13, values_only=True):
        nome = linha[0]
        if not nome:
            continue
        faixas = tuple(_faixa(t) for t in linha[4:9])
        abaixo, dentro, _acima = (_faixa(t) for t in linha[9:12])
        produtos[str(nome).strip()] = (faixas, (abaixo[1], dentro[1]))
    return produtos
