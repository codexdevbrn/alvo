import { ArrowDownRight, ArrowUpRight } from 'lucide-react';
import type { ProdutoRadarPercentual, RadarPercentualDiagnostico } from '../../api/client';
import { formatCurrency, formatPercent } from '../../utils/formatters';
import { TituloDiagnostico } from './TituloDiagnostico';

interface Props {
  radar: RadarPercentualDiagnostico;
}

function Coluna({ titulo, itens, variante }: { titulo: string; itens: ProdutoRadarPercentual[]; variante: 'alta' | 'queda' }) {
  if (itens.length === 0) {
    return (
      <div>
        <h3 className="diagnostico-radar-coluna-titulo">
          {variante === 'alta' ? <ArrowUpRight size={14} /> : <ArrowDownRight size={14} />} {titulo}
        </h3>
        <p className="analisador-hint">Nenhum sinal fora do que o Tornado já mostra.</p>
      </div>
    );
  }
  return (
    <div>
      <h3 className="diagnostico-radar-coluna-titulo">
        {variante === 'alta' ? <ArrowUpRight size={14} /> : <ArrowDownRight size={14} />} {titulo}
      </h3>
      <ul className="diagnostico-dumbbell-lista-legenda">
        {itens.map((item) => (
          <li key={item.descricao}>
            <div className="diagnostico-radar-linha-topo">
              <strong>{item.descricao}</strong>
              <span className={`diagnostico-titulo-pilula is-${variante}`}>
                {formatPercent(item.variacao_pct ?? 0, 0)}
              </span>
            </div>
            <p>{formatCurrency(item.receita_anterior ?? 0)} → {formatCurrency(item.receita_atual ?? 0)}</p>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** ATO II: complemento do Tornado, não substituto — mesmo docstring de
 *  `painel_diagnostico._radar_percentual`. O Tornado ranqueia por R$ e por
 *  isso é cego a um produto pequeno que ainda vai virar dinheiro; aqui o
 *  ranking é por variação %, com piso de materialidade (mediana da receita
 *  anterior entre quem se moveu) pra não deixar R$10→R$100 passar por sinal.
 *  Quem já apareceu no Tornado não repete aqui — as duas listas juntas
 *  cobrem o mecanismo sem se sobrepor. */
export function RadarPercentual({ radar }: Props) {
  if (!radar.disponivel || (radar.alta.length === 0 && radar.queda.length === 0)) {
    return null;
  }

  return (
    <section className="glass-card glass-card-flat clientes-visao-card">
      <header className="clientes-visao-card-topo">
        <div>
          <TituloDiagnostico texto="Sinais precoces" variante="neutro" />
          <p>
            Produtos com variação percentual forte que o Tornado (ranking por R$) ainda não mostra —
            ainda pequenos em valor, mas mudando de patamar rápido.
          </p>
        </div>
      </header>

      <div className="diagnostico-radar-colunas">
        <Coluna titulo="Em alta" itens={radar.alta} variante="alta" />
        <Coluna titulo="Em queda" itens={radar.queda} variante="queda" />
      </div>
    </section>
  );
}
