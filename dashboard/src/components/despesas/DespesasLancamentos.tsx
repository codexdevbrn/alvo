import { useEffect, useMemo, useState } from 'react';
import { AlertTriangle, Loader2, Search } from 'lucide-react';
import {
  obterDetalheDespesas,
  obterResumoDespesas,
  type DetalheDespesasResposta,
  type ResumoDespesasResposta,
} from '../../api/client';
import { formatCurrency, formatPercent } from '../../utils/formatters';

type Props = {
  empresa: string;
  loja: string | null;
};

const TODAS = '';

function normalizar(texto: string): string {
  return texto.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase();
}

/** Aba Lançamentos: tabela filtrável por mês e categoria, ordenada do maior
 *  para o menor valor. Os selects usam o resumo (janela ampla) só para montar
 *  as opções — o filtro em si roda no backend; a busca por texto é local, sobre
 *  a página já carregada, para não disparar uma ida ao servidor por tecla. */
export function DespesasLancamentos({ empresa, loja }: Props) {
  const [resumo, setResumo] = useState<ResumoDespesasResposta | null>(null);
  const [periodo, setPeriodo] = useState(TODAS);
  const [categoria, setCategoria] = useState(TODAS);
  const [busca, setBusca] = useState('');
  const [detalhe, setDetalhe] = useState<DetalheDespesasResposta | null>(null);
  const [carregando, setCarregando] = useState(true);
  const [erro, setErro] = useState<string | null>(null);

  useEffect(() => {
    setPeriodo(TODAS);
    setCategoria(TODAS);
    setBusca('');
    let vivo = true;
    void obterResumoDespesas(empresa, { loja, meses: 36, usarMesesFechados: false })
      .then((resposta) => {
        if (vivo) setResumo(resposta);
      })
      .catch(() => {
        if (vivo) setResumo(null);
      });
    return () => {
      vivo = false;
    };
  }, [empresa, loja]);

  useEffect(() => {
    let vivo = true;
    setCarregando(true);
    setErro(null);
    void obterDetalheDespesas(empresa, { loja, periodo: periodo || null, categoria: categoria || null })
      .then((resposta) => {
        if (vivo) setDetalhe(resposta);
      })
      .catch((falha) => {
        if (!vivo) return;
        setDetalhe(null);
        setErro(falha instanceof Error ? falha.message : 'Falha ao carregar os lançamentos.');
      })
      .finally(() => {
        if (vivo) setCarregando(false);
      });
    return () => {
      vivo = false;
    };
  }, [empresa, loja, periodo, categoria]);

  const itens = useMemo(() => {
    const todos = detalhe?.itens ?? [];
    const alvo = normalizar(busca.trim());
    if (!alvo) return todos;
    return todos.filter((item) => normalizar(`${item.loja} ${item.categoria}`).includes(alvo));
  }, [detalhe, busca]);

  const total = useMemo(() => itens.reduce((soma, item) => soma + item.valor, 0), [itens]);
  const maior = itens.reduce((maximo, item) => Math.max(maximo, item.valor), 0);

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
      <div className="despesas-lancamentos-barra">
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
          <label className="analisador-campo">
            <span>Buscar</span>
            <span className="despesas-busca">
              <Search size={14} aria-hidden="true" />
              <input
                type="search"
                value={busca}
                onChange={(e) => setBusca(e.target.value)}
                placeholder="Loja ou categoria"
              />
            </span>
          </label>
        </div>

        <div className="despesas-lancamentos-total">
          <span>{itens.length} {itens.length === 1 ? 'lançamento' : 'lançamentos'}</span>
          <strong>{formatCurrency(total)}</strong>
        </div>
      </div>

      <div className="analisador-tabela-wrap despesas-tabela-wrap">
        <table className="analisador-tabela despesas-tabela">
          <thead>
            <tr>
              <th>Loja</th>
              <th>Categoria</th>
              <th>Mês</th>
              <th className="despesas-col-valor">Valor</th>
              <th className="despesas-col-peso">Peso</th>
            </tr>
          </thead>
          <tbody>
            {carregando && !detalhe && (
              <tr><td colSpan={5} className="analisador-tabela-vazia"><Loader2 size={16} className="dashboard-filter-spinner" /> Carregando lançamentos…</td></tr>
            )}
            {detalhe && itens.length === 0 && (
              <tr><td colSpan={5} className="analisador-tabela-vazia">Nenhum lançamento nesta seleção.</td></tr>
            )}
            {itens.map((item, indice) => (
              <tr key={`${item.loja}-${item.categoria}-${item.ano}-${item.mes}-${indice}`}>
                <td>{item.loja}</td>
                <td title={item.categoria}>{item.categoria}</td>
                <td>{String(item.mes).padStart(2, '0')}/{item.ano}</td>
                <td className="despesas-col-valor">{formatCurrency(item.valor)}</td>
                <td className="despesas-col-peso">
                  <span className="despesas-peso">
                    <i aria-hidden="true">
                      <b style={{ width: `${maior > 0 ? (item.valor / maior) * 100 : 0}%` }} />
                    </i>
                    <em>{formatPercent(total > 0 ? (item.valor / total) * 100 : 0, 1)}</em>
                  </span>
                </td>
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
