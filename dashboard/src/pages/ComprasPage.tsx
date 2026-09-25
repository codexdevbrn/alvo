import { useEffect, useState } from 'react';
import { createPortal } from 'react-dom';
import { useSearchParams } from 'react-router-dom';
import { AlertTriangle, Search, ShoppingCart, X } from 'lucide-react';
import { AppShell } from '../components/AppShell';
import { PainelItemCompras } from '../components/compras/PainelItemCompras';
import { TabelaCompras, TabelaComprasEsqueleto } from '../components/compras/TabelaCompras';
import { chaveProduto, moedaOuTraco, type Selecao } from '../components/compras/formatoCompras';
import { obterCompras } from '../api/client';
import { useDebouncedValue } from '../hooks/useDebouncedValue';
import { useEscopoAtual } from '../hooks/useEscopoAtual';
import { useGruposClientesFiltro } from '../hooks/useGruposClientesFiltro';
import { useVersaoCortesRelatorios } from '../hooks/useVersaoCortesRelatorios';
import { gruposClientesParam } from '../utils/gruposClientesFiltro';
import type { ComprasResposta, GiroCompras, PrazoEntrega } from '../types/compras';

const PRAZOS: { id: PrazoEntrega; rotulo: string }[] = [
  { id: 'imediato', rotulo: 'Imediato' },
  { id: 'regular', rotulo: 'Regular' },
  { id: 'industria', rotulo: 'Indústria' },
];

const GIROS: { id: GiroCompras; rotulo: string }[] = [
  { id: 'impulsionado', rotulo: 'Impulsionado' },
  { id: 'nao_impulsionado', rotulo: 'Não impulsionado' },
];

const BREAKPOINT_DRAWER = 1024;

/** Cenário na URL (`?prazo=regular&giro=nao&caixa=1&todos=1`): link compartilhado
 *  abre o mesmo cenário. Valor que não reconhece cai no padrão. */
function lerCenario(params: URLSearchParams) {
  const prazo = params.get('prazo');
  return {
    prazo: (PRAZOS.some((p) => p.id === prazo) ? prazo : 'imediato') as PrazoEntrega,
    giro: (params.get('giro') === 'nao' ? 'nao_impulsionado' : 'impulsionado') as GiroCompras,
    caixa: params.get('caixa') === '1',
    somenteRecomendados: params.get('todos') !== '1',
  };
}

function useTelaEstreita(): boolean {
  const consulta = `(max-width: ${BREAKPOINT_DRAWER}px)`;
  const [estreita, setEstreita] = useState(() => window.matchMedia(consulta).matches);
  useEffect(() => {
    const mq = window.matchMedia(consulta);
    const aoMudar = () => setEstreita(mq.matches);
    mq.addEventListener('change', aoMudar);
    return () => mq.removeEventListener('change', aoMudar);
  }, [consulta]);
  return estreita;
}

/** Tela Compras: o que repor, por produto, a partir da venda dos últimos 12
 *  meses e do estoque atual. Regras em `backend/compras.py`. */
export default function ComprasPage() {
  const { empresa, loja } = useEscopoAtual();
  return (
    <AppShell>
      <div className="dashboard-container estoque-page">
        <header className="app-page-header estoque-page-header">
          <div>
            <h1>Compras{empresa && <span className="analisador-header-empresa"> · {empresa}</span>}</h1>
            <p>O que repor, a partir da venda dos últimos 12 meses</p>
          </div>
        </header>
        {empresa ? (
          // Trocar de empresa zera fabricante, busca e seleção.
          <Compras key={empresa} empresa={empresa} loja={loja} />
        ) : (
          <div className="glass-card glass-card-flat estoque-vazio">
            <ShoppingCart size={24} aria-hidden="true" />
            <div>
              <strong>Selecione uma empresa</strong>
              <p>Use o seletor no topo para calcular as compras.</p>
            </div>
          </div>
        )}
      </div>
    </AppShell>
  );
}

function Compras({ empresa, loja }: { empresa: string; loja: string | null }) {
  const [params, setParams] = useSearchParams();
  const cenario = lerCenario(params);
  const [fabricante, setFabricante] = useState('');
  const [busca, setBusca] = useState('');
  const buscaAplicada = useDebouncedValue(busca, 300);
  const [selecao, setSelecionado] = useState<Selecao | null>(null);
  const [abertos, setAbertos] = useState<Set<string>>(() => new Set());
  const [tentativa, setTentativa] = useState(0);
  const versaoCortes = useVersaoCortesRelatorios();
  const gruposParam = gruposClientesParam(useGruposClientesFiltro());
  const estreita = useTelaEstreita();

  const { prazo, giro, caixa, somenteRecomendados } = cenario;
  const termo = buscaAplicada.trim();
  const chave = JSON.stringify([
    empresa, loja, prazo, giro, caixa, somenteRecomendados, fabricante, termo, gruposParam, versaoCortes, tentativa,
  ]);
  // Última lista de fabricantes: o select não pisca nem encolhe enquanto a próxima resposta chega.
  const [fabricantes, setFabricantes] = useState<string[]>([]);
  const [resultado, setResultado] = useState<{ chave: string; dados: ComprasResposta | null; erro: string | null } | null>(null);
  const carregando = resultado?.chave !== chave;
  const dados = carregando ? null : resultado?.dados ?? null;
  const erro = carregando ? null : resultado?.erro ?? null;

  useEffect(() => {
    // Resposta atrasada não sobrescreve a nova: a anterior é cancelada.
    const controle = new AbortController();
    obterCompras(
      empresa,
      {
        prazo_entrega: prazo,
        giro,
        caixa_apertado: caixa,
        somenteRecomendados,
        loja,
        fabricante: fabricante || null,
        busca: termo,
        grupos: gruposParam,
      },
      controle.signal,
    )
      .then((resposta) => {
        setResultado({ chave, dados: resposta, erro: null });
        setFabricantes(resposta.fabricantes);
      })
      .catch((e: unknown) => {
        if (controle.signal.aborted) return;
        setResultado({ chave, dados: null, erro: e instanceof Error ? e.message : 'Falha ao calcular as compras.' });
      });
    return () => controle.abort();
  }, [chave, empresa, loja, prazo, giro, caixa, somenteRecomendados, fabricante, termo, gruposParam]);

  // Fecha o drawer com Esc.
  useEffect(() => {
    if (!estreita || !selecao) return;
    const aoTeclar = (evento: KeyboardEvent) => {
      if (evento.key === 'Escape') setSelecionado(null);
    };
    window.addEventListener('keydown', aoTeclar);
    return () => window.removeEventListener('keydown', aoTeclar);
  }, [estreita, selecao]);

  const mudarCenario = (mudanca: Partial<Record<'prazo' | 'giro' | 'caixa' | 'todos', string | null>>) => {
    const proximo = new URLSearchParams(params);
    for (const [nome, valor] of Object.entries(mudanca)) {
      if (valor == null) proximo.delete(nome);
      else proximo.set(nome, valor);
    }
    setParams(proximo, { replace: true });
  };

  const produtoAtivo = selecao ? dados?.itens.find((p) => chaveProduto(p) === selecao.chave) ?? null : null;
  const skuAtivo = selecao?.tipo === 'sku' ? produtoAtivo?.skus.find((s) => s.codigo === selecao.codigo) ?? null : null;
  const alternar = (chave: string) => setAbertos((atual) => {
    const proximo = new Set(atual);
    if (proximo.has(chave)) proximo.delete(chave);
    else proximo.add(chave);
    return proximo;
  });
  const nuncaCompra = giro === 'nao_impulsionado' && caixa;

  return (
    <div className="prec-hist compras" aria-busy={carregando}>
      <section className="glass-card glass-card-flat compras-parametros" aria-label="Parâmetros da compra">
        <Segmentado
          rotulo="Prazo de entrega"
          opcoes={PRAZOS}
          valor={prazo}
          desabilitado={carregando}
          onMudar={(id) => mudarCenario({ prazo: id === 'imediato' ? null : id })}
        />
        <Segmentado
          rotulo="Giro"
          opcoes={GIROS}
          valor={giro}
          desabilitado={carregando}
          onMudar={(id) => mudarCenario({ giro: id === 'nao_impulsionado' ? 'nao' : null })}
        />
        <Segmentado
          rotulo="Caixa apertado"
          opcoes={[{ id: 'sim', rotulo: 'Sim' }, { id: 'nao', rotulo: 'Não' }]}
          valor={caixa ? 'sim' : 'nao'}
          desabilitado={carregando}
          onMudar={(id) => mudarCenario({ caixa: id === 'sim' ? '1' : null })}
        />
        <label className="compras-toggle">
          <input
            type="checkbox"
            role="switch"
            checked={somenteRecomendados}
            disabled={carregando}
            onChange={(e) => mudarCenario({ todos: e.target.checked ? null : '1' })}
          />
          <span className="compras-toggle-trilho" aria-hidden="true" />
          Somente recomendados
        </label>
      </section>

      {nuncaCompra && (
        <div className="compras-alerta" role="status">
          <AlertTriangle size={14} aria-hidden="true" />
          Caixa apertado: itens não impulsionados não são comprados neste cenário.
        </div>
      )}

      {erro ? (
        <div className="compras-erro" role="alert">
          <AlertTriangle size={16} aria-hidden="true" />
          <span>{erro}</span>
          <button type="button" className="compras-botao" onClick={() => setTentativa((n) => n + 1)}>
            Tentar de novo
          </button>
        </div>
      ) : (
        <>
          <div className="prec-indicadores">
            <Indicador
              rotulo="Produtos a comprar"
              valor={dados?.produtos_a_comprar.toLocaleString('pt-BR')}
              detalhe={dados ? `${dados.itens_a_comprar.toLocaleString('pt-BR')} SKUs com sugestão maior que zero` : 'SKUs com sugestão maior que zero'}
              acento="var(--accent)"
            />
            <Indicador
              rotulo="Valor do pedido"
              valor={dados ? moedaOuTraco(dados.total_compra) : undefined}
              detalhe="custo médio recente × sugestão"
              acento="var(--text-muted)"
            />
            <Indicador
              rotulo="SKUs sem custo"
              valor={dados?.produtos_sem_custo.toLocaleString('pt-BR')}
              detalhe="sem venda nos últimos 3 meses fechados · fora do total"
              acento={dados && dados.produtos_sem_custo > 0 ? 'var(--danger)' : 'var(--surface-4)'}
            />
            <Indicador
              rotulo="SKUs não recomendados"
              valor={dados?.nao_recomendados.toLocaleString('pt-BR')}
              detalhe="estoque já cobre o alvo"
              acento="var(--surface-4)"
            />
          </div>

          <div className="compras-filtros">
            <label className="compras-select">
              <span className="sr-only">Fabricante</span>
              <select value={fabricante} onChange={(e) => { setFabricante(e.target.value); setSelecionado(null); }}>
                <option value="">Fabricante: todos</option>
                {fabricantes.map((nome) => <option key={nome} value={nome}>{nome}</option>)}
              </select>
            </label>
            <label className="prec-busca compras-busca">
              <Search size={13} aria-hidden="true" />
              <input
                type="search"
                value={busca}
                onChange={(e) => setBusca(e.target.value)}
                placeholder="Buscar por descrição ou código…"
                aria-label="Buscar produto por descrição ou código"
              />
            </label>
            {dados?.limitado && (
              <span className="prec-mudo compras-limitado">
                Mostrando os {dados.itens_exibidos.toLocaleString('pt-BR')} produtos de maior valor · KPIs com o total
              </span>
            )}
          </div>

          <div className="prec-corpo compras-corpo">
            <section className="glass-card glass-card-flat prec-card">
              {!dados ? (
                <TabelaComprasEsqueleto />
              ) : dados.itens.length === 0 ? (
                <Vazio
                  somenteRecomendados={somenteRecomendados}
                  onMostrarTodos={() => mudarCenario({ todos: '1' })}
                />
              ) : (
                <>
                  <TabelaCompras
                    produtos={dados.itens}
                    abertos={abertos}
                    selecao={selecao}
                    onAlternar={alternar}
                    onSelecionar={setSelecionado}
                  />
                  <p className="prec-mudo prec-rodape">
                    Ordem: valor decrescente. Sem custo fica no fim, fora do total. Cálculo por loja, somado no produto.
                  </p>
                </>
              )}
            </section>

            {!estreita && (
              <aside className="glass-card glass-card-flat prec-painel" aria-label="Detalhe do item">
                <PainelItemCompras produto={produtoAtivo} sku={skuAtivo} meses={dados?.meses ?? []} />
              </aside>
            )}
          </div>
        </>
      )}

      {/* Portal: o `will-change: transform` do .app-shell-main prenderia o fixed dentro dele, sob a barra do topo. */}
      {estreita && produtoAtivo && createPortal(
        <div className="compras-drawer-fundo" onClick={() => setSelecionado(null)}>
          <aside
            className="compras-drawer prec-painel"
            role="dialog"
            aria-modal="true"
            aria-label={`Detalhe de ${skuAtivo?.codigo ?? produtoAtivo.descricao}`}
            onClick={(e) => e.stopPropagation()}
          >
            <button type="button" className="compras-drawer-fechar" aria-label="Fechar detalhe" onClick={() => setSelecionado(null)}>
              <X size={16} aria-hidden="true" />
            </button>
            <PainelItemCompras produto={produtoAtivo} sku={skuAtivo} meses={dados?.meses ?? []} />
          </aside>
        </div>,
        document.body,
      )}
    </div>
  );
}

function Segmentado<T extends string>({
  rotulo,
  opcoes,
  valor,
  desabilitado,
  onMudar,
}: {
  rotulo: string;
  opcoes: { id: T; rotulo: string }[];
  valor: T;
  desabilitado: boolean;
  onMudar: (id: T) => void;
}) {
  return (
    <div className="compras-campo" role="radiogroup" aria-label={rotulo}>
      <span className="prec-rotulo">{rotulo}</span>
      <div className="compras-seg">
        {opcoes.map((opcao) => (
          <button
            key={opcao.id}
            type="button"
            role="radio"
            aria-checked={valor === opcao.id}
            disabled={desabilitado}
            className={valor === opcao.id ? 'is-ativo' : undefined}
            onClick={() => valor !== opcao.id && onMudar(opcao.id)}
          >
            {opcao.rotulo}
          </button>
        ))}
      </div>
    </div>
  );
}

function Indicador({ rotulo, valor, detalhe, acento }: { rotulo: string; valor?: string; detalhe: string; acento: string }) {
  return (
    <div
      className={`glass-card glass-card-flat prec-indicador${valor == null ? ' is-esqueleto' : ''}`}
      style={{ ['--prec-acento' as string]: acento }}
    >
      <span className="prec-rotulo">{rotulo}</span>
      <strong>{valor ?? ' '}</strong>
      <em>{detalhe}</em>
    </div>
  );
}

function Vazio({ somenteRecomendados, onMostrarTodos }: { somenteRecomendados: boolean; onMostrarTodos: () => void }) {
  if (somenteRecomendados) {
    return (
      <p className="prec-vazio compras-vazio">
        Nada a comprar neste cenário.{' '}
        <button type="button" className="compras-link" onClick={onMostrarTodos}>Mostrar todos</button>
      </p>
    );
  }
  return <p className="prec-vazio compras-vazio">Nenhum produto encontrado com estes filtros.</p>;
}
