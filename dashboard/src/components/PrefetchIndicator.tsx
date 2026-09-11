import { useEffect, useState } from 'react';
import { Loader2, CheckCircle2 } from 'lucide-react';
import { EVENTO_PREFETCH, type EstadoPrefetch } from '../utils/prefetchSequencial';

export function PrefetchIndicator() {
  const [estado, setEstado] = useState<EstadoPrefetch | null>(null);
  const [visivel, setVisivel] = useState(false);

  useEffect(() => {
    let timeoutId: number;

    const aoMudar = (evento: Event) => {
      const novoEstado = (evento as CustomEvent<EstadoPrefetch>).detail;
      setEstado(novoEstado);

      if (novoEstado.rodando) {
        setVisivel(true);
        window.clearTimeout(timeoutId);
      } else if (novoEstado.nome === 'Concluído') {
        // Aguarda 3 segundos antes de sumir
        timeoutId = window.setTimeout(() => setVisivel(false), 3000);
      } else {
        setVisivel(false);
      }
    };

    window.addEventListener(EVENTO_PREFETCH, aoMudar);
    return () => {
      window.removeEventListener(EVENTO_PREFETCH, aoMudar);
      window.clearTimeout(timeoutId);
    };
  }, []);

  if (!visivel || !estado) return null;

  const progresso = estado.total > 0 ? (estado.atual / estado.total) * 100 : 0;
  const finalizado = !estado.rodando && estado.nome === 'Concluído';

  return (
    <div className={`prefetch-indicator ${finalizado ? 'is-finished' : ''}`}>
      <div className="prefetch-indicator-content">
        {finalizado ? (
          <CheckCircle2 size={16} className="prefetch-icon-success" />
        ) : (
          <Loader2 size={16} className="prefetch-icon-spin" />
        )}
        <span className="prefetch-text">
          {finalizado ? 'Tudo pronto!' : `Carregando: ${estado.nome}`}
        </span>
      </div>
      {!finalizado && (
        <div className="prefetch-progress-bar">
          <div 
            className="prefetch-progress-fill" 
            style={{ width: `${progresso}%` }} 
          />
        </div>
      )}
    </div>
  );
}
