import { useMemo, useState } from 'react';
import type { ItemProdutoPrevia } from '../../api/client';
import { formatCurrency, rotuloGrupoCurto } from '../../utils/formatters';

interface PreviaProdutosTableProps {
  itens: ItemProdutoPrevia[];
  excluidos: Set<string>;
  onToggle: (produto: string) => void;
  onToggleAll?: (produtos: string[], checkAll: boolean) => void;
  carregando?: boolean;
}

function formatarPct(valor: number | null): string {
  if (valor == null || Number.isNaN(valor)) return '—';
  return `${valor.toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}%`;
}

export function PreviaProdutosTable({ itens, excluidos, onToggle, onToggleAll, carregando }: PreviaProdutosTableProps) {
  const [busca, setBusca] = useState('');
  const [grupoFiltro, setGrupoFiltro] = useState('');
  const lista = useMemo(() => itens ?? [], [itens]);

  const gruposDisponiveis = useMemo(() => {
    const nomes = new Set(lista.map((item) => item.grupo));
    return Array.from(nomes).sort((a, b) => a.localeCompare(b, 'pt-BR'));
  }, [lista]);

  const itensFiltrados = useMemo(() => {
    const termo = busca.trim().toLowerCase();
    return lista.filter((item) => {
      if (grupoFiltro && item.grupo !== grupoFiltro) return false;
      if (termo && !item.produto.toLowerCase().includes(termo)) return false;
      return true;
    });
  }, [lista, busca, grupoFiltro]);

  // A tabela sempre mostra o catálogo completo (para permitir marcar/desmarcar
  // qualquer produto), então a contagem "de Y produtos" nunca muda com
  // exclusões. O que de fato varia — e o que importa para o usuário saber o
  // que entrará nos relatórios — é quantos desses itens estão INCLUÍDOS.
  //
  // Duas maneiras diferentes de ficar de fora, e elas não se misturam:
  // desmarcado à mão (checkbox) e fora por regra (abaixo do corte ou não
  // harmonizado, decidido pelos checkboxes do painel). A checkbox de cada
  // linha reflete só a primeira.
  const contagem = useMemo(() => {
    let manuais = 0;
    let demais = 0;
    let naoHarmonizados = 0;
    for (const item of itensFiltrados) {
      if (excluidos.has(item.produto)) manuais += 1;
      else if (item.fora_por_regra === 'demais') demais += 1;
      else if (item.fora_por_regra === 'nao_harmonizado') naoHarmonizados += 1;
    }
    return {
      manuais,
      demais,
      naoHarmonizados,
      dentro: itensFiltrados.length - manuais - demais - naoHarmonizados,
    };
  }, [itensFiltrados, excluidos]);

  const marcadosNoFiltro = itensFiltrados.length - contagem.manuais;
  const todosConsideradosFiltro = itensFiltrados.length > 0 && contagem.manuais === 0;
  const algumConsideradoFiltro = marcadosNoFiltro > 0;

  if (carregando) {
    return <p className="analisador-hint">Calculando prévia de produtos...</p>;
  }

  if (lista.length === 0) {
    return (
      <p className="analisador-hint">
        Clique em &quot;Atualizar prévia&quot; para ver os produtos por faixa.
      </p>
    );
  }

  return (
    <div className="analisador-previa">
      <div className="analisador-previa-filtros">
        <label className="analisador-campo">
          <span>Buscar</span>
          <input
            className="analisador-input"
            placeholder="Nome do produto..."
            value={busca}
            onChange={(e) => setBusca(e.target.value)}
          />
        </label>
        <label className="analisador-campo">
          <span>Grupo</span>
          <select
            className="custom-select analisador-select"
            value={grupoFiltro}
            onChange={(e) => setGrupoFiltro(e.target.value)}
          >
            <option value="">Todos</option>
            {gruposDisponiveis.map((grupo) => (
              <option key={grupo} value={grupo}>{rotuloGrupoCurto(grupo)}</option>
            ))}
          </select>
        </label>
      </div>

      <div className="analisador-tabela-wrap custom-scrollbar">
        <table className="analisador-tabela">
          <thead>
            <tr>
              <th className="col-check">
                <label className="analisador-check">
                  <input
                    type="checkbox"
                    aria-label="Incluir todos os produtos do filtro"
                    title="Incluir/excluir todos os produtos do filtro"
                    checked={todosConsideradosFiltro}
                    ref={(el) => {
                      if (el) el.indeterminate = algumConsideradoFiltro && !todosConsideradosFiltro;
                    }}
                    onChange={() => {
                      if (onToggleAll) {
                        const checkAll = !todosConsideradosFiltro;
                        const chaves = itensFiltrados.map((i) => i.produto);
                        onToggleAll(chaves, checkAll);
                      }
                    }}
                  />
                </label>
              </th>
              <th className="col-nome">Produto</th>
              <th className="col-num">Receita</th>
              <th className="col-pct">% Rec.</th>
              <th className="col-pct-acum">% Acum.</th>
              <th className="col-grupo">Grupo</th>
            </tr>
          </thead>
          <tbody>
            {itensFiltrados.length === 0 && (
              <tr>
                <td colSpan={6} className="analisador-tabela-vazia">Nenhum produto neste filtro.</td>
              </tr>
            )}
            {itensFiltrados.map((item) => {
              const considerado = !excluidos.has(item.produto);
              const regra = considerado ? item.fora_por_regra : null;
              return (
                <tr
                  key={item.produto}
                  className={
                    !considerado ? 'is-excluido' : regra ? 'is-fora-regra' : undefined
                  }
                >
                  <td className="col-check">
                    <label className="analisador-check">
                      <input
                        type="checkbox"
                        checked={considerado}
                        onChange={() => onToggle(item.produto)}
                      />
                    </label>
                  </td>
                  <td className="col-nome" title={item.produto}>
                    {item.produto}
                    {regra && (
                      <span className="analisador-marca-regra">
                        {regra === 'demais' ? 'abaixo do corte' : 'não harmonizado'}
                      </span>
                    )}
                  </td>
                  <td className="col-num">{formatCurrency(item.receita)}</td>
                  <td className="col-pct">{formatarPct(item.percentual_receita)}</td>
                  <td className="col-pct-acum">{formatarPct(item.percentual_acumulado)}</td>
                  <td className="col-grupo" title={item.grupo}>{rotuloGrupoCurto(item.grupo)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="analisador-hint">
        {contagem.dentro} de {itensFiltrados.length} produto(s) nos relatórios
        {contagem.demais > 0 && ` · ${contagem.demais} abaixo do corte`}
        {contagem.naoHarmonizados > 0 && ` · ${contagem.naoHarmonizados} não harmonizado(s)`}
        {contagem.manuais > 0 && ` · ${contagem.manuais} desmarcado(s) à mão`}
        {itensFiltrados.length !== lista.length && ` · catálogo completo: ${lista.length} produto(s)`}
      </p>
    </div>
  );
}
