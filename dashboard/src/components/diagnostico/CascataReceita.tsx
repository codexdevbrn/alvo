import { Bar, BarChart, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import type { CascataDiagnostico, PassoCascata } from '../../api/client';
import { formatCompacto, formatCurrency, formatPercent } from '../../utils/formatters';
import { TituloDiagnostico } from './TituloDiagnostico';

interface Props {
  cascata: CascataDiagnostico;
}

const COR_POR_TIPO: Record<PassoCascata['tipo'], string> = {
  inicio: 'var(--surface-4)',
  fim: 'var(--accent)',
  ganho: 'var(--success)',
  perda: 'var(--danger)',
};

function TooltipCascata({
  active,
  payload,
}: {
  active?: boolean;
  payload?: Array<{ payload?: PassoCascata }>;
}) {
  const passo = payload?.[0]?.payload;
  if (!active || !passo) return null;
  const ponta = passo.tipo === 'inicio' || passo.tipo === 'fim';
  return (
    <div className="vendedores-chart-tooltip">
      <strong>{passo.rotulo}</strong>
      <dl>
        <div>
          <dt>{ponta ? 'Receita' : 'Efeito'}</dt>
          <dd>{ponta ? formatCurrency(passo.delta ?? 0) : `${(passo.delta ?? 0) > 0 ? '+' : ''}${formatCurrency(passo.delta ?? 0)}`}</dd>
        </div>
        {!ponta && (
          <div><dt>Acumulado</dt><dd>{formatCurrency(passo.acumulado ?? 0)}</dd></div>
        )}
      </dl>
    </div>
  );
}

/** ATO II: de onde saiu e onde chegou a receita, contra o mesmo período do ano
 *  passado. Cada degrau é um produto; a barra flutua sobre um trecho invisível
 *  (`base`), que o backend já calcula.
 *
 *  Verde/vermelho aqui é status semântico (ganhou/perdeu), e a posição do degrau
 *  — subindo ou descendo — carrega a mesma informação, então a cor não é o único
 *  canal. */
export function CascataReceita({ cascata }: Props) {
  const { passos, cobertura_pct: cobertura } = cascata;
  if (passos.length === 0) {
    return <p className="analisador-hint">Sem período equivalente no ano anterior para comparar.</p>;
  }

  const inicio = passos[0];
  const fim = passos[passos.length - 1];
  const delta = (fim.delta ?? 0) - (inicio.delta ?? 0);
  const caiu = delta < 0;
  const ganhos = passos.filter((passo) => passo.tipo === 'ganho').length;
  const perdas = passos.filter((passo) => passo.tipo === 'perda').length;

  // Eixo truncado, e dito em voz alta no rodapé. Os degraus somam R$ 126 mil
  // sobre uma base de R$ 6,3 M: num eixo a partir do zero eles viram um risco
  // de 2px, e o gráfico deixa de responder à pergunta que justifica existir.
  // O total continua legível porque as duas pontas são colunas cheias.
  const acumulados = passos.map((passo) => passo.acumulado ?? 0);
  const menor = Math.min(...acumulados);
  const maior = Math.max(...acumulados);
  const folga = Math.max((maior - menor) * 0.15, maior * 0.005);
  // Arredonda as pontas para um múltiplo do espaçamento dos ticks, senão o
  // Recharts parte de um piso quebrado e imprime dois deles quase colados.
  // O múltiplo sai do espaçamento (faixa ÷ 4), não da década: arredondar para a
  // década cheia devolveria um eixo de R$ 5 M a R$ 7 M e desfaria o zoom que
  // é a razão de o eixo ser truncado.
  const arredondado = (valor: number) => {
    const decada = 10 ** Math.floor(Math.log10(valor));
    const norma = valor / decada;
    return (norma <= 1 ? 1 : norma <= 2 ? 2 : norma <= 2.5 ? 2.5 : norma <= 5 ? 5 : 10) * decada;
  };
  const espacamento = arredondado(((maior + folga) - (menor - folga)) / 4);
  const piso = Math.floor((menor - folga) / espacamento) * espacamento;
  const teto = Math.ceil((maior + folga) / espacamento) * espacamento;

  return (
    <section className="glass-card glass-card-flat clientes-visao-card">
      <header className="clientes-visao-card-topo">
        <div>
          <TituloDiagnostico
            texto="Receita vs. ano anterior"
            destaque={`${caiu ? '−' : '+'}${formatCurrency(Math.abs(delta))}`}
            variante={caiu ? 'queda' : 'alta'}
          />
          <p>
            {perdas} produto(s) puxaram, {ganhos} seguraram, contra {inicio.rotulo} do ano anterior — o corte que tira sazonalidade da conta.
            {cobertura != null && ` Cobre ${formatPercent(cobertura, 1)} da receita (produtos harmonizados).`}
          </p>
        </div>
        {/* A base sobe para o cabeçalho, em vez de ficar só no subtítulo: este
            card e o tornado ao lado medem o mesmo produto contra réguas
            diferentes, e o mesmo item aparece verde aqui e vermelho lá sem se
            contradizer. Sem o rótulo, isso lê como erro. */}
        <span className="diagnostico-base-chip">vs {inicio.rotulo} · ano anterior</span>
      </header>

      <div className="vendedores-chart clientes-visao-chart diagnostico-cascata-chart">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={passos} margin={{ top: 8, right: 8, left: 0, bottom: 4 }}>
            <XAxis
              dataKey="rotulo"
              tick={{ fill: 'var(--text-secondary)', fontSize: 10 }}
              axisLine={false}
              tickLine={false}
              interval={0}
              angle={-35}
              textAnchor="end"
              height={78}
              tickFormatter={(valor: string) => (valor.length > 16 ? `${valor.slice(0, 15)}…` : valor)}
            />
            <YAxis
              tick={{ fill: 'var(--text-muted)', fontSize: 11 }}
              axisLine={false}
              tickLine={false}
              width={68}
              domain={[piso, teto]}
              tickCount={5}
              allowDataOverflow
              tickFormatter={(valor: number) => formatCompacto(valor, true)}
            />
            <Tooltip content={<TooltipCascata />} cursor={{ fill: 'var(--surface-2)' }} />
            {/* Trecho invisível que levanta a barra até o acumulado do degrau. */}
            <Bar dataKey="base" stackId="cascata" fill="transparent" isAnimationActive={false} />
            <Bar dataKey="altura" stackId="cascata" radius={[4, 4, 0, 0]} isAnimationActive={false}>
              {passos.map((passo) => (
                <Cell key={`${passo.tipo}-${passo.rotulo}`} fill={COR_POR_TIPO[passo.tipo]} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
      <p className="diagnostico-nota-eixo">
        Eixo começa em {formatCompacto(piso, true)} — cada degrau é pequeno ao lado do total.
      </p>
    </section>
  );
}
