export function formatCurrency(val: number) {
    if (!Number.isFinite(val)) return 'R$ 0,00';
    return new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL' }).format(val);
}

export function formatNumber(val: number) {
    if (!Number.isFinite(val)) return '0';
    return val.toLocaleString('pt-BR');
}
