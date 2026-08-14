import { useEffect, useMemo, useState, type CSSProperties } from 'react';
import {
  AlertTriangle,
  BellRing,
  CalendarClock,
  ChevronDown,
  ChevronUp,
  Loader2,
  Plus,
  Save,
  Settings2,
  Trash2,
} from 'lucide-react';
import {
  obterAlertasClientes,
  salvarRegrasAlertasClientes,
  type AlertasClientesResposta,
  type DirecaoAlertaCliente,
  type GranularidadeAlertaCliente,
  type RegraAlertaCliente,
  type TagCatalogoItem,
} from '../../api/client';
import { formatCurrency, formatPercent } from '../../utils/formatters';

interface Props {
  empresa: string;
  loja?: string | null;
  catalogo: TagCatalogoItem[];
}

const ROTULOS_GRANULARIDADE: Record<GranularidadeAlertaCliente, string> = {
  diaria: 'Diária',
  semanal: 'Semanal',
  mensal: 'Mensal',
};

function novoId(tagId: string): string {
  return `ritmo_${tagId}_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`;
}

function regraPadrao(tagId: string): RegraAlertaCliente {
  return {
    id: novoId(tagId),
    tag_id: tagId,
    ativa: true,
    metrica: 'receita',
    granularidade: 'mensal',
    direcao: 'queda',
    limite_percentual: 20,
    limite_valor: 1000,
    meses_historico: 6,
    min_dias_uteis: 2,
  };
}

function dataBr(valor: string | null): string {
  if (!valor) return '—';
  const [ano, mes, dia] = valor.split('-');
  return `${dia}/${mes}/${ano}`;
}

/** Permite várias regras por tag, cada uma com janela diária, semanal ou mensal. */
export function ClientesRitmoAlertas({ empresa, loja = null, catalogo }: Props) {
  const [dados, setDados] = useState<AlertasClientesResposta | null>(null);
  const [regras, setRegras] = useState<RegraAlertaCliente[]>([]);
  const [configurando, setConfigurando] = useState(false);
  const [carregando, setCarregando] = useState(true);
  const [salvando, setSalvando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<string | null>(null);

  const tagsConfiguraveis = useMemo(
    () => catalogo.filter((tag) => tag.ativa && tag.id !== 'cliente_balcao' && tag.id !== 'encerrou_operacao'),
    [catalogo],
  );
  const catalogoMapa = useMemo(
    () => new Map(catalogo.map((tag) => [tag.id, tag])),
    [catalogo],
  );

  const carregar = async () => {
    setCarregando(true);
    setErro(null);
    try {
      const resposta = await obterAlertasClientes(empresa, loja);
      setDados(resposta);
      setRegras(resposta.regras ?? []);
    } catch (falha) {
      setErro(falha instanceof Error ? falha.message : 'Falha ao avaliar alertas de clientes.');
    } finally {
      setCarregando(false);
    }
  };

  useEffect(() => {
    void carregar();
    // Empresa/loja formam o escopo persistido. Catálogo não dispara leitura.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [empresa, loja]);

  const adicionarRegra = () => {
    const primeiraTag = tagsConfiguraveis[0];
    if (!primeiraTag) return;
    setRegras((atuais) => [...atuais, regraPadrao(primeiraTag.id)]);
    setFeedback('Nova regra adicionada. Salve para confirmar.');
  };

  const atualizarRegra = (regraId: string, patch: Partial<RegraAlertaCliente>) => {
    setRegras((atuais) => atuais.map((regra) => regra.id === regraId ? { ...regra, ...patch } : regra));
  };

  const removerRegra = (regraId: string) => {
    setRegras((atuais) => atuais.filter((regra) => regra.id !== regraId));
    setFeedback('Regra removida da edição. Salve para confirmar.');
  };

  const salvar = async () => {
    setSalvando(true);
    setErro(null);
    setFeedback(null);
    try {
      const resposta = await salvarRegrasAlertasClientes(empresa, regras, loja);
      setRegras(resposta.regras_alerta ?? regras);
      setConfigurando(false);
      await carregar();
      setFeedback('Regras salvas. Alertas recalculados.');
    } catch (falha) {
      setErro(falha instanceof Error ? falha.message : 'Falha ao salvar regras.');
    } finally {
      setSalvando(false);
    }
  };

  return (
    <section className="glass-card glass-card-flat clientes-ritmo-card">
      <div className="clientes-ritmo-topo">
        <div>
          <div className="clientes-ritmo-titulo"><BellRing size={18} /><h2>Alertas de ritmo do mês</h2></div>
          <p>Crie alertas diários, semanais ou mensais. Todas as janelas respeitam os dias úteis e os limites do mês.</p>
        </div>
        <button
          type="button"
          className="analisador-btn analisador-btn-sec"
          aria-expanded={configurando}
          onClick={() => setConfigurando((valor) => !valor)}
        >
          <Settings2 size={15} /> Configurar {configurando ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
        </button>
      </div>

      {configurando && (
        <div className="clientes-ritmo-config">
          <div className="clientes-ritmo-config-cabecalho">
            <div><strong>Alertas configurados</strong><span>Uma tag pode ter várias regras e granularidades.</span></div>
            <div className="clientes-ritmo-config-acoes">
              <button type="button" className="analisador-btn analisador-btn-sec" disabled={!tagsConfiguraveis.length || salvando} onClick={adicionarRegra}>
                <Plus size={15} /> Adicionar alerta
              </button>
              <button type="button" className="analisador-btn" disabled={salvando} onClick={() => void salvar()}>
                {salvando ? <Loader2 size={15} className="dashboard-filter-spinner" /> : <Save size={15} />}
                Salvar regras
              </button>
            </div>
          </div>
          <div className="clientes-ritmo-regras">
            {regras.length === 0 && <p className="clientes-ritmo-sem-alertas">Nenhum alerta configurado. Clique em “Adicionar alerta”.</p>}
            {regras.map((regra) => {
              const tag = catalogoMapa.get(regra.tag_id) ?? tagsConfiguraveis[0];
              return (
                <article key={regra.id} className={`clientes-ritmo-regra${regra.ativa ? ' is-ativa' : ''}`} style={{ '--tag-cor': tag?.cor } as CSSProperties}>
                  <label className="clientes-ritmo-regra-chave">
                    <input type="checkbox" checked={regra.ativa} onChange={(evento) => atualizarRegra(regra.id, { ativa: evento.target.checked })} />
                    <span>Ativo</span>
                  </label>
                  <label className="analisador-campo"><span>Tag</span><select className="custom-select analisador-select" value={regra.tag_id} disabled={!regra.ativa} onChange={(evento) => atualizarRegra(regra.id, { tag_id: evento.target.value })}>{tagsConfiguraveis.map((item) => <option key={item.id} value={item.id}>{item.rotulo}</option>)}</select></label>
                  <label className="analisador-campo"><span>Granularidade</span><select className="custom-select analisador-select" value={regra.granularidade} disabled={!regra.ativa} onChange={(evento) => atualizarRegra(regra.id, { granularidade: evento.target.value as GranularidadeAlertaCliente })}><option value="diaria">Diária</option><option value="semanal">Semanal</option><option value="mensal">Mensal</option></select></label>
                  <label className="analisador-campo"><span>Direção</span><select className="custom-select analisador-select" value={regra.direcao} disabled={!regra.ativa} onChange={(evento) => atualizarRegra(regra.id, { direcao: evento.target.value as DirecaoAlertaCliente })}><option value="queda">Queda</option><option value="alta">Alta</option><option value="ambos">Ambos</option></select></label>
                  <label className="analisador-campo"><span>Variação mínima</span><span className="clientes-ritmo-input-sufixo"><input className="analisador-input" type="number" min={0} max={1000} step={1} value={regra.limite_percentual} disabled={!regra.ativa} onChange={(evento) => atualizarRegra(regra.id, { limite_percentual: Number(evento.target.value) })} /><i>%</i></span></label>
                  <label className="analisador-campo"><span>Impacto mínimo</span><span className="clientes-ritmo-input-sufixo"><input className="analisador-input" type="number" min={0} step={100} value={regra.limite_valor} disabled={!regra.ativa} onChange={(evento) => atualizarRegra(regra.id, { limite_valor: Number(evento.target.value) })} /><i>R$</i></span></label>
                  <label className="analisador-campo"><span>Histórico</span><select className="custom-select analisador-select" value={regra.meses_historico} disabled={!regra.ativa} onChange={(evento) => atualizarRegra(regra.id, { meses_historico: Number(evento.target.value) })}><option value={3}>3 meses</option><option value={6}>6 meses</option><option value={9}>9 meses</option><option value={12}>12 meses</option></select></label>
                  <label className="analisador-campo"><span>Aguardar</span><select className="custom-select analisador-select" value={regra.min_dias_uteis} disabled={!regra.ativa} onChange={(evento) => atualizarRegra(regra.id, { min_dias_uteis: Number(evento.target.value) })}><option value={1}>1 dia útil</option><option value={2}>2 dias úteis</option><option value={3}>3 dias úteis</option><option value={5}>5 dias úteis</option></select></label>
                  <button type="button" className="clientes-ritmo-remover" onClick={() => removerRegra(regra.id)} aria-label="Remover alerta" title="Remover alerta; confirme em Salvar regras"><Trash2 size={16} /></button>
                </article>
              );
            })}
          </div>
        </div>
      )}

      {erro && <div className="clientes-ritmo-aviso is-erro" role="alert"><AlertTriangle size={16} />{erro}</div>}
      {feedback && <p className="clientes-ritmo-feedback" role="status">{feedback}</p>}
      {carregando && <p className="clientes-ritmo-carregando" role="status"><Loader2 size={16} className="dashboard-filter-spinner" /> Avaliando ritmo dos clientes…</p>}

      {!carregando && dados && !dados.disponivel && (
        <div className="clientes-ritmo-aviso" role="status">
          <CalendarClock size={19} />
          <div><strong>Aguardando granularidade diária</strong><p>{dados.motivo}</p></div>
        </div>
      )}

      {!carregando && dados?.disponivel && (
        <>
          <div className="clientes-ritmo-resumo">
            <span><strong>{dados.resumo.ativos}</strong> alertas ativos</span>
            <span><strong>{dados.resumo.quedas}</strong> quedas</span>
            <span><strong>{dados.resumo.altas}</strong> altas</span>
            <span><strong>{dados.resumo.clientes_avaliados}</strong> avaliados</span>
            <small>{dados.dias_uteis_decorridos}º dia útil · semana {dataBr(dados.semana_inicio)}–{dataBr(dados.semana_fim)}</small>
          </div>
          <div className="clientes-ritmo-lista">
            {dados.alertas.length === 0 && <p className="clientes-ritmo-sem-alertas">Nenhuma regra disparou neste período.</p>}
            {dados.alertas.slice(0, 30).map((alerta) => {
              const tag = catalogoMapa.get(alerta.tag_id);
              return (
                <article key={alerta.id} className={`clientes-ritmo-alerta is-${alerta.sentido}`}>
                  <div className="clientes-ritmo-alerta-cliente"><strong>{alerta.cliente}</strong><span style={{ '--tag-cor': tag?.cor } as CSSProperties}>{tag?.rotulo ?? alerta.tag_id}</span><em>{ROTULOS_GRANULARIDADE[alerta.granularidade]}</em></div>
                  <div className="clientes-ritmo-alerta-variacao">{alerta.sentido === 'queda' ? <ChevronDown size={16} /> : <ChevronUp size={16} />}<strong>{formatPercent(alerta.variacao_percentual, 1)}</strong><small>{formatCurrency(alerta.diferenca)}</small></div>
                  <dl><div><dt>{ROTULOS_GRANULARIDADE[alerta.granularidade]}</dt><dd>{formatCurrency(alerta.realizado)} / {formatCurrency(alerta.esperado)}</dd></div><div><dt>Dia</dt><dd>{formatCurrency(alerta.dia_realizado)} / {formatCurrency(alerta.dia_esperado)}</dd></div><div><dt>Semana</dt><dd>{formatCurrency(alerta.semana_realizado)} / {formatCurrency(alerta.semana_esperado)}</dd></div><div><dt>Mês</dt><dd>{formatCurrency(alerta.mes_realizado)} / {formatCurrency(alerta.mes_esperado)}</dd></div><div><dt>Média/dia</dt><dd>{formatCurrency(alerta.media_diaria_atual)}</dd></div></dl>
                </article>
              );
            })}
          </div>
        </>
      )}
    </section>
  );
}
