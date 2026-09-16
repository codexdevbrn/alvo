import { useModoGraficoPrecificacao } from '../hooks/useModoGraficoPrecificacao';
import type { ModoGraficoPrecificacao } from '../utils/modoGraficoPrecificacao';

const OPCOES: Array<{ valor: ModoGraficoPrecificacao; rotulo: string; titulo: string }> = [
  { valor: 'sintetica', rotulo: 'Sintética', titulo: 'Série mensal, antes e depois da precificação' },
  { valor: 'detalhada', rotulo: 'Detalhada', titulo: 'Dia a dia, zoom no entorno da data de precificação' },
];

/** Só aparece na tela Pós precificação (AppShell filtra por rota). */
export function TopoPosPrecificacaoModoToggle() {
  const [modo, setModo] = useModoGraficoPrecificacao();

  return (
    <div className="app-sidebar-empresa">
      <span className="app-sidebar-nav-label">Visão</span>
      <div className="periodo-segmented" role="radiogroup" aria-label="Detalhe do gráfico">
        {OPCOES.map((opcao) => (
          <button
            key={opcao.valor}
            type="button"
            role="radio"
            aria-checked={modo === opcao.valor}
            title={opcao.titulo}
            className={`periodo-segmented-btn${modo === opcao.valor ? ' is-active' : ''}`}
            onClick={() => setModo(opcao.valor)}
          >
            {opcao.rotulo}
          </button>
        ))}
      </div>
    </div>
  );
}
