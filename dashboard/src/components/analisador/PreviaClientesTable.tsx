import { useMemo, useState } from 'react';
import type { ItemClientePrevia } from '../../api/client';

interface PreviaClientesTableProps {
  itens: ItemClientePrevia[];
  excluidos: Set<string>;
  onToggle: (cliente: string) => void;
  carregando?: boolean;
}

function formatarMoeda(valor: number): string {
  return valor.toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' });
}

function formatarPct(valor: number | null): string {
  if (valor == null || Number.isNaN(valor)) return '—';
  return `${valor.toFixed(2)}%`;
}

export function PreviaClientesTable({ itens, excluidos, onToggle, carregando }: PreviaClientesTableProps) {
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
      if (termo && !item.cliente.toLowerCase().includes(termo)) return false;
      return true;
    });
  }, [lista, busca, grupoFiltro]);

  // A tabela sempre mostra a base completa de clientes (para permitir
  // marcar/desmarcar qualquer um), então a contagem "de Y clientes" nunca
  // muda com exclusões. O que varia é quantos desses itens estão de fato
  // considerados nas métricas.
  const consideradosNoFiltro = useMemo(
    () => itensFiltrados.filter((item) => !excluidos.has(item.cliente)).length,
    [itensFiltrados, excluidos],
  );

  if (carregando) {
    return <p className="analisador-hint">Calculando prévia dos grupos...</p>;
  }

  if (lista.length === 0) {
    return (
      <p className="analisador-hint">
        Clique em &quot;Atualizar prévia dos grupos&quot; para ver os clientes por faixa.
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
            placeholder="Nome do cliente..."
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
              <option key={grupo} value={grupo}>{grupo}</option>
            ))}
          </select>
        </label>
      </div>

      <div className="analisador-tabela-wrap custom-scrollbar">
        <table className="analisador-tabela">
          <thead>
            <tr>
              <th className="col-check">Incluir?</th>
              <th className="col-nome">Cliente</th>
              <th className="col-num">Receita</th>
              <th className="col-pct">% Receita</th>
              <th className="col-pct-acum">% Acumulada</th>
              <th className="col-grupo">Grupo</th>
            </tr>
          </thead>
          <tbody>
            {itensFiltrados.length === 0 && (
              <tr>
                <td colSpan={6} className="analisador-tabela-vazia">Nenhum cliente neste filtro.</td>
              </tr>
            )}
            {itensFiltrados.map((item) => {
              const excluido = excluidos.has(item.cliente);
              return (
                <tr key={item.cliente} className={excluido ? 'is-excluido' : undefined}>
                  <td className="col-check">
                    <label className="analisador-check">
                      <input
                        type="checkbox"
                        checked={!excluido}
                        onChange={() => onToggle(item.cliente)}
                      />
                    </label>
                  </td>
                  <td className="col-nome" title={item.cliente}>{item.cliente}</td>
                  <td className="col-num">{formatarMoeda(item.receita)}</td>
                  <td className="col-pct">{formatarPct(item.percentual_receita)}</td>
                  <td className="col-pct-acum">{formatarPct(item.percentual_acumulado)}</td>
                  <td className="col-grupo">{item.grupo}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="analisador-hint">
        {consideradosNoFiltro} de {itensFiltrados.length} cliente(s) considerado(s) nas métricas
        {itensFiltrados.length !== lista.length && ` · base completa: ${lista.length} cliente(s)`}
        {excluidos.size > 0 && ` · ${excluidos.size} excluído(s) das métricas no total`}
      </p>
    </div>
  );
}
