import { MESES_DESPESAS_PERIODO, type MesesDespesasPeriodo } from '../utils/despesasPeriodo';
import { useDespesasPeriodo } from '../hooks/useDespesasPeriodo';
import { AnalisadorCombobox } from './analisador/AnalisadorCombobox';

const ROTULO: Record<MesesDespesasPeriodo, string> = {
  6: 'Últimos 6 meses',
  12: 'Últimos 12 meses',
  24: 'Últimos 24 meses',
};

const ROTULOS = MESES_DESPESAS_PERIODO.map((valor) => ROTULO[valor]);

function mesesPorRotulo(rotulo: string): MesesDespesasPeriodo {
  const valor = MESES_DESPESAS_PERIODO.find((m) => ROTULO[m] === rotulo);
  return valor ?? MESES_DESPESAS_PERIODO[0];
}

/** Combobox de janela das Despesas no `app-shell-topo`, só em Despesas. */
export function TopoDespesasPeriodoSelect() {
  const [meses, setMeses] = useDespesasPeriodo();

  return (
    <div className="app-sidebar-empresa">
      <span className="app-sidebar-nav-label">Janela</span>
      <AnalisadorCombobox
        value={ROTULO[meses]}
        options={ROTULOS}
        onChange={(rotulo) => setMeses(mesesPorRotulo(rotulo))}
        emptyLabel={false}
        searchPlaceholder={false}
        aria-label="Janela de meses das despesas"
        direcao="abaixo"
        portal
      />
    </div>
  );
}
