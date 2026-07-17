import { useMemo, useState } from 'react';
import type { ItemProdutoPrevia } from '../../api/client';
import { formatCurrency, rotuloGrupoCurto } from '../../utils/formatters';

interface PreviaProdutosTableProps {
  itens: ItemProdutoPrevia[];
  excluidos: Set<string>;
  onToggle: (produto: string) => void;
  carregando?: boolean;
}

function formatarPct(valor: number | null): string {
  if (valor == null || Number.isNaN(valor)) return '—';
  return `${valor.toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}%`;
}

export function PreviaProdutosTable({ itens, excluidos, onToggle, carregando }: PreviaProdutosTableProps) {
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
  const incluidosNoFiltro = useMemo(
    () => itensFiltrados.filter((item) => !excluidos.has(item.produto)).length,
    [itensFiltrados, excluidos],
  );

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
              <th className="col-check">Incluir?</th>
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
              return (
                <tr key={item.produto} className={considerado ? undefined : 'is-excluido'}>
                  <td className="col-check">
                    <label className="analisador-check">
                      <input
                        type="checkbox"
                        checked={considerado}
                        onChange={() => onToggle(item.produto)}
                      />
                    </label>
                  </td>
                  <td className="col-nome" title={item.produto}>{item.produto}</td>
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
        {incluidosNoFiltro} de {itensFiltrados.length} produto(s) incluído(s) na análise
        {itensFiltrados.length !== lista.length && ` · catálogo completo: ${lista.length} produto(s)`}
        {excluidos.size > 0 && ` · ${excluidos.size} fora da análise no catálogo completo`}
      </p>
    </div>
  );
}
