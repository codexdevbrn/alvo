import { ArrowDownRight, ArrowUpRight, CalendarRange, Crosshair, TrendingDown } from 'lucide-react';
import { StatCard } from '../StatCard';
import type { TensaoDiagnostico } from '../../api/client';
import { formatCompacto, formatCurrency, formatNumber, formatPercent } from '../../utils/formatters';

interface Props {
  tensao: TensaoDiagnostico;
  rotuloPeriodo: string | null;
}

/** ATO I: abre a tela com o movimento do mês e o quanto dele está concentrado.
 *
 *  Não mostra "receita sob risco" de propósito — ver `painel_diagnostico._tensao`:
 *  nesta base a compra é intermitente, então somar quedas individuais conta como
 *  churn quem só não voltou ainda. O que abre a tela é o que aconteceu.
 *
 *  O par mês/ano é a leitura central: queda contra o mês anterior com estabilidade
 *  contra o ano passado é sazonalidade, não deterioração — e a conclusão vai no
 *  texto, não na cabeça de quem lê. */
export function TensaoHero({ tensao, rotuloPeriodo }: Props) {
  const variacaoMes = tensao.variacao_pct;
  const variacaoAno = tensao.variacao_ano_pct;
  const caiuNoMes = (variacaoMes ?? 0) < 0;
  const estavelNoAno = variacaoAno != null && Math.abs(variacaoAno) < 5;
  // O delta, não a receita de referência: "R$ 7,4 M" com seta para baixo lê como
  // "caiu 7,4 milhões", quando 7,4 M é o mês inteiro contra o qual comparamos.
  const deltaAno = tensao.receita_ano_anterior == null || tensao.receita_periodo == null
    ? null
    : tensao.receita_periodo - tensao.receita_ano_anterior;
  const notaDelta = (delta: number | null, referencia: string | null) =>
    delta == null
      ? '—'
      : `${delta < 0 ? '−' : '+'}${formatCompacto(Math.abs(delta), true)} vs ${referencia}`;

  const leitura = variacaoMes == null || variacaoAno == null
    ? null
    : caiuNoMes && estavelNoAno
      ? `Queda contra ${tensao.rotulo_anterior}, mas estável contra ${tensao.rotulo_ano_anterior} — o padrão é sazonal, não deterioração.`
      : caiuNoMes && variacaoAno < 0
        ? `Cai contra ${tensao.rotulo_anterior} e contra ${tensao.rotulo_ano_anterior} — a queda não é do mês, é do ano.`
        : `Cresce contra ${tensao.rotulo_ano_anterior}.`;

  return (
    <section className="diagnostico-tensao" aria-label="Movimento do período">
      <article className="glass-card glass-card-flat vendedores-hero">
        <p className="despesas-hero-rotulo">
          <CalendarRange size={14} aria-hidden="true" /> Receita de {rotuloPeriodo}
        </p>
        <strong className="despesas-hero-valor">{formatCurrency(tensao.receita_periodo ?? 0)}</strong>
        <p className={`despesas-hero-nota ${caiuNoMes ? 'is-queda' : 'is-alta'}`}>
          {caiuNoMes
            ? <ArrowDownRight size={14} aria-hidden="true" />
            : <ArrowUpRight size={14} aria-hidden="true" />}
          {formatCurrency(Math.abs(tensao.delta_receita ?? 0))} {caiuNoMes ? 'a menos' : 'a mais'} que {tensao.rotulo_anterior}
        </p>
      </article>

      <div className="vendedores-kpis-secundarios">
        <StatCard
          title={`vs. ${tensao.rotulo_anterior ?? 'mês anterior'}`}
          value={variacaoMes == null ? '—' : formatPercent(variacaoMes, 1)}
          icon={caiuNoMes ? ArrowDownRight : ArrowUpRight}
          useTrendColor
          trendUp={!caiuNoMes}
          trend={notaDelta(tensao.delta_receita ?? null, tensao.rotulo_anterior)}
        />
        <StatCard
          title={`vs. ${tensao.rotulo_ano_anterior ?? 'ano anterior'}`}
          value={variacaoAno == null ? '—' : formatPercent(variacaoAno, 1)}
          icon={(variacaoAno ?? 0) < 0 ? ArrowDownRight : ArrowUpRight}
          useTrendColor
          trendUp={(variacaoAno ?? 0) >= 0}
          trend={notaDelta(deltaAno, tensao.rotulo_ano_anterior)}
        />
        <StatCard
          title="Concentração"
          value={tensao.concentracao_queda_pct == null ? '—' : formatPercent(tensao.concentracao_queda_pct, 0)}
          icon={Crosshair}
          trend={`da queda nos ${tensao.topo_concentracao} produtos que mais caíram`}
        />
        <StatCard
          title="Produtos em queda"
          value={formatNumber(tensao.produtos_em_queda)}
          icon={TrendingDown}
          trend={`contra ${tensao.rotulo_anterior ?? 'o mês anterior'}`}
        />
      </div>

      {leitura && <p className="diagnostico-leitura">{leitura}</p>}
    </section>
  );
}
