import { useEffect, useMemo, useState, type CSSProperties } from 'react';
import { Link } from 'react-router-dom';
import {
  AlertTriangle,
  BellRing,
  CalendarClock,
  ChevronDown,
  ChevronUp,
  Loader2,
  Settings2,
} from 'lucide-react';
import {
  obterAlertasClientes,
  type AlertasClientesResposta,
  type GranularidadeAlertaCliente,
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

function dataBr(valor: string | null): string {
  if (!valor) return '—';
  const [ano, mes, dia] = valor.split('-');
  return `${dia}/${mes}/${ano}`;
}

/**
 * Mostra os alertas de ritmo que dispararam no escopo atual.
 *
 * As regras são editadas em Configurações → Alertas de ritmo do mês; aqui é só
 * leitura, para a tela operacional não misturar acompanhamento com ajuste.
 */
export function ClientesRitmoAlertas({ empresa, loja = null, catalogo }: Props) {
  const [dados, setDados] = useState<AlertasClientesResposta | null>(null);
  const [carregando, setCarregando] = useState(true);
  const [erro, setErro] = useState<string | null>(null);

  const catalogoMapa = useMemo(
    () => new Map(catalogo.map((tag) => [tag.id, tag])),
    [catalogo],
  );

  useEffect(() => {
    let cancelado = false;
    const carregar = async () => {
      setCarregando(true);
      setErro(null);
      try {
        const resposta = await obterAlertasClientes(empresa, loja);
        if (!cancelado) setDados(resposta);
      } catch (falha) {
        if (!cancelado) {
          setErro(falha instanceof Error ? falha.message : 'Falha ao avaliar alertas de clientes.');
        }
      } finally {
        if (!cancelado) setCarregando(false);
      }
    };
    void carregar();
    return () => { cancelado = true; };
  }, [empresa, loja]);

  return (
    <section className="glass-card glass-card-flat clientes-ritmo-card">
      <div className="clientes-ritmo-topo">
        <div>
          <div className="clientes-ritmo-titulo"><BellRing size={18} /><h2>Alertas de ritmo do mês</h2></div>
          <p>Alertas diários, semanais ou mensais. Todas as janelas respeitam os dias úteis e os limites do mês.</p>
        </div>
        <Link className="analisador-btn analisador-btn-sec" to="/config">
          <Settings2 size={15} /> Configurar
        </Link>
      </div>

      {erro && <div className="clientes-ritmo-aviso is-erro" role="alert"><AlertTriangle size={16} />{erro}</div>}
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
