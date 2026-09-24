import { useItensPrecificacao } from '../hooks/useItensPrecificacao';
import type { ItensPrecificacao } from '../utils/itensPrecificacao';

const OPCOES: Array<{ valor: ItensPrecificacao; rotulo: string; titulo: string }> = [
  { valor: 'todos', rotulo: 'Todos', titulo: 'Loja inteira — o que ficou fora da rodada aparece como "não precificado"' },
  { valor: 'precificados', rotulo: 'Precificados', titulo: 'Só os pares família × fabricante que entraram na rodada' },
];

/** Só aparece na tela Pós precificação (AppShell filtra por rota). */
export function TopoPosPrecificacaoItensToggle() {
  const [itens, setItens] = useItensPrecificacao();

  return (
    <div className="app-sidebar-empresa">
      <span className="app-sidebar-nav-label">Itens</span>
      <div className="periodo-segmented" role="radiogroup" aria-label="Itens considerados">
        {OPCOES.map((opcao) => (
          <button
            key={opcao.valor}
            type="button"
            role="radio"
            aria-checked={itens === opcao.valor}
            title={opcao.titulo}
            className={`periodo-segmented-btn${itens === opcao.valor ? ' is-active' : ''}`}
            onClick={() => setItens(opcao.valor)}
          >
            {opcao.rotulo}
          </button>
        ))}
      </div>
    </div>
  );
}
