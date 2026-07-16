import type { AggregateResult, ChartPoint, DashboardData, GranularidadeDash, Row } from '../types/dashboard';
import {
  bucketKeyFromIndex,
  groupIndicesByChartAxis,
  labelBucketWithYear,
  orderShortLabels,
  rotuloUnidade,
  sortBucketKeys,
} from './granularidade';

export function buildComparisonChartData(
  data: DashboardData,
  populationRows: Row[],
  pA: number[],
  pB: number[],
  statsA: AggregateResult,
  statsB: AggregateResult,
  granularidade: GranularidadeDash = 'Mensal',
): ChartPoint[] {
  const emptyBucket = () => ({
    revenueA: null as number | null,
    revenueB: null as number | null,
    mfrsA: null as number | null,
    mfrsB: null as number | null,
    descsA: null as number | null,
    descsB: null as number | null,
    cntA: null as number | null,
    cntB: null as number | null,
    clientsA: null as number | null,
    clientsB: null as number | null,
  });

  const bucketMap: Record<string, ReturnType<typeof emptyBucket>> = {};

  const accumulate = (
    indices: number[],
    side: 'A' | 'B',
    stats: AggregateResult,
  ) => {
    const grouped = groupIndicesByChartAxis(data, indices, granularidade);
    grouped.forEach((idxs, axisLabel) => {
      if (!bucketMap[axisLabel]) bucketMap[axisLabel] = emptyBucket();
      let rev = 0;
      let cnt = 0;
      const mfrSet = new Set<number>();
      const descSet = new Set<number>();
      const clientSet = new Set<number>();
      for (const idx of idxs) {
        const node = stats.monthlyNodes[idx];
        if (!node) continue;
        rev += node.rev;
        node.mfrs.forEach((id) => mfrSet.add(id));
        node.descs.forEach((id) => descSet.add(id));
        node.clients.forEach((id) => clientSet.add(id));
        populationRows.forEach((r) => {
          if (r[0] === idx) cnt++;
        });
      }
      const slot = bucketMap[axisLabel];
      if (side === 'A') {
        slot.revenueA = (slot.revenueA ?? 0) + rev;
        slot.mfrsA = (slot.mfrsA ?? 0) + mfrSet.size;
        slot.descsA = (slot.descsA ?? 0) + descSet.size;
        slot.cntA = (slot.cntA ?? 0) + cnt;
        slot.clientsA = (slot.clientsA ?? 0) + clientSet.size;
      } else {
        slot.revenueB = (slot.revenueB ?? 0) + rev;
        slot.mfrsB = (slot.mfrsB ?? 0) + mfrSet.size;
        slot.descsB = (slot.descsB ?? 0) + descSet.size;
        slot.cntB = (slot.cntB ?? 0) + cnt;
        slot.clientsB = (slot.clientsB ?? 0) + clientSet.size;
      }
    });
  };

  accumulate(pA, 'A', statsA);
  accumulate(pB, 'B', statsB);

  if (granularidade === 'Anual') {
    return Object.keys(bucketMap)
      .sort((a, b) => Number(a) - Number(b))
      .map((name) => ({ name, ...bucketMap[name] }));
  }

  const order = orderShortLabels(granularidade);
  return order.filter((m) => bucketMap[m]).map((m) => ({ name: m, ...bucketMap[m] }));
}

export function buildTrendChartData(
  data: DashboardData,
  periodChart: number[],
  pAChartSet: Set<number>,
  statsTotalChart: AggregateResult,
  granularidade: GranularidadeDash,
): ChartPoint[] {
  if (granularidade === 'Mensal') {
    return [...periodChart].sort((a, b) => a - b).map((idx) => {
      const cNodes = statsTotalChart.monthlyNodes[idx];
      const isA = pAChartSet.has(idx);
      const m = data.monthly[idx];
      return {
        name: m?.name || '?',
        revenueA: isA ? (cNodes?.rev || 0) : null,
        revenueB: cNodes?.rev || 0,
        cntA: isA ? (cNodes?.cnt || 0) : null,
        cntB: cNodes?.cnt || 0,
        clientsA: isA ? (cNodes?.clients.size || 0) : null,
        clientsB: cNodes?.clients.size || 0,
      };
    });
  }

  const keyToIndices = new Map<string, number[]>();
  for (const idx of periodChart) {
    const key = bucketKeyFromIndex(data, idx, granularidade);
    if (!key) continue;
    const list = keyToIndices.get(key) ?? [];
    list.push(idx);
    keyToIndices.set(key, list);
  }

  return sortBucketKeys([...keyToIndices.keys()], granularidade).map((key) => {
    const idxs = keyToIndices.get(key) ?? [];
    let rev = 0;
    let cnt = 0;
    let revA = 0;
    let cntA = 0;
    const clientSet = new Set<number>();
    const clientSetA = new Set<number>();
    for (const idx of idxs) {
      const node = statsTotalChart.monthlyNodes[idx];
      if (!node) continue;
      rev += node.rev;
      cnt += node.cnt;
      node.clients.forEach((c) => clientSet.add(c));
      if (pAChartSet.has(idx)) {
        revA += node.rev;
        cntA += node.cnt;
        node.clients.forEach((c) => clientSetA.add(c));
      }
    }
    return {
      name: labelBucketWithYear(key, granularidade),
      revenueA: revA || null,
      revenueB: rev,
      cntA: cntA || null,
      cntB: cnt,
      clientsA: clientSetA.size || null,
      clientsB: clientSet.size,
    };
  });
}

export function rotulosTendencia(
  granularidade: GranularidadeDash,
  pALen: number,
  pBLen: number,
): { labelA: string; labelB: string } {
  const u = rotuloUnidade(granularidade);
  const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);
  return {
    labelA: pALen > 0
      ? (pALen === 1 ? `${cap(u.singular)} Ant.` : `Média ${pALen} ${u.plural} Ant.`)
      : '',
    labelB: pBLen === 1
      ? `${cap(u.singular)} Atual`
      : `Média últ. ${pBLen} ${u.plural}`,
  };
}
