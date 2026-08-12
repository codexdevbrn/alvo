import { useEffect, useState } from 'react';
import { Download, FolderOpen, Loader2, Pencil, Plus, RefreshCw, Save, Trash2 } from 'lucide-react';
import { AppShell } from '../components/AppShell';
import { NumberStepper } from '../components/analisador/NumberStepper';
import { PastaPickerModal } from '../components/PastaPickerModal';
import { EVENTO_EMPRESA } from '../utils/empresaSelecionada';
import {
  definirAguardandoBaseDados,
  definirCaminhoFonteDados,
  definirCaminhoTrabalho,
  listarEmpresasDashboard,
  obterAguardandoBaseDados,
  obterCaminhoFonteDados,
  obterCaminhoTrabalho,
  aplicarAtualizacao,
  definirCaminhoAtualizacoes,
  obterCaminhoAtualizacoes,
  obterStatusAtualizacao,
  obterTagsClientes,
  obterVersao,
  regenerarBaseEmpresa,
  salvarCatalogoTags,
  salvarConfiguracaoEmpresa,
  tentarCarregarConfiguracaoEmpresa,
  TAGS_CATALOGO_PADRAO,
  type ConfigEmpresaSalva,
  type StatusAtualizacao,
  type TagCatalogoItem,
} from '../api/client';
import { invalidarSummary } from '../utils/cacheSummary';

const LS_CAMINHO_FONTE = 'prisma_caminho_fonte';
const LS_CAMINHO_TRABALHO = 'prisma_caminho_trabalho';
const LS_EMPRESA = 'alvo_empresa';

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
    /* private mode / quota */
  }
}

function slugifyTag(rotulo: string): string {
  return rotulo
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '')
    .slice(0, 48) || 'tag';
}

function novoIdTag(rotulo: string, existentes: Set<string>): string {
  const base = slugifyTag(rotulo) || 'tag';
  let id = base;
  let n = 2;
  while (existentes.has(id)) {
    id = `${base}_${n}`;
    n += 1;
  }
  return id;
}

/** Uma única tela de Configurações, organizada por setores. */
export default function ConfiguracoesPage() {
  const [, setEmpresas] = useState<string[]>([]);
  const [empresa, setEmpresa] = useState(() => lerLocal(LS_EMPRESA));
  const [caminhoFonte, setCaminhoFonte] = useState(() => lerLocal(LS_CAMINHO_FONTE));
  const [caminhoTrabalho, setCaminhoTrabalho] = useState(() => lerLocal(LS_CAMINHO_TRABALHO));
  const [sincronizando, setSincronizando] = useState(false);
  const [salvando, setSalvando] = useState(false);
  const [regenerando, setRegenerando] = useState(false);
  const [buscando, setBuscando] = useState<'fonte' | 'trabalho' | 'atualizacoes' | null>(null);
  const [caminhoAtualizacoes, setCaminhoAtualizacoes] = useState('');
  const [statusAtualizacao, setStatusAtualizacao] = useState<StatusAtualizacao | null>(null);
  const [verificandoAtualizacao, setVerificandoAtualizacao] = useState(false);
  const [aplicandoAtualizacao, setAplicandoAtualizacao] = useState(false);
  const [feedbackAtualizacao, setFeedbackAtualizacao] = useState<{ tipo: 'ok' | 'erro'; texto: string } | null>(null);
  const [feedbackDados, setFeedbackDados] = useState<{ tipo: 'ok' | 'erro'; texto: string } | null>(null);
  const [aguardandoBaseDados, setAguardandoBaseDados] = useState(false);
  const [versao, setVersao] = useState<string | null>(null);
  const [salvandoFlag, setSalvandoFlag] = useState(false);

  const [tagsCatalogo, setTagsCatalogo] = useState<TagCatalogoItem[]>(TAGS_CATALOGO_PADRAO);
  const [novoTagNome, setNovoTagNome] = useState('');
  const [editandoTagId, setEditandoTagId] = useState<string | null>(null);
  const [salvandoTags, setSalvandoTags] = useState(false);
  const [feedbackTags, setFeedbackTags] = useState<{ tipo: 'ok' | 'erro'; texto: string } | null>(null);

  const [periodosQueda, setPeriodosQueda] = useState(2);
  const [quedaMinimaAlertaRs, setQuedaMinimaAlertaRs] = useState<number | ''>(3000);
  const [topNProdutos, setTopNProdutos] = useState<number | ''>('');
  const [reducaoMinimaErosao, setReducaoMinimaErosao] = useState(50);
  const [quedaMinimaErosaoRs, setQuedaMinimaErosaoRs] = useState<number | ''>(3000);
  const [reducaoMinimaSemVenda, setReducaoMinimaSemVenda] = useState(90);
  const [topNPoderCompra, setTopNPoderCompra] = useState<number | ''>('');
  const [excluirPeriodoAtual, setExcluirPeriodoAtual] = useState(true);
  const [erosaoSomenteProdutosEmAlerta, setErosaoSomenteProdutosEmAlerta] = useState(false);
  const [granularidade, setGranularidade] = useState('Mensal');
  const [configBase, setConfigBase] = useState<ConfigEmpresaSalva | null>(null);
  const [salvandoParams, setSalvandoParams] = useState(false);
  const [feedbackParams, setFeedbackParams] = useState<{ tipo: 'ok' | 'erro'; texto: string } | null>(null);

  useEffect(() => {
    listarEmpresasDashboard().then(setEmpresas).catch(() => setEmpresas([]));
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
      .catch(() => { /* localStorage cobre o gap */ });
    obterAguardandoBaseDados(false).then(setAguardandoBaseDados).catch(() => { /* mantém false */ });
  }, []);

  const alternarAguardandoBaseDados = async (valor: boolean) => {
    setAguardandoBaseDados(valor);
    setFeedbackDados(null);
    setSalvandoFlag(true);
    try {
      await definirAguardandoBaseDados(valor, false);
    } catch (e) {
      setAguardandoBaseDados(!valor);
      setFeedbackDados({ tipo: 'erro', texto: e instanceof Error ? e.message : 'Falha ao salvar a flag.' });
    } finally {
      setSalvandoFlag(false);
    }
  };

  useEffect(() => {
    // Versão é informativa: se a chamada falhar, o rodapé simplesmente não
    // aparece — nada aqui depende dela.
    void obterVersao()
      .then((info) => setVersao(info.versao))
      .catch(() => setVersao(null));
  }, []);

  useEffect(() => {
    // Consulta o canal ao abrir a tela. O backend já trata canal ausente ou
    // fora do ar como estado normal, então não há erro a exibir aqui.
    void obterCaminhoAtualizacoes()
      .then(async (caminho) => {
        setCaminhoAtualizacoes(caminho);
        setStatusAtualizacao(await obterStatusAtualizacao());
      })
      .catch(() => setStatusAtualizacao(null));
  }, []);

  useEffect(() => {
    const syncEmpresa = () => setEmpresa(lerLocal(LS_EMPRESA));
    window.addEventListener(EVENTO_EMPRESA, syncEmpresa);
    window.addEventListener('storage', syncEmpresa);
    return () => {
      window.removeEventListener(EVENTO_EMPRESA, syncEmpresa);
      window.removeEventListener('storage', syncEmpresa);
    };
  }, []);

  useEffect(() => {
    if (!empresa) {
      setTagsCatalogo(TAGS_CATALOGO_PADRAO);
      setEditandoTagId(null);
      setConfigBase(null);
      return;
    }
    let cancelado = false;
    void (async () => {
      try {
        const [tags, cfg] = await Promise.all([
          obterTagsClientes(empresa, null),
          tentarCarregarConfiguracaoEmpresa(empresa, null),
        ]);
        if (cancelado) return;
        setEditandoTagId(null);
        setTagsCatalogo(tags.catalogo?.length ? tags.catalogo : TAGS_CATALOGO_PADRAO);
        if (cfg) {
          setConfigBase(cfg);
          setPeriodosQueda(cfg.periodosQueda ?? 2);
          setQuedaMinimaAlertaRs(cfg.quedaMinimaAlertaRs ?? 3000);
          setTopNProdutos(cfg.topNProdutos ?? '');
          setReducaoMinimaErosao(cfg.reducaoMinimaErosao ?? 50);
          setQuedaMinimaErosaoRs(cfg.quedaMinimaErosaoRs ?? 3000);
          setReducaoMinimaSemVenda(cfg.reducaoMinimaSemVenda ?? 90);
          setTopNPoderCompra(cfg.topNPoderCompra ?? '');
          setExcluirPeriodoAtual(cfg.excluirPeriodoAtual ?? true);
          setErosaoSomenteProdutosEmAlerta(cfg.erosaoSomenteProdutosEmAlerta ?? false);
          setGranularidade(cfg.granularidade ?? 'Mensal');
        }
      } catch (e) {
        if (!cancelado) {
          setFeedbackTags({
            tipo: 'erro',
            texto: e instanceof Error ? e.message : 'Falha ao carregar dados do Analisador.',
          });
        }
      }
    })();
    return () => { cancelado = true; };
  }, [empresa]);

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
    setFeedbackDados(null);
    setSalvando(true);
    try {
      await persistirCaminhos();
      setFeedbackDados({ tipo: 'ok', texto: 'Caminhos salvos.' });
    } catch (e) {
      setFeedbackDados({ tipo: 'erro', texto: e instanceof Error ? e.message : 'Falha ao salvar os caminhos.' });
    } finally {
      setSalvando(false);
    }
  };

  const sincronizar = async () => {
    setFeedbackDados(null);
    setSincronizando(true);
    try {
      if (caminhoFonte.trim() || caminhoTrabalho.trim()) {
        await persistirCaminhos();
      }
      const lista = await listarEmpresasDashboard();
      setEmpresas(lista);
      if (lista.length === 0) {
        setFeedbackDados({ tipo: 'erro', texto: 'Nenhuma empresa com Dados Mais Atacado.xlsx encontrado na pasta fonte.' });
      } else {
        setFeedbackDados({ tipo: 'ok', texto: `${lista.length} empresa(s) sincronizada(s).` });
      }
    } catch (e) {
      setFeedbackDados({ tipo: 'erro', texto: e instanceof Error ? e.message : 'Falha ao sincronizar empresas.' });
    } finally {
      setSincronizando(false);
    }
  };

  const regenerarBase = async () => {
    if (!empresa) {
      setFeedbackDados({ tipo: 'erro', texto: 'Selecione uma empresa na sidebar antes de regenerar a base.' });
      return;
    }
    setFeedbackDados(null);
    setRegenerando(true);
    try {
      if (caminhoFonte.trim() || caminhoTrabalho.trim()) {
        await persistirCaminhos();
      }
      await regenerarBaseEmpresa(empresa, false);
      // O Dashboard mantém o summary em memória durante a sessão — sem isto
      // ele mostraria os números antigos ao voltar.
      invalidarSummary(empresa);
      setFeedbackDados({ tipo: 'ok', texto: `Base de ${empresa} regenerada. Abra o Dashboard para ver os dados.` });
    } catch (e) {
      setFeedbackDados({ tipo: 'erro', texto: e instanceof Error ? e.message : 'Falha ao regenerar a base.' });
    } finally {
      setRegenerando(false);
    }
  };

  const escolherPastaNavegada = (caminho: string) => {
    if (buscando === 'fonte') {
      setCaminhoFonte(caminho);
      gravarLocal(LS_CAMINHO_FONTE, caminho);
    } else if (buscando === 'trabalho') {
      setCaminhoTrabalho(caminho);
      gravarLocal(LS_CAMINHO_TRABALHO, caminho);
    } else if (buscando === 'atualizacoes') {
      setCaminhoAtualizacoes(caminho);
    }
    setBuscando(null);
  };

  const aplicar = async () => {
    setAplicandoAtualizacao(true);
    setFeedbackAtualizacao(null);
    try {
      const { mensagem } = await aplicarAtualizacao();
      setFeedbackAtualizacao({ tipo: 'ok', texto: mensagem });
      // O backend se encerra logo após responder, então daqui para frente não há
      // mais nada a fazer nesta aba: o atualizador religa o app e o usuário
      // recarrega. Deixar o botão travado evita um segundo clique inútil.
    } catch (erro) {
      setFeedbackAtualizacao({ tipo: 'erro', texto: (erro as Error).message });
      setAplicandoAtualizacao(false);
    }
  };

  /** Salva o canal e já consulta, para o usuário ver o resultado num clique. */
  const salvarCanalEVerificar = async () => {
    setVerificandoAtualizacao(true);
    setFeedbackAtualizacao(null);
    try {
      const salvo = await definirCaminhoAtualizacoes(caminhoAtualizacoes);
      setCaminhoAtualizacoes(salvo);
      setStatusAtualizacao(await obterStatusAtualizacao());
    } catch (erro) {
      setStatusAtualizacao(null);
      setFeedbackAtualizacao({ tipo: 'erro', texto: (erro as Error).message });
    } finally {
      setVerificandoAtualizacao(false);
    }
  };

  const ocupado = sincronizando || salvando || regenerando;
  const analisePronta = Boolean(empresa);

  const atualizarTag = (id: string, patch: Partial<TagCatalogoItem>) => {
    setTagsCatalogo((lista) => lista.map((item) => (item.id === id ? { ...item, ...patch } : item)));
  };

  const removerTag = (id: string) => {
    if (id === 'alerta') return;
    setTagsCatalogo((lista) => lista.filter((item) => item.id !== id));
    setEditandoTagId((atual) => (atual === id ? null : atual));
  };

  const adicionarTag = () => {
    const rotulo = novoTagNome.trim() || 'Nova tag';
    const ids = new Set(tagsCatalogo.map((item) => item.id));
    setTagsCatalogo((lista) => [
      ...lista,
      { id: novoIdTag(rotulo, ids), rotulo, ativa: true, cor: '#64748b' },
    ]);
    setNovoTagNome('');
  };

  const salvarTags = async () => {
    if (!empresa) return;
    setFeedbackTags(null);
    setSalvandoTags(true);
    try {
      const dados = await salvarCatalogoTags(empresa, tagsCatalogo, null);
      setTagsCatalogo(dados.catalogo ?? tagsCatalogo);
      setFeedbackTags({ tipo: 'ok', texto: 'Catálogo de tags salvo.' });
    } catch (e) {
      setFeedbackTags({ tipo: 'erro', texto: e instanceof Error ? e.message : 'Falha ao salvar tags.' });
    } finally {
      setSalvandoTags(false);
    }
  };

  const salvarParams = async () => {
    if (!empresa) return;
    setFeedbackParams(null);
    setSalvandoParams(true);
    try {
      const base = configBase ?? (await tentarCarregarConfiguracaoEmpresa(empresa, null)) ?? {};
      const dados: ConfigEmpresaSalva = {
        ...base,
        periodosQueda,
        quedaMinimaAlertaRs,
        topNProdutos,
        reducaoMinimaErosao,
        quedaMinimaErosaoRs,
        reducaoMinimaSemVenda,
        topNPoderCompra,
        excluirPeriodoAtual,
        erosaoSomenteProdutosEmAlerta,
        granularidade,
      };
      await salvarConfiguracaoEmpresa(empresa, dados, null);
      setConfigBase(dados);
      setFeedbackParams({ tipo: 'ok', texto: 'Parâmetros de análise salvos.' });
    } catch (e) {
      setFeedbackParams({ tipo: 'erro', texto: e instanceof Error ? e.message : 'Falha ao salvar parâmetros.' });
    } finally {
      setSalvandoParams(false);
    }
  };

  return (
    <AppShell>
      <div className="dashboard-container config-page">
        <header className="app-page-header">
          <div>
            <h1>Configurações</h1>
            <p className="app-page-header-sub">
              Dados do sistema, tags de clientes e parâmetros do Analisador — tudo numa tela.
            </p>
          </div>
        </header>

        <div className="config-page-stack">
          {/* ——— Setor 1: Dados ——— */}
          <section className="glass-card glass-card-flat config-page-card" aria-labelledby="setor-dados">
            <h2 id="setor-dados" className="config-page-card-titulo">Dados do sistema</h2>
            <p className="config-page-card-desc">
              Pastas fonte/trabalho, sincronização de empresas e atualização do dashboard.
            </p>

            <label className="analisador-campo">
              <span>Pasta fonte (somente leitura)</span>
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
                  onClick={() => setBuscando('fonte')}
                  disabled={ocupado}
                  aria-label="Buscar pasta fonte"
                >
                  <FolderOpen size={14} />
                  Buscar
                </button>
              </div>
            </label>
            <p className="analisador-hint">
              Selecione a pasta raiz que contém as empresas. Cada empresa deve ter diretamente o arquivo Dados Mais Atacado.xlsx. O app nunca altera esta pasta.
            </p>

            <label className="analisador-campo">
              <span>Pasta de trabalho (summary / config)</span>
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
                  onClick={() => setBuscando('trabalho')}
                  disabled={ocupado}
                  aria-label="Buscar pasta de trabalho"
                >
                  <FolderOpen size={14} />
                  Buscar
                </button>
              </div>
            </label>
            <p className="analisador-hint">
              Onde o app grava summary, config.json e caches. Deve ser distinta da fonte.
            </p>

            <label className="analisador-check-linha">
              <input
                type="checkbox"
                checked={aguardandoBaseDados}
                onChange={(e) => void alternarAguardandoBaseDados(e.target.checked)}
                disabled={salvandoFlag}
              />
              Aguardando montagem da base de dados (mostra aviso no Dashboard público)
            </label>

            {feedbackDados && (
              <p
                className="config-page-feedback"
                style={{ color: feedbackDados.tipo === 'erro' ? '#f43f5e' : '#34d399' }}
                role={feedbackDados.tipo === 'erro' ? 'alert' : 'status'}
              >
                {feedbackDados.texto}
              </p>
            )}

            <div className="config-page-card-acoes">
              <button type="button" className="analisador-btn analisador-btn-sec" onClick={() => void salvarCaminhos()} disabled={ocupado}>
                {salvando ? <Loader2 size={14} className="dashboard-filter-spinner" /> : <Save size={14} />}
                Salvar caminhos
              </button>
              <button type="button" className="analisador-btn analisador-btn-sec" onClick={() => void sincronizar()} disabled={ocupado}>
                {sincronizando ? <Loader2 size={14} className="dashboard-filter-spinner" /> : <RefreshCw size={14} />}
                Sincronizar
              </button>
              <button
                type="button"
                className="analisador-btn analisador-btn-pri"
                onClick={() => void regenerarBase()}
                disabled={ocupado || !empresa}
              >
                {regenerando ? <Loader2 size={14} className="dashboard-filter-spinner" /> : <RefreshCw size={14} />}
                Regenerar base
              </button>
            </div>
          </section>

          {/* ——— Setor 2: Atualizações ——— */}
          <section className="glass-card glass-card-flat config-page-card" aria-labelledby="setor-atualizacoes">
            <h2 id="setor-atualizacoes" className="config-page-card-titulo">Atualizações</h2>
            <p className="config-page-card-desc">
              Pasta compartilhada de onde o Prisma lê as novas versões publicadas.
            </p>

            <label className="analisador-campo">
              <span>Canal de atualização (somente leitura)</span>
              <div className="caminho-pasta-row">
                <input
                  className="analisador-input"
                  value={caminhoAtualizacoes}
                  onChange={(e) => setCaminhoAtualizacoes(e.target.value)}
                  placeholder="Ex.: C:\...\OneDrive - Empresa\Prisma\atualizacoes"
                />
                <button
                  type="button"
                  className="analisador-btn analisador-btn-sec caminho-pasta-btn"
                  onClick={() => setBuscando('atualizacoes')}
                  disabled={verificandoAtualizacao}
                  aria-label="Buscar pasta do canal de atualização"
                >
                  <FolderOpen size={14} />
                  Buscar
                </button>
              </div>
            </label>
            <p className="analisador-hint">
              A pasta precisa ter o version.json e o pacote da versão. Deixe em branco para
              desligar a verificação de atualizações.
            </p>

            {statusAtualizacao && (
              <p
                className="config-page-atualizacao-status"
                role="status"
                data-disponivel={statusAtualizacao.atualizavel ? 'sim' : 'nao'}
              >
                {statusAtualizacao.motivo}
                {statusAtualizacao.atualizavel && statusAtualizacao.notas
                  ? ` — ${statusAtualizacao.notas}`
                  : ''}
              </p>
            )}

            {feedbackAtualizacao && (
              <p
                className="config-page-feedback"
                style={{ color: feedbackAtualizacao.tipo === 'erro' ? '#f43f5e' : '#34d399' }}
                role={feedbackAtualizacao.tipo === 'erro' ? 'alert' : 'status'}
              >
                {feedbackAtualizacao.texto}
              </p>
            )}

            <div className="config-page-card-acoes">
              <button
                type="button"
                className="analisador-btn analisador-btn-sec"
                onClick={() => void salvarCanalEVerificar()}
                disabled={verificandoAtualizacao}
              >
                {verificandoAtualizacao
                  ? <Loader2 size={14} className="dashboard-filter-spinner" />
                  : <RefreshCw size={14} />}
                Salvar e verificar
              </button>
              {statusAtualizacao?.atualizavel && (
                <button
                  type="button"
                  className="analisador-btn analisador-btn-pri"
                  onClick={() => void aplicar()}
                  disabled={verificandoAtualizacao || aplicandoAtualizacao}
                >
                  {aplicandoAtualizacao
                    ? <Loader2 size={14} className="dashboard-filter-spinner" />
                    : <Download size={14} />}
                  Atualizar para {statusAtualizacao.versao_disponivel}
                </button>
              )}
            </div>
          </section>

          {/* ——— Setor 3: Tags ——— */}
          <section className="glass-card glass-card-flat config-page-card config-tipos-card" aria-labelledby="setor-tags">
            <div className="config-tipos-head">
              <h2 id="setor-tags" className="config-page-card-titulo">Tags de clientes</h2>
              {empresa ? (
                <span className="config-tipos-count">{tagsCatalogo.length}</span>
              ) : null}
            </div>
            <p className="config-page-card-desc">
              Catálogo de tags da prévia de clientes{empresa ? ` — ${empresa}` : ''}.
            </p>

            {!empresa ? (
              <p className="analisador-hint">Selecione uma empresa na sidebar.</p>
            ) : (
              <>
                {tagsCatalogo.length === 0 ? (
                  <p className="analisador-hint">Nenhuma tag cadastrada.</p>
                ) : (
                  <ul className="config-tipos-lista">
                    {tagsCatalogo.map((tag) => {
                      const editando = editandoTagId === tag.id;
                      return (
                        <li key={tag.id} className={`config-tipos-item${editando ? ' is-editando' : ''}`}>
                          {editando ? (
                            <input
                              type="color"
                              className="config-tipos-cor"
                              value={tag.cor}
                              onChange={(e) => atualizarTag(tag.id, { cor: e.target.value })}
                              aria-label={`Cor da tag ${tag.rotulo}`}
                            />
                          ) : (
                            <span
                              className="config-tipos-swatch"
                              style={{ background: tag.cor }}
                              title={tag.cor}
                              aria-hidden
                            />
                          )}
                          {editando ? (
                            <div className="config-tipos-edit-fields">
                              <input
                                className="config-tipos-input-edit"
                                value={tag.rotulo}
                                onChange={(e) => atualizarTag(tag.id, { rotulo: e.target.value })}
                                placeholder="Nome da tag"
                                aria-label={`Nome da tag ${tag.id}`}
                              />
                              <label className="analisador-check-linha config-tipos-check">
                                <input
                                  type="checkbox"
                                  checked={tag.ativa}
                                  onChange={(e) => atualizarTag(tag.id, { ativa: e.target.checked })}
                                />
                                Ativa
                              </label>
                            </div>
                          ) : (
                            <span className="config-tipos-label">{tag.rotulo}</span>
                          )}
                          <div className="config-tipos-acoes">
                            <button
                              type="button"
                              className={`config-tipos-btn-edit${editando ? ' is-ativo' : ''}`}
                              onClick={() => setEditandoTagId(editando ? null : tag.id)}
                              aria-label={editando ? 'Fechar edição' : 'Editar'}
                              aria-pressed={editando}
                            >
                              <Pencil size={14} />
                            </button>
                            <button
                              type="button"
                              className="config-tipos-btn-del"
                              onClick={() => removerTag(tag.id)}
                              disabled={tag.id === 'alerta'}
                              title={tag.id === 'alerta' ? 'Tag base — não pode ser excluída' : 'Excluir'}
                              aria-label="Remover"
                            >
                              <Trash2 size={14} />
                            </button>
                          </div>
                        </li>
                      );
                    })}
                  </ul>
                )}
                <form
                  className="config-tipos-add"
                  onSubmit={(e) => {
                    e.preventDefault();
                    adicionarTag();
                  }}
                >
                  <input
                    className="config-tipos-add-input"
                    value={novoTagNome}
                    onChange={(e) => setNovoTagNome(e.target.value)}
                    placeholder="Adicionar..."
                    aria-label="Nome da nova tag"
                  />
                  <button type="submit" className="config-tipos-btn-add" aria-label="Adicionar tag">
                    <Plus size={18} />
                  </button>
                </form>
                {feedbackTags && (
                  <p
                    className="config-page-feedback"
                    style={{ color: feedbackTags.tipo === 'erro' ? '#f43f5e' : '#34d399' }}
                  >
                    {feedbackTags.texto}
                  </p>
                )}
                <div className="config-page-card-acoes">
                  <button
                    type="button"
                    className="analisador-btn analisador-btn-pri"
                    onClick={() => void salvarTags()}
                    disabled={salvandoTags}
                  >
                    {salvandoTags ? <Loader2 size={14} className="dashboard-filter-spinner" /> : <Save size={14} />}
                    Salvar tags
                  </button>
                </div>
              </>
            )}
          </section>

          {/* ——— Setor 3: Parâmetros (separados por relatório) ——— */}
          <section className="glass-card glass-card-flat config-page-card" aria-labelledby="setor-params">
            <h2 id="setor-params" className="config-page-card-titulo">Parâmetros de análise</h2>
            <p className="config-page-card-desc">
              Regras do Analisador gravadas no config.json{empresa ? ` de ${empresa}` : ''} — agrupadas por relatório.
            </p>

            {!analisePronta ? (
              <div className="config-page-setor-bloqueado">
                <p className="analisador-hint">Selecione uma empresa na sidebar.</p>
              </div>
            ) : (
              <>
                <div className="config-params-por-relatorio">
                  <section className="config-modal-secao">
                    <h3>Análise geral</h3>
                    <div className="analisador-grid-campos analisador-grid-campos-2">
                      <label className="analisador-campo">
                        <span>Granularidade</span>
                        <select
                          className="custom-select analisador-select"
                          value={granularidade}
                          onChange={(e) => setGranularidade(e.target.value)}
                        >
                          {['Mensal', 'Trimestral', 'Semestral', 'Anual'].map((g) => (
                            <option key={g} value={g}>{g}</option>
                          ))}
                        </select>
                      </label>
                    </div>
                    <label className="analisador-check-linha">
                      <input
                        type="checkbox"
                        checked={excluirPeriodoAtual}
                        onChange={(e) => setExcluirPeriodoAtual(e.target.checked)}
                      />
                      Excluir período atual (incompleto)
                    </label>
                  </section>

                  <section className="config-modal-secao">
                    <h3>Alertas de Queda Consecutiva</h3>
                    <label className="config-modal-campo-linha">
                      <span>Períodos mínimos seguidos em queda</span>
                      <NumberStepper value={periodosQueda} onChange={(v) => setPeriodosQueda(v === '' ? 2 : v)} />
                    </label>
                    <label className="config-modal-campo-linha">
                      <span>Queda mínima em R$ p/ alerta</span>
                      <NumberStepper value={quedaMinimaAlertaRs} onChange={setQuedaMinimaAlertaRs} placeholder="0 = sem piso" />
                    </label>
                    <label className="config-modal-campo-linha">
                      <span>Produtos a exibir (top N por tendência)</span>
                      <NumberStepper value={topNProdutos} onChange={setTopNProdutos} placeholder="Vazio = todos" />
                    </label>
                    <p className="analisador-hint">
                      Vale para &quot;Alertas de Queda Consecutiva&quot; (usa a mesma tendência interna do gráfico &quot;Evolução no Tempo&quot;)
                      e também limita &quot;Venda por Produto&quot; e &quot;Venda por Fabricante&quot;, que seguem o mesmo
                      recorte de período do resto do relatório (vazio = top 20).
                    </p>
                  </section>

                  <section className="config-modal-secao">
                    <h3>Erosão de Clientes</h3>
                    <label className="config-modal-campo-linha">
                      <span>Redução mínima p/ erosão (%)</span>
                      <NumberStepper value={reducaoMinimaErosao} onChange={(v) => setReducaoMinimaErosao(v === '' ? 50 : v)} />
                    </label>
                    <label className="config-modal-campo-linha">
                      <span>Queda mínima em R$ p/ erosão</span>
                      <NumberStepper value={quedaMinimaErosaoRs} onChange={setQuedaMinimaErosaoRs} placeholder="0 = sem piso" />
                    </label>
                    <label className="analisador-check-linha">
                      <input
                        type="checkbox"
                        checked={erosaoSomenteProdutosEmAlerta}
                        onChange={(e) => setErosaoSomenteProdutosEmAlerta(e.target.checked)}
                      />
                      Limitar erosão e churn aos produtos com alerta de queda
                    </label>
                    <p className="analisador-hint">
                      Vale para &quot;Erosão de Clientes por Produto&quot;, &quot;Correlação Produto x Cliente&quot; e
                      &quot;Impacto Financeiro do Churn&quot;. Desmarcado (padrão), o risco é calculado sobre a base
                      inteira e fica comparável entre períodos. Marcado, o escopo cai só para os produtos que
                      entraram nos alertas de queda — e passa a depender do &quot;top N por tendência&quot;.
                    </p>
                  </section>

                  <section className="config-modal-secao">
                    <h3>Sem Venda</h3>
                    <label className="config-modal-campo-linha">
                      <span>Redução mínima p/ Sem Venda (%)</span>
                      <NumberStepper value={reducaoMinimaSemVenda} onChange={(v) => setReducaoMinimaSemVenda(v === '' ? 90 : v)} />
                    </label>
                    <p className="analisador-hint">
                      Sem piso de R$ de propósito — pega também clientes de baixo volume.
                    </p>
                  </section>

                  <section className="config-modal-secao">
                    <h3>Poder de Compra por Cliente (3 maiores meses)</h3>
                    <label className="config-modal-campo-linha">
                      <span>Máximo de clientes a exibir</span>
                      <NumberStepper value={topNPoderCompra} onChange={setTopNPoderCompra} placeholder="Vazio = todos" />
                    </label>
                    <p className="analisador-hint">
                      Maior Poder de Compra primeiro. Vazio = todos os clientes.
                    </p>
                  </section>
                </div>

                {feedbackParams && (
                  <p
                    className="config-page-feedback"
                    style={{ color: feedbackParams.tipo === 'erro' ? '#f43f5e' : '#34d399' }}
                  >
                    {feedbackParams.texto}
                  </p>
                )}
                <div className="config-page-card-acoes">
                  <button
                    type="button"
                    className="analisador-btn analisador-btn-pri"
                    onClick={() => void salvarParams()}
                    disabled={salvandoParams}
                  >
                    {salvandoParams ? <Loader2 size={14} className="dashboard-filter-spinner" /> : <Save size={14} />}
                    Salvar parâmetros
                  </button>
                </div>
              </>
            )}
          </section>
        </div>
        {versao && <footer className="config-page-versao">Prisma v{versao}</footer>}
      </div>
      <PastaPickerModal
        aberto={buscando !== null}
        titulo={buscando === 'fonte' ? 'Selecionar pasta fonte' : 'Selecionar pasta de trabalho'}
        caminhoInicial={buscando === 'fonte' ? caminhoFonte : caminhoTrabalho}
        onCancelar={() => setBuscando(null)}
        onEscolher={escolherPastaNavegada}
      />
    </AppShell>
  );
}
