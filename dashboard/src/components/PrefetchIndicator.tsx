import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Loader2, CheckCircle2, Circle } from 'lucide-react';
import {
  EVENTO_PREFETCH,
  type EstadoPrefetch,
  obterEstadoPrefetch,
  estaPrefetchVisivel,
  obterTempoConclusaoPrefetch,
} from '../utils/prefetchSequencial';

const ROTA_ETAPA: Record<string, string> = {
  Dashboard: '/',
  'Clientes: Visão geral': '/clientes',
  'Clientes: Base e tags': '/clientes',
  Vendedores: '/vendedores',
  Estoque: '/estoque',
  Despesas: '/despesas',
  Monitoramento: '/monitor',
};

export function PrefetchIndicator() {
  const navigate = useNavigate();
  const [estado, setEstado] = useState<EstadoPrefetch>(obterEstadoPrefetch);
  const [visivel, setVisivel] = useState<boolean>(estaPrefetchVisivel);

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

    // Se montou enquanto já estava concluído, programa o fechamento com o tempo restante
    if (!estado.rodando && estado.nome === 'Concluído') {
      const decorrido = Date.now() - obterTempoConclusaoPrefetch();
      const restante = Math.max(0, 3000 - decorrido);
      if (restante > 0) {
        setVisivel(true);
        timeoutId = window.setTimeout(() => setVisivel(false), restante);
      } else {
        setVisivel(false);
      }
    } else if (estado.rodando) {
      setVisivel(true);
    }

    window.addEventListener(EVENTO_PREFETCH, aoMudar);
    return () => {
      window.removeEventListener(EVENTO_PREFETCH, aoMudar);
      window.clearTimeout(timeoutId);
    };
  }, []);

  if (!visivel || !estado || (!estado.rodando && estado.nome !== 'Concluído')) return null;

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
      {estado.etapas.length > 0 && (
        <ul className="prefetch-etapas-lista">
          {estado.etapas.map((etapa, i) => {
            const status = i < estado.atual || finalizado ? 'feita' : i === estado.atual && estado.rodando ? 'atual' : 'pendente';
            const rota = ROTA_ETAPA[etapa];
            return (
              <li key={etapa} className={`prefetch-etapa prefetch-etapa-${status}`}>
                {status === 'feita' ? (
                  <CheckCircle2 size={12} className="prefetch-icon-success" />
                ) : status === 'atual' ? (
                  <Loader2 size={12} className="prefetch-icon-spin" />
                ) : (
                  <Circle size={12} className="prefetch-icon-pendente" />
                )}
                {rota ? (
                  <button type="button" className="prefetch-etapa-link" onClick={() => navigate(rota)}>
                    {etapa}
                  </button>
                ) : (
                  <span>{etapa}</span>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
