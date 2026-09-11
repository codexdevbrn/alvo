import { useEffect, useState } from 'react';
import { AlertTriangle, Loader2 } from 'lucide-react';
import {
  obterDetalheDespesas,
  obterResumoDespesas,
  type DetalheDespesasResposta,
  type ResumoDespesasResposta,
} from '../../api/client';
import { formatCurrency } from '../../utils/formatters';

type Props = {
  empresa: string;
  loja: string | null;
};

const TODAS = '';

/** Aba Lançamentos: tabela filtrável por mês e categoria, ordenada do maior
 *  para o menor valor. Os selects usam o resumo (janela ampla) só para montar
 *  as opções — o filtro em si roda no backend. */
export function DespesasLancamentos({ empresa, loja }: Props) {
  const [resumo, setResumo] = useState<ResumoDespesasResposta | null>(null);
  const [periodo, setPeriodo] = useState(TODAS);
  const [categoria, setCategoria] = useState(TODAS);
  const [detalhe, setDetalhe] = useState<DetalheDespesasResposta | null>(null);
  const [carregando, setCarregando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);

  useEffect(() => {
    setPeriodo(TODAS);
    setCategoria(TODAS);
    const controller = new AbortController();
    void obterResumoDespesas(empresa, { loja, meses: 36, usarMesesFechados: false }, controller.signal)
      .then(setResumo)
      .catch(() => setResumo(null));
    return () => controller.abort();
  }, [empresa, loja]);

  useEffect(() => {
    const controller = new AbortController();
    setCarregando(true);
    setErro(null);
    void obterDetalheDespesas(empresa, { loja, periodo: periodo || null, categoria: categoria || null }, controller.signal)
      .then(setDetalhe)
      .catch((falha) => {
        if (falha instanceof DOMException && falha.name === 'AbortError') return;
        setDetalhe(null);
        setErro(falha instanceof Error ? falha.message : 'Falha ao carregar os lançamentos.');
      })
      .finally(() => {
        if (!controller.signal.aborted) setCarregando(false);
      });
    return () => controller.abort();
  }, [empresa, loja, periodo, categoria]);

  if (erro) {
    return (
      <div className="glass-card glass-card-flat estoque-aviso" role="alert">
        <AlertTriangle size={18} /><span>{erro}</span>
      </div>
    );
  }

  const periodos = [...(resumo?.serie_mensal ?? [])].reverse();

  return (
    <div className="estoque-visao">
      <div className="estoque-header-filtros">
        <label className="analisador-campo">
          <span>Mês</span>
          <select className="custom-select analisador-select" value={periodo} onChange={(e) => setPeriodo(e.target.value)}>
            <option value={TODAS}>Todos os meses</option>
            {periodos.map((ponto) => (
              <option key={ponto.periodo} value={ponto.periodo}>{ponto.rotulo}</option>
            ))}
          </select>
        </label>
        <label className="analisador-campo">
          <span>Categoria</span>
          <select className="custom-select analisador-select" value={categoria} onChange={(e) => setCategoria(e.target.value)}>
            <option value={TODAS}>Todas as categorias</option>
            {(resumo?.por_categoria ?? []).map((item) => (
              <option key={item.categoria} value={item.categoria}>{item.categoria}</option>
            ))}
          </select>
        </label>
      </div>

      <div className="analisador-tabela-wrap">
        <table className="analisador-tabela">
          <thead>
            <tr>
              <th>Loja</th>
              <th>Categoria</th>
              <th>Mês</th>
              <th>Valor</th>
            </tr>
          </thead>
          <tbody>
            {carregando && !detalhe && (
              <tr><td colSpan={4} className="analisador-tabela-vazia"><Loader2 size={16} className="dashboard-filter-spinner" /> Carregando lançamentos…</td></tr>
            )}
            {detalhe && detalhe.itens.length === 0 && (
              <tr><td colSpan={4} className="analisador-tabela-vazia">Nenhum lançamento nesta seleção.</td></tr>
            )}
            {detalhe?.itens.map((item, indice) => (
              <tr key={`${item.loja}-${item.categoria}-${item.ano}-${item.mes}-${indice}`}>
                <td>{item.loja}</td>
                <td title={item.categoria}>{item.categoria}</td>
                <td>{String(item.mes).padStart(2, '0')}/{item.ano}</td>
                <td>{formatCurrency(item.valor)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {detalhe?.limitado && (
        <p className="analisador-hint">
          Mostrando os {detalhe.itens.length} maiores lançamentos de {detalhe.total_itens} nesta seleção.
        </p>
      )}
    </div>
  );
}
