import type { DashboardData } from '../types/dashboard';
import type { GranularidadeDash } from './granularidade';
import {
  indicesPeriodosFechados,
  bucketKeyFromMonth,
  labelBucketShort,
} from './granularidade';
import {
  MES_ABREV,
  mesDeRotulo,
  ultimoMesFechado,
  mesAtualNum,
  abrevMesAtual,
  mesAbrevDeRotulo,
  abrevUltimoMesFechado,
} from './mesesCalendario';

export {
  MES_ABREV,
  mesDeRotulo,
  ultimoMesFechado,
  mesAtualNum,
  abrevMesAtual,
  mesAbrevDeRotulo,
  abrevUltimoMesFechado,
};

/** Um mês entra nos cálculos padrão se já estiver fechado (exclui o mês corrente).
 *  Em todos os anos aplica o mesmo corte (jan..mês anterior) para comparação YoY justa.
 *  Exceção: em janeiro o ano corrente ainda não tem mês fechado — entram anos anteriores completos. */
export function mesEhFechado(
  entry: { name: string; year: number },
  ref: Date = new Date(),
): boolean {
  const mes = mesDeRotulo(entry.name);
  if (mes <= 0) return false;

  const anoAtual = ref.getFullYear();
  const limite = ultimoMesFechado(ref);

  if (limite <= 0) {
    return entry.year < anoAtual;
  }

  return mes <= limite;
}

/** Índices em `data.monthly` dos meses fechados (padrão de cálculo). */
export function indicesMesesFechados(data: DashboardData, ref: Date = new Date()): number[] {
  return data.monthly
    .map((m, idx) => (mesEhFechado(m, ref) ? idx : -1))
    .filter((idx) => idx !== -1);
}

/** Um mês entra em "até agora" se seu número for ≤ ao mês corrente — inclui o
 *  mês corrente, ainda aberto (diferente de `mesEhFechado`, que o exclui).
 *  Mesmo corte em todos os anos, para comparação YoY justa. */
export function mesEhAteAgora(entry: { name: string }, ref: Date = new Date()): boolean {
  const mes = mesDeRotulo(entry.name);
  if (mes <= 0) return false;
  return mes <= mesAtualNum(ref);
}

/** Índices em `data.monthly` até o mês corrente (inclusive) em todos os anos. */
export function indicesAteMesAtual(data: DashboardData, ref: Date = new Date()): number[] {
  return data.monthly
    .map((m, idx) => (mesEhAteAgora(m, ref) ? idx : -1))
    .filter((idx) => idx !== -1);
}

/** Último mês (1–12) presente no ano mais recente do dataset. */
export function ultimoMesDisponivelAnoRecente(data: DashboardData): number {
  if (data.monthly.length === 0) return 12;
  const anoMaisRecente = Math.max(...data.monthly.map((m) => m.year));
  const mesesDoAnoRecente = data.monthly
    .filter((m) => m.year === anoMaisRecente)
    .map((m) => mesDeRotulo(m.name));
  return mesesDoAnoRecente.length > 0 ? Math.max(...mesesDoAnoRecente) : 12;
}

/** Índices de `data.monthly` cujo mês (1–12) é ≤ ao último mês disponível no ano
 *  mais recente do dataset. Sem isso, anos anteriores completos (ex.: 2025 até
 *  dez) esticam o eixo do gráfico além do ano corrente (ex.: 2026 até jul),
 *  deixando meses futuros vazios — o ano corrente incompleto deve limitar até
 *  onde qualquer ano é exibido, não o contrário. */
function periodoAteUltimoMesDisponivel(data: DashboardData): number[] {
  const ultimoMes = ultimoMesDisponivelAnoRecente(data);
  return data.monthly
    .map((m, idx) => (mesDeRotulo(m.name) <= ultimoMes ? idx : -1))
    .filter((idx) => idx !== -1);
}

/** Garante YoY justo: nenhum ano entra com mês além do último mês que existe
 *  no ano mais recente (evita comparar 6 meses de 2025 vs 3 de 2026). */
function limitarAoMesDoAnoRecente(data: DashboardData, indices: number[]): number[] {
  const ultimoMes = ultimoMesDisponivelAnoRecente(data);
  return indices.filter((i) => {
    const m = data.monthly[i];
    return m && mesDeRotulo(m.name) > 0 && mesDeRotulo(m.name) <= ultimoMes;
  });
}

/** Base antes do filtro de meses fechados: seleção manual ou até o último mês disponível. */
export function periodoBase(data: DashboardData, period: number[]): number[] {
  return period.length > 0 ? period : periodoAteUltimoMesDisponivel(data);
}

/** Período efetivo para cálculos: base × opcionalmente só períodos fechados (por grain),
 *  sempre limitado ao último mês existente no ano mais recente (YoY justo). */
export function resolverPeriodoEfetivo(
  data: DashboardData,
  period: number[],
  usarMesesFechados = true,
  ref: Date = new Date(),
  granularidade: GranularidadeDash = 'Mensal',
): number[] {
  const base = periodoBase(data, period);
  let resultado = base;
  if (usarMesesFechados) {
    const fechados = new Set(
      granularidade === 'Mensal'
        ? indicesMesesFechados(data, ref)
        : indicesPeriodosFechados(data, granularidade, ref),
    );
    resultado = resultado.filter((i) => fechados.has(i));
  }
  return limitarAoMesDoAnoRecente(data, resultado);
}

/** Rótulo curto do corte no ano atual (ex.: "até jun/26"). */
export function rotuloCorteMesesFechados(ref: Date = new Date()): string {
  const limite = ultimoMesFechado(ref);
  const ano = ref.getFullYear();
  if (limite <= 0) {
    return `ano ${ano} ainda sem mês fechado`;
  }
  return `até ${MES_ABREV[limite]}/${String(ano).slice(2)}`;
}

/** Texto para combobox / banner quando o padrão (meses fechados) está ativo. */
export function descricaoPeriodoPadrao(
  data: DashboardData,
  ref: Date = new Date(),
  granularidade: GranularidadeDash = 'Mensal',
): string {
  const limite = ultimoMesFechado(ref);
  const qtd = (
    granularidade === 'Mensal'
      ? indicesMesesFechados(data, ref)
      : indicesPeriodosFechados(data, granularidade, ref)
  ).length;
  if (limite <= 0) {
    return granularidade === 'Mensal'
      ? 'Meses fechados (anos anteriores completos)'
      : 'Períodos fechados (anos anteriores completos)';
  }
  if (granularidade === 'Mensal') {
    return `Meses fechados (jan–${MES_ABREV[limite]} em cada ano · ${qtd} meses)`;
  }
  return `Períodos fechados (corte jan–${MES_ABREV[limite]} · ${qtd} meses)`;
}

/** Banner explicativo fixo no painel de filtros. */
export function textoBannerMesesFechados(
  ref: Date = new Date(),
  granularidade: GranularidadeDash = 'Mensal',
): string {
  const limite = ultimoMesFechado(ref);
  const mesCorrente = MES_ABREV[limite + 1] ?? '?';
  const ano = String(ref.getFullYear()).slice(2);
  const unidade =
    granularidade === 'Mensal' ? 'meses' :
    granularidade === 'Trimestral' ? 'trimestres' :
    granularidade === 'Semestral' ? 'semestres' : 'anos';
  if (limite <= 0) {
    return `Os cálculos usam apenas ${unidade} fechados. Em janeiro/${ano} ainda não há mês fechado no ano corrente — entram os anos anteriores completos.`;
  }
  if (granularidade === 'Mensal') {
    return `Os cálculos usam meses fechados (jan–${MES_ABREV[limite]} em cada ano). O mês corrente (${mesCorrente}/${ano}) fica de fora por estar em aberto.`;
  }
  return `Os cálculos usam ${unidade} fechados (corte jan–${MES_ABREV[limite]}). O período corrente em aberto fica de fora.`;
}

export function periodosIguais(a: number[], b: number[]): boolean {
  if (a.length !== b.length) return false;
  const sa = [...a].sort((x, y) => x - y);
  const sb = [...b].sort((x, y) => x - y);
  return sa.every((v, i) => v === sb[i]);
}

/** Abreviatura/rótulo curto do bucket de corte para a linha no gráfico. */
export function rotuloCorteFechadoParaGrafico(
  granularidade: GranularidadeDash,
  ref: Date = new Date(),
): string | null {
  const limite = ultimoMesFechado(ref);
  if (limite <= 0) return null;
  if (granularidade === 'Mensal') return MES_ABREV[limite] ?? null;
  const key = bucketKeyFromMonth(ref.getFullYear(), limite, granularidade);
  return labelBucketShort(key, granularidade);
}
