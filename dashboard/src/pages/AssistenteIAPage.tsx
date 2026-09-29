import {
  useEffect,
  useRef,
  useState,
  type FormEvent,
  type KeyboardEvent,
} from 'react';
import {
  AlertTriangle,
  BookOpen,
  Bot,
  CalendarClock,
  CheckCircle2,
  Database,
  FileText,
  Loader2,
  RotateCcw,
  Send,
  ShieldAlert,
  Sparkles,
  X,
  XCircle,
} from 'lucide-react';
import { AppShell } from '../components/AppShell';
import { MarkdownResposta } from '../components/assistente/MarkdownResposta';
import { PassosAgenteAoVivo, PassosAgenteResumo, type PassoLocal } from '../components/assistente/PassosAgente';
import { semFrontmatter } from '../utils/markdown';
import {
  conversarChatIAStream,
  obterAnaliseChatIA,
  obterContextoChatIA,
  type AnaliseEmpresaIA,
  type ChatIAMensagem,
  type ContextoChatIA,
} from '../api/client';
import { useEscopoAtual } from '../hooks/useEscopoAtual';

interface MensagemLocal extends ChatIAMensagem {
  id: string;
  /** O que o agente consultou para chegar nesta resposta. */
  passos?: PassoLocal[];
  segundos?: number;
}

function criarId(): string {
  return typeof crypto !== 'undefined' && 'randomUUID' in crypto
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random()}`;
}

const MOTIVOS_DADOS: Record<string, string> = {
  trabalho_nao_configurado: 'Pasta de trabalho não configurada',
  sem_pasta_prisma: 'Empresa sem pasta na pasta de trabalho',
  mapeamento_ambiguo: 'Mais de uma pasta corresponde à empresa',
  summary_ausente: 'Base ainda não foi gerada',
  resumo_monitor_ausente: 'Resumo de monitoramento ausente',
  dados_extensos: 'Base excede o limite seguro do chat',
};

const SUGESTOES = [
  'Qual o principal risco desta empresa hoje?',
  'Como está a tendência comercial nos últimos meses?',
  'Onde está o capital parado no estoque?',
  'Quais oportunidades de venda aparecem nos dados?',
  'Monte a pauta da próxima reunião.',
];

const CLASSE_RISCO: Record<string, string> = {
  baixo: 'is-baixo',
  médio: 'is-medio',
  medio: 'is-medio',
  alto: 'is-alto',
};

function formatarData(valor: string | null): string {
  if (!valor) return 'Não disponível';
  const data = new Date(valor);
  if (Number.isNaN(data.getTime())) return 'Data não informada';
  return new Intl.DateTimeFormat('pt-BR', {
    dateStyle: 'short',
    timeStyle: 'short',
  }).format(data);
}

/**
 * Revela o texto em escrita aos poucos, a cada quadro de tela.
 *
 * O Claude entrega em rajadas (um pedaço de várias palavras de cada vez); sem
 * isto o texto e o cursor davam saltos. O passo cresce com o atraso — ~1/10 do
 * que falta por quadro —, então a tela nunca fica muito atrás do que já chegou.
 */
function useTextoSuave(alvo: string): string {
  const [exibido, setExibido] = useState('');
  const atualRef = useRef('');

  useEffect(() => {
    let quadro = 0;
    const avancar = () => {
      // Nova tentativa ou nova resposta: o texto recomeça do zero.
      const atual = alvo.startsWith(atualRef.current) ? atualRef.current : '';
      if (atual.length >= alvo.length) {
        if (atual !== atualRef.current || exibido !== atual) {
          atualRef.current = atual;
          setExibido(atual);
        }
        return;
      }
      const falta = alvo.length - atual.length;
      const proximo = alvo.slice(0, atual.length + Math.max(1, Math.ceil(falta / 10)));
      atualRef.current = proximo;
      setExibido(proximo);
      quadro = requestAnimationFrame(avancar);
    };
    quadro = requestAnimationFrame(avancar);
    return () => cancelAnimationFrame(quadro);
    // `exibido` fica fora: ele muda a cada quadro e reiniciaria o laço.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [alvo]);

  return exibido;
}

/** Por que a conversa não abre, em linguagem de quem usa a tela. */
function motivoIndisponivel(contexto: ContextoChatIA): { titulo: string; texto: string } | null {
  if (contexto.pronto) return null;
  if (!contexto.crm.disponivel && !contexto.provisorio) {
    return {
      titulo: 'O CRM desta empresa ainda não chegou',
      texto: 'A conversa usa o dossiê do CRM como base. Assim que ele for publicado na pasta da carteira, a análise diária é gerada e o assistente libera.',
    };
  }
  if (!contexto.analise.disponivel) {
    return {
      titulo: 'A análise diária ainda não foi gerada',
      texto: 'Ela sai no lote da manhã, depois que a base da empresa é atualizada. Volte após a próxima passada do lote.',
    };
  }
  const codigo = contexto.analise.resumo?.erro_codigo;
  return {
    titulo: 'A última análise diária falhou',
    texto: `O lote tenta de novo na próxima passada.${codigo ? ` Código do erro: ${codigo}.` : ''}`,
  };
}

/** Chat executivo: histórico local; CRM e chave permanecem no backend. */
export default function AssistenteIAPage() {
  const { empresa } = useEscopoAtual();
  const [contexto, setContexto] = useState<ContextoChatIA | null>(null);
  const [mensagens, setMensagens] = useState<MensagemLocal[]>([]);
  const [rascunho, setRascunho] = useState('');
  const [refazendo, setRefazendo] = useState(false);
  const [pergunta, setPergunta] = useState('');
  const [carregandoContexto, setCarregandoContexto] = useState(false);
  const [enviando, setEnviando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);
  const [erroContexto, setErroContexto] = useState<string | null>(null);
  const [analiseAberta, setAnaliseAberta] = useState(false);
  const fimRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const envioRef = useRef<AbortController | null>(null);
  const rascunhoExibido = useTextoSuave(rascunho);
  const [passos, setPassos] = useState<PassoLocal[]>([]);
  const [segundos, setSegundos] = useState(0);

  // Relógio da espera: só corre enquanto há pergunta em andamento.
  useEffect(() => {
    if (!enviando) return;
    const inicio = Date.now();
    const intervalo = window.setInterval(() => setSegundos(Math.round((Date.now() - inicio) / 1000)), 1000);
    return () => window.clearInterval(intervalo);
  }, [enviando]);

  useEffect(() => {
    envioRef.current?.abort();
    setMensagens([]);
    setRascunho('');
    setPergunta('');
    setErro(null);
    setErroContexto(null);
    setContexto(null);
    setAnaliseAberta(false);
    if (!empresa) return;

    const controller = new AbortController();
    setCarregandoContexto(true);
    void obterContextoChatIA(empresa, controller.signal)
      .then(setContexto)
      .catch((falha) => {
        if (falha instanceof DOMException && falha.name === 'AbortError') return;
        setErroContexto(falha instanceof Error ? falha.message : 'Falha ao carregar contexto da empresa.');
      })
      .finally(() => {
        if (!controller.signal.aborted) setCarregandoContexto(false);
      });
    return () => controller.abort();
  }, [empresa]);

  useEffect(() => {
    fimRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
  }, [enviando, mensagens, rascunhoExibido]);

  useEffect(() => () => envioRef.current?.abort(), []);

  const limparConversa = () => {
    envioRef.current?.abort();
    setMensagens([]);
    setRascunho('');
    setErro(null);
    window.setTimeout(() => textareaRef.current?.focus(), 0);
  };

  const perguntar = async (textoBruto: string) => {
    const texto = textoBruto.trim();
    if (!texto || !empresa || !contexto?.pronto || enviando) return;

    const mensagemUsuario: MensagemLocal = { id: criarId(), role: 'user', content: texto };
    const historico = [...mensagens, mensagemUsuario].slice(-12);
    setMensagens(historico);
    setPergunta('');
    setErro(null);
    setRascunho('');
    setRefazendo(false);
    setPassos([]);
    setSegundos(0);
    setEnviando(true);
    const controller = new AbortController();
    envioRef.current = controller;
    const inicio = Date.now();
    let tentativas = 0;
    // Cópia local: o fechamento da resposta precisa da lista final, e o estado
    // do React ainda não refletiria os últimos passos naquele instante.
    let passosLocais: PassoLocal[] = [];
    const atualizarPassos = (proximos: PassoLocal[]) => {
      passosLocais = proximos;
      setPassos(proximos);
    };
    try {
      const { resposta } = await conversarChatIAStream(
        empresa,
        historico.map(({ role, content }) => ({ role, content })),
        {
          aoIniciar: () => {
            tentativas += 1;
            setRascunho('');
            setRefazendo(tentativas > 1);
          },
          aoReceber: (pedaco) => setRascunho((atual) => atual + pedaco),
          aoPasso: (passo) => {
            if (passo.estado === 'andamento') {
              // Texto escrito antes de uma consulta é preâmbulo, não a resposta.
              setRascunho('');
              atualizarPassos([...passosLocais, { ...passo, texto: passo.texto ?? 'Consultando o Prisma' }]);
            } else {
              atualizarPassos(passosLocais.map((p) => (p.id === passo.id ? { ...p, estado: passo.estado } : p)));
            }
          },
        },
        controller.signal,
      );
      setMensagens((atuais) => [...atuais, {
        id: criarId(),
        role: 'assistant',
        content: resposta,
        passos: passosLocais,
        segundos: Math.round((Date.now() - inicio) / 1000),
      }]);
    } catch (falha) {
      if (falha instanceof DOMException && falha.name === 'AbortError') return;
      setErro(falha instanceof Error ? falha.message : 'A IA não conseguiu responder.');
    } finally {
      if (envioRef.current === controller) {
        envioRef.current = null;
        setRascunho('');
        setRefazendo(false);
        setEnviando(false);
        window.setTimeout(() => textareaRef.current?.focus(), 0);
      }
    }
  };

  const enviar = (evento?: FormEvent) => {
    evento?.preventDefault();
    void perguntar(pergunta);
  };

  const aoPressionarTecla = (evento: KeyboardEvent<HTMLTextAreaElement>) => {
    if (evento.key === 'Enter' && !evento.shiftKey) {
      evento.preventDefault();
      enviar();
    }
  };

  const indisponivel = contexto ? motivoIndisponivel(contexto) : null;
  const resumo = contexto?.analise.resumo;
  const analiseOk = Boolean(contexto?.analise.disponivel && contexto.analise.status === 'ok');

  return (
    <AppShell>
      <div className="dashboard-container chat-ia-page">
        <header className="app-page-header chat-ia-header">
          <div>
            <h1>MonitorIA{empresa && <span className="analisador-header-empresa"> · {empresa}</span>}</h1>
            <p className="app-page-header-sub">Converse sobre a empresa com base no CRM, na análise diária e nos números do Prisma.</p>
          </div>
          {mensagens.length > 0 && (
            <button type="button" className="chat-ia-limpar" onClick={limparConversa}>
              <RotateCcw size={15} aria-hidden="true" /> Nova conversa
            </button>
          )}
        </header>

        {!empresa && (
          <div className="glass-card glass-card-flat chat-ia-aviso" role="status">
            <Bot size={24} aria-hidden="true" />
            <div><strong>Selecione uma empresa</strong><p>Use o seletor no topo da tela para definir o contexto.</p></div>
          </div>
        )}

        {empresa && (
          <div className="chat-ia-layout">
            <aside className="chat-ia-lateral custom-scrollbar" aria-label="Contexto carregado">
              {carregandoContexto && (
                <div className="glass-card glass-card-flat chat-ia-painel">
                  <div className="chat-ia-contexto-carregando" role="status">
                    <Loader2 size={18} className="chat-ia-spin" aria-hidden="true" /> Carregando contexto…
                  </div>
                </div>
              )}

              {contexto && analiseOk && resumo && (
                <section className="glass-card glass-card-flat chat-ia-painel chat-ia-resumo" aria-label="Resumo da análise diária">
                  <div className="chat-ia-painel-titulo">
                    <ShieldAlert size={16} aria-hidden="true" />
                    <strong>Risco executivo</strong>
                    {resumo.risco && (
                      <span className={`chat-ia-risco ${CLASSE_RISCO[resumo.risco.toLowerCase()] ?? ''}`}>{resumo.risco}</span>
                    )}
                  </div>

                  {resumo.alertas && resumo.alertas.length > 0 && (
                    <div className="chat-ia-resumo-bloco">
                      <span className="chat-ia-resumo-rotulo"><AlertTriangle size={13} aria-hidden="true" /> Alertas</span>
                      <ul>{resumo.alertas.map((alerta) => <li key={alerta}>{alerta}</li>)}</ul>
                    </div>
                  )}

                  {resumo.proxima_pauta && resumo.proxima_pauta.length > 0 && (
                    <div className="chat-ia-resumo-bloco">
                      <span className="chat-ia-resumo-rotulo"><CalendarClock size={13} aria-hidden="true" /> Próxima pauta</span>
                      <ul>{resumo.proxima_pauta.map((item) => <li key={item}>{item}</li>)}</ul>
                    </div>
                  )}

                  <button type="button" className="chat-ia-acao chat-ia-ler-analise" onClick={() => setAnaliseAberta(true)}>
                    <BookOpen size={15} aria-hidden="true" /> Ler análise completa
                  </button>
                </section>
              )}

              {contexto && (
                <section className="glass-card glass-card-flat chat-ia-painel" aria-label="Fontes da conversa">
                  <div className="chat-ia-painel-titulo">
                    <Sparkles size={16} aria-hidden="true" />
                    <strong>Fontes da conversa</strong>
                  </div>
                  <div className="chat-ia-documentos">
                    <div className={`chat-ia-documento${contexto.crm.disponivel ? ' is-ok' : ' is-erro'}`}>
                      <FileText size={16} aria-hidden="true" />
                      <div><strong>CRM</strong><span>{contexto.crm.disponivel ? formatarData(contexto.crm.atualizado_em) : 'Ainda não publicado'}</span></div>
                      {contexto.crm.disponivel ? <CheckCircle2 size={15} /> : <XCircle size={15} />}
                    </div>
                    <div className={`chat-ia-documento${analiseOk ? ' is-ok' : ' is-erro'}`}>
                      <FileText size={16} aria-hidden="true" />
                      <div>
                        <strong>Análise diária</strong>
                        <span>{contexto.analise.disponivel ? formatarData(contexto.analise.atualizado_em) : 'Ainda não gerada'}</span>
                      </div>
                      {analiseOk ? <CheckCircle2 size={15} /> : <XCircle size={15} />}
                    </div>
                    <div className={`chat-ia-documento${contexto.dados.disponivel ? ' is-ok' : ' is-erro'}`}>
                      <Database size={16} aria-hidden="true" />
                      <div>
                        <strong>Base do Prisma</strong>
                        <span>
                          {contexto.dados.disponivel
                            ? formatarData(contexto.dados.atualizado_em)
                            : MOTIVOS_DADOS[contexto.dados.motivo ?? ''] ?? 'Não disponível'}
                        </span>
                      </div>
                      {contexto.dados.disponivel ? <CheckCircle2 size={15} /> : <XCircle size={15} />}
                    </div>
                  </div>
                  <p className="chat-ia-privacidade">A pergunta, os documentos e os números da base vão para o Claude (Anthropic) ou, se ele falhar, para o Ollama Cloud. O Prisma não salva o histórico.</p>
                </section>
              )}
            </aside>

            <section className="glass-card glass-card-flat chat-ia-conversa" aria-label="Conversa com o MonitorIA">
              <div className="chat-ia-mensagens custom-scrollbar" aria-live="polite">
                {mensagens.length === 0 && !enviando && (
                  <div className="chat-ia-vazio">
                    {erroContexto ? (
                      <>
                        <span className="chat-ia-vazio-icone is-indisponivel"><Bot size={27} aria-hidden="true" /></span>
                        <h2>O assistente não está disponível para {empresa}</h2>
                        <p>{erroContexto}</p>
                      </>
                    ) : indisponivel ? (
                      <>
                        <span className="chat-ia-vazio-icone is-indisponivel"><Bot size={27} aria-hidden="true" /></span>
                        <h2>{indisponivel.titulo}</h2>
                        <p>{indisponivel.texto}</p>
                      </>
                    ) : (
                      <>
                        <span className="chat-ia-vazio-icone"><Bot size={27} aria-hidden="true" /></span>
                        <h2>O que você quer entender sobre {empresa}?</h2>
                        <p>Escolha uma pergunta para começar ou escreva a sua.</p>
                        <div className="chat-ia-sugestoes">
                          {SUGESTOES.map((sugestao) => (
                            <button
                              key={sugestao}
                              type="button"
                              className="chat-ia-sugestao"
                              onClick={() => void perguntar(sugestao)}
                              disabled={!contexto?.pronto}
                            >
                              {sugestao}
                            </button>
                          ))}
                        </div>
                      </>
                    )}
                  </div>
                )}
                {mensagens.map((mensagem) => (
                  <article key={mensagem.id} className={`chat-ia-mensagem is-${mensagem.role}`}>
                    <span className="chat-ia-mensagem-autor">{mensagem.role === 'user' ? 'Você' : 'MonitorIA'}</span>
                    {mensagem.role === 'assistant'
                      ? <MarkdownResposta texto={mensagem.content} className="chat-ia-balao" />
                      : <p className="chat-ia-balao">{mensagem.content}</p>}
                    {mensagem.passos && <PassosAgenteResumo passos={mensagem.passos} segundos={mensagem.segundos} />}
                  </article>
                ))}
                {enviando && (
                  <article className="chat-ia-mensagem is-assistant is-digitando" role="status">
                    <span className="chat-ia-mensagem-autor">MonitorIA</span>
                    <PassosAgenteAoVivo
                      passos={passos}
                      escrevendo={Boolean(rascunhoExibido)}
                      refazendo={refazendo}
                      segundos={segundos}
                    />
                    {rascunhoExibido && (
                      <MarkdownResposta texto={rascunhoExibido} className="chat-ia-balao" escrevendo />
                    )}
                  </article>
                )}
                <div ref={fimRef} />
              </div>

              {erro && (
                <div className="chat-ia-erro" role="alert"><AlertTriangle size={16} aria-hidden="true" /> {erro}</div>
              )}

              <form className="chat-ia-composer" onSubmit={enviar}>
                <label htmlFor="chat-ia-pergunta" className="sr-only">Pergunta para a IA</label>
                <textarea
                  ref={textareaRef}
                  id="chat-ia-pergunta"
                  value={pergunta}
                  onChange={(evento) => setPergunta(evento.target.value)}
                  onKeyDown={aoPressionarTecla}
                  maxLength={4000}
                  rows={2}
                  placeholder={contexto?.pronto ? 'Pergunte sobre a empresa…' : 'Conversa indisponível para esta empresa'}
                  disabled={!contexto?.pronto || enviando}
                />
                <button type="submit" disabled={!pergunta.trim() || !contexto?.pronto || enviando} aria-label="Enviar pergunta" title="Enviar pergunta">
                  {enviando ? <Loader2 size={18} className="chat-ia-spin" /> : <Send size={18} />}
                </button>
              </form>
              <p className="chat-ia-composer-hint">Enter envia · Shift + Enter quebra linha · respostas podem conter interpretações</p>
            </section>
          </div>
        )}

        {empresa && analiseAberta && (
          <AnaliseModal empresa={empresa} aoFechar={() => setAnaliseAberta(false)} />
        )}
      </div>
    </AppShell>
  );
}

function AnaliseModal({ empresa, aoFechar }: { empresa: string; aoFechar: () => void }) {
  const [analise, setAnalise] = useState<AnaliseEmpresaIA | null>(null);
  const [erro, setErro] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    void obterAnaliseChatIA(empresa, controller.signal)
      .then(setAnalise)
      .catch((falha) => {
        if (falha instanceof DOMException && falha.name === 'AbortError') return;
        setErro(falha instanceof Error ? falha.message : 'Não foi possível abrir a análise.');
      });
    return () => controller.abort();
  }, [empresa]);

  useEffect(() => {
    const aoTeclar = (evento: globalThis.KeyboardEvent) => {
      if (evento.key === 'Escape') aoFechar();
    };
    window.addEventListener('keydown', aoTeclar);
    return () => window.removeEventListener('keydown', aoTeclar);
  }, [aoFechar]);

  return (
    <div className="config-modal-overlay" onClick={aoFechar} role="presentation">
      <div
        className="config-modal chat-ia-analise-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="chat-ia-analise-titulo"
        onClick={(evento) => evento.stopPropagation()}
      >
        <header className="config-modal-header">
          <div>
            <h2 id="chat-ia-analise-titulo">Análise diária · {empresa}</h2>
            {analise && <span className="chat-ia-analise-data">Gerada em {formatarData(analise.atualizado_em)}</span>}
          </div>
          <button type="button" className="analisador-btn analisador-btn-sec" onClick={aoFechar} aria-label="Fechar">
            <X size={16} />
          </button>
        </header>
        <div className="config-modal-body custom-scrollbar">
          {!analise && !erro && (
            <div className="chat-ia-contexto-carregando" role="status">
              <Loader2 size={18} className="chat-ia-spin" aria-hidden="true" /> Abrindo a análise…
            </div>
          )}
          {erro && <div className="chat-ia-erro" role="alert"><AlertTriangle size={16} aria-hidden="true" /> {erro}</div>}
          {analise && <MarkdownResposta texto={semFrontmatter(analise.markdown)} className="chat-ia-analise-texto" />}
        </div>
      </div>
    </div>
  );
}
