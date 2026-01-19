import { useState, useEffect } from 'react';
import {
    Users, Package, Store, LayoutDashboard, AlertTriangle, X, Filter, SlidersHorizontal, RefreshCw
} from 'lucide-react';
import { PeriodSelector } from './PeriodSelector';
import type { DashboardData } from '../types/dashboard';

interface FilterContentProps {
    data: DashboardData;
    filters: {
        client: number;
        mfr: number;
        desc: number;
        store: number;
        severity: number;
        period: number[];
    };
    filterOptions: {
        clientOpts: Set<number>;
        mfrOpts: Set<number>;
        descOpts: Set<number>;
        storeOpts: Set<number>;
    } | null;
    setters: {
        setClient: (v: number) => void;
        setMfr: (v: number) => void;
        setDesc: (v: number) => void;
        setStore: (v: number) => void;
        setSeverity: (v: number) => void;
        setPeriod: (v: number[]) => void;
    };
    onClear: () => void;
}

interface CustomDropdownProps {
    label: string;
    icon: any;
    value: number;
    options: { id: number; name: string }[];
    onChange: (id: number) => void;
    onClear: () => void;
    placeholder: string;
}

function CustomDropdown({ label, icon: Icon, value, options, onChange, onClear, placeholder }: CustomDropdownProps) {
    const [isOpen, setIsOpen] = useState(false);
    const [search, setSearch] = useState('');

    const selectedName = options.find(o => o.id === value)?.name || placeholder;
    const filteredOptions = options.filter(o => o.name.toLowerCase().includes(search.toLowerCase()));

    return (
        <div className="filter-group" style={{ position: 'relative' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
                <label style={{ marginBottom: 0 }}><Icon size={12} style={{ marginRight: 4 }} /> {label}</label>
                {value !== -1 && <button onClick={(e) => { e.stopPropagation(); onClear(); }} className="mini-clear-btn"><X size={10} /></button>}
            </div>
            <div
                className="custom-select"
                onClick={() => setIsOpen(!isOpen)}
                style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', cursor: 'pointer' }}
            >
                <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{selectedName}</span>
            </div>

            {isOpen && (
                <>
                    <div style={{ position: 'fixed', inset: 0, zIndex: 999 }} onClick={() => setIsOpen(false)} />
                    <div style={{
                        position: 'absolute', top: '100%', left: 0, right: 0, zIndex: 1000,
                        background: '#1a1a1e', border: '1px solid var(--border)', borderRadius: '12px',
                        marginTop: '8px', padding: '8px', boxShadow: '0 10px 25px rgba(0,0,0,0.5)',
                        maxHeight: '300px', display: 'flex', flexDirection: 'column', gap: '8px'
                    }}>
                        <input
                            autoFocus
                            type="text"
                            placeholder="Buscar..."
                            value={search}
                            onChange={e => setSearch(e.target.value)}
                            onClick={e => e.stopPropagation()}
                            style={{
                                background: 'rgba(255,255,255,0.05)', border: '1px solid var(--border)',
                                borderRadius: '8px', padding: '8px 12px', color: 'white', fontSize: '0.85rem', outline: 'none'
                            }}
                        />
                        <div className="custom-scrollbar" style={{ overflowY: 'auto', flex: 1, display: 'flex', flexDirection: 'column' }}>
                            <div
                                onClick={() => { onChange(-1); setIsOpen(false); }}
                                style={{
                                    padding: '8px 12px', borderRadius: '8px', cursor: 'pointer', fontSize: '0.85rem',
                                    color: value === -1 ? 'var(--accent)' : 'var(--text-secondary)',
                                    background: value === -1 ? 'rgba(99, 102, 241, 0.1)' : 'transparent'
                                }}
                            >
                                {placeholder}
                            </div>
                            {filteredOptions.map(opt => (
                                <div
                                    key={opt.id}
                                    onClick={() => { onChange(opt.id); setIsOpen(false); }}
                                    style={{
                                        padding: '8px 12px', borderRadius: '8px', cursor: 'pointer', fontSize: '0.85rem',
                                        color: value === opt.id ? 'var(--accent)' : 'white',
                                        background: value === opt.id ? 'rgba(99, 102, 241, 0.1)' : 'transparent'
                                    }}
                                >
                                    {opt.name}
                                </div>
                            ))}
                            {filteredOptions.length === 0 && (
                                <div style={{ padding: '8px 12px', fontSize: '0.85rem', color: 'var(--text-secondary)', textAlign: 'center' }}>
                                    Nenhuma opção encontrada
                                </div>
                            )}
                        </div>
                    </div>
                </>
            )}
        </div>
    );
}

function FilterContent({ data, filters, filterOptions, setters, onClear }: FilterContentProps) {
    const { client, mfr, desc, store, severity, period } = filters;
    const { setClient, setMfr, setDesc, setStore, setSeverity, setPeriod } = setters;

    const severityOpts = [
        { id: 0, name: "🟡 Amena (-8% a -15%)" },
        { id: 1, name: "🟠 Grave (-15% a -35%)" },
        { id: 2, name: "🔴 Gravíssima (-35% a -60%)" },
        { id: 3, name: "💀 Desconstrução (< -60%)" }
    ];

    const hasFilters = client !== -1 || mfr !== -1 || desc !== -1 || store !== -1 || severity !== -1 || period.length > 0;

    return (
        <>
            <div style={{ gridColumn: '1 / -1', marginBottom: '16px', display: 'flex', justifyContent: 'flex-end', width: '100%' }}>
                <button
                    onClick={onClear}
                    disabled={!hasFilters}
                    style={{
                        background: 'transparent',
                        border: 'none',
                        color: hasFilters ? 'var(--accent)' : 'var(--text-secondary)',
                        display: 'flex',
                        alignItems: 'center',
                        gap: '6px',
                        padding: '0',
                        cursor: hasFilters ? 'pointer' : 'not-allowed',
                        opacity: hasFilters ? 1 : 0.4,
                        transition: 'all 0.2s ease',
                        width: 'fit-content'
                    }}
                    onMouseOver={(e) => hasFilters && (e.currentTarget.style.filter = 'brightness(1.2)')}
                    onMouseOut={(e) => hasFilters && (e.currentTarget.style.filter = 'none')}
                >
                    <RefreshCw size={14} className={hasFilters ? "" : ""} />
                    <span style={{ fontSize: '0.85rem', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.5px' }}>
                        Resetar Filtros
                    </span>
                </button>
            </div>

            <CustomDropdown
                label="Gravidade"
                icon={AlertTriangle}
                value={severity}
                options={severityOpts}
                onChange={v => { setSeverity(v); setClient(-1); }}
                onClear={() => setSeverity(-1)}
                placeholder="Todos os Cenários"
            />

            <CustomDropdown
                label="Cliente"
                icon={Users}
                value={client}
                options={data.maps.c.map((name, id) => ({ id, name })).filter(o => client === o.id || (filterOptions?.clientOpts.has(o.id)))}
                onChange={setClient}
                onClear={() => setClient(-1)}
                placeholder="Todos os Clientes"
            />

            <CustomDropdown
                label="Loja"
                icon={Store}
                value={store}
                options={data.maps.s.map((name, id) => ({ id, name })).filter(o => store === o.id || (filterOptions?.storeOpts.has(o.id)))}
                onChange={setStore}
                onClear={() => setStore(-1)}
                placeholder="Todas as Lojas"
            />

            <CustomDropdown
                label="Fabricante"
                icon={Package}
                value={mfr}
                options={data.maps.m.map((name, id) => ({ id, name })).filter(o => mfr === o.id || (filterOptions?.mfrOpts.has(o.id)))}
                onChange={setMfr}
                onClear={() => setMfr(-1)}
                placeholder="Todos os Fabricantes"
            />

            <CustomDropdown
                label="Descrição"
                icon={LayoutDashboard}
                value={desc}
                options={data.maps.d.map((name, id) => ({ id, name })).filter(o => desc === o.id || (filterOptions?.descOpts.has(o.id)))}
                onChange={setDesc}
                onClear={() => setDesc(-1)}
                placeholder="Todas as Descrições"
            />

            <PeriodSelector
                label="Período de Análise"
                value={period}
                data={data}
                onChange={setPeriod}
            />
        </>
    );
}

interface FilterBarProps {
    data: DashboardData;
    filters: {
        client: number;
        mfr: number;
        desc: number;
        store: number;
        severity: number;
        period: number[];
    };
    filterOptions: {
        clientOpts: Set<number>;
        mfrOpts: Set<number>;
        descOpts: Set<number>;
        storeOpts: Set<number>;
    } | null;
    setters: {
        setClient: (v: number) => void;
        setMfr: (v: number) => void;
        setDesc: (v: number) => void;
        setStore: (v: number) => void;
        setSeverity: (v: number) => void;
        setPeriod: (v: number[]) => void;
    };
    onClear: () => void;
}

export function FilterBar({ data, filters, filterOptions, setters, onClear }: FilterBarProps) {
    const [isModalOpen, setIsModalOpen] = useState(false);
    const [isMobile, setIsMobile] = useState(window.innerWidth <= 1280);

    useEffect(() => {
        const handleResize = () => setIsMobile(window.innerWidth <= 1280);
        window.addEventListener('resize', handleResize);
        return () => window.removeEventListener('resize', handleResize);
    }, []);

    const { client, mfr, desc, store, severity, period } = filters;

    if (isMobile) {
        return (
            <div style={{ marginBottom: '1.5rem' }}>
                <button
                    onClick={() => setIsModalOpen(true)}
                    className="glass-card"
                    style={{
                        width: '100%',
                        padding: '12px',
                        display: 'flex',
                        justifyContent: 'center',
                        alignItems: 'center',
                        gap: '10px',
                        color: 'white',
                        border: '1px solid var(--border)',
                        cursor: 'pointer'
                    }}
                >
                    <Filter size={18} color="var(--accent)" />
                    <span style={{ fontWeight: 600 }}>Filtros e Períodos</span>
                    {(client !== -1 || mfr !== -1 || desc !== -1 || store !== -1 || severity !== -1 || period.length > 0) && (
                        <span style={{
                            background: 'var(--accent)',
                            borderRadius: '50%',
                            width: '18px',
                            height: '18px',
                            fontSize: '10px',
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'center'
                        }}>!</span>
                    )}
                </button>

                {isModalOpen && (
                    <div style={{
                        position: 'fixed',
                        inset: 0,
                        zIndex: 10000,
                        background: 'rgba(0,0,0,0.85)',
                        backdropFilter: 'blur(10px)',
                        display: 'flex',
                        alignItems: 'flex-end',
                        justifyContent: 'center'
                    }}>
                        <div
                            style={{
                                width: '100%',
                                maxHeight: '90vh',
                                background: '#121214',
                                borderTopLeftRadius: '24px',
                                borderTopRightRadius: '24px',
                                padding: '24px',
                                overflowY: 'auto',
                                position: 'relative',
                                boxShadow: '0 -10px 40px rgba(0,0,0,0.5)'
                            }}
                        >
                            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '24px' }}>
                                <h2 style={{ color: 'white', fontSize: '1.25rem', display: 'flex', alignItems: 'center', gap: '8px' }}>
                                    <SlidersHorizontal size={20} color="var(--accent)" /> Filtros
                                </h2>
                                <button
                                    onClick={() => setIsModalOpen(false)}
                                    style={{ background: 'rgba(255,255,255,0.05)', border: 'none', borderRadius: '50%', width: '36px', height: '36px', display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'white', cursor: 'pointer' }}
                                >
                                    <X size={20} />
                                </button>
                            </div>

                            <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
                                <FilterContent data={data} filters={filters} filterOptions={filterOptions} setters={setters} onClear={onClear} />
                            </div>

                            <button
                                onClick={() => setIsModalOpen(false)}
                                style={{
                                    width: '100%',
                                    padding: '16px',
                                    background: 'white',
                                    color: 'black',
                                    border: 'none',
                                    borderRadius: '12px',
                                    marginTop: '24px',
                                    fontWeight: 'bold',
                                    fontSize: '1rem'
                                }}
                            >
                                Visualizar Dashboard
                            </button>
                        </div>
                    </div>
                )}
            </div>
        );
    }

    return (
        <div className="filters-header">
            <FilterContent data={data} filters={filters} filterOptions={filterOptions} setters={setters} onClear={onClear} />
        </div>
    );
}
