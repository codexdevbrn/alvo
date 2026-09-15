import { MESES_VENDA_MEDIA, type MesesVendaMedia } from '../utils/vendaMedia';
import { useVendaMedia } from '../hooks/useVendaMedia';
import { AnalisadorCombobox } from './analisador/AnalisadorCombobox';

const ROTULO: Record<MesesVendaMedia, string> = {
  3: 'Últimos 3 meses',
  6: 'Últimos 6 meses',
  12: 'Últimos 12 meses',
};

const ROTULOS = MESES_VENDA_MEDIA.map((valor) => ROTULO[valor]);

function mesesPorRotulo(rotulo: string): MesesVendaMedia {
  const valor = MESES_VENDA_MEDIA.find((m) => ROTULO[m] === rotulo);
  return valor ?? MESES_VENDA_MEDIA[0];
}

/** Combobox de venda média no `app-shell-topo`, só no Estoque. */
export function TopoVendaMediaSelect() {
  const [meses, setMeses] = useVendaMedia();

  return (
    <div className="app-sidebar-empresa">
      <span className="app-sidebar-nav-label">Venda média</span>
      <AnalisadorCombobox
        value={ROTULO[meses]}
        options={ROTULOS}
        onChange={(rotulo) => setMeses(mesesPorRotulo(rotulo))}
        emptyLabel={false}
        searchPlaceholder={false}
        aria-label="Janela da venda média"
        direcao="abaixo"
        portal
      />
    </div>
  );
}
