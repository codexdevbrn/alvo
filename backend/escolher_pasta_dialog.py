"""
Diálogo nativo de pasta (tkinter), pensado para rodar em processo próprio.

Chamado pelo backend via subprocess para evitar Tcl/Tk no threadpool do
uvicorn (causa comum de 500 / crash do worker no Windows).
"""

from __future__ import annotations

import sys
from typing import Optional


class ErroDialogoPasta(Exception):
    """Falha ao abrir o diálogo nativo (tkinter / Tcl)."""

    def __init__(self, codigo: int, mensagem: str):
        super().__init__(mensagem)
        self.codigo = codigo
        self.mensagem = mensagem


def escolher_pasta(titulo: str = "Selecionar pasta") -> Optional[str]:
    try:
        import tkinter as tk
        from tkinter import filedialog
    except ImportError as exc:
        raise ErroDialogoPasta(2, f"tkinter indisponível: {exc}") from exc

    root = None
    try:
        root = tk.Tk()
        root.withdraw()
        try:
            root.attributes("-topmost", True)
        except tk.TclError:
            pass
        try:
            root.update_idletasks()
        except tk.TclError:
            pass
        escolhido = filedialog.askdirectory(
            title=titulo or "Selecionar pasta",
            mustexist=True,
            parent=root,
        )
        return escolhido if escolhido else None
    except ErroDialogoPasta:
        raise
    except Exception as exc:
        raise ErroDialogoPasta(3, str(exc)) from exc
    finally:
        if root is not None:
            try:
                root.quit()
            except Exception:
                pass
            try:
                root.destroy()
            except Exception:
                pass


if __name__ == "__main__":
    titulo_arg = sys.argv[1] if len(sys.argv) > 1 else "Selecionar pasta"
    try:
        caminho = escolher_pasta(titulo_arg)
    except ErroDialogoPasta as exc:
        prefix = "ERR_IMPORT:" if exc.codigo == 2 else "ERR_DIALOG:"
        print(f"{prefix}{exc.mensagem}", file=sys.stderr)
        sys.exit(exc.codigo)
    # stdout só o caminho (UTF-8); vazio = cancelado
    sys.stdout.buffer.write((caminho or "").encode("utf-8"))
    sys.exit(0)
