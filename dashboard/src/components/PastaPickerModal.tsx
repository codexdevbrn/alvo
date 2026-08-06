import { useCallback, useEffect, useState } from 'react';
import { ArrowUp, Folder, HardDrive, Loader2, X } from 'lucide-react';
import { listarPastas, type PastaItem } from '../api/client';

interface PastaPickerModalProps {
  aberto: boolean;
  titulo: string;
  /** Caminho atual do campo; abre a navegação já nele (ou no pai, se for arquivo inexistente). */
  caminhoInicial?: string;
  /** true = usa as rotas autenticadas do Analisador. */
  auth?: boolean;
  onCancelar: () => void;
  onEscolher: (caminho: string) => void;
}

/**
 * Navegador de pastas do **servidor**. O backend roda como serviço do Windows
 * (sem sessão gráfica) e é acessado pelo navegador, às vezes de outra máquina —
 * diálogo nativo não funciona nesse cenário, então a navegação é feita aqui.
 */
export function PastaPickerModal({
  aberto,
  titulo,
  caminhoInicial,
  auth = false,
  onCancelar,
  onEscolher,
}: PastaPickerModalProps) {
  const [caminho, setCaminho] = useState<string | null>(null);
  const [pai, setPai] = useState<string | null>(null);
  const [pastas, setPastas] = useState<PastaItem[]>([]);
  const [carregando, setCarregando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);
  const [digitado, setDigitado] = useState('');

  const navegar = useCallback(
    async (destino: string | null, comFallback = false) => {
      setCarregando(true);
      setErro(null);
      try {
        const dados = await listarPastas(destino, auth);
        setCaminho(dados.caminho);
        setPai(dados.pai);
        setPastas(dados.pastas);
        setDigitado(dados.caminho ?? '');
      } catch (e) {
        const msg = e instanceof Error ? e.message : 'Falha ao listar pastas.';
        if (comFallback) {
          // Caminho salvo pode não existir mais: cai nas raízes em vez de travar.
          await navegar(null);
          setErro(msg);
          return;
        }
        setErro(msg);
      } finally {
        setCarregando(false);
      }
    },
    [auth],
  );

  useEffect(() => {
    if (!aberto) return;
    const inicial = (caminhoInicial || '').trim();
    void navegar(inicial || null, Boolean(inicial));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [aberto]);

  useEffect(() => {
    if (!aberto) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onCancelar();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [aberto, onCancelar]);

  if (!aberto) return null;

  const naRaiz = caminho === null;

  return (
    <div className="config-modal-overlay" onClick={onCancelar} role="presentation">
      <div
        className="config-modal pasta-picker-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="pasta-picker-titulo"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="config-modal-header">
          <h2 id="pasta-picker-titulo">{titulo}</h2>
          <button
            type="button"
            className="analisador-btn analisador-btn-sec"
            onClick={onCancelar}
            aria-label="Fechar"
          >
            <X size={16} />
          </button>
        </header>

        <div className="pasta-picker-barra">
          <button
            type="button"
            className="analisador-btn analisador-btn-sec"
            onClick={() => void navegar(pai)}
            disabled={carregando || naRaiz}
            aria-label="Pasta acima"
            title="Pasta acima"
          >
            <ArrowUp size={16} />
          </button>
          <form
            className="pasta-picker-form"
            onSubmit={(e) => {
              e.preventDefault();
              void navegar(digitado.trim() || null);
            }}
          >
            <input
              className="analisador-input"
              value={digitado}
              onChange={(e) => setDigitado(e.target.value)}
              placeholder="Digite ou cole um caminho e pressione Enter"
              spellCheck={false}
              aria-label="Caminho"
            />
          </form>
        </div>

        <div className="config-modal-body custom-scrollbar pasta-picker-body">
          {erro && <p className="analisador-erro">{erro}</p>}
          {carregando ? (
            <p className="analisador-hint pasta-picker-status">
              <Loader2 size={14} className="dashboard-filter-spinner" /> Carregando...
            </p>
          ) : pastas.length === 0 ? (
            <p className="analisador-hint pasta-picker-status">Nenhuma subpasta aqui.</p>
          ) : (
            <ul className="pasta-picker-lista">
              {pastas.map((p) => (
                <li key={p.caminho}>
                  <button type="button" onClick={() => void navegar(p.caminho)}>
                    {naRaiz ? <HardDrive size={15} /> : <Folder size={15} />}
                    <span>{p.nome}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>

        <footer className="config-modal-footer">
          <span className="pasta-picker-atual" title={caminho ?? undefined}>
            {caminho ?? 'Unidades do servidor'}
          </span>
          <button type="button" className="analisador-btn analisador-btn-sec" onClick={onCancelar}>
            Cancelar
          </button>
          <button
            type="button"
            className="analisador-btn analisador-btn-pri"
            onClick={() => caminho && onEscolher(caminho)}
            disabled={carregando || naRaiz}
          >
            Usar esta pasta
          </button>
        </footer>
      </div>
    </div>
  );
}
