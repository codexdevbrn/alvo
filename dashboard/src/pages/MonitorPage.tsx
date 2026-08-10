import { useCallback, useEffect, useMemo, useState } from 'react';
import { AlertTriangle, RefreshCw } from 'lucide-react';
import { AppShell } from '../components/AppShell';
import {
  obterMonitorEmpresas,
  salvarFavoritas,
  type EmpresaMonitor,
  type MetricaMonitor,
  type MonitorResposta,
} from '../api/client';

const LS_METRICA = 'monitor_metrica';
const LS_MESES = 'monitor_meses';

/** Janela padrão: 12 períodos com movimento cobrem o ano corrente e dão base de
 *  comparação com o ano anterior nos cards. */
const MESES_PADRAO = 12;

function lerMetrica(): MetricaMonitor {
  const v = localStorage.getItem(LS_METRICA);
  return v === 'qtd' || v === 'clientes' ? v : 'receita';
}

function lerMeses(): number {
  const n = Number(localStorage.getItem(LS_MESES));
  return Number.isFinite(n) && n >= 1 && n <= 60 ? n : MESES_PADRAO;
}

export default function MonitorPage() {
  const [metrica, setMetrica] = useState<MetricaMonitor>(lerMetrica);
  const [meses, setMeses] = useState<number>(lerMeses);
  const [dados, setDados] = useState<MonitorResposta | null>(null);
  const [carregando, setCarregando] = useState(true);
  const [erro, setErro] = useState<string | null>(null);
  const [favoritas, setFavoritas] = useState<string[]>([]);
  const [salvandoFavorita, setSalvandoFavorita] = useState(false);

  useEffect(() => {
    localStorage.setItem(LS_METRICA, metrica);
    localStorage.setItem(LS_MESES, String(meses));
  }, [metrica, meses]);

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

  /** Otimista: a estrela responde na hora e volta atrás se o servidor recusar. */
  const alternarFavorita = async (empresa: string) => {
    const proximas = favoritas.includes(empresa)
      ? favoritas.filter((n) => n !== empresa)
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

  const empresas = useMemo<EmpresaMonitor[]>(() => dados?.empresas ?? [], [dados]);

  return (
    <AppShell>
      <div className="dashboard-container monitor-page">
        <header className="monitor-header">
          <div>
            <h1>Monitoramento</h1>
            <p>
              {/* Sem dados por causa de erro, a contagem seria "0 empresas" — o que
                  soa como base vazia, não como falha de conexão. */}
              {carregando && !dados
                ? 'Carregando empresas…'
                : erro && !dados
                  ? 'Não foi possível carregar'
                  : `${empresas.length} empresas · ${favoritas.length} favorita${favoritas.length === 1 ? '' : 's'}`}
            </p>
          </div>
          {/* Controles mínimos para o esqueleto funcionar de ponta a ponta. A
              barra completa (busca, ordenação, alternador Favoritas/Todas) é da
              Tarefa 5 do plano. */}
          <div className="monitor-header-acoes">
            <label className="analisador-campo">
              <span>Métrica</span>
              <select
                className="custom-select analisador-select"
                value={metrica}
                onChange={(e) => setMetrica(e.target.value as MetricaMonitor)}
              >
                <option value="receita">Receita</option>
                <option value="qtd">Quantidade</option>
                <option value="clientes">Clientes</option>
              </select>
            </label>

            <label className="analisador-campo">
              <span>Períodos</span>
              <input
                className="analisador-input"
                type="number"
                min={1}
                max={60}
                value={meses}
                onChange={(e) => setMeses(Math.max(1, Math.min(60, Number(e.target.value) || MESES_PADRAO)))}
              />
            </label>

            <button
              type="button"
              className="analisador-btn analisador-btn-sec analisador-btn-compact"
              onClick={() => void carregar(true)}
              disabled={carregando}
              title="Recalcula o resumo de todas as empresas a partir dos summaries"
            >
              <RefreshCw size={14} />
              {carregando ? 'Atualizando…' : 'Recalcular'}
            </button>
          </div>
        </header>

        {erro && (
          <div className="glass-card monitor-aviso" role="alert">
            <AlertTriangle size={18} color="#e0645c" />
            <span>{erro}</span>
          </div>
        )}

        {carregando && !dados && (
          <div className="monitor-grid" aria-hidden="true">
            {Array.from({ length: 8 }, (_, i) => (
              <div key={i} className="glass-card monitor-card is-esqueleto" />
            ))}
          </div>
        )}

        {!carregando && !erro && empresas.length === 0 && (
          <div className="glass-card monitor-vazio">
            <p>Nenhuma empresa encontrada na pasta fonte.</p>
            <p className="analisador-hint">
              Confira os caminhos em Configurações — a lista sai das subpastas com
              o arquivo de dados do BI.
            </p>
          </div>
        )}

        {/* Cards entram na Tarefa 4; aqui só a grade e os estados. */}
        {empresas.length > 0 && (
          <div className="monitor-grid">
            {empresas.map((item) => (
              <article key={item.empresa} className="glass-card monitor-card">
                <h2>{item.empresa}</h2>
                <p className="analisador-hint">
                  {item.estado === 'ok'
                    ? `${item.valores?.length ?? 0} períodos · ${item.updated_at ?? '—'}`
                    : item.detalhe}
                </p>
                <button
                  type="button"
                  onClick={() => void alternarFavorita(item.empresa)}
                  disabled={salvandoFavorita}
                >
                  {favoritas.includes(item.empresa) ? 'Favorita' : 'Favoritar'}
                </button>
              </article>
            ))}
          </div>
        )}

        <p className="analisador-hint">
          Métrica {metrica} · últimos {meses} períodos com movimento
        </p>
      </div>
    </AppShell>
  );
}
