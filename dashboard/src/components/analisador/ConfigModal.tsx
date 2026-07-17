import { useState } from 'react';
import { FolderOpen, Loader2, Plus, RefreshCw, Trash2, X } from 'lucide-react';
import type { TagCatalogoItem } from '../../api/client';
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
  empresa: string | null;
  tagsCatalogo: TagCatalogoItem[];
}

interface ConfigModalProps {
  aberto: boolean;
  onFechar: () => void;
  config: ConfigAnaliseState;
  onChange: (patch: Partial<ConfigAnaliseState>) => void;
  onSalvarCaminho: () => void;
  /** Abre diálogo nativo e devolve o caminho (null = cancelado). */
  onBuscarPasta: (campo: 'fonte' | 'trabalho') => Promise<string | null>;
  onSalvarTagsCatalogo: () => void | Promise<void>;
  salvandoTagsCatalogo?: boolean;
  /** Força regenerar Base.csv da empresa selecionada e recarregar. */
  onRegenerarBase?: () => void | Promise<void>;
  regenerandoBase?: boolean;
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

function slugifyTag(rotulo: string): string {
  return rotulo
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '')
    .slice(0, 48) || 'tag';
}

function novoIdTag(rotulo: string, existentes: Set<string>): string {
  const base = slugifyTag(rotulo) || 'tag';
  let id = base;
  let n = 2;
  while (existentes.has(id)) {
    id = `${base}_${n}`;
    n += 1;
  }
  return id;
}

export function ConfigModal({
  aberto,
  onFechar,
  config,
  onChange,
  onSalvarCaminho,
  onBuscarPasta,
  onSalvarTagsCatalogo,
  salvandoTagsCatalogo = false,
  onRegenerarBase,
  regenerandoBase = false,
}: ConfigModalProps) {
  const [buscando, setBuscando] = useState<'fonte' | 'trabalho' | null>(null);
  const [erroBusca, setErroBusca] = useState<string | null>(null);

  if (!aberto) return null;

  const buscar = async (campo: 'fonte' | 'trabalho') => {
    setErroBusca(null);
    setBuscando(campo);
    try {
      const escolhido = await onBuscarPasta(campo);
      if (escolhido == null) return;
      if (campo === 'fonte') onChange({ caminhoFonteInput: escolhido });
      else onChange({ caminhoTrabalhoInput: escolhido });
    } catch (e) {
      setErroBusca(e instanceof Error ? e.message : 'Falha ao abrir o seletor de pasta.');
    } finally {
      setBuscando(null);
    }
  };

  const atualizarTag = (id: string, patch: Partial<TagCatalogoItem>) => {
    const proximo = config.tagsCatalogo.map((item) =>
      item.id === id ? { ...item, ...patch } : item,
    );
    onChange({ tagsCatalogo: proximo });
  };

  const removerTag = (id: string) => {
    onChange({ tagsCatalogo: config.tagsCatalogo.filter((item) => item.id !== id) });
  };

  const adicionarTag = () => {
    const rotulo = 'Nova tag';
    const ids = new Set(config.tagsCatalogo.map((item) => item.id));
    onChange({
      tagsCatalogo: [
        ...config.tagsCatalogo,
        {
          id: novoIdTag(rotulo, ids),
          rotulo,
          ativa: true,
          cor: '#64748b',
        },
      ],
    });
  };

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
              <div className="caminho-pasta-row">
                <input
                  className="analisador-input"
                  value={config.caminhoFonteInput}
                  onChange={(e) => onChange({ caminhoFonteInput: e.target.value })}
                  placeholder="Ex.: C:\...\clientes-fonte"
                />
                <button
                  type="button"
                  className="analisador-btn analisador-btn-sec caminho-pasta-btn"
                  onClick={() => buscar('fonte')}
                  disabled={buscando !== null}
                  title="Buscar pasta"
                  aria-label="Buscar pasta fonte"
                >
                  {buscando === 'fonte'
                    ? <Loader2 size={14} className="dashboard-filter-spinner" />
                    : <FolderOpen size={14} />}
                  Buscar
                </button>
              </div>
            </label>
            <p className="analisador-hint">
              Subpastas com BI/. O app nunca cria, altera nem apaga nada nesta pasta.
            </p>
            <label className="analisador-campo">
              <span>Pasta de trabalho (Base.csv / config.json)</span>
              <div className="caminho-pasta-row">
                <input
                  className="analisador-input"
                  value={config.caminhoTrabalhoInput}
                  onChange={(e) => onChange({ caminhoTrabalhoInput: e.target.value })}
                  placeholder="Ex.: C:\...\clientes-trabalho"
                />
                <button
                  type="button"
                  className="analisador-btn analisador-btn-sec caminho-pasta-btn"
                  onClick={() => buscar('trabalho')}
                  disabled={buscando !== null}
                  title="Buscar pasta"
                  aria-label="Buscar pasta de trabalho"
                >
                  {buscando === 'trabalho'
                    ? <Loader2 size={14} className="dashboard-filter-spinner" />
                    : <FolderOpen size={14} />}
                  Buscar
                </button>
              </div>
            </label>
            <p className="analisador-hint">
              Onde ficam Base.csv, config.json e harm.xlsx. Deve ser distinta da fonte.
            </p>
            {erroBusca && (
              <p style={{ margin: 0, fontSize: '0.85rem', color: '#f43f5e' }}>{erroBusca}</p>
            )}
            <div className="analisador-acoes">
              <button type="button" onClick={onSalvarCaminho} className="analisador-btn analisador-btn-pri">
                Salvar caminhos
              </button>
              {onRegenerarBase && (
                <button
                  type="button"
                  className="analisador-btn analisador-btn-sec"
                  onClick={() => void onRegenerarBase()}
                  disabled={!config.empresa || regenerandoBase || buscando !== null}
                  title={config.empresa
                    ? `Regenerar Base.csv de ${config.empresa} a partir do BI`
                    : 'Selecione uma empresa na tela principal'}
                >
                  {regenerandoBase
                    ? <Loader2 size={14} className="dashboard-filter-spinner" />
                    : <RefreshCw size={14} />}
                  Regenerar base
                </button>
              )}
            </div>
            <p className="analisador-hint">
              Regenerar base força a leitura do BI, recria o Base.csv e recarrega a empresa
              {config.empresa ? ` (${config.empresa})` : ''} — mesmo se a origem não tiver mudado de data.
            </p>
            {(config.caminhoFonte || config.caminhoTrabalho) && (
              <p className="analisador-hint">
                Fonte: {config.caminhoFonte || '—'}
                <br />
                Trabalho: {config.caminhoTrabalho || '—'}
              </p>
            )}
          </section>

          <section className="config-modal-secao">
            <h3>Tags de clientes</h3>
            <p className="analisador-hint">
              Defina as tags disponíveis na prévia de clientes. Tags desativadas ficam ocultas;
              ao excluir uma tag, as atribuições nos clientes são removidas ao salvar.
            </p>
            {!config.empresa && (
              <p className="analisador-hint" style={{ color: '#f59e0b' }}>
                Selecione uma empresa na tela principal para salvar as tags.
              </p>
            )}
            {config.tagsCatalogo.length === 0 ? (
              <p className="analisador-hint">Nenhuma tag cadastrada.</p>
            ) : (
              <ul className="config-tag-lista">
                {config.tagsCatalogo.map((tag) => (
                  <li key={tag.id}>
                    <label className="analisador-campo">
                      <span>Nome</span>
                      <div className="caminho-pasta-row">
                        <input
                          type="color"
                          className="config-tag-cor"
                          value={tag.cor}
                          onChange={(e) => atualizarTag(tag.id, { cor: e.target.value })}
                          title="Cor da tag"
                          aria-label={`Cor da tag ${tag.rotulo}`}
                        />
                        <input
                          className="analisador-input"
                          value={tag.rotulo}
                          onChange={(e) => atualizarTag(tag.id, { rotulo: e.target.value })}
                          placeholder="Nome da tag"
                          aria-label={`Rótulo da tag ${tag.rotulo}`}
                        />
                        <button
                          type="button"
                          className="analisador-btn analisador-btn-sec caminho-pasta-btn"
                          onClick={() => removerTag(tag.id)}
                          title="Excluir tag"
                          aria-label={`Excluir tag ${tag.rotulo}`}
                        >
                          <Trash2 size={14} />
                        </button>
                      </div>
                    </label>
                    <div className="analisador-checks">
                      <label className="analisador-check-linha">
                        <input
                          type="checkbox"
                          checked={tag.ativa}
                          onChange={(e) => atualizarTag(tag.id, { ativa: e.target.checked })}
                        />
                        Exibir na prévia
                      </label>
                    </div>
                  </li>
                ))}
              </ul>
            )}
            <div className="analisador-acoes">
              <button
                type="button"
                className="analisador-btn analisador-btn-sec"
                onClick={adicionarTag}
              >
                <Plus size={14} />
                Adicionar tag
              </button>
              <button
                type="button"
                onClick={() => void onSalvarTagsCatalogo()}
                disabled={!config.empresa || salvandoTagsCatalogo}
                className="analisador-btn analisador-btn-pri"
              >
                {salvandoTagsCatalogo ? 'Salvando...' : 'Salvar tags'}
              </button>
            </div>
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
