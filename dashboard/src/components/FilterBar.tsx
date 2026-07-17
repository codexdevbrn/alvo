import { useState, useEffect, useRef } from 'react';
import {
    Users, Package, Store, LayoutDashboard, AlertTriangle, X, Filter, SlidersHorizontal, RefreshCw, CalendarClock, Check
} from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import { PeriodSelector } from './PeriodSelector';
import { textoBannerMesesFechados } from '../utils/periodoFechado';
import { GRANULARIDADES_DASH, rotuloUnidade } from '../utils/granularidade';
import type { DashboardData, GranularidadeDash } from '../types/dashboard';

// ==========================================
// Types & Interfaces
// ==========================================

type IdFilters = {
    client: number[];
    mfr: number[];
    desc: number[];
    store: number[];
    severity: number[];
    period: number[];
    usarMesesFechados: boolean;
    visaoDetalhada: boolean;
    granularidade: GranularidadeDash;
};

type IdFilterSetters = {
    setClient: (v: number[]) => void;
    setMfr: (v: number[]) => void;
    setDesc: (v: number[]) => void;
    setStore: (v: number[]) => void;
    setSeverity: (v: number[]) => void;
    setPeriod: (v: number[]) => void;
    setUsarMesesFechados: (v: boolean) => void;
    setVisaoDetalhada: (v: boolean) => void;
    setGranularidade: (v: GranularidadeDash) => void;
};

interface FilterContentProps {
    data: DashboardData;
    filters: IdFilters;
    filterOptions: {
        clientOpts: Set<number>;
        mfrOpts: Set<number>;
        descOpts: Set<number>;
        storeOpts: Set<number>;
    } | null;
    setters: IdFilterSetters;
    onClear: () => void;
}

interface CustomDropdownProps {
    label: string;
    icon: LucideIcon;
    value: number[];
    options: { id: number; name: string }[];
    onChange: (ids: number[]) => void;
    onClear: () => void;
    placeholder: string;
    /** Sem busca: mostra só os N primeiros; com texto na busca, libera o restante. */
    limitePadrao?: number;
}

interface FilterBarProps {
    data: DashboardData;
    filters: IdFilters;
    filterOptions: {
        clientOpts: Set<number>;
        mfrOpts: Set<number>;
        descOpts: Set<number>;
        storeOpts: Set<number>;
    } | null;
    setters: IdFilterSetters;
    onClear: () => void;
}

// ==========================================
// Helper Components
// ==========================================

function rotuloSelecao(value: number[], options: { id: number; name: string }[], placeholder: string) {
    if (value.length === 0) return placeholder;
    if (value.length === 1) {
        return options.find(o => o.id === value[0])?.name || placeholder;
    }
    return `${value.length} selecionados`;
}

function CustomDropdown({
    label,
    icon: Icon,
    value,
    options,
    onChange,
    onClear,
    placeholder,
    limitePadrao,
}: CustomDropdownProps) {
    const [isOpen, setIsOpen] = useState(false);
    const [search, setSearch] = useState('');

    const selectedName = rotuloSelecao(value, options, placeholder);
    const selectedSet = new Set(value);
    const busca = search.trim().toLowerCase();
    const matched = busca
        ? options.filter((o) => o.name.toLowerCase().includes(busca))
        : options;

    let visibleOptions = matched;
    let truncated = false;
    if (limitePadrao != null && limitePadrao > 0 && !busca) {
        const head = matched.slice(0, limitePadrao);
        const headIds = new Set(head.map((o) => o.id));
        const extrasSelecionados = matched.filter(
            (o) => selectedSet.has(o.id) && !headIds.has(o.id),
        );
        visibleOptions = [...head, ...extrasSelecionados];
        truncated = matched.length > limitePadrao;
    }

    const toggle = (id: number) => {
        if (selectedSet.has(id)) onChange(value.filter(v => v !== id));
        else onChange([...value, id]);
    };

    const fechar = () => {
        setIsOpen(false);
        setSearch('');
    };

    return (
        <div className="filter-group" style={{ position: 'relative' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <label style={{ marginBottom: 0 }}><Icon size={12} style={{ marginRight: 4 }} /> {label}</label>
                {value.length > 0 && <button onClick={(e) => { e.stopPropagation(); onClear(); }} className="mini-clear-btn"><X size={10} /></button>}
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
                    <div style={{ position: 'fixed', inset: 0, zIndex: 999 }} onClick={fechar} />
                    <div className="dropdown-menu-panel" style={{
                        position: 'absolute', top: '100%', left: 0, right: 0, zIndex: 1000,
                        marginTop: '8px', padding: '8px',
                        maxHeight: '300px', display: 'flex', flexDirection: 'column', gap: '8px'
                    }}>
                        <input
                            autoFocus
                            type="text"
                            placeholder={limitePadrao ? `Buscar entre ${options.length.toLocaleString('pt-BR')}…` : 'Buscar...'}
                            value={search}
                            onChange={e => setSearch(e.target.value)}
                            onClick={e => e.stopPropagation()}
                            style={{
                                background: 'rgba(255,255,255,0.05)', border: '1px solid var(--border)',
                                borderRadius: '8px', padding: '8px 12px', color: 'white', fontSize: '0.85rem', outline: 'none'
                            }}
                        />
                        <div className="custom-scrollbar" style={{ overflowY: 'auto', flex: 1, display: 'flex', flexDirection: 'column', gap: '2px' }}>
                            <div
                                role="option"
                                aria-selected={value.length === 0}
                                className={`dropdown-menu-item is-muted${value.length === 0 ? ' is-selected' : ''}`}
                                onClick={() => { onChange([]); fechar(); }}
                            >
                                {placeholder}
                            </div>
                            {visibleOptions.map(opt => {
                                const ativo = selectedSet.has(opt.id);
                                return (
                                    <div
                                        key={opt.id}
                                        role="option"
                                        aria-selected={ativo}
                                        className={`dropdown-menu-item${ativo ? ' is-selected' : ''}`}
                                        onClick={() => toggle(opt.id)}
                                        style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}
                                    >
                                        <span style={{ overflow: 'hidden', textOverflow: 'ellipsis' }}>{opt.name}</span>
                                        {ativo && <Check size={14} color="var(--accent)" strokeWidth={3} style={{ flexShrink: 0 }} />}
                                    </div>
                                );
                            })}
                            {truncated && (
                                <div style={{ padding: '8px 12px', fontSize: '0.75rem', color: 'var(--text-secondary)', textAlign: 'center' }}>
                                    Mostrando {limitePadrao} de {matched.length.toLocaleString('pt-BR')} — digite para buscar o restante
                                </div>
                            )}
                            {visibleOptions.length === 0 && (
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

const VISAO_TOGGLE_ANIM_MS = 220;

function VisaoToggle({
    value,
    onChange,
}: {
    value: boolean;
    onChange: (detalhada: boolean) => void;
}) {
    const [uiValue, setUiValue] = useState(value);
    const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

    useEffect(() => {
        setUiValue(value);
    }, [value]);

    useEffect(() => () => {
        if (timerRef.current) clearTimeout(timerRef.current);
    }, []);

    const select = (detalhada: boolean) => {
        if (detalhada === uiValue) return;
        if (timerRef.current) clearTimeout(timerRef.current);
        setUiValue(detalhada);
        timerRef.current = setTimeout(() => {
            onChange(detalhada);
            timerRef.current = null;
        }, VISAO_TOGGLE_ANIM_MS);
    };

    return (
        <div className="visao-toggle filters-option-chip" role="group" aria-label="Modo de visualização">
            <span className="visao-toggle-label">Visualização</span>
            <div className={`visao-toggle-track${uiValue ? ' is-detalhada' : ''}`}>
                <span className="visao-toggle-thumb" aria-hidden="true" />
                <button
                    type="button"
                    className={`visao-toggle-btn${!uiValue ? ' is-active' : ''}`}
                    onClick={() => select(false)}
                    aria-pressed={!uiValue}
                >
                    Sintética
                </button>
                <button
                    type="button"
                    className={`visao-toggle-btn${uiValue ? ' is-active' : ''}`}
                    onClick={() => select(true)}
                    aria-pressed={uiValue}
                >
                    Detalhada
                </button>
            </div>
        </div>
    );
}

function FilterContent({ data, filters, filterOptions, setters, onClear }: FilterContentProps) {
    const { client, mfr, desc, store, severity, period, usarMesesFechados, visaoDetalhada, granularidade } = filters;
    const {
        setClient, setMfr, setDesc, setStore, setSeverity, setPeriod,
        setUsarMesesFechados, setVisaoDetalhada, setGranularidade,
    } = setters;

    const severityOpts = [
        { id: 0, name: "Amena (-8% a -15%)" },
        { id: 1, name: "Grave (-15% a -35%)" },
        { id: 2, name: "Gravíssima (-35% a -60%)" },
        { id: 3, name: "Desconstrução (< -60%)" }
    ];

    const unidade = rotuloUnidade(granularidade);
    const hasFilters = client.length > 0 || mfr.length > 0 || desc.length > 0 || store.length > 0 || severity.length > 0
      || period.length > 0 || !usarMesesFechados || visaoDetalhada || granularidade !== 'Mensal';

    return (
        <>
            <div className="filters-grid">
            <CustomDropdown
                label="Gravidade"
                icon={AlertTriangle}
                value={severity}
                options={severityOpts}
                onChange={v => { setSeverity(v); setClient([]); }}
                onClear={() => setSeverity([])}
                placeholder="Todos os Cenários"
            />

            <CustomDropdown
                label="Cliente"
                icon={Users}
                value={client}
                options={data.maps.c
                    .map((name, id) => ({ id, name }))
                    .filter(o => o.name !== "Consumidor Final")
                    .filter(o => client.includes(o.id) || (filterOptions?.clientOpts.has(o.id)))}
                onChange={setClient}
                onClear={() => setClient([])}
                placeholder="Todos os Clientes"
                limitePadrao={60}
            />

            <CustomDropdown
                label="Loja"
                icon={Store}
                value={store}
                options={data.maps.s.map((name, id) => ({ id, name })).filter(o => store.includes(o.id) || (filterOptions?.storeOpts.has(o.id)))}
                onChange={setStore}
                onClear={() => setStore([])}
                placeholder="Todas as Lojas"
            />

            <CustomDropdown
                label="Fabricante"
                icon={Package}
                value={mfr}
                options={data.maps.m.map((name, id) => ({ id, name })).filter(o => mfr.includes(o.id) || (filterOptions?.mfrOpts.has(o.id)))}
                onChange={setMfr}
                onClear={() => setMfr([])}
                placeholder="Todos os Fabricantes"
            />

            <CustomDropdown
                label="Descrição"
                icon={LayoutDashboard}
                value={desc}
                options={data.maps.d.map((name, id) => ({ id, name })).filter(o => desc.includes(o.id) || (filterOptions?.descOpts.has(o.id)))}
                onChange={setDesc}
                onClear={() => setDesc([])}
                placeholder="Todas as Descrições"
            />

            <PeriodSelector
                label="Período de Análise"
                value={period}
                data={data}
                onChange={setPeriod}
                usarMesesFechados={usarMesesFechados}
                onUsarMesesFechados={setUsarMesesFechados}
                granularidade={granularidade}
            />
            </div>

            <div className="filters-options-bar">
                <label
                    className="periodo-fechado-check filters-option-chip"
                    title={usarMesesFechados
                      ? textoBannerMesesFechados(new Date(), granularidade)
                      : `Incluir o ${unidade.singular} corrente nos cálculos dos cards`}
                >
                    <input
                        type="checkbox"
                        checked={usarMesesFechados}
                        onChange={(e) => setUsarMesesFechados(e.target.checked)}
                    />
                    <CalendarClock size={14} aria-hidden="true" />
                    <span>
                      {granularidade === 'Mensal'
                        ? 'Meses fechados nos cálculos'
                        : 'Períodos fechados nos cálculos'}
                    </span>
                </label>

                <div className="granularidade-options" role="group" aria-label="Granularidade do dashboard">
                    <span className="granularidade-options-label">
                        <CalendarClock size={12} aria-hidden="true" /> Granularidade
                    </span>
                    <div className="granularidade-segmented">
                        {GRANULARIDADES_DASH.map((g) => (
                            <button
                                key={g}
                                type="button"
                                className={`granularidade-seg-btn${granularidade === g ? ' is-active' : ''}`}
                                aria-pressed={granularidade === g}
                                onClick={() => setGranularidade(g)}
                            >
                                {g}
                            </button>
                        ))}
                    </div>
                </div>

                <div className="filters-options-right">
                    <VisaoToggle value={visaoDetalhada} onChange={setVisaoDetalhada} />

                    <button
                        onClick={onClear}
                        disabled={!hasFilters}
                        className="filters-reset-btn filters-option-chip"
                        style={{
                            color: hasFilters ? 'var(--accent)' : 'var(--text-secondary)',
                            cursor: hasFilters ? 'pointer' : 'not-allowed',
                            opacity: hasFilters ? 1 : 0.4,
                        }}
                        onMouseOver={(e) => hasFilters && (e.currentTarget.style.filter = 'brightness(1.2)')}
                        onMouseOut={(e) => hasFilters && (e.currentTarget.style.filter = 'none')}
                    >
                        <RefreshCw size={13} />
                        <span>Resetar Filtros</span>
                    </button>
                </div>
            </div>
        </>
    );
}

// ==========================================
// Main Component
// ==========================================

export function FilterBar({ data, filters, filterOptions, setters, onClear }: FilterBarProps) {
    const [isModalOpen, setIsModalOpen] = useState(false);
    const [isMobile, setIsMobile] = useState(window.innerWidth <= 1280);

    // Effect: Handle Screen Resize
    useEffect(() => {
        const handleResize = () => setIsMobile(window.innerWidth <= 1280);
        window.addEventListener('resize', handleResize);
        return () => window.removeEventListener('resize', handleResize);
    }, []);

    const { client, mfr, desc, store, severity, period, usarMesesFechados, visaoDetalhada, granularidade } = filters;
    const hasActiveFilters = client.length > 0 || mfr.length > 0 || desc.length > 0 || store.length > 0 || severity.length > 0
      || period.length > 0 || !usarMesesFechados || visaoDetalhada || granularidade !== 'Mensal';

    // Mobile View
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
                    {hasActiveFilters && (
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
                    <div className="mobile-filter-modal-overlay">
                        <div className="mobile-filter-modal-content">
                            <div className="mobile-filter-modal-header">
                                <h2 style={{ color: 'white', fontSize: '1.25rem', display: 'flex', alignItems: 'center', gap: '8px', margin: 0 }}>
                                    <SlidersHorizontal size={20} color="var(--accent)" /> Filtros e Períodos
                                </h2>
                                <button
                                    onClick={() => setIsModalOpen(false)}
                                    className="mobile-filter-close-btn"
                                >
                                    <X size={20} />
                                </button>
                            </div>

                            <div className="mobile-filter-list">
                                <FilterContent data={data} filters={filters} filterOptions={filterOptions} setters={setters} onClear={onClear} />
                            </div>

                            <button
                                onClick={() => setIsModalOpen(false)}
                                className="mobile-filter-apply-btn"
                            >
                                Visualizar Dashboard
                            </button>
                        </div>
                    </div>
                )}
            </div>
        );
    }

    // Desktop View
    return (
        <div className="filters-header">
            <FilterContent data={data} filters={filters} filterOptions={filterOptions} setters={setters} onClear={onClear} />
        </div>
    );
}
