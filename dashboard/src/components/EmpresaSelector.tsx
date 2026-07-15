import { useEffect, useState } from 'react';
import { Building2, ChevronDown, Loader2, RefreshCw, Settings, X } from 'lucide-react';
import {
    definirCaminhoFonteDados,
    definirCaminhoTrabalho,
    listarEmpresasDashboard,
    obterCaminhoFonteDados,
    obterCaminhoTrabalho,
} from '../api/client';

// ==========================================
// Types & Interfaces
// ==========================================

interface EmpresaSelectorProps {
    /** Empresa selecionada ('' = dados padrão do summary.json estático) */
    empresa: string;
    onChange: (empresa: string) => void;
    /** true enquanto o summary da empresa está sendo processado no backend */
    loading?: boolean;
}

const ROTULO_PADRAO = 'Dados padrão';

// ==========================================
// Main Component
// ==========================================

export function EmpresaSelector({ empresa, onChange, loading = false }: EmpresaSelectorProps) {
    const [empresas, setEmpresas] = useState<string[]>([]);
    const [dropdownAberto, setDropdownAberto] = useState(false);
    const [configAberta, setConfigAberta] = useState(false);
    const [caminhoFonte, setCaminhoFonte] = useState('');
    const [caminhoTrabalho, setCaminhoTrabalho] = useState('');
    const [sincronizando, setSincronizando] = useState(false);
    const [erro, setErro] = useState<string | null>(null);

    useEffect(() => {
        // Backend indisponível não pode quebrar o dashboard público: fica só
        // sem opções de empresa (o summary.json estático continua funcionando).
        listarEmpresasDashboard().then(setEmpresas).catch(() => setEmpresas([]));
    }, []);

    const abrirConfig = () => {
        setErro(null);
        setDropdownAberto(false);
        setConfigAberta(true);
        obterCaminhoFonteDados(false)
            .then((atual) => { if (atual) setCaminhoFonte(atual); })
            .catch(() => { /* usuário ainda pode digitar o caminho */ });
        obterCaminhoTrabalho(false)
            .then((atual) => { if (atual) setCaminhoTrabalho(atual); })
            .catch(() => { /* usuário ainda pode digitar o caminho */ });
    };

    const sincronizar = async () => {
        setErro(null);
        setSincronizando(true);
        try {
            if (caminhoFonte.trim()) {
                await definirCaminhoFonteDados(caminhoFonte.trim(), false);
            }
            if (caminhoTrabalho.trim()) {
                await definirCaminhoTrabalho(caminhoTrabalho.trim(), false);
            }
            const lista = await listarEmpresasDashboard();
            setEmpresas(lista);
            if (lista.length === 0) {
                setErro('Nenhuma empresa com pasta BI/ encontrada na pasta fonte.');
            }
        } catch (e) {
            setErro(e instanceof Error ? e.message : 'Falha ao sincronizar empresas.');
        } finally {
            setSincronizando(false);
        }
    };

    const selecionar = (nome: string) => {
        setDropdownAberto(false);
        setConfigAberta(false);
        if (nome !== empresa) onChange(nome);
    };

    return (
        <>
            <button
                type="button"
                onClick={abrirConfig}
                title="Configurar dados e empresa"
                aria-label="Configurar dados e empresa"
                style={{
                    display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
                    background: 'rgba(255,255,255,0.05)', color: 'var(--text-secondary)',
                    border: '1px solid var(--border)', borderRadius: '0.65rem',
                    padding: '0.55rem', cursor: 'pointer',
                }}
            >
                {loading
                    ? <Loader2 size={16} className="dashboard-filter-spinner" />
                    : <Settings size={16} />}
            </button>

            {configAberta && (
                <div className="config-modal-overlay" onClick={() => { setConfigAberta(false); setDropdownAberto(false); }} role="presentation">
                    <div
                        className="glass-card"
                        role="dialog"
                        aria-modal="true"
                        aria-labelledby="empresa-config-titulo"
                        onClick={(e) => e.stopPropagation()}
                        style={{ width: 'min(520px, 92vw)', padding: '1.5rem', display: 'flex', flexDirection: 'column', gap: '1rem' }}
                    >
                        <header style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                            <h2 id="empresa-config-titulo" style={{ margin: 0, fontSize: '1.05rem', color: 'white' }}>
                                Dados do dashboard
                            </h2>
                            <button
                                type="button"
                                className="analisador-btn analisador-btn-sec"
                                onClick={() => { setConfigAberta(false); setDropdownAberto(false); }}
                                aria-label="Fechar"
                            >
                                <X size={16} />
                            </button>
                        </header>

                        <label className="analisador-campo">
                            <span>Pasta fonte (BI, somente leitura)</span>
                            <input
                                className="analisador-input"
                                value={caminhoFonte}
                                onChange={(e) => setCaminhoFonte(e.target.value)}
                                placeholder="Ex.: C:\...\clientes-fonte"
                            />
                        </label>
                        <p className="analisador-hint" style={{ margin: 0 }}>
                            Subpastas com BI/ ({'{cliente}'}_MOVIMENTO_ATUAL + _PRODUTO). O app nunca altera esta pasta.
                        </p>

                        <label className="analisador-campo">
                            <span>Pasta de trabalho (Base.csv / config)</span>
                            <input
                                className="analisador-input"
                                value={caminhoTrabalho}
                                onChange={(e) => setCaminhoTrabalho(e.target.value)}
                                placeholder="Ex.: C:\...\clientes-trabalho"
                            />
                        </label>
                        <p className="analisador-hint" style={{ margin: 0 }}>
                            Onde o app grava Base.csv, config.json e harm.xlsx. Deve ser distinta da fonte.
                        </p>

                        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '0.5rem' }}>
                            <button
                                type="button"
                                className="analisador-btn analisador-btn-pri"
                                onClick={sincronizar}
                                disabled={sincronizando}
                            >
                                {sincronizando
                                    ? <Loader2 size={14} className="dashboard-filter-spinner" />
                                    : <RefreshCw size={14} />}
                                Sincronizar
                            </button>
                        </div>

                        <label className="analisador-campo" style={{ marginBottom: 0 }}>
                            <span>Empresa</span>
                            <div style={{ position: 'relative' }}>
                                <div
                                    className="custom-select"
                                    onClick={() => setDropdownAberto(!dropdownAberto)}
                                    style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '0.5rem', cursor: 'pointer' }}
                                >
                                    <span style={{ display: 'inline-flex', alignItems: 'center', gap: '0.5rem', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                        <Building2 size={14} style={{ opacity: 0.7, flexShrink: 0 }} />
                                        {empresa || ROTULO_PADRAO}
                                    </span>
                                    <ChevronDown size={14} style={{ opacity: 0.6, flexShrink: 0 }} />
                                </div>

                                {dropdownAberto && (
                                    <div style={{
                                        position: 'absolute', top: '100%', left: 0, right: 0, zIndex: 10,
                                        background: '#1a1a1e', border: '1px solid var(--border)', borderRadius: '12px',
                                        marginTop: '8px', padding: '8px', boxShadow: '0 10px 25px rgba(0,0,0,0.5)',
                                        maxHeight: '240px', overflowY: 'auto', display: 'flex', flexDirection: 'column',
                                    }}>
                                        <div
                                            onClick={() => selecionar('')}
                                            style={{
                                                padding: '8px 12px', borderRadius: '8px', cursor: 'pointer', fontSize: '0.85rem',
                                                color: empresa === '' ? 'var(--accent)' : 'var(--text-secondary)',
                                                background: empresa === '' ? 'rgba(99, 102, 241, 0.1)' : 'transparent',
                                            }}
                                        >
                                            {ROTULO_PADRAO}
                                        </div>
                                        {empresas.map((nome) => (
                                            <div
                                                key={nome}
                                                onClick={() => selecionar(nome)}
                                                style={{
                                                    padding: '8px 12px', borderRadius: '8px', cursor: 'pointer', fontSize: '0.85rem',
                                                    color: empresa === nome ? 'var(--accent)' : 'white',
                                                    background: empresa === nome ? 'rgba(99, 102, 241, 0.1)' : 'transparent',
                                                }}
                                            >
                                                {nome}
                                            </div>
                                        ))}
                                        {empresas.length === 0 && (
                                            <div style={{ padding: '8px 12px', fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
                                                Nenhuma empresa sincronizada. Salve os caminhos e clique em Sincronizar.
                                            </div>
                                        )}
                                    </div>
                                )}
                            </div>
                        </label>

                        {erro && (
                            <p style={{ margin: 0, fontSize: '0.85rem', color: '#f43f5e' }}>{erro}</p>
                        )}

                        <p className="analisador-hint" style={{ margin: 0 }}>
                            {empresas.length > 0
                                ? `${empresas.length} empresa(s) disponível(is). A seleção aparece ao lado de Prisma no topo.`
                                : 'Salve os dois caminhos e sincronize para listar as empresas.'}
                        </p>
                    </div>
                </div>
            )}
        </>
    );
}
