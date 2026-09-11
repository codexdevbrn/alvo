import { useEffect, useMemo, useState, type CSSProperties } from 'react';
import { AlertTriangle, Loader2, Plus, Save, Trash2 } from 'lucide-react';
import {
  obterTagsClientes,
  salvarRegrasAlertasClientes,
  type DirecaoAlertaCliente,
  type GranularidadeAlertaCliente,
  type RegraAlertaCliente,
  type TagCatalogoItem,
} from '../../api/client';

interface Props {
  empresa: string;
  /** Escopo de lojas já codificado; null = todas. As regras são gravadas nele. */
  loja?: string | null;
  catalogo: TagCatalogoItem[];
}

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

/**
 * Edita as regras de alerta de ritmo do mês.
 *
 * Vive em Configurações; a tela de Clientes apenas exibe o que dispara. As
 * regras são gravadas no `clientes_tags.json` do escopo (empresa + lojas), o
 * mesmo que a tela de Clientes lê — por isso o `loja` precisa vir do escopo da
 * barra lateral, e não fixo em null.
 */
export function RegrasRitmoAlertasEditor({ empresa, loja = null, catalogo }: Props) {
  const [regras, setRegras] = useState<RegraAlertaCliente[]>([]);
  const [carregando, setCarregando] = useState(false);
  const [salvando, setSalvando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<string | null>(null);

  const tagsConfiguraveis = useMemo(
    () => catalogo.filter(
      (tag) => tag.ativa
        && tag.entra_na_analise
        && tag.id !== 'cliente_balcao'
        && tag.id !== 'encerrou_operacao',
    ),
    [catalogo],
  );
  const catalogoMapa = useMemo(
    () => new Map(catalogo.map((tag) => [tag.id, tag])),
    [catalogo],
  );

  useEffect(() => {
    if (!empresa) {
      setRegras([]);
      return;
    }
    let cancelado = false;
    const carregar = async () => {
      setCarregando(true);
      setErro(null);
      setFeedback(null);
      try {
        const resposta = await obterTagsClientes(empresa, loja);
        if (!cancelado) setRegras(resposta.regras_alerta ?? []);
      } catch (falha) {
        if (!cancelado) {
          setErro(falha instanceof Error ? falha.message : 'Falha ao carregar as regras de ritmo.');
        }
      } finally {
        if (!cancelado) setCarregando(false);
      }
    };
    void carregar();
    return () => { cancelado = true; };
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
      setFeedback('Regras salvas. A tela de Clientes recalcula os alertas ao abrir.');
    } catch (falha) {
      setErro(falha instanceof Error ? falha.message : 'Falha ao salvar regras.');
    } finally {
      setSalvando(false);
    }
  };

  return (
    <div className="clientes-ritmo-config">
      <div className="clientes-ritmo-config-cabecalho">
        <div><strong>Alertas configurados</strong><span>Uma tag pode ter várias regras e granularidades.</span></div>
        <div className="clientes-ritmo-config-acoes">
          <button
            type="button"
            className="analisador-btn analisador-btn-sec"
            disabled={!tagsConfiguraveis.length || salvando || carregando}
            onClick={adicionarRegra}
          >
            <Plus size={15} /> Adicionar alerta
          </button>
          <button
            type="button"
            className="analisador-btn analisador-btn-pri"
            disabled={salvando || carregando}
            onClick={() => void salvar()}
          >
            {salvando ? <Loader2 size={15} className="dashboard-filter-spinner" /> : <Save size={15} />}
            Salvar regras
          </button>
        </div>
      </div>

      {erro && <div className="clientes-ritmo-aviso is-erro" role="alert"><AlertTriangle size={16} />{erro}</div>}
      {feedback && <p className="clientes-ritmo-feedback" role="status">{feedback}</p>}

      <div className="clientes-ritmo-regras">
        {carregando && (
          <p className="clientes-ritmo-carregando" role="status">
            <Loader2 size={16} className="dashboard-filter-spinner" /> Carregando regras…
          </p>
        )}
        {!carregando && regras.length === 0 && (
          <p className="clientes-ritmo-sem-alertas">Nenhum alerta configurado. Clique em “Adicionar alerta”.</p>
        )}
        {!carregando && regras.map((regra) => {
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
  );
}
