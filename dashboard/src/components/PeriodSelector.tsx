import { useState, useRef, useEffect, type MouseEvent } from 'react';
import { X, TrendingUp, Check } from 'lucide-react';
import type { DashboardData } from '../types/dashboard';
import {
    indicesAteMesAtual,
    indicesMesesFechados,
    mesDeRotulo,
    periodosIguais,
    rotuloCorteMesesFechados,
} from '../utils/periodoFechado';

interface PeriodSelectorProps {
    label: string;
    value: number[];
    data: DashboardData;
    onChange: (value: number[]) => void;
    usarMesesFechados?: boolean;
    onUsarMesesFechados?: (value: boolean) => void;
}

export function PeriodSelector({ label, value, data, onChange, usarMesesFechados = false, onUsarMesesFechados }: PeriodSelectorProps) {
    const [isOpen, setIsOpen] = useState(false);
    const [expandedYears, setExpandedYears] = useState<Set<number>>(() => new Set());
    const closeTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
    const lastMonthClickRef = useRef<{ idx: number; time: number }>({ idx: -1, time: 0 });

    const years = Array.from(new Set(data.monthly.map((m) => m.year))).sort((a, b) => a - b);
    const allIndices = data.monthly.map((_, i) => i);
    const selecionados = value.length === 0 ? allIndices : value;

    useEffect(() => {
        const timeoutId = closeTimeoutRef.current;
        return () => {
            if (timeoutId) clearTimeout(timeoutId);
        };
    }, []);

    const handleToggle = () => {
        if (closeTimeoutRef.current) clearTimeout(closeTimeoutRef.current);
        const abrir = !isOpen;
        setIsOpen(abrir);
        if (abrir) setExpandedYears(new Set(years));
    };

    const toggleYearExpanded = (y: number) => {
        if (closeTimeoutRef.current) clearTimeout(closeTimeoutRef.current);
        setExpandedYears((prev) => {
            const next = new Set(prev);
            if (next.has(y)) next.delete(y);
            else next.add(y);
            return next;
        });
    };

    const isolarMes = (mesNum: number) => {
        const indices = data.monthly
            .map((m, i) => (mesDeRotulo(m.name) === mesNum ? i : -1))
            .filter((i) => i !== -1);
        onChange(indices);
    };

    const aplicarSelecao = (indices: number[]) => {
        if (periodosIguais(indices, allIndices)) {
            onChange([]);
            return;
        }
        onChange(indices);
    };

    const toggleMonth = (idx: number) => {
        const base = selecionados;
        const newValue = base.includes(idx) ? base.filter((v) => v !== idx) : [...base, idx];
        aplicarSelecao(newValue);
    };

    const handleMonthClick = (idx: number) => {
        // eslint-disable-next-line react-hooks/purity
        const agora = Date.now();
        const ehDuploClique =
            lastMonthClickRef.current.idx === idx && agora - lastMonthClickRef.current.time < 400;
        lastMonthClickRef.current = { idx, time: agora };

        if (ehDuploClique) {
            lastMonthClickRef.current = { idx: -1, time: 0 };
            isolarMes(mesDeRotulo(data.monthly[idx].name));
            return;
        }
        toggleMonth(idx);
    };

    const handleOutsideClick = () => {
        if (closeTimeoutRef.current) clearTimeout(closeTimeoutRef.current);
        setIsOpen(false);
    };

    const toggleYear = (y: number, currentlySelected: boolean) => {
        if (closeTimeoutRef.current) clearTimeout(closeTimeoutRef.current);
        const yearIndices = data.monthly
            .map((m, idx) => (m.year === y ? idx : -1))
            .filter((i) => i !== -1);

        let newValue: number[];
        if (currentlySelected) {
            newValue = selecionados.filter((idx) => !yearIndices.includes(idx));
        } else {
            newValue = Array.from(new Set([...selecionados, ...yearIndices]));
        }

        aplicarSelecao(newValue);
    };

    const selectMesesFechados = (e?: MouseEvent) => {
        e?.stopPropagation();
        if (closeTimeoutRef.current) clearTimeout(closeTimeoutRef.current);
        onUsarMesesFechados?.(true);
        // Seleção explícita (não []) — trava o gráfico nos mesmos meses
        // fechados usados no cálculo, em vez de deixar o mês corrente aberto
        // aparecer no traçado.
        onChange(indicesMesesFechados(data));
    };

    const selectAteAgora = (e?: MouseEvent) => {
        e?.stopPropagation();
        if (closeTimeoutRef.current) clearTimeout(closeTimeoutRef.current);
        onUsarMesesFechados?.(false);
        // Mesmo corte (jan..mês corrente) nos dois anos, mas incluindo o mês
        // corrente — diferente de "Meses fechados", que o exclui.
        onChange(indicesAteMesAtual(data));
    };

    const selectTodosOsMeses = (e?: MouseEvent) => {
        e?.stopPropagation();
        if (closeTimeoutRef.current) clearTimeout(closeTimeoutRef.current);
        onUsarMesesFechados?.(false);
        // Seleção explícita de tudo (não []) — [] agora cai no fallback "até o
        // último mês disponível" (periodoBase), então precisa ser literal para
        // realmente pegar anos anteriores completos além do mês corrente.
        onChange(allIndices);
    };

    const verMesAtual = (e?: MouseEvent) => {
        e?.stopPropagation();
        if (closeTimeoutRef.current) clearTimeout(closeTimeoutRef.current);
        const mesAtual = new Date().getMonth() + 1;
        isolarMes(mesAtual);
    };

    const getSelectedText = () => {
        if (value.length === 0) {
            return usarMesesFechados ? 'Todos os períodos (só meses fechados)' : 'Todos os períodos';
        }
        if (periodosIguais(value, allIndices)) return 'Todos os meses (incl. mês corrente)';

        const contagens = years
            .map((y) => {
                const n = value.filter((i) => data.monthly[i]?.year === y).length;
                return n > 0 ? `${n}m ('${String(y).slice(2)})` : null;
            })
            .filter(Boolean);
        if (contagens.length > 1) return contagens.join(' vs ');
        return `${value.length} meses selecionados`;
    };

    const mesEstaSelecionado = (idx: number) => selecionados.includes(idx);

    return (
        <div className="filter-group" style={{ position: 'relative' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <label style={{ marginBottom: 0 }}>
                    <TrendingUp size={12} style={{ marginRight: 4 }} /> {label}
                </label>
                {!periodosIguais(value, allIndices) && value.length > 0 && (
                    <button
                        type="button"
                        onClick={(e) => {
                            e.stopPropagation();
                            onChange([]);
                        }}
                        className="mini-clear-btn"
                        title="Limpar seleção (todos os períodos)"
                    >
                        <X size={10} />
                    </button>
                )}
            </div>
            <div
                className="custom-select"
                onClick={handleToggle}
                style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', cursor: 'pointer' }}
            >
                <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {getSelectedText()}
                </span>
            </div>

            {isOpen && (
                <>
                    <div style={{ position: 'fixed', inset: 0, zIndex: 999 }} onClick={handleOutsideClick} />
                    <div
                        className="custom-scrollbar"
                        style={{
                            position: 'absolute',
                            top: '100%',
                            left: 0,
                            right: 0,
                            zIndex: 1000,
                            background: '#1a1a1e',
                            border: '1px solid var(--border)',
                            borderRadius: '12px',
                            marginTop: '8px',
                            padding: '8px',
                            boxShadow: '0 10px 25px rgba(0,0,0,0.5)',
                            maxHeight: '400px',
                            overflowY: 'auto',
                        }}
                    >
                        <div style={{ display: 'flex', flexDirection: 'column', gap: '6px', marginBottom: '8px' }}>
                            <div style={{ display: 'flex', gap: '6px' }}>
                                <button
                                    type="button"
                                    onClick={selectMesesFechados}
                                    title="Só meses fechados, mesmo corte nos dois anos"
                                    style={{
                                        flex: 1,
                                        padding: '8px 10px',
                                        borderRadius: '8px',
                                        border: periodosIguais(value, indicesMesesFechados(data))
                                            ? '1px solid rgba(99, 102, 241, 0.65)'
                                            : '1px solid rgba(99, 102, 241, 0.35)',
                                        background: periodosIguais(value, indicesMesesFechados(data))
                                            ? 'rgba(99, 102, 241, 0.22)'
                                            : 'rgba(99, 102, 241, 0.12)',
                                        color: 'var(--text-primary)',
                                        fontSize: '0.72rem',
                                        fontWeight: 600,
                                        cursor: 'pointer',
                                        fontFamily: 'inherit',
                                    }}
                                >
                                    Meses fechados
                                </button>
                                <button
                                    type="button"
                                    onClick={selectAteAgora}
                                    title="Jan até o mês corrente (incluso), mesmo corte nos dois anos"
                                    style={{
                                        flex: 1,
                                        padding: '8px 10px',
                                        borderRadius: '8px',
                                        border: periodosIguais(value, indicesAteMesAtual(data))
                                            ? '1px solid rgba(245, 158, 11, 0.65)'
                                            : '1px solid rgba(245, 158, 11, 0.35)',
                                        background: periodosIguais(value, indicesAteMesAtual(data))
                                            ? 'rgba(245, 158, 11, 0.22)'
                                            : 'rgba(245, 158, 11, 0.12)',
                                        color: 'var(--text-primary)',
                                        fontSize: '0.72rem',
                                        fontWeight: 600,
                                        cursor: 'pointer',
                                        fontFamily: 'inherit',
                                    }}
                                >
                                    Meses até agora
                                </button>
                            </div>
                            <div style={{ display: 'flex', gap: '6px' }}>
                                <button
                                    type="button"
                                    onClick={verMesAtual}
                                    title="Filtra apenas o mês corrente em todos os anos"
                                    style={{
                                        flex: 1,
                                        padding: '8px 10px',
                                        borderRadius: '8px',
                                        border: '1px solid rgba(16, 185, 129, 0.35)',
                                        background: 'rgba(16, 185, 129, 0.12)',
                                        color: 'var(--text-primary)',
                                        fontSize: '0.72rem',
                                        fontWeight: 600,
                                        cursor: 'pointer',
                                        fontFamily: 'inherit',
                                    }}
                                >
                                    Mês atual
                                </button>
                                <button
                                    type="button"
                                    onClick={selectTodosOsMeses}
                                    title="Todos os meses de todos os anos, incl. corrente"
                                    style={{
                                        flex: 1,
                                        padding: '8px 10px',
                                        borderRadius: '8px',
                                        border: periodosIguais(value, allIndices)
                                            ? '1px solid rgba(148, 163, 184, 0.65)'
                                            : '1px solid rgba(148, 163, 184, 0.35)',
                                        background: periodosIguais(value, allIndices)
                                            ? 'rgba(148, 163, 184, 0.22)'
                                            : 'rgba(148, 163, 184, 0.12)',
                                        color: 'var(--text-primary)',
                                        fontSize: '0.72rem',
                                        fontWeight: 600,
                                        cursor: 'pointer',
                                        fontFamily: 'inherit',
                                    }}
                                >
                                    Todos os meses
                                </button>
                            </div>
                        </div>
                        <p
                            style={{
                                margin: '0 2px 8px',
                                fontSize: '0.62rem',
                                color: 'var(--text-secondary)',
                                lineHeight: 1.35,
                            }}
                        >
                            {usarMesesFechados
                                ? `Com a opção ativa, entram só meses fechados (${rotuloCorteMesesFechados()}). Dica: duplo clique num mês para ver só ele nos anos disponíveis.`
                                : 'Todos os meses entram nos cálculos, inclusive o mês corrente. Dica: duplo clique num mês para ver só ele nos anos disponíveis.'}
                        </p>

                        {years.map((y) => {
                            const yearIndices = data.monthly
                                .map((m, idx) => (m.year === y ? idx : -1))
                                .filter((i) => i !== -1);
                            const yearAllSelected =
                                yearIndices.length > 0 && yearIndices.every((idx) => mesEstaSelecionado(idx));
                            const yearSomeSelected =
                                yearIndices.some((idx) => mesEstaSelecionado(idx)) && !yearAllSelected;
                            const isExpanded = expandedYears.has(y);

                            return (
                                <div
                                    key={y}
                                    style={{
                                        marginBottom: '8px',
                                        borderBottom: '1px solid rgba(255,255,255,0.05)',
                                        paddingBottom: '4px',
                                    }}
                                >
                                    <div
                                        style={{
                                            padding: '8px 12px',
                                            borderRadius: '10px',
                                            display: 'flex',
                                            justifyContent: 'space-between',
                                            alignItems: 'center',
                                            background: isExpanded ? 'rgba(255,255,255,0.03)' : 'transparent',
                                            transition: 'background 0.2s',
                                        }}
                                    >
                                        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                                            <div
                                                onClick={() => toggleYear(y, yearAllSelected)}
                                                style={{
                                                    width: '18px',
                                                    height: '18px',
                                                    borderRadius: '5px',
                                                    border: `1.5px solid ${yearAllSelected || yearSomeSelected ? 'var(--accent)' : 'rgba(255,255,255,0.2)'}`,
                                                    backgroundColor: yearAllSelected
                                                        ? 'var(--accent)'
                                                        : yearSomeSelected
                                                          ? 'rgba(99, 102, 241, 0.2)'
                                                          : 'transparent',
                                                    display: 'flex',
                                                    alignItems: 'center',
                                                    justifyContent: 'center',
                                                    cursor: 'pointer',
                                                    transition: 'all 0.2s cubic-bezier(0.4, 0, 0.2, 1)',
                                                    boxShadow: yearAllSelected
                                                        ? '0 0 10px rgba(99, 102, 241, 0.3)'
                                                        : 'none',
                                                }}
                                            >
                                                {yearAllSelected && <Check size={12} color="white" strokeWidth={3} />}
                                                {yearSomeSelected && (
                                                    <div
                                                        style={{
                                                            width: '8px',
                                                            height: '2px',
                                                            backgroundColor: 'var(--accent)',
                                                            borderRadius: '1px',
                                                        }}
                                                    />
                                                )}
                                            </div>
                                            <span
                                                onClick={() => toggleYearExpanded(y)}
                                                style={{
                                                    color:
                                                        yearAllSelected || yearSomeSelected
                                                            ? 'white'
                                                            : 'var(--text-secondary)',
                                                    fontWeight: 600,
                                                    cursor: 'pointer',
                                                    fontSize: '0.85rem',
                                                    transition: 'color 0.2s',
                                                }}
                                            >
                                                {y}
                                            </span>
                                        </div>
                                        <span
                                            onClick={() => toggleYearExpanded(y)}
                                            style={{
                                                fontSize: '0.6rem',
                                                color: 'var(--text-secondary)',
                                                cursor: 'pointer',
                                                padding: '6px',
                                                transform: isExpanded ? 'rotate(0deg)' : 'rotate(-90deg)',
                                                transition: 'transform 0.3s',
                                            }}
                                        >
                                            ▼
                                        </span>
                                    </div>
                                    {isExpanded && (
                                        <div
                                            style={{
                                                display: 'grid',
                                                gridTemplateColumns: 'repeat(3, 1fr)',
                                                gap: '6px',
                                                padding: '10px 12px',
                                            }}
                                        >
                                            {data.monthly.map(
                                                (m, idx) =>
                                                    m.year === y && (
                                                        <button
                                                            key={idx}
                                                            type="button"
                                                            onClick={() => handleMonthClick(idx)}
                                                            style={{
                                                                padding: '8px 4px',
                                                                fontSize: '0.7rem',
                                                                borderRadius: '8px',
                                                                border: '1px solid',
                                                                borderColor: mesEstaSelecionado(idx)
                                                                    ? 'transparent'
                                                                    : 'var(--border)',
                                                                cursor: 'pointer',
                                                                background: mesEstaSelecionado(idx)
                                                                    ? y === years[years.length - 1]
                                                                        ? 'var(--accent)'
                                                                        : '#10b981'
                                                                    : 'rgba(255,255,255,0.02)',
                                                                color: mesEstaSelecionado(idx)
                                                                    ? 'white'
                                                                    : 'var(--text-secondary)',
                                                                transition: 'all 0.2s',
                                                                fontWeight: mesEstaSelecionado(idx) ? 600 : 500,
                                                            }}
                                                        >
                                                            {m.name.split('/')[0]}
                                                        </button>
                                                    ),
                                            )}
                                        </div>
                                    )}
                                </div>
                            );
                        })}
                    </div>
                </>
            )}
        </div>
    );
}
