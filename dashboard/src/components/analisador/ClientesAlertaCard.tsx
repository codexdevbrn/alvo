import { useEffect, useMemo, useState, type CSSProperties } from 'react';
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { AlertTriangle, FileDown, Filter, Loader2, Tag } from 'lucide-react';
import {
  explorarAgregar,
  gerarPainelCliente,
  type TagCatalogoItem,
  type TagCliente,
} from '../../api/client';
import { formatCurrency, formatNumber, formatPercent } from '../../utils/formatters';

type ItemCliente = {
  cliente: string;
  receita: number;
};

type Props = {
  empresa: string | null;
  loja?: string | null;
  itensClientes: ItemCliente[];
  tagsPorCliente: Record<string, TagCliente[]>;
  tagsCatalogo: TagCatalogoItem[];
  clientesBalcao: string[];
};

type PontoSerie = {
  periodo: string;
  rotulo: string;
  Receita: number;
  QTD: number;
};

type SerieCliente = {
  serie: PontoSerie[];
  receitaUltimo: number;
  qtdUltimo: number;
  rotuloUltimo: string;
  varReceita: number | null;
  varQtd: number | null;
  /** Mês anterior − atual (R$). Positivo = perda. */
  perdaReceita: number;
};

type SeriePorCliente = Record<string, SerieCliente>;

const MES_ABREV = [
  'jan', 'fev', 'mar', 'abr', 'mai', 'jun',
  'jul', 'ago', 'set', 'out', 'nov', 'dez',
];

const CHART_H = 120;

function normalizarTexto(s: string): string {
  return s
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLowerCase()
    .trim();
}

/** Nome previsível e seguro para o download no navegador. */
function slugArquivoCliente(nome: string): string {
  return nome
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .replace(/[^a-zA-Z0-9]+/g, '-')
    .replace(/^-|-$/g, '')
    .toLowerCase()
    .slice(0, 64) || 'cliente';
}

/** Resolve a tag "Alerta" pelo rótulo ou id (ex.: nova_tag / Alerta). */
function resolverTagAlerta(catalogo: TagCatalogoItem[]): TagCatalogoItem | null {
  const candidatas = catalogo.filter((t) => t.ativa !== false && t.entra_na_analise);
  const exata = candidatas.find((t) => {
    const id = normalizarTexto(t.id);
    const rotulo = normalizarTexto(t.rotulo);
    return id === 'alerta' || rotulo === 'alerta';
  });
  if (exata) return exata;
  return candidatas.find((t) => {
    const id = normalizarTexto(t.id);
    const rotulo = normalizarTexto(t.rotulo);
    return id.includes('alerta') || rotulo.includes('alerta');
  }) ?? null;
}

function rotuloPeriodoMensal(periodo: string): string {
  const m = /^(\d{4})-(\d{2})$/.exec(String(periodo).trim());
  if (!m) return periodo;
  const mes = Number(m[2]);
  if (mes < 1 || mes > 12) return periodo;
  return `${MES_ABREV[mes - 1]}/${m[1].slice(2)}`;
}

function parsePeriodoMensal(periodo: string): { ano: number; mes: number } | null {
  const m = /^(\d{4})-(\d{2})$/.exec(String(periodo).trim());
  if (!m) return null;
  const ano = Number(m[1]);
  const mes = Number(m[2]);
  if (!Number.isFinite(ano) || mes < 1 || mes > 12) return null;
  return { ano, mes };
}

function formatPeriodoMensal(ano: number, mes: number): string {
  return `${ano}-${String(mes).padStart(2, '0')}`;
}

/** Lista contínua YYYY-MM de `inicio` até `fim` (inclusive). */
function mesesEntre(inicio: string, fim: string): string[] {
  const a = parsePeriodoMensal(inicio);
  const b = parsePeriodoMensal(fim);
  if (!a || !b) return [];
  const out: string[] = [];
  let { ano, mes } = a;
  while (ano < b.ano || (ano === b.ano && mes <= b.mes)) {
    out.push(formatPeriodoMensal(ano, mes));
    mes += 1;
    if (mes > 12) {
      mes = 1;
      ano += 1;
    }
    if (out.length > 120) break;
  }
  return out;
}

/** Preenche meses sem movimento com 0 para o eixo ficar contínuo. */
function preencherSerieMensal(pontos: PontoSerie[], calendario: string[]): PontoSerie[] {
  if (calendario.length === 0) return pontos;
  const porPeriodo = new Map<string, PontoSerie>();
  for (const p of pontos) {
    const chave = String(p.periodo).trim();
    if (!parsePeriodoMensal(chave)) continue;
    const prev = porPeriodo.get(chave);
    if (!prev) {
      porPeriodo.set(chave, { ...p, periodo: chave });
      continue;
    }
    // Soma se vier duplicado do backend.
    porPeriodo.set(chave, {
      ...prev,
      Receita: prev.Receita + (Number(p.Receita) || 0),
      QTD: prev.QTD + (Number(p.QTD) || 0),
    });
  }
  return calendario.map((periodo) => {
    const existente = porPeriodo.get(periodo);
    if (existente) return existente;
    return {
      periodo,
      rotulo: rotuloPeriodoMensal(periodo),
      Receita: 0,
      QTD: 0,
    };
  });
}

function deslocarMes(periodo: string, delta: number): string | null {
  const p = parsePeriodoMensal(periodo);
  if (!p) return null;
  const idx = p.ano * 12 + (p.mes - 1) + delta;
  const ano = Math.floor(idx / 12);
  const mes = (idx % 12) + 1;
  return formatPeriodoMensal(ano, mes);
}

const MESES_CORRIDOS = 6;

/**
 * Últimos N meses corridos até `fim` (ou até o último mês com dado).
 * Meses sem movimento entram como 0 — contam na janela e aparecem no eixo.
 */
function serieUltimosMesesCorridos(
  pontos: PontoSerie[],
  n = MESES_CORRIDOS,
  fimForcado?: string | null,
): PontoSerie[] {
  const ordenados = [...pontos]
    .filter((p) => parsePeriodoMensal(p.periodo))
    .sort((a, b) => a.periodo.localeCompare(b.periodo));

  const fim =
    (fimForcado && parsePeriodoMensal(fimForcado) ? fimForcado : null)
    ?? ordenados[ordenados.length - 1]?.periodo
    ?? null;
  if (!fim) return [];

  const inicio = deslocarMes(fim, -(n - 1));
  if (!inicio) return ordenados.slice(-n);
  return preencherSerieMensal(ordenados, mesesEntre(inicio, fim));
}

/** Variação % do último mês vs o anterior (na série já preenchida). */
function variacaoNosUltimosMeses(
  pontos: PontoSerie[],
  chave: 'Receita' | 'QTD',
): number | null {
  if (pontos.length < 2) return null;
  const atual = pontos[pontos.length - 1][chave];
  const anterior = pontos[pontos.length - 2][chave];
  if (!(anterior > 0) || !Number.isFinite(atual)) return null;
  return ((atual - anterior) / anterior) * 100;
}

/** Perda absoluta de receita (R$): mês anterior − atual. Positivo = queda. */
function perdaReceitaAbs(bloco?: SerieCliente | null): number {
  if (bloco && Number.isFinite(bloco.perdaReceita)) return bloco.perdaReceita;
  const pontos = bloco?.serie;
  if (!pontos || pontos.length < 2) return 0;
  const atual = Number(pontos[pontos.length - 1].Receita) || 0;
  const anterior = Number(pontos[pontos.length - 2].Receita) || 0;
  return anterior - atual;
}

function perdaReceitaDaSerie(pontos: PontoSerie[]): number {
  if (pontos.length < 2) return 0;
  const atual = Number(pontos[pontos.length - 1].Receita) || 0;
  const anterior = Number(pontos[pontos.length - 2].Receita) || 0;
  return anterior - atual;
}

function BadgeVariacao({ pct }: { pct: number | null }) {
  if (pct == null || !Number.isFinite(pct)) {
    return <span className="analisador-alerta-var neutro">—</span>;
  }
  const positivo = pct >= 0;
  return (
    <span className={`analisador-alerta-var ${positivo ? 'alta' : 'queda'}`}>
      {positivo ? '↑' : '↓'} {formatPercent(Math.abs(pct), 1)}
    </span>
  );
}

/** Mostra perda/ganho em R$ (critério da ordenação) + % vs mês anterior. */
function BadgePerdaReceita({
  perdaRs,
  pct,
}: {
  perdaRs: number;
  pct: number | null;
}) {
  if (!Number.isFinite(perdaRs) || (perdaRs === 0 && (pct == null || !Number.isFinite(pct)))) {
    return <span className="analisador-alerta-var neutro">—</span>;
  }
  const queda = perdaRs > 0;
  const alta = perdaRs < 0;
  const classe = queda ? 'queda' : alta ? 'alta' : 'neutro';
  const seta = queda ? '↓' : alta ? '↑' : '→';
  return (
    <span className={`analisador-alerta-var ${classe}`}>
      {seta} {formatCurrency(Math.abs(perdaRs))}
      {pct != null && Number.isFinite(pct) ? ` · ${formatPercent(Math.abs(pct), 1)}` : ''}
    </span>
  );
}

function MiniChart({
  titulo,
  data,
  dataKey,
  cor,
  formatValor,
}: {
  titulo: string;
  data: PontoSerie[];
  dataKey: 'Receita' | 'QTD';
  cor: string;
  formatValor: (v: number) => string;
}) {
  return (
    <div className="analisador-alerta-chart">
      <h3>{titulo}</h3>
      <ResponsiveContainer width="100%" height={CHART_H}>
        <AreaChart data={data} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
          <CartesianGrid stroke="rgba(255,255,255,0.06)" vertical={false} />
          <XAxis
            dataKey="rotulo"
            interval={0}
            tick={{ fill: 'var(--text-secondary)', fontSize: 10 }}
          />
          <YAxis
            tick={{ fill: 'var(--text-secondary)', fontSize: 10 }}
            tickFormatter={(v) => formatNumber(Number(v))}
            width={44}
          />
          <Tooltip
            contentStyle={{
              background: '#1a1a1e',
              border: '1px solid var(--border)',
              borderRadius: 8,
            }}
            formatter={(value) => [formatValor(Number(value ?? 0)), titulo]}
          />
          <Area
            type="monotone"
            dataKey={dataKey}
            stroke={cor}
            fill="transparent"
            strokeWidth={1.75}
            dot={{ r: 3, fill: cor, strokeWidth: 0 }}
            activeDot={{ r: 4 }}
            connectNulls
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}

export function ClientesAlertaCard({
  empresa,
  loja = null,
  itensClientes,
  tagsPorCliente,
  tagsCatalogo,
  clientesBalcao,
}: Props) {
  const [seriePorCliente, setSeriePorCliente] = useState<SeriePorCliente>({});
  const [carregando, setCarregando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);
  const [gerandoPainel, setGerandoPainel] = useState<string | null>(null);
  // `null` mantém a tag Alerta como foco inicial; string vazia representa todas.
  const [tagSelecionada, setTagSelecionada] = useState<string | null>(null);

  const balcaoSet = useMemo(() => new Set(clientesBalcao), [clientesBalcao]);
  const tagsDisponiveis = useMemo(
    () => tagsCatalogo.filter((tag) => tag.ativa && tag.entra_na_analise && tag.id !== 'cliente_balcao'),
    [tagsCatalogo],
  );
  const tagAlerta = useMemo(() => resolverTagAlerta(tagsCatalogo), [tagsCatalogo]);

  // Catálogo pode mudar por empresa; não deixa filtro apontar para tag removida.
  useEffect(() => {
    setTagSelecionada((atual) => {
      if (atual === '') return atual;
      if (atual && tagsDisponiveis.some((tag) => tag.id === atual)) return atual;
      return tagAlerta?.id ?? tagsDisponiveis[0]?.id ?? null;
    });
  }, [tagAlerta, tagsDisponiveis]);

  const tagEmFoco = useMemo(() => {
    if (tagSelecionada === '') return null;
    if (tagSelecionada) {
      return tagsDisponiveis.find((tag) => tag.id === tagSelecionada) ?? null;
    }
    return tagAlerta ?? tagsDisponiveis[0] ?? null;
  }, [tagAlerta, tagSelecionada, tagsDisponiveis]);
  const avaliarTodas = tagSelecionada === '';

  const clientesAlerta = useMemo(() => {
    if (!tagEmFoco && !avaliarTodas) return [];
    const receitaPorCliente = new Map(
      itensClientes.map((i) => [i.cliente.trim(), i.receita] as const),
    );
    const balcaoNorm = new Set([...balcaoSet].map((c) => c.trim()));
    const nomes = new Set<string>();
    for (const k of Object.keys(tagsPorCliente)) {
      const n = k.trim();
      if (n) nomes.add(n);
    }
    for (const i of itensClientes) {
      const n = i.cliente.trim();
      if (n) nomes.add(n);
    }
    return Array.from(nomes)
      .filter((cliente) => {
        if (balcaoNorm.has(cliente)) return false;
        const tags = tagsPorCliente[cliente] ?? [];
        if (tags.includes('cliente_balcao')) return false;
        return avaliarTodas
          ? tags.some((tag) => tagsDisponiveis.some((item) => item.id === tag))
          : tags.includes(tagEmFoco?.id ?? '');
      })
      .map((cliente) => ({
        cliente,
        receita: receitaPorCliente.get(cliente) ?? 0,
      }));
  }, [avaliarTodas, tagEmFoco, tagsDisponiveis, tagsPorCliente, itensClientes, balcaoSet]);

  /** Maior perda de receita (R$ vs mês anterior) primeiro; depois pior %; depois receita. */
  const clientesAlertaOrdenados = useMemo(() => {
    return [...clientesAlerta].sort((a, b) => {
      const blocoA = seriePorCliente[a.cliente];
      const blocoB = seriePorCliente[b.cliente];
      const perdaA = perdaReceitaAbs(blocoA);
      const perdaB = perdaReceitaAbs(blocoB);
      if (perdaA !== perdaB) return perdaB - perdaA;
      const varA = blocoA?.varReceita;
      const varB = blocoB?.varReceita;
      const pctA = varA == null || !Number.isFinite(varA) ? 0 : varA;
      const pctB = varB == null || !Number.isFinite(varB) ? 0 : varB;
      if (pctA !== pctB) return pctA - pctB;
      return b.receita - a.receita;
    });
  }, [clientesAlerta, seriePorCliente]);

  const chaveClientesAlerta = useMemo(
    () => clientesAlerta.map((c) => c.cliente).join('\n'),
    [clientesAlerta],
  );

  useEffect(() => {
    if (!empresa || !chaveClientesAlerta) {
      setSeriePorCliente({});
      setErro(null);
      setCarregando(false);
      return;
    }

    const nomes = chaveClientesAlerta.split('\n').filter(Boolean);
    const controller = new AbortController();
    setCarregando(true);
    setErro(null);

    void explorarAgregar(
      {
        empresa,
        loja,
        dimensoes: ['Cliente', 'Periodo_Mensal'],
        metricas: ['Receita', 'QTD'],
        filtros: { Cliente: nomes },
        aplicar_grupos: false,
        limite: Math.max(500, nomes.length * 36),
        ordenar_por: 'Periodo_Mensal',
        ordem: 'asc',
        modo_viz: 'agregar',
      },
      controller.signal,
    )
      .then((res) => {
        const iCliente = res.colunas.indexOf('Cliente');
        const iPeriodo = res.colunas.indexOf('Periodo_Mensal');
        const iReceita = res.colunas.indexOf('Receita');
        const iQtd = res.colunas.indexOf('QTD');
        if (iCliente < 0 || iPeriodo < 0) {
          setSeriePorCliente({});
          return;
        }

        const bruto: Record<string, PontoSerie[]> = {};
        let fimGlobal: string | null = null;
        for (const linha of res.linhas) {
          const cliente = String(linha[iCliente] ?? '').trim();
          if (!cliente) continue;
          const periodo = String(linha[iPeriodo] ?? '').trim();
          if (!parsePeriodoMensal(periodo)) continue;
          if (!fimGlobal || periodo > fimGlobal) fimGlobal = periodo;
          const ponto: PontoSerie = {
            periodo,
            rotulo: rotuloPeriodoMensal(periodo),
            Receita: iReceita >= 0 ? Number(linha[iReceita]) || 0 : 0,
            QTD: iQtd >= 0 ? Number(linha[iQtd]) || 0 : 0,
          };
          (bruto[cliente] ??= []).push(ponto);
        }

        // Garante todos os clientes em alerta na janela, mesmo sem linha na agregação.
        for (const nome of nomes) {
          bruto[nome] ??= [];
        }

        const agrupado: SeriePorCliente = {};
        for (const [cliente, pontos] of Object.entries(bruto)) {
          const chave = cliente.trim();
          if (!chave) continue;
          const serie = serieUltimosMesesCorridos(pontos, MESES_CORRIDOS, fimGlobal);
          const ultimo = serie[serie.length - 1];
          agrupado[chave] = {
            serie,
            receitaUltimo: ultimo?.Receita ?? 0,
            qtdUltimo: ultimo?.QTD ?? 0,
            rotuloUltimo: ultimo?.rotulo ?? '',
            varReceita: variacaoNosUltimosMeses(serie, 'Receita'),
            varQtd: variacaoNosUltimosMeses(serie, 'QTD'),
            perdaReceita: perdaReceitaDaSerie(serie),
          };
        }
        setSeriePorCliente(agrupado);
      })
      .catch((err) => {
        if (err instanceof DOMException && err.name === 'AbortError') return;
        setSeriePorCliente({});
        setErro(err instanceof Error ? err.message : 'Falha ao carregar série dos alertas.');
      })
      .finally(() => {
        if (!controller.signal.aborted) setCarregando(false);
      });

    return () => controller.abort();
  }, [empresa, loja, chaveClientesAlerta]);

  if (!empresa) return null;

  const cor = tagEmFoco?.cor ?? 'var(--accent)';

  const baixarPainel = async (cliente: string, posicao: number, total: number) => {
    if (!empresa || gerandoPainel) return;
    setGerandoPainel(cliente);
    setErro(null);
    try {
      const blob = await gerarPainelCliente({ empresa, cliente, loja, posicao, total });
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `painel-cliente-${slugArquivoCliente(cliente)}.pdf`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    } catch (e) {
      setErro(e instanceof Error ? e.message : `Falha ao gerar painel de ${cliente}.`);
    } finally {
      setGerandoPainel(null);
    }
  };

  if (!tagsDisponiveis.length) {
    return (
      <div className="glass-card glass-card-flat analisador-alerta-card">
        <h2 className="analisador-titulo">
          <AlertTriangle size={18} style={{ color: '#f59e0b' }} /> Clientes em alerta
        </h2>
        <p className="analisador-hint" style={{ margin: 0 }}>
          Crie uma tag chamada <strong style={{ color: 'white' }}>Alerta</strong> em Configurações
          e marque os clientes na prévia para acompanhar aqui.
        </p>
      </div>
    );
  }

  const tituloFiltro = avaliarTodas ? 'Todas as tags' : (tagEmFoco?.rotulo ?? 'Clientes');
  const tituloCard = avaliarTodas ? 'Clientes com tags' : `Clientes em ${tituloFiltro.toLowerCase()}`;
  const corBorda = cor.startsWith('var(') ? 'var(--border)' : `${cor}55`;

  return (
    <div
      className="glass-card glass-card-flat analisador-alerta-card"
      style={{ borderColor: corBorda }}
    >
      <div className="analisador-alerta-filtros" aria-label="Filtrar avaliação por tag">
        <span className="analisador-alerta-filtros-label">
          <Filter size={14} aria-hidden="true" /> Avaliar por tag
        </span>
        <div className="analisador-alerta-filtros-lista">
          <button
            type="button"
            className={`analisador-alerta-filtro${avaliarTodas ? ' is-ativo' : ''}`}
            onClick={() => setTagSelecionada('')}
            aria-pressed={avaliarTodas}
          >
            Todas as tags
            <span>{clientesAlerta.length}</span>
          </button>
          {tagsDisponiveis.map((tag) => {
            const total = Object.values(tagsPorCliente).filter((tags) => tags.includes(tag.id)).length;
            const ativo = !avaliarTodas && tagEmFoco?.id === tag.id;
            return (
              <button
                key={tag.id}
                type="button"
                className={`analisador-alerta-filtro${ativo ? ' is-ativo' : ''}`}
                style={{ '--tag-cor': tag.cor } as CSSProperties}
                onClick={() => setTagSelecionada(tag.id)}
                aria-pressed={ativo}
              >
                {tag.rotulo}
                <span>{total}</span>
              </button>
            );
          })}
        </div>
      </div>
      <header className="analisador-alerta-header">
        <h2 className="analisador-titulo">
          {tagEmFoco?.id === 'alerta'
            ? <AlertTriangle size={18} style={{ color: cor, flexShrink: 0 }} />
            : <Tag size={18} style={{ color: cor, flexShrink: 0 }} />}
          {tituloCard}
          <span className="analisador-tag-chip" style={{ borderColor: cor, color: cor }}>
            {tituloFiltro}
          </span>
          {clientesAlerta.length > 0 && (
            <span className="analisador-alerta-count">{clientesAlerta.length}</span>
          )}
        </h2>
        <p className="analisador-hint">
          Um bloco por cliente — últimos 6 meses. Ordenados pela maior perda de receita em R$
          (mês atual vs anterior).
        </p>
      </header>

      {clientesAlerta.length === 0 ? (
        <p className="analisador-lista-vazia" role="status">
          {avaliarTodas
            ? 'Nenhum cliente possui tags de acompanhamento. Marque na base de clientes abaixo.'
            : <>Nenhum cliente com a tag “{tagEmFoco?.rotulo}”. Marque na base de clientes abaixo.</>}
        </p>
      ) : (
        <>
          {carregando && (
            <p className="analisador-hint analisador-alerta-status">
              <Loader2 size={14} className="dashboard-filter-spinner" /> Carregando gráficos…
            </p>
          )}
          {erro && (
            <p className="analisador-alerta-status" style={{ color: '#f43f5e' }} role="alert">
              {erro}
            </p>
          )}

          <div className="analisador-alerta-clientes custom-scrollbar">
            {clientesAlertaOrdenados.map((item, indice) => {
              const bloco = seriePorCliente[item.cliente];
              const serie = bloco?.serie ?? [];
              const receitaUltimo = bloco?.receitaUltimo ?? item.receita;
              const qtdUltimo = bloco?.qtdUltimo ?? 0;
              const varReceita = bloco?.varReceita ?? null;
              const varQtd = bloco?.varQtd ?? null;
              const perdaReceita = bloco?.perdaReceita ?? perdaReceitaAbs(bloco);
              const rotuloUltimo = bloco?.rotuloUltimo || null;

              return (
                <article key={item.cliente} className="analisador-alerta-cliente">
                  <div className="analisador-alerta-cliente-topo">
                    <div className="analisador-alerta-cliente-titulo">
                      <h3 className="analisador-alerta-cliente-nome" title={item.cliente}>
                        {item.cliente}
                      </h3>
                      {rotuloUltimo && (
                        <span className="analisador-alerta-vs">
                          Últimos 6 meses · {rotuloUltimo} · variação vs mês anterior
                        </span>
                      )}
                    </div>
                    <div className="analisador-alerta-cliente-acoes">
                      <button
                        type="button"
                        className="analisador-btn analisador-btn-sec analisador-btn-compact analisador-alerta-painel-btn"
                        onClick={() => void baixarPainel(
                          item.cliente,
                          indice + 1,
                          clientesAlertaOrdenados.length,
                        )}
                        disabled={gerandoPainel != null}
                        aria-label={`Gerar painel PDF de ${item.cliente}`}
                      >
                        {gerandoPainel === item.cliente
                          ? <Loader2 size={14} className="dashboard-filter-spinner" aria-hidden="true" />
                          : <FileDown size={14} aria-hidden="true" />}
                        {gerandoPainel === item.cliente ? 'Gerando…' : 'Painel PDF'}
                      </button>
                      <div className="analisador-alerta-cliente-kpis">
                        <div className="analisador-alerta-kpi">
                          <span>Receita</span>
                          <strong>
                            {formatCurrency(receitaUltimo)}
                            <BadgePerdaReceita perdaRs={perdaReceita} pct={varReceita} />
                          </strong>
                        </div>
                        <div className="analisador-alerta-kpi">
                          <span>Quantidade</span>
                          <strong>
                            {formatNumber(qtdUltimo)}
                            <BadgeVariacao pct={varQtd} />
                          </strong>
                        </div>
                      </div>
                    </div>
                  </div>

                  {!carregando && !erro && serie.length === 0 ? (
                    <p className="analisador-hint" style={{ margin: 0 }}>
                      Sem movimento no período carregado.
                    </p>
                  ) : serie.length > 0 ? (
                    <div className="analisador-alerta-charts-grid">
                      <MiniChart
                        titulo="Receita mensal"
                        data={serie}
                        dataKey="Receita"
                        cor={cor}
                        formatValor={formatCurrency}
                      />
                      <MiniChart
                        titulo="Quantidade mensal"
                        data={serie}
                        dataKey="QTD"
                        cor="#38bdf8"
                        formatValor={formatNumber}
                      />
                    </div>
                  ) : null}
                </article>
              );
            })}
          </div>
        </>
      )}
    </div>
  );
}
