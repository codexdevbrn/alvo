import { Activity, ShieldAlert, TrendingDown } from 'lucide-react';
import { StatCard } from '../StatCard';
import type { ImpactoChurnDiagnostico } from '../../api/client';
import { formatCompacto, formatPercent } from '../../utils/formatters';
import { TituloDiagnostico } from './TituloDiagnostico';

interface Props {
  impacto: ImpactoChurnDiagnostico;
}

/** Ponte entre o mecanismo (Ato II) e a pauta (Ato III): o número que a Tensão
 *  deixa de fora de propósito (ver `TensaoHero`) porque a base tem compra
 *  intermitente — somar toda queda individual superestimaria quem só ainda
 *  não voltou a comprar. Aqui ele aparece, mas rotulado como exposição, não
 *  perda confirmada — a tela que segue (Risco, Matriz de Erosão) mostra quem
 *  compõe esse número. */
export function ImpactoChurn({ impacto }: Props) {
  const semDado = impacto.receita_sob_risco == null && impacto.maior_retracao_pct == null;
  if (semDado) return null;

  return (
    <section className="glass-card glass-card-flat clientes-visao-card" aria-label="Exposição a churn">
      <header className="clientes-visao-card-topo">
        <div>
          <TituloDiagnostico texto="Exposição a churn" variante="queda" />
          <p>
            Soma de toda queda cliente × produto no período — é o teto do risco, não a perda
            confirmada: parte pode voltar no próximo mês (padrão de compra intermitente).
          </p>
        </div>
      </header>

      <div className="vendedores-kpis-secundarios">
        <StatCard
          title="Receita sob risco"
          value={impacto.receita_sob_risco == null ? '—' : formatCompacto(impacto.receita_sob_risco, true)}
          icon={ShieldAlert}
          trend="soma das quedas cliente × produto"
        />
        <StatCard
          title="Maior retração individual"
          value={impacto.maior_retracao_pct == null ? '—' : formatPercent(impacto.maior_retracao_pct, 0)}
          icon={TrendingDown}
          trend="pior caso entre os eventos de erosão"
        />
        <StatCard
          title="Variação global do período"
          value={impacto.variacao_global_pct == null ? '—' : formatPercent(impacto.variacao_global_pct, 1)}
          icon={Activity}
          useTrendColor
          trendUp={(impacto.variacao_global_pct ?? 0) >= 0}
          trend="mesmo número da Tensão, para contexto"
        />
      </div>
    </section>
  );
}
