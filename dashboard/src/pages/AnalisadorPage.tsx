import { useEffect, useMemo, useRef, useState } from 'react';
import { AppShell } from '../components/AppShell';
import { Download, FolderOpen, Save } from 'lucide-react';
import {
  analisar,
  exportarRelatorio,
  type FormatoExportacao,
  listarEmpresas,
  obterBase,
  obterCaminhoTrabalho,
  obterCatalogo,
  obterPreviaGrupos,
  obterPreviaProdutos,
  obterTagsClientes,
  salvarConfiguracaoEmpresa,
  salvarGruposManuais,
  salvarTagsUmCliente,
  tentarCarregarConfiguracaoEmpresa,
  TAGS_CATALOGO_PADRAO,
  type CategoriaCatalogo,
  type ConfigEmpresaSalva,
  type Grupo,
  type GrupoManualClientes,
  type ItemClientePrevia,
  type ItemProdutoPrevia,
  type ParametrosAnalise,
  type PreviaBase,
  type ResultadoAnalise,
  type TagCatalogoItem,
  type TagCliente,
} from '../api/client';
import { PreviaClientesTable } from '../components/analisador/PreviaClientesTable';
import { PreviaProdutosTable } from '../components/analisador/PreviaProdutosTable';
import { NumberStepper } from '../components/analisador/NumberStepper';
import { ResultTable } from '../components/analisador/ResultTable';
import { ExportarModal } from '../components/analisador/ExportarModal';
import { ExplorarBuilder } from '../components/analisador/ExplorarBuilder';
import { ClientesGruposPanel } from '../components/analisador/ClientesGruposPanel';
import { AnalisadorCombobox } from '../components/analisador/AnalisadorCombobox';
import { slugId } from '../utils/slug';
import { rotuloGrupoCurto } from '../utils/formatters';

type Etapa = 'carregando-base' | 'config' | 'resultados';
type AbaWorkspace = 'relatorios' | 'graficos' | 'tabelas' | 'clientes';

const ABAS_WORKSPACE: { id: AbaWorkspace; rotulo: string }[] = [
  { id: 'relatorios', rotulo: 'Relatórios' },
  { id: 'graficos', rotulo: 'Gráficos' },
  { id: 'tabelas', rotulo: 'Tabelas' },
  { id: 'clientes', rotulo: 'Clientes' },
];

type OverridePrevia = {
  clientesExcluidos: string[];
  cortes: [number, number, number];
  balcao: boolean;
  produtosExcluidos: string[];
  corte: number;
  maxPorGrupo: number;
};

const CORTES_CLIENTES_PADRAO: [number, number, number] = [30, 50, 60];
const CORTE_PRODUTOS_PADRAO = 80;
const MAX_POR_GRUPO_PADRAO = 20;

function chaveStorageLoja(empresa: string): string {
  return `analisador_loja_${empresa}`;
}

function lerLojaSalva(empresa: string): string {
  if (!empresa) return '';
  return localStorage.getItem(chaveStorageLoja(empresa)) || '';
}

function persistirLoja(empresa: string, loja: string): void {
  if (!empresa) return;
  if (loja) localStorage.setItem(chaveStorageLoja(empresa), loja);
  else localStorage.removeItem(chaveStorageLoja(empresa));
}

function resumirRegrasConfig(dados: ConfigEmpresaSalva): string[] {
  const cortes = dados.cortesClientes ?? CORTES_CLIENTES_PADRAO;
  const linhas = [
    `Cortes de clientes: ${cortes.join(' / ')}%`,
    `Corte de produtos (alto giro): ${dados.corteProdutos ?? CORTE_PRODUTOS_PADRAO}%`,
    `Máx. por grupo (sugerir): ${dados.maxPorGrupo ?? MAX_POR_GRUPO_PADRAO}`,
    `Granularidade: ${dados.granularidade ?? 'Mensal'}`,
    `Períodos de queda: ${dados.periodosQueda ?? 2}`,
    `Desconsiderar balcão: ${dados.desconsiderarBalcao ? 'sim' : 'não'}`,
    `Desconsiderar demais produtos: ${dados.desconsiderarDemaisProdutos ? 'sim' : 'não'}`,
    `Desconsiderar não harmonizados: ${dados.desconsiderarNaoHarmonizados ? 'sim' : 'não'}`,
    `Clientes excluídos: ${(dados.clientesExcluidos ?? []).length}`,
    `Produtos excluídos: ${(dados.produtosExcluidos ?? []).length}`,
    `Relatórios marcados: ${(dados.chavesSelecionadas ?? []).length}`,
  ];
  return linhas;
}

export default function AnalisadorPage() {
  const [etapa, setEtapa] = useState<Etapa>('carregando-base');
  const [erro, setErro] = useState<string | null>(null);
  const [sucesso, setSucesso] = useState<string | null>(null);
  const [salvandoConfig, setSalvandoConfig] = useState(false);
  const [carregando, setCarregando] = useState(false);

  const [previa, setPrevia] = useState<PreviaBase | null>(null);
  const [catalogo, setCatalogo] = useState<CategoriaCatalogo[]>([]);
  const [resultados, setResultados] = useState<ResultadoAnalise | null>(null);
  // Identifica o resultado mantido temporariamente no backend para exportação
  // sem repetir todos os agrupamentos e análises pesadas.
  const [resultadoId, setResultadoId] = useState<string | null>(null);
  const [abaAtiva, setAbaAtiva] = useState<string | null>(null);
  const [formatoParaConfirmar, setFormatoParaConfirmar] = useState<FormatoExportacao | null>(null);

  const [clientesExcluidos, setClientesExcluidos] = useState<Set<string>>(new Set());
  const [produtosExcluidos, setProdutosExcluidos] = useState<Set<string>>(new Set());
  const [granularidade, setGranularidade] = useState('Mensal');
  const [chavesSelecionadas, setChavesSelecionadas] = useState<Set<string>>(new Set());
  const [cortesClientes, setCortesClientes] = useState<[number, number, number]>([30, 50, 60]);
  const [corteProdutos, setCorteProdutos] = useState(80);
  const [periodosQueda, setPeriodosQueda] = useState(2);
  const [desconsiderarBalcao, setDesconsiderarBalcao] = useState(false);
  const [desconsiderarDemaisProdutos, setDesconsiderarDemaisProdutos] = useState(false);
  const [desconsiderarNaoHarmonizados, setDesconsiderarNaoHarmonizados] = useState(false);
  const [excluirPeriodoAtual, setExcluirPeriodoAtual] = useState(true);
  const [erosaoSomenteProdutosEmAlerta, setErosaoSomenteProdutosEmAlerta] = useState(false);
  const [nomeEmpresaManual, setNomeEmpresaManual] = useState('');
  const [topNProdutos, setTopNProdutos] = useState<number | ''>('');
  const [reducaoMinimaErosao, setReducaoMinimaErosao] = useState(50);
  const [quedaMinimaAlertaRs, setQuedaMinimaAlertaRs] = useState<number | ''>(3000);
  const [quedaMinimaErosaoRs, setQuedaMinimaErosaoRs] = useState<number | ''>(3000);
  const [reducaoMinimaSemVenda, setReducaoMinimaSemVenda] = useState(90);
  const [topNPoderCompra, setTopNPoderCompra] = useState<number | ''>('');

  const [maxPorGrupo, setMaxPorGrupo] = useState(20);
  const [grupos, setGrupos] = useState<Grupo[] | null>(null);
  const [itensClientes, setItensClientes] = useState<ItemClientePrevia[]>([]);
  const [tagsPorCliente, setTagsPorCliente] = useState<Record<string, TagCliente[]>>({});
  const [tagsCatalogo, setTagsCatalogo] = useState<TagCatalogoItem[]>(TAGS_CATALOGO_PADRAO);
  const [gruposManuais, setGruposManuais] = useState<GrupoManualClientes[]>([]);
  const [carregandoGrupos, setCarregandoGrupos] = useState(false);
  const [produtosGrupos, setProdutosGrupos] = useState<Grupo[] | null>(null);
  const [itensProdutos, setItensProdutos] = useState<ItemProdutoPrevia[]>([]);
  const [produtosDemaisCompletos, setProdutosDemaisCompletos] = useState<string[]>([]);
  const [produtosNaoHarmCompletos, setProdutosNaoHarmCompletos] = useState<string[]>([]);
  const [carregandoProdutos, setCarregandoProdutos] = useState(false);

  const [abaWorkspace, setAbaWorkspace] = useState<AbaWorkspace>('relatorios');
  const [salvandoGrupos, setSalvandoGrupos] = useState(false);
  const [clientesBalcao, setClientesBalcao] = useState<string[]>([]);
  /** Serializa saves de grupos (painel + modal) para não sobrescrever no disco. */
  const gruposSaveChainRef = useRef(Promise.resolve());
  const gruposManuaisRef = useRef(gruposManuais);
  gruposManuaisRef.current = gruposManuais;
  /** Invalida cargas async antigas ao trocar empresa/loja rapidamente. */
  const cargaSeqRef = useRef(0);
  /** Debounce da prévia após saves de grupos (último empresa/loja vence). */
  const gruposPreviaDebounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const gruposPreviaCtxRef = useRef<{ empresa: string; loja: string | null } | null>(null);

  const [empresas, setEmpresas] = useState<string[]>([]);
  const [empresaSelecionada, setEmpresaSelecionada] = useState(
    () => localStorage.getItem('alvo_empresa') || '',
  );
  /** '' = Todas as lojas; demais = nome da loja (escopo de config/tags). */
  const [lojaSelecionada, setLojaSelecionada] = useState(
    () => lerLojaSalva(localStorage.getItem('alvo_empresa') || ''),
  );

  const [caminhoTrabalho, setCaminhoTrabalho] = useState<string | null>(null);
  const [configPendente, setConfigPendente] = useState<{
    empresa: string;
    dados: ConfigEmpresaSalva;
    loja?: string | null;
  } | null>(null);

  const nomeEmpresaEfetivo = empresaSelecionada || nomeEmpresaManual.trim();
  const empresaBase = empresaSelecionada || null;
  /** null/omitido nas APIs = todas as lojas. */
  const lojaApi = lojaSelecionada || null;
  const lojasDisponiveis = previa?.lojas ?? [];
  const mostrarSeletorLoja = lojasDisponiveis.length > 1;
  const rotuloEscopoLoja = lojaSelecionada || 'Todas as lojas';

  useEffect(() => {
    obterCatalogo()
      .then(setCatalogo)
      .catch((e) => setErro(e instanceof Error ? e.message : 'Falha ao carregar catálogo.'));
    listarEmpresas().then(setEmpresas).catch(() => {});
    Promise.all([obterCaminhoTrabalho(true)])
      .then(([trabalho]) => {
        setCaminhoTrabalho(trabalho);
      })
      .catch(() => {});
  }, []);

  // Recarrega o catálogo ao entrar na aba Relatórios (pega categorias novas sem F5).
  useEffect(() => {
    if (abaWorkspace !== 'relatorios') return;
    obterCatalogo()
      .then(setCatalogo)
      .catch(() => {});
  }, [abaWorkspace]);

  useEffect(() => {
    return () => {
      if (gruposPreviaDebounceRef.current !== null) {
        clearTimeout(gruposPreviaDebounceRef.current);
        gruposPreviaDebounceRef.current = null;
      }
    };
  }, []);

  const aplicarDadosConfig = (dados: ConfigEmpresaSalva): OverridePrevia => {
    const cortes = (dados.cortesClientes ?? CORTES_CLIENTES_PADRAO) as [number, number, number];
    const corte = dados.corteProdutos ?? CORTE_PRODUTOS_PADRAO;
    const maxG = dados.maxPorGrupo ?? MAX_POR_GRUPO_PADRAO;
    const clientes = dados.clientesExcluidos ?? [];
    const produtos = dados.produtosExcluidos ?? [];
    const balcao = Boolean(dados.desconsiderarBalcao);

    setCortesClientes(cortes);
    setCorteProdutos(corte);
    setPeriodosQueda(dados.periodosQueda ?? 2);
    setDesconsiderarBalcao(balcao);
    setDesconsiderarDemaisProdutos(Boolean(dados.desconsiderarDemaisProdutos));
    setDesconsiderarNaoHarmonizados(Boolean(dados.desconsiderarNaoHarmonizados));
    setExcluirPeriodoAtual(dados.excluirPeriodoAtual ?? true);
    setErosaoSomenteProdutosEmAlerta(dados.erosaoSomenteProdutosEmAlerta ?? false);
    setTopNProdutos(dados.topNProdutos ?? '');
    setReducaoMinimaErosao(dados.reducaoMinimaErosao ?? 50);
    setQuedaMinimaAlertaRs(dados.quedaMinimaAlertaRs ?? 3000);
    setQuedaMinimaErosaoRs(dados.quedaMinimaErosaoRs ?? 3000);
    setReducaoMinimaSemVenda(dados.reducaoMinimaSemVenda ?? 90);
    setTopNPoderCompra(dados.topNPoderCompra ?? '');
    setMaxPorGrupo(maxG);
    setClientesExcluidos(new Set(clientes));
    setProdutosExcluidos(new Set(produtos));
    setChavesSelecionadas(new Set(dados.chavesSelecionadas ?? []));
    setGranularidade(dados.granularidade ?? 'Mensal');

    return {
      clientesExcluidos: clientes,
      cortes,
      balcao,
      produtosExcluidos: produtos,
      corte,
      maxPorGrupo: maxG,
    };
  };

  const resetarParaPadrao = (): OverridePrevia => {
    setCortesClientes(CORTES_CLIENTES_PADRAO);
    setCorteProdutos(CORTE_PRODUTOS_PADRAO);
    setPeriodosQueda(2);
    setDesconsiderarBalcao(false);
    setDesconsiderarDemaisProdutos(false);
    setDesconsiderarNaoHarmonizados(false);
    setExcluirPeriodoAtual(true);
    setTopNProdutos('');
    setReducaoMinimaErosao(50);
    setQuedaMinimaAlertaRs(3000);
    setQuedaMinimaErosaoRs(3000);
    setReducaoMinimaSemVenda(90);
    setTopNPoderCompra('');
    setMaxPorGrupo(MAX_POR_GRUPO_PADRAO);
    setClientesExcluidos(new Set());
    setProdutosExcluidos(new Set());
    // Mantém catálogo / chaves já escolhidas pelo usuário se houver — só limpa exclusões e cortes.
    return {
      clientesExcluidos: [],
      cortes: CORTES_CLIENTES_PADRAO,
      balcao: false,
      produtosExcluidos: [],
      corte: CORTE_PRODUTOS_PADRAO,
      maxPorGrupo: MAX_POR_GRUPO_PADRAO,
    };
  };

  const carregarBaseAtual = async (
    empresa: string | null,
    opcoes?: { ajustarCortes?: boolean; override?: OverridePrevia; loja?: string | null },
  ) => {
    const seq = ++cargaSeqRef.current;
    const ajustarCortes = opcoes?.ajustarCortes ?? true;
    const loja = opcoes?.loja !== undefined ? opcoes.loja : lojaApi;
    setErro(null);
    setEtapa('carregando-base');
    try {
      const resultado = await obterBase(empresa, loja);
      if (seq !== cargaSeqRef.current) return;
      setPrevia(resultado);
      if (loja && resultado.lojas && resultado.lojas.length > 0 && !resultado.lojas.includes(loja)) {
        setLojaSelecionada('');
        if (empresa) persistirLoja(empresa, '');
      }
      if (resultado.granularidades.length > 0) {
        if (opcoes?.ajustarCortes === false) {
          setGranularidade((atual) =>
            resultado.granularidades.includes(atual) ? atual : resultado.granularidades[0],
          );
        } else {
          setGranularidade(resultado.granularidades[0]);
        }
      }
      setEtapa('config');
      if (seq !== cargaSeqRef.current) return;
      await carregarPrevias(empresa, { ajustarCortes, override: opcoes?.override, loja });
      if (seq !== cargaSeqRef.current) return;
    } catch (e) {
      if (seq !== cargaSeqRef.current) return;
      setErro(e instanceof Error ? e.message : 'Falha ao carregar a base de dados.');
      setEtapa('config');
    }
  };

  /** Antes de puxar dados: se há config.json no escopo, pergunta; senão usa o padrão (autoajuste max). */
  const iniciarEmpresa = async (nome: string | null, loja?: string | null) => {
    const seq = ++cargaSeqRef.current;
    setConfigPendente(null);
    const lojaEfetiva = loja !== undefined ? loja : lojaApi;
    if (!nome) {
      setLojaSelecionada('');
      const override = resetarParaPadrao();
      if (seq !== cargaSeqRef.current) return;
      await carregarBaseAtual(null, { ajustarCortes: true, override, loja: null });
      return;
    }
    setEtapa('carregando-base');
    try {
      const dados = await tentarCarregarConfiguracaoEmpresa(nome, lojaEfetiva);
      if (seq !== cargaSeqRef.current) return;
      if (dados) {
        setConfigPendente({ empresa: nome, dados, loja: lojaEfetiva });
        return;
      }
      const override = resetarParaPadrao();
      await carregarBaseAtual(nome, { ajustarCortes: true, override, loja: lojaEfetiva });
    } catch (e) {
      if (seq !== cargaSeqRef.current) return;
      setErro(e instanceof Error ? e.message : 'Falha ao verificar configuração da empresa.');
      const override = resetarParaPadrao();
      await carregarBaseAtual(nome, { ajustarCortes: true, override, loja: lojaEfetiva });
    }
  };

  /** Troca de escopo de loja: aplica config salva do escopo ou padrão, sem modal. */
  const trocarEscopoLoja = async (loja: string | null) => {
    if (!empresaSelecionada) return;
    const seq = ++cargaSeqRef.current;
    setConfigPendente(null);
    setEtapa('carregando-base');
    try {
      const dados = await tentarCarregarConfiguracaoEmpresa(empresaSelecionada, loja);
      if (seq !== cargaSeqRef.current) return;
      if (dados) {
        const override = aplicarDadosConfig(dados);
        await carregarBaseAtual(empresaSelecionada, { ajustarCortes: false, override, loja });
        return;
      }
      const override = resetarParaPadrao();
      await carregarBaseAtual(empresaSelecionada, { ajustarCortes: true, override, loja });
    } catch (e) {
      if (seq !== cargaSeqRef.current) return;
      setErro(e instanceof Error ? e.message : 'Falha ao carregar configuração do escopo de loja.');
      const override = resetarParaPadrao();
      await carregarBaseAtual(empresaSelecionada, { ajustarCortes: true, override, loja });
    }
  };

  const confirmarAplicarConfig = () => {
    if (!configPendente) return;
    const { empresa, dados, loja } = configPendente;
    setConfigPendente(null);
    const override = aplicarDadosConfig(dados);
    void carregarBaseAtual(empresa, { ajustarCortes: false, override, loja: loja ?? lojaApi });
  };

  const recusarConfig = () => {
    if (!configPendente) return;
    const { empresa, loja } = configPendente;
    setConfigPendente(null);
    const override = resetarParaPadrao();
    void carregarBaseAtual(empresa, { ajustarCortes: true, override, loja: loja ?? lojaApi });
  };

  useEffect(() => {
    void iniciarEmpresa(empresaSelecionada || null, lojaSelecionada || null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!configPendente) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') recusarConfig();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [configPendente]);

  const montarParametros = (): ParametrosAnalise => ({
    granularidades: [granularidade],
    chaves_selecionadas: Array.from(chavesSelecionadas),
    clientes_excluidos: Array.from(clientesExcluidos),
    produtos_excluidos: Array.from(produtosExcluidos),
    cortes_clientes: cortesClientes,
    corte_produtos: corteProdutos,
    periodos_queda_consecutiva: periodosQueda,
    desconsiderar_balcao: desconsiderarBalcao,
    excluir_periodo_atual: excluirPeriodoAtual,
    erosao_somente_produtos_em_alerta: erosaoSomenteProdutosEmAlerta,
    top_n_produtos: topNProdutos === '' ? null : topNProdutos,
    reducao_minima_erosao: reducaoMinimaErosao,
    queda_minima_alerta_rs: quedaMinimaAlertaRs === '' ? 0 : quedaMinimaAlertaRs,
    queda_minima_erosao_rs: quedaMinimaErosaoRs === '' ? 0 : quedaMinimaErosaoRs,
    reducao_minima_sem_venda: reducaoMinimaSemVenda,
    top_n_poder_compra: topNPoderCompra === '' ? null : topNPoderCompra,
    nome_empresa: nomeEmpresaEfetivo,
    nome_usuario: '',
    empresa: empresaBase,
    loja: lojaApi,
  });

  const atualizarPreviaGrupos = async (parametros?: {
    clientesExcluidos?: string[];
    cortes?: [number, number, number];
    balcao?: boolean;
    empresa?: string | null;
    loja?: string | null;
    maxPorGrupo?: number;
    ajustarCortes?: boolean;
  }) => {
    setErro(null);
    setCarregandoGrupos(true);
    try {
      const resultado = await obterPreviaGrupos({
        clientes_excluidos: parametros?.clientesExcluidos ?? Array.from(clientesExcluidos),
        cortes_clientes: parametros?.cortes ?? cortesClientes,
        desconsiderar_balcao: parametros?.balcao ?? desconsiderarBalcao,
        max_itens_por_grupo: parametros?.maxPorGrupo ?? maxPorGrupo,
        ajustar_cortes: parametros?.ajustarCortes ?? true,
        empresa: parametros?.empresa !== undefined ? parametros.empresa : empresaBase,
        loja: parametros?.loja !== undefined ? parametros.loja : lojaApi,
      });
      if (Array.isArray(resultado.cortes_clientes) && resultado.cortes_clientes.length === 3) {
        setCortesClientes(resultado.cortes_clientes as [number, number, number]);
      }
      setGrupos(resultado.grupos);
      if (!Array.isArray(resultado.itens)) {
        setItensClientes([]);
        setErro('Backend desatualizado: a prévia não retornou a lista de clientes. Reinicie o uvicorn (porta do proxy em vite.config.ts).');
      } else {
        setItensClientes(resultado.itens);
      }
    } catch (e) {
      setErro(e instanceof Error ? e.message : 'Falha ao carregar prévia dos grupos.');
    } finally {
      setCarregandoGrupos(false);
    }
  };

  const handleAtualizarPreviaGrupos = () => atualizarPreviaGrupos({ ajustarCortes: false });

  const handleSugerirCortes = () => atualizarPreviaGrupos({ ajustarCortes: true });

  const atualizarPreviaProdutos = async (parametros?: {
    produtosExcluidos?: string[];
    corte?: number;
    empresa?: string | null;
    loja?: string | null;
    maxPorGrupo?: number;
    ajustarCortes?: boolean;
  }) => {
    setErro(null);
    setCarregandoProdutos(true);
    try {
      const resultado = await obterPreviaProdutos({
        produtos_excluidos: parametros?.produtosExcluidos ?? Array.from(produtosExcluidos),
        corte_produtos: parametros?.corte ?? corteProdutos,
        max_itens_por_grupo: parametros?.maxPorGrupo ?? maxPorGrupo,
        ajustar_cortes: parametros?.ajustarCortes ?? true,
        empresa: parametros?.empresa !== undefined ? parametros.empresa : empresaBase,
        loja: parametros?.loja !== undefined ? parametros.loja : lojaApi,
      });
      if (typeof resultado.corte_produtos === 'number') {
        setCorteProdutos(resultado.corte_produtos);
      }
      setProdutosGrupos(resultado.grupos);
      setProdutosDemaisCompletos(
        Array.isArray(resultado.produtos_demais) ? resultado.produtos_demais : [],
      );
      setProdutosNaoHarmCompletos(
        Array.isArray(resultado.produtos_nao_harmonizados) ? resultado.produtos_nao_harmonizados : [],
      );
      if (!Array.isArray(resultado.itens)) {
        setItensProdutos([]);
        setErro('Backend desatualizado: a prévia não retornou a lista de produtos. Reinicie o uvicorn (porta do proxy em vite.config.ts).');
      } else {
        setItensProdutos(resultado.itens);
      }
    } catch (e) {
      setErro(e instanceof Error ? e.message : 'Falha ao carregar prévia de produtos.');
    } finally {
      setCarregandoProdutos(false);
    }
  };

  const handleAtualizarPreviaProdutos = () => atualizarPreviaProdutos({ ajustarCortes: false });

  // Ao ligar, exclui de vez (via produtos_excluidos) TODOS os produtos
  // classificados como "Demais" (lista completa do backend, não só a prévia).
  // Ao desligar, devolve exatamente esses mesmos produtos.
  const handleToggleDesconsiderarDemais = async (checked: boolean) => {
    setDesconsiderarDemaisProdutos(checked);
    const produtosDemais = produtosDemaisCompletos;
    const novoSet = new Set(produtosExcluidos);
    produtosDemais.forEach((produto) => {
      if (checked) novoSet.add(produto);
      else novoSet.delete(produto);
    });
    setProdutosExcluidos(novoSet);
    await atualizarPreviaProdutos({
      produtosExcluidos: Array.from(novoSet),
      ajustarCortes: false,
    });
  };

  // Ao ligar, exclui todos os "não harmonizados" (lista completa). Ao desligar, devolve.
  const handleToggleDesconsiderarNaoHarmonizados = async (checked: boolean) => {
    setDesconsiderarNaoHarmonizados(checked);
    const produtosNaoHarmonizados = produtosNaoHarmCompletos;
    const novoSet = new Set(produtosExcluidos);
    produtosNaoHarmonizados.forEach((produto) => {
      if (checked) novoSet.add(produto);
      else novoSet.delete(produto);
    });
    setProdutosExcluidos(novoSet);
    await atualizarPreviaProdutos({
      produtosExcluidos: Array.from(novoSet),
      ajustarCortes: false,
    });
  };

  const carregarTagsClientes = async (empresa: string | null, loja?: string | null) => {
    if (!empresa) {
      setTagsPorCliente({});
      setTagsCatalogo(TAGS_CATALOGO_PADRAO);
      setGruposManuais([]);
      setClientesBalcao([]);
      return;
    }
    try {
      const dados = await obterTagsClientes(empresa, loja !== undefined ? loja : lojaApi);
      setTagsPorCliente(dados.tags ?? {});
      setTagsCatalogo(dados.catalogo ?? TAGS_CATALOGO_PADRAO);
      setGruposManuais(dados.grupos ?? []);
      setClientesBalcao(dados.clientes_balcao ?? []);
    } catch (e) {
      // Não zera gruposManuais: a prévia pode ter aplicado grupos do disco;
      // limpar aqui deixaria o painel Clientes inconsistente com a prévia.
      setErro(e instanceof Error ? e.message : 'Falha ao carregar tags/grupos da empresa.');
    }
  };

  const persistirGruposManuais = (proximos: GrupoManualClientes[]) => {
    if (!empresaBase) {
      return Promise.reject(new Error('Selecione uma empresa.'));
    }
    const empresa = empresaBase;
    const loja = lojaApi;
    const job = gruposSaveChainRef.current.catch(() => undefined).then(async () => {
      const dados = await salvarGruposManuais(empresa, proximos, loja);
      setGruposManuais(dados.grupos ?? proximos);
      // Prévia fora da fila de disco: N saves rápidos → 1 refresh após idle.
      gruposPreviaCtxRef.current = { empresa, loja };
      if (gruposPreviaDebounceRef.current !== null) {
        clearTimeout(gruposPreviaDebounceRef.current);
      }
      gruposPreviaDebounceRef.current = setTimeout(() => {
        gruposPreviaDebounceRef.current = null;
        const ctx = gruposPreviaCtxRef.current;
        gruposPreviaCtxRef.current = null;
        if (!ctx) return;
        void atualizarPreviaGrupos({
          ajustarCortes: false,
          empresa: ctx.empresa,
          loja: ctx.loja,
        });
      }, 450);
      return dados;
    });
    gruposSaveChainRef.current = job.then(
      () => undefined,
      () => undefined,
    );
    return job;
  };

  const handleToggleGrupoManual = async (cliente: string, grupoId: string) => {
    if (!empresaBase) return;
    const atual = gruposManuaisRef.current;
    const proximos = atual.map((g) => ({
      ...g,
      clientes: g.clientes.filter((c) => c !== cliente),
    }));
    const alvo = proximos.find((g) => g.id === grupoId);
    const estavaNoGrupo = atual.some(
      (g) => g.id === grupoId && g.clientes.includes(cliente),
    );
    if (!estavaNoGrupo && alvo) {
      alvo.clientes.push(cliente);
    }
    gruposManuaisRef.current = proximos;
    setGruposManuais(proximos);
    try {
      await persistirGruposManuais(proximos);
    } catch (e) {
      setErro(e instanceof Error ? e.message : 'Falha ao salvar grupo manual.');
    }
  };

  const handleCriarGrupoManual = async (cliente: string, nome: string) => {
    if (!empresaBase) return;
    const rotulo = nome.trim();
    if (!rotulo) return;
    const atual = gruposManuaisRef.current;
    const baseId = slugId(rotulo);
    const ids = new Set(atual.map((g) => g.id));
    let grupoId = baseId;
    let n = 2;
    while (ids.has(grupoId)) {
      grupoId = `${baseId}_${n}`;
      n += 1;
    }
    const semCliente = atual.map((g) => ({
      ...g,
      clientes: g.clientes.filter((c) => c !== cliente),
    }));
    const proximos = [...semCliente, { id: grupoId, nome: rotulo, clientes: [cliente] }];
    gruposManuaisRef.current = proximos;
    setGruposManuais(proximos);
    try {
      await persistirGruposManuais(proximos);
    } catch (e) {
      setErro(e instanceof Error ? e.message : 'Falha ao criar grupo manual.');
    }
  };

  const handleSalvarGruposManuais = async () => {
    if (!empresaBase) throw new Error('Selecione uma empresa.');
    setSalvandoGrupos(true);
    setErro(null);
    try {
      await persistirGruposManuais(gruposManuaisRef.current);
    } finally {
      setSalvandoGrupos(false);
    }
  };

  const handleTagsClienteChange = async (cliente: string, tags: TagCliente[]) => {
    if (!empresaBase) return;
    const chave = cliente.trim();
    if (!chave) return;
    const tinhaBalcao = (tagsPorCliente[chave] ?? []).includes('cliente_balcao');
    const temBalcao = tags.includes('cliente_balcao');
    try {
      const dados = await salvarTagsUmCliente(empresaBase, chave, tags, lojaApi);
      setTagsPorCliente(dados.tags ?? {});
      // Tag só cadastra o nome; o filtro só muda a prévia se o checkbox estiver ligado.
      if (desconsiderarBalcao && tinhaBalcao !== temBalcao) {
        await atualizarPreviaGrupos({ ajustarCortes: false, empresa: empresaBase, loja: lojaApi });
      }
    } catch (e) {
      setErro(e instanceof Error ? e.message : 'Falha ao salvar tags do cliente.');
    }
  };

  const carregarPrevias = async (
    empresa?: string | null,
    opcoes?: { ajustarCortes?: boolean; override?: OverridePrevia; loja?: string | null },
  ) => {
    const emp = empresa !== undefined ? empresa : empresaBase;
    const loja = opcoes?.loja !== undefined ? opcoes.loja : lojaApi;
    const ajustarCortes = opcoes?.ajustarCortes ?? true;
    const o = opcoes?.override;
    // Tags (I/O leve) em paralelo com a 1ª prévia; a 2ª prévia sequencial
    // evita dois groupbys pesados competindo no worker único do uvicorn.
    await Promise.all([
      carregarTagsClientes(emp ?? null, loja),
      (async () => {
        await atualizarPreviaGrupos({
          empresa: emp,
          loja,
          ajustarCortes,
          clientesExcluidos: o?.clientesExcluidos,
          cortes: o?.cortes,
          balcao: o?.balcao,
          maxPorGrupo: o?.maxPorGrupo,
        });
        await atualizarPreviaProdutos({
          empresa: emp,
          loja,
          ajustarCortes,
          produtosExcluidos: o?.produtosExcluidos,
          corte: o?.corte,
          maxPorGrupo: o?.maxPorGrupo,
        });
      })(),
    ]);
  };

  const configAtual = () => ({
    cortesClientes, corteProdutos, periodosQueda, desconsiderarBalcao, desconsiderarDemaisProdutos,
    desconsiderarNaoHarmonizados, excluirPeriodoAtual, erosaoSomenteProdutosEmAlerta,
    nomeEmpresa: nomeEmpresaEfetivo, topNProdutos, reducaoMinimaErosao, maxPorGrupo,
    quedaMinimaAlertaRs, quedaMinimaErosaoRs, reducaoMinimaSemVenda, topNPoderCompra,
    clientesExcluidos: Array.from(clientesExcluidos), produtosExcluidos: Array.from(produtosExcluidos),
    chavesSelecionadas: Array.from(chavesSelecionadas), granularidade,
  });

  const handleSalvarConfiguracaoEmpresa = async () => {
    if (!nomeEmpresaEfetivo) {
      const msg = 'Selecione ou informe o nome da empresa antes de salvar.';
      setErro(msg);
      setSucesso(null);
      return;
    }
    if (!caminhoTrabalho) {
      const msg = 'Configure a pasta de trabalho (engrenagem) antes de salvar a configuração.';
      setErro(msg);
      setSucesso(null);
      return;
    }
    setErro(null);
    setSucesso(null);
    setSalvandoConfig(true);
    try {
      const resultado = await salvarConfiguracaoEmpresa(nomeEmpresaEfetivo, configAtual(), lojaApi);
      const caminho = resultado.caminho || `${caminhoTrabalho}/${nomeEmpresaEfetivo}/config.json`;
      const escopo = rotuloEscopoLoja;
      setSucesso(`Configuração salva (${escopo}) em ${caminho}`);
      setEmpresaSelecionada(nomeEmpresaEfetivo);
      setNomeEmpresaManual('');
      localStorage.setItem('alvo_empresa', nomeEmpresaEfetivo);
      try {
        const nomes = await listarEmpresas();
        setEmpresas(nomes);
      } catch {
        // Salvamento já ok — falha ao listar empresas não invalida o arquivo.
      }
    } catch (e) {
      const msg = e instanceof Error ? e.message : 'Falha ao salvar configuração da empresa.';
      setErro(msg);
      setSucesso(null);
    } finally {
      setSalvandoConfig(false);
    }
  };

  const handleSelecionarEmpresa = (nome: string) => {
    setEmpresaSelecionada(nome);
    const lojaSalva = nome ? lerLojaSalva(nome) : '';
    setLojaSelecionada(lojaSalva);
    if (nome) {
      setNomeEmpresaManual('');
      localStorage.setItem('alvo_empresa', nome);
    } else {
      localStorage.removeItem('alvo_empresa');
    }
    void iniciarEmpresa(nome || null, lojaSalva || null);
  };

  const handleSelecionarLoja = (loja: string) => {
    setLojaSelecionada(loja);
    if (empresaSelecionada) persistirLoja(empresaSelecionada, loja);
    void trocarEscopoLoja(loja || null);
  };

  const handleCarregarConfiguracaoEmpresa = async () => {
    if (!empresaSelecionada) {
      setErro('Selecione uma empresa no combobox para carregar a configuração.');
      return;
    }
    setErro(null);
    try {
      const dados = await tentarCarregarConfiguracaoEmpresa(empresaSelecionada, lojaApi);
      if (!dados) {
        setErro(`Configuração não encontrada para ${rotuloEscopoLoja}.`);
        return;
      }
      setNomeEmpresaManual('');
      const override = aplicarDadosConfig(dados);
      await atualizarPreviaGrupos({
        clientesExcluidos: override.clientesExcluidos,
        cortes: override.cortes,
        balcao: override.balcao,
        maxPorGrupo: override.maxPorGrupo,
        ajustarCortes: false,
        empresa: empresaSelecionada,
        loja: lojaApi,
      });
      await atualizarPreviaProdutos({
        produtosExcluidos: override.produtosExcluidos,
        corte: override.corte,
        maxPorGrupo: override.maxPorGrupo,
        ajustarCortes: false,
        empresa: empresaSelecionada,
        loja: lojaApi,
      });
    } catch (e) {
      setErro(e instanceof Error ? e.message : 'Falha ao carregar configuração da empresa.');
    }
  };

  const handleGerar = async () => {
    if (chavesSelecionadas.size === 0) {
      setErro('Selecione ao menos um relatório do catálogo.');
      return;
    }
    setErro(null);
    setCarregando(true);
    try {
      const resposta = await analisar(montarParametros());
      setResultados(resposta.resultados);
      setResultadoId(resposta.resultadoId);
      setEtapa('resultados');
    } catch (e) {
      setErro(e instanceof Error ? e.message : 'Falha ao gerar análises.');
    } finally {
      setCarregando(false);
    }
  };

  const handleExportar = async (formato: FormatoExportacao, chavesParaExportar: string[]) => {
    setErro(null);
    setCarregando(true);
    try {
      const parametros = { ...montarParametros(), chaves_selecionadas: chavesParaExportar };
      const blob = await exportarRelatorio(formato, parametros, resultadoId);
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `relatorio.${{ excel: 'xlsx', pdf: 'pdf', html: 'html' }[formato]}`;
      link.click();
      URL.revokeObjectURL(url);
      setFormatoParaConfirmar(null);
    } catch (e) {
      setErro(e instanceof Error ? e.message : `Falha ao exportar ${formato}.`);
    } finally {
      setCarregando(false);
    }
  };

  const toggleSet = (set: Set<string>, item: string, setter: (s: Set<string>) => void) => {
    const novo = new Set(set);
    if (novo.has(item)) novo.delete(item);
    else novo.add(item);
    setter(novo);
  };

  const nomesRelatorios = useMemo(() => {
    const mapa: Record<string, string> = {
      liquidez_estoque: 'Liquidez — Estoque',
      liquidez_vendas: 'Liquidez — Vendas',
    };
    catalogo.forEach((c) => c.itens.forEach((i) => { mapa[i.chave] = i.titulo; }));
    return mapa;
  }, [catalogo]);

  const todasAsChaves = useMemo(
    () => catalogo.flatMap((c) => c.itens.map((i) => i.chave)),
    [catalogo],
  );

  const abasResultados = useMemo(() => {
    if (!resultados) return [];
    const lista: { chaveAba: string; chave: string; rotulo: string; tabela: ResultadoAnalise[string][string] }[] = [];
    Object.entries(resultados).forEach(([granularidadeResultado, analises]) => {
      Object.entries(analises).forEach(([chave, tabela]) => {
        const titulo = nomesRelatorios[chave] || chave;
        const rotulo = granularidadeResultado === 'Alvos'
          ? titulo
          : `${titulo} (${granularidadeResultado})`;
        lista.push({
          chaveAba: `${granularidadeResultado}::${chave}`,
          chave,
          rotulo,
          tabela,
        });
      });
    });
    return lista;
  }, [resultados, nomesRelatorios]);

  useEffect(() => {
    if (abasResultados.length === 0) {
      setAbaAtiva(null);
      return;
    }
    if (!abasResultados.some((aba) => aba.chaveAba === abaAtiva)) {
      setAbaAtiva(abasResultados[0].chaveAba);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [abasResultados]);

  // Conta, por grupo (Faixa), quantos itens já visíveis na prévia estão
  // marcados como excluídos — usado para ajustar a contagem "oficial" (que
  // vem do backend e não sabe de exclusões feitas só no front, sem clicar em
  // "Atualizar prévia" de novo) para o valor real que de fato entra na
  // análise.
  const contarExcluidosPorGrupo = <T,>(
    itens: T[],
    excluidos: Set<string>,
    obterGrupo: (item: T) => string,
    obterChave: (item: T) => string,
  ) => {
    const mapa: Record<string, number> = {};
    itens.forEach((item) => {
      if (excluidos.has(obterChave(item))) {
        const grupo = obterGrupo(item);
        mapa[grupo] = (mapa[grupo] ?? 0) + 1;
      }
    });
    return mapa;
  };

  const clientesExcluidosPorGrupo = useMemo(
    () => contarExcluidosPorGrupo(itensClientes, clientesExcluidos, (i) => i.grupo, (i) => i.cliente),
    [itensClientes, clientesExcluidos],
  );
  const produtosExcluidosPorGrupo = useMemo(
    () => contarExcluidosPorGrupo(itensProdutos, produtosExcluidos, (i) => i.grupo, (i) => i.produto),
    [itensProdutos, produtosExcluidos],
  );

  const resumoGrupos = (
    lista: Grupo[] | null,
    rotulo: string,
    excluidosPorGrupo: Record<string, number> = {},
  ) => {
    if (!lista) return null;
    return (
      <p className="analisador-resumo-grupos">
        {lista.map((g) => {
          // O nome do grupo aqui pode ter um sufixo (ex.: "Grupo 1 (alto
          // giro)") que não existe no campo "grupo" de cada item da prévia
          // (ex.: "Grupo 1") — por isso o match é por prefixo, não só igualdade.
          const chaveCorrespondente = Object.keys(excluidosPorGrupo).find(
            (chave) => g.nome === chave || g.nome.startsWith(`${chave} `),
          );
          const excluidosNoGrupo = chaveCorrespondente ? excluidosPorGrupo[chaveCorrespondente] : 0;
          const quantidadeReal = Math.max(0, g.quantidade - excluidosNoGrupo);
          const rotuloCurto = rotuloGrupoCurto(g.nome);
          const texto = g.ate_percentual != null
            ? `${rotuloCurto} (até ${g.ate_percentual.toFixed(1)}%): ${quantidadeReal} ${rotulo}`
            : `${rotuloCurto}: ${quantidadeReal} ${rotulo}`;
          return excluidosNoGrupo > 0 ? `${texto} (${excluidosNoGrupo} excluído(s))` : texto;
        }).join(' | ')}
      </p>
    );
  };

  return (
    <AppShell>
    <div className="dashboard-container analisador-page">
      <header className="app-page-header">
        <div>
          <h1>
            Analisador de Monitoria
            {nomeEmpresaEfetivo && (
              <span className="analisador-header-empresa">
                <span className="analisador-header-empresa-sep" aria-hidden="true">·</span>
                <span className="analisador-header-empresa-nome">{nomeEmpresaEfetivo}</span>
                {lojaSelecionada && (
                  <span className="analisador-header-empresa-loja"> · {lojaSelecionada}</span>
                )}
              </span>
            )}
          </h1>
        </div>
      </header>

      <ExportarModal
        aberto={formatoParaConfirmar !== null}
        formato={formatoParaConfirmar}
        relatorios={abasResultados.map((aba) => ({ chave: aba.chave, rotulo: aba.rotulo }))}
        carregando={carregando}
        onCancelar={() => setFormatoParaConfirmar(null)}
        onConfirmar={(chaves) => formatoParaConfirmar && handleExportar(formatoParaConfirmar, chaves)}
      />

      {erro && (
        <div className="glass-card glass-card-flat analisador-erro" role="alert">
          {erro}
        </div>
      )}

      {sucesso && (
        <div className="glass-card glass-card-flat analisador-sucesso" role="status">
          {sucesso}
        </div>
      )}

      {configPendente && (
        <div
          className="config-modal-overlay"
          role="presentation"
          onClick={recusarConfig}
        >
          <div
            className="config-modal"
            style={{ width: 'min(480px, 100%)', maxHeight: 'min(80vh, 640px)' }}
            role="dialog"
            aria-modal="true"
            aria-labelledby="confirm-config-titulo"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="config-modal-header">
              <h2 id="confirm-config-titulo">Configuração salva</h2>
            </div>
            <div className="config-modal-body" style={{ padding: '1.25rem' }}>
              <p style={{ margin: '0 0 1rem', color: 'var(--text-secondary)', lineHeight: 1.5 }}>
                A empresa <strong>{configPendente.empresa}</strong> tem configuração salva
                {configPendente.loja ? (
                  <> para a loja <strong>{configPendente.loja}</strong></>
                ) : (
                  <> para <strong>Todas as lojas</strong></>
                )}
                . Deseja aplicar essas regras antes de carregar os dados?
              </p>
              <ul
                style={{
                  margin: '0 0 1.25rem',
                  paddingLeft: '1.25rem',
                  color: 'var(--text-secondary)',
                  lineHeight: 1.6,
                  fontSize: '0.95rem',
                }}
              >
                {resumirRegrasConfig(configPendente.dados).map((linha) => (
                  <li key={linha}>{linha}</li>
                ))}
              </ul>
              <p style={{ margin: '0 0 1.25rem', fontSize: '0.9rem', color: 'var(--text-muted, var(--text-secondary))' }}>
                Se escolher Não, usa o padrão (cortes 30/50/60 e 80%, com ajuste automático até {MAX_POR_GRUPO_PADRAO} por grupo).
              </p>
              <div style={{ display: 'flex', gap: '0.75rem', justifyContent: 'flex-end', flexWrap: 'wrap' }}>
                <button type="button" className="analisador-btn analisador-btn-sec" onClick={recusarConfig}>
                  Não, usar padrão
                </button>
                <button type="button" className="analisador-btn analisador-btn-pri" onClick={confirmarAplicarConfig}>
                  Sim, aplicar
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {etapa === 'carregando-base' && !configPendente && (
        <div className="glass-card glass-card-flat" style={{ maxWidth: 480 }}>
          <p className="analisador-hint">Carregando base de dados...</p>
        </div>
      )}

      {etapa === 'carregando-base' && configPendente && (
        <div className="glass-card glass-card-flat" style={{ maxWidth: 480 }}>
          <p className="analisador-hint">Aguardando confirmação da configuração salva...</p>
        </div>
      )}

      {etapa === 'config' && previa && (
        <div className="analisador-stack">
          <div className="glass-card glass-card-flat">
            <p className="analisador-hint" style={{ margin: 0 }}>
              {previa.linhas.toLocaleString('pt-BR')} linhas carregadas
              {mostrarSeletorLoja && lojaSelecionada && ` · loja ${lojaSelecionada}`}
              {!mostrarSeletorLoja && lojasDisponiveis.length === 1 && ` · loja ${lojasDisponiveis[0]}`}
              {previa.linhas_ignoradas > 0 && ` (${previa.linhas_ignoradas} ignoradas por Ano/Mês vazio)`}
              {previa.qtd_nao_harmonizados > 0 && ` · ${previa.qtd_nao_harmonizados} lançamentos sem descrição de produto`}
            </p>
          </div>

          <div className="glass-card glass-card-flat analisador-bloco analisador-bloco-empresa">
            <h2 className="analisador-titulo">Empresa analisada</h2>
            <div className="analisador-campo">
              <span>Empresa analisada</span>
              <AnalisadorCombobox
                value={empresaSelecionada}
                options={empresas}
                onChange={handleSelecionarEmpresa}
                emptyLabel="— Digitar manualmente —"
                searchPlaceholder="Buscar empresa…"
                includeOrphanValue
                aria-label="Empresa analisada"
              />
            </div>
            {!empresaSelecionada && (
              <label className="analisador-campo">
                <span>Nome manual</span>
                <input
                  className="analisador-input"
                  value={nomeEmpresaManual}
                  onChange={(e) => setNomeEmpresaManual(e.target.value)}
                  placeholder="Aparece na capa e no nome do arquivo"
                />
              </label>
            )}
            {mostrarSeletorLoja && (
              <div className="analisador-campo">
                <span>Loja</span>
                <AnalisadorCombobox
                  value={lojaSelecionada}
                  options={lojasDisponiveis}
                  onChange={handleSelecionarLoja}
                  emptyLabel="Todas as lojas"
                  searchPlaceholder={lojasDisponiveis.length > 8 ? 'Buscar loja…' : false}
                  aria-label="Loja"
                />
              </div>
            )}
            <div className="analisador-acoes">
              <button type="button" onClick={handleCarregarConfiguracaoEmpresa} className="analisador-btn analisador-btn-sec">
                <FolderOpen size={16} /> Carregar configuração
              </button>
              <button
                type="button"
                onClick={handleSalvarConfiguracaoEmpresa}
                disabled={salvandoConfig}
                className="analisador-btn analisador-btn-sec"
              >
                <Save size={16} /> {salvandoConfig ? 'Salvando...' : 'Salvar configuração'}
              </button>
            </div>
            {sucesso && (
              <p className="analisador-feedback-inline ok" role="status">{sucesso}</p>
            )}
            {erro && (
              <p className="analisador-feedback-inline erro" role="alert">{erro}</p>
            )}
            <p className="analisador-hint" style={{ width: '100%' }}>
              {empresaSelecionada
                ? `Configuração, tags e grupos são salvos por escopo de loja em ${caminhoTrabalho || 'pasta de trabalho'}/${empresaSelecionada}/ (config.json e clientes_tags.json). Escopo atual: ${rotuloEscopoLoja}.`
                : 'Sem empresa: usa base_de_dados.xlsx da raiz. Selecione uma empresa (ou abra o Analisador com uma já escolhida no Dashboard).'}
            </p>
          </div>

          <div className="analisador-tabs custom-scrollbar" role="tablist" aria-label="Áreas do analisador">
            {ABAS_WORKSPACE.map((aba) => (
              <button
                key={aba.id}
                type="button"
                role="tab"
                aria-selected={abaWorkspace === aba.id}
                className={`analisador-tab${abaWorkspace === aba.id ? ' is-ativa' : ''}`}
                onClick={(e) => {
                  setAbaWorkspace(aba.id);
                  e.currentTarget.scrollIntoView({ behavior: 'smooth', inline: 'nearest', block: 'nearest' });
                }}
              >
                {aba.rotulo}
              </button>
            ))}
          </div>

          {abaWorkspace === 'relatorios' && (
          <>
          <div className="analisador-previas-grid">
            <div className="glass-card glass-card-flat analisador-stack-inner">
              <h2 className="analisador-titulo">Grupos de clientes</h2>
              <div className="analisador-segmentacao-linha">
                <div className="analisador-campo">
                  <span id="cortes-abc-label">Cortes A/B/C (% acumulada) e máx. por grupo</span>
                  <div className="analisador-cortes" role="group" aria-labelledby="cortes-abc-label">
                    {cortesClientes.map((valor, indice) => (
                      <NumberStepper
                        key={indice}
                        value={valor}
                        ariaLabel={`Corte grupo ${indice + 1}`}
                        onChange={(v) => {
                          const novo = [...cortesClientes] as [number, number, number];
                          novo[indice] = v === '' ? 0 : v;
                          setCortesClientes(novo);
                        }}
                      />
                    ))}
                    <span className="analisador-cortes-sep" aria-hidden="true" />
                    <NumberStepper
                      value={maxPorGrupo}
                      ariaLabel="Máximo de clientes por grupo"
                      onChange={(v) => setMaxPorGrupo(v === '' ? 0 : v)}
                    />
                  </div>
                </div>
              </div>
              <label className="analisador-check-linha">
                <input
                  type="checkbox"
                  checked={desconsiderarBalcao}
                  onChange={(e) => {
                    const checked = e.target.checked;
                    setDesconsiderarBalcao(checked);
                    void atualizarPreviaGrupos({ balcao: checked, ajustarCortes: false });
                  }}
                />
                Desconsiderar clientes balcão
              </label>
              <div className="analisador-acoes">
                <button type="button" onClick={handleSugerirCortes} disabled={carregandoGrupos} className="analisador-btn analisador-btn-sec">
                  {carregandoGrupos ? 'Calculando...' : 'Sugerir cortes automaticamente'}
                </button>
                <button type="button" onClick={handleAtualizarPreviaGrupos} disabled={carregandoGrupos} className="analisador-btn analisador-btn-sec">
                  {carregandoGrupos ? 'Calculando...' : 'Atualizar prévia dos grupos'}
                </button>
              </div>
              <PreviaClientesTable
                itens={itensClientes}
                excluidos={clientesExcluidos}
                onToggle={(cliente) => toggleSet(clientesExcluidos, cliente, setClientesExcluidos)}
                onToggleAll={(chaves, checkAll) => {
                  setClientesExcluidos((prev) => {
                    const novo = new Set(prev);
                    chaves.forEach((c) => (checkAll ? novo.delete(c) : novo.add(c)));
                    return novo;
                  });
                }}
                carregando={carregandoGrupos}
                empresa={empresaBase}
                tagsPorCliente={tagsPorCliente}
                tagsCatalogo={tagsCatalogo}
                gruposManuais={gruposManuais}
                onTagsChange={handleTagsClienteChange}
                onToggleGrupoManual={handleToggleGrupoManual}
                onCriarGrupoManual={handleCriarGrupoManual}
                desconsiderarBalcao={desconsiderarBalcao}
              />
              <p className="analisador-hint" style={{ width: '100%', marginTop: '0.5rem' }}>
                Cortes ajustados automaticamente para ≤{maxPorGrupo} por grupo (exceto Demais: até 300 na prévia; contagem total acima).
              </p>
              {resumoGrupos(grupos, 'clientes', clientesExcluidosPorGrupo)}
            </div>

            <div className="glass-card glass-card-flat analisador-stack-inner">
              <h2 className="analisador-titulo">Grupos de produtos</h2>
              <div className="analisador-segmentacao-linha">
                <label className="analisador-campo">
                  <span>Corte de produtos (%)</span>
                  <div className="analisador-cortes">
                    <NumberStepper
                      value={corteProdutos}
                      onChange={(v) => setCorteProdutos(v === '' ? 0 : v)}
                    />
                  </div>
                </label>
              </div>
              <div className="analisador-check-linha-grupo">
                <label className="analisador-check-linha">
                  <input
                    type="checkbox"
                    checked={desconsiderarDemaisProdutos}
                    onChange={(e) => handleToggleDesconsiderarDemais(e.target.checked)}
                  />
                  Desconsiderar os demais nos relatórios
                </label>
                <label className="analisador-check-linha">
                  <input
                    type="checkbox"
                    checked={desconsiderarNaoHarmonizados}
                    onChange={(e) => handleToggleDesconsiderarNaoHarmonizados(e.target.checked)}
                  />
                  Desconsiderar "não harmonizados"
                </label>
              </div>
              <div className="analisador-acoes">
                <button
                  type="button"
                  onClick={handleAtualizarPreviaProdutos}
                  disabled={carregandoProdutos}
                  className="analisador-btn analisador-btn-sec"
                >
                  {carregandoProdutos ? 'Calculando...' : 'Atualizar prévia dos produtos'}
                </button>
              </div>
              <PreviaProdutosTable
                itens={itensProdutos}
                excluidos={produtosExcluidos}
                onToggle={(produto) => toggleSet(produtosExcluidos, produto, setProdutosExcluidos)}
                onToggleAll={(chaves, checkAll) => {
                  setProdutosExcluidos((prev) => {
                    const novo = new Set(prev);
                    chaves.forEach((p) => (checkAll ? novo.delete(p) : novo.add(p)));
                    return novo;
                  });
                }}
                carregando={carregandoProdutos}
              />
              <p className="analisador-hint" style={{ width: '100%', marginTop: '0.5rem' }}>
                Corte ajustado automaticamente para ≤{maxPorGrupo} no alto giro (Demais: até 300 na prévia; contagem total acima).
              </p>
              {resumoGrupos(produtosGrupos, 'produtos', produtosExcluidosPorGrupo)}
            </div>
          </div>

          <div className="glass-card glass-card-flat analisador-stack-inner">
            <div className="analisador-titulo-linha">
              <h2 className="analisador-titulo">Relatórios a gerar</h2>
              <div className="analisador-titulo-linha-acoes">
                <p className="analisador-hint" style={{ margin: 0 }}>
                  {chavesSelecionadas.size} selecionado{chavesSelecionadas.size === 1 ? '' : 's'}
                </p>
                <button
                  type="button"
                  className="analisador-btn analisador-btn-sec analisador-btn-compact"
                  onClick={() => {
                    setChavesSelecionadas(
                      chavesSelecionadas.size === todasAsChaves.length ? new Set() : new Set(todasAsChaves),
                    );
                  }}
                >
                  {chavesSelecionadas.size === todasAsChaves.length ? 'Desmarcar todos' : 'Marcar todos'}
                </button>
              </div>
            </div>
            <div className="analisador-catalogo-grid">
              {catalogo.map((categoria) => {
                const todasMarcadas = categoria.itens.every((item) => chavesSelecionadas.has(item.chave));
                return (
                  <div key={categoria.categoria} className="analisador-catalogo-cat">
                    <div className="analisador-catalogo-cat-header">
                      <p className="analisador-catalogo-titulo">{categoria.categoria}</p>
                      <button
                        type="button"
                        className="analisador-catalogo-toggle"
                        onClick={() => {
                          const novo = new Set(chavesSelecionadas);
                          if (todasMarcadas) {
                            categoria.itens.forEach((item) => novo.delete(item.chave));
                          } else {
                            categoria.itens.forEach((item) => novo.add(item.chave));
                          }
                          setChavesSelecionadas(novo);
                        }}
                      >
                        {todasMarcadas ? 'Desmarcar' : 'Marcar todas'}
                      </button>
                    </div>
                    <div className="analisador-catalogo-itens">
                      {categoria.itens.map((item) => {
                        const marcado = chavesSelecionadas.has(item.chave);
                        return (
                          <label
                            key={item.chave}
                            className={`analisador-catalogo-item${marcado ? ' is-marcado' : ''}`}
                          >
                            <input
                              type="checkbox"
                              checked={marcado}
                              onChange={() => toggleSet(chavesSelecionadas, item.chave, setChavesSelecionadas)}
                            />
                            <span>{item.titulo}</span>
                          </label>
                        );
                      })}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          <button type="button" onClick={handleGerar} disabled={carregando} className="analisador-btn analisador-btn-pri analisador-btn-gerar">
            {carregando ? 'Gerando...' : 'Gerar relatório'}
          </button>
          </>
          )}

          {abaWorkspace === 'graficos' && (
            <ExplorarBuilder empresa={empresaBase} loja={lojaApi} modo="grafico" />
          )}
          {abaWorkspace === 'tabelas' && (
            <ExplorarBuilder empresa={empresaBase} loja={lojaApi} modo="tabela" />
          )}
          {abaWorkspace === 'clientes' && (
            <ClientesGruposPanel
              empresa={empresaBase}
              loja={lojaApi}
              itensClientes={itensClientes}
              tagsPorCliente={tagsPorCliente}
              tagsCatalogo={tagsCatalogo}
              clientesBalcao={clientesBalcao}
              grupos={gruposManuais}
              onChangeGrupos={setGruposManuais}
              onSalvarGrupos={handleSalvarGruposManuais}
              salvando={salvandoGrupos}
            />
          )}
        </div>
      )}

      {etapa === 'resultados' && resultados && (
        <div className="analisador-stack">
          <div className="analisador-acoes">
            <button type="button" onClick={() => setFormatoParaConfirmar('excel')} disabled={carregando} className="analisador-btn analisador-btn-pri">
              <Download size={16} /> Baixar Excel
            </button>
            <button type="button" onClick={() => setFormatoParaConfirmar('pdf')} disabled={carregando} className="analisador-btn analisador-btn-pri">
              <Download size={16} /> Baixar PDF
            </button>
            <button
              type="button"
              onClick={() => setFormatoParaConfirmar('html')}
              disabled={carregando}
              className="analisador-btn analisador-btn-pri"
              title="Página estática num arquivo único — abre em qualquer navegador, sem instalar nada"
            >
              <Download size={16} /> Baixar HTML
            </button>
            <button type="button" onClick={() => setEtapa('config')} className="analisador-btn analisador-btn-sec">
              Ajustar parâmetros
            </button>
          </div>

          <div className="analisador-tabs custom-scrollbar" role="tablist">
            {abasResultados.map((aba) => (
              <button
                key={aba.chaveAba}
                type="button"
                role="tab"
                aria-selected={aba.chaveAba === abaAtiva}
                className={`analisador-tab${aba.chaveAba === abaAtiva ? ' is-ativa' : ''}`}
                onClick={(e) => {
                  setAbaAtiva(aba.chaveAba);
                  e.currentTarget.scrollIntoView({ behavior: 'smooth', inline: 'nearest', block: 'nearest' });
                }}
              >
                {aba.rotulo}
              </button>
            ))}
          </div>

          {abasResultados.map((aba) => (
            aba.chaveAba === abaAtiva && (
              <div key={aba.chaveAba} className="glass-card glass-card-flat analisador-stack-inner">
                <ResultTable tabela={aba.tabela} chave={aba.chave} />
              </div>
            )
          ))}
        </div>
      )}
    </div>
    </AppShell>
  );
}
