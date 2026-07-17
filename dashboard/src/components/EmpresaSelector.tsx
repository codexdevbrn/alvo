import { useEffect, useMemo, useState } from 'react';
import { Building2, ChevronDown, FolderOpen, Loader2, RefreshCw, Save, Search, Settings, X } from 'lucide-react';
import {
    escolherPasta,
    definirCaminhoFonteDados,
    definirCaminhoTrabalho,
    listarEmpresasDashboard,
    obterCaminhoFonteDados,
    obterCaminhoTrabalho,
    regenerarBaseEmpresa,
} from '../api/client';

// ==========================================
// Types & Interfaces
// ==========================================

interface EmpresaSelectorProps {
    /** Empresa selecionada ('' = dados padrão do summary.json estático) */
    empresa: string;
    onChange: (empresa: string) => void;
    /** Chamado após regenerar a Base.csv com sucesso — recarrega os dados da empresa. */
    onRecarregarEmpresa?: (empresa: string) => void;
}

const ROTULO_PADRAO = 'Dados padrão';
const LS_CAMINHO_FONTE = 'prisma_caminho_fonte';
const LS_CAMINHO_TRABALHO = 'prisma_caminho_trabalho';

function lerLocal(chave: string): string {
    try {
        return localStorage.getItem(chave) || '';
    } catch {
        return '';
    }
}

function gravarLocal(chave: string, valor: string) {
    try {
        if (valor) localStorage.setItem(chave, valor);
        else localStorage.removeItem(chave);
    } catch {
        /* private mode / quota — backend continua sendo a fonte da verdade */
    }
}

// ==========================================
// Main Component
// ==========================================

export function EmpresaSelector({
    empresa,
    onChange,
    onRecarregarEmpresa,
}: EmpresaSelectorProps) {
    const [empresas, setEmpresas] = useState<string[]>([]);
    const [dropdownAberto, setDropdownAberto] = useState(false);
    const [configAberta, setConfigAberta] = useState(false);
    const [caminhoFonte, setCaminhoFonte] = useState(() => lerLocal(LS_CAMINHO_FONTE));
    const [caminhoTrabalho, setCaminhoTrabalho] = useState(() => lerLocal(LS_CAMINHO_TRABALHO));
    const [sincronizando, setSincronizando] = useState(false);
    const [salvando, setSalvando] = useState(false);
    const [regenerando, setRegenerando] = useState(false);
    const [buscando, setBuscando] = useState<'fonte' | 'trabalho' | null>(null);
    const [erro, setErro] = useState<string | null>(null);
    const [okMsg, setOkMsg] = useState<string | null>(null);
    const [buscaEmpresa, setBuscaEmpresa] = useState('');

    const empresasFiltradas = useMemo(() => {
        const termo = buscaEmpresa.trim().toLowerCase();
        if (!termo) return empresas;
        return empresas.filter((nome) => nome.toLowerCase().includes(termo));
    }, [empresas, buscaEmpresa]);

    useEffect(() => {
        // Backend indisponível não pode quebrar o dashboard público: fica só
        // sem opções de empresa (o summary.json estático continua funcionando).
        listarEmpresasDashboard().then(setEmpresas).catch(() => setEmpresas([]));
        // Prefetch dos caminhos salvos para preencher o modal na próxima abertura
        // e manter localStorage alinhado com o SQLite do backend.
        Promise.all([obterCaminhoFonteDados(false), obterCaminhoTrabalho(false)])
            .then(([fonte, trabalho]) => {
                if (fonte) {
                    setCaminhoFonte(fonte);
                    gravarLocal(LS_CAMINHO_FONTE, fonte);
                }
                if (trabalho) {
                    setCaminhoTrabalho(trabalho);
                    gravarLocal(LS_CAMINHO_TRABALHO, trabalho);
                }
            })
            .catch(() => { /* localStorage / digitação manual cobrem o gap */ });
    }, []);

    const abrirConfig = () => {
        setErro(null);
        setOkMsg(null);
        setDropdownAberto(false);
        setConfigAberta(true);
        obterCaminhoFonteDados(false)
            .then((atual) => {
                if (atual) {
                    setCaminhoFonte(atual);
                    gravarLocal(LS_CAMINHO_FONTE, atual);
                }
            })
            .catch(() => { /* usuário ainda pode digitar o caminho */ });
        obterCaminhoTrabalho(false)
            .then((atual) => {
                if (atual) {
                    setCaminhoTrabalho(atual);
                    gravarLocal(LS_CAMINHO_TRABALHO, atual);
                }
            })
            .catch(() => { /* usuário ainda pode digitar o caminho */ });
    };

    const persistirCaminhos = async () => {
        let fonteSalva = caminhoFonte.trim();
        let trabalhoSalvo = caminhoTrabalho.trim();
        if (fonteSalva) {
            fonteSalva = await definirCaminhoFonteDados(fonteSalva, false);
            setCaminhoFonte(fonteSalva);
            gravarLocal(LS_CAMINHO_FONTE, fonteSalva);
        }
        if (trabalhoSalvo) {
            trabalhoSalvo = await definirCaminhoTrabalho(trabalhoSalvo, false);
            setCaminhoTrabalho(trabalhoSalvo);
            gravarLocal(LS_CAMINHO_TRABALHO, trabalhoSalvo);
        }
        if (!fonteSalva && !trabalhoSalvo) {
            throw new Error('Informe ao menos um caminho para salvar.');
        }
    };

    const salvarCaminhos = async () => {
        setErro(null);
        setOkMsg(null);
        setSalvando(true);
        try {
            await persistirCaminhos();
            setOkMsg('Caminhos salvos.');
        } catch (e) {
            setErro(e instanceof Error ? e.message : 'Falha ao salvar os caminhos.');
        } finally {
            setSalvando(false);
        }
    };

    const sincronizar = async () => {
        setErro(null);
        setOkMsg(null);
        setSincronizando(true);
        try {
            if (caminhoFonte.trim() || caminhoTrabalho.trim()) {
                await persistirCaminhos();
            }
            const lista = await listarEmpresasDashboard();
            setEmpresas(lista);
            if (lista.length === 0) {
                setErro('Nenhuma empresa com pasta BI/ encontrada na pasta fonte.');
            } else {
                setOkMsg(`${lista.length} empresa(s) sincronizada(s).`);
            }
        } catch (e) {
            setErro(e instanceof Error ? e.message : 'Falha ao sincronizar empresas.');
        } finally {
            setSincronizando(false);
        }
    };

    const regenerarBase = async () => {
        if (!empresa) {
            setErro('Selecione uma empresa antes de regenerar a base.');
            return;
        }
        setErro(null);
        setOkMsg(null);
        setRegenerando(true);
        try {
            if (caminhoFonte.trim() || caminhoTrabalho.trim()) {
                await persistirCaminhos();
            }
            await regenerarBaseEmpresa(empresa, false);
            setOkMsg(`Base de ${empresa} regenerada. Recarregando…`);
            onRecarregarEmpresa?.(empresa);
        } catch (e) {
            setErro(e instanceof Error ? e.message : 'Falha ao regenerar a base.');
        } finally {
            setRegenerando(false);
        }
    };

    const buscarPasta = async (campo: 'fonte' | 'trabalho') => {
        setErro(null);
        setOkMsg(null);
        setBuscando(campo);
        try {
            const titulo = campo === 'fonte'
                ? 'Selecionar pasta fonte (BI)'
                : 'Selecionar pasta de trabalho';
            const escolhido = await escolherPasta(titulo, false);
            if (escolhido == null) return; // cancelado
            if (campo === 'fonte') {
                setCaminhoFonte(escolhido);
                gravarLocal(LS_CAMINHO_FONTE, escolhido);
            } else {
                setCaminhoTrabalho(escolhido);
                gravarLocal(LS_CAMINHO_TRABALHO, escolhido);
            }
        } catch (e) {
            setErro(e instanceof Error ? e.message : 'Falha ao abrir o seletor de pasta.');
        } finally {
            setBuscando(null);
        }
    };

    const selecionar = (nome: string) => {
        setDropdownAberto(false);
        setBuscaEmpresa('');
        setConfigAberta(false);
        if (nome !== empresa) onChange(nome);
    };

    const alternarDropdown = () => {
        setDropdownAberto((aberto) => {
            if (aberto) setBuscaEmpresa('');
            return !aberto;
        });
    };

    const ocupado = sincronizando || salvando || regenerando || buscando !== null;

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
                <Settings size={16} />
            </button>

            {configAberta && (
                <div className="config-modal-overlay" onClick={() => { setConfigAberta(false); setDropdownAberto(false); setBuscaEmpresa(''); }} role="presentation">
                    <div
                        className="glass-card empresa-config-card"
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
                                onClick={() => { setConfigAberta(false); setDropdownAberto(false); setBuscaEmpresa(''); }}
                                aria-label="Fechar"
                            >
                                <X size={16} />
                            </button>
                        </header>

                        <label className="analisador-campo">
                            <span>Pasta fonte (BI, somente leitura)</span>
                            <div className="caminho-pasta-row">
                                <input
                                    className="analisador-input"
                                    value={caminhoFonte}
                                    onChange={(e) => setCaminhoFonte(e.target.value)}
                                    placeholder="Ex.: C:\...\clientes-fonte"
                                />
                                <button
                                    type="button"
                                    className="analisador-btn analisador-btn-sec caminho-pasta-btn"
                                    onClick={() => buscarPasta('fonte')}
                                    disabled={ocupado}
                                    title="Buscar pasta"
                                    aria-label="Buscar pasta fonte"
                                >
                                    {buscando === 'fonte'
                                        ? <Loader2 size={14} className="dashboard-filter-spinner" />
                                        : <FolderOpen size={14} />}
                                    Buscar
                                </button>
                            </div>
                        </label>
                        <p className="analisador-hint" style={{ margin: 0 }}>
                            Subpastas com BI/ ({'{cliente}'}_MOVIMENTO_ATUAL + _PRODUTO). O app nunca altera esta pasta.
                        </p>

                        <label className="analisador-campo">
                            <span>Pasta de trabalho (Base.csv / config)</span>
                            <div className="caminho-pasta-row">
                                <input
                                    className="analisador-input"
                                    value={caminhoTrabalho}
                                    onChange={(e) => setCaminhoTrabalho(e.target.value)}
                                    placeholder="Ex.: C:\...\clientes-trabalho"
                                />
                                <button
                                    type="button"
                                    className="analisador-btn analisador-btn-sec caminho-pasta-btn"
                                    onClick={() => buscarPasta('trabalho')}
                                    disabled={ocupado}
                                    title="Buscar pasta"
                                    aria-label="Buscar pasta de trabalho"
                                >
                                    {buscando === 'trabalho'
                                        ? <Loader2 size={14} className="dashboard-filter-spinner" />
                                        : <FolderOpen size={14} />}
                                    Buscar
                                </button>
                            </div>
                        </label>
                        <p className="analisador-hint" style={{ margin: 0 }}>
                            Onde o app grava Base.csv, config.json e harm.xlsx. Deve ser distinta da fonte.
                        </p>

                        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '0.5rem', flexWrap: 'wrap' }}>
                            <button
                                type="button"
                                className="analisador-btn analisador-btn-sec"
                                onClick={salvarCaminhos}
                                disabled={ocupado}
                            >
                                {salvando
                                    ? <Loader2 size={14} className="dashboard-filter-spinner" />
                                    : <Save size={14} />}
                                Salvar caminhos
                            </button>
                            <button
                                type="button"
                                className="analisador-btn analisador-btn-sec"
                                onClick={sincronizar}
                                disabled={ocupado}
                            >
                                {sincronizando
                                    ? <Loader2 size={14} className="dashboard-filter-spinner" />
                                    : <RefreshCw size={14} />}
                                Sincronizar
                            </button>
                            <button
                                type="button"
                                className="analisador-btn analisador-btn-pri"
                                onClick={regenerarBase}
                                disabled={ocupado || !empresa}
                                title={empresa
                                    ? `Regenerar Base.csv de ${empresa} a partir do BI e recarregar`
                                    : 'Selecione uma empresa para regenerar a base'}
                            >
                                {regenerando
                                    ? <Loader2 size={14} className="dashboard-filter-spinner" />
                                    : <RefreshCw size={14} />}
                                Regenerar base
                            </button>
                        </div>

                        <p className="analisador-hint" style={{ margin: 0 }}>
                            Regenerar base lê o BI da fonte, recria Base.csv (e Liquidez) na pasta de trabalho
                            {empresa ? ` (${empresa})` : ''} e recarrega o dashboard. Fora disso o app só usa
                            o CSV já gerado; a data do último movimento no topo vem do BI.
                        </p>

                        <label className="analisador-campo" style={{ marginBottom: 0 }}>
                            <span>Empresa</span>
                            <div className="empresa-select-wrap">
                                <div
                                    className="custom-select"
                                    onClick={alternarDropdown}
                                    style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '0.5rem', cursor: 'pointer' }}
                                >
                                    <span style={{ display: 'inline-flex', alignItems: 'center', gap: '0.5rem', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                        <Building2 size={14} style={{ opacity: 0.7, flexShrink: 0 }} />
                                        {empresa || ROTULO_PADRAO}
                                    </span>
                                    <ChevronDown size={14} style={{ opacity: 0.6, flexShrink: 0 }} />
                                </div>

                                {dropdownAberto && (
                                    <div
                                        className="empresa-dropdown-panel"
                                        onClick={(e) => e.stopPropagation()}
                                    >
                                        <div className="empresa-dropdown-busca">
                                            <Search size={14} aria-hidden="true" />
                                            <input
                                                type="search"
                                                className="analisador-input"
                                                placeholder="Buscar empresa..."
                                                value={buscaEmpresa}
                                                onChange={(e) => setBuscaEmpresa(e.target.value)}
                                                autoFocus
                                                aria-label="Buscar empresa"
                                            />
                                        </div>
                                        <div className="empresa-dropdown-lista custom-scrollbar">
                                            {(!buscaEmpresa.trim() || ROTULO_PADRAO.toLowerCase().includes(buscaEmpresa.trim().toLowerCase())) && (
                                                <div
                                                    role="option"
                                                    aria-selected={empresa === ''}
                                                    className={`dropdown-menu-item empresa-dropdown-item is-padrao${empresa === '' ? ' is-selecionada is-selected' : ''}`}
                                                    onClick={() => selecionar('')}
                                                >
                                                    {ROTULO_PADRAO}
                                                </div>
                                            )}
                                            {empresasFiltradas.map((nome) => (
                                                <div
                                                    key={nome}
                                                    role="option"
                                                    aria-selected={empresa === nome}
                                                    className={`dropdown-menu-item empresa-dropdown-item${empresa === nome ? ' is-selecionada is-selected' : ''}`}
                                                    onClick={() => selecionar(nome)}
                                                >
                                                    {nome}
                                                </div>
                                            ))}
                                            {empresas.length === 0 && (
                                                <div className="empresa-dropdown-vazio">
                                                    Nenhuma empresa sincronizada. Salve os caminhos e clique em Sincronizar.
                                                </div>
                                            )}
                                            {empresas.length > 0 && empresasFiltradas.length === 0 && (
                                                <div className="empresa-dropdown-vazio">
                                                    Nenhuma empresa correspondente a “{buscaEmpresa.trim()}”.
                                                </div>
                                            )}
                                        </div>
                                    </div>
                                )}
                            </div>
                        </label>

                        {erro && (
                            <p style={{ margin: 0, fontSize: '0.85rem', color: '#f43f5e' }}>{erro}</p>
                        )}
                        {okMsg && !erro && (
                            <p style={{ margin: 0, fontSize: '0.85rem', color: '#34d399' }}>{okMsg}</p>
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
