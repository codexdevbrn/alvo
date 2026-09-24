import { useEffect, useState } from 'react';
import { AlertTriangle, Loader2, Stethoscope } from 'lucide-react';
import { AppShell } from '../components/AppShell';
import { TensaoHero } from '../components/diagnostico/TensaoHero';
import { CascataReceita } from '../components/diagnostico/CascataReceita';
import { TornadoProdutos } from '../components/diagnostico/TornadoProdutos';
import { RadarPercentual } from '../components/diagnostico/RadarPercentual';
import { FluxoFaixas } from '../components/diagnostico/FluxoFaixas';
import { MatrizStreak } from '../components/diagnostico/MatrizStreak';
import { ScatterRisco } from '../components/diagnostico/ScatterRisco';
import { DumbbellQuantidade } from '../components/diagnostico/DumbbellQuantidade';
import { MatrizErosao } from '../components/diagnostico/MatrizErosao';
import { ImpactoChurn } from '../components/diagnostico/ImpactoChurn';
import { MargemGiro } from '../components/diagnostico/MargemGiro';
import {
  obterPainelDiagnostico,
  type DiagnosticoResposta,
  type ImpactoChurnDiagnostico,
  type RadarPercentualDiagnostico,
} from '../api/client';
import { useEscopoAtual } from '../hooks/useEscopoAtual';
import { useMesesFechados } from '../hooks/useMesesFechados';
import { useVersaoCortesRelatorios } from '../hooks/useVersaoCortesRelatorios';
import { useGruposClientesFiltro } from '../hooks/useGruposClientesFiltro';
import { gruposClientesParam } from '../utils/gruposClientesFiltro';

const IMPACTO_CHURN_VAZIO: ImpactoChurnDiagnostico = {
  receita_sob_risco: null, maior_retracao_pct: null, variacao_global_pct: null,
};
const RADAR_PERCENTUAL_VAZIO: RadarPercentualDiagnostico = {
  disponivel: false, mensagem: null, alta: [], queda: [],
};

/** Diagnóstico da carteira, em atos: o que aconteceu (tensão), por que mudou
 *  (mecanismo) e — nas próximas fases — sobre quem falar (pauta).
 *
 *  A ordem das seções é a leitura: quem chega na tela recebe o tamanho do
 *  movimento antes da explicação, e a explicação antes do detalhe. */
export default function DiagnosticoPage() {
  const { empresa, loja } = useEscopoAtual();
  const [modoPeriodo] = useMesesFechados();
  const versaoCortes = useVersaoCortesRelatorios();
  const gruposClientes = useGruposClientesFiltro();
  const gruposParam = gruposClientesParam(gruposClientes);

  const [dados, setDados] = useState<DiagnosticoResposta | null>(null);
  const [carregando, setCarregando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);

  useEffect(() => {
    if (!empresa) {
      setDados(null);
      return;
    }
    let vivo = true;
    setCarregando(true);
    setErro(null);
    void obterPainelDiagnostico(empresa, loja, modoPeriodo, gruposParam)
      .then((resposta) => {
        if (vivo) setDados(resposta);
      })
      .catch((falha) => {
        if (!vivo) return;
        setDados(null);
        setErro(falha instanceof Error ? falha.message : 'Falha ao carregar o diagnóstico.');
      })
      .finally(() => {
        if (vivo) setCarregando(false);
      });
    return () => {
      vivo = false;
    };
  }, [empresa, loja, modoPeriodo, versaoCortes, gruposParam]);

  return (
    <AppShell>
      <div className="dashboard-container diagnostico-page">
        <header className="app-page-header">
          <div>
            <h1>Diagnóstico{empresa && <span className="analisador-header-empresa"> · {empresa}</span>}</h1>
            <p>O que mudou no período, por quê, e onde agir.</p>
          </div>
        </header>

        {!empresa && (
          <div className="glass-card glass-card-flat estoque-vazio">
            <Stethoscope size={24} aria-hidden="true" />
            <div>
              <strong>Selecione uma empresa</strong>
              <p>Use o seletor no topo da tela para carregar o diagnóstico da carteira.</p>
            </div>
          </div>
        )}

        {empresa && carregando && !dados && (
          <div className="glass-card estoque-carregando" role="status">
            <Loader2 size={20} className="dashboard-filter-spinner" /> Lendo a carteira…
          </div>
        )}

        {empresa && erro && (
          <div className="glass-card glass-card-flat analisador-erro" role="alert">
            <AlertTriangle size={17} /> {erro}
          </div>
        )}

        {empresa && dados && !dados.disponivel && (
          <div className="glass-card glass-card-flat estoque-vazio" role="status">
            <AlertTriangle size={22} aria-hidden="true" />
            <div>
              <strong>Diagnóstico indisponível</strong>
              <p>{dados.mensagem || 'A base não tem período suficiente para comparar.'}</p>
            </div>
          </div>
        )}

        {empresa && dados?.disponivel && dados.tensao && (
          <>
            <TensaoHero tensao={dados.tensao} rotuloPeriodo={dados.rotulo_periodo} />
            {/* `?? IMPACTO_CHURN_VAZIO`/`RADAR_PERCENTUAL_VAZIO`: cache local
                (`cacheRequisicoes.ts`) não tem versão — uma resposta salva antes
                desses dois campos existirem no backend fica servida do jeito que
                está até expirar sozinha ou a pessoa limpar o cache. */}
            <ImpactoChurn impacto={dados.impacto_churn ?? IMPACTO_CHURN_VAZIO} />
            <div className="diagnostico-mecanismo diagnostico-mecanismo-3col">
              <CascataReceita cascata={dados.cascata} />
              <ScatterRisco risco={dados.risco} />
              <MargemGiro margemGiro={dados.margem_giro} />
            </div>
            <div className="diagnostico-mecanismo">
              <TornadoProdutos
                linhas={dados.tornado}
                rotuloAnterior={dados.tensao.rotulo_anterior}
                rotuloPeriodo={dados.rotulo_periodo}
              />
              <DumbbellQuantidade queda={dados.queda_quantidade} />
            </div>
            <RadarPercentual radar={dados.radar_percentual ?? RADAR_PERCENTUAL_VAZIO} />
            <div className="diagnostico-mecanismo">
              <FluxoFaixas fluxo={dados.fluxo_faixas} />
              <MatrizStreak streak={dados.streak} />
            </div>
            <MatrizErosao matriz={dados.matriz_erosao} />
          </>
        )}
      </div>
    </AppShell>
  );
}
