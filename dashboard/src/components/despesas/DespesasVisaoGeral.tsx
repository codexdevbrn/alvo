import { useEffect, useState } from 'react';
import { AlertTriangle, Loader2, Receipt, TrendingDown, TrendingUp, Wallet } from 'lucide-react';
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Label,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { StatCard } from '../StatCard';
import { DonutFuro } from '../DonutFuro';
import {
  obterResumoDespesas,
  type GrupoAbcDespesa,
  type ItemDespesaCategoria,
  type ResumoDespesasResposta,
} from '../../api/client';
import { formatCompacto, formatCurrency, formatPercent, rotuloGrupoCurto } from '../../utils/formatters';
import { useMesesFechados } from '../../hooks/useMesesFechados';
import { modoParaBooleano } from '../../utils/mesesFechados';

type Props = {
  empresa: string;
  loja: string | null;
  meses: number;
};

// Mesma paleta de `ExplorarBuilder` (derivada da marca), para as categorias do
// empilhado mensal. "Outras" fica cinza — mesmo tom do "Demais" da curva ABC,
// não uma cor de destaque disputando atenção com quem importa.
const CORES_CATEGORIA = ['#dabb6c', '#6f8cc4', '#68818d', '#cc6300', '#8aa3ad', '#4cae7a'];
const COR_OUTRAS = '#5d5d66';

// Ouro → cinza, mesma progressão de `CORES_FAIXA` em Clientes: a faixa mais
// forte puxa o acento, "Demais" esfria pro neutro.
const CORES_GRUPO = ['#dabb6c', '#6f8cc4', '#68818d', '#5d5d66'];

function corCategoria(categoria: string, indice: number): string {
  return categoria === 'Outras' ? COR_OUTRAS : CORES_CATEGORIA[indice % CORES_CATEGORIA.length];
}

function corGrupo(grupo: string | null, grupos: GrupoAbcDespesa[]): string {
  const indice = grupos.findIndex((item) => item.grupo === grupo);
  return indice >= 0 ? CORES_GRUPO[indice % CORES_GRUPO.length] : 'var(--accent)';
}

type EntradaComposicao = { dataKey?: string; name?: string; value?: number; color?: string };

function TooltipComposicao({
  active,
  payload,
  label,
}: {
  active?: boolean;
  payload?: EntradaComposicao[];
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
            <dt>{item.name}</dt>
            <dd>{formatCurrency(Number(item.value) || 0)}</dd>
          </div>
        ))}
        <div><dt>Total</dt><dd>{formatCurrency(total)}</dd></div>
      </dl>
    </div>
  );
}

function TooltipGrupo({ active, payload }: { active?: boolean; payload?: { payload: GrupoAbcDespesa }[] }) {
  if (!active || !payload?.length) return null;
  const grupo = payload[0].payload;
  return (
    <div className="vendedores-chart-tooltip">
      <strong>{grupo.grupo}</strong>
      <dl>
        <div><dt>Categorias</dt><dd>{grupo.quantidade}</dd></div>
        <div><dt>Valor</dt><dd>{formatCurrency(grupo.valor)}</dd></div>
        <div><dt>Participação</dt><dd>{formatPercent(grupo.pct, 1)}</dd></div>
      </dl>
    </div>
  );
}

function tendenciaTexto(item: ItemDespesaCategoria): string | null {
  if (item.tendencia_pct == null) return null;
  const seta = item.tendencia_pct >= 0 ? '↑' : '↓';
  return `${seta} ${formatPercent(Math.abs(item.tendencia_pct), 1)} na janela`;
}

/** Aba Visão geral: total, evolução mensal por categoria, concentração (curva
 *  ABC) e para onde o dinheiro foi — tudo derivado de Loja/categoria/Ano/Mês/Valor,
 *  os únicos campos que a Controladoria traz (sem fornecedor, forma de pagamento etc.). */
export function DespesasVisaoGeral({ empresa, loja, meses }: Props) {
  const [dados, setDados] = useState<ResumoDespesasResposta | null>(null);
  const [carregando, setCarregando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);
  const [modoPeriodo] = useMesesFechados();
  const usarMesesFechados = modoParaBooleano(modoPeriodo);

  useEffect(() => {
    const controller = new AbortController();
    setCarregando(true);
    setErro(null);
    void obterResumoDespesas(empresa, { loja, meses, usarMesesFechados }, controller.signal)
      .then(setDados)
      .catch((falha) => {
        if (falha instanceof DOMException && falha.name === 'AbortError') return;
        setDados(null);
        setErro(falha instanceof Error ? falha.message : 'Falha ao carregar as despesas.');
      })
      .finally(() => {
        if (!controller.signal.aborted) setCarregando(false);
      });
    return () => controller.abort();
  }, [empresa, loja, meses, usarMesesFechados]);

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
  const despesaCaiu = (resumo.variacao_pct ?? 0) < 0;
  const variacaoAnualConhecida = resumo.variacao_anual_pct != null;
  const despesaCaiuNoAno = (resumo.variacao_anual_pct ?? 0) < 0;
  const periodo = dados.periodo_inicio && dados.periodo_fim
    ? `${dados.periodo_inicio} a ${dados.periodo_fim}`
    : 'sem lançamentos';
  const maiorCategoria = dados.por_categoria[0]?.valor ?? 0;
  const maiorLoja = dados.por_loja[0]?.valor ?? 0;

  const composicaoMensal = dados.serie_mensal_categorias.pontos.map((ponto) => ({
    periodo: ponto.periodo,
    rotulo: ponto.rotulo,
    ...ponto.valores,
  }));
  const categoriasComposicao = dados.serie_mensal_categorias.categorias;

  const grupos = dados.curva_abc_categorias.grupos;
  const categoriaComMaisPeso = grupos[0];

  return (
    <div className="estoque-visao">
      <p className="estoque-visao-referencia">
        Despesas de <strong>{periodo}</strong>.
      </p>

      <section className="estoque-visao-kpis" aria-label="Indicadores de despesas">
        <StatCard title="Total no período" value={formatCurrency(resumo.total)} icon={Wallet} />
        <StatCard title="Média mensal" value={formatCurrency(resumo.media_mensal)} icon={Receipt} />
        <StatCard
          title="Último mês"
          value={formatCurrency(resumo.mes_atual)}
          icon={despesaCaiu ? TrendingDown : TrendingUp}
          trend={variacaoConhecida ? `${formatPercent(Math.abs(resumo.variacao_pct ?? 0), 1)} vs. mês anterior` : 'sem mês anterior para comparar'}
          trendUp={despesaCaiu}
          useTrendColor={variacaoConhecida}
        />
        <StatCard
          title="vs. mesmo mês ano passado"
          value={variacaoAnualConhecida ? `${formatPercent(Math.abs(resumo.variacao_anual_pct ?? 0), 1)}` : '—'}
          icon={despesaCaiuNoAno ? TrendingDown : TrendingUp}
          trend={variacaoAnualConhecida
            ? `era ${formatCurrency(resumo.mes_mesmo_periodo_ano_anterior ?? 0)}`
            : 'sem dado no ano anterior'}
          trendUp={despesaCaiuNoAno}
          useTrendColor={variacaoAnualConhecida}
        />
      </section>

      <section className="glass-card glass-card-flat estoque-visao-card">
        <header className="estoque-card-topo">
          <div>
            <h2>Despesas mês a mês, por categoria</h2>
            <p>Composição do total lançado em cada mês da janela selecionada.</p>
          </div>
        </header>
        {composicaoMensal.length === 0 ? (
          <p className="analisador-hint">Sem lançamentos nesta seleção.</p>
        ) : (
          <>
            <div className="vendedores-chart" style={{ height: 260 }}>
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

      <div className="estoque-visao-grade estoque-visao-grade-auto">
        <section className="glass-card glass-card-flat estoque-visao-card">
          <header className="estoque-card-topo">
            <div>
              <h2>Por categoria</h2>
              <p>Maiores categorias de despesa no período, com tendência dentro da janela.</p>
            </div>
            <span className="estoque-card-nota">{formatCurrency(resumo.total)}</span>
          </header>
          {dados.por_categoria.length === 0 ? (
            <p className="analisador-hint">Sem categorias nesta seleção.</p>
          ) : (
            <ul className="estoque-barras">
              {dados.por_categoria.map((linha) => {
                const tendencia = tendenciaTexto(linha);
                return (
                  <li key={linha.categoria}>
                    <span title={linha.categoria}>
                      {linha.grupo_abc && (
                        <b
                          className="despesas-grupo-chip"
                          title={linha.grupo_abc}
                          style={{ background: corGrupo(linha.grupo_abc, grupos) }}
                        >
                          {rotuloGrupoCurto(linha.grupo_abc)}
                        </b>
                      )}
                      {linha.categoria}
                    </span>
                    <i aria-hidden="true">
                      <b style={{
                        width: `${maiorCategoria > 0 ? (linha.valor / maiorCategoria) * 100 : 0}%`,
                        background: corGrupo(linha.grupo_abc, grupos),
                      }}
                      />
                    </i>
                    <strong>{formatCurrency(linha.valor)}</strong>
                    <em title={tendencia ?? undefined}>
                      {formatPercent(linha.pct, 1)}{tendencia ? ` · ${tendencia}` : ''}
                    </em>
                  </li>
                );
              })}
            </ul>
          )}
        </section>

        <section className="glass-card glass-card-flat estoque-visao-card">
          <header className="estoque-card-topo">
            <div>
              <h2>Concentração por categoria</h2>
              <p>Curva ABC das categorias no período, mesma régua de Clientes/Produtos.</p>
            </div>
          </header>
          {grupos.length === 0 ? (
            <p className="analisador-hint">Sem despesa na seleção para montar a curva.</p>
          ) : (
            <div className="donut-linha">
              <div className="donut">
                <ResponsiveContainer width="100%" height={168}>
                  <PieChart>
                    <Pie
                      data={grupos}
                      dataKey="valor"
                      nameKey="grupo"
                      innerRadius={52}
                      outerRadius={78}
                      paddingAngle={2}
                      stroke="var(--bg-card)"
                      strokeWidth={2}
                    >
                      {grupos.map((grupo, indice) => (
                        <Cell key={grupo.grupo} fill={CORES_GRUPO[indice % CORES_GRUPO.length]} />
                      ))}
                    </Pie>
                    <Label
                      content={(props) => (
                        <DonutFuro
                          valor={rotuloGrupoCurto(categoriaComMaisPeso?.grupo)}
                          legenda={`${formatPercent(categoriaComMaisPeso?.pct ?? 0, 0)} do gasto`}
                          viewBox={props.viewBox as { cx?: number; cy?: number } | undefined}
                        />
                      )}
                    />
                    <Tooltip content={<TooltipGrupo />} />
                  </PieChart>
                </ResponsiveContainer>
              </div>
              <ul className="donut-legenda">
                {grupos.map((grupo, indice) => (
                  <li key={grupo.grupo}>
                    <i style={{ background: CORES_GRUPO[indice % CORES_GRUPO.length] }} aria-hidden="true" />
                    <span>{rotuloGrupoCurto(grupo.grupo)}</span>
                    <strong>{grupo.quantidade}</strong>
                    <em>{formatPercent(grupo.pct, 1)}</em>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </section>

        {dados.por_loja.length > 1 && (
          <section className="glass-card glass-card-flat estoque-visao-card">
            <header className="estoque-card-topo">
              <div>
                <h2>Por loja</h2>
                <p>Despesas somadas por loja no período.</p>
              </div>
            </header>
            <ul className="estoque-barras">
              {dados.por_loja.map((linha) => (
                <li key={linha.loja}>
                  <span title={linha.loja}>{linha.loja}</span>
                  <i aria-hidden="true">
                    <b style={{ width: `${maiorLoja > 0 ? (linha.valor / maiorLoja) * 100 : 0}%` }} />
                  </i>
                  <strong>{formatCurrency(linha.valor)}</strong>
                </li>
              ))}
            </ul>
          </section>
        )}
      </div>
    </div>
  );
}
