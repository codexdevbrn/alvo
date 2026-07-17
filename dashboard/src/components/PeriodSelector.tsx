import { useState, useRef, useEffect, type MouseEvent } from 'react';
import { X, TrendingUp, Check } from 'lucide-react';
import type { DashboardData, GranularidadeDash } from '../types/dashboard';
import {
  indicesAteMesAtual,
  indicesMesesFechados,
  mesDeRotulo,
  periodosIguais,
  rotuloCorteMesesFechados,
} from '../utils/periodoFechado';
import {
  indicesAtePeriodoAtual,
  indicesPeriodoAtual,
  indicesPeriodosFechados,
  listBuckets,
  rotuloUnidade,
  type BucketInfo,
} from '../utils/granularidade';

interface PeriodSelectorProps {
  label: string;
  value: number[];
  data: DashboardData;
  onChange: (value: number[]) => void;
  usarMesesFechados?: boolean;
  onUsarMesesFechados?: (value: boolean) => void;
  granularidade?: GranularidadeDash;
}

export function PeriodSelector({
  label,
  value,
  data,
  onChange,
  usarMesesFechados = false,
  onUsarMesesFechados,
  granularidade = 'Mensal',
}: PeriodSelectorProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [expandedYears, setExpandedYears] = useState<Set<number>>(() => new Set());
  const closeTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const lastMonthClickRef = useRef<{ idx: number; time: number }>({ idx: -1, time: 0 });

  const years = Array.from(new Set(data.monthly.map((m) => m.year))).sort((a, b) => a - b);
  const allIndices = data.monthly.map((_, i) => i);
  const selecionados = value.length === 0 ? allIndices : value;
  const unidade = rotuloUnidade(granularidade);
  const buckets = listBuckets(data, granularidade);
  const indicesFechados =
    granularidade === 'Mensal'
      ? indicesMesesFechados(data)
      : indicesPeriodosFechados(data, granularidade);
  const indicesAteAgora =
    granularidade === 'Mensal'
      ? indicesAteMesAtual(data)
      : indicesAtePeriodoAtual(data, granularidade);

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

  const toggleBucket = (bucket: BucketInfo) => {
    const todos = bucket.monthIndices.every((idx) => selecionados.includes(idx));
    let newValue: number[];
    if (todos) {
      const rem = new Set(bucket.monthIndices);
      newValue = selecionados.filter((idx) => !rem.has(idx));
    } else {
      newValue = Array.from(new Set([...selecionados, ...bucket.monthIndices]));
    }
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

  const selectFechados = (e?: MouseEvent) => {
    e?.stopPropagation();
    if (closeTimeoutRef.current) clearTimeout(closeTimeoutRef.current);
    onUsarMesesFechados?.(true);
    onChange(indicesFechados);
  };

  const selectAteAgora = (e?: MouseEvent) => {
    e?.stopPropagation();
    if (closeTimeoutRef.current) clearTimeout(closeTimeoutRef.current);
    onUsarMesesFechados?.(false);
    onChange(indicesAteAgora);
  };

  const selectTodos = (e?: MouseEvent) => {
    e?.stopPropagation();
    if (closeTimeoutRef.current) clearTimeout(closeTimeoutRef.current);
    onUsarMesesFechados?.(false);
    onChange(allIndices);
  };

  const verPeriodoAtual = (e?: MouseEvent) => {
    e?.stopPropagation();
    if (closeTimeoutRef.current) clearTimeout(closeTimeoutRef.current);
    if (granularidade === 'Mensal') {
      isolarMes(new Date().getMonth() + 1);
      return;
    }
    onChange(indicesPeriodoAtual(data, granularidade));
  };

  const getSelectedText = () => {
    if (value.length === 0) {
      return usarMesesFechados
        ? `Todos os períodos (só ${unidade.plural} fechados)`
        : 'Todos os períodos';
    }
    if (periodosIguais(value, allIndices)) {
      return `${unidade.todos} (incl. período corrente)`;
    }

    if (granularidade === 'Mensal') {
      const contagens = years
        .map((y) => {
          const n = value.filter((i) => data.monthly[i]?.year === y).length;
          return n > 0 ? `${n}m ('${String(y).slice(2)})` : null;
        })
        .filter(Boolean);
      if (contagens.length > 1) return contagens.join(' vs ');
      return `${value.length} meses selecionados`;
    }

    const selecionadosBuckets = buckets.filter((b) =>
      b.monthIndices.every((idx) => value.includes(idx)),
    );
    const contagens = years
      .map((y) => {
        const n = selecionadosBuckets.filter((b) => b.year === y).length;
        return n > 0 ? `${n}${unidade.singular[0]} ('${String(y).slice(2)})` : null;
      })
      .filter(Boolean);
    if (contagens.length > 1) return contagens.join(' vs ');
    return `${selecionadosBuckets.length} ${unidade.plural} selecionados`;
  };

  const mesEstaSelecionado = (idx: number) => selecionados.includes(idx);

  const bucketEstaSelecionado = (bucket: BucketInfo) =>
    bucket.monthIndices.length > 0 &&
    bucket.monthIndices.every((idx) => mesEstaSelecionado(idx));

  const bucketParcial = (bucket: BucketInfo) =>
    bucket.monthIndices.some((idx) => mesEstaSelecionado(idx)) && !bucketEstaSelecionado(bucket);

  const anosAsc = years;
  const anoMaisRecente = anosAsc[anosAsc.length - 1];
  /** Alinha com HistoryChart: série B (ano atual) = verde, série A (anterior) = accent. */
  const corAno = (y: number) => (y === anoMaisRecente ? '#10b981' : 'var(--accent)');
  const corAnoSolida = (y: number) => (y === anoMaisRecente ? '#10b981' : '#6366f1');

  const cols =
    granularidade === 'Mensal' ? 3 :
    granularidade === 'Trimestral' ? 4 :
    granularidade === 'Semestral' ? 2 : 1;

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
            className="custom-scrollbar dropdown-menu-panel"
            style={{
              position: 'absolute',
              top: '100%',
              left: 0,
              right: 0,
              zIndex: 1000,
              marginTop: '8px',
              padding: '8px',
              maxHeight: '400px',
              overflowY: 'auto',
            }}
          >
            <div style={{ display: 'flex', flexDirection: 'column', gap: '6px', marginBottom: '8px' }}>
              <div style={{ display: 'flex', gap: '6px' }}>
                <button
                  type="button"
                  className="period-dropdown-action"
                  onClick={selectFechados}
                  title={`Só ${unidade.plural} fechados, mesmo corte nos dois anos`}
                  style={{
                    flex: 1,
                    padding: '8px 10px',
                    borderRadius: '8px',
                    border: periodosIguais(value, indicesFechados)
                      ? '1px solid rgba(99, 102, 241, 0.65)'
                      : '1px solid rgba(99, 102, 241, 0.35)',
                    background: periodosIguais(value, indicesFechados)
                      ? 'rgba(99, 102, 241, 0.22)'
                      : 'rgba(99, 102, 241, 0.12)',
                    color: 'var(--text-primary)',
                    fontSize: '0.72rem',
                    fontWeight: 600,
                    cursor: 'pointer',
                    fontFamily: 'inherit',
                  }}
                >
                  {unidade.fechados}
                </button>
                <button
                  type="button"
                  className="period-dropdown-action"
                  onClick={selectAteAgora}
                  title={`${unidade.plural} até o período corrente (incluso)`}
                  style={{
                    flex: 1,
                    padding: '8px 10px',
                    borderRadius: '8px',
                    border: periodosIguais(value, indicesAteAgora)
                      ? '1px solid rgba(245, 158, 11, 0.65)'
                      : '1px solid rgba(245, 158, 11, 0.35)',
                    background: periodosIguais(value, indicesAteAgora)
                      ? 'rgba(245, 158, 11, 0.22)'
                      : 'rgba(245, 158, 11, 0.12)',
                    color: 'var(--text-primary)',
                    fontSize: '0.72rem',
                    fontWeight: 600,
                    cursor: 'pointer',
                    fontFamily: 'inherit',
                  }}
                >
                  {unidade.ateAgora}
                </button>
              </div>
              <div style={{ display: 'flex', gap: '6px' }}>
                <button
                  type="button"
                  className="period-dropdown-action"
                  onClick={verPeriodoAtual}
                  title={`Filtra apenas o ${unidade.singular} corrente em todos os anos`}
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
                  {unidade.atual}
                </button>
                <button
                  type="button"
                  className="period-dropdown-action"
                  onClick={selectTodos}
                  title={`${unidade.todos}, incl. corrente`}
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
                  {unidade.todos}
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
                ? `Com a opção ativa, entram só ${unidade.plural} fechados (${rotuloCorteMesesFechados()}).`
                : `Todos os ${unidade.plural} entram nos cálculos, inclusive o período corrente.`}
              {granularidade === 'Mensal' &&
                ' Dica: duplo clique num mês para ver só ele nos anos disponíveis.'}
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
              const yearBuckets = buckets.filter((b) => b.year === y);

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
                    className="period-dropdown-year-row"
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
                                          border: `1.5px solid ${yearAllSelected || yearSomeSelected ? corAno(y) : 'rgba(255,255,255,0.2)'}`,
                                          backgroundColor: yearAllSelected
                                            ? corAnoSolida(y)
                                            : yearSomeSelected
                                              ? `${corAnoSolida(y)}33`
                                              : 'transparent',
                                          display: 'flex',
                                          alignItems: 'center',
                                          justifyContent: 'center',
                                          cursor: 'pointer',
                                          transition: 'all 0.2s cubic-bezier(0.4, 0, 0.2, 1)',
                                          boxShadow: yearAllSelected
                                            ? `0 0 10px ${corAnoSolida(y)}55`
                                            : 'none',
                                        }}
                                      >
                                        {yearAllSelected && <Check size={12} color="white" strokeWidth={3} />}
                                        {yearSomeSelected && (
                                          <div
                                            style={{
                                              width: '8px',
                                              height: '2px',
                                              backgroundColor: corAnoSolida(y),
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
                        gridTemplateColumns: `repeat(${cols}, 1fr)`,
                        gap: '6px',
                        padding: '10px 12px',
                      }}
                    >
                      {granularidade === 'Mensal'
                        ? data.monthly.map(
                            (m, idx) =>
                              m.year === y && (
                                <button
                                  key={idx}
                                  type="button"
                                  className="period-dropdown-chip"
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
                                      ? corAnoSolida(y)
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
                          )
                        : yearBuckets.map((bucket) => {
                            const on = bucketEstaSelecionado(bucket);
                            const partial = bucketParcial(bucket);
                            return (
                              <button
                                key={bucket.key}
                                type="button"
                                className="period-dropdown-chip"
                                onClick={() => toggleBucket(bucket)}
                                style={{
                                  padding: '8px 4px',
                                  fontSize: '0.7rem',
                                  borderRadius: '8px',
                                  border: '1px solid',
                                  borderColor: on || partial ? 'transparent' : 'var(--border)',
                                  cursor: 'pointer',
                                  background: on
                                    ? corAnoSolida(y)
                                    : partial
                                      ? `${corAnoSolida(y)}40`
                                      : 'rgba(255,255,255,0.02)',
                                  color: on || partial ? 'white' : 'var(--text-secondary)',
                                  transition: 'all 0.2s',
                                  fontWeight: on ? 600 : 500,
                                }}
                              >
                                {bucket.shortLabel}
                              </button>
                            );
                          })}
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
