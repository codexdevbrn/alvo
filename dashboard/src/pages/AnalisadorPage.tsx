import { useEffect, useMemo, useState } from 'react';
import { AppShell } from '../components/AppShell';
import { Download } from 'lucide-react';
import {
  analisar,
  exportarRelatorio,
  type FormatoExportacao,
  obterBase,
  obterCatalogo,
  tentarCarregarConfiguracaoEmpresa,
  type CategoriaCatalogo,
  type ConfigEmpresaSalva,
  type ParametrosAnalise,
  type ResultadoAnalise,
} from '../api/client';
import { ResultTable } from '../components/analisador/ResultTable';
import { TendenciaProdutosView } from '../components/analisador/TendenciaProdutosView';
import { ExportarModal } from '../components/analisador/ExportarModal';
import { ExplorarBuilder } from '../components/analisador/ExplorarBuilder';
import { useEscopoAtual } from '../hooks/useEscopoAtual';
import {
  CORTES_CLIENTES_PADRAO,
  CORTE_PRODUTOS_PADRAO,
} from '../utils/configAnalisador';

type Etapa = 'config' | 'resultados';
type AbaWorkspace = 'relatorios' | 'graficos' | 'tabelas';

const ABAS_WORKSPACE: { id: AbaWorkspace; rotulo: string }[] = [
  { id: 'relatorios', rotulo: 'Relatórios' },
  { id: 'graficos', rotulo: 'Gráficos' },
  { id: 'tabelas', rotulo: 'Tabelas' },
];

/** Parâmetros de corte/exclusão são editados na tela Cortes e só lidos aqui, no
 *  config.json salvo — esta tela não os edita nem exige um Salvar antes de gerar. */
type ConfigCorteSalvo = Pick<
  ConfigEmpresaSalva,
  | 'cortesClientes'
  | 'corteProdutos'
  | 'desconsiderarBalcao'
  | 'desconsiderarDemaisProdutos'
  | 'desconsiderarNaoHarmonizados'
  | 'clientesExcluidos'
  | 'produtosExcluidos'
  | 'periodosQueda'
  | 'excluirPeriodoAtual'
  | 'erosaoSomenteProdutosEmAlerta'
  | 'topNProdutos'
  | 'reducaoMinimaErosao'
  | 'quedaMinimaAlertaRs'
  | 'quedaMinimaErosaoRs'
  | 'reducaoMinimaSemVenda'
  | 'topNPoderCompra'
>;

const CONFIG_CORTE_PADRAO: ConfigCorteSalvo = {
  cortesClientes: CORTES_CLIENTES_PADRAO,
  corteProdutos: CORTE_PRODUTOS_PADRAO,
  desconsiderarBalcao: false,
  desconsiderarDemaisProdutos: false,
  desconsiderarNaoHarmonizados: false,
  clientesExcluidos: [],
  produtosExcluidos: [],
  periodosQueda: 2,
  excluirPeriodoAtual: true,
  erosaoSomenteProdutosEmAlerta: false,
  topNProdutos: '',
  reducaoMinimaErosao: 50,
  quedaMinimaAlertaRs: 3000,
  quedaMinimaErosaoRs: 3000,
  reducaoMinimaSemVenda: 90,
  topNPoderCompra: '',
};

export default function AnalisadorPage() {
  const { empresa: empresaSelecionada, lojas: lojasEscopo, loja: lojaApi } = useEscopoAtual();
  const empresaBase = empresaSelecionada || null;

  const [etapa, setEtapa] = useState<Etapa>('config');
  const [erro, setErro] = useState<string | null>(null);
  const [carregando, setCarregando] = useState(false);

  const [catalogo, setCatalogo] = useState<CategoriaCatalogo[]>([]);
  const [resultados, setResultados] = useState<ResultadoAnalise | null>(null);
  const [resultadoId, setResultadoId] = useState<string | null>(null);
  const [abaAtiva, setAbaAtiva] = useState<string | null>(null);
  const [formatoParaConfirmar, setFormatoParaConfirmar] = useState<FormatoExportacao | null>(null);

  const [chavesSelecionadas, setChavesSelecionadas] = useState<Set<string>>(new Set());
  const [granularidade, setGranularidade] = useState('Mensal');
  const [configCorte, setConfigCorte] = useState<ConfigCorteSalvo>(CONFIG_CORTE_PADRAO);

  const [abaWorkspace, setAbaWorkspace] = useState<AbaWorkspace>('relatorios');

  useEffect(() => {
    obterCatalogo()
      .then(setCatalogo)
      .catch((e) => setErro(e instanceof Error ? e.message : 'Falha ao carregar catálogo.'));
  }, []);

  // Recarrega o catálogo ao entrar na aba Relatórios (pega categorias novas sem F5).
  useEffect(() => {
    if (abaWorkspace !== 'relatorios') return;
    obterCatalogo()
      .then(setCatalogo)
      .catch(() => {});
  }, [abaWorkspace]);

  // Carrega, só para leitura, os cortes/exclusões salvos em Cortes para este
  // escopo — e a granularidade disponível na base. Sem modal de confirmação:
  // esta tela usa direto o que estiver salvo (ou o padrão, se nada foi salvo).
  useEffect(() => {
    let cancelado = false;
    (async () => {
      try {
        const [dadosConfig, base] = await Promise.all([
          empresaSelecionada ? tentarCarregarConfiguracaoEmpresa(empresaSelecionada, lojaApi) : Promise.resolve(null),
          obterBase(empresaBase, lojaApi),
        ]);
        if (cancelado) return;
        setConfigCorte(dadosConfig ? { ...CONFIG_CORTE_PADRAO, ...dadosConfig } : CONFIG_CORTE_PADRAO);
        if (base.granularidades.length > 0) {
          setGranularidade((atual) =>
            base.granularidades.includes(atual) ? atual : base.granularidades[0],
          );
        }
      } catch (e) {
        if (cancelado) return;
        setErro(e instanceof Error ? e.message : 'Falha ao carregar configuração da empresa.');
      }
    })();
    return () => { cancelado = true; };
  }, [empresaSelecionada, empresaBase, lojaApi]);

  const montarParametros = (): ParametrosAnalise => ({
    granularidades: [granularidade],
    chaves_selecionadas: Array.from(chavesSelecionadas),
    clientes_excluidos: configCorte.clientesExcluidos ?? [],
    produtos_excluidos: configCorte.produtosExcluidos ?? [],
    cortes_clientes: configCorte.cortesClientes ?? CORTES_CLIENTES_PADRAO,
    corte_produtos: configCorte.corteProdutos ?? CORTE_PRODUTOS_PADRAO,
    periodos_queda_consecutiva: configCorte.periodosQueda ?? 2,
    desconsiderar_balcao: Boolean(configCorte.desconsiderarBalcao),
    excluir_periodo_atual: configCorte.excluirPeriodoAtual ?? true,
    erosao_somente_produtos_em_alerta: Boolean(configCorte.erosaoSomenteProdutosEmAlerta),
    desconsiderar_demais_produtos: Boolean(configCorte.desconsiderarDemaisProdutos),
    desconsiderar_nao_harmonizados: Boolean(configCorte.desconsiderarNaoHarmonizados),
    top_n_produtos: configCorte.topNProdutos === '' || configCorte.topNProdutos == null ? null : configCorte.topNProdutos,
    reducao_minima_erosao: configCorte.reducaoMinimaErosao ?? 50,
    queda_minima_alerta_rs: configCorte.quedaMinimaAlertaRs === '' || configCorte.quedaMinimaAlertaRs == null ? 0 : configCorte.quedaMinimaAlertaRs,
    queda_minima_erosao_rs: configCorte.quedaMinimaErosaoRs === '' || configCorte.quedaMinimaErosaoRs == null ? 0 : configCorte.quedaMinimaErosaoRs,
    reducao_minima_sem_venda: configCorte.reducaoMinimaSemVenda ?? 90,
    top_n_poder_compra: configCorte.topNPoderCompra === '' || configCorte.topNPoderCompra == null ? null : configCorte.topNPoderCompra,
    nome_empresa: empresaSelecionada,
    nome_usuario: '',
    empresa: empresaBase,
    loja: lojaApi,
  });

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

  return (
    <AppShell>
    <div className="dashboard-container analisador-page">
      <header className="app-page-header">
        <div>
          <h1>
            Relatórios
            {empresaSelecionada && (
              <span className="analisador-header-empresa">
                <span className="analisador-header-empresa-sep" aria-hidden="true">·</span>
                <span className="analisador-header-empresa-nome">{empresaSelecionada}</span>
                {lojasEscopo.length > 0 && (
                  <span className="analisador-header-empresa-loja"> · {lojasEscopo.length === 1 ? lojasEscopo[0] : `${lojasEscopo.length} lojas`}</span>
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

      {etapa === 'config' && (
        <div className="analisador-stack">
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
                {aba.chave === 'evolucao_produtos'
                  ? <TendenciaProdutosView tabela={aba.tabela} />
                  : <ResultTable tabela={aba.tabela} chave={aba.chave} />}
              </div>
            )
          ))}
        </div>
      )}
    </div>
    </AppShell>
  );
}
