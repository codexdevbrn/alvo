import { useEffect, useState } from 'react';
import { FileCode2, FileSpreadsheet, FileText, X } from 'lucide-react';

import type { FormatoExportacao } from '../../api/client';

export interface RelatorioExportavel {
  chave: string;
  rotulo: string;
}

interface ExportarModalProps {
  aberto: boolean;
  formato: FormatoExportacao | null;
  relatorios: RelatorioExportavel[];
  carregando: boolean;
  onCancelar: () => void;
  onConfirmar: (chavesSelecionadas: string[]) => void;
}

export function ExportarModal({ aberto, formato, relatorios, carregando, onCancelar, onConfirmar }: ExportarModalProps) {
  const [selecionados, setSelecionados] = useState<Set<string>>(new Set());

  useEffect(() => {
    if (aberto) setSelecionados(new Set(relatorios.map((r) => r.chave)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [aberto]);

  if (!aberto || !formato) return null;

  const rotuloFormato = formato === 'excel' ? 'Excel' : formato === 'pdf' ? 'PDF' : 'HTML';
  const IconeFormato = formato === 'excel' ? FileSpreadsheet : formato === 'pdf' ? FileText : FileCode2;
  const todosMarcados = relatorios.length > 0 && selecionados.size === relatorios.length;

  const alternar = (chave: string) => {
    setSelecionados((prev) => {
      const novo = new Set(prev);
      if (novo.has(chave)) novo.delete(chave);
      else novo.add(chave);
      return novo;
    });
  };

  return (
    <div className="config-modal-overlay" onClick={onCancelar} role="presentation">
      <div
        className="config-modal exportar-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="exportar-modal-titulo"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="config-modal-header">
          <h2 id="exportar-modal-titulo">Confirmar exportação em {rotuloFormato}</h2>
          <button type="button" className="analisador-btn analisador-btn-sec" onClick={onCancelar} aria-label="Fechar">
            <X size={16} />
          </button>
        </header>

        <div className="config-modal-body custom-scrollbar">
          <div className="exportar-modal-cabecalho">
            <p className="analisador-hint">
              Escolha quais relatórios gerados devem entrar no arquivo:
            </p>
            <button
              type="button"
              className="analisador-catalogo-toggle"
              onClick={() => setSelecionados(todosMarcados ? new Set() : new Set(relatorios.map((r) => r.chave)))}
            >
              {todosMarcados ? 'Desmarcar todos' : 'Marcar todos'}
            </button>
          </div>
          <ul className="exportar-modal-lista">
            {relatorios.map((r) => (
              <li key={r.chave}>
                <label className="analisador-check-linha exportar-modal-item">
                  <input
                    type="checkbox"
                    checked={selecionados.has(r.chave)}
                    onChange={() => alternar(r.chave)}
                  />
                  <IconeFormato size={15} />
                  <span>{r.rotulo}</span>
                </label>
              </li>
            ))}
          </ul>
        </div>

        <footer className="config-modal-footer">
          <span className="exportar-modal-contagem">
            {selecionados.size} de {relatorios.length} selecionado{relatorios.length === 1 ? '' : 's'}
          </span>
          <button type="button" className="analisador-btn analisador-btn-sec" onClick={onCancelar} disabled={carregando}>
            Cancelar
          </button>
          <button
            type="button"
            className="analisador-btn analisador-btn-pri"
            onClick={() => onConfirmar(Array.from(selecionados))}
            disabled={carregando || selecionados.size === 0}
          >
            {carregando ? 'Baixando...' : `Confirmar e baixar ${rotuloFormato}`}
          </button>
        </footer>
      </div>
    </div>
  );
}
