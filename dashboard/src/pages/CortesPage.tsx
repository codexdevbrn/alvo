import { useEffect, useMemo, useRef, useState } from 'react';
import { AppShell } from '../components/AppShell';
import { FolderOpen, Save, Wand2, RefreshCw } from 'lucide-react';
import {
  obterBase,
  obterCaminhoTrabalho,
  obterPreviaGrupos,
  obterPreviaProdutos,
  sugerirCorteProdutos,
  obterTagsClientes,
  salvarConfiguracaoEmpresa,
  salvarGruposManuais,
  salvarTagsUmCliente,
  tentarCarregarConfiguracaoEmpresa,
  TAGS_CATALOGO_PADRAO,
  type ConfigEmpresaSalva,
  type Grupo,
  type GrupoManualClientes,
  type ItemClientePrevia,
  type ItemProdutoPrevia,
  type PreviaBase,
  type TagCatalogoItem,
  type TagCliente,
} from '../api/client';
import { PreviaClientesTable } from '../components/analisador/PreviaClientesTable';
import { PreviaProdutosTable } from '../components/analisador/PreviaProdutosTable';
import { NumberStepper } from '../components/analisador/NumberStepper';
import { rotuloGrupoCurto } from '../utils/formatters';
import { slugId } from '../utils/slug';
import { LeituraFaixa } from '../components/LeituraFaixa';
import { useEscopoAtual } from '../hooks/useEscopoAtual';
import {
  CORTES_CLIENTES_PADRAO,
  CORTE_PRODUTOS_PADRAO,
  MAX_POR_GRUPO_PADRAO,
} from '../utils/configAnalisador';

type Etapa = 'carregando-base' | 'config';

type OverridePrevia = {
  clientesExcluidos: string[];
  cortes: [number, number, number];
  balcao: boolean;
  produtosExcluidos: string[];
  corte: number;
  maxPorGrupo: number;
  desconsiderarDemais: boolean;
  desconsiderarNaoHarm: boolean;
};

/** % acumulado do item que ocupa a posição `rank` (1 = maior receita) na curva
 *  já carregada na prévia — usado para converter "quero N itens no grupo" no
 *  corte % equivalente, sem depender do backend (que já devolve os grupos A/B/C
 *  inteiros; só "Demais" vem truncado, então isto cobre qualquer rank dentro
 *  dos grupos correntes). Devolve null se a prévia não tem itens suficientes. */
function corteNoRank(itens: Array<{ percentual_acumulado: number | null }>, rank: number): number | null {
  if (rank <= 0) return null;
  const curva = itens
    .map((i) => i.percentual_acumulado)
    .filter((v): v is number => v != null)
    .sort((a, b) => a - b);
  if (curva.length === 0) return null;
  const indice = Math.min(rank, curva.length) - 1;
  // Arredonda pra CIMA: o corte precisa ficar >= ao acumulado real do item, senão
  // ele cai fora do grupo (classificação é por "acumulado <= corte", inclusivo) —
  // arredondar pra baixo derrubava o último item pedido pro grupo seguinte.
  return Math.ceil(curva[indice] * 10) / 10;
}

export default function CortesPage() {
  const { empresa: empresaSelecionada, lojas: lojasEscopo, loja: lojaApi } = useEscopoAtual();
  const empresaBase = empresaSelecionada || null;
  const nomeEmpresaEfetivo = empresaSelecionada;

  const [etapa, setEtapa] = useState<Etapa>('carregando-base');
  const [erro, setErro] = useState<string | null>(null);
  const [sucesso, setSucesso] = useState<string | null>(null);
  const [salvandoConfig, setSalvandoConfig] = useState(false);

  const [previa, setPrevia] = useState<PreviaBase | null>(null);
  const [caminhoTrabalho, setCaminhoTrabalho] = useState<string | null>(null);

  const [clientesExcluidos, setClientesExcluidos] = useState<Set<string>>(new Set());
  const [produtosExcluidos, setProdutosExcluidos] = useState<Set<string>>(new Set());
  const [cortesClientes, setCortesClientes] = useState<[number, number, number]>(CORTES_CLIENTES_PADRAO);
  const [corteProdutos, setCorteProdutos] = useState(CORTE_PRODUTOS_PADRAO);
  const [desconsiderarBalcao, setDesconsiderarBalcao] = useState(false);
  const [desconsiderarDemaisProdutos, setDesconsiderarDemaisProdutos] = useState(false);
  const [desconsiderarNaoHarmonizados, setDesconsiderarNaoHarmonizados] = useState(false);
  const [maxPorGrupo, setMaxPorGrupo] = useState(MAX_POR_GRUPO_PADRAO);

  /** Modo de separação: cortes A/B/C por % acumulada (padrão, o que o config.json
   *  guarda) ou por quantidade de itens desejada por grupo — esta última só
   *  existe na tela, e ao aplicar é convertida para os % equivalentes na
   *  prévia carregada, então não muda o formato salvo nem o backend. */
  const [modoClientes, setModoClientes] = useState<'percentual' | 'quantidade'>('percentual');
  const [quantidadesClientes, setQuantidadesClientes] = useState<[number, number, number]>([20, 50, 100]);
  const [modoProdutos, setModoProdutos] = useState<'percentual' | 'quantidade'>('percentual');
  const [quantidadeProdutos, setQuantidadeProdutos] = useState(50);

  const [grupos, setGrupos] = useState<Grupo[] | null>(null);
  const [itensClientes, setItensClientes] = useState<ItemClientePrevia[]>([]);
  const [tagsPorCliente, setTagsPorCliente] = useState<Record<string, TagCliente[]>>({});
  const [tagsCatalogo, setTagsCatalogo] = useState<TagCatalogoItem[]>(TAGS_CATALOGO_PADRAO);
  const [gruposManuais, setGruposManuais] = useState<GrupoManualClientes[]>([]);
  const [carregandoGrupos, setCarregandoGrupos] = useState(false);
  const [produtosGrupos, setProdutosGrupos] = useState<Grupo[] | null>(null);
  const [itensProdutos, setItensProdutos] = useState<ItemProdutoPrevia[]>([]);
  const [carregandoProdutos, setCarregandoProdutos] = useState(false);

  /** Resto do config.json que esta tela não edita (chaves de Relatórios) — mantido
   *  intacto para não ser apagado quando esta tela salva. */
  const configRestanteRef = useRef<ConfigEmpresaSalva>({});

  const gruposSaveChainRef = useRef(Promise.resolve());
  const gruposManuaisRef = useRef(gruposManuais);
  gruposManuaisRef.current = gruposManuais;
  const cargaSeqRef = useRef(0);
  const gruposPreviaDebounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const gruposPreviaCtxRef = useRef<{ empresa: string; loja: string | null } | null>(null);
  const escopoAnteriorRef = useRef<string | null>(null);

  const rotuloEscopoLoja = lojasEscopo.length === 0 ? 'Todas as lojas' : lojasEscopo.length === 1 ? lojasEscopo[0] : `${lojasEscopo.length} lojas`;

  useEffect(() => {
    obterCaminhoTrabalho(true).then(setCaminhoTrabalho).catch(() => {});
  }, []);

  useEffect(() => {
    if (!sucesso) return undefined;
    const timer = window.setTimeout(() => setSucesso(null), 5000);
    return () => window.clearTimeout(timer);
  }, [sucesso]);

  const aplicarDadosConfig = (dados: ConfigEmpresaSalva): OverridePrevia => {
    configRestanteRef.current = dados;
    const cortes = (dados.cortesClientes ?? CORTES_CLIENTES_PADRAO) as [number, number, number];
    const corte = dados.corteProdutos ?? CORTE_PRODUTOS_PADRAO;
    const maxG = dados.maxPorGrupo ?? MAX_POR_GRUPO_PADRAO;
    const clientes = dados.clientesExcluidos ?? [];
    const produtos = dados.produtosExcluidos ?? [];
    const balcao = Boolean(dados.desconsiderarBalcao);
    const semDemais = Boolean(dados.desconsiderarDemaisProdutos);
    const semNaoHarm = Boolean(dados.desconsiderarNaoHarmonizados);

    setCortesClientes(cortes);
    setCorteProdutos(corte);
    setDesconsiderarBalcao(balcao);
    setDesconsiderarDemaisProdutos(semDemais);
    setDesconsiderarNaoHarmonizados(semNaoHarm);
    setMaxPorGrupo(maxG);
    setClientesExcluidos(new Set(clientes));
    setProdutosExcluidos(new Set(produtos));
    setModoClientes(dados.modoClientes ?? 'percentual');
    setQuantidadesClientes(dados.quantidadesClientes ?? [20, 50, 100]);
    setModoProdutos(dados.modoProdutos ?? 'percentual');
    setQuantidadeProdutos(dados.quantidadeProdutos ?? 50);

    return {
      clientesExcluidos: clientes,
      cortes,
      balcao,
      produtosExcluidos: produtos,
      corte,
      maxPorGrupo: maxG,
      desconsiderarDemais: semDemais,
      desconsiderarNaoHarm: semNaoHarm,
    };
  };

  const resetarParaPadrao = (): OverridePrevia => {
    configRestanteRef.current = {};
    setCortesClientes(CORTES_CLIENTES_PADRAO);
    setCorteProdutos(CORTE_PRODUTOS_PADRAO);
    setDesconsiderarBalcao(false);
    setDesconsiderarDemaisProdutos(false);
    setDesconsiderarNaoHarmonizados(false);
    setMaxPorGrupo(MAX_POR_GRUPO_PADRAO);
    setClientesExcluidos(new Set());
    setProdutosExcluidos(new Set());
    setModoClientes('percentual');
    setQuantidadesClientes([20, 50, 100]);
    setModoProdutos('percentual');
    setQuantidadeProdutos(50);
    return {
      clientesExcluidos: [],
      cortes: CORTES_CLIENTES_PADRAO,
      balcao: false,
      produtosExcluidos: [],
      corte: CORTE_PRODUTOS_PADRAO,
      maxPorGrupo: MAX_POR_GRUPO_PADRAO,
      desconsiderarDemais: false,
      desconsiderarNaoHarm: false,
    };
  };

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

  const atualizarPreviaProdutos = async (parametros?: {
    produtosExcluidos?: string[];
    corte?: number;
    empresa?: string | null;
    loja?: string | null;
    desconsiderarDemais?: boolean;
    desconsiderarNaoHarm?: boolean;
    sugerirCorte?: boolean;
  }) => {
    setErro(null);
    setCarregandoProdutos(true);
    try {
      const excluidosEnviados = parametros?.produtosExcluidos ?? Array.from(produtosExcluidos);
      const comuns = {
        produtos_excluidos: excluidosEnviados,
        corte_produtos: parametros?.corte ?? corteProdutos,
        desconsiderar_demais_produtos: parametros?.desconsiderarDemais ?? desconsiderarDemaisProdutos,
        desconsiderar_nao_harmonizados: parametros?.desconsiderarNaoHarm ?? desconsiderarNaoHarmonizados,
        empresa: parametros?.empresa !== undefined ? parametros.empresa : empresaBase,
        loja: parametros?.loja !== undefined ? parametros.loja : lojaApi,
      };
      const resultado = parametros?.sugerirCorte
        ? await sugerirCorteProdutos({ ...comuns, max_itens_por_grupo: maxPorGrupo })
        : await obterPreviaProdutos(comuns);
      if (typeof resultado.corte_produtos === 'number') {
        setCorteProdutos(resultado.corte_produtos);
      }
      setProdutosGrupos(resultado.grupos);
      if (Array.isArray(resultado.produtos_fora_por_regra) && resultado.produtos_fora_por_regra.length > 0) {
        const porRegra = new Set(resultado.produtos_fora_por_regra);
        const manuais = excluidosEnviados.filter((produto) => !porRegra.has(produto));
        if (manuais.length !== excluidosEnviados.length) {
          setProdutosExcluidos(new Set(manuais));
        }
      }
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

  const carregarTagsClientes = async (empresa: string | null, loja?: string | null) => {
    if (!empresa) {
      setTagsPorCliente({});
      setTagsCatalogo(TAGS_CATALOGO_PADRAO);
      setGruposManuais([]);
      return;
    }
    try {
      const dados = await obterTagsClientes(empresa, loja !== undefined ? loja : lojaApi);
      setTagsPorCliente(dados.tags ?? {});
      setTagsCatalogo(dados.catalogo ?? TAGS_CATALOGO_PADRAO);
      setGruposManuais(dados.grupos ?? []);
    } catch (e) {
      setErro(e instanceof Error ? e.message : 'Falha ao carregar tags/grupos da empresa.');
    }
  };

  const carregarPrevias = async (
    empresa: string | null,
    loja: string | null,
    opcoes?: { ajustarCortes?: boolean; override?: OverridePrevia },
  ) => {
    const ajustarCortes = opcoes?.ajustarCortes ?? true;
    const o = opcoes?.override;
    await Promise.all([
      carregarTagsClientes(empresa, loja),
      (async () => {
        await atualizarPreviaGrupos({
          empresa,
          loja,
          ajustarCortes,
          clientesExcluidos: o?.clientesExcluidos,
          cortes: o?.cortes,
          balcao: o?.balcao,
          maxPorGrupo: o?.maxPorGrupo,
        });
        await atualizarPreviaProdutos({
          empresa,
          loja,
          produtosExcluidos: o?.produtosExcluidos,
          corte: o?.corte,
          desconsiderarDemais: o?.desconsiderarDemais,
          desconsiderarNaoHarm: o?.desconsiderarNaoHarm,
        });
      })(),
    ]);
  };

  const carregarBaseAtual = async (
    empresa: string | null,
    loja: string | null,
    opcoes?: { ajustarCortes?: boolean; override?: OverridePrevia },
  ) => {
    const seq = ++cargaSeqRef.current;
    setErro(null);
    setEtapa('carregando-base');
    try {
      const resultado = await obterBase(empresa, loja);
      if (seq !== cargaSeqRef.current) return;
      setPrevia(resultado);
      setEtapa('config');
      await carregarPrevias(empresa, loja, opcoes);
      if (seq !== cargaSeqRef.current) return;
    } catch (e) {
      if (seq !== cargaSeqRef.current) return;
      setErro(e instanceof Error ? e.message : 'Falha ao carregar a base de dados.');
      setEtapa('config');
    }
  };

  // Ao trocar empresa/loja (sidebar): aplica direto o config.json salvo no
  // escopo (sem perguntar — mesma regra do Relatórios), avisando por banner
  // qual config entrou em vigor; sem config salva, usa o padrão.
  useEffect(() => {
    const chaveEscopo = `${empresaSelecionada}::${lojaApi ?? ''}`;
    if (escopoAnteriorRef.current === chaveEscopo) return;
    escopoAnteriorRef.current = chaveEscopo;
    const seq = ++cargaSeqRef.current;
    if (!empresaSelecionada) {
      const override = resetarParaPadrao();
      void carregarBaseAtual(null, null, { ajustarCortes: true, override });
      return;
    }
    setEtapa('carregando-base');
    (async () => {
      try {
        const dados = await tentarCarregarConfiguracaoEmpresa(empresaSelecionada, lojaApi);
        if (seq !== cargaSeqRef.current) return;
        if (dados) {
          const override = aplicarDadosConfig(dados);
          setSucesso(`Configuração salva de ${rotuloEscopoLoja} aplicada.`);
          await carregarBaseAtual(empresaSelecionada, lojaApi, { ajustarCortes: false, override });
          return;
        }
        const override = resetarParaPadrao();
        setSucesso(`Sem configuração salva para ${rotuloEscopoLoja} — usando padrão (30/50/60, 80%).`);
        await carregarBaseAtual(empresaSelecionada, lojaApi, { ajustarCortes: true, override });
      } catch (e) {
        if (seq !== cargaSeqRef.current) return;
        setErro(e instanceof Error ? e.message : 'Falha ao verificar configuração da empresa.');
        const override = resetarParaPadrao();
        await carregarBaseAtual(empresaSelecionada, lojaApi, { ajustarCortes: true, override });
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [empresaSelecionada, lojaApi]);

  const handleAtualizarPreviaGrupos = () => atualizarPreviaGrupos({ ajustarCortes: false });
  const handleSugerirCortes = () => atualizarPreviaGrupos({ ajustarCortes: true });
  const handleAtualizarPreviaProdutos = () => atualizarPreviaProdutos();
  const handleSugerirCorteProdutos = () => atualizarPreviaProdutos({ sugerirCorte: true });

  const handleToggleDesconsiderarDemais = async (checked: boolean) => {
    setDesconsiderarDemaisProdutos(checked);
    await atualizarPreviaProdutos({ desconsiderarDemais: checked });
  };

  const handleToggleDesconsiderarNaoHarmonizados = async (checked: boolean) => {
    setDesconsiderarNaoHarmonizados(checked);
    await atualizarPreviaProdutos({ desconsiderarNaoHarm: checked });
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
      gruposPreviaCtxRef.current = { empresa, loja };
      if (gruposPreviaDebounceRef.current !== null) {
        clearTimeout(gruposPreviaDebounceRef.current);
      }
      gruposPreviaDebounceRef.current = setTimeout(() => {
        gruposPreviaDebounceRef.current = null;
        const ctx = gruposPreviaCtxRef.current;
        gruposPreviaCtxRef.current = null;
        if (!ctx) return;
        void atualizarPreviaGrupos({ ajustarCortes: false, empresa: ctx.empresa, loja: ctx.loja });
      }, 450);
      return dados;
    });
    gruposSaveChainRef.current = job.then(() => undefined, () => undefined);
    return job;
  };

  const handleToggleGrupoManual = async (cliente: string, grupoId: string) => {
    if (!empresaBase) return;
    const atual = gruposManuaisRef.current;
    const proximos = atual.map((g) => ({ ...g, clientes: g.clientes.filter((c) => c !== cliente) }));
    const alvo = proximos.find((g) => g.id === grupoId);
    const estavaNoGrupo = atual.some((g) => g.id === grupoId && g.clientes.includes(cliente));
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
    const semCliente = atual.map((g) => ({ ...g, clientes: g.clientes.filter((c) => c !== cliente) }));
    const proximos = [...semCliente, { id: grupoId, nome: rotulo, clientes: [cliente] }];
    gruposManuaisRef.current = proximos;
    setGruposManuais(proximos);
    try {
      await persistirGruposManuais(proximos);
    } catch (e) {
      setErro(e instanceof Error ? e.message : 'Falha ao criar grupo manual.');
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
      if (desconsiderarBalcao && tinhaBalcao !== temBalcao) {
        await atualizarPreviaGrupos({ ajustarCortes: false, empresa: empresaBase, loja: lojaApi });
      }
    } catch (e) {
      setErro(e instanceof Error ? e.message : 'Falha ao salvar tags do cliente.');
    }
  };

  const handleCarregarConfiguracaoEmpresa = async () => {
    if (!empresaSelecionada) {
      setErro('Selecione uma empresa na barra lateral para carregar a configuração.');
      return;
    }
    setErro(null);
    try {
      const dados = await tentarCarregarConfiguracaoEmpresa(empresaSelecionada, lojaApi, true);
      if (!dados) {
        setErro(`Configuração não encontrada para ${rotuloEscopoLoja}.`);
        return;
      }
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
        desconsiderarDemais: override.desconsiderarDemais,
        desconsiderarNaoHarm: override.desconsiderarNaoHarm,
        empresa: empresaSelecionada,
        loja: lojaApi,
      });
    } catch (e) {
      setErro(e instanceof Error ? e.message : 'Falha ao carregar configuração da empresa.');
    }
  };

  const handleSalvarConfiguracaoEmpresa = async () => {
    if (!nomeEmpresaEfetivo) {
      setErro('Selecione uma empresa na barra lateral antes de salvar.');
      setSucesso(null);
      return;
    }
    if (!caminhoTrabalho) {
      setErro('Configure a pasta de trabalho (Configurações) antes de salvar a configuração.');
      setSucesso(null);
      return;
    }
    setErro(null);
    setSucesso(null);
    setSalvandoConfig(true);
    try {
      const dadosParaSalvar: ConfigEmpresaSalva = {
        ...configRestanteRef.current,
        cortesClientes,
        corteProdutos,
        desconsiderarBalcao,
        desconsiderarDemaisProdutos,
        desconsiderarNaoHarmonizados,
        maxPorGrupo,
        clientesExcluidos: Array.from(clientesExcluidos),
        produtosExcluidos: Array.from(produtosExcluidos),
        modoClientes,
        quantidadesClientes,
        modoProdutos,
        quantidadeProdutos,
      };
      const resultado = await salvarConfiguracaoEmpresa(nomeEmpresaEfetivo, dadosParaSalvar, lojaApi);
      configRestanteRef.current = dadosParaSalvar;
      const caminho = resultado.caminho || `${caminhoTrabalho}/${nomeEmpresaEfetivo}/config.json`;
      setSucesso(`Configuração salva (${rotuloEscopoLoja}) em ${caminho}`);
    } catch (e) {
      const msg = e instanceof Error ? e.message : 'Falha ao salvar configuração da empresa.';
      setErro(msg);
      setSucesso(null);
    } finally {
      setSalvandoConfig(false);
    }
  };

  const iniciarModoQuantidadeClientes = () => {
    if (grupos && grupos.length >= 3) {
      setQuantidadesClientes([grupos[0].quantidade, grupos[1].quantidade, grupos[2].quantidade]);
    }
    setModoClientes('quantidade');
  };

  const iniciarModoQuantidadeProdutos = () => {
    if (produtosGrupos && produtosGrupos.length >= 1) {
      setQuantidadeProdutos(produtosGrupos[0].quantidade);
    }
    setModoProdutos('quantidade');
  };

  const aplicarQuantidadesClientes = () => {
    if (itensClientes.length === 0) {
      setErro('Sem prévia carregada — clique em Atualizar antes de aplicar quantidades.');
      return;
    }
    let acumulado = 0;
    let faltou = false;
    const novosCortes = quantidadesClientes.map((qtd) => {
      acumulado += Math.max(0, Math.round(qtd));
      const corte = corteNoRank(itensClientes, acumulado);
      if (corte == null) faltou = true;
      return corte ?? 100;
    }) as [number, number, number];
    setErro(faltou ? 'Quantidade pedida passa do que está carregado na prévia — peça menos itens ou ajuste os cortes % direto.' : null);
    setCortesClientes(novosCortes);
    void atualizarPreviaGrupos({ cortes: novosCortes, ajustarCortes: false });
  };

  const aplicarQuantidadeProdutos = () => {
    if (itensProdutos.length === 0) {
      setErro('Sem prévia carregada — clique em Atualizar antes de aplicar a quantidade.');
      return;
    }
    const corte = corteNoRank(itensProdutos, Math.max(0, Math.round(quantidadeProdutos)));
    if (corte == null) {
      setErro('Quantidade pedida passa do que está carregado na prévia — peça menos itens ou ajuste o corte % direto.');
      return;
    }
    setErro(null);
    setCorteProdutos(corte);
    void atualizarPreviaProdutos({ corte });
  };

  const toggleSet = (set: Set<string>, item: string, setter: (s: Set<string>) => void) => {
    const novo = new Set(set);
    if (novo.has(item)) novo.delete(item);
    else novo.add(item);
    setter(novo);
  };

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
      <LeituraFaixa>
        O item entra no primeiro grupo cujo corte o acumulado dele ainda não passa.
        {' '}{lista.map((g) => {
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
        }).join(' · ')}
      </LeituraFaixa>
    );
  };

  return (
    <AppShell>
    <div className="dashboard-container analisador-page">
      <header className="app-page-header">
        <div>
          <h1>
            Cortes
            {nomeEmpresaEfetivo && (
              <span className="analisador-header-empresa">
                <span className="analisador-header-empresa-sep" aria-hidden="true">·</span>
                <span className="analisador-header-empresa-nome">{nomeEmpresaEfetivo}</span>
                {lojasEscopo.length > 0 && (
                  <span className="analisador-header-empresa-loja"> · {rotuloEscopoLoja}</span>
                )}
              </span>
            )}
          </h1>
          <p className="app-page-header-sub">
            {empresaSelecionada
              ? `Cortes e exclusões salvos por escopo de loja em ${caminhoTrabalho || 'pasta de trabalho'}/${empresaSelecionada}/config.json.`
              : 'Selecione uma empresa na barra lateral.'}
          </p>
        </div>
        {etapa === 'config' && previa && (
          <div className="app-page-header-actions">
            <button type="button" onClick={handleCarregarConfiguracaoEmpresa} className="analisador-btn analisador-btn-sec">
              <FolderOpen size={16} /> Carregar configuração
            </button>
            <button
              type="button"
              onClick={handleSalvarConfiguracaoEmpresa}
              disabled={salvandoConfig}
              className="analisador-btn analisador-btn-pri"
            >
              <Save size={16} /> {salvandoConfig ? 'Salvando...' : 'Salvar configuração'}
            </button>
          </div>
        )}
      </header>

      {erro && (
        <div className="glass-card glass-card-flat analisador-erro" role="alert">
          {erro}
        </div>
      )}

      {sucesso && (
        <div className="glass-card glass-card-flat analisador-sucesso" role="status" aria-live="polite">
          <span>{sucesso}</span>
          <button
            type="button"
            className="analisador-sucesso-fechar"
            onClick={() => setSucesso(null)}
            aria-label="Fechar notificação"
            title="Fechar"
          >
            ×
          </button>
        </div>
      )}

      {etapa === 'carregando-base' && (
        <div className="glass-card glass-card-flat" style={{ maxWidth: 480 }}>
          <p className="analisador-hint">Carregando base de dados...</p>
        </div>
      )}

      {etapa === 'config' && previa && (
        <div className="analisador-stack">
          <div className="analisador-previas-grid">
            <div className="glass-card glass-card-flat analisador-stack-inner">
              <div className="analisador-titulo-linha">
                <h2 className="analisador-titulo">Grupos de clientes</h2>
                <div className="analisador-titulo-linha-acoes">
                  {modoClientes === 'percentual' ? (
                    <button
                      type="button"
                      onClick={handleSugerirCortes}
                      disabled={carregandoGrupos}
                      className="analisador-btn analisador-btn-sec analisador-btn-compact"
                    >
                      <Wand2 size={14} /> {carregandoGrupos ? 'Calculando...' : 'Sugerir cortes'}
                    </button>
                  ) : (
                    <button
                      type="button"
                      onClick={aplicarQuantidadesClientes}
                      disabled={carregandoGrupos}
                      className="analisador-btn analisador-btn-sec analisador-btn-compact"
                    >
                      <Wand2 size={14} /> {carregandoGrupos ? 'Calculando...' : 'Aplicar quantidades'}
                    </button>
                  )}
                  {modoClientes === 'percentual' && (
                    <button
                      type="button"
                      onClick={handleAtualizarPreviaGrupos}
                      disabled={carregandoGrupos}
                      className="analisador-btn analisador-btn-sec analisador-btn-compact"
                      title="Atualizar prévia dos grupos"
                      aria-label="Atualizar prévia dos grupos"
                    >
                      <RefreshCw size={14} />
                    </button>
                  )}
                </div>
              </div>
              <div className="periodo-segmented analisador-modo-segmented" role="radiogroup" aria-label="Modo de separação dos grupos de clientes">
                <button
                  type="button"
                  role="radio"
                  aria-checked={modoClientes === 'percentual'}
                  className={`periodo-segmented-btn${modoClientes === 'percentual' ? ' is-active' : ''}`}
                  onClick={() => setModoClientes('percentual')}
                >
                  % acumulado
                </button>
                <button
                  type="button"
                  role="radio"
                  aria-checked={modoClientes === 'quantidade'}
                  className={`periodo-segmented-btn${modoClientes === 'quantidade' ? ' is-active' : ''}`}
                  onClick={iniciarModoQuantidadeClientes}
                >
                  Quantidade por grupo
                </button>
              </div>
              {modoClientes === 'percentual' ? (
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
              ) : (
                <div className="analisador-segmentacao-linha">
                  <div className="analisador-campo">
                    <span id="qtd-abc-label">Quantidade de clientes por grupo (1/2/3)</span>
                    <div className="analisador-cortes" role="group" aria-labelledby="qtd-abc-label">
                      {quantidadesClientes.map((valor, indice) => (
                        <NumberStepper
                          key={indice}
                          value={valor}
                          ariaLabel={`Quantidade grupo ${indice + 1}`}
                          onChange={(v) => {
                            const novo = [...quantidadesClientes] as [number, number, number];
                            novo[indice] = v === '' ? 0 : v;
                            setQuantidadesClientes(novo);
                          }}
                        />
                      ))}
                    </div>
                  </div>
                  <p className="analisador-hint" style={{ width: '100%', margin: 0 }}>
                    Cada número é o tamanho do grupo (não acumulado): {quantidadesClientes[0]} no Grupo 1,
                    {' '}{quantidadesClientes[1]} no Grupo 2, {quantidadesClientes[2]} no Grupo 3. Clique em
                    "Aplicar quantidades" para converter em cortes % e atualizar a prévia.
                  </p>
                </div>
              )}
              <label className="analisador-toggle-linha">
                <span className="analisador-toggle-label">Desconsiderar clientes balcão</span>
                <input
                  type="checkbox"
                  role="switch"
                  aria-checked={desconsiderarBalcao}
                  className="analisador-toggle-switch"
                  checked={desconsiderarBalcao}
                  onChange={(e) => {
                    const checked = e.target.checked;
                    setDesconsiderarBalcao(checked);
                    void atualizarPreviaGrupos({ balcao: checked, ajustarCortes: false });
                  }}
                />
              </label>
              {resumoGrupos(grupos, 'clientes', clientesExcluidosPorGrupo)}
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
                {modoClientes === 'percentual'
                  ? `Cortes ajustados automaticamente para ≤${maxPorGrupo} por grupo (exceto Demais: até 300 na prévia; contagem total acima).`
                  : 'Demais: até 300 na prévia; contagem total acima.'}
              </p>
            </div>

            <div className="glass-card glass-card-flat analisador-stack-inner">
              <div className="analisador-titulo-linha">
                <h2 className="analisador-titulo">Grupos de produtos</h2>
                <div className="analisador-titulo-linha-acoes">
                  {modoProdutos === 'percentual' ? (
                    <button
                      type="button"
                      onClick={handleSugerirCorteProdutos}
                      disabled={carregandoProdutos}
                      className="analisador-btn analisador-btn-sec analisador-btn-compact"
                      title={`Recalcula o corte para o alto giro caber em ${maxPorGrupo} produtos`}
                    >
                      <Wand2 size={14} /> {carregandoProdutos ? 'Calculando...' : 'Sugerir corte'}
                    </button>
                  ) : (
                    <button
                      type="button"
                      onClick={aplicarQuantidadeProdutos}
                      disabled={carregandoProdutos}
                      className="analisador-btn analisador-btn-sec analisador-btn-compact"
                    >
                      <Wand2 size={14} /> {carregandoProdutos ? 'Calculando...' : 'Aplicar quantidade'}
                    </button>
                  )}
                  {modoProdutos === 'percentual' && (
                    <button
                      type="button"
                      onClick={handleAtualizarPreviaProdutos}
                      disabled={carregandoProdutos}
                      className="analisador-btn analisador-btn-sec analisador-btn-compact"
                      title="Atualizar prévia dos produtos"
                      aria-label="Atualizar prévia dos produtos"
                    >
                    <RefreshCw size={14} />
                    </button>
                  )}
                </div>
              </div>
              <div className="periodo-segmented analisador-modo-segmented" role="radiogroup" aria-label="Modo de separação do alto giro de produtos">
                <button
                  type="button"
                  role="radio"
                  aria-checked={modoProdutos === 'percentual'}
                  className={`periodo-segmented-btn${modoProdutos === 'percentual' ? ' is-active' : ''}`}
                  onClick={() => setModoProdutos('percentual')}
                >
                  % acumulado
                </button>
                <button
                  type="button"
                  role="radio"
                  aria-checked={modoProdutos === 'quantidade'}
                  className={`periodo-segmented-btn${modoProdutos === 'quantidade' ? ' is-active' : ''}`}
                  onClick={iniciarModoQuantidadeProdutos}
                >
                  Quantidade no alto giro
                </button>
              </div>
              {modoProdutos === 'percentual' ? (
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
              ) : (
                <div className="analisador-segmentacao-linha">
                  <label className="analisador-campo">
                    <span>Quantidade de produtos no alto giro</span>
                    <div className="analisador-cortes">
                      <NumberStepper
                        value={quantidadeProdutos}
                        onChange={(v) => setQuantidadeProdutos(v === '' ? 0 : v)}
                      />
                    </div>
                  </label>
                  <p className="analisador-hint" style={{ width: '100%', margin: 0 }}>
                    Clique em "Aplicar quantidade" para converter em corte % e atualizar a prévia.
                  </p>
                </div>
              )}
              <div className="analisador-toggle-grupo">
                <label className="analisador-toggle-linha">
                  <span className="analisador-toggle-label" title="Desconsiderar os demais nos relatórios">Desconsiderar os demais nos relatórios</span>
                  <input
                    type="checkbox"
                    role="switch"
                    aria-checked={desconsiderarDemaisProdutos}
                    className="analisador-toggle-switch"
                    checked={desconsiderarDemaisProdutos}
                    onChange={(e) => handleToggleDesconsiderarDemais(e.target.checked)}
                  />
                </label>
                <label className="analisador-toggle-linha">
                  <span className="analisador-toggle-label" title='Desconsiderar "não harmonizados"'>Desconsiderar "não harmonizados"</span>
                  <input
                    type="checkbox"
                    role="switch"
                    aria-checked={desconsiderarNaoHarmonizados}
                    className="analisador-toggle-switch"
                    checked={desconsiderarNaoHarmonizados}
                    onChange={(e) => handleToggleDesconsiderarNaoHarmonizados(e.target.checked)}
                  />
                </label>
              </div>
              {resumoGrupos(produtosGrupos, 'produtos', produtosExcluidosPorGrupo)}
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
                {modoProdutos === 'percentual'
                  ? `O corte % acima é o que manda — ele só muda quando você clica em "Sugerir corte", que o recalcula para o alto giro caber em ${maxPorGrupo} produtos (o mesmo máximo por grupo dos clientes). Demais: até 300 na prévia; contagem total abaixo.`
                  : 'A quantidade acima só vale depois de clicar em "Aplicar quantidade" — ela converte para o corte % e atualiza a prévia. Demais: até 300 na prévia; contagem total abaixo.'}
              </p>
            </div>
          </div>
        </div>
      )}
    </div>
    </AppShell>
  );
}
