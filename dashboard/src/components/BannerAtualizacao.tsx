import { useState } from 'react';
import { Download, Loader2, X } from 'lucide-react';
import { aplicarAtualizacao, type StatusAtualizacao } from '../api/client';

const LS_DISPENSADA = 'prisma_atualizacao_dispensada';

/** Versão cuja faixa o usuário já fechou, para não reaparecer a cada navegação. */
function lerDispensada(): string | null {
  try {
    return localStorage.getItem(LS_DISPENSADA);
  } catch {
    return null;
  }
}

function gravarDispensada(versao: string) {
  try {
    localStorage.setItem(LS_DISPENSADA, versao);
  } catch {
    /* private mode */
  }
}

interface Props {
  status: StatusAtualizacao;
}

/**
 * Faixa no topo avisando de versão nova, com o botão de aplicar ali mesmo.
 *
 * Existe porque o ponto discreto no ícone de Configurações passava desapercebido:
 * o app agora fica rodando em segundo plano por dias, e ninguém abre aquela tela
 * sem motivo. A faixa é dispensável e a dispensa é por versão — fechar hoje não
 * esconde a próxima release.
 */
export function BannerAtualizacao({ status }: Props) {
  const versao = status.versao_disponivel ?? '';
  const [fechado, setFechado] = useState(() => lerDispensada() === versao);
  const [aplicando, setAplicando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);

  if (!status.atualizavel || !versao || fechado) return null;

  const aplicar = async () => {
    setAplicando(true);
    setErro(null);
    try {
      await aplicarAtualizacao();
      // O backend se encerra logo após responder; daqui não há mais nada a fazer
      // além de manter o botão travado até o app voltar.
    } catch (e) {
      setErro((e as Error).message);
      setAplicando(false);
    }
  };

  return (
    <div className="banner-atualizacao" role="status">
      <div className="banner-atualizacao-texto">
        <strong>Versão {versao} disponível</strong>
        {status.notas && <span>{status.notas}</span>}
        {erro && <span className="banner-atualizacao-erro">{erro}</span>}
      </div>

      <button
        type="button"
        className="analisador-btn analisador-btn-pri banner-atualizacao-acao"
        onClick={() => void aplicar()}
        disabled={aplicando}
      >
        {aplicando ? <Loader2 size={14} className="dashboard-filter-spinner" /> : <Download size={14} />}
        {aplicando ? 'Atualizando...' : 'Atualizar agora'}
      </button>

      <button
        type="button"
        className="banner-atualizacao-fechar"
        onClick={() => { gravarDispensada(versao); setFechado(true); }}
        aria-label="Dispensar aviso desta versão"
        title="Dispensar até a próxima versão"
      >
        <X size={15} />
      </button>
    </div>
  );
}
