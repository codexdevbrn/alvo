import type { DashboardData } from '../types/dashboard';

const MES_NUM: Record<string, number> = {
    jan: 1, fev: 2, mar: 3, abr: 4, mai: 5, jun: 6,
    jul: 7, ago: 8, set: 9, out: 10, nov: 11, dez: 12,
};

const MES_ABREV = ['', 'jan', 'fev', 'mar', 'abr', 'mai', 'jun', 'jul', 'ago', 'set', 'out', 'nov', 'dez'];

/** Número do mês (1–12) a partir do rótulo do summary (`jan/25`). */
export function mesDeRotulo(name: string): number {
    return MES_NUM[name.split('/')[0].toLowerCase()] ?? 0;
}

/** Último mês fechado no ano corrente (1–12). 0 = nenhum (ex.: estamos em janeiro). */
export function ultimoMesFechado(ref: Date = new Date()): number {
    return ref.getMonth();
}

/** Abreviatura (jan–dez) do mês corrente. */
export function abrevMesAtual(ref: Date = new Date()): string {
    return MES_ABREV[ref.getMonth() + 1];
}

/** Abreviatura do mês a partir do rótulo do summary (`jan/25` → `jan`). */
export function mesAbrevDeRotulo(name: string): string {
    return name.split('/')[0].toLowerCase();
}

/** Abreviatura (jan–dez) do último mês fechado no ano corrente, ou null em janeiro. */
export function abrevUltimoMesFechado(ref: Date = new Date()): string | null {
    const limite = ultimoMesFechado(ref);
    if (limite <= 0) return null;
    return MES_ABREV[limite];
}

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

/** Mês corrente (1–12). */
export function mesAtualNum(ref: Date = new Date()): number {
    return ref.getMonth() + 1;
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

/** Índices de `data.monthly` cujo mês (1–12) é ≤ ao último mês disponível no ano
 *  mais recente do dataset. Sem isso, anos anteriores completos (ex.: 2025 até
 *  dez) esticam o eixo do gráfico além do ano corrente (ex.: 2026 até jul),
 *  deixando meses futuros vazios — o ano corrente incompleto deve limitar até
 *  onde qualquer ano é exibido, não o contrário. */
function periodoAteUltimoMesDisponivel(data: DashboardData): number[] {
    if (data.monthly.length === 0) return [];
    const anoMaisRecente = Math.max(...data.monthly.map((m) => m.year));
    const mesesDoAnoRecente = data.monthly
        .filter((m) => m.year === anoMaisRecente)
        .map((m) => mesDeRotulo(m.name));
    const ultimoMes = mesesDoAnoRecente.length > 0 ? Math.max(...mesesDoAnoRecente) : 12;
    return data.monthly
        .map((m, idx) => (mesDeRotulo(m.name) <= ultimoMes ? idx : -1))
        .filter((idx) => idx !== -1);
}

/** Base antes do filtro de meses fechados: seleção manual ou até o último mês disponível. */
export function periodoBase(data: DashboardData, period: number[]): number[] {
    return period.length > 0 ? period : periodoAteUltimoMesDisponivel(data);
}

/** Período efetivo para cálculos: base × opcionalmente só meses fechados. */
export function resolverPeriodoEfetivo(
    data: DashboardData,
    period: number[],
    usarMesesFechados = true,
    ref: Date = new Date(),
): number[] {
    const base = periodoBase(data, period);
    if (!usarMesesFechados) return base;
    const fechados = new Set(indicesMesesFechados(data, ref));
    return base.filter((i) => fechados.has(i));
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
export function descricaoPeriodoPadrao(data: DashboardData, ref: Date = new Date()): string {
    const limite = ultimoMesFechado(ref);
    const qtd = indicesMesesFechados(data, ref).length;
    if (limite <= 0) {
        return `Meses fechados (anos anteriores completos)`;
    }
    return `Meses fechados (jan–${MES_ABREV[limite]} em cada ano · ${qtd} meses)`;
}

/** Banner explicativo fixo no painel de filtros. */
export function textoBannerMesesFechados(ref: Date = new Date()): string {
    const limite = ultimoMesFechado(ref);
    const mesCorrente = MES_ABREV[limite + 1] ?? '?';
    const ano = String(ref.getFullYear()).slice(2);
    if (limite <= 0) {
        return `Os cálculos usam apenas meses fechados. Em janeiro/${ano} ainda não há mês fechado no ano corrente — entram os anos anteriores completos.`;
    }
    return `Os cálculos usam meses fechados (jan–${MES_ABREV[limite]} em cada ano). O mês corrente (${mesCorrente}/${ano}) fica de fora por estar em aberto.`;
}

export function periodosIguais(a: number[], b: number[]): boolean {
    if (a.length !== b.length) return false;
    const sa = [...a].sort((x, y) => x - y);
    const sb = [...b].sort((x, y) => x - y);
    return sa.every((v, i) => v === sb[i]);
}
