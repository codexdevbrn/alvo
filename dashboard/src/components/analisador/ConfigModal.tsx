import { X } from 'lucide-react';
import { NumberStepper } from './NumberStepper';

export interface ConfigAnaliseState {
  granularidade: string;
  granularidadesDisponiveis: string[];
  periodosQueda: number;
  quedaMinimaAlertaRs: number | '';
  topNProdutos: number | '';
  reducaoMinimaErosao: number;
  quedaMinimaErosaoRs: number | '';
  reducaoMinimaSemVenda: number;
  topNPoderCompra: number | '';
  excluirPeriodoAtual: boolean;
  caminhoFonteInput: string;
  caminhoFonte: string | null;
  caminhoTrabalhoInput: string;
  caminhoTrabalho: string | null;
}

interface ConfigModalProps {
  aberto: boolean;
  onFechar: () => void;
  config: ConfigAnaliseState;
  onChange: (patch: Partial<ConfigAnaliseState>) => void;
  onSalvarCaminho: () => void;
}

function CampoNumero({
  label,
  value,
  onChange,
  placeholder,
}: {
  label: string;
  value: number | '';
  onChange: (v: number | '') => void;
  placeholder?: string;
}) {
  return (
    <label className="config-modal-campo-linha">
      <span>{label}</span>
      <NumberStepper value={value} onChange={onChange} placeholder={placeholder} />
    </label>
  );
}

export function ConfigModal({ aberto, onFechar, config, onChange, onSalvarCaminho }: ConfigModalProps) {
  if (!aberto) return null;

  return (
    <div className="config-modal-overlay" onClick={onFechar} role="presentation">
      <div
        className="config-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="config-modal-titulo"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="config-modal-header">
          <h2 id="config-modal-titulo">Configurações da análise</h2>
          <button type="button" className="analisador-btn analisador-btn-sec" onClick={onFechar} aria-label="Fechar">
            <X size={16} />
          </button>
        </header>

        <div className="config-modal-body custom-scrollbar">
          <section className="config-modal-secao">
            <h3>Pastas de dados</h3>
            <label className="analisador-campo">
              <span>Pasta fonte (BI, somente leitura)</span>
              <input
                className="analisador-input"
                value={config.caminhoFonteInput}
                onChange={(e) => onChange({ caminhoFonteInput: e.target.value })}
                placeholder="Ex.: C:\...\clientes-fonte"
              />
            </label>
            <p className="analisador-hint">
              Subpastas com BI/. O app nunca cria, altera nem apaga nada nesta pasta.
            </p>
            <label className="analisador-campo">
              <span>Pasta de trabalho (Base.csv / config.json)</span>
              <input
                className="analisador-input"
                value={config.caminhoTrabalhoInput}
                onChange={(e) => onChange({ caminhoTrabalhoInput: e.target.value })}
                placeholder="Ex.: C:\...\clientes-trabalho"
              />
            </label>
            <p className="analisador-hint">
              Onde ficam Base.csv, config.json e harm.xlsx. Deve ser distinta da fonte.
            </p>
            <div className="analisador-acoes">
              <button type="button" onClick={onSalvarCaminho} className="analisador-btn analisador-btn-pri">
                Salvar caminhos
              </button>
            </div>
            {(config.caminhoFonte || config.caminhoTrabalho) && (
              <p className="analisador-hint">
                Fonte: {config.caminhoFonte || '—'}
                <br />
                Trabalho: {config.caminhoTrabalho || '—'}
              </p>
            )}
          </section>

          <section className="config-modal-secao">
            <h3>Análise geral</h3>
            <div className="analisador-grid-campos analisador-grid-campos-2">
              <label className="analisador-campo">
                <span>Granularidade</span>
                <select
                  className="custom-select analisador-select"
                  value={config.granularidade}
                  onChange={(e) => onChange({ granularidade: e.target.value })}
                >
                  {config.granularidadesDisponiveis.map((g) => (
                    <option key={g} value={g}>{g}</option>
                  ))}
                </select>
              </label>
            </div>
            <div className="analisador-checks">
              <label className="analisador-check-linha">
                <input
                  type="checkbox"
                  checked={config.excluirPeriodoAtual}
                  onChange={(e) => onChange({ excluirPeriodoAtual: e.target.checked })}
                />
                Excluir período atual (incompleto)
              </label>
            </div>
          </section>

          <section className="config-modal-secao">
            <h3>Alertas de Queda Consecutiva</h3>
            <CampoNumero
              label="Períodos mínimos seguidos em queda:"
              value={config.periodosQueda}
              onChange={(v) => onChange({ periodosQueda: v === '' ? 2 : v })}
            />
            <CampoNumero
              label="Queda mínima em R$ p/ alerta:"
              value={config.quedaMinimaAlertaRs}
              onChange={(v) => onChange({ quedaMinimaAlertaRs: v })}
              placeholder="0 = sem piso"
            />
            <CampoNumero
              label="Produtos a exibir (top N por tendência):"
              value={config.topNProdutos}
              onChange={(v) => onChange({ topNProdutos: v })}
              placeholder="Vazio = todos"
            />
            <p className="analisador-hint">
              Vale para &quot;Alertas de Queda Consecutiva&quot; (usa a mesma tendência interna do gráfico &quot;Evolução no Tempo&quot;).
            </p>
          </section>

          <section className="config-modal-secao">
            <h3>Erosão de Clientes</h3>
            <CampoNumero
              label="Redução mínima p/ erosão (%):"
              value={config.reducaoMinimaErosao}
              onChange={(v) => onChange({ reducaoMinimaErosao: v === '' ? 50 : v })}
            />
            <CampoNumero
              label="Queda mínima em R$ p/ erosão:"
              value={config.quedaMinimaErosaoRs}
              onChange={(v) => onChange({ quedaMinimaErosaoRs: v })}
              placeholder="0 = sem piso"
            />
            <p className="analisador-hint">
              Vale para &quot;Erosão de Clientes por Produto&quot;.
            </p>
          </section>

          <section className="config-modal-secao">
            <h3>Sem Venda</h3>
            <CampoNumero
              label="Redução mínima p/ Sem Venda (%):"
              value={config.reducaoMinimaSemVenda}
              onChange={(v) => onChange({ reducaoMinimaSemVenda: v === '' ? 90 : v })}
            />
            <p className="analisador-hint">
              Sem piso de R$ de propósito — pega também clientes de baixo volume.
            </p>
          </section>

          <section className="config-modal-secao">
            <h3>Poder de Compra por Cliente (3 maiores meses)</h3>
            <CampoNumero
              label="Máximo de clientes a exibir:"
              value={config.topNPoderCompra}
              onChange={(v) => onChange({ topNPoderCompra: v })}
              placeholder="Vazio = todos"
            />
            <p className="analisador-hint">
              Maior Poder de Compra primeiro. Vazio = todos os clientes.
            </p>
          </section>
        </div>

        <footer className="config-modal-footer">
          <button type="button" className="analisador-btn analisador-btn-pri" onClick={onFechar}>
            Concluído
          </button>
        </footer>
      </div>
    </div>
  );
}
