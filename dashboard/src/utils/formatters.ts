export function formatCurrency(val: number) {
    if (!Number.isFinite(val)) return 'R$ 0,00';
    return new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL' }).format(val);
}

export function formatNumber(val: number) {
    if (!Number.isFinite(val)) return '0';
    return val.toLocaleString('pt-BR');
}

/**
 * Número curto para eixo de gráfico: 2.400.000 → "2,4 M", 850.000 → "850 k".
 *
 * Eixo com o número inteiro ("R$ 2.400.000,00") não cabe na largura reservada e
 * o recharts corta o texto pela esquerda — o tick passa a mostrar um valor
 * MENOR e plausível ("400.000,00"), que é pior que não mostrar nada.
 */
export function formatCompacto(val: number, comMoeda = false): string {
    if (!Number.isFinite(val)) return comMoeda ? 'R$ 0' : '0';
    const prefixo = comMoeda ? 'R$ ' : '';
    const sinal = val < 0 ? '-' : '';
    const abs = Math.abs(val);
    const curto = (valor: number, sufixo: string) => {
        const texto = valor.toLocaleString('pt-BR', {
            maximumFractionDigits: valor < 10 ? 1 : 0,
        });
        return `${sinal}${prefixo}${texto}${sufixo}`;
    };
    if (abs >= 1e9) return curto(abs / 1e9, ' B');
    if (abs >= 1e6) return curto(abs / 1e6, ' M');
    if (abs >= 1e3) return curto(abs / 1e3, ' k');
    return `${sinal}${prefixo}${abs.toLocaleString('pt-BR', { maximumFractionDigits: 2 })}`;
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
