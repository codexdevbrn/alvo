import { Component, type ErrorInfo, type ReactNode } from 'react';
import { AlertTriangle } from 'lucide-react';

type Props = { children: ReactNode };
type State = { erro: Error | null };

/** Sem isto, um erro de render em qualquer tela (ex.: campo inesperado numa
 *  resposta da API) derruba a árvore inteira do React e a página fica em
 *  branco — sobre o fundo escuro do tema, isso aparece como tela preta. */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { erro: null };

  static getDerivedStateFromError(erro: Error): State {
    return { erro };
  }

  componentDidCatch(erro: Error, info: ErrorInfo) {
    console.error('Erro não tratado na interface:', erro, info.componentStack);
  }

  render() {
    if (this.state.erro) {
      return (
        <div className="app-error-boundary">
          <div className="glass-card glass-card-flat app-error-boundary-card">
            <AlertTriangle size={24} aria-hidden="true" />
            <div>
              <strong>Algo deu errado nesta tela</strong>
              <p>{this.state.erro.message || 'Erro inesperado ao renderizar a página.'}</p>
            </div>
            <button type="button" className="analisador-btn" onClick={() => window.location.reload()}>
              Recarregar
            </button>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}
