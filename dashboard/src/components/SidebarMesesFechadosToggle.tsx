import { useMesesFechados } from '../hooks/useMesesFechados';
import type { ModoPeriodo } from '../utils/mesesFechados';

const OPCOES: Array<{ valor: ModoPeriodo; rotulo: string; titulo: string }> = [
  { valor: 'fechados', rotulo: 'Fechados', titulo: 'Meses fechados — mês corrente em aberto fica fora dos cálculos' },
  { valor: 'completo', rotulo: 'Completo', titulo: 'Completo — inclui o mês corrente inteiro, mesmo em aberto' },
  { valor: 'mesmo_periodo', rotulo: 'Mesmo período', titulo: 'Mesmo período — compara só até o dia que o mês corrente já tem' },
];

interface SidebarMesesFechadosToggleProps {
  /** Dashboard e Estoque não comparam "1 mês vs média histórica" — não há
   *  corte por dia pra aplicar, então essa opção não se aplica a elas. */
  desabilitarMesmoPeriodo?: boolean;
}

/**
 * Controle global de período dos cálculos, na sidebar — vale para Dashboard,
 * Clientes, Vendedores e Estoque. Segmentado compacto (3 pílulas numa barra só),
 * menor que os combobox de Empresa/Loja — não é uma lista de opções que cresce,
 * então não precisa do mesmo padrão de dropdown.
 */
export function SidebarMesesFechadosToggle({ desabilitarMesmoPeriodo }: SidebarMesesFechadosToggleProps) {
  const [modoPeriodo, setModoPeriodo] = useMesesFechados();
  const opcoes = desabilitarMesmoPeriodo
    ? OPCOES.filter((opcao) => opcao.valor !== 'mesmo_periodo')
    : OPCOES;
  // Nas telas sem "mesmo período", o modo global equivalente é "completo"
  // (mesmo comportamento que `modoParaBooleano` já aplica no cálculo).
  const modoExibido = desabilitarMesmoPeriodo && modoPeriodo === 'mesmo_periodo' ? 'completo' : modoPeriodo;

  return (
    <div className="app-sidebar-empresa">
      <span className="app-sidebar-nav-label">Período</span>
      <div className="periodo-segmented" role="radiogroup" aria-label="Período usado nos cálculos">
        {opcoes.map((opcao) => (
          <button
            key={opcao.valor}
            type="button"
            role="radio"
            aria-checked={modoExibido === opcao.valor}
            title={opcao.titulo}
            className={`periodo-segmented-btn${modoExibido === opcao.valor ? ' is-active' : ''}`}
            onClick={() => setModoPeriodo(opcao.valor)}
          >
            {opcao.rotulo}
          </button>
        ))}
      </div>
    </div>
  );
}
