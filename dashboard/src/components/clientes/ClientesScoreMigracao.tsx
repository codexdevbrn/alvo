import { Fragment, useEffect, useMemo, useState } from 'react';
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Label,
  Pie,
  PieChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import {
  AlertTriangle,
  ArrowDownRight,
  ArrowUpRight,
  ChevronDown,
  ChevronUp,
  Loader2,
  Shuffle,
  TrendingDown,
  UsersRound,
} from 'lucide-react';
import { DonutFuro } from '../DonutFuro';
import { StatCard } from '../StatCard';
import {
  obterPainelClientes,
  type PainelClientesResposta,
  type RankingScorePainel,
} from '../../api/client';
import { formatNumber, formatPercent } from '../../utils/formatters';
import { useMesesFechados } from '../../hooks/useMesesFechados';
import { useVersaoCortesRelatorios } from '../../hooks/useVersaoCortesRelatorios';
import { useGruposClientesFiltro } from '../../hooks/useGruposClientesFiltro';
import { gruposClientesParam } from '../../utils/gruposClientesFiltro';
import { ClienteCausaMigracaoDetalhe } from './ClienteCausaMigracaoDetalhe';

interface Props {
  empresa: string;
  loja?: string | null;
  onCarregandoChange?: (carregando: boolean) => void;
}

/** Vermelho na pior cauda, âmbar no meio, verde em quem só sobe — mesma
 *  ordem de severidade de --danger/--warning/--success do projeto. */
const CORES_FAIXA_SCORE: Record<string, string> = {
  '≤ -5': 'var(--danger)',
  '-4 a -1': 'var(--warning)',
  '+1 ou mais': 'var(--success)',
};

function TooltipSaldoScore({
  active,
  payload,
}: {
  active?: boolean;
  payload?: Array<{ payload?: { rotulo: string; subiu: number; desceu: number; saldo: number } }>;
}) {
  const ponto = payload?.[0]?.payload;
  if (!active || !ponto) return null;
  return (
    <div className="vendedores-chart-tooltip">
      <strong>{ponto.rotulo}</strong>
      <dl>
        <div><dt>Subiu de faixa</dt><dd>{formatNumber(ponto.subiu)}</dd></div>
        <div><dt>Desceu de faixa</dt><dd>{formatNumber(ponto.desceu)}</dd></div>
        <div><dt>Saldo</dt><dd>{ponto.saldo > 0 ? '+' : ''}{formatNumber(ponto.saldo)}</dd></div>
      </dl>
    </div>
  );
}

function TooltipFaixaScore({
  active,
  payload,
}: {
  active?: boolean;
  payload?: Array<{ payload?: { faixa: string; clientes: number; participacao: number } }>;
}) {
  const fatia = payload?.[0]?.payload;
  if (!active || !fatia) return null;
  return (
    <div className="vendedores-chart-tooltip">
      <strong>{fatia.faixa}</strong>
      <dl>
        <div><dt>Clientes</dt><dd>{formatNumber(fatia.clientes)}</dd></div>
        <div><dt>Participação</dt><dd>{formatPercent(fatia.participacao, 1)}</dd></div>
      </dl>
    </div>
  );
}

function LinhaScoreCliente({
  item,
  posicao,
  aberto,
  onAlternar,
}: {
  item: RankingScorePainel;
  posicao: number;
  aberto: boolean;
  onAlternar: (cliente: string) => void;
}) {
  const positivo = item.score > 0;
  return (
    <li className="clientes-ranking-linha-clicavel">
      <button
        type="button"
        className={`clientes-score-linha-btn${aberto ? ' is-aberto' : ''}`}
        onClick={() => onAlternar(item.cliente)}
        aria-expanded={aberto}
        title={aberto ? `Fechar migrações de ${item.cliente}` : `Ver por que o score de ${item.cliente} é esse`}
      >
        <span className="clientes-ranking-numero">{posicao}</span>
        <strong title={item.cliente}>{item.cliente}</strong>
        <span className={`clientes-score-valor ${positivo ? 'is-alta' : 'is-queda'}`}>
          {positivo ? '+' : ''}{item.score}
        </span>
        <span className="clientes-score-migra">
          <ArrowUpRight size={11} aria-hidden="true" />{item.subiu}
          <ArrowDownRight size={11} aria-hidden="true" />{item.desceu}
        </span>
        <span className="clientes-score-permanencia">{formatPercent(item.permanencia, 0)}</span>
        {aberto
          ? <ChevronUp size={14} className="clientes-score-chevron" aria-hidden="true" />
          : <ChevronDown size={14} className="clientes-score-chevron" aria-hidden="true" />}
      </button>
    </li>
  );
}

/** Aba "Score e migração" da tela de Clientes: migração de faixa ABC mês a
 *  mês (score +3/-2, distribuição, saldo mensal e rankings). Mesmo endpoint
 *  do painel da Visão geral (`obterPainelClientes`) — o cache por chave
 *  evita um segundo request se a outra aba já carregou primeiro. */
export function ClientesScoreMigracao({ empresa, loja = null, onCarregandoChange }: Props) {
  const [dados, setDados] = useState<PainelClientesResposta | null>(null);
  const [carregando, setCarregando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);
  const [clientePiorCauda, setClientePiorCauda] = useState<string | null>(null);
  const [clienteMelhores, setClienteMelhores] = useState<string | null>(null);
  const [modoPeriodo] = useMesesFechados();
  const versaoCortes = useVersaoCortesRelatorios();
  const gruposClientes = useGruposClientesFiltro();
  const gruposParam = gruposClientesParam(gruposClientes);

  useEffect(() => {
    onCarregandoChange?.(carregando);
  }, [carregando, onCarregandoChange]);

  useEffect(() => {
    let vivo = true;
    setCarregando(true);
    setErro(null);
    void obterPainelClientes(empresa, loja, undefined, modoPeriodo, gruposParam)
      .then((resposta) => {
        if (vivo) setDados(resposta);
      })
      .catch((falha) => {
        if (!vivo) return;
        setDados(null);
        setErro(falha instanceof Error ? falha.message : 'Falha ao carregar o score de migração.');
      })
      .finally(() => {
        if (vivo) setCarregando(false);
      });
    return () => {
      vivo = false;
    };
  }, [empresa, loja, modoPeriodo, versaoCortes, gruposParam]);

  const scoreMigracao = dados?.score_migracao;

  const totalMigrouScore = useMemo(
    () => (scoreMigracao?.distribuicao ?? []).reduce((total, item) => total + item.clientes, 0),
    [scoreMigracao],
  );

  const percentPositivoScore = useMemo(() => {
    if (!scoreMigracao || totalMigrouScore === 0) return 0;
    const positivo = scoreMigracao.distribuicao.find((item) => item.faixa === '+1 ou mais')?.clientes ?? 0;
    return (positivo / totalMigrouScore) * 100;
  }, [scoreMigracao, totalMigrouScore]);

  const fatiasScore = useMemo(() => {
    if (!scoreMigracao || totalMigrouScore === 0) return [];
    return scoreMigracao.distribuicao
      .filter((item) => item.clientes > 0)
      .map((item) => ({ ...item, participacao: (item.clientes / totalMigrouScore) * 100 }));
  }, [scoreMigracao, totalMigrouScore]);

  if (carregando && !dados) {
    return (
      <div className="glass-card vendedores-carregando" role="status">
        <Loader2 size={20} className="dashboard-filter-spinner" /> Calculando o score de migração…
      </div>
    );
  }

  if (erro) {
    return (
      <div className="glass-card glass-card-flat analisador-erro" role="alert">
        <AlertTriangle size={17} /> {erro}
      </div>
    );
  }

  if (!dados || !scoreMigracao) return null;

  if (!dados.disponivel) {
    return (
      <div className="glass-card glass-card-flat clientes-vazio" role="status">
        <UsersRound size={24} aria-hidden="true" />
        <div>
          <strong>Sem dados para o painel</strong>
          <p>{dados.mensagem || 'A base desta empresa não tem período mensal utilizável.'}</p>
        </div>
      </div>
    );
  }

  return (
    <div className="clientes-visao">
      <section className="clientes-score-secao">
        <header className="clientes-visao-card-topo">
          <div>
            <h2>Score de migração de faixa</h2>
            <p>
              Subidas de faixa ABC valem +3, descidas valem -2, acumulado nos últimos{' '}
              {scoreMigracao.janela_meses} meses.
            </p>
          </div>
        </header>

        {!scoreMigracao.disponivel ? (
          <p className="analisador-hint">Histórico insuficiente para calcular migração de faixa.</p>
        ) : (
          <>
            <div className="clientes-score-kpis">
              <StatCard
                title="Clientes com score ≠ 0"
                value={formatNumber(scoreMigracao.clientes_score_diferente_zero)}
                icon={Shuffle}
              />
              <StatCard
                title="Pior cauda (score ≤ -5)"
                value={formatNumber(scoreMigracao.clientes_pior_cauda)}
                icon={TrendingDown}
              />
            </div>

            <div className="clientes-visao-grade">
              <section className="glass-card glass-card-flat clientes-visao-card">
                <header className="clientes-visao-card-topo">
                  <div>
                    <h2>Clientes que migraram, por faixa de score</h2>
                    <p>Exclui score 0 — só quem migrou de faixa ABC na janela.</p>
                  </div>
                </header>
                {totalMigrouScore === 0 ? (
                  <p className="analisador-hint">Nenhum cliente migrou de faixa na janela.</p>
                ) : (
                  <>
                    <div className="donut-linha">
                      <div className="donut">
                        <ResponsiveContainer width="100%" height={168}>
                          <PieChart>
                            <Pie
                              data={fatiasScore}
                              dataKey="clientes"
                              nameKey="faixa"
                              cx="50%"
                              cy="50%"
                              innerRadius={52}
                              outerRadius={78}
                              paddingAngle={2}
                              // Piso de ângulo: "≤ -5" costuma ser 1 cliente em
                              // ~1400 (0,1%) — sem isso a fatia vermelha soma
                              // menos de 1° e desaparece do anel (mesmo problema
                              // que a barra proporcional já resolvia com raiz
                              // quadrada; aqui o Recharts resolve com minAngle).
                              minAngle={4}
                              stroke="var(--bg-card)"
                              strokeWidth={2}
                            >
                              {fatiasScore.map((item) => (
                                <Cell key={item.faixa} fill={CORES_FAIXA_SCORE[item.faixa]} />
                              ))}
                            </Pie>
                            <Label
                              content={(props) => (
                                <DonutFuro
                                  valor={formatPercent(percentPositivoScore, 0)}
                                  legenda="subiu de faixa"
                                  viewBox={props.viewBox as { cx?: number; cy?: number } | undefined}
                                />
                              )}
                            />
                            <Tooltip content={<TooltipFaixaScore />} />
                          </PieChart>
                        </ResponsiveContainer>
                      </div>
                      <ul className="donut-legenda">
                        {scoreMigracao.distribuicao.map((item) => (
                          <li key={item.faixa}>
                            <i style={{ background: CORES_FAIXA_SCORE[item.faixa] }} aria-hidden="true" />
                            <span title={item.faixa}>{item.faixa}</span>
                            <strong>{formatNumber(item.clientes)}</strong>
                            <em>{formatPercent((item.clientes / totalMigrouScore) * 100, 1)}</em>
                          </li>
                        ))}
                      </ul>
                    </div>
                    <p className="clientes-visao-card-nota clientes-visao-card-rodape">
                      {formatPercent(percentPositivoScore, 1)} de quem migrou subiu de faixa;{' '}
                      {formatPercent(100 - percentPositivoScore, 1)} desceu.
                    </p>
                  </>
                )}
              </section>

              <section className="glass-card glass-card-flat clientes-visao-card">
                <header className="clientes-visao-card-topo">
                  <div>
                    <h2>Saldo de migrações por mês</h2>
                    <p>Subiu menos desceu de faixa, mês a mês.</p>
                  </div>
                </header>
                <div className="vendedores-chart clientes-visao-chart">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart
                      data={scoreMigracao.saldo_por_periodo}
                      margin={{ top: 8, right: 8, left: 0, bottom: 4 }}
                    >
                      <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" vertical={false} />
                      <XAxis
                        dataKey="rotulo_curto"
                        tick={{ fill: 'var(--text-secondary)', fontSize: 11 }}
                        axisLine={false}
                        tickLine={false}
                        interval={0}
                      />
                      <YAxis
                        tick={{ fill: 'var(--text-muted)', fontSize: 11 }}
                        axisLine={false}
                        tickLine={false}
                        width={32}
                        allowDecimals={false}
                      />
                      <Tooltip cursor={{ fill: 'var(--surface-2)' }} content={<TooltipSaldoScore />} />
                      <ReferenceLine y={0} stroke="var(--border-strong)" />
                      <Bar dataKey="saldo" maxBarSize={26}>
                        {scoreMigracao.saldo_por_periodo.map((item) => (
                          <Cell
                            key={item.periodo_atual}
                            fill={item.saldo >= 0 ? 'var(--success)' : 'var(--danger)'}
                          />
                        ))}
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              </section>
            </div>

            <div className="clientes-visao-grade">
              <section className="glass-card glass-card-flat clientes-visao-card">
                <header className="clientes-visao-card-topo">
                  <div>
                    <h2>Pior cauda</h2>
                    <p>Clientes com score negativo, do pior para o menos pior.</p>
                  </div>
                </header>
                {scoreMigracao.pior_cauda.length === 0 ? (
                  <p className="analisador-hint">Nenhum cliente com score negativo.</p>
                ) : (
                  <ul className="clientes-score-tabela">
                    {scoreMigracao.pior_cauda.map((item, indice) => (
                      <Fragment key={item.cliente}>
                        <LinhaScoreCliente
                          item={item}
                          posicao={indice + 1}
                          aberto={clientePiorCauda === item.cliente}
                          onAlternar={(cliente) => setClientePiorCauda((atual) => (atual === cliente ? null : cliente))}
                        />
                        {clientePiorCauda === item.cliente && (
                          <ClienteCausaMigracaoDetalhe
                            empresa={empresa}
                            cliente={item.cliente}
                            loja={loja}
                            modoPeriodo={modoPeriodo}
                            grupos={gruposParam}
                          />
                        )}
                      </Fragment>
                    ))}
                  </ul>
                )}
              </section>

              <section className="glass-card glass-card-flat clientes-visao-card">
                <header className="clientes-visao-card-topo">
                  <div>
                    <h2>Melhores scores</h2>
                    <p>Clientes com score positivo, do melhor para o menos bom.</p>
                  </div>
                </header>
                {scoreMigracao.melhores.length === 0 ? (
                  <p className="analisador-hint">Nenhum cliente com score positivo.</p>
                ) : (
                  <ul className="clientes-score-tabela">
                    {scoreMigracao.melhores.map((item, indice) => (
                      <Fragment key={item.cliente}>
                        <LinhaScoreCliente
                          item={item}
                          posicao={indice + 1}
                          aberto={clienteMelhores === item.cliente}
                          onAlternar={(cliente) => setClienteMelhores((atual) => (atual === cliente ? null : cliente))}
                        />
                        {clienteMelhores === item.cliente && (
                          <ClienteCausaMigracaoDetalhe
                            empresa={empresa}
                            cliente={item.cliente}
                            loja={loja}
                            modoPeriodo={modoPeriodo}
                            grupos={gruposParam}
                          />
                        )}
                      </Fragment>
                    ))}
                  </ul>
                )}
              </section>
            </div>
          </>
        )}
      </section>
    </div>
  );
}
