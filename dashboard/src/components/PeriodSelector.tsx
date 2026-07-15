import { useState, useRef, useEffect } from 'react';
import { X, TrendingUp, Check } from 'lucide-react';
import type { DashboardData } from '../types/dashboard';

interface PeriodSelectorProps {
    label: string;
    value: number[];
    data: DashboardData;
    onChange: (value: number[]) => void;
}

const MES_NUM: Record<string, number> = {
    jan: 1, fev: 2, mar: 3, abr: 4, mai: 5, jun: 6,
    jul: 7, ago: 8, set: 9, out: 10, nov: 11, dez: 12,
};

function mesDeRotulo(name: string): number {
    return MES_NUM[name.split('/')[0].toLowerCase()] ?? 0;
}

export function PeriodSelector({ label, value, data, onChange }: PeriodSelectorProps) {
    const [isOpen, setIsOpen] = useState(false);
    const [expandedYears, setExpandedYears] = useState<Set<number>>(() => new Set());
    const closeTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
    // Guarda o último mês clicado e quando, para detectar duplo clique sem
    // atrasar o clique simples (ver handleMonthClick).
    const lastMonthClickRef = useRef<{ idx: number; time: number }>({ idx: -1, time: 0 });

    const years = Array.from(new Set(data.monthly.map((m) => m.year))).sort((a, b) => a - b);
    const allIndices = data.monthly.map((_, i) => i);
    const isAllSelected = value.length === 0;

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

    // Isola um mês (por número, ex.: 1 = janeiro): filtra apenas esse mês,
    // em todos os anos disponíveis — usado no duplo clique e no "Ver mês atual".
    const isolarMes = (mesNum: number) => {
        const indices = data.monthly
            .map((m, i) => (mesDeRotulo(m.name) === mesNum ? i : -1))
            .filter((i) => i !== -1);
        onChange(indices.length === allIndices.length ? [] : indices);
    };

    const toggleMonth = (idx: number) => {
        let newValue: number[];
        if (isAllSelected) {
            newValue = allIndices.filter((i) => i !== idx);
        } else {
            newValue = value.includes(idx) ? value.filter((v) => v !== idx) : [...value, idx];
        }

        if (newValue.length === allIndices.length) newValue = [];
        onChange(newValue);
    };

    // Clique único alterna o mês imediatamente (com sincronia entre anos
    // feita no pai) — sem atraso, para que cliques rápidos em meses
    // diferentes em sequência funcionem normalmente. Só quando o SEGUNDO
    // clique cai no mesmo mês dentro da janela é que tratamos como duplo
    // clique e isolamos esse mês.
    const handleMonthClick = (idx: number) => {
        // Date.now() aqui é seguro: handleMonthClick só roda a partir do
        // onClick do botão de mês, nunca durante o render — a regra de
        // pureza do eslint-plugin-react-hooks não distingue isso ainda.
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
        if (isAllSelected) {
            newValue = allIndices.filter((idx) => !yearIndices.includes(idx));
        } else if (!currentlySelected) {
            newValue = Array.from(new Set([...value, ...yearIndices]));
        } else {
            newValue = value.filter((idx) => !yearIndices.includes(idx));
        }

        if (newValue.length === allIndices.length) newValue = [];
        onChange(newValue);
    };

    const selectUntilNow = () => {
        if (closeTimeoutRef.current) clearTimeout(closeTimeoutRef.current);
        const agora = new Date();
        const anoAtual = agora.getFullYear();
        const mesAtual = agora.getMonth() + 1;

        const indices = data.monthly
            .map((m, idx) => {
                const mes = mesDeRotulo(m.name);
                if (m.year < anoAtual) return idx;
                if (m.year === anoAtual && mes > 0 && mes <= mesAtual) return idx;
                return -1;
            })
            .filter((i) => i !== -1);

        onChange(indices.length === allIndices.length ? [] : indices);
    };

    const verMesAtual = () => {
        if (closeTimeoutRef.current) clearTimeout(closeTimeoutRef.current);
        const mesAtual = new Date().getMonth() + 1;
        isolarMes(mesAtual);
    };

    const getSelectedText = () => {
        if (value.length === 0) return 'Todos os períodos';
        const contagens = years
            .map((y) => {
                const n = value.filter((i) => data.monthly[i]?.year === y).length;
                return n > 0 ? `${n}m ('${String(y).slice(2)})` : null;
            })
            .filter(Boolean);
        if (contagens.length > 1) return contagens.join(' vs ');
        return `${value.length} meses selecionados`;
    };

    return (
        <div className="filter-group" style={{ position: 'relative' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <label style={{ marginBottom: 0 }}>
                    <TrendingUp size={12} style={{ marginRight: 4 }} /> {label}
                </label>
                {value.length > 0 && (
                    <button
                        type="button"
                        onClick={(e) => {
                            e.stopPropagation();
                            onChange([]);
                        }}
                        className="mini-clear-btn"
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
                        <div style={{ display: 'flex', gap: '6px', marginBottom: '8px' }}>
                            <button
                                type="button"
                                onClick={selectUntilNow}
                                style={{
                                    flex: 1,
                                    padding: '8px 10px',
                                    borderRadius: '8px',
                                    border: '1px solid rgba(99, 102, 241, 0.35)',
                                    background: 'rgba(99, 102, 241, 0.12)',
                                    color: 'var(--text-primary)',
                                    fontSize: '0.72rem',
                                    fontWeight: 600,
                                    cursor: 'pointer',
                                    fontFamily: 'inherit',
                                }}
                            >
                                Meses até agora
                            </button>
                            <button
                                type="button"
                                onClick={verMesAtual}
                                title="Filtra apenas o mês atual em todos os anos"
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
                        </div>
                        <p
                            style={{
                                margin: '0 2px 8px',
                                fontSize: '0.62rem',
                                color: 'var(--text-secondary)',
                                lineHeight: 1.3,
                            }}
                        >
                            Dica: clique duplo num mês para ver só ele nos anos disponíveis.
                        </p>

                        {years.map((y) => {
                            const yearIndices = data.monthly
                                .map((m, idx) => (m.year === y ? idx : -1))
                                .filter((i) => i !== -1);
                            const yearAllSelected =
                                isAllSelected ||
                                (yearIndices.length > 0 && yearIndices.every((idx) => value.includes(idx)));
                            const yearSomeSelected =
                                !isAllSelected &&
                                yearIndices.some((idx) => value.includes(idx)) &&
                                !yearAllSelected;
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
                                                                borderColor:
                                                                    isAllSelected || value.includes(idx)
                                                                        ? 'transparent'
                                                                        : 'var(--border)',
                                                                cursor: 'pointer',
                                                                background:
                                                                    isAllSelected || value.includes(idx)
                                                                        ? y === years[0]
                                                                            ? 'var(--accent)'
                                                                            : '#10b981'
                                                                        : 'rgba(255,255,255,0.02)',
                                                                color:
                                                                    isAllSelected || value.includes(idx)
                                                                        ? 'white'
                                                                        : 'var(--text-secondary)',
                                                                transition: 'all 0.2s',
                                                                fontWeight:
                                                                    isAllSelected || value.includes(idx) ? 600 : 500,
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
