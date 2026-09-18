import { useEffect, useMemo, useRef, useState, type PointerEvent as ReactPointerEvent } from 'react';
import {
  AlertTriangle,
  ArrowDown,
  ArrowUp,
  BadgePercent,
  Loader2,
  Search,
} from 'lucide-react';
import {
  Area,
  AreaChart,
  CartesianGrid,
  LabelList,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { LeituraFaixa } from '../LeituraFaixa';
import {
  obterPosPrecificacao,
  type ItemPosPrecificacao,
  type JanelaFixaPrecificacao,
  type PontoSeriePrecificacao,
  type PosPrecificacaoResposta,
  type ResumoPosPrecificacao,
  type SituacaoPrecificacao,
} from '../../api/client';
import { formatCompacto, formatCurrency, formatPercent } from '../../utils/formatters';
import { useMesesFechados } from '../../hooks/useMesesFechados';
import { modoParaBooleano } from '../../utils/mesesFechados';

type Props = {
  empresa: string;
  loja: string | null;
  modoGrafico: 'sintetica' | 'detalhada';
};

type AbaLista = 'produtos' | 'fabricantes';

const TODOS = '__todos__';

// Espelha `JANELA_DETALHE_DIAS` do backend (precificacao.py) — só pra legenda,
// a janela real quem decide é o servidor.
const JANELA_DETALHE_DIAS = 20;

const ABAS: { id: AbaLista; rotulo: string }[] = [
  { id: 'produtos', rotulo: 'Produtos' },
  { id: 'fabricantes', rotulo: 'Fabricantes' },
];

const ROTULO_SITUACAO: Record<SituacaoPrecificacao, string> = {
  acima: 'acima do alvo',
  abaixo: 'abaixo do alvo',
  no_alvo: 'no alvo',
  sem_venda: 'sem venda depois',
  sem_alvo: 'sem alvo',
};

const DIAS_SEMANA_ABREV = ['dom', 'seg', 'ter', 'qua', 'qui', 'sex', 'sáb'];

function diaSemanaAbrev(periodo: string): string | null {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(periodo)) return null;
  const [ano, mes, dia] = periodo.split('-').map(Number);
  return DIAS_SEMANA_ABREV[new Date(ano, mes - 1, dia).getDay()];
}

function dataBr(iso: string | null | undefined): string {
  if (!iso) return '—';
  const [ano, mes, dia] = iso.split('-');
  if (!ano || !mes || !dia) return iso;
  return `${dia}/${mes}/${ano}`;
}

function textoSinal(valor: number | null | undefined, sufixo = '%'): string {
  if (valor == null || !Number.isFinite(valor)) return '—';
  const sinal = valor > 0 ? '+' : '';
  if (sufixo === 'pp') {
    return `${sinal}${valor.toLocaleString('pt-BR', { maximumFractionDigits: 1, minimumFractionDigits: 1 })} pp`;
  }
  return `${sinal}${formatPercent(valor, 1)}`;
}

function formatQtd(valor: number | null | undefined): string {
  if (valor == null || !Number.isFinite(valor)) return '—';
  const inteiro = Math.abs(valor - Math.round(valor)) < 0.05;
  return valor.toLocaleString('pt-BR', { maximumFractionDigits: inteiro ? 0 : 1 });
}

function normalizarBusca(valor: string): string {
  return valor.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLocaleLowerCase('pt-BR');
}

function ultimoLucroDia(serie: PontoSeriePrecificacao[]): number | null {
  for (let i = serie.length - 1; i >= 0; i -= 1) {
    if (serie[i].lucro_dia != null) return serie[i].lucro_dia;
  }
  return null;
}

function variacaoMomLucroDia(serie: PontoSeriePrecificacao[]): number | null {
  const pontos = serie.filter((ponto) => ponto.lucro_dia != null && ponto.lucro_dia !== 0);
  if (pontos.length < 2) return null;
  const anterior = pontos[pontos.length - 2].lucro_dia ?? 0;
  const atual = pontos[pontos.length - 1].lucro_dia ?? 0;
  if (anterior <= 0) return null;
  return ((atual - anterior) / anterior) * 100;
}

function ultimoCampo(serie: PontoSeriePrecificacao[], chave: 'margem' | 'lucro_dia' | 'qtd_dia'): number | null {
  for (let i = serie.length - 1; i >= 0; i -= 1) {
    const valor = serie[i][chave];
    if (valor != null) return valor;
  }
  return null;
}

function variacaoMomCampo(serie: PontoSeriePrecificacao[], chave: 'margem' | 'lucro_dia' | 'qtd_dia'): number | null {
  const pontos = serie.filter((ponto) => ponto[chave] != null);
  if (pontos.length < 2) return null;
  const anterior = pontos[pontos.length - 2][chave];
  const atual = pontos[pontos.length - 1][chave];
  if (anterior == null || atual == null || anterior === 0) return null;
  if (chave === 'margem') return atual - anterior;
  return ((atual - anterior) / anterior) * 100;
}

export function PosPrecificacaoVisao({ empresa, loja, modoGrafico }: Props) {
  const [dados, setDados] = useState<PosPrecificacaoResposta | null>(null);
  const [carregando, setCarregando] = useState(true);
  const [erro, setErro] = useState<string | null>(null);
  const [aba, setAba] = useState<AbaLista>('produtos');
  const [busca, setBusca] = useState('');
  const [selecao, setSelecao] = useState<string | null>(null);
  const [modoPeriodo] = useMesesFechados();
  const usarMesesFechados = modoParaBooleano(modoPeriodo);

  useEffect(() => {
    let vivo = true;
    setCarregando(true);
    setErro(null);
    setSelecao(null);
    void obterPosPrecificacao(empresa, { loja, usarMesesFechados })
      .then((resposta) => {
        if (vivo) setDados(resposta);
      })
      .catch((falha) => {
        if (!vivo) return;
        setDados(null);
        setErro(falha instanceof Error ? falha.message : 'Falha ao carregar a precificação.');
      })
      .finally(() => {
        if (vivo) setCarregando(false);
      });
    return () => {
      vivo = false;
    };
  }, [empresa, loja, usarMesesFechados]);

  useEffect(() => {
    setSelecao(null);
    setBusca('');
  }, [aba]);

  const itens = aba === 'produtos' ? (dados?.produtos ?? []) : (dados?.fabricantes ?? []);
  const itensDestaque = useMemo(
    () => [...itens].sort((a, b) => (ultimoLucroDia(b.serie_mensal) ?? -1) - (ultimoLucroDia(a.serie_mensal) ?? -1)),
    [itens],
  );
  const filtrados = useMemo(() => {
    const termo = normalizarBusca(busca);
    if (!termo) return itens;
    return itens.filter((item) => normalizarBusca(item.nome).includes(termo));
  }, [itens, busca]);

  if (carregando) {
    return (
      <div className="glass-card glass-card-flat estoque-carregando">
        <Loader2 size={20} className="dashboard-filter-spinner" /> Cruzando dump e movimento…
      </div>
    );
  }

  if (erro) {
    return (
      <div className="glass-card glass-card-flat estoque-vazio">
        <AlertTriangle size={24} aria-hidden="true" />
        <div>
          <strong>Sem dump de precificação</strong>
          <p>{erro}</p>
        </div>
      </div>
    );
  }

  if (!dados || dados.linhas_dump === 0) {
    return (
      <div className="glass-card glass-card-flat estoque-vazio">
        <BadgePercent size={24} aria-hidden="true" />
        <div>
          <strong>Nada precificado</strong>
          <p>O arquivo existe, mas não tem linha com família e fabricante.</p>
        </div>
      </div>
    );
  }

  const nomeAtivo = selecao ?? TODOS;
  const itemAtivo = nomeAtivo === TODOS ? null : (itens.find((item) => item.nome === nomeAtivo) ?? null);
  const serie = itemAtivo?.serie_mensal?.length ? itemAtivo.serie_mensal : dados.serie_mensal;
  const rotuloCorte = serie.find((ponto) => ponto.periodo === dados.periodo_corte)?.rotulo;
  const serieDiaria = itemAtivo?.serie_diaria?.length ? itemAtivo.serie_diaria : dados.serie_diaria;
  const rotuloCorteDia = serieDiaria.find((ponto) => ponto.periodo === dados.data_precificacao)?.rotulo;
  const serieGrafico = modoGrafico === 'detalhada' ? serieDiaria : serie;
  const rotuloCorteGrafico = modoGrafico === 'detalhada' ? rotuloCorteDia : rotuloCorte;
  const kpis = itemAtivo ?? resumoComoKpis(dados.resumo);
  const avisoAberto = !dados.tem_movimento_depois;
  const gap = kpis.gap_alvo_pp;
  const sit = dados.resumo.situacoes;
  const rotuloEscopo = itemAtivo ? itemAtivo.nome : `todas as ${dados.familias} famílias`;
  const leitura = avisoAberto
    ? `Precificação em ${dataBr(dados.data_precificacao)}. Movimento ainda sem venda depois da data — só o que foi marcado.`
    : `${rotuloEscopo}: lucro bruto ${formatCurrency(kpis.lucro_depois)} (${kpis.lucro_dia_depois != null ? `${formatCurrency(kpis.lucro_dia_depois)}/dia com venda` : 'sem dia com venda'}). Qtd ${formatQtd(kpis.qtd_depois)}${kpis.qtd_dia_depois != null ? ` (${formatQtd(kpis.qtd_dia_depois)}/dia)` : ''}. Margem ${kpis.margem_depois != null ? formatPercent(kpis.margem_depois, 1) : '—'} vs alvo ${kpis.margem_alvo != null ? formatPercent(kpis.margem_alvo, 1) : '—'}${gap != null ? ` (${textoSinal(gap, 'pp')})` : ''}.`;

  const maxReceita = Math.max(...filtrados.map((item) => item.receita_depois), 0);

  return (
    <div className="estoque-visao despesas-visao">
      <LeituraFaixa tom={avisoAberto || (gap != null && gap < -1) ? 'aviso' : 'normal'}>
        {leitura}
      </LeituraFaixa>

      <FaixaDestaques
        aba={aba}
        itens={itensDestaque}
        serieTodos={dados.serie_mensal}
        lucroDiaTodos={dados.resumo.lucro_dia_depois}
        nomeAtivo={nomeAtivo}
        onSelecionar={setSelecao}
      />

      <section className="pos-precificacao-graficos" aria-label={`Séries de ${rotuloEscopo}`}>
        {modoGrafico === 'detalhada' && (
          <div className="pos-precificacao-graficos-topo">
            <span className="pos-precificacao-graficos-nota">
              Dia a dia, {JANELA_DETALHE_DIAS} dias antes e depois de {dataBr(dados.data_precificacao)}. Dias sem venda ficam fora.
            </span>
          </div>
        )}
        <GraficoSerie
          titulo="Margem %"
          nota={itemAtivo ? itemAtivo.nome : 'Pares do dump'}
          serie={serieGrafico}
          dataKey="margem"
          cor="var(--accent)"
          formato={(valor) => `${Number(valor).toLocaleString('pt-BR', { maximumFractionDigits: 1 })}%`}
          valorTopo={ultimoCampo(serie, 'margem') == null ? '—' : formatPercent(ultimoCampo(serie, 'margem') as number, 1)}
          deltaTopo={variacaoMomCampo(serie, 'margem') == null ? null : textoSinal(variacaoMomCampo(serie, 'margem'), 'pp')}
          rotuloCorte={rotuloCorteGrafico}
          mostrarRotulos={modoGrafico === 'sintetica'}
        />
        <GraficoSerie
          titulo="Lucro bruto / dia"
          nota={modoGrafico === 'detalhada' ? 'Lucro do dia' : 'Lucro do mês ÷ dias com venda'}
          serie={serieGrafico}
          dataKey="lucro_dia"
          cor="var(--accent-secondary-bright)"
          formato={(valor) => formatCompacto(Number(valor), true)}
          valorTopo={ultimoCampo(serie, 'lucro_dia') == null ? '—' : formatCurrency(ultimoCampo(serie, 'lucro_dia') as number)}
          deltaTopo={textoSinal(variacaoMomCampo(serie, 'lucro_dia'))}
          rotuloCorte={rotuloCorteGrafico}
          mostrarRotulos={modoGrafico === 'sintetica'}
        />
        <GraficoSerie
          titulo="Qtd. vendas / dia"
          nota={modoGrafico === 'detalhada' ? 'Quantidade do dia' : 'Quantidade do mês ÷ dias com venda'}
          serie={serieGrafico}
          dataKey="qtd_dia"
          cor="var(--alert-warm)"
          formato={(valor) => formatQtd(Number(valor))}
          valorTopo={formatQtd(ultimoCampo(serie, 'qtd_dia'))}
          deltaTopo={textoSinal(variacaoMomCampo(serie, 'qtd_dia'))}
          rotuloCorte={rotuloCorteGrafico}
          mostrarRotulos={modoGrafico === 'sintetica'}
        />
      </section>

      <section className="pos-precificacao-metros" aria-label="Indicadores do recorte">
        <Metro rotulo="Lucro depois" valor={formatCurrency(kpis.lucro_depois)} delta={textoSinal(kpis.variacao_lucro_pct)} alta={(kpis.variacao_lucro_pct ?? 0) >= 0} />
        <Metro rotulo="Lucro / dia" valor={kpis.lucro_dia_depois == null ? '—' : formatCurrency(kpis.lucro_dia_depois)} delta={kpis.dias_venda_depois > 0 ? `${kpis.dias_venda_depois} dias com venda` : 'sem venda'} />
        <Metro rotulo="Quantidade" valor={formatQtd(kpis.qtd_depois)} delta={textoSinal(kpis.variacao_qtd_pct)} alta={(kpis.variacao_qtd_pct ?? 0) >= 0} />
        <Metro
          rotulo="Margem vs alvo"
          valor={gap == null ? '—' : textoSinal(gap, 'pp')}
          delta={kpis.margem_depois == null ? 'sem venda' : `${formatPercent(kpis.margem_depois, 1)} · alvo ${kpis.margem_alvo != null ? formatPercent(kpis.margem_alvo, 1) : '—'}`}
          alta={gap == null ? undefined : gap >= 0}
        />
      </section>

      <section className="glass-card glass-card-flat estoque-visao-card">
        <header className="estoque-card-topo pos-precificacao-lista-topo">
          <div>
            <h2>O que foi precificado e como andou</h2>
            <p>
              Clique na linha pra mandar o recorte pro gráfico.
              {` ${sit.acima} acima do alvo · ${sit.abaixo} abaixo · ${sit.sem_venda} sem venda.`}
            </p>
          </div>
          <div className="pos-precificacao-lista-controles">
            <div className="periodo-segmented" role="tablist" aria-label="Lista">
              {ABAS.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  role="tab"
                  aria-selected={aba === item.id}
                  className={`periodo-segmented-btn${aba === item.id ? ' is-active' : ''}`}
                  onClick={() => setAba(item.id)}
                >
                  {item.rotulo}
                </button>
              ))}
            </div>
            <label className="despesas-busca">
              <Search size={14} aria-hidden="true" />
              <input
                type="search"
                value={busca}
                onChange={(evento) => setBusca(evento.target.value)}
                placeholder="Filtrar…"
                aria-label="Filtrar lista"
              />
            </label>
          </div>
        </header>
        <ul className="despesas-lista pos-precificacao-lista">
          {filtrados.map((item) => (
            <LinhaPrecificada
              key={item.nome}
              item={item}
              maxReceita={maxReceita}
              ativo={item.nome === nomeAtivo}
              onSelecionar={() => setSelecao(item.nome === nomeAtivo ? TODOS : item.nome)}
            />
          ))}
        </ul>
        {filtrados.length === 0 && (
          <p className="estoque-card-topo" style={{ paddingTop: 0 }}>Nenhum nome casa com o filtro.</p>
        )}
      </section>
    </div>
  );
}

function resumoComoKpis(resumo: ResumoPosPrecificacao): ItemPosPrecificacao {
  return {
    nome: 'Todos',
    skus_dump: 0,
    receita_dump: resumo.receita_dump,
    margem_anterior_dump: resumo.margem_anterior_dump,
    margem_alvo: resumo.margem_alvo,
    receita_antes: resumo.receita_antes,
    receita_depois: resumo.receita_depois,
    lucro_antes: resumo.lucro_antes,
    lucro_depois: resumo.lucro_depois,
    qtd_antes: resumo.qtd_antes,
    qtd_depois: resumo.qtd_depois,
    margem_antes: resumo.margem_antes,
    margem_depois: resumo.margem_depois,
    dias_venda_antes: resumo.dias_venda_antes,
    dias_venda_depois: resumo.dias_venda_depois,
    lucro_dia_antes: resumo.lucro_dia_antes,
    lucro_dia_depois: resumo.lucro_dia_depois,
    qtd_dia_antes: resumo.qtd_dia_antes,
    qtd_dia_depois: resumo.qtd_dia_depois,
    variacao_receita_pct: resumo.variacao_receita_pct,
    variacao_lucro_pct: resumo.variacao_lucro_pct,
    variacao_qtd_pct: resumo.variacao_qtd_pct,
    gap_alvo_pp: resumo.gap_alvo_pp,
    situacao: 'sem_alvo',
    serie_mensal: [],
    serie_diaria: [],
    janelas: resumo.janelas,
  };
}

function Metro({
  rotulo,
  valor,
  delta,
  alta,
}: {
  rotulo: string;
  valor: string;
  delta: string;
  alta?: boolean;
}) {
  return (
    <div>
      <span>{rotulo}</span>
      <strong>{valor}</strong>
      <em className={alta == null ? '' : alta ? 'is-alta' : 'is-queda'}>{delta}</em>
    </div>
  );
}

type Destaque = {
  nome: string;
  id: string;
  lucroDia: number | null;
  mom: number | null;
};

function medirTrilho(el: HTMLDivElement): { thumb: number; left: number } {
  const total = el.scrollWidth;
  const visivel = el.clientWidth;
  if (total <= visivel + 1) return { thumb: 1, left: 0 };
  return {
    thumb: visivel / total,
    left: el.scrollLeft / total,
  };
}

function FaixaDestaques({
  aba,
  itens,
  serieTodos,
  lucroDiaTodos,
  nomeAtivo,
  onSelecionar,
}: {
  aba: AbaLista;
  itens: ItemPosPrecificacao[];
  serieTodos: PontoSeriePrecificacao[];
  lucroDiaTodos: number | null;
  nomeAtivo: string;
  onSelecionar: (nome: string) => void;
}) {
  const faixa = useRef<HTMLDivElement>(null);
  const trilhoRef = useRef<HTMLElement>(null);
  const trilhoBarraRef = useRef<HTMLDivElement>(null);
  const arrastandoTrilho = useRef(false);
  const direcao = useRef(1);
  const pausadoAte = useRef(0);
  const nomeAnterior = useRef(nomeAtivo);
  const destaques: Destaque[] = [
    {
      id: TODOS,
      nome: aba === 'produtos' ? 'Todos os produtos' : 'Todos os fabricantes',
      lucroDia: ultimoLucroDia(serieTodos) ?? lucroDiaTodos,
      mom: variacaoMomLucroDia(serieTodos),
    },
    ...itens.map((item) => ({
      id: item.nome,
      nome: item.nome,
      lucroDia: ultimoLucroDia(item.serie_mensal) ?? item.lucro_dia_depois,
      mom: variacaoMomLucroDia(item.serie_mensal),
    })),
  ];

  const atualizarTrilho = () => {
    const el = faixa.current;
    const bar = trilhoRef.current;
    if (!el || !bar) return;
    const { thumb, left } = medirTrilho(el);
    bar.style.width = `${Math.max(8, thumb * 100)}%`;
    bar.style.marginLeft = `${left * 100}%`;
  };

  const pausar = (ms = 10_000) => {
    pausadoAte.current = Date.now() + ms;
  };

  const pausarNoHover = () => {
    pausadoAte.current = Number.POSITIVE_INFINITY;
  };

  const retomarDoHover = () => {
    pausadoAte.current = 0;
  };

  const moverTrilhoPara = (clienteX: number) => {
    const barra = trilhoBarraRef.current;
    const el = faixa.current;
    if (!barra || !el) return;
    const rect = barra.getBoundingClientRect();
    const fracao = rect.width <= 0 ? 0 : (clienteX - rect.left) / rect.width;
    const max = Math.max(0, el.scrollWidth - el.clientWidth);
    el.scrollLeft = Math.min(max, Math.max(0, fracao * el.scrollWidth - el.clientWidth * fracao));
  };

  const iniciarArrasteTrilho = (evento: ReactPointerEvent<HTMLDivElement>) => {
    arrastandoTrilho.current = true;
    pausarNoHover();
    evento.currentTarget.setPointerCapture(evento.pointerId);
    moverTrilhoPara(evento.clientX);
  };

  const arrastarTrilho = (evento: ReactPointerEvent<HTMLDivElement>) => {
    if (!arrastandoTrilho.current) return;
    moverTrilhoPara(evento.clientX);
  };

  const encerrarArrasteTrilho = (evento: ReactPointerEvent<HTMLDivElement>) => {
    if (!arrastandoTrilho.current) return;
    arrastandoTrilho.current = false;
    evento.currentTarget.releasePointerCapture(evento.pointerId);
    retomarDoHover();
  };

  useEffect(() => {
    const el = faixa.current;
    if (!el) return;
    el.scrollTo({ left: 0 });
    direcao.current = 1;
    atualizarTrilho();
  }, [aba, destaques.length]);

  useEffect(() => {
    const el = faixa.current;
    if (!el) return;
    const reduzido = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (reduzido) return undefined;

    let raf = 0;
    let ultimo = performance.now();
    let pos = el.scrollLeft;
    const pxPorSegundo = 36;

    const tick = (agora: number) => {
      raf = window.requestAnimationFrame(tick);
      const dt = Math.min(40, agora - ultimo);
      ultimo = agora;
      const max = el.scrollWidth - el.clientWidth;
      if (max <= 8) return;
      if (Date.now() < pausadoAte.current) {
        pos = el.scrollLeft;
        return;
      }
      if (Math.abs(el.scrollLeft - pos) > 4) pos = el.scrollLeft;
      let dir = direcao.current;
      if (pos >= max - 0.5) {
        dir = -1;
        pos = max;
      } else if (pos <= 0.5) {
        dir = 1;
        pos = 0;
      }
      direcao.current = dir;
      pos = Math.min(max, Math.max(0, pos + dir * pxPorSegundo * (dt / 1000)));
      el.scrollLeft = pos;
    };

    raf = window.requestAnimationFrame(tick);
    el.addEventListener('scroll', atualizarTrilho, { passive: true });
    window.addEventListener('resize', atualizarTrilho);
    atualizarTrilho();
    return () => {
      window.cancelAnimationFrame(raf);
      el.removeEventListener('scroll', atualizarTrilho);
      window.removeEventListener('resize', atualizarTrilho);
    };
  }, [destaques.length]);

  useEffect(() => {
    if (nomeAnterior.current === nomeAtivo) return;
    nomeAnterior.current = nomeAtivo;
    const el = faixa.current;
    const ativo = el?.querySelector('[aria-selected="true"]');
    if (!(ativo instanceof HTMLElement) || !el) return;
    pausar(6000);
    const pad = 48;
    const alvo = ativo.getBoundingClientRect().left - el.getBoundingClientRect().left + el.scrollLeft - pad;
    el.scrollTo({ left: Math.max(0, alvo), behavior: 'smooth' });
  }, [nomeAtivo]);

  return (
    <section className="pos-precificacao-destaques-bloco" aria-label="Destaques por lucro bruto diário">
      <div className="pos-precificacao-carrossel">
        <div
          className="pos-precificacao-destaques"
          ref={faixa}
          role="listbox"
          aria-label="Recorte do gráfico"
          tabIndex={-1}
          onPointerDown={() => pausar()}
          onWheel={() => pausar(6000)}
          onMouseEnter={pausarNoHover}
          onMouseLeave={retomarDoHover}
        >
          {destaques.map((item) => {
            const ativo = item.id === nomeAtivo;
            const momUp = (item.mom ?? 0) >= 0;
            return (
              <button
                key={item.id}
                type="button"
                role="option"
                aria-selected={ativo}
                className={`pos-precificacao-destaque${ativo ? ' is-ativo' : ''}`}
                onClick={() => {
                  pausar();
                  onSelecionar(item.id);
                }}
              >
                <span>{item.nome}</span>
                <div className="pos-precificacao-destaque-linha">
                  <strong>{item.lucroDia == null ? '—' : formatCurrency(item.lucroDia)}</strong>
                  {item.mom == null ? (
                    <em className="is-neutro">sem mês anterior</em>
                  ) : (
                    <em className={momUp ? 'is-alta' : 'is-queda'}>
                      {momUp ? <ArrowUp size={10} /> : <ArrowDown size={10} />}
                      {textoSinal(item.mom).replace('+', '')}
                    </em>
                  )}
                </div>
              </button>
            );
          })}
        </div>
      </div>
      <div
        className="pos-precificacao-carrossel-trilho"
        ref={trilhoBarraRef}
        aria-label="Rolar destaques"
        onPointerDown={iniciarArrasteTrilho}
        onPointerMove={arrastarTrilho}
        onPointerUp={encerrarArrasteTrilho}
        onPointerCancel={encerrarArrasteTrilho}
      >
        <i ref={trilhoRef} />
      </div>
    </section>
  );
}

function GraficoSerie({
  titulo,
  nota,
  serie,
  dataKey,
  cor,
  formato,
  valorTopo,
  deltaTopo,
  rotuloCorte,
  mostrarRotulos = true,
}: {
  titulo: string;
  nota: string;
  serie: PontoSeriePrecificacao[];
  dataKey: 'margem' | 'lucro_dia' | 'qtd_dia';
  cor: string;
  formato: (valor: number) => string;
  valorTopo: string;
  deltaTopo: string | null;
  rotuloCorte?: string;
  mostrarRotulos?: boolean;
}) {
  const fillId = `pos-prec-${dataKey}`;
  const deltaAlta = deltaTopo != null && !deltaTopo.startsWith('−') && !deltaTopo.startsWith('-') && deltaTopo !== '—';
  return (
    <article className="glass-card glass-card-flat pos-precificacao-grafico">
      <header>
        <div>
          <h2>{titulo}</h2>
          <p>{nota}</p>
        </div>
        <div className="pos-precificacao-grafico-kpi">
          <strong>{valorTopo}</strong>
          {deltaTopo && deltaTopo !== '—' && (
            <em className={deltaAlta ? 'is-alta' : 'is-queda'}>{deltaTopo}</em>
          )}
        </div>
      </header>
      <div className="pos-precificacao-grafico-area">
        {serie.length === 0 ? (
          <p className="pos-precificacao-grafico-vazio">Sem série neste recorte.</p>
        ) : (
          <ResponsiveContainer width="100%" height={200}>
            <AreaChart data={serie} margin={{ top: 20, right: 14, left: 14, bottom: 4 }}>
              <defs>
                <linearGradient id={fillId} x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={cor} stopOpacity={0.35} />
                  <stop offset="100%" stopColor={cor} stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid stroke="var(--border)" vertical={false} />
              <XAxis dataKey="rotulo" tick={{ fill: 'var(--text-muted)', fontSize: 11 }} axisLine={false} tickLine={false} />
              <YAxis hide />
              {rotuloCorte && (
                <ReferenceLine
                  x={rotuloCorte}
                  stroke="var(--accent)"
                  strokeWidth={1.5}
                  strokeDasharray="4 4"
                  label={{
                    value: 'Precificação',
                    position: 'insideBottomLeft',
                    fill: 'var(--accent)',
                    fontSize: 10,
                    offset: 4,
                  }}
                />
              )}
              <Tooltip
                content={({ active, payload, label }) => {
                  if (!active || !payload?.length) return null;
                  const ponto = payload[0]?.payload as PontoSeriePrecificacao;
                  const diaSemana = diaSemanaAbrev(ponto.periodo);
                  return (
                    <div className="vendedores-chart-tooltip">
                      <strong>{label}{diaSemana ? ` · ${diaSemana}` : ''}</strong>
                      <dl>
                        <div><dt>Margem</dt><dd>{ponto.margem == null ? '—' : formatPercent(ponto.margem, 1)}</dd></div>
                        <div><dt>Lucro / dia</dt><dd>{ponto.lucro_dia == null ? '—' : formatCurrency(ponto.lucro_dia)}</dd></div>
                        <div><dt>Qtd / dia</dt><dd>{ponto.qtd_dia == null ? '—' : formatQtd(ponto.qtd_dia)}</dd></div>
                        <div><dt>Lucro</dt><dd>{formatCurrency(ponto.lucro)}</dd></div>
                        <div><dt>Qtd</dt><dd>{formatQtd(ponto.qtd)}</dd></div>
                      </dl>
                    </div>
                  );
                }}
              />
              <Area
                type="monotone"
                dataKey={dataKey}
                stroke={cor}
                strokeWidth={2}
                fill={`url(#${fillId})`}
                connectNulls={false}
                dot={{ r: mostrarRotulos ? 3 : 2, fill: cor, strokeWidth: 0 }}
                activeDot={{ r: 5 }}
                isAnimationActive={false}
              >
                {mostrarRotulos ? (
                  <LabelList
                    dataKey={dataKey}
                    position="top"
                    formatter={(valor: unknown) => (typeof valor === 'number' ? formato(valor) : '')}
                    style={{ fill: 'var(--text-primary)', fontSize: 11 }}
                  />
                ) : (
                  <LabelList
                    dataKey={dataKey}
                    position="top"
                    content={({ x, y, value, index }) => {
                      const ponto = index != null ? serie[Number(index)] : undefined;
                      if (!ponto || ponto.rotulo !== rotuloCorte || typeof value !== 'number') return null;
                      return (
                        <text x={x} y={Number(y) - 6} textAnchor="middle" fontSize={11} fill="var(--accent)">
                          {formato(value)}
                        </text>
                      );
                    }}
                  />
                )}
              </Area>
            </AreaChart>
          </ResponsiveContainer>
        )}
      </div>
    </article>
  );
}

function JanelaMini({ titulo, janela }: { titulo: string; janela: JanelaFixaPrecificacao }) {
  const semVenda = janela.receita_depois <= 0;
  const alta = !semVenda && (janela.variacao_lucro_pct ?? 0) >= 0;
  return (
    <div className={`pos-precificacao-linha-janela${semVenda ? ' is-neutro' : alta ? ' is-alta' : ' is-queda'}`}>
      <span className="pos-precificacao-linha-janela-titulo">
        {titulo}
        {!janela.completa && <i>em andamento</i>}
      </span>
      <strong>{formatCurrency(janela.lucro_depois)}</strong>
      <em>{semVenda ? 'sem venda' : textoSinal(janela.variacao_lucro_pct)}</em>
    </div>
  );
}

function LinhaPrecificada({
  item,
  maxReceita,
  ativo,
  onSelecionar,
}: {
  item: ItemPosPrecificacao;
  maxReceita: number;
  ativo: boolean;
  onSelecionar: () => void;
}) {
  const largura = maxReceita > 0 ? Math.max(4, (item.receita_depois / maxReceita) * 100) : 0;
  return (
    <li>
      <button
        type="button"
        className={`pos-precificacao-linha${ativo ? ' is-ativa' : ''}`}
        onClick={onSelecionar}
        aria-pressed={ativo}
      >
        <div className="despesas-lista-topo">
          <span>{item.nome}</span>
          <strong>{formatCurrency(item.lucro_depois)}</strong>
        </div>
        <i className="despesas-lista-trilho" aria-hidden="true">
          <b style={{ width: `${largura}%` }} />
        </i>
        <div className="despesas-lista-rodape">
          <em>
            {item.skus_dump} SKU
            {item.lucro_dia_depois != null ? ` · ${formatCurrency(item.lucro_dia_depois)}/dia` : ''}
            {item.qtd_dia_depois != null ? ` · ${formatQtd(item.qtd_dia_depois)} un/dia` : ''}
            {item.variacao_lucro_pct != null ? ` · ${textoSinal(item.variacao_lucro_pct)} lucro` : ''}
          </em>
          <span className={`pos-precificacao-chip is-${item.situacao}`}>
            {item.margem_depois != null ? formatPercent(item.margem_depois, 1) : '—'}
            {item.margem_alvo != null ? ` / alvo ${formatPercent(item.margem_alvo, 1)}` : ''}
            {' · '}
            {ROTULO_SITUACAO[item.situacao]}
          </span>
        </div>
        <div className="pos-precificacao-linha-janelas">
          <JanelaMini titulo="Semana" janela={item.janelas.semana} />
          <JanelaMini titulo="Mês" janela={item.janelas.mes} />
        </div>
      </button>
    </li>
  );
}
