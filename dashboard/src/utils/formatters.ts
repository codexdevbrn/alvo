export function formatCurrency(val: number) {
    if (!Number.isFinite(val)) return 'R$ 0,00';
    return new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL' }).format(val);
}

export function formatNumber(val: number) {
    if (!Number.isFinite(val)) return '0';
    return val.toLocaleString('pt-BR');
}

/** Percentual pt-BR (vírgula decimal), ex.: 12,34% — sem sinal de "+". */
export function formatPercent(val: number, decimals = 2) {
    if (!Number.isFinite(val)) return `${(0).toFixed(decimals).replace('.', ',')}%`;
    return `${val.toLocaleString('pt-BR', {
        minimumFractionDigits: decimals,
        maximumFractionDigits: decimals,
    })}%`;
}

/**
 * Rótulo curto da faixa ABC na UI: "Grupo 1" → "1", "Demais" → "X", "Balcão" → "B".
 * O valor canônico do backend permanece "Grupo N" / "Demais" / "Balcão".
 */
export function rotuloGrupoCurto(grupo: string | null | undefined): string {
    if (grupo == null) return '—';
    const nome = String(grupo).trim();
    if (!nome) return '—';
    if (/^demais$/i.test(nome)) return 'X';
    if (/^balc[aã]o$/i.test(nome)) return 'B';
    const m = nome.match(/^grupo\s+(\d+)\b/i);
    if (m) return m[1];
    return nome;
}
