import { MESES_VENDA_MEDIA, type MesesVendaMedia } from '../utils/vendaMedia';
import { useVendaMedia } from '../hooks/useVendaMedia';

const ROTULO: Record<MesesVendaMedia, string> = {
  3: 'Últimos 3 meses',
  6: 'Últimos 6 meses',
  12: 'Últimos 12 meses',
};

/** Select de venda média no `app-shell-topo`, só no Estoque. */
export function TopoVendaMediaSelect() {
  const [meses, setMeses] = useVendaMedia();

  return (
    <div className="app-sidebar-empresa">
      <span className="app-sidebar-nav-label">Venda média</span>
      <select
        className="custom-select analisador-select"
        value={meses}
        aria-label="Janela da venda média"
        onChange={(e) => setMeses(Number(e.target.value) as MesesVendaMedia)}
      >
        {MESES_VENDA_MEDIA.map((valor) => (
          <option key={valor} value={valor}>{ROTULO[valor]}</option>
        ))}
      </select>
    </div>
  );
}
