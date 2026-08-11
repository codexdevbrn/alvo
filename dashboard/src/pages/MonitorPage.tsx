import { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { AlertTriangle, RefreshCw, Search } from 'lucide-react';
import { AppShell } from '../components/AppShell';
import { EmpresaMiniCard } from '../components/monitor/EmpresaMiniCard';
import { selecionarEmpresaGlobal } from '../utils/empresaSelecionada';
import {
  obterMonitorEmpresas,
  salvarFavoritas,
  type EmpresaMonitor,
  type MetricaMonitor,
  type MonitorResposta,
} from '../api/client';

const LS_METRICA = 'monitor_metrica';
const LS_MESES = 'monitor_meses';
const LS_BUSCA = 'monitor_busca';
const LS_ORDENACAO = 'monitor_ordenacao';
const LS_ESCOPO = 'monitor_escopo';
const MESES_PADRAO = 12;

type OrdenacaoMonitor = 'nome' | 'valor' | 'variacao';
type EscopoMonitor = 'favoritas' | 'todas';

function lerMetrica(): MetricaMonitor {
  const valor = localStorage.getItem(LS_METRICA);
  return valor === 'qtd' || valor === 'clientes' || valor === 'receita_dia'
    ? valor
    : 'receita';
}

function lerMeses(): number {
  const valor = Number(localStorage.getItem(LS_MESES));
  return Number.isFinite(valor) && valor >= 1 && valor <= 60 ? valor : MESES_PADRAO;
}

function lerOrdenacao(): OrdenacaoMonitor {
  const valor = localStorage.getItem(LS_ORDENACAO);
  return valor === 'valor' || valor === 'variacao' ? valor : 'nome';
}

function normalizarBusca(valor: string): string {
  return valor.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLocaleLowerCase('pt-BR');
}

function valorPrincipal(item: EmpresaMonitor, metrica: MetricaMonitor): number {
  return metrica === 'receita_dia' ? (item.media ?? 0) : (item.total ?? 0);
}

export default function MonitorPage() {
  const navigate = useNavigate();
  const [metrica, setMetrica] = useState<MetricaMonitor>(lerMetrica);
  const [meses, setMeses] = useState<number>(lerMeses);
  const [busca, setBusca] = useState(() => localStorage.getItem(LS_BUSCA) || '');
  const [ordenacao, setOrdenacao] = useState<OrdenacaoMonitor>(lerOrdenacao);
  const [escopo, setEscopo] = useState<EscopoMonitor>(() =>
    localStorage.getItem(LS_ESCOPO) === 'favoritas' ? 'favoritas' : 'todas',
  );
  const [dados, setDados] = useState<MonitorResposta | null>(null);
  const [carregando, setCarregando] = useState(true);
  const [erro, setErro] = useState<string | null>(null);
  const [favoritas, setFavoritas] = useState<string[]>([]);
  const [salvandoFavorita, setSalvandoFavorita] = useState(false);

  useEffect(() => {
    localStorage.setItem(LS_METRICA, metrica);
    localStorage.setItem(LS_MESES, String(meses));
    localStorage.setItem(LS_BUSCA, busca);
    localStorage.setItem(LS_ORDENACAO, ordenacao);
    localStorage.setItem(LS_ESCOPO, escopo);
  }, [metrica, meses, busca, ordenacao, escopo]);

  const carregar = useCallback((forcar = false, signal?: AbortSignal) => {
    setCarregando(true);
    setErro(null);
    return obterMonitorEmpresas({ metrica, meses, forcar }, signal)
      .then((resposta) => {
        setDados(resposta);
        setFavoritas(resposta.favoritas ?? []);
      })
      .catch((e) => {
        if (signal?.aborted) return;
        setErro(e instanceof Error ? e.message : 'Falha ao carregar o monitoramento.');
      })
      .finally(() => {
        if (!signal?.aborted) setCarregando(false);
      });
  }, [metrica, meses]);

  useEffect(() => {
    const controller = new AbortController();
    void carregar(false, controller.signal);
    return () => controller.abort();
  }, [carregar]);

  /** Atualização otimista: estrela reage sem esperar rede e reverte se salvar falhar. */
  const alternarFavorita = async (empresa: string) => {
    const proximas = favoritas.includes(empresa)
      ? favoritas.filter((nome) => nome !== empresa)
      : [...favoritas, empresa];
    const anteriores = favoritas;
    setFavoritas(proximas);
    setSalvandoFavorita(true);
    try {
      const salvas = await salvarFavoritas(proximas);
      setFavoritas(salvas.empresas);
    } catch (e) {
      setFavoritas(anteriores);
      setErro(e instanceof Error ? e.message : 'Não foi possível salvar as favoritas.');
    } finally {
      setSalvandoFavorita(false);
    }
  };

  /** O card promete "abrir o Dashboard da empresa" — selecionar sem navegar
   *  deixava o usuario na mesma tela achando que nada aconteceu. Usa a mesma
   *  porta de entrada da sidebar, para o Dashboard montar ja com a empresa certa
   *  em vez de carregar a anterior e trocar depois. */
  const abrirDashboard = useCallback((empresa: string) => {
    selecionarEmpresaGlobal(empresa);
    navigate('/');
  }, [navigate]);

  const empresas = useMemo<EmpresaMonitor[]>(() => dados?.empresas ?? [], [dados]);
  const empresasVisiveis = useMemo(() => {
    const termo = normalizarBusca(busca.trim());
    return empresas
      .filter((item) => escopo === 'todas' || favoritas.includes(item.empresa))
      .filter((item) => !termo || normalizarBusca(item.empresa).includes(termo))
      .sort((a, b) => {
        if (ordenacao === 'valor') {
          return valorPrincipal(b, metrica) - valorPrincipal(a, metrica);
        }
        if (ordenacao === 'variacao') {
          return (b.variacao_pct ?? Number.NEGATIVE_INFINITY)
            - (a.variacao_pct ?? Number.NEGATIVE_INFINITY);
        }
        return a.empresa.localeCompare(b.empresa, 'pt-BR', { sensitivity: 'base' });
      });
  }, [busca, empresas, escopo, favoritas, metrica, ordenacao]);

  return (
    <AppShell>
      <div className="dashboard-container monitor-page">
        <header className="monitor-header">
          <div>
            <h1>Monitoramento</h1>
            <p>
              {carregando && !dados
                ? 'Carregando empresas…'
                : erro && !dados
                  ? 'Não foi possível carregar'
                  : `${empresasVisiveis.length} de ${empresas.length} empresas · ${favoritas.length} favorita${favoritas.length === 1 ? '' : 's'}`}
            </p>
          </div>
          <button
            type="button"
            className="analisador-btn analisador-btn-sec analisador-btn-compact"
            onClick={() => void carregar(true)}
            disabled={carregando}
            title="Recalcular resumos a partir dos dados mais recentes"
          >
            <RefreshCw size={14} aria-hidden="true" className={carregando ? 'is-girando' : ''} />
            {carregando ? 'Atualizando…' : 'Recalcular'}
          </button>
        </header>

        <section className="glass-card monitor-filtros" aria-label="Filtros do monitoramento">
          <label className="analisador-campo monitor-busca">
            <span>Buscar empresa</span>
            <span className="monitor-input-icon-wrap">
              <Search size={15} aria-hidden="true" />
              <input
                className="analisador-input"
                type="search"
                value={busca}
                onChange={(evento) => setBusca(evento.target.value)}
                placeholder="Nome da empresa"
              />
            </span>
          </label>

          <label className="analisador-campo">
            <span>Métrica</span>
            <select
              className="custom-select analisador-select"
              value={metrica}
              onChange={(evento) => setMetrica(evento.target.value as MetricaMonitor)}
            >
              <option value="receita">Receita</option>
              <option value="receita_dia">Média de receita por dia útil</option>
              <option value="qtd">Quantidade</option>
              <option value="clientes">Clientes</option>
            </select>
          </label>

          <label className="analisador-campo monitor-periodos">
            <span>Últimos períodos</span>
            <input
              className="analisador-input"
              type="number"
              min={1}
              max={60}
              value={meses}
              onChange={(evento) => setMeses(
                Math.max(1, Math.min(60, Number(evento.target.value) || MESES_PADRAO)),
              )}
            />
          </label>

          <label className="analisador-campo">
            <span>Ordenar por</span>
            <select
              className="custom-select analisador-select"
              value={ordenacao}
              onChange={(evento) => setOrdenacao(evento.target.value as OrdenacaoMonitor)}
            >
              <option value="nome">Nome</option>
              <option value="valor">Maior valor</option>
              <option value="variacao">Maior variação</option>
            </select>
          </label>

          <div className="analisador-campo monitor-escopo">
            <span>Exibir</span>
            <div className="monitor-segmentado" role="group" aria-label="Empresas exibidas">
              <button
                type="button"
                className={escopo === 'favoritas' ? 'is-ativo' : ''}
                aria-pressed={escopo === 'favoritas'}
                onClick={() => setEscopo('favoritas')}
              >
                Favoritas
              </button>
              <button
                type="button"
                className={escopo === 'todas' ? 'is-ativo' : ''}
                aria-pressed={escopo === 'todas'}
                onClick={() => setEscopo('todas')}
              >
                Todas
              </button>
            </div>
          </div>
        </section>

        {metrica === 'receita_dia' && (
          <p className="monitor-nota">
            Receita mensal ÷ dias úteis do mês. Sábados e domingos são excluídos;
            feriados não. Último período pode estar incompleto.
          </p>
        )}

        {erro && (
          <div className="glass-card monitor-aviso" role="alert">
            <AlertTriangle size={18} aria-hidden="true" />
            <span>{erro}</span>
          </div>
        )}

        {carregando && !dados && (
          <div className="monitor-grid" aria-hidden="true">
            {Array.from({ length: 8 }, (_, indice) => (
              <div key={indice} className="glass-card monitor-card is-esqueleto" />
            ))}
          </div>
        )}

        {!carregando && !erro && empresas.length === 0 && (
          <div className="glass-card monitor-vazio">
            <p>Nenhuma empresa encontrada na pasta fonte.</p>
            <p className="analisador-hint">Confira os caminhos em Configurações.</p>
          </div>
        )}

        {!carregando && empresas.length > 0 && empresasVisiveis.length === 0 && (
          <div className="glass-card monitor-vazio">
            <p>{escopo === 'favoritas' && favoritas.length === 0
              ? 'Você ainda não favoritou nenhuma empresa.'
              : 'Nenhuma empresa corresponde aos filtros.'}</p>
            <p className="analisador-hint">
              {escopo === 'favoritas' && favoritas.length === 0
                ? 'Abra “Todas” e use a estrela para montar seu painel principal.'
                : 'Limpe a busca ou altere os filtros.'}
            </p>
          </div>
        )}

        {empresasVisiveis.length > 0 && (
          <div className="monitor-grid">
            {empresasVisiveis.map((item) => (
              <EmpresaMiniCard
                key={item.empresa}
                item={item}
                metrica={metrica}
                favorita={favoritas.includes(item.empresa)}
                salvandoFavorita={salvandoFavorita}
                onAlternarFavorita={(empresa) => void alternarFavorita(empresa)}
                onAbrir={abrirDashboard}
              />
            ))}
          </div>
        )}

        <p className="analisador-hint monitor-rodape-nota">
          Últimos {meses} períodos com movimento. Clique num card para abrir o Dashboard da empresa.
        </p>
      </div>
    </AppShell>
  );
}
