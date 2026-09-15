import { useEffect, useMemo, useState } from 'react';
import { AlertTriangle, CalendarRange, Loader2, TrendingDown, TrendingUp, Wallet } from 'lucide-react';
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ComposedChart,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { StatCard } from '../StatCard';
import { LeituraFaixa } from '../LeituraFaixa';
import {
  obterResumoDespesas,
  type GrupoAbcDespesa,
  type ItemDespesaCategoria,
  type ResumoDespesasResposta,
} from '../../api/client';
import { formatCompacto, formatCurrency, formatPercent, rotuloGrupoCurto } from '../../utils/formatters';
import { useMesesFechados } from '../../hooks/useMesesFechados';
import { modoParaBooleano } from '../../utils/mesesFechados';
import { variacaoSuspeita } from '../../utils/variacaoSuspeita';

type Props = {
  empresa: string;
  loja: string | null;
  meses: number;
};

type ModoEvolucao = 'total' | 'composicao';

// Paleta categórica das categorias no empilhado. Validada para o fundo de card
// escuro (`--bg-card`, #131316): piso de croma, separação para daltonismo e
// contraste passam; a ordem é fixa, nunca rotacionada, para a mesma categoria
// manter a cor quando o filtro muda o conjunto. O ouro da marca (`--accent`)
// fica no índice 0 e é o único tom acima da faixa de luminosidade ideal — é
// deliberado: ele é o acento do app e marca a maior categoria.
const CORES_CATEGORIA = ['#dabb6c', '#6690cf', '#e2703a', '#35a898', '#a97bcb', '#4da156'];
const COR_OUTRAS = '#5d5d66';

// Ouro → cinza, mesma progressão de `CORES_FAIXA` em Clientes: a faixa mais
// forte puxa o acento, "Demais" esfria pro neutro.
const CORES_GRUPO = ['#dabb6c', '#6690cf', '#35a898', '#5d5d66'];
// Texto do chip: o ouro do índice 0 é o `--accent` — sobre ele o texto segue a
// regra do projeto (`--accent-contrast`, nunca branco); os demais tons são
// escuros o bastante para texto branco comum.
const TEXTO_GRUPO = ['var(--accent-contrast)', '#fff', '#fff', '#fff'];

const MODOS: { id: ModoEvolucao; rotulo: string }[] = [
  { id: 'total', rotulo: 'Total por mês' },
  { id: 'composicao', rotulo: 'Por categoria' },
];

function corCategoria(categoria: string, indice: number): string {
  return categoria === 'Outras' ? COR_OUTRAS : CORES_CATEGORIA[indice % CORES_CATEGORIA.length];
}

function indiceGrupo(grupo: string | null, grupos: GrupoAbcDespesa[]): number {
  return grupos.findIndex((item) => item.grupo === grupo);
}

function corGrupo(grupo: string | null, grupos: GrupoAbcDespesa[]): string {
  const indice = indiceGrupo(grupo, grupos);
  return indice >= 0 ? CORES_GRUPO[indice % CORES_GRUPO.length] : 'var(--accent)';
}

function estiloGrupoChip(grupo: string | null, grupos: GrupoAbcDespesa[]): { background: string; color: string } {
  const indice = indiceGrupo(grupo, grupos);
  if (indice < 0) return { background: 'var(--accent)', color: 'var(--accent-contrast)' };
  return {
    background: CORES_GRUPO[indice % CORES_GRUPO.length],
    color: TEXTO_GRUPO[indice % TEXTO_GRUPO.length],
  };
}

function encurtar(texto: string, limite = 14): string {
  return texto.length > limite ? `${texto.slice(0, limite - 1)}…` : texto;
}

type EntradaGrafico = { dataKey?: string; name?: string; value?: number; color?: string };

function TooltipComposicao({
  active,
  payload,
  label,
}: {
  active?: boolean;
  payload?: EntradaGrafico[];
  label?: string;
}) {
  if (!active || !payload?.length) return null;
  const total = payload.reduce((soma, item) => soma + (Number(item.value) || 0), 0);
  const ordenado = [...payload].sort((a, b) => (Number(b.value) || 0) - (Number(a.value) || 0));
  return (
    <div className="vendedores-chart-tooltip">
      <strong>{label}</strong>
      <dl>
        {ordenado.map((item) => (
          <div key={item.dataKey}>
            <dt>
              <i className="despesas-tooltip-cor" style={{ background: item.color }} aria-hidden="true" />
              {item.name}
            </dt>
            <dd>{formatCurrency(Number(item.value) || 0)}</dd>
          </div>
        ))}
        <div><dt>Total</dt><dd>{formatCurrency(total)}</dd></div>
      </dl>
    </div>
  );
}

type PontoTotal = { rotulo: string; valor: number; variacao: number | null };

function TooltipTotal({ active, payload }: { active?: boolean; payload?: { payload: PontoTotal }[] }) {
  if (!active || !payload?.length) return null;
  const ponto = payload[0].payload;
  return (
    <div className="vendedores-chart-tooltip">
      <strong>{ponto.rotulo}</strong>
      <dl>
        <div><dt>Despesa</dt><dd>{formatCurrency(ponto.valor)}</dd></div>
        {ponto.variacao != null && (
          <div>
            <dt>vs. mês anterior</dt>
            <dd>{ponto.variacao >= 0 ? '+' : '−'}{formatPercent(Math.abs(ponto.variacao), 1)}</dd>
          </div>
        )}
      </dl>
    </div>
  );
}

type PontoPareto = {
  categoria: string;
  curto: string;
  valor: number;
  pct: number;
  acumulado: number;
  grupo: string | null;
  cor: string;
};

function TooltipPareto({ active, payload }: { active?: boolean; payload?: { payload: PontoPareto }[] }) {
  if (!active || !payload?.length) return null;
  const ponto = payload[0].payload;
  return (
    <div className="vendedores-chart-tooltip">
      <strong>{ponto.categoria}</strong>
      <dl>
        <div><dt>Valor</dt><dd>{formatCurrency(ponto.valor)}</dd></div>
        <div><dt>Participação</dt><dd>{formatPercent(ponto.pct, 1)}</dd></div>
        <div><dt>Acumulado</dt><dd>{formatPercent(ponto.acumulado, 1)}</dd></div>
        {ponto.grupo && <div><dt>Grupo</dt><dd>{ponto.grupo}</dd></div>}
      </dl>
    </div>
  );
}

function tendenciaTexto(item: ItemDespesaCategoria): string | null {
  if (item.tendencia_pct == null) return null;
  const seta = item.tendencia_pct >= 0 ? '↑' : '↓';
  return `${seta} ${formatPercent(Math.abs(item.tendencia_pct), 1)}`;
}

/** Aba Visão geral: total, evolução mensal, concentração (Pareto com a mesma
 *  régua ABC de Clientes/Produtos) e para onde o dinheiro foi — tudo derivado de
 *  Loja/categoria/Ano/Mês/Valor, os únicos campos que a Controladoria traz. */
export function DespesasVisaoGeral({ empresa, loja, meses }: Props) {
  const [dados, setDados] = useState<ResumoDespesasResposta | null>(null);
  const [carregando, setCarregando] = useState(true);
  const [erro, setErro] = useState<string | null>(null);
  const [modo, setModo] = useState<ModoEvolucao>('total');
  const [modoPeriodo] = useMesesFechados();
  const usarMesesFechados = modoParaBooleano(modoPeriodo);

  useEffect(() => {
    let vivo = true;
    setCarregando(true);
    setErro(null);
    void obterResumoDespesas(empresa, { loja, meses, usarMesesFechados })
      .then((resposta) => {
        if (vivo) setDados(resposta);
      })
      .catch((falha) => {
        if (!vivo) return;
        setDados(null);
        setErro(falha instanceof Error ? falha.message : 'Falha ao carregar as despesas.');
      })
      .finally(() => {
        if (vivo) setCarregando(false);
      });
    return () => {
      vivo = false;
    };
  }, [empresa, loja, meses, usarMesesFechados]);

  // A série total ganha a variação mês a mês aqui (o backend só manda o valor),
  // porque é o número que o tooltip mostra em cada barra.
  const serieTotal = useMemo<PontoTotal[]>(() => {
    const pontos = dados?.serie_mensal ?? [];
    return pontos.map((ponto, indice) => {
      const anterior = indice > 0 ? pontos[indice - 1].valor : null;
      return {
        rotulo: ponto.rotulo,
        valor: ponto.valor,
        variacao: anterior && anterior > 0 ? ((ponto.valor - anterior) / anterior) * 100 : null,
      };
    });
  }, [dados]);

  // Pareto em uma escala só: barra e linha são ambas percentuais, então não há
  // segundo eixo — o valor em reais vive no tooltip.
  const pareto = useMemo<PontoPareto[]>(() => {
    const grupos = dados?.curva_abc_categorias.grupos ?? [];
    let acumulado = 0;
    return (dados?.por_categoria ?? [])
      .filter((item) => item.categoria !== 'Demais')
      .map((item) => {
      acumulado += item.pct;
      return {
        categoria: item.categoria,
        curto: encurtar(item.categoria),
        valor: item.valor,
        pct: item.pct,
        acumulado: Math.min(acumulado, 100),
        grupo: item.grupo_abc,
        cor: corGrupo(item.grupo_abc, grupos),
      };
    });
  }, [dados]);

  if (erro) {
    return (
      <div className="glass-card glass-card-flat estoque-aviso" role="alert">
        <AlertTriangle size={18} /><span>{erro}</span>
      </div>
    );
  }

  if (carregando && !dados) {
    return (
      <div className="glass-card estoque-carregando" role="status">
        <Loader2 size={20} className="dashboard-filter-spinner" /> Somando lançamentos de despesas…
      </div>
    );
  }

  if (!dados) return null;

  const { resumo } = dados;
  const variacaoConhecida = resumo.variacao_pct != null;
  const quedaBuraco = variacaoSuspeita(resumo.variacao_pct, resumo.mes_atual, resumo.mes_anterior);
  const despesaCaiu = !quedaBuraco && (resumo.variacao_pct ?? 0) < 0;
  const variacaoAnualConhecida = resumo.variacao_anual_pct != null;
  const quedaBuracoAno = variacaoSuspeita(
    resumo.variacao_anual_pct,
    resumo.mes_atual,
    resumo.mes_mesmo_periodo_ano_anterior ?? 0,
  );
  const despesaCaiuNoAno = !quedaBuracoAno && (resumo.variacao_anual_pct ?? 0) < 0;
  const periodo = dados.periodo_inicio && dados.periodo_fim
    ? `${dados.periodo_inicio} a ${dados.periodo_fim}`
    : 'sem lançamentos';
  const maiorCategoria = dados.por_categoria[0]?.valor ?? 0;
  const totalLojas = dados.por_loja.reduce((soma, item) => soma + item.valor, 0);
  const maiorLoja = dados.por_loja[0]?.valor ?? 0;

  const composicaoMensal = (dados.serie_mensal_categorias?.pontos ?? []).map((ponto) => ({
    periodo: ponto.periodo,
    rotulo: ponto.rotulo,
    ...ponto.valores,
  }));
  const categoriasComposicao = dados.serie_mensal_categorias?.categorias ?? [];
  const grupos = dados.curva_abc_categorias?.grupos ?? [];
  const temEvolucao = modo === 'total' ? serieTotal.length > 0 : composicaoMensal.length > 0;

  return (
    <div className="estoque-visao despesas-visao">
      <LeituraFaixa tom={quedaBuraco || quedaBuracoAno ? 'aviso' : 'normal'}>
        {quedaBuraco
          ? `Último mês (${formatCurrency(resumo.mes_atual)}) despenca contra o anterior — conferir se a competência tem lançamento, não celebrar como economia.`
          : `Total ${formatCurrency(resumo.total)} em ${periodo}. Último mês ${formatCurrency(resumo.mes_atual)}${variacaoConhecida ? ` (${formatPercent(resumo.variacao_pct ?? 0, 1)} vs anterior)` : ''}.`}
      </LeituraFaixa>
      <section className="despesas-kpis" aria-label="Indicadores de despesas">
        <article className="glass-card glass-card-flat despesas-hero">
          <div className="despesas-hero-texto">
            <p className="despesas-hero-rotulo">
              <Wallet size={14} aria-hidden="true" /> Total no período
            </p>
            <strong className="despesas-hero-valor">{formatCurrency(resumo.total)}</strong>
            <p className="despesas-hero-nota">
              <CalendarRange size={13} aria-hidden="true" /> {periodo} · média de {formatCurrency(resumo.media_mensal)} por mês
            </p>
          </div>
          {serieTotal.length > 1 && (
            <div className="despesas-hero-spark" aria-hidden="true">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={serieTotal} margin={{ top: 4, right: 0, left: 0, bottom: 0 }}>
                  <defs>
                    <linearGradient id="despesasHeroFill" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor="var(--accent)" stopOpacity={0.35} />
                      <stop offset="100%" stopColor="var(--accent)" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <Area
                    type="monotone"
                    dataKey="valor"
                    stroke="var(--accent)"
                    strokeWidth={2}
                    fill="url(#despesasHeroFill)"
                    dot={false}
                    isAnimationActive={false}
                  />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          )}
        </article>

        <div className="despesas-kpis-secundarios">
          <StatCard
            title="Último mês"
            value={formatCurrency(resumo.mes_atual)}
            icon={quedaBuraco ? AlertTriangle : (despesaCaiu ? TrendingDown : TrendingUp)}
            trend={quedaBuraco
              ? 'queda extrema — conferir lançamento do mês'
              : variacaoConhecida
                ? `${formatPercent(Math.abs(resumo.variacao_pct ?? 0), 1)} vs. mês anterior`
                : 'sem mês anterior para comparar'}
            trendUp={despesaCaiu}
            trendArrow={despesaCaiu ? 'down' : 'up'}
            useTrendColor={variacaoConhecida && !quedaBuraco}
          />
          <StatCard
            title="vs. mesmo mês do ano passado"
            value={variacaoAnualConhecida ? formatPercent(Math.abs(resumo.variacao_anual_pct ?? 0), 1) : '—'}
            icon={quedaBuracoAno ? AlertTriangle : (despesaCaiuNoAno ? TrendingDown : TrendingUp)}
            trend={quedaBuracoAno
              ? 'buraco de dado, não economia'
              : variacaoAnualConhecida
                ? `era ${formatCurrency(resumo.mes_mesmo_periodo_ano_anterior ?? 0)}`
                : 'sem dado no ano anterior'}
            trendUp={despesaCaiuNoAno}
            trendArrow={despesaCaiuNoAno ? 'down' : 'up'}
            useTrendColor={variacaoAnualConhecida && !quedaBuracoAno}
          />
        </div>
      </section>

      <section className="glass-card glass-card-flat estoque-visao-card">
        <header className="estoque-card-topo">
          <div>
            <h2>Evolução mensal</h2>
            <p>
              {modo === 'total'
                ? 'Total lançado em cada mês, com a linha da média do período.'
                : 'Composição do total de cada mês pelas maiores categorias.'}
            </p>
          </div>
          <div className="periodo-segmented despesas-segmented" role="tablist" aria-label="Modo do gráfico de evolução">
            {MODOS.map((item) => (
              <button
                key={item.id}
                type="button"
                role="tab"
                aria-selected={modo === item.id}
                className={`periodo-segmented-btn${modo === item.id ? ' is-active' : ''}`}
                onClick={() => setModo(item.id)}
              >
                {item.rotulo}
              </button>
            ))}
          </div>
        </header>
        {!temEvolucao ? (
          <p className="analisador-hint">Sem lançamentos nesta seleção.</p>
        ) : modo === 'total' ? (
          <>
            <div className="vendedores-chart" style={{ height: 280 }}>
              <ResponsiveContainer width="100%" height="100%">
                <ComposedChart data={serieTotal} margin={{ top: 8, right: 8, left: 0, bottom: 4 }}>
                  <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" vertical={false} />
                  <XAxis
                    dataKey="rotulo"
                    tick={{ fill: 'var(--text-secondary)', fontSize: 11 }}
                    axisLine={false}
                    tickLine={false}
                  />
                  <YAxis
                    tickFormatter={(v) => formatCompacto(Number(v), true)}
                    tick={{ fill: 'var(--text-muted)', fontSize: 11 }}
                    axisLine={false}
                    tickLine={false}
                    width={56}
                  />
                  <Tooltip cursor={{ fill: 'var(--surface-2)' }} content={<TooltipTotal />} />
                  <Bar dataKey="valor" name="Despesa" fill="var(--accent)" radius={[4, 4, 0, 0]} maxBarSize={34} />
                  <ReferenceLine
                    y={resumo.media_mensal}
                    stroke="var(--text-muted)"
                    strokeDasharray="4 4"
                    strokeWidth={2}
                  />
                </ComposedChart>
              </ResponsiveContainer>
            </div>
            <div className="vendedores-chart-legenda">
              <span><i style={{ background: 'var(--accent)' }} aria-hidden="true" />Despesa do mês</span>
              <span>
                <i className="despesas-legenda-media" aria-hidden="true" />
                Média mensal · {formatCurrency(resumo.media_mensal)}
              </span>
            </div>
          </>
        ) : (
          <>
            <div className="vendedores-chart" style={{ height: 280 }}>
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={composicaoMensal} margin={{ top: 8, right: 8, left: 0, bottom: 4 }}>
                  <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" vertical={false} />
                  <XAxis
                    dataKey="rotulo"
                    tick={{ fill: 'var(--text-secondary)', fontSize: 11 }}
                    axisLine={false}
                    tickLine={false}
                  />
                  <YAxis
                    tickFormatter={(v) => formatCompacto(Number(v), true)}
                    tick={{ fill: 'var(--text-muted)', fontSize: 11 }}
                    axisLine={false}
                    tickLine={false}
                    width={56}
                  />
                  <Tooltip cursor={{ fill: 'var(--surface-2)' }} content={<TooltipComposicao />} />
                  {categoriasComposicao.map((categoria, indice) => (
                    <Bar
                      key={categoria}
                      dataKey={categoria}
                      name={categoria}
                      stackId="total"
                      fill={corCategoria(categoria, indice)}
                      stroke="var(--bg-card)"
                      strokeWidth={2}
                      radius={indice === categoriasComposicao.length - 1 ? [4, 4, 0, 0] : undefined}
                      maxBarSize={36}
                    />
                  ))}
                </BarChart>
              </ResponsiveContainer>
            </div>
            <ul className="analisador-explorar-legend">
              {categoriasComposicao.map((categoria, indice) => (
                <li key={categoria} className="analisador-explorar-legend-item">
                  <span className="analisador-explorar-legend-swatch" style={{ background: corCategoria(categoria, indice) }} />
                  <span className="analisador-explorar-legend-label" title={categoria}>{categoria}</span>
                </li>
              ))}
            </ul>
          </>
        )}
      </section>

      <section className="glass-card glass-card-flat estoque-visao-card">
        <header className="estoque-card-topo">
          <div>
            <h2>Concentração do gasto</h2>
            <p>Participação de cada categoria e o acumulado — mesma régua ABC de Clientes e Produtos.</p>
          </div>
        </header>
        {pareto.length === 0 ? (
          <p className="analisador-hint">Sem despesa na seleção para montar a curva.</p>
        ) : (
          <>
            <div className="vendedores-chart" style={{ height: 260 }}>
              <ResponsiveContainer width="100%" height="100%">
                <ComposedChart data={pareto} margin={{ top: 8, right: 8, left: 0, bottom: 4 }}>
                  <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" vertical={false} />
                  <XAxis
                    dataKey="curto"
                    tick={{ fill: 'var(--text-secondary)', fontSize: 10 }}
                    axisLine={false}
                    tickLine={false}
                    interval={0}
                    angle={-24}
                    textAnchor="end"
                    height={54}
                  />
                  <YAxis
                    domain={[0, 100]}
                    tickFormatter={(v) => `${v}%`}
                    tick={{ fill: 'var(--text-muted)', fontSize: 11 }}
                    axisLine={false}
                    tickLine={false}
                    width={44}
                  />
                  <Tooltip cursor={{ fill: 'var(--surface-2)' }} content={<TooltipPareto />} />
                  {dados.curva_abc_categorias.cortes.map((corte) => (
                    <ReferenceLine key={corte} y={corte} stroke="var(--border-strong)" strokeDasharray="3 4" />
                  ))}
                  <Bar dataKey="pct" name="Participação" radius={[4, 4, 0, 0]} maxBarSize={38}>
                    {pareto.map((ponto) => (
                      <Cell key={ponto.categoria} fill={ponto.cor} />
                    ))}
                  </Bar>
                  <Line
                    type="monotone"
                    dataKey="acumulado"
                    name="Acumulado"
                    stroke="var(--text-primary)"
                    strokeWidth={2}
                    dot={{ r: 3, fill: 'var(--bg-card)', stroke: 'var(--text-primary)', strokeWidth: 2 }}
                    isAnimationActive={false}
                  />
                </ComposedChart>
              </ResponsiveContainer>
            </div>
            <ul className="despesas-grupos">
              {grupos.map((grupo, indice) => (
                <li key={grupo.grupo}>
                  <i style={{ background: CORES_GRUPO[indice % CORES_GRUPO.length] }} aria-hidden="true" />
                  <span>{grupo.grupo}</span>
                  <strong>{grupo.quantidade} {grupo.quantidade === 1 ? 'categoria' : 'categorias'}</strong>
                  <em>{formatPercent(grupo.pct, 1)} do gasto</em>
                </li>
              ))}
            </ul>
          </>
        )}
      </section>

      <div className="estoque-visao-grade estoque-visao-grade-auto">
        <section className="glass-card glass-card-flat estoque-visao-card">
          <header className="estoque-card-topo">
            <div>
              <h2>Para onde o dinheiro foi</h2>
              <p>Maiores categorias no período, com a tendência dentro da janela.</p>
            </div>
            <span className="estoque-card-nota">{dados.por_categoria.length} categorias</span>
          </header>
          {dados.por_categoria.length === 0 ? (
            <p className="analisador-hint">Sem categorias nesta seleção.</p>
          ) : (
            <ul className="despesas-lista">
              {dados.por_categoria.map((linha) => {
                const tendencia = tendenciaTexto(linha);
                const subiu = (linha.tendencia_pct ?? 0) >= 0;
                const extrema = Math.abs(linha.tendencia_pct ?? 0) >= 80;
                return (
                  <li key={linha.categoria}>
                    <div className="despesas-lista-topo">
                      {linha.grupo_abc && (
                        <b
                          className="despesas-grupo-chip"
                          title={linha.grupo_abc}
                          style={estiloGrupoChip(linha.grupo_abc, grupos)}
                        >
                          {rotuloGrupoCurto(linha.grupo_abc)}
                        </b>
                      )}
                      <span title={linha.categoria}>{linha.categoria}</span>
                      <strong>{formatCurrency(linha.valor)}</strong>
                    </div>
                    <i className="despesas-lista-trilho" aria-hidden="true">
                      <b style={{
                        width: `${maiorCategoria > 0 ? (linha.valor / maiorCategoria) * 100 : 0}%`,
                        background: corGrupo(linha.grupo_abc, grupos),
                      }}
                      />
                    </i>
                    <div className="despesas-lista-rodape">
                      <em>{formatPercent(linha.pct, 1)} do total</em>
                      {tendencia && (
                        <span
                          className={`despesas-tendencia${extrema ? '' : subiu ? ' is-alta' : ' is-baixa'}`}
                          title="Variação entre o início e o fim da janela"
                        >
                          {tendencia}
                        </span>
                      )}
                    </div>
                  </li>
                );
              })}
            </ul>
          )}
        </section>

        {dados.por_loja.length > 1 && (
          <section className="glass-card glass-card-flat estoque-visao-card">
            <header className="estoque-card-topo">
              <div>
                <h2>Por loja</h2>
                <p>Despesas somadas por loja no período.</p>
              </div>
              <span className="estoque-card-nota">{formatCurrency(totalLojas)}</span>
            </header>
            <ul className="despesas-lista">
              {dados.por_loja.map((linha) => (
                <li key={linha.loja}>
                  <div className="despesas-lista-topo">
                    <span title={linha.loja}>{linha.loja}</span>
                    <strong>{formatCurrency(linha.valor)}</strong>
                  </div>
                  <i className="despesas-lista-trilho" aria-hidden="true">
                    <b style={{ width: `${maiorLoja > 0 ? (linha.valor / maiorLoja) * 100 : 0}%` }} />
                  </i>
                  <div className="despesas-lista-rodape">
                    <em>{formatPercent(totalLojas > 0 ? (linha.valor / totalLojas) * 100 : 0, 1)} do total</em>
                  </div>
                </li>
              ))}
            </ul>
          </section>
        )}
      </div>
    </div>
  );
}
