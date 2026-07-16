import type { DashboardData, MonthlyData, GranularidadeDash } from '../types/dashboard';
import { mesDeRotulo, ultimoMesFechado, mesAtualNum } from './mesesCalendario';

export type { GranularidadeDash };
export const GRANULARIDADES_DASH: GranularidadeDash[] = [
  'Mensal',
  'Trimestral',
  'Semestral',
  'Anual',
];

const MES_ABREV = ['', 'jan', 'fev', 'mar', 'abr', 'mai', 'jun', 'jul', 'ago', 'set', 'out', 'nov', 'dez'];

/** Chave canônica: `2025-01` | `2025-T1` | `2025-S1` | `2025` */
export function bucketKeyFromMonth(year: number, month: number, gran: GranularidadeDash): string {
  if (month < 1 || month > 12) return '';
  if (gran === 'Mensal') return `${year}-${String(month).padStart(2, '0')}`;
  if (gran === 'Anual') return String(year);
  if (gran === 'Semestral') return `${year}-S${month <= 6 ? 1 : 2}`;
  const trimestre = Math.ceil(month / 3);
  return `${year}-T${trimestre}`;
}

export function bucketKeyFromEntry(
  entry: MonthlyData,
  gran: GranularidadeDash,
): string {
  return bucketKeyFromMonth(entry.year, mesDeRotulo(entry.name), gran);
}

export function bucketKeyFromIndex(
  data: DashboardData,
  idx: number,
  gran: GranularidadeDash,
): string {
  const entry = data.monthly[idx];
  if (!entry) return '';
  return bucketKeyFromEntry(entry, gran);
}

/** Meses 1–12 que compõem o bucket (sem ano). */
export function monthsInBucketKey(bucketKey: string, gran: GranularidadeDash): number[] {
  if (gran === 'Mensal') {
    const m = Number(bucketKey.split('-')[1]);
    return m >= 1 && m <= 12 ? [m] : [];
  }
  if (gran === 'Anual') return [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12];
  if (gran === 'Semestral') {
    const s = bucketKey.includes('-S2') ? 2 : 1;
    return s === 1 ? [1, 2, 3, 4, 5, 6] : [7, 8, 9, 10, 11, 12];
  }
  const tMatch = bucketKey.match(/-T([1-4])$/);
  const t = tMatch ? Number(tMatch[1]) : 1;
  const start = (t - 1) * 3 + 1;
  return [start, start + 1, start + 2];
}

export function yearFromBucketKey(bucketKey: string, gran: GranularidadeDash): number {
  if (gran === 'Anual') return Number(bucketKey);
  return Number(bucketKey.split('-')[0]);
}

/** Último mês (1–12) do bucket — usado para saber se o período está fechado. */
export function lastMonthOfBucket(bucketKey: string, gran: GranularidadeDash): number {
  const meses = monthsInBucketKey(bucketKey, gran);
  return meses.length ? Math.max(...meses) : 0;
}

/** Rótulo curto no eixo (YoY): jan | T1 | S1 | 2025 */
export function labelBucketShort(bucketKey: string, gran: GranularidadeDash): string {
  if (!bucketKey) return '';
  if (gran === 'Anual') return bucketKey;
  if (gran === 'Mensal') {
    const m = Number(bucketKey.split('-')[1]);
    return MES_ABREV[m] ?? bucketKey;
  }
  if (gran === 'Semestral') {
    return bucketKey.includes('-S2') ? 'S2' : 'S1';
  }
  const t = bucketKey.match(/-T([1-4])$/)?.[1] ?? '1';
  return `T${t}`;
}

/** Rótulo com ano: T1/25 | S1/25 | jan/25 | 2025 */
export function labelBucketWithYear(bucketKey: string, gran: GranularidadeDash): string {
  if (gran === 'Anual') return bucketKey;
  const year = yearFromBucketKey(bucketKey, gran);
  const yy = String(year).slice(2);
  return `${labelBucketShort(bucketKey, gran)}/${yy}`;
}

/** Ordem estável de rótulos curtos no eixo YoY. */
export function orderShortLabels(gran: GranularidadeDash): string[] {
  if (gran === 'Mensal') {
    return ['jan', 'fev', 'mar', 'abr', 'mai', 'jun', 'jul', 'ago', 'set', 'out', 'nov', 'dez'];
  }
  if (gran === 'Trimestral') return ['T1', 'T2', 'T3', 'T4'];
  if (gran === 'Semestral') return ['S1', 'S2'];
  return [];
}

export function sortBucketKeys(keys: string[], gran: GranularidadeDash): string[] {
  return [...keys].sort((a, b) => {
    const ya = yearFromBucketKey(a, gran);
    const yb = yearFromBucketKey(b, gran);
    if (ya !== yb) return ya - yb;
    if (gran === 'Anual') return 0;
    if (gran === 'Mensal') {
      return Number(a.split('-')[1]) - Number(b.split('-')[1]);
    }
    if (gran === 'Semestral') {
      return (a.includes('-S2') ? 2 : 1) - (b.includes('-S2') ? 2 : 1);
    }
    const ta = Number(a.match(/-T([1-4])$/)?.[1] ?? 0);
    const tb = Number(b.match(/-T([1-4])$/)?.[1] ?? 0);
    return ta - tb;
  });
}

export type BucketInfo = {
  key: string;
  year: number;
  label: string;
  shortLabel: string;
  monthIndices: number[];
};

/** Lista de buckets presentes em `data.monthly` para a granularidade. */
export function listBuckets(data: DashboardData, gran: GranularidadeDash): BucketInfo[] {
  const map = new Map<string, number[]>();
  data.monthly.forEach((m, idx) => {
    const key = bucketKeyFromEntry(m, gran);
    if (!key) return;
    const list = map.get(key) ?? [];
    list.push(idx);
    map.set(key, list);
  });
  return sortBucketKeys([...map.keys()], gran).map((key) => ({
    key,
    year: yearFromBucketKey(key, gran),
    label: labelBucketWithYear(key, gran),
    shortLabel: labelBucketShort(key, gran),
    monthIndices: map.get(key) ?? [],
  }));
}

/** Bucket fechado = seu último mês já passou do corte de calendário.
 *  Mesmo critério em todos os anos (YoY justo): NÃO marcar anos anteriores
 *  inteiros como fechados — senão o card compara 12 meses de 2025 vs T1–T2 de 2026. */
export function bucketEhFechado(
  bucketKey: string,
  gran: GranularidadeDash,
  ref: Date = new Date(),
): boolean {
  const year = yearFromBucketKey(bucketKey, gran);
  const last = lastMonthOfBucket(bucketKey, gran);
  const anoAtual = ref.getFullYear();
  const limite = ultimoMesFechado(ref);

  if (limite <= 0) return year < anoAtual;
  // Anual: o “ano” só fecha em dez; mid-year o corte justo é mês a mês (ver indicesPeriodosFechados).
  if (gran === 'Anual') return false;
  return last <= limite;
}

/** Bucket “até agora” = já começou (último mês do bucket ≥ 1 e início ≤ mês corrente). */
export function bucketEhAteAgora(
  bucketKey: string,
  gran: GranularidadeDash,
  ref: Date = new Date(),
): boolean {
  const months = monthsInBucketKey(bucketKey, gran);
  if (months.length === 0) return false;
  const start = Math.min(...months);
  return start <= mesAtualNum(ref);
}

/** Índices mensais dos buckets fechados. */
export function indicesPeriodosFechados(
  data: DashboardData,
  gran: GranularidadeDash,
  ref: Date = new Date(),
): number[] {
  // Mensal e Anual: corte por mês do calendário em todos os anos (YoY justo).
  if (gran === 'Mensal' || gran === 'Anual') {
    const limite = ultimoMesFechado(ref);
    const anoAtual = ref.getFullYear();
    return data.monthly
      .map((m, idx) => {
        const mes = mesDeRotulo(m.name);
        if (mes <= 0) return -1;
        if (limite <= 0) return m.year < anoAtual ? idx : -1;
        return mes <= limite ? idx : -1;
      })
      .filter((i) => i !== -1);
  }

  const out: number[] = [];
  for (const b of listBuckets(data, gran)) {
    if (bucketEhFechado(b.key, gran, ref)) out.push(...b.monthIndices);
  }
  return out;
}

/** Índices até o período corrente (inclui bucket aberto). */
export function indicesAtePeriodoAtual(
  data: DashboardData,
  gran: GranularidadeDash,
  ref: Date = new Date(),
): number[] {
  if (gran === 'Mensal') {
    const ate = mesAtualNum(ref);
    return data.monthly
      .map((m, idx) => (mesDeRotulo(m.name) <= ate ? idx : -1))
      .filter((i) => i !== -1);
  }

  const out: number[] = [];
  for (const b of listBuckets(data, gran)) {
    if (!bucketEhAteAgora(b.key, gran, ref)) continue;
    // Só meses ≤ mês corrente (mesmo corte YoY dentro do bucket aberto)
    const ate = mesAtualNum(ref);
    for (const idx of b.monthIndices) {
      const mes = mesDeRotulo(data.monthly[idx].name);
      if (mes > 0 && mes <= ate) out.push(idx);
    }
  }
  return out;
}

/** Isola o bucket corrente (ex.: trimestre atual) em todos os anos. */
export function indicesPeriodoAtual(
  data: DashboardData,
  gran: GranularidadeDash,
  ref: Date = new Date(),
): number[] {
  const mes = mesAtualNum(ref);
  const ano = ref.getFullYear();
  const currentKey = bucketKeyFromMonth(ano, mes, gran);
  const short = labelBucketShort(currentKey, gran);

  if (gran === 'Anual') {
    return data.monthly.map((m, i) => (m.year === ano ? i : -1)).filter((i) => i !== -1);
  }

  return data.monthly
    .map((m, i) => {
      const key = bucketKeyFromEntry(m, gran);
      return labelBucketShort(key, gran) === short ? i : -1;
    })
    .filter((i) => i !== -1);
}

/**
 * Ao trocar a granularidade: sobe a seleção atual para buckets completos
 * da nova grain (qualquer mês selecionado puxa o bucket inteiro).
 */
export function remapPeriodoParaGranularidade(
  data: DashboardData,
  period: number[],
  gran: GranularidadeDash,
): number[] {
  if (period.length === 0) return [];
  const keys = new Set<string>();
  for (const idx of period) {
    const key = bucketKeyFromIndex(data, idx, gran);
    if (key) keys.add(key);
  }
  const out: number[] = [];
  for (const b of listBuckets(data, gran)) {
    if (keys.has(b.key)) out.push(...b.monthIndices);
  }
  return out;
}

/** Quantidade de períodos da grain cobertos por `indices` (meses → 1:1;
 *  trimestral/semestral/anual → nº de buckets distintos). Usado em médias e rótulos. */
export function countBucketsInIndices(
  data: DashboardData,
  indices: number[],
  gran: GranularidadeDash,
): number {
  if (indices.length === 0) return 0;
  if (gran === 'Mensal') return indices.length;
  const keys = new Set<string>();
  for (const idx of indices) {
    const key = bucketKeyFromIndex(data, idx, gran);
    if (key) keys.add(key);
  }
  return keys.size;
}

/** Agrupa índices mensais pela chave curta YoY (jan/T1/S1) ou por ano (Anual). */
export function groupIndicesByChartAxis(
  data: DashboardData,
  indices: number[],
  gran: GranularidadeDash,
): Map<string, number[]> {
  const map = new Map<string, number[]>();
  for (const idx of indices) {
    const entry = data.monthly[idx];
    if (!entry) continue;
    const key = bucketKeyFromEntry(entry, gran);
    const axis =
      gran === 'Anual'
        ? String(entry.year)
        : labelBucketShort(key, gran);
    const list = map.get(axis) ?? [];
    list.push(idx);
    map.set(axis, list);
  }
  return map;
}

/** Média das taxas YoY por ponto da grain (ex.: média de (T1_26−T1_25)/T1_25 e
 *  (T2_26−T2_25)/T2_25). Diferente do YoY do total — e muda ao trocar a grain. */
export function mediaTaxaYoYPorBucket(
  data: DashboardData,
  pA: number[],
  pB: number[],
  revPorIndiceA: (idx: number) => number,
  revPorIndiceB: (idx: number) => number,
  gran: GranularidadeDash,
): number {
  if (gran === 'Anual') {
    const sum = (idxs: number[], revOf: (i: number) => number) =>
      idxs.reduce((acc, i) => acc + revOf(i), 0);
    const a = sum(pA, revPorIndiceA);
    const b = sum(pB, revPorIndiceB);
    return a > 0 ? ((b - a) / a) * 100 : 0;
  }

  const gA = groupIndicesByChartAxis(data, pA, gran);
  const gB = groupIndicesByChartAxis(data, pB, gran);
  const labels = orderShortLabels(gran).filter((l) => gA.has(l) || gB.has(l));
  const rates: number[] = [];
  for (const label of labels) {
    const sum = (idxs: number[], revOf: (i: number) => number) =>
      idxs.reduce((acc, i) => acc + revOf(i), 0);
    const a = sum(gA.get(label) ?? [], revPorIndiceA);
    const b = sum(gB.get(label) ?? [], revPorIndiceB);
    if (a > 0) rates.push((b - a) / a);
  }
  if (rates.length === 0) return 0;
  return (rates.reduce((acc, r) => acc + r, 0) / rates.length) * 100;
}

export function rotuloUnidade(gran: GranularidadeDash): {
  singular: string;
  plural: string;
  fechados: string;
  ateAgora: string;
  atual: string;
  todos: string;
} {
  switch (gran) {
    case 'Trimestral':
      return {
        singular: 'trimestre',
        plural: 'trimestres',
        fechados: 'Trimestres fechados',
        ateAgora: 'Trimestres até agora',
        atual: 'Trimestre atual',
        todos: 'Todos os trimestres',
      };
    case 'Semestral':
      return {
        singular: 'semestre',
        plural: 'semestres',
        fechados: 'Semestres fechados',
        ateAgora: 'Semestres até agora',
        atual: 'Semestre atual',
        todos: 'Todos os semestres',
      };
    case 'Anual':
      return {
        singular: 'ano',
        plural: 'anos',
        fechados: 'Anos fechados',
        ateAgora: 'Anos até agora',
        atual: 'Ano atual',
        todos: 'Todos os anos',
      };
    default:
      return {
        singular: 'mês',
        plural: 'meses',
        fechados: 'Meses fechados',
        ateAgora: 'Meses até agora',
        atual: 'Mês atual',
        todos: 'Todos os meses',
      };
  }
}
