import { useEffect, useMemo, useState, type CSSProperties } from 'react';
import {
  Bar,
  BarChart,
  Cell,
  CartesianGrid,
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
  Banknote,
  Loader2,
  Receipt,
  UserPlus,
  UsersRound,
} from 'lucide-react';
import { DonutFuro } from '../DonutFuro';
import { StatCard } from '../StatCard';
import {
  obterPainelClientes,
  type EventoCarteira,
  type PainelClientesResposta,
} from '../../api/client';
import { formatCompacto, formatCurrency, formatNumber, formatPercent } from '../../utils/formatters';
import { useMesesFechados } from '../../hooks/useMesesFechados';

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

function TooltipFaixa({
  active,
  payload,
}: {
  active?: boolean;
  payload?: Array<{ payload?: { nome: string; clientes: number; receita: number; participacao: number } }>;
}) {
  const ponto = payload?.[0]?.payload;
  if (!active || !ponto) return null;
  return (
    <div className="vendedores-chart-tooltip">
      <strong>{ponto.nome}</strong>
      <dl>
        <div><dt>Clientes</dt><dd>{formatNumber(ponto.clientes)}</dd></div>
        <div><dt>Receita</dt><dd>{formatCurrency(ponto.receita)}</dd></div>
        <div><dt>Participação</dt><dd>{formatPercent(ponto.participacao, 1)}</dd></div>
      </dl>
    </div>
  );
}

function ListaEventos({ itens, evento }: { itens: EventoCarteira[]; evento: AbaEvento }) {
  if (itens.length === 0) {
    return <p className="analisador-hint">Nenhum cliente {ROTULOS_EVENTO[evento].toLowerCase()} neste mês.</p>;
  }
  return (
    <ul className="clientes-eventos-lista custom-scrollbar">
      {itens.map((item) => (
        <li key={`${evento}-${item.cliente}`}>
          <strong title={item.cliente}>{item.cliente}</strong>
          {item.ultimo_mes && <span className="clientes-evento-selo">última compra {item.ultimo_mes}</span>}
          <span className="clientes-evento-valor">{formatCurrency(item.receita)}</span>
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
  const [abaEvento, setAbaEvento] = useState<AbaEvento>('recuperados');
  const [modoPeriodo] = useMesesFechados();

  useEffect(() => {
    onCarregandoChange?.(carregando);
  }, [carregando, onCarregandoChange]);

  useEffect(() => {
    const controller = new AbortController();
    setCarregando(true);
    setErro(null);
    void obterPainelClientes(empresa, loja, controller.signal, modoPeriodo)
      .then(setDados)
      .catch((falha) => {
        if (falha instanceof DOMException && falha.name === 'AbortError') return;
        setDados(null);
        setErro(falha instanceof Error ? falha.message : 'Falha ao carregar o painel de clientes.');
      })
      .finally(() => {
        if (!controller.signal.aborted) setCarregando(false);
      });
    return () => controller.abort();
  }, [empresa, loja, modoPeriodo]);

  const movimento = useMemo(
    () => (dados?.movimento ?? []).map((mes) => ({
      ...mes,
      // Perdidos descem do zero: entrada e saída não podem empilhar como se
      // fossem a mesma coisa.
      perdidos_grafico: -mes.perdidos,
    })),
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

  return (
    <div className="clientes-visao">
      <p className="clientes-visao-referencia">
        Mês de referência <strong>{dados.rotulo_periodo}</strong> contra a média de {dados.meses_media} meses.
        {' '}Janela de inatividade: {dados.janela_inatividade_meses} meses.
        {dados.balcao_excluidos > 0 && ` ${formatNumber(dados.balcao_excluidos)} cliente(s) de balcão fora do painel.`}
      </p>

      {modoPeriodo === 'completo' && (resumo.variacao_receita ?? 0) <= -40 && (
        <p className="clientes-visao-aviso" role="status">
          <AlertTriangle size={15} aria-hidden="true" />
          Queda forte contra a média. {dados.rotulo_periodo} ainda pode estar em aberto e sendo
          {' '}comparado contra meses fechados — troque para "Meses fechados" ou "Mesmo período"
          na barra lateral pra ver se a queda se sustenta com uma comparação justa.
        </p>
      )}

      <section className="clientes-visao-kpis" aria-label="Indicadores da carteira">
        <StatCard
          title="Clientes ativos"
          value={formatNumber(resumo.clientes_ativos)}
          icon={UsersRound}
          trend={resumo.variacao_clientes == null
            ? undefined
            : `${textoVariacao(resumo.variacao_clientes)} vs média (${formatNumber(Math.round(resumo.clientes_media))})`}
          trendUp={(resumo.variacao_clientes ?? 0) >= 0}
        />
        <StatCard
          title={`Receita de ${dados.rotulo_periodo}`}
          value={formatCurrency(resumo.receita_atual)}
          icon={Banknote}
          trend={resumo.variacao_receita == null
            ? undefined
            : `${textoVariacao(resumo.variacao_receita)} vs ${formatCurrency(resumo.receita_media)}`}
          trendUp={(resumo.variacao_receita ?? 0) >= 0}
        />
        <StatCard
          title="Ticket médio por cliente"
          value={formatCurrency(resumo.ticket_medio)}
          icon={Receipt}
          trend={resumo.variacao_ticket == null
            ? undefined
            : `${textoVariacao(resumo.variacao_ticket)} vs ${formatCurrency(resumo.ticket_medio_media)}`}
          trendUp={(resumo.variacao_ticket ?? 0) >= 0}
        />
        <StatCard
          title="Saldo da carteira"
          value={`${resumo.saldo > 0 ? '+' : ''}${formatNumber(resumo.saldo)}`}
          icon={UserPlus}
          trend={`${formatNumber(resumo.novos)} novos · ${formatNumber(resumo.recuperados)} recuperados · ${formatNumber(resumo.perdidos)} perdidos`}
          trendUp={resumo.saldo >= 0}
          useTrendColor
        />
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
            <div className="donut-linha">
              <div className="donut">
                <ResponsiveContainer width="100%" height={168}>
                  <PieChart>
                    <Pie
                      data={concentracao.faixas}
                      dataKey="receita"
                      nameKey="nome"
                      cx="50%"
                      cy="50%"
                      innerRadius={52}
                      outerRadius={78}
                      paddingAngle={2}
                      stroke="var(--bg-card)"
                      strokeWidth={2}
                    >
                      {concentracao.faixas.map((faixa, indice) => (
                        <Cell key={faixa.nome} fill={CORES_FAIXA[indice % CORES_FAIXA.length]} />
                      ))}
                    </Pie>
                    <Label
                      content={(props) => (
                        <DonutFuro
                          valor={formatNumber(concentracao.clientes_80)}
                          legenda="clientes fazem 80%"
                          viewBox={props.viewBox as { cx?: number; cy?: number } | undefined}
                        />
                      )}
                    />
                    <Tooltip content={<TooltipFaixa />} />
                  </PieChart>
                </ResponsiveContainer>
              </div>
              <ul className="donut-legenda">
                {concentracao.faixas.map((faixa, indice) => (
                  <li key={faixa.nome}>
                    <i style={{ background: CORES_FAIXA[indice % CORES_FAIXA.length] }} aria-hidden="true" />
                    <span>{faixa.nome}</span>
                    <strong>{formatNumber(faixa.clientes)}</strong>
                    <em>{formatPercent(faixa.participacao, 1)}</em>
                  </li>
                ))}
              </ul>
            </div>
          )}
          <p className="analisador-hint">
            {formatPercent(concentracao.participacao_clientes_80, 1)} da carteira responde por 80% da receita.
          </p>

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
          <div className="clientes-tabela-wrap clientes-visao-tabela custom-scrollbar">
            <table className="analisador-tabela clientes-tabela">
              <thead>
                <tr>
                  <th className="col-nome">Cliente</th>
                  <th className="col-num">Receita</th>
                  <th className="col-num">Média</th>
                  <th className="col-num">Variação</th>
                </tr>
              </thead>
              <tbody>
                {dados.top_clientes.length === 0 && (
                  <tr><td colSpan={4} className="analisador-tabela-vazia">Sem venda no mês de referência.</td></tr>
                )}
                {dados.top_clientes.map((item) => (
                  <tr key={item.cliente} className={classeLinha(item.variacao, item.alerta)}>
                    <td className="col-nome" title={item.cliente}>{item.cliente}</td>
                    <td className="col-num">{formatCurrency(item.receita_atual)}</td>
                    <td className="col-num">{formatCurrency(item.receita_media)}</td>
                    <td className={`col-num ${classeVariacao(item.variacao)}`}>
                      {item.variacao != null && item.variacao !== 0 && (
                        item.variacao > 0
                          ? <ArrowUpRight size={13} aria-hidden="true" />
                          : <ArrowDownRight size={13} aria-hidden="true" />
                      )}
                      {textoVariacao(item.variacao)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      </div>
    </div>
  );
}
