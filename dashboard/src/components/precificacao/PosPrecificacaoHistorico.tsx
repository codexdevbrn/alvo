import { useEffect, useMemo, useState } from 'react';
import { AlertTriangle, Loader2, Search, Tags } from 'lucide-react';
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import {
  obterHistoricoPrecificacao,
  obterItemHistoricoPrecificacao,
  type HistoricoPrecificacaoResposta,
  type ItemHistoricoPrecificacao,
  type LinhaHistorico,
  type MarcadorPrecificacao,
  type NivelHistorico,
  type PontoSeriePrecificacao,
  type RodadaLinhaTempo,
  type SituacaoHistorico,
} from '../../api/client';
import { formatCurrency, formatPercent } from '../../utils/formatters';
import { useDebouncedValue } from '../../hooks/useDebouncedValue';
import { ehSemPrecificacao } from '../../utils/semPrecificacao';

type Props = { empresa: string };

type Metrica = 'margem' | 'lucro_dia' | 'qtd_dia';
type NivelItem = Exclude<NivelHistorico, 'rodada'>;

// Espelha `PERIODOS_DIAS` do backend (historico_precificacao.py).
const PERIODOS: { dias: number; rotulo: string }[] = [
  { dias: 90, rotulo: '90 dias' },
  { dias: 180, rotulo: '180 dias' },
  { dias: 365, rotulo: '12 meses' },
];

const ROTULO_PERIODO: Record<number, string> = Object.fromEntries(
  PERIODOS.map((item) => [item.dias, `últimos ${item.rotulo}`]),
);

const NIVEIS: { id: NivelHistorico; rotulo: string }[] = [
  { id: 'familia', rotulo: 'Família' },
  { id: 'fabricante', rotulo: 'Fabricante' },
  { id: 'par', rotulo: 'Família × fab.' },
  { id: 'sku', rotulo: 'SKU' },
  { id: 'rodada', rotulo: 'Rodada' },
];

const METRICAS: { id: Metrica; rotulo: string }[] = [
  { id: 'margem', rotulo: 'Margem' },
  { id: 'lucro_dia', rotulo: 'Lucro / dia' },
  { id: 'qtd_dia', rotulo: 'Qtd / dia' },
];

const ROTULO_NIVEL: Record<NivelHistorico, string> = {
  familia: 'Família',
  fabricante: 'Fabricante',
  par: 'Família × fabricante',
  sku: 'SKU',
  rodada: 'Rodada',
};

const ROTULO_SITUACAO: Record<SituacaoHistorico, string> = {
  acima: 'acima do alvo',
  abaixo: 'abaixo do alvo',
  no_alvo: 'no alvo',
  sem_venda: 'sem venda depois',
  sem_alvo: 'sem alvo',
};

const MESES_ABREV = ['jan', 'fev', 'mar', 'abr', 'mai', 'jun', 'jul', 'ago', 'set', 'out', 'nov', 'dez'];

// Linha do tempo: a partir de quantos % de distância duas etiquetas deixam de
// se sobrepor, e quantos andares de haste há para empilhar as que se sobrepõem.
const DISTANCIA_MINIMA_PCT = 11;
const ANDARES = 3;
const HASTE_BASE_PX = 14;
const HASTE_ANDAR_PX = 40;
const BASE_LT_PX = 34;
const ETIQUETA_PX = 42;

function dataBr(iso: string | null | undefined): string {
  if (!iso) return '—';
  const [ano, mes, dia] = iso.split('-');
  if (!ano || !mes || !dia) return iso;
  return `${dia}/${mes}/${ano}`;
}

function dataCurta(iso: string): string {
  const [, mes, dia] = iso.split('-');
  return `${dia} ${MESES_ABREV[Number(mes) - 1] ?? mes}`;
}

function paraMs(iso: string): number {
  const [ano, mes, dia] = iso.split('-').map(Number);
  return Date.UTC(ano, mes - 1, dia);
}

function pct(valor: number | null | undefined, casas = 1): string {
  return valor == null || !Number.isFinite(valor) ? '—' : formatPercent(valor, casas);
}

function textoSinal(valor: number | null | undefined, sufixo: '%' | 'pp' = '%'): string {
  if (valor == null || !Number.isFinite(valor)) return '—';
  const sinal = valor > 0 ? '+' : '';
  if (sufixo === 'pp') {
    return `${sinal}${valor.toLocaleString('pt-BR', { maximumFractionDigits: 1, minimumFractionDigits: 1 })} pp`;
  }
  return `${sinal}${formatPercent(valor, 1)}`;
}

function classeSinal(valor: number | null | undefined): string {
  if (valor == null || !Number.isFinite(valor) || valor === 0) return '';
  return valor > 0 ? 'is-alta' : 'is-queda';
}

function moeda(valor: number | null | undefined): string {
  return valor == null || !Number.isFinite(valor) ? '—' : formatCurrency(valor);
}

function formatQtd(valor: number | null | undefined): string {
  if (valor == null || !Number.isFinite(valor)) return '—';
  const inteiro = Math.abs(valor - Math.round(valor)) < 0.05;
  return valor.toLocaleString('pt-BR', { maximumFractionDigits: inteiro ? 0 : 1 });
}

function alternar<T>(lista: T[], valor: T): T[] {
  return lista.includes(valor) ? lista.filter((v) => v !== valor) : [...lista, valor];
}

export function PosPrecificacaoHistorico({ empresa }: Props) {
  const [periodo, setPeriodo] = useState(180);
  const [rodadas, setRodadas] = useState<string[]>([]);
  const [faixas, setFaixas] = useState<string[]>([]);
  const [nivel, setNivel] = useState<NivelHistorico>('familia');
  const [todos, setTodos] = useState(false);
  const [metrica, setMetrica] = useState<Metrica>('margem');
  const [busca, setBusca] = useState('');
  const buscaDebounced = useDebouncedValue(busca);
  const [selecionado, setSelecionado] = useState<{ nivel: NivelItem; nome: string } | null>(null);

  // "Carregando" é derivado: a última resposta vem carimbada com a chave do
  // pedido, e enquanto ela não bate com o filtro atual a tela mostra a anterior.
  // Trocar de empresa remonta o componente (key na página), zerando o recorte.
  const buscaEfetiva = nivel === 'rodada' ? '' : buscaDebounced;
  const chave = JSON.stringify([empresa, periodo, rodadas, faixas, nivel, todos, buscaEfetiva]);
  const [dados, setDados] = useState<HistoricoPrecificacaoResposta | null>(null);
  const [resultado, setResultado] = useState<{ chave: string; erro: string | null } | null>(null);
  const carregando = resultado?.chave !== chave;
  const erro = carregando ? null : resultado?.erro ?? null;

  useEffect(() => {
    const controle = new AbortController();
    obterHistoricoPrecificacao(
      empresa,
      { periodo, rodadas, faixas, nivel, todos, busca: buscaEfetiva },
      controle.signal,
    )
      .then((resposta) => {
        setDados(resposta);
        setResultado({ chave, erro: null });
      })
      .catch((e: unknown) => {
        if (controle.signal.aborted) return;
        setResultado({ chave, erro: e instanceof Error ? e.message : 'Falha ao carregar o histórico de precificações.' });
      });
    return () => controle.abort();
  }, [chave, empresa, periodo, rodadas, faixas, nivel, todos, buscaEfetiva]);

  // Trocar de nível invalida o item aberto (o nome é de outro agrupamento).
  function escolherNivel(novo: NivelHistorico) {
    setNivel(novo);
    setSelecionado(null);
    setBusca('');
  }

  function clicarLinha(linha: LinhaHistorico) {
    if (nivel === 'rodada') {
      setRodadas((atual) => (atual.length === 1 && atual[0] === linha.nome ? [] : [linha.nome]));
      return;
    }
    setSelecionado((atual) =>
      atual && atual.nivel === nivel && atual.nome === linha.nome ? null : { nivel, nome: linha.nome },
    );
  }

  if (erro && !dados && ehSemPrecificacao(erro)) {
    return (
      <div className="glass-card glass-card-flat estoque-vazio">
        <Tags size={24} aria-hidden="true" />
        <div>
          <strong>Empresa ainda não precificada</strong>
          <p>Não há rodada de precificação para esta empresa. A aba passa a mostrar os dados assim que houver uma — a atualização é diária.</p>
        </div>
      </div>
    );
  }

  if (erro && !dados) {
    return (
      <div className="glass-card glass-card-flat estoque-vazio">
        <AlertTriangle size={24} aria-hidden="true" />
        <div>
          <strong>Não foi possível carregar as precificações</strong>
          <p>{erro}</p>
        </div>
      </div>
    );
  }

  if (!dados) {
    return (
      <div className="glass-card glass-card-flat estoque-vazio">
        <Loader2 size={24} className="dashboard-filter-spinner" aria-hidden="true" />
        <div>
          <strong>Carregando precificações…</strong>
          <p>Casando cada precificação com as vendas antes e depois.</p>
        </div>
      </div>
    );
  }

  const kpis = dados.kpis;
  const situacoes = kpis.situacoes;

  return (
    <div className="prec-hist" aria-busy={carregando}>
      <section className="glass-card glass-card-flat prec-card">
        <div className="prec-card-topo">
          <div>
            <h2>Rodadas de precificação</h2>
            <p className="prec-mudo">
              Clique numa rodada para isolá-la. Efeito medido em {dados.janela_dias} dias antes × até {dados.janela_dias} dias
              depois, cortado na próxima precificação do mesmo SKU.
            </p>
          </div>
          <div className="prec-card-acoes">
            {carregando && <Loader2 size={14} className="dashboard-filter-spinner" aria-label="Atualizando" />}
            {erro && <span className="prec-mudo is-queda" title={erro}>falha ao atualizar</span>}
            {dados.faixas_disponiveis.length > 0 && (
              <div className="periodo-segmented" role="group" aria-label="Faixas">
                <button
                  type="button"
                  className={`periodo-segmented-btn${faixas.length === 0 ? ' is-active' : ''}`}
                  onClick={() => setFaixas([])}
                >
                  Todas
                </button>
                {dados.faixas_disponiveis.map((faixa) => (
                  <button
                    key={faixa}
                    type="button"
                    aria-pressed={faixas.includes(faixa)}
                    className={`periodo-segmented-btn${faixas.includes(faixa) ? ' is-active' : ''}`}
                    onClick={() => setFaixas((atual) => alternar(atual, faixa))}
                  >
                    Faixa {faixa}
                  </button>
                ))}
              </div>
            )}
            <div className="periodo-segmented" role="radiogroup" aria-label="Período">
              {PERIODOS.map((item) => (
                <button
                  key={item.dias}
                  type="button"
                  role="radio"
                  aria-checked={periodo === item.dias}
                  className={`periodo-segmented-btn${periodo === item.dias ? ' is-active' : ''}`}
                  onClick={() => setPeriodo(item.dias)}
                >
                  {item.rotulo}
                </button>
              ))}
            </div>
          </div>
        </div>
        <LinhaDoTempo
          rodadas={dados.linha_tempo}
          escolhidas={rodadas}
          inicioMovimento={dados.inicio_movimento}
          fimMovimento={dados.fim_movimento}
          periodoDias={periodo}
          onAlternar={(dia) => setRodadas((atual) => alternar(atual, dia))}
        />
        <div className="prec-legenda">
          <span><i className="prec-lt-ponto" />medível</span>
          <span><i className="prec-lt-ponto is-sem-medida" />sem venda antes (não medível)</span>
          <span><i className="prec-lt-ponto is-apagada" />fora do período ou do filtro</span>
          <span><i className="prec-legenda-periodo" />período escolhido</span>
          {rodadas.length > 0 && (
            <button type="button" className="prec-mudo" onClick={() => setRodadas([])}>
              limpar rodadas ({rodadas.length})
            </button>
          )}
        </div>
      </section>

      <div className="prec-indicadores">
        <Indicador
          rotulo="SKUs precificados"
          valor={kpis.skus.toLocaleString('pt-BR')}
          detalhe={`${kpis.pares.toLocaleString('pt-BR')} famílias × fab. · ${kpis.rodadas} rodada${kpis.rodadas === 1 ? '' : 's'}`}
          acento="var(--accent)"
        />
        <Indicador
          rotulo="Margem depois"
          valor={pct(kpis.margem_depois)}
          detalhe={`alvo ${pct(kpis.alvo)} · ${textoSinal(kpis.gap_pp, 'pp')}`}
          acento={kpis.gap_pp == null ? 'var(--text-muted)' : kpis.gap_pp >= -1 ? 'var(--success)' : 'var(--danger)'}
        />
        <Indicador
          rotulo="Lucro por dia"
          valor={textoSinal(kpis.efeito_lucro_pct)}
          detalhe={`${moeda(kpis.lucro_dia_antes)} → ${moeda(kpis.lucro_dia_depois)}`}
          acento={kpis.efeito_lucro_pct == null ? 'var(--text-muted)' : kpis.efeito_lucro_pct >= 0 ? 'var(--success)' : 'var(--danger)'}
        />
        <Indicador
          rotulo="Acima do alvo"
          valor={pct(kpis.pct_acima, 0)}
          detalhe={`${situacoes.acima ?? 0} acima · ${situacoes.no_alvo ?? 0} no alvo · ${situacoes.abaixo ?? 0} abaixo · receita coberta ${pct(kpis.receita_coberta_pct, 0)}`}
          acento="var(--text-muted)"
        />
      </div>

      <div className="prec-corpo">
        <div className="prec-coluna">
          <section className="glass-card glass-card-flat prec-card">
            <div className="prec-card-topo">
              <div>
                <h2>Evolução mensal</h2>
                <p className="prec-mudo">
                  {todos ? 'Loja inteira' : 'Só os SKUs precificados no filtro'} · meses com precificação em destaque.
                </p>
              </div>
              <div className="prec-card-acoes">
                <div className="periodo-segmented" role="radiogroup" aria-label="Abrangência do gráfico">
                  <button
                    type="button"
                    role="radio"
                    aria-checked={!todos}
                    className={`periodo-segmented-btn${!todos ? ' is-active' : ''}`}
                    onClick={() => setTodos(false)}
                  >
                    Precificados
                  </button>
                  <button
                    type="button"
                    role="radio"
                    aria-checked={todos}
                    className={`periodo-segmented-btn${todos ? ' is-active' : ''}`}
                    onClick={() => setTodos(true)}
                  >
                    Loja inteira
                  </button>
                </div>
                <div className="periodo-segmented" role="radiogroup" aria-label="Métrica">
                  {METRICAS.map((item) => (
                    <button
                      key={item.id}
                      type="button"
                      role="radio"
                      aria-checked={metrica === item.id}
                      className={`periodo-segmented-btn${metrica === item.id ? ' is-active' : ''}`}
                      onClick={() => setMetrica(item.id)}
                    >
                      {item.rotulo}
                    </button>
                  ))}
                </div>
              </div>
            </div>
            <SerieMensal serie={dados.serie_mensal} marcadores={dados.marcadores} metrica={metrica} altura={220} />
          </section>

          <section className="glass-card glass-card-flat prec-card">
            <div className="prec-card-topo">
              <div className="prec-card-acoes">
                <div className="periodo-segmented" role="radiogroup" aria-label="Agrupar por">
                  {NIVEIS.map((item) => (
                    <button
                      key={item.id}
                      type="button"
                      role="radio"
                      aria-checked={nivel === item.id}
                      className={`periodo-segmented-btn${nivel === item.id ? ' is-active' : ''}`}
                      onClick={() => escolherNivel(item.id)}
                    >
                      {item.rotulo}
                    </button>
                  ))}
                </div>
              </div>
              {nivel !== 'rodada' && (
                <label className="prec-busca">
                  <Search size={13} aria-hidden="true" />
                  <input
                    type="search"
                    value={busca}
                    onChange={(e) => setBusca(e.target.value)}
                    placeholder={nivel === 'sku' ? 'Código, descrição ou fabricante' : 'Buscar'}
                    aria-label="Buscar na tabela"
                  />
                </label>
              )}
            </div>
            <TabelaHistorico
              linhas={dados.linhas}
              nivel={dados.nivel}
              selecionado={nivel === 'rodada' ? (rodadas.length === 1 ? rodadas[0] : null) : selecionado?.nome ?? null}
              onClicar={clicarLinha}
            />
            {dados.total_linhas > dados.linhas.length && (
              <p className="prec-mudo prec-rodape">
                Mostrando as {dados.linhas.length.toLocaleString('pt-BR')} maiores de{' '}
                {dados.total_linhas.toLocaleString('pt-BR')} — use a busca para achar as demais.
              </p>
            )}
          </section>
        </div>

        <PainelItem
          empresa={empresa}
          selecionado={selecionado}
          periodo={periodo}
          rodadas={rodadas}
          faixas={faixas}
        />
      </div>
    </div>
  );
}

function Indicador({ rotulo, valor, detalhe, acento }: { rotulo: string; valor: string; detalhe: string; acento: string }) {
  return (
    <div
      className="glass-card glass-card-flat prec-indicador"
      style={{ ['--prec-acento' as string]: acento }}
    >
      <span className="prec-rotulo">{rotulo}</span>
      <strong>{valor}</strong>
      <em>{detalhe}</em>
    </div>
  );
}

function LinhaDoTempo({
  rodadas,
  escolhidas,
  inicioMovimento,
  fimMovimento,
  periodoDias,
  onAlternar,
}: {
  rodadas: RodadaLinhaTempo[];
  escolhidas: string[];
  inicioMovimento: string | null;
  fimMovimento: string | null;
  periodoDias: number;
  onAlternar: (dia: string) => void;
}) {
  const layout = useMemo(() => {
    if (rodadas.length === 0) return null;
    const dias = rodadas.map((r) => paraMs(r.dia));
    const inicio = Math.min(...dias, inicioMovimento ? paraMs(inicioMovimento) : Infinity);
    const fim = Math.max(...dias, fimMovimento ? paraMs(fimMovimento) : -Infinity);
    const span = Math.max(fim - inicio, 1);
    const posicao = (ms: number) => ((ms - inicio) / span) * 100;

    // Etiqueta por importância, não por ordem de data: a escolhida, depois as do
    // período, depois as maiores. Cada uma pega o primeiro andar com folga dos
    // dois lados; sem folga em nenhum, fica só o ponto (detalhe no title). Antes
    // o quarto vizinho voltava ao térreo por cima do primeiro — com as ~20
    // rodadas da Lupi as etiquetas viravam "30 04 nov".
    const porAndar: number[][] = Array.from({ length: ANDARES }, () => []);
    const andarDe = new Map<string, number | null>();
    const prioridade = (r: RodadaLinhaTempo) =>
      (escolhidas.includes(r.dia) ? 2e9 : 0) + (r.no_periodo ? 1e9 : 0) + r.skus;
    for (const rodada of [...rodadas].sort((a, b) => prioridade(b) - prioridade(a))) {
      const x = posicao(paraMs(rodada.dia));
      const andar = porAndar.findIndex((ocupados) => ocupados.every((o) => Math.abs(x - o) >= DISTANCIA_MINIMA_PCT));
      if (andar >= 0) porAndar[andar].push(x);
      andarDe.set(rodada.dia, andar >= 0 ? andar : null);
    }
    const marcos = [...rodadas]
      .sort((a, b) => a.dia.localeCompare(b.dia))
      .map((rodada) => ({ rodada, x: posicao(paraMs(rodada.dia)), andar: andarDe.get(rodada.dia) ?? null }));

    // Mês sempre com ano ("set/25", "set/26"): a linha costuma cobrir mais de
    // 12 meses, e "set" duas vezes no eixo não dizia qual era qual.
    const meses: { x: number; rotulo: string }[] = [];
    const anos: { x: number; rotulo: string }[] = [];
    const data = new Date(inicio);
    const cursor = new Date(Date.UTC(data.getUTCFullYear(), data.getUTCMonth() + 1, 1));
    const total = Math.round(span / (30 * 86_400_000));
    const passo = total > 14 ? 3 : total > 7 ? 2 : 1;
    let contador = 0;
    while (cursor.getTime() <= fim) {
      const mes = cursor.getUTCMonth();
      const x = posicao(cursor.getTime());
      if (mes === 0) anos.push({ x, rotulo: String(cursor.getUTCFullYear()) });
      if (contador % passo === 0) {
        meses.push({ x, rotulo: `${MESES_ABREV[mes]}/${String(cursor.getUTCFullYear()).slice(2)}` });
      }
      contador += 1;
      cursor.setUTCMonth(cursor.getUTCMonth() + 1);
    }

    // Faixa do período escolhido: termina no último movimento e volta
    // `periodoDias` — a mesma régua que o backend usa para `no_periodo`.
    const fimPeriodo = fimMovimento ? paraMs(fimMovimento) : fim;
    const inicioPeriodo = Math.max(inicio, fimPeriodo - periodoDias * 86_400_000);
    const periodo = { x0: posicao(inicioPeriodo), x1: posicao(fimPeriodo) };

    const semDado = inicioMovimento ? Math.max(0, posicao(paraMs(inicioMovimento))) : 0;
    const andares = Math.max(0, ...marcos.map((m) => m.andar ?? 0)) + 1;
    return { marcos, meses, anos, semDado, andares, periodo };
  }, [rodadas, escolhidas, inicioMovimento, fimMovimento, periodoDias]);

  if (!layout) return <p className="prec-vazio">Nenhuma rodada de precificação registrada.</p>;

  const altura = BASE_LT_PX + HASTE_BASE_PX + (layout.andares - 1) * HASTE_ANDAR_PX + ETIQUETA_PX + 8;

  return (
    <div className="prec-lt" style={{ height: altura }}>
      {layout.semDado > 0.5 && (
        <div className="prec-lt-sem-dado" style={{ width: `${layout.semDado}%` }}>
          {layout.semDado > 12 && <span>sem movimento</span>}
        </div>
      )}
      <div
        className="prec-lt-periodo"
        style={{ left: `${layout.periodo.x0}%`, width: `${Math.max(layout.periodo.x1 - layout.periodo.x0, 0.5)}%` }}
      >
        <span>{ROTULO_PERIODO[periodoDias] ?? `${periodoDias} dias`}</span>
      </div>
      {layout.anos.map((ano) => (
        <div key={ano.rotulo} className="prec-lt-ano" style={{ left: `${ano.x}%` }} title={`início de ${ano.rotulo}`} />
      ))}
      <div className="prec-lt-trilho" />
      {layout.meses.map((mes) => (
        <span key={`${mes.x}-${mes.rotulo}`} className="prec-lt-mes" style={{ left: `${mes.x}%` }}>
          {mes.rotulo}
        </span>
      ))}
      {layout.marcos.map(({ rodada, x, andar }) => {
        const escolhida = escolhidas.includes(rodada.dia);
        const apagada = !rodada.no_periodo || !rodada.selecionada;
        const classes = [
          'prec-lt-marco',
          escolhida ? 'is-escolhida' : '',
          apagada ? 'is-apagada' : '',
          x < 6 ? 'is-borda-esq' : x > 94 ? 'is-borda-dir' : '',
          andar == null ? 'is-so-ponto' : '',
        ].filter(Boolean).join(' ');
        const resumo = `${dataCurta(rodada.dia)} · ${rodada.skus.toLocaleString('pt-BR')} SKUs · ${rodada.pares.toLocaleString('pt-BR')} fam.`;
        const ponto = ['prec-lt-ponto', !rodada.mensuravel ? 'is-sem-medida' : '', apagada ? 'is-apagada' : '']
          .filter(Boolean).join(' ');
        return (
          <button
            key={rodada.dia}
            type="button"
            className={classes}
            style={{ left: `${x}%`, ['--prec-haste' as string]: `${HASTE_BASE_PX + (andar ?? 0) * HASTE_ANDAR_PX}px` }}
            disabled={!rodada.no_periodo}
            aria-pressed={escolhida}
            aria-label={resumo}
            title={rodada.no_periodo ? (andar == null ? resumo : undefined) : `${resumo} · fora do período selecionado`}
            onClick={() => onAlternar(rodada.dia)}
          >
            {andar != null && (
              <>
                <span className="prec-lt-etiqueta">
                  <b>{dataCurta(rodada.dia)}</b>
                  <small>{rodada.skus.toLocaleString('pt-BR')} SKUs · {rodada.pares.toLocaleString('pt-BR')} fam.</small>
                </span>
                <span className="prec-lt-haste" />
              </>
            )}
            <span className={ponto} />
          </button>
        );
      })}
    </div>
  );
}

function SerieMensal({
  serie,
  marcadores,
  metrica,
  altura,
}: {
  serie: PontoSeriePrecificacao[];
  marcadores: MarcadorPrecificacao[];
  metrica: Metrica;
  altura: number;
}) {
  const skusPorMes = useMemo(() => {
    const mapa = new Map<string, number>();
    for (const m of marcadores) mapa.set(m.periodo, (mapa.get(m.periodo) ?? 0) + m.skus);
    return mapa;
  }, [marcadores]);

  if (serie.length === 0) return <p className="prec-vazio">Sem vendas neste recorte.</p>;

  const cor = 'var(--accent)';
  const fillId = `prec-hist-${metrica}-${altura}`;
  return (
    <ResponsiveContainer width="100%" height={altura}>
      <AreaChart data={serie} margin={{ top: 12, right: 24, left: 24, bottom: 4 }}>
        <defs>
          <linearGradient id={fillId} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={cor} stopOpacity={0.3} />
            <stop offset="100%" stopColor={cor} stopOpacity={0} />
          </linearGradient>
        </defs>
        <CartesianGrid stroke="var(--border)" vertical={false} />
        <XAxis
          dataKey="rotulo"
          tick={{ fill: 'var(--text-muted)', fontSize: 11 }}
          axisLine={false}
          tickLine={false}
          // No painel (estreito) todos os meses não cabem — deixa o Recharts espaçar.
          interval={altura >= 200 && serie.length <= 12 ? 0 : 'preserveStartEnd'}
          minTickGap={altura >= 200 ? 8 : 20}
        />
        <YAxis hide domain={['auto', 'auto']} />
        <Tooltip
          content={({ active, payload, label }) => {
            if (!active || !payload?.length) return null;
            const ponto = payload[0]?.payload as PontoSeriePrecificacao;
            const skus = skusPorMes.get(ponto.periodo);
            return (
              <div className="vendedores-chart-tooltip">
                <strong>{label}{skus ? ` · ${skus.toLocaleString('pt-BR')} SKUs precificados` : ''}</strong>
                <dl>
                  <div><dt>Margem</dt><dd>{pct(ponto.margem)}</dd></div>
                  <div><dt>Lucro / dia</dt><dd>{moeda(ponto.lucro_dia)}</dd></div>
                  <div><dt>Qtd / dia</dt><dd>{formatQtd(ponto.qtd_dia)}</dd></div>
                  <div><dt>Receita</dt><dd>{formatCurrency(ponto.receita)}</dd></div>
                </dl>
              </div>
            );
          }}
        />
        <Area
          type="monotone"
          dataKey={metrica}
          stroke={cor}
          strokeWidth={2}
          fill={`url(#${fillId})`}
          connectNulls={false}
          isAnimationActive={false}
          dot={({ cx, cy, index }: { cx?: number; cy?: number; index?: number }) => {
            const chave = `ponto-${index}`;
            if (cx == null || cy == null || index == null) return <g key={chave} />;
            if (!skusPorMes.has(serie[index]?.periodo)) {
              return <circle key={chave} cx={cx} cy={cy} r={2} fill={cor} />;
            }
            return (
              <g key={chave}>
                <circle cx={cx} cy={cy} r={6.5} fill="none" stroke={cor} strokeOpacity={0.45} strokeWidth={1.5} />
                <circle cx={cx} cy={cy} r={3.5} fill={cor} stroke="var(--bg-card)" strokeWidth={1.5} />
              </g>
            );
          }}
          activeDot={{ r: 5 }}
        />
      </AreaChart>
    </ResponsiveContainer>
  );
}

function Situacao({ situacao }: { situacao: SituacaoHistorico }) {
  return <span className={`prec-situacao is-${situacao}`}>{ROTULO_SITUACAO[situacao]}</span>;
}

function TabelaHistorico({
  linhas,
  nivel,
  selecionado,
  onClicar,
}: {
  linhas: LinhaHistorico[];
  nivel: NivelHistorico;
  selecionado: string | null;
  onClicar: (linha: LinhaHistorico) => void;
}) {
  if (linhas.length === 0) return <p className="prec-vazio">Nenhuma precificação neste filtro.</p>;
  return (
    <div className="prec-tabela-rolagem">
      <table className="prec-tabela">
        <thead>
          <tr>
            <th>{ROTULO_NIVEL[nivel]}</th>
            <th className="r">SKUs</th>
            <th>{nivel === 'rodada' ? 'Faixas' : 'Última'}</th>
            <th className="r">Alvo</th>
            <th className="r">Margem antes → depois</th>
            <th className="r">Gap</th>
            <th className="r">Lucro / dia</th>
            <th className="r">Qtd / dia</th>
            <th>Situação</th>
          </tr>
        </thead>
        <tbody>
          {linhas.map((linha) => (
            <tr
              key={linha.nome}
              className={selecionado === linha.nome ? 'is-selecionada' : undefined}
              onClick={() => onClicar(linha)}
            >
              <td>
                <span className="prec-nome">
                  {nivel === 'rodada' ? dataBr(linha.nome) : linha.nome}
                  {nivel === 'sku' && (
                    <small>{linha.descricao} · {linha.fabricante}{linha.fx ? ` · ${linha.fx}` : ''}</small>
                  )}
                </span>
              </td>
              <td className="r">{linha.skus.toLocaleString('pt-BR')}</td>
              <td>
                {nivel === 'rodada' ? (
                  linha.faixas.join(', ') || '—'
                ) : (
                  <>
                    {linha.precificacoes > 1 && (
                      <span className="prec-bolas" title={`${linha.precificacoes} precificações no filtro`}>
                        {Array.from({ length: Math.min(linha.precificacoes, 5) }, (_, i) => <i key={i} />)}
                      </span>
                    )}
                    {dataBr(linha.ultima)}
                  </>
                )}
              </td>
              <td className="r">{pct(linha.alvo)}</td>
              <td className="r">
                {pct(linha.margem_antes)}<span className="prec-seta">→</span>{pct(linha.margem_depois)}
              </td>
              <td className={`r ${classeSinal(linha.gap_pp)}`}>{textoSinal(linha.gap_pp, 'pp')}</td>
              <td className={`r ${classeSinal(linha.efeito_lucro_pct)}`}>{textoSinal(linha.efeito_lucro_pct)}</td>
              <td className={`r ${classeSinal(linha.efeito_qtd_pct)}`}>{textoSinal(linha.efeito_qtd_pct)}</td>
              <td><Situacao situacao={linha.situacao} /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function PainelItem({
  empresa,
  selecionado,
  periodo,
  rodadas,
  faixas,
}: {
  empresa: string;
  selecionado: { nivel: NivelItem; nome: string } | null;
  periodo: number;
  rodadas: string[];
  faixas: string[];
}) {
  const chave = selecionado
    ? JSON.stringify([empresa, selecionado.nivel, selecionado.nome, periodo, rodadas, faixas])
    : null;
  const [resultado, setResultado] = useState<
    { chave: string; item: ItemHistoricoPrecificacao | null; erro: string | null } | null
  >(null);
  const atual = resultado && resultado.chave === chave ? resultado : null;
  const carregando = chave != null && atual == null;
  const item = atual?.item ?? null;
  const erro = atual?.erro ?? null;

  useEffect(() => {
    if (!selecionado || chave == null) return;
    const controle = new AbortController();
    obterItemHistoricoPrecificacao(
      empresa,
      { periodo, rodadas, faixas, nivel: selecionado.nivel, nome: selecionado.nome },
      controle.signal,
    )
      .then((resposta) => setResultado({ chave, item: resposta, erro: null }))
      .catch((e: unknown) => {
        if (controle.signal.aborted) return;
        setResultado({ chave, item: null, erro: e instanceof Error ? e.message : 'Falha ao carregar o item.' });
      });
    return () => controle.abort();
  }, [chave, empresa, selecionado, periodo, rodadas, faixas]);

  if (!selecionado) {
    return (
      <aside className="glass-card glass-card-flat prec-painel">
        <p className="prec-painel-vazio">Clique numa linha da tabela para ver o histórico de precificações do item.</p>
      </aside>
    );
  }

  return (
    <aside className="glass-card glass-card-flat prec-painel" aria-busy={carregando}>
      <div>
        <span className="prec-rotulo">{ROTULO_NIVEL[selecionado.nivel]}</span>
        <h3>{selecionado.nome}</h3>
        {item && (
          <p className="prec-mudo">
            {item.skus_total.toLocaleString('pt-BR')} SKUs · {item.fabricantes} fabricante{item.fabricantes === 1 ? '' : 's'}
            {item.faixas.length > 0 ? ` · faixa ${item.faixas.join(', ')}` : ''}
          </p>
        )}
      </div>

      {carregando && !item && <p className="prec-vazio"><Loader2 size={14} className="dashboard-filter-spinner" aria-hidden="true" /> Carregando…</p>}
      {erro && <p className="prec-vazio">{erro}</p>}

      {item && (
        <>
          <div>
            <span className="prec-rotulo">Margem mensal</span>
            <SerieMensal serie={item.serie_mensal} marcadores={item.marcadores} metrica="margem" altura={140} />
          </div>

          <div>
            <span className="prec-rotulo">Precificações</span>
            {item.historico.length === 0 ? (
              <p className="prec-vazio">Sem precificações.</p>
            ) : (
              <ol className="prec-historico">
                {item.historico.map((evento) => (
                  <li key={evento.dia} className={evento.no_filtro ? undefined : 'is-apagado'}>
                    <b>{dataBr(evento.dia)}</b>
                    alvo {pct(evento.alvo)} · margem no dia {pct(evento.margem_no_dia)} · {evento.skus} SKU{evento.skus === 1 ? '' : 's'}
                    {!evento.mensuravel && ' · não medível'}
                  </li>
                ))}
              </ol>
            )}
          </div>

          {item.skus.length > 0 && (
            <div>
              <span className="prec-rotulo">SKUs que mais pesam</span>
              <ul className="prec-skus">
                {item.skus.map((sku) => (
                  <li key={sku.codigo} title={`${sku.descricao} · ${sku.fabricante}`}>
                    <code>{sku.codigo}</code>
                    <span>{sku.descricao}</span>
                    <b className={classeSinal(sku.efeito_lucro_pct)}>{textoSinal(sku.efeito_lucro_pct)}</b>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </>
      )}
    </aside>
  );
}
