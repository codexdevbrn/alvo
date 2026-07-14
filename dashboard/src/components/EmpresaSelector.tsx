import { useEffect, useState } from 'react';
import { Building2, ChevronDown, Loader2, RefreshCw, Settings, X } from 'lucide-react';
import {
    definirCaminhoDadosDashboard,
    listarEmpresasDashboard,
    obterCaminhoDadosDashboard,
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
    const [caminho, setCaminho] = useState('');
    const [sincronizando, setSincronizando] = useState(false);
    const [erro, setErro] = useState<string | null>(null);

    useEffect(() => {
        // Backend indisponível não pode quebrar o dashboard público: fica só
        // sem opções de empresa (o summary.json estático continua funcionando).
        listarEmpresasDashboard().then(setEmpresas).catch(() => setEmpresas([]));
    }, []);

    const abrirConfig = () => {
        setErro(null);
        setConfigAberta(true);
        obterCaminhoDadosDashboard()
            .then((atual) => { if (atual) setCaminho(atual); })
            .catch(() => { /* usuário ainda pode digitar o caminho */ });
    };

    const sincronizar = async () => {
        setErro(null);
        setSincronizando(true);
        try {
            if (caminho.trim()) {
                await definirCaminhoDadosDashboard(caminho.trim());
            }
            const lista = await listarEmpresasDashboard();
            setEmpresas(lista);
            if (lista.length === 0) {
                setErro('Nenhuma empresa encontrada nessa pasta (esperado: uma subpasta por empresa).');
            }
        } catch (e) {
            setErro(e instanceof Error ? e.message : 'Falha ao sincronizar empresas.');
        } finally {
            setSincronizando(false);
        }
    };

    const selecionar = (nome: string) => {
        setDropdownAberto(false);
        if (nome !== empresa) onChange(nome);
    };

    return (
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', position: 'relative' }}>
            {/* Combobox de empresa */}
            <div style={{ position: 'relative', minWidth: '180px' }}>
                <div
                    className="custom-select"
                    onClick={() => setDropdownAberto(!dropdownAberto)}
                    style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '0.5rem', cursor: 'pointer' }}
                >
                    <span style={{ display: 'inline-flex', alignItems: 'center', gap: '0.5rem', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        {loading
                            ? <Loader2 size={14} className="dashboard-filter-spinner" />
                            : <Building2 size={14} style={{ opacity: 0.7, flexShrink: 0 }} />}
                        {empresa || ROTULO_PADRAO}
                    </span>
                    <ChevronDown size={14} style={{ opacity: 0.6, flexShrink: 0 }} />
                </div>

                {dropdownAberto && (
                    <>
                        <div style={{ position: 'fixed', inset: 0, zIndex: 999 }} onClick={() => setDropdownAberto(false)} />
                        <div style={{
                            position: 'absolute', top: '100%', left: 0, right: 0, zIndex: 1000,
                            background: '#1a1a1e', border: '1px solid var(--border)', borderRadius: '12px',
                            marginTop: '8px', padding: '8px', boxShadow: '0 10px 25px rgba(0,0,0,0.5)',
                            maxHeight: '300px', overflowY: 'auto', display: 'flex', flexDirection: 'column',
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
                                    Nenhuma empresa sincronizada. Configure o caminho na engrenagem ao lado.
                                </div>
                            )}
                        </div>
                    </>
                )}
            </div>

            {/* Engrenagem — configura o caminho dos dados */}
            <button
                type="button"
                onClick={abrirConfig}
                title="Configurar caminho dos dados das empresas"
                aria-label="Configurar caminho dos dados das empresas"
                style={{
                    display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
                    background: 'rgba(255,255,255,0.05)', color: 'var(--text-secondary)',
                    border: '1px solid var(--border)', borderRadius: '0.65rem',
                    padding: '0.55rem', cursor: 'pointer',
                }}
            >
                <Settings size={16} />
            </button>

            {/* Modal de configuração */}
            {configAberta && (
                <div className="config-modal-overlay" onClick={() => setConfigAberta(false)} role="presentation">
                    <div
                        className="glass-card"
                        role="dialog"
                        aria-modal="true"
                        aria-labelledby="empresa-config-titulo"
                        onClick={(e) => e.stopPropagation()}
                        style={{ width: 'min(480px, 92vw)', padding: '1.5rem', display: 'flex', flexDirection: 'column', gap: '1rem' }}
                    >
                        <header style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                            <h2 id="empresa-config-titulo" style={{ margin: 0, fontSize: '1.05rem', color: 'white' }}>
                                Dados do dashboard
                            </h2>
                            <button
                                type="button"
                                className="analisador-btn analisador-btn-sec"
                                onClick={() => setConfigAberta(false)}
                                aria-label="Fechar"
                            >
                                <X size={16} />
                            </button>
                        </header>

                        <label className="analisador-campo">
                            <span>Pasta com as pastas das empresas (cada uma com Base.csv)</span>
                            <input
                                className="analisador-input"
                                value={caminho}
                                onChange={(e) => setCaminho(e.target.value)}
                                placeholder="Ex.: C:\...\base-clientes"
                            />
                        </label>

                        {erro && (
                            <p style={{ margin: 0, fontSize: '0.85rem', color: '#f43f5e' }}>{erro}</p>
                        )}

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

                        <p className="analisador-hint" style={{ margin: 0 }}>
                            {empresas.length > 0
                                ? `${empresas.length} empresa(s) sincronizada(s): ${empresas.join(', ')}`
                                : 'Salve o caminho e sincronize para listar as empresas no seletor.'}
                        </p>
                    </div>
                </div>
            )}
        </div>
    );
}
