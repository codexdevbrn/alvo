import { useEffect, useState } from 'react';
import { obterAplicarCortesRelatorios } from '../api/client';
import { EVENTO_CORTES_RELATORIOS } from '../utils/cortesRelatorios';
import { definirGruposClientesFiltro } from '../utils/gruposClientesFiltro';
import { useGruposClientesFiltro } from '../hooks/useGruposClientesFiltro';

const OPCOES: Array<{ valor: string; rotulo: string; titulo: string }> = [
  { valor: '1', rotulo: 'G1', titulo: 'Grupo 1' },
  { valor: '2', rotulo: 'G2', titulo: 'Grupo 2' },
  { valor: '3', rotulo: 'G3', titulo: 'Grupo 3' },
  { valor: 'X', rotulo: 'Demais', titulo: 'Demais' },
  { valor: 'B', rotulo: 'Balcão', titulo: 'Balcão' },
];

/**
 * Filtro global por grupo de clientes (Grupo 1/2/3, Demais, Balcão) — mesmos
 * grupos da tela Cortes. Seleção múltipla; nenhum marcado = sem filtro (todos).
 * Só existe com "Cortes: Com corte" ligado, porque sem ele nenhuma dessas
 * telas aplica corte algum, e o filtro ficaria sem efeito.
 */
export function TopoGruposClientesFiltro() {
  const [cortesAtivo, setCortesAtivo] = useState(false);
  const gruposSelecionados = useGruposClientesFiltro();

  useEffect(() => {
    void obterAplicarCortesRelatorios().then(setCortesAtivo).catch(() => setCortesAtivo(false));
    const sincronizar = (evento: Event) => {
      const detalhe = evento instanceof CustomEvent ? evento.detail : undefined;
      setCortesAtivo(Boolean(detalhe));
    };
    window.addEventListener(EVENTO_CORTES_RELATORIOS, sincronizar);
    return () => window.removeEventListener(EVENTO_CORTES_RELATORIOS, sincronizar);
  }, []);

  if (!cortesAtivo) return null;

  const alternar = (valor: string) => {
    const novo = gruposSelecionados.includes(valor)
      ? gruposSelecionados.filter((g) => g !== valor)
      : [...gruposSelecionados, valor];
    definirGruposClientesFiltro(novo);
  };

  return (
    <div className="app-sidebar-empresa">
      <span className="app-sidebar-nav-label">Grupos</span>
      <div
        className="periodo-segmented"
        role="group"
        aria-label="Filtrar por grupo de clientes (Grupo 1/2/3, Demais, Balcão)"
      >
        {OPCOES.map((opcao) => (
          <button
            key={opcao.valor}
            type="button"
            aria-pressed={gruposSelecionados.includes(opcao.valor)}
            title={opcao.titulo}
            className={`periodo-segmented-btn${gruposSelecionados.includes(opcao.valor) ? ' is-active' : ''}`}
            onClick={() => alternar(opcao.valor)}
          >
            {opcao.rotulo}
          </button>
        ))}
      </div>
    </div>
  );
}
