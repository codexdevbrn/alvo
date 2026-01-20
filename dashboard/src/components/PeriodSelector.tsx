import { useState, useRef, useEffect } from 'react';
import { X, TrendingUp, Check } from 'lucide-react';
import type { DashboardData } from '../types/dashboard';

// ==========================================
// Types & Interfaces
// ==========================================

interface PeriodSelectorProps {
    label: string;
    value: number[];
    data: DashboardData;
    onChange: (value: number[]) => void;
}

// ==========================================
// Main Component
// ==========================================

export function PeriodSelector({ label, value, data, onChange }: PeriodSelectorProps) {
    // ==========================================
    // State & Refs
    // ==========================================

    const [isOpen, setIsOpen] = useState(false);
    const [expandedYear, setExpandedYear] = useState<number | null>(null);
    const closeTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

    const years = Array.from(new Set(data.monthly.map((m: any) => m.year))).sort() as number[];
    const allIndices = data.monthly.map((_: any, i: number) => i);
    const isAllSelected = value.length === 0;

    // ==========================================
    // Effects
    // ==========================================

    // Clear timeout on unmount or when manual toggle happens
    useEffect(() => {
        return () => {
            if (closeTimeoutRef.current) clearTimeout(closeTimeoutRef.current);
        };
    }, []);

    // ==========================================
    // Helper Functions (Handlers)
    // ==========================================

    const startCloseTimer = () => {
        if (closeTimeoutRef.current) clearTimeout(closeTimeoutRef.current);
        closeTimeoutRef.current = setTimeout(() => {
            setIsOpen(false);
        }, 2000); // 2 seconds delay
    };

    const handleToggle = () => {
        if (closeTimeoutRef.current) clearTimeout(closeTimeoutRef.current);
        setIsOpen(!isOpen);
    };

    const handleMonthClick = (idx: number) => {
        let newValue: number[];
        if (isAllSelected) {
            newValue = allIndices.filter(i => i !== idx);
        } else {
            newValue = value.includes(idx) ? value.filter((v: any) => v !== idx) : [...value, idx];
        }

        if (newValue.length === allIndices.length) newValue = [];
        onChange(newValue);
        startCloseTimer();
    };

    const handleOutsideClick = () => {
        if (closeTimeoutRef.current) clearTimeout(closeTimeoutRef.current);
        setIsOpen(false);
    };

    const toggleYear = (y: number, currentlySelected: boolean) => {
        if (closeTimeoutRef.current) clearTimeout(closeTimeoutRef.current);
        const yearIndices = data.monthly.map((m: any, idx: number) => m.year === y ? idx : -1).filter(i => i !== -1);

        let newValue: number[];
        if (isAllSelected) {
            newValue = allIndices.filter(idx => !yearIndices.includes(idx));
        } else {
            if (!currentlySelected) {
                newValue = Array.from(new Set([...value, ...yearIndices]));
            } else {
                newValue = value.filter(idx => !yearIndices.includes(idx));
            }
        }

        if (newValue.length === allIndices.length) newValue = [];
        onChange(newValue);
        startCloseTimer();
    };

    const getSelectedText = () => {
        if (value.length === 0) return "Todos os períodos";
        const c24 = value.filter((i: any) => data.monthly[i].year === 2024).length;
        const c25 = value.filter((i: any) => data.monthly[i].year === 2025).length;
        if (c24 && c25) return `${c24}m ('24) vs ${c25}m ('25)`;
        return `${value.length} meses selecionados`;
    };

    // ==========================================
    // Render
    // ==========================================

    return (
        <div className="filter-group" style={{ position: 'relative' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
                <label style={{ marginBottom: 0 }}><TrendingUp size={12} style={{ marginRight: 4 }} /> {label}</label>
                {value.length > 0 && <button onClick={(e) => { e.stopPropagation(); onChange([]); }} className="mini-clear-btn"><X size={10} /></button>}
            </div>
            <div
                className="custom-select"
                onClick={handleToggle}
                style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', cursor: 'pointer' }}
            >
                <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{getSelectedText()}</span>
            </div>

            {isOpen && (
                <>
                    <div style={{ position: 'fixed', inset: 0, zIndex: 999 }} onClick={handleOutsideClick} />
                    <div style={{
                        position: 'absolute', top: '100%', left: 0, right: 0, zIndex: 1000,
                        background: '#1a1a1e', border: '1px solid var(--border)', borderRadius: '12px',
                        marginTop: '8px', padding: '8px', boxShadow: '0 10px 25px rgba(0,0,0,0.5)',
                        maxHeight: '400px', overflowY: 'auto'
                    }}>
                        {years.map(y => {
                            const yearIndices = data.monthly.map((m: any, idx: number) => m.year === y ? idx : -1).filter(i => i !== -1);
                            const yearAllSelected = isAllSelected || (yearIndices.length > 0 && yearIndices.every(idx => value.includes(idx)));
                            const yearSomeSelected = !isAllSelected && yearIndices.some(idx => value.includes(idx)) && !yearAllSelected;

                            return (
                                <div key={y} style={{ marginBottom: '8px', borderBottom: '1px solid rgba(255,255,255,0.05)', paddingBottom: '4px' }}>
                                    <div
                                        style={{
                                            padding: '8px 12px', borderRadius: '10px',
                                            display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                                            background: expandedYear === y ? 'rgba(255,255,255,0.03)' : 'transparent',
                                            transition: 'background 0.2s'
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
                                                    backgroundColor: yearAllSelected ? 'var(--accent)' : (yearSomeSelected ? 'rgba(99, 102, 241, 0.2)' : 'transparent'),
                                                    display: 'flex',
                                                    alignItems: 'center',
                                                    justifyContent: 'center',
                                                    cursor: 'pointer',
                                                    transition: 'all 0.2s cubic-bezier(0.4, 0, 0.2, 1)',
                                                    boxShadow: yearAllSelected ? '0 0 10px rgba(99, 102, 241, 0.3)' : 'none'
                                                }}
                                            >
                                                {yearAllSelected && <Check size={12} color="white" strokeWidth={3} />}
                                                {yearSomeSelected && <div style={{ width: '8px', height: '2px', backgroundColor: 'var(--accent)', borderRadius: '1px' }} />}
                                            </div>
                                            <span
                                                onClick={() => {
                                                    if (closeTimeoutRef.current) clearTimeout(closeTimeoutRef.current);
                                                    setExpandedYear(expandedYear === y ? null : y);
                                                }}
                                                style={{
                                                    color: yearAllSelected || yearSomeSelected ? 'white' : 'var(--text-secondary)',
                                                    fontWeight: 600,
                                                    cursor: 'pointer',
                                                    fontSize: '0.85rem',
                                                    transition: 'color 0.2s'
                                                }}
                                            >
                                                {y}
                                            </span>
                                        </div>
                                        <span
                                            onClick={() => {
                                                if (closeTimeoutRef.current) clearTimeout(closeTimeoutRef.current);
                                                setExpandedYear(expandedYear === y ? null : y);
                                            }}
                                            style={{
                                                fontSize: '0.6rem',
                                                color: 'var(--text-secondary)',
                                                cursor: 'pointer',
                                                padding: '6px',
                                                transform: expandedYear === y ? 'rotate(0deg)' : 'rotate(-90deg)',
                                                transition: 'transform 0.3s'
                                            }}
                                        >
                                            ▼
                                        </span>
                                    </div>
                                    {expandedYear === y && (
                                        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '6px', padding: '10px 12px' }}>
                                            {data.monthly.map((m: any, idx: number) => m.year === y && (
                                                <button
                                                    key={idx}
                                                    onClick={() => handleMonthClick(idx)}
                                                    style={{
                                                        padding: '8px 4px', fontSize: '0.7rem', borderRadius: '8px',
                                                        border: '1px solid',
                                                        borderColor: (isAllSelected || value.includes(idx)) ? 'transparent' : 'var(--border)',
                                                        cursor: 'pointer',
                                                        background: (isAllSelected || value.includes(idx)) ? (y === 2024 ? 'var(--accent)' : '#10b981') : 'rgba(255,255,255,0.02)',
                                                        color: (isAllSelected || value.includes(idx)) ? 'white' : 'var(--text-secondary)',
                                                        transition: 'all 0.2s',
                                                        fontWeight: (isAllSelected || value.includes(idx)) ? 600 : 500
                                                    }}
                                                >
                                                    {m.name.split('/')[0]}
                                                </button>
                                            ))}
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


