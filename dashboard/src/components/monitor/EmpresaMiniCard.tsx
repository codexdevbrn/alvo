import { memo } from 'react';
import { Area, AreaChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { ArrowDown, ArrowUp, Star } from 'lucide-react';
import type { EmpresaMonitor, MetricaMonitor } from '../../api/client';
import { formatCompacto, formatCurrency, formatNumber, formatPercent } from '../../utils/formatters';
import { COR_ANO_RECENTE } from '../../utils/coresAno';

const ROTULOS_METRICA: Record<MetricaMonitor, string> = {
  receita: 'Receita',
  qtd: 'Quantidade',
  clientes: 'Clientes',
  receita_dia: 'Receita / dia útil',
};

function ehMoeda(metrica: MetricaMonitor): boolean {
  return metrica === 'receita' || metrica === 'receita_dia';
}

type PontoSparkline = { rotulo: string; valor: number };

/**
 * Rótulo de valor sobre o ponto, intercalado — mesma ideia do Histórico do
 * Dashboard (que também pula rótulos): escrever os 12 num card de 1/3 de tela
 * viraria borrão. Um a cada dois recebe texto, e o último sempre, porque é o
 * número que se lê primeiro.
 */
function RotuloIntercalado(props: {
  x?: number | string;
  y?: number | string;
  value?: number | string | Array<number | string> | boolean | null;
  index?: number;
  total?: number;
  moeda: boolean;
}) {
  const { moeda } = props;
  const x = Number(props.x) || 0;
  const y = Number(props.y) || 0;
  const valor = Number(props.value) || 0;
  const indice = props.index ?? 0;
  const total = props.total ?? 0;
  const ultimo = total > 0 && indice === total - 1;

  if (!valor) return null;
  if (!ultimo && indice % 2 !== 0) return null;

  // Alterna acima/abaixo: em série quase plana dois rótulos vizinhos ficariam
  // colados. O último fica sempre acima e ancorado à direita, para não sair do
  // card.
  const acima = ultimo || indice % 4 === 0;

  return (
    <text
      x={x}
      y={y + (acima ? -7 : 13)}
      dx={indice === 0 ? 2 : ultimo ? -2 : 0}
      textAnchor={indice === 0 ? 'start' : ultimo ? 'end' : 'middle'}
      fill="var(--text-primary)"
      fontSize={9}
      fontWeight={ultimo ? 700 : 500}
      opacity={ultimo ? 0.95 : 0.6}
      style={{ pointerEvents: 'none' }}
    >
      {formatCompacto(valor, moeda)}
    </text>
  );
}

function TooltipSparkline({
  active,
  payload,
  label,
  moeda,
}: {
  active?: boolean;
  payload?: Array<{ value?: number }>;
  label?: string | number;
  moeda: boolean;
}) {
  if (!active || !payload?.length) return null;
  const valor = Number(payload[0]?.value ?? 0);
  return (
    <div className="monitor-grafico-tooltip">
      <span>{String(label ?? '')}</span>
      <strong>{moeda ? formatCurrency(valor) : formatNumber(valor)}</strong>
    </div>
  );
}

function Sparkline({ pontos, moeda }: { pontos: PontoSparkline[]; moeda: boolean }) {
  // Um ponto só existe na base (empresa com um único mês de movimento): área com
  // um ponto não desenha nada, então mostra o número, que é a informação.
  if (pontos.length === 1) {
    return (
      <div className="monitor-sparkline monitor-sparkline-unico">
        <strong>{formatCompacto(pontos[0].valor, moeda)}</strong>
        <span>{pontos[0].rotulo}</span>
      </div>
    );
  }

  return (
    <div className="monitor-sparkline">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={pontos} margin={{ top: 16, right: 18, left: 18, bottom: 4 }}>
          <defs>
            <linearGradient id="monitorSpark" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={COR_ANO_RECENTE} stopOpacity={0.3} />
              <stop offset="100%" stopColor={COR_ANO_RECENTE} stopOpacity={0} />
            </linearGradient>
          </defs>
          <XAxis
            dataKey="rotulo"
            axisLine={false}
            tickLine={false}
            // Reserva altura e afastamento reais para o texto. Com 14px e
            // margem inferior zero, o SVG cortava a metade dos rótulos.
            height={22}
            tickMargin={5}
            // Mostra ~4 marcas: com 12 períodos os rótulos se sobrepõem.
            interval={Math.max(0, Math.ceil(pontos.length / 4) - 1)}
          />
          {/* Escondido, e com domínio ajustado à faixa dos dados em vez de começar
              no zero: com base zero, uma série entre 4,3M e 6,3M ocupa a metade de
              cima de uma escala de 0 a 8,2M e vira quase uma reta — a variação, que
              é a razão do gráfico existir, desaparece. A folga embaixo é maior que
              em cima porque os rótulos de valor alternam acima/abaixo do ponto.
              Os números absolutos ficam nos rótulos, então a base não-zero não
              esconde informação. */}
          <YAxis
            hide
            domain={[
              (min: number) => min - (min > 0 ? min * 0.35 : 0),
              (max: number) => max * 1.12,
            ]}
          />
          <Tooltip
            content={<TooltipSparkline moeda={moeda} />}
            cursor={{ stroke: 'rgba(255,255,255,0.18)', strokeWidth: 1 }}
          />
          <Area
            type="monotone"
            dataKey="valor"
            stroke={COR_ANO_RECENTE}
            strokeWidth={1.8}
            fill="url(#monitorSpark)"
            isAnimationActive={false}
            // Pontinhos em todos os períodos: num card pequeno são a única pista
            // de quantos meses a linha cobre.
            dot={{ r: 2, fill: COR_ANO_RECENTE, strokeWidth: 0 }}
            activeDot={{ r: 3.5, fill: '#fff', stroke: COR_ANO_RECENTE, strokeWidth: 2 }}
            // `total` explícito: o Recharts não o passa no render prop, e sem ele
            // `ultimo` era sempre falso — o último ponto, que é o número que se lê
            // primeiro, ficava sem rótulo sempre que a série tinha tamanho par.
            label={(props: object) => (
              <RotuloIntercalado {...props} total={pontos.length} moeda={moeda} />
            )}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}

interface Props {
  item: EmpresaMonitor;
  metrica: MetricaMonitor;
  favorita: boolean;
  /** Bloqueia a estrela durante o POST para não disparar dois salvamentos. */
  salvandoFavorita?: boolean;
  onAlternarFavorita: (empresa: string) => void;
  onAbrir: (empresa: string) => void;
}

function EmpresaMiniCardInterno({
  item,
  metrica,
  favorita,
  salvandoFavorita = false,
  onAlternarFavorita,
  onAbrir,
}: Props) {
  const moeda = ehMoeda(metrica);
  const semBase = item.estado !== 'ok';

  const pontos: PontoSparkline[] = (item.valores ?? []).map((valor, indice) => ({
    rotulo: String(item.rotulos?.[indice] ?? ''),
    valor,
  }));

  // Resumo compacto da mesma janela exibida no gráfico. A média já vem do
  // backend porque receita/dia precisa ser ponderada pelos dias úteis.
  const ultimoPonto = pontos[pontos.length - 1];
  const picoPonto = pontos.reduce<PontoSparkline | undefined>(
    (maior, ponto) => (!maior || ponto.valor > maior.valor ? ponto : maior),
    undefined,
  );
  const mediaPontos = item.media ?? (
    pontos.length > 0
      ? pontos.reduce((soma, ponto) => soma + ponto.valor, 0) / pontos.length
      : 0
  );

  // Métrica de média vem sem total (somar médias não significa nada): o número
  // grande passa a ser a média ponderada da janela.
  const ehMedia = item.total === null || item.total === undefined;
  const destaque = (ehMedia ? item.media : item.total) ?? 0;

  const variacao = item.variacao_pct;
  const classeVariacao =
    variacao == null ? 'is-neutra' : variacao >= 0 ? 'is-positiva' : 'is-negativa';

  const classes = [
    'glass-card',
    'monitor-card',
    favorita ? 'is-favorita' : '',
    semBase ? 'is-sem-base' : '',
  ].filter(Boolean).join(' ');

  return (
    <article className={classes}>
      <button
        type="button"
        className="monitor-favorito-btn"
        onClick={() => onAlternarFavorita(item.empresa)}
        disabled={salvandoFavorita}
        aria-pressed={favorita}
        aria-label={favorita ? `Remover ${item.empresa} dos favoritos` : `Favoritar ${item.empresa}`}
        title={favorita ? 'Remover dos favoritos' : 'Favoritar'}
      >
        <Star size={16} fill={favorita ? 'currentColor' : 'none'} />
      </button>

      {/* O card inteiro é o alvo de clique (abre o Dashboard da empresa), mas a
          estrela fica FORA dele: aninhar botão em botão é HTML inválido e o
          clique na estrela abriria o Dashboard sem querer. */}
      <button type="button" className="monitor-card-link" onClick={() => onAbrir(item.empresa)}>
        <div className="monitor-card-topo">
          <h2 title={item.empresa}>{item.empresa}</h2>
          {favorita && <span className="monitor-favorita-tag">favorita</span>}
          {/* Data na linha do nome, e não num rodapé próprio: é metadado do card, e
              uma linha inteira só para ela custava altura em dezenas de cards. */}
          {item.updated_at && (
            <span className="monitor-card-data" title="Última atualização">
              {item.updated_at}
            </span>
          )}
        </div>

        {semBase ? (
          <div className="monitor-card-sem-base">
            <strong>{item.estado === 'sem_base' ? 'Base não gerada' : 'Erro ao ler'}</strong>
            <span>{item.detalhe ?? 'Dados indisponíveis para esta empresa.'}</span>
          </div>
        ) : (
          <>
            <div className="monitor-kpi">
              <span>
                {ROTULOS_METRICA[metrica]} · {ehMedia ? 'média por dia útil' : 'total do período'}
              </span>
              {/* Variação ao lado do valor, e não no rodapé: é o par que o usuário
                  lê junto — quanto foi e se subiu ou caiu. */}
              <div className="monitor-kpi-linha">
                <strong>{moeda ? formatCurrency(destaque) : formatNumber(destaque)}</strong>
                {variacao != null ? (
                  <span
                    className={`monitor-variacao ${classeVariacao}`}
                    title={
                      item.ano_comparado
                        ? `${item.meses_comparados} ${item.meses_comparados === 1 ? 'mês' : 'meses'} de ${item.ano_comparado} vs ${item.ano_comparado - 1}`
                        : undefined
                    }
                  >
                    {variacao >= 0 ? <ArrowUp size={12} /> : <ArrowDown size={12} />}
                    {formatPercent(variacao)}
                  </span>
                ) : (
                  <span
                    className="monitor-variacao is-neutra"
                    title={
                      item.base_comparavel === false
                        ? 'O ano anterior teve movimento irrisório nesses meses — o percentual não ajudaria a decidir.'
                        : 'Sem os mesmos meses no ano anterior para comparar.'
                    }
                  >
                    sem base
                  </span>
                )}
              </div>
            </div>

            <Sparkline pontos={pontos} moeda={moeda} />

            <div className="monitor-card-metricas" aria-label={`Resumo de ${ROTULOS_METRICA[metrica].toLowerCase()}`}>
              <div className="monitor-card-metrica">
                <span>Último</span>
                <strong title={ultimoPonto ? (moeda ? formatCurrency(ultimoPonto.valor) : formatNumber(ultimoPonto.valor)) : '—'}>
                  {ultimoPonto ? formatCompacto(ultimoPonto.valor, moeda) : '—'}
                </strong>
                <small>{ultimoPonto?.rotulo || 'sem período'}</small>
              </div>
              <div className="monitor-card-metrica">
                <span>Média</span>
                <strong title={moeda ? formatCurrency(mediaPontos) : formatNumber(mediaPontos)}>
                  {formatCompacto(mediaPontos, moeda)}
                </strong>
                <small>{pontos.length} {pontos.length === 1 ? 'período' : 'períodos'}</small>
              </div>
              <div className="monitor-card-metrica">
                <span>Pico</span>
                <strong title={picoPonto ? (moeda ? formatCurrency(picoPonto.valor) : formatNumber(picoPonto.valor)) : '—'}>
                  {picoPonto ? formatCompacto(picoPonto.valor, moeda) : '—'}
                </strong>
                <small>{picoPonto?.rotulo || 'sem período'}</small>
              </div>
            </div>

          </>
        )}
      </button>
    </article>
  );
}

/** memo: são dezenas de cards com gráfico, e favoritar muda o estado do pai —
 *  sem isso um clique redesenha todos. */
export const EmpresaMiniCard = memo(EmpresaMiniCardInterno);
