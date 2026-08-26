"""Contrato do catálogo global e das marcações de tags por loja."""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import main


def test_catalogo_global_aparece_e_valida_tag_no_escopo_da_loja(tmp_path, monkeypatch):
    """Tag criada em Configurações fica disponível ao editar cliente de uma loja."""
    monkeypatch.setattr(main, "_exigir_caminho_trabalho", lambda: str(tmp_path))

    main._gravar_catalogo_tags(
        "Empresa Teste",
        [{
            "id": "vip",
            "rotulo": "VIP",
            "ativa": True,
            "entra_na_analise": False,
            "cor": "#123456",
        }],
    )

    estado = main._ler_tags_clientes("Empresa Teste", loja="Matriz")
    vip = next(tag for tag in estado["catalogo"] if tag["id"] == "vip")
    assert vip["entra_na_analise"] is False

    salvo = main._gravar_tags_clientes(
        "Empresa Teste", {"Cliente A": ["vip"]}, loja="Matriz",
    )
    assert salvo["tags"] == {"Cliente A": ["vip"]}
