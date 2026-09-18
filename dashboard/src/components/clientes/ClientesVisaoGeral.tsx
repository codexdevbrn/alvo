import { useEffect, useMemo, useState, type CSSProperties } from 'react';
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
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
  Banknote,
  Loader2,
  Receipt,
  UserPlus,
  UsersRound,
} from 'lucide-react';
import { StatCard } from '../StatCard';
import { LeituraFaixa } from '../LeituraFaixa';
import {
  obterPainelClientes,
  type EventoCarteira,
  type PainelClientesResposta,
  type TopClientePainel,
} from '../../api/client';
import { formatCompacto, formatCurrency, formatNumber, formatPercent } from '../../utils/formatters';
import { useMesesFechados } from '../../hooks/useMesesFechados';
import { useVersaoCortesRelatorios } from '../../hooks/useVersaoCortesRelatorios';
import { useGruposClientesFiltro } from '../../hooks/useGruposClientesFiltro';
import { gruposClientesParam } from '../../utils/gruposClientesFiltro';

interface Props {
  empresa: string;
  loja?: string | null;
  onCarregandoChange?: (carregando: boolean) => void;
}

type AbaEvento = 'recuperados' | 'novos' | 'perdidos';

/** Ouro do acento para a faixa mais forte, esfriando até o cinza de "Demais". */
const CORES_FAIXA = ['#dabb6c', '#c2a45f', '#8e8a7d', '#5d5d66', '#43434b'];
const COR_NOVOS = '#4cae7a';
const COR_RECUPERADOS = '#dabb6c';
const COR_PERDIDOS = '#e0645c';

const ROTULOS_EVENTO: Record<AbaEvento, string> = {
  recuperados: 'Recuperados',
  novos: 'Novos',
  perdidos: 'Perdidos',
};

const CORES_EVENTO: Record<AbaEvento, string> = {
  novos: COR_NOVOS,
  recuperados: COR_RECUPERADOS,
  perdidos: COR_PERDIDOS,
};

function textoVariacao(valor: number | null | undefined): string {
  if (valor == null || !Number.isFinite(valor)) return '—';
  return `${valor > 0 ? '+' : ''}${formatPercent(valor, 1)}`;
}

function classeVariacao(valor: number | null | undefined): string {
  if (valor == null) return '';
  if (valor <= -20) return 'is-queda';
  if (valor >= 20) return 'is-alta';
  return '';
}

/** Filete lateral da linha: vermelho na queda, verde na alta, nada no meio.
 *  Mesma régua de 20% da cor do percentual — o `alerta` vem pronto do backend. */
function classeLinha(variacao: number | null, alerta: boolean): string {
  if (alerta) return 'is-alerta';
  if (variacao != null && variacao >= 20) return 'is-destaque';
  return '';
}

function TooltipMovimento({
  active,
  payload,
  label,
}: {
  active?: boolean;
  payload?: Array<{ payload?: { novos: number; recuperados: number; perdidos: number } }>;
  label?: string;
}) {
  const ponto = payload?.[0]?.payload;
  if (!active || !ponto) return null;
  return (
    <div className="vendedores-chart-tooltip">
      <strong>{label}</strong>
      <dl>
        <div><dt>Novos</dt><dd>{formatNumber(ponto.novos)}</dd></div>
        <div><dt>Recuperados</dt><dd>{formatNumber(ponto.recuperados)}</dd></div>
        <div><dt>Perdidos</dt><dd>{formatNumber(ponto.perdidos)}</dd></div>
      </dl>
    </div>
  );
}

function maiorFamilia(resumo: { perdidos: number; novos: number; recuperados: number }): AbaEvento {
  const familias: [AbaEvento, number][] = [
    ['perdidos', resumo.perdidos],
    ['novos', resumo.novos],
    ['recuperados', resumo.recuperados],
  ];
  familias.sort((a, b) => b[1] - a[1]);
  return familias[0][0];
}

/** Largura da barra de ranking, em %, relativa ao maior valor da lista.
 *  Raiz quadrada em vez de proporção linear: um outlier (ex.: "CLIENTE
 *  BALCÃO" concentrando venda avulsa) não pode reduzir a barra de todo o
 *  resto a um traço invisível — a ordem se mantém, só a escala comprime. */
function barraRanking(valor: number, maior: number): number {
  if (maior <= 0 || valor <= 0) return 0;
  return Math.max(0, Math.min(100, Math.sqrt(valor / maior) * 100));
}

function LinhaMaiorCliente({
  item,
  posicao,
  maiorReceita,
}: {
  item: TopClientePainel;
  posicao: number;
  maiorReceita: number;
}) {
  return (
    <li className={classeLinha(item.variacao, item.alerta)}>
      <div className="clientes-ranking-topo">
        <span className="clientes-ranking-numero">{posicao}</span>
        <strong title={item.cliente}>{item.cliente}</strong>
        <span className="clientes-ranking-valor">{formatCurrency(item.receita_atual)}</span>
      </div>
      <div className="clientes-ranking-barra" aria-hidden="true">
        <i style={{ width: `${barraRanking(item.receita_atual, maiorReceita)}%` }} />
      </div>
      <div className="clientes-ranking-rodape">
        <span>média {formatCurrency(item.receita_media)}</span>
        <em className={classeVariacao(item.variacao)}>
          {item.variacao != null && item.variacao !== 0 && (
            item.variacao > 0
              ? <ArrowUpRight size={12} aria-hidden="true" />
              : <ArrowDownRight size={12} aria-hidden="true" />
          )}
          {textoVariacao(item.variacao)}
        </em>
      </div>
    </li>
  );
}

function ListaEventos({ itens, evento }: { itens: EventoCarteira[]; evento: AbaEvento }) {
  if (itens.length === 0) {
    return <p className="analisador-hint">Nenhum cliente {ROTULOS_EVENTO[evento].toLowerCase()} neste mês.</p>;
  }
  const maiorValor = Math.max(...itens.map((item) => item.receita), 1);
  return (
    <ul className="clientes-eventos-lista custom-scrollbar">
      {itens.map((item, indice) => (
        <li key={`${evento}-${item.cliente}`}>
          <div className="clientes-ranking-topo">
            <span className="clientes-ranking-numero">{indice + 1}</span>
            <strong title={item.cliente}>{item.cliente}</strong>
            <span className="clientes-ranking-valor">{formatCurrency(item.receita)}</span>
          </div>
          <div className="clientes-ranking-barra" aria-hidden="true">
            <i style={{ width: `${barraRanking(item.receita, maiorValor)}%`, background: CORES_EVENTO[evento] }} />
          </div>
          {item.ultimo_mes && (
            <div className="clientes-ranking-rodape">
              <span className="clientes-evento-selo">última compra {item.ultimo_mes}</span>
            </div>
          )}
        </li>
      ))}
    </ul>
  );
}

/** Aba 1 da tela de Clientes: retrato da carteira no mês de referência da base. */
export function ClientesVisaoGeral({ empresa, loja = null, onCarregandoChange }: Props) {
  const [dados, setDados] = useState<PainelClientesResposta | null>(null);
  const [carregando, setCarregando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);
  const [abaEvento, setAbaEvento] = useState<AbaEvento>('perdidos');
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
        setErro(falha instanceof Error ? falha.message : 'Falha ao carregar o painel de clientes.');
      })
      .finally(() => {
        if (vivo) setCarregando(false);
      });
    return () => {
      vivo = false;
    };
  }, [empresa, loja, modoPeriodo, versaoCortes, gruposParam]);

  useEffect(() => {
    if (dados?.resumo) setAbaEvento(maiorFamilia(dados.resumo));
  }, [dados]);

  const movimento = useMemo(
    () => (dados?.movimento ?? []).map((mes) => ({
      ...mes,
      // Perdidos descem do zero: entrada e saída não podem empilhar como se
      // fossem a mesma coisa.
      perdidos_grafico: -mes.perdidos,
    })),
    [dados],
  );

  const maiorReceitaTop = useMemo(
    () => Math.max(...(dados?.top_clientes ?? []).map((item) => item.receita_atual), 1),
    [dados],
  );

  if (carregando && !dados) {
    return (
      <div className="glass-card vendedores-carregando" role="status">
        <Loader2 size={20} className="dashboard-filter-spinner" /> Montando a visão da carteira…
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

  if (!dados) return null;

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

  const { resumo, concentracao } = dados;
  const eventos = dados.eventos[abaEvento];
  const familiaDestaque = maiorFamilia(resumo);
  const avisoAberto = modoPeriodo === 'completo' && (resumo.variacao_receita ?? 0) <= -40;
  const maiorFaixa = Math.max(0, ...concentracao.faixas.map((faixa) => faixa.receita));

  return (
    <div className="clientes-visao">
      <p className="clientes-visao-referencia">
        Mês de referência <strong>{dados.rotulo_periodo}</strong> contra a média de {dados.meses_media} meses.
        {' '}Janela de inatividade: {dados.janela_inatividade_meses} meses.
        {dados.balcao_excluidos > 0 && ` ${formatNumber(dados.balcao_excluidos)} cliente(s) de balcão fora do painel.`}
      </p>

      <LeituraFaixa tom={avisoAberto ? 'aviso' : (resumo.saldo < 0 ? 'aviso' : 'normal')}>
        {avisoAberto
          ? `${dados.rotulo_periodo} ainda pode estar em aberto e comparado contra meses fechados. `
          : ''}
        Saldo {resumo.saldo > 0 ? '+' : ''}{formatNumber(resumo.saldo)}:
        {' '}{formatNumber(resumo.perdidos)} perdidos, {formatNumber(resumo.novos)} novos, {formatNumber(resumo.recuperados)} recuperados.
        {' '}Maior movimento: {ROTULOS_EVENTO[familiaDestaque].toLowerCase()}.
      </LeituraFaixa>

      <section className="vendedores-kpis" aria-label="Indicadores da carteira">
        <article className="glass-card glass-card-flat vendedores-hero vendedores-hero-com-spark">
          <div className="despesas-hero-texto">
            <p className="despesas-hero-rotulo">
              <UserPlus size={14} aria-hidden="true" /> Saldo da carteira
            </p>
            <strong className="despesas-hero-valor">
              {resumo.saldo > 0 ? '+' : ''}{formatNumber(resumo.saldo)}
            </strong>
            <p className={`despesas-hero-nota${resumo.saldo >= 0 ? ' is-alta' : ' is-queda'}`}>
              {formatNumber(resumo.novos)} novos · {formatNumber(resumo.recuperados)} recuperados · {formatNumber(resumo.perdidos)} perdidos
            </p>
          </div>
          {dados.movimento.length > 1 && (
            <div className="despesas-hero-spark" aria-hidden="true">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={dados.movimento} margin={{ top: 4, right: 0, left: 0, bottom: 0 }}>
                  <defs>
                    <linearGradient id="clientesHeroFill" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor="var(--accent)" stopOpacity={0.35} />
                      <stop offset="100%" stopColor="var(--accent)" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <Area
                    type="monotone"
                    dataKey="saldo"
                    stroke="var(--accent)"
                    strokeWidth={2}
                    fill="url(#clientesHeroFill)"
                    dot={false}
                    isAnimationActive={false}
                  />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          )}
        </article>
        <div className="vendedores-kpis-secundarios">
          <StatCard
            title="Clientes ativos"
            value={formatNumber(resumo.clientes_ativos)}
            icon={UsersRound}
            trend={resumo.variacao_clientes == null
              ? undefined
              : `${textoVariacao(resumo.variacao_clientes)} vs média (${formatNumber(Math.round(resumo.clientes_media))})`}
            trendUp={(resumo.variacao_clientes ?? 0) >= 0}
            useTrendColor={resumo.variacao_clientes != null}
          />
          <StatCard
            title={`Receita de ${dados.rotulo_periodo}`}
            value={formatCompacto(resumo.receita_atual, true)}
            icon={Banknote}
            trend={resumo.variacao_receita == null
              ? undefined
              : `${textoVariacao(resumo.variacao_receita)} vs ${formatCurrency(resumo.receita_media)}`}
            trendUp={(resumo.variacao_receita ?? 0) >= 0}
            useTrendColor={resumo.variacao_receita != null}
          />
          <StatCard
            title="Ticket médio por cliente"
            value={formatCurrency(resumo.ticket_medio)}
            icon={Receipt}
            trend={resumo.variacao_ticket == null
              ? undefined
              : `${textoVariacao(resumo.variacao_ticket)} vs ${formatCurrency(resumo.ticket_medio_media)}`}
            trendUp={(resumo.variacao_ticket ?? 0) >= 0}
            useTrendColor={resumo.variacao_ticket != null}
          />
        </div>
      </section>

      <div className="clientes-visao-grade">
        <section className="glass-card glass-card-flat clientes-visao-card">
          <header className="clientes-visao-card-topo">
            <div>
              <h2>Concentração da carteira</h2>
              <p>Curva ABC dos últimos {dados.janela_abc_meses} meses, nos cortes do Analisador.</p>
            </div>
            <span className="clientes-visao-card-nota">{formatNumber(concentracao.clientes)} clientes</span>
          </header>
          {concentracao.faixas.length === 0 ? (
            <p className="analisador-hint">Sem receita na janela da curva.</p>
          ) : (
            <>
              <p className="clientes-concentracao-punch">
                <strong>{formatNumber(concentracao.clientes_80)}</strong>
                <span>clientes fazem 80% da receita</span>
                <em>{formatPercent(concentracao.participacao_clientes_80, 1)} da carteira</em>
              </p>
              <ul className="estoque-barras">
                {concentracao.faixas.map((faixa, indice) => (
                  <li key={faixa.nome}>
                    <span title={faixa.nome}>{faixa.nome}</span>
                    <i aria-hidden="true">
                      <b style={{
                        width: `${maiorFaixa > 0 ? (faixa.receita / maiorFaixa) * 100 : 0}%`,
                        background: CORES_FAIXA[indice % CORES_FAIXA.length],
                      }}
                      />
                    </i>
                    <strong>{formatNumber(faixa.clientes)}</strong>
                    <em>{formatPercent(faixa.participacao, 1)}</em>
                  </li>
                ))}
              </ul>
            </>
          )}

          {dados.tags.length > 0 && (
            <div className="clientes-visao-tags clientes-visao-card-rodape">
              <p className="clientes-visao-tags-titulo">Receita por tag na mesma janela</p>
              <div className="clientes-visao-tags-grade">
                {dados.tags.map((tag) => (
                  <article
                    key={tag.id}
                    className="clientes-tag-chip"
                    style={{ '--tag-cor': tag.cor || 'var(--accent)' } as CSSProperties}
                  >
                    <p className="clientes-tag-chip-topo">
                      <i aria-hidden="true" />
                      <span>{tag.rotulo}</span>
                      <em>{formatNumber(tag.clientes)}</em>
                    </p>
                    <strong>{formatCurrency(tag.receita)}</strong>
                    <span className="clientes-tag-chip-barra" aria-hidden="true">
                      <i style={{ width: `${Math.min(tag.participacao, 100)}%` }} />
                    </span>
                    <small>{formatPercent(tag.participacao, 1)} da receita</small>
                  </article>
                ))}
              </div>
            </div>
          )}
        </section>

        <section className="glass-card glass-card-flat clientes-visao-card">
          <header className="clientes-visao-card-topo">
            <div>
              <h2>Entrada e saída de clientes</h2>
              <p>Novos e recuperados sobem; perdidos descem. Cada cliente conta uma vez por evento.</p>
            </div>
          </header>
          <p className="vendedores-chart-legenda clientes-visao-legenda">
            <span><i style={{ background: COR_NOVOS }} aria-hidden="true" /> Novos</span>
            <span><i style={{ background: COR_RECUPERADOS }} aria-hidden="true" /> Recuperados</span>
            <span><i style={{ background: COR_PERDIDOS }} aria-hidden="true" /> Perdidos</span>
          </p>
          <div className="vendedores-chart clientes-visao-chart">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={movimento} margin={{ top: 8, right: 8, left: 0, bottom: 4 }} stackOffset="sign">
                <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" vertical={false} />
                <XAxis
                  dataKey="rotulo"
                  tick={{ fill: 'var(--text-secondary)', fontSize: 11 }}
                  axisLine={false}
                  tickLine={false}
                  interval={0}
                />
                <YAxis
                  tickFormatter={(v) => formatCompacto(Math.abs(Number(v)))}
                  tick={{ fill: 'var(--text-muted)', fontSize: 11 }}
                  axisLine={false}
                  tickLine={false}
                  width={40}
                />
                <Tooltip cursor={{ fill: 'var(--surface-2)' }} content={<TooltipMovimento />} />
                <ReferenceLine y={0} stroke="var(--border-strong)" />
                <Bar dataKey="novos" stackId="carteira" fill={COR_NOVOS} maxBarSize={26} />
                <Bar dataKey="recuperados" stackId="carteira" fill={COR_RECUPERADOS} maxBarSize={26} />
                <Bar dataKey="perdidos_grafico" stackId="carteira" fill={COR_PERDIDOS} maxBarSize={26} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </section>

        <section className="glass-card glass-card-flat clientes-visao-card">
          <header className="clientes-visao-card-topo">
            <div>
              <h2>Movimento de {dados.rotulo_periodo}</h2>
              <p>Quem entrou, voltou ou parou de comprar — até 20 nomes, do maior valor para o menor.</p>
            </div>
          </header>
          <div className="analisador-tabs custom-scrollbar" role="tablist" aria-label="Evento da carteira">
            {(Object.keys(ROTULOS_EVENTO) as AbaEvento[]).map((chave) => (
              <button
                key={chave}
                type="button"
                role="tab"
                aria-selected={abaEvento === chave}
                className={`analisador-tab${abaEvento === chave ? ' is-ativa' : ''}`}
                onClick={() => setAbaEvento(chave)}
              >
                {ROTULOS_EVENTO[chave]} ({formatNumber(resumo[chave])})
              </button>
            ))}
          </div>
          <ListaEventos itens={eventos} evento={abaEvento} />
        </section>

      
        <section className="glass-card glass-card-flat clientes-visao-card">
          <header className="clientes-visao-card-topo">
            <div>
              <h2>Maiores clientes de {dados.rotulo_periodo}</h2>
              <p>Receita do mês contra a média de {dados.meses_media} meses.</p>
            </div>
          </header>
          {dados.top_clientes.length === 0 ? (
            <p className="analisador-hint">Sem venda no mês de referência.</p>
          ) : (
            <ul className="clientes-eventos-lista custom-scrollbar">
              {dados.top_clientes.map((item, indice) => (
                <LinhaMaiorCliente
                  key={item.cliente}
                  item={item}
                  posicao={indice + 1}
                  maiorReceita={maiorReceitaTop}
                />
              ))}
            </ul>
          )}
        </section>
      </div>
    </div>
  );
}
