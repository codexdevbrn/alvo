import { useState } from 'react';
import { ExternalLink, Loader2, RefreshCw } from 'lucide-react';
import { AppShell } from '../components/AppShell';

/**
 * URL do Pregão Mercadológico.
 *
 * Fica aqui, num lugar só, e não em `config_app` como os caminhos de dados: é uma
 * constante de produto, não configuração por máquina. Se o endereço mudar, é esta
 * linha, um build e uma release — que agora chega sozinha pelo canal de
 * atualização. Se virar coisa que muda com frequência, aí vale um campo em
 * Configurações.
 */
const URL_MERCADOLOGICO = 'http://77.37.126.180:5900/';

/**
 * Pregão Mercadológico embutido numa aba do Prisma.
 *
 * É um iframe, com uma consequência que não tem contorno: o conteúdo lá dentro
 * mantém o CSS dele. O navegador isola documentos de origens diferentes, então o
 * Prisma não pode — nem poderia — reestilizar aquele conteúdo. O que esta tela
 * entrega é a navegação integrada (sidebar, seleção de empresa, mesma janela); o
 * visual interno continua sendo o do outro sistema.
 */
export default function MercadologicoPage() {
  const [carregando, setCarregando] = useState(true);
  const [falhou, setFalhou] = useState(false);
  // Muda a key para forçar o iframe a recarregar sem tocar no histórico do
  // navegador (mexer no src reescreveria a navegação do documento embutido).
  const [tentativa, setTentativa] = useState(0);

  const recarregar = () => {
    setCarregando(true);
    setFalhou(false);
    setTentativa((n) => n + 1);
  };

  return (
    <AppShell>
      <header className="mercadologico-cabecalho">
        <div>
          <h1>Dados mercadológicos</h1>
          <p>Pregão Mercadológico — sistema externo, aberto aqui dentro.</p>
        </div>
        <div className="mercadologico-acoes">
          <button type="button" className="analisador-btn analisador-btn-sec" onClick={recarregar}>
            <RefreshCw size={14} />
            Recarregar
          </button>
          <a
            className="analisador-btn analisador-btn-sec"
            href={URL_MERCADOLOGICO}
            target="_blank"
            rel="noopener noreferrer"
          >
            <ExternalLink size={14} />
            Abrir em nova aba
          </a>
        </div>
      </header>

      <div className="mercadologico-moldura">
        {carregando && !falhou && (
          <div className="mercadologico-estado">
            <Loader2 size={20} className="dashboard-filter-spinner" />
            <span>Carregando o Pregão Mercadológico...</span>
          </div>
        )}

        {falhou && (
          <div className="mercadologico-estado">
            <strong>Não foi possível carregar</strong>
            <span>
              O servidor do Pregão ({URL_MERCADOLOGICO}) não respondeu. Ele fica fora do
              Prisma, então isto costuma ser rede ou o serviço estar parado.
            </span>
            <button type="button" className="analisador-btn analisador-btn-sec" onClick={recarregar}>
              <RefreshCw size={14} />
              Tentar de novo
            </button>
          </div>
        )}

        <iframe
          key={tentativa}
          className="mercadologico-iframe"
          src={URL_MERCADOLOGICO}
          title="Pregão Mercadológico"
          onLoad={() => setCarregando(false)}
          // `onError` de iframe não dispara em erro HTTP nem em recusa de conexão;
          // serve só para falha de carregamento do próprio elemento. O estado de
          // erro real fica a cargo do usuário perceber e clicar em recarregar —
          // detectar de fora exigiria acessar o documento, que a origem cruzada
          // impede.
          onError={() => { setCarregando(false); setFalhou(true); }}
          // Sem `allow-same-origin` o app externo perderia cookies e
          // localStorage próprios e provavelmente não funcionaria; o sandbox aqui
          // limita o que ele pode fazer com a PÁGINA que o contém.
          sandbox="allow-scripts allow-same-origin allow-forms allow-popups allow-downloads"
          referrerPolicy="no-referrer"
        />
      </div>
    </AppShell>
  );
}
