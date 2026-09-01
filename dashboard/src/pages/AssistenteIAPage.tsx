import {
  useEffect,
  useRef,
  useState,
  type FormEvent,
  type KeyboardEvent,
} from 'react';
import {
  AlertTriangle,
  Bot,
  CheckCircle2,
  Database,
  FileText,
  Loader2,
  RotateCcw,
  Send,
  Sparkles,
  XCircle,
} from 'lucide-react';
import { AppShell } from '../components/AppShell';
import {
  conversarChatIA,
  obterContextoChatIA,
  type ChatIAMensagem,
  type ContextoChatIA,
} from '../api/client';
import { useEscopoAtual } from '../hooks/useEscopoAtual';

interface MensagemLocal extends ChatIAMensagem {
  id: string;
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

function formatarData(valor: string | null): string {
  if (!valor) return 'Não disponível';
  const data = new Date(valor);
  if (Number.isNaN(data.getTime())) return 'Data não informada';
  return new Intl.DateTimeFormat('pt-BR', {
    dateStyle: 'short',
    timeStyle: 'short',
  }).format(data);
}

/** Chat executivo: histórico local; contexto e chave permanecem no backend. */
export default function AssistenteIAPage() {
  const { empresa } = useEscopoAtual();
  const [contexto, setContexto] = useState<ContextoChatIA | null>(null);
  const [mensagens, setMensagens] = useState<MensagemLocal[]>([]);
  const [pergunta, setPergunta] = useState('');
  const [carregandoContexto, setCarregandoContexto] = useState(false);
  const [enviando, setEnviando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);
  const fimRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    setMensagens([]);
    setPergunta('');
    setErro(null);
    setContexto(null);
    if (!empresa) return;

    const controller = new AbortController();
    setCarregandoContexto(true);
    void obterContextoChatIA(empresa, controller.signal)
      .then(setContexto)
      .catch((falha) => {
        if (falha instanceof DOMException && falha.name === 'AbortError') return;
        setErro(falha instanceof Error ? falha.message : 'Falha ao carregar contexto da empresa.');
      })
      .finally(() => {
        if (!controller.signal.aborted) setCarregandoContexto(false);
      });
    return () => controller.abort();
  }, [empresa]);

  useEffect(() => {
    fimRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
  }, [enviando, mensagens]);

  const limparConversa = () => {
    setMensagens([]);
    setErro(null);
    window.setTimeout(() => textareaRef.current?.focus(), 0);
  };

  const enviar = async (evento?: FormEvent) => {
    evento?.preventDefault();
    const texto = pergunta.trim();
    if (!texto || !empresa || !contexto?.pronto || enviando) return;

    const mensagemUsuario: MensagemLocal = { id: criarId(), role: 'user', content: texto };
    const historico = [...mensagens, mensagemUsuario].slice(-12);
    setMensagens(historico);
    setPergunta('');
    setErro(null);
    setEnviando(true);
    try {
      const resposta = await conversarChatIA(
        empresa,
        historico.map(({ role, content }) => ({ role, content })),
      );
      setMensagens((atuais) => [
        ...atuais,
        { id: criarId(), role: 'assistant', content: resposta.resposta },
      ]);
    } catch (falha) {
      setErro(falha instanceof Error ? falha.message : 'A IA não conseguiu responder.');
    } finally {
      setEnviando(false);
      window.setTimeout(() => textareaRef.current?.focus(), 0);
    }
  };

  const aoPressionarTecla = (evento: KeyboardEvent<HTMLTextAreaElement>) => {
    if (evento.key === 'Enter' && !evento.shiftKey) {
      evento.preventDefault();
      void enviar();
    }
  };

  const contextoIncompleto = contexto && !contexto.pronto;

  return (
    <AppShell>
      <div className="dashboard-container chat-ia-page">
        <header className="app-page-header chat-ia-header">
          <div>
            <h1>Assistente IA{empresa && <span className="analisador-header-empresa"> · {empresa}</span>}</h1>
            <p className="app-page-header-sub">Converse usando exclusivamente os dossiês disponíveis da empresa.</p>
          </div>
          {mensagens.length > 0 && (
            <button type="button" className="chat-ia-limpar" onClick={limparConversa} disabled={enviando}>
              <RotateCcw size={15} aria-hidden="true" /> Nova conversa
            </button>
          )}
        </header>

        {!empresa && (
          <div className="glass-card glass-card-flat chat-ia-aviso" role="status">
            <Bot size={24} aria-hidden="true" />
            <div><strong>Selecione uma empresa</strong><p>Use o seletor da barra lateral para definir o contexto.</p></div>
          </div>
        )}

        {empresa && (
          <div className="chat-ia-layout">
            <aside className="glass-card glass-card-flat chat-ia-contexto" aria-label="Contexto carregado">
              <div className="chat-ia-contexto-titulo">
                <Sparkles size={17} aria-hidden="true" />
                <div><strong>Contexto da conversa</strong><span>Conteúdo fica no backend</span></div>
              </div>

              {carregandoContexto ? (
                <div className="chat-ia-contexto-carregando" role="status">
                  <Loader2 size={18} className="chat-ia-spin" aria-hidden="true" /> Validando documentos…
                </div>
              ) : contexto ? (
                <div className="chat-ia-documentos">
                  <div className={`chat-ia-documento${contexto.crm.disponivel ? ' is-ok' : ' is-erro'}`}>
                    <FileText size={17} aria-hidden="true" />
                    <div><strong>CRM</strong><span>{contexto.provisorio && !contexto.crm.disponivel ? 'Aguardando geração' : formatarData(contexto.crm.atualizado_em)}</span></div>
                    {contexto.crm.disponivel ? <CheckCircle2 size={16} /> : <XCircle size={16} />}
                  </div>
                  <div className={`chat-ia-documento${contexto.analise.disponivel && contexto.analise.status === 'ok' ? ' is-ok' : ' is-erro'}`}>
                    <FileText size={17} aria-hidden="true" />
                    <div><strong>Análise diária</strong><span>{formatarData(contexto.analise.atualizado_em)}</span></div>
                    {contexto.analise.disponivel && contexto.analise.status === 'ok' ? <CheckCircle2 size={16} /> : <XCircle size={16} />}
                  </div>
                  <div className={`chat-ia-documento${contexto.dados.disponivel ? ' is-ok' : ' is-erro'}`}>
                    <Database size={17} aria-hidden="true" />
                    <div>
                      <strong>Base do Prisma</strong>
                      <span>
                        {contexto.dados.disponivel
                          ? formatarData(contexto.dados.atualizado_em)
                          : MOTIVOS_DADOS[contexto.dados.motivo ?? ''] ?? 'Não disponível'}
                      </span>
                    </div>
                    {contexto.dados.disponivel ? <CheckCircle2 size={16} /> : <XCircle size={16} />}
                  </div>
                  <p className="chat-ia-privacidade">A pergunta, os MDs e os números da base disponíveis são enviados ao Ollama Cloud. Histórico não é salvo pelo Prisma.</p>
                </div>
              ) : null}
            </aside>

            <section className="glass-card glass-card-flat chat-ia-conversa" aria-label="Conversa com assistente IA">
              <div className="chat-ia-mensagens custom-scrollbar" aria-live="polite">
                {mensagens.length === 0 && !enviando && (
                  <div className="chat-ia-vazio">
                    <span className="chat-ia-vazio-icone"><Bot size={27} aria-hidden="true" /></span>
                    <h2>O que você quer entender sobre {empresa}?</h2>
                    <p>Exemplos: risco atual, tendência comercial, oportunidades ou pauta da próxima reunião.</p>
                  </div>
                )}
                {mensagens.map((mensagem) => (
                  <article key={mensagem.id} className={`chat-ia-mensagem is-${mensagem.role}`}>
                    <span className="chat-ia-mensagem-autor">{mensagem.role === 'user' ? 'Você' : 'Prisma IA'}</span>
                    <p>{mensagem.content}</p>
                  </article>
                ))}
                {enviando && (
                  <article className="chat-ia-mensagem is-assistant is-digitando" role="status">
                    <span className="chat-ia-mensagem-autor">Prisma IA</span>
                    <p><Loader2 size={16} className="chat-ia-spin" aria-hidden="true" /> Analisando os documentos…</p>
                  </article>
                )}
                <div ref={fimRef} />
              </div>

              {erro && (
                <div className="chat-ia-erro" role="alert"><AlertTriangle size={16} aria-hidden="true" /> {erro}</div>
              )}
              {contextoIncompleto && !erro && (
                <div className="chat-ia-erro" role="alert"><AlertTriangle size={16} aria-hidden="true" /> Uma análise diária com status válido é obrigatória.</div>
              )}

              <form className="chat-ia-composer" onSubmit={(evento) => void enviar(evento)}>
                <label htmlFor="chat-ia-pergunta" className="sr-only">Pergunta para a IA</label>
                <textarea
                  ref={textareaRef}
                  id="chat-ia-pergunta"
                  value={pergunta}
                  onChange={(evento) => setPergunta(evento.target.value)}
                  onKeyDown={aoPressionarTecla}
                  maxLength={4000}
                  rows={2}
                  placeholder={contexto?.pronto ? 'Pergunte sobre a empresa…' : 'Contexto indisponível'}
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
      </div>
    </AppShell>
  );
}
