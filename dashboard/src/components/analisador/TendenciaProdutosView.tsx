import { useMemo, useState } from 'react';
import { Area, CartesianGrid, ComposedChart, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import type { TabelaResultado } from '../../api/client';
import { formatCurrency, formatNumber, formatPercent } from '../../utils/formatters';
import { ResultTable } from './ResultTable';

interface TendenciaProdutosViewProps {
  tabela: TabelaResultado;
}

interface PontoTendencia {
  periodo: string;
  receita: number;
  quantidade: number;
  variacao: number | null;
  receitaAnterior: number | null;
}

type OrdenacaoProdutos =
  | 'tendencia_desc'
  | 'tendencia_asc'
  | 'receita_desc'
  | 'receita_asc'
  | 'quantidade_desc'
  | 'quantidade_asc'
  | 'nome_asc'
  | 'nome_desc';

interface ResumoProduto {
  nome: string;
  tendencia: number;
  receitaAtual: number;
  quantidadeAtual: number;
}

const comparadorNomes = new Intl.Collator('pt-BR', { sensitivity: 'base', numeric: true });

const moedaCompacta = new Intl.NumberFormat('pt-BR', {
  style: 'currency',
  currency: 'BRL',
  notation: 'compact',
  maximumFractionDigits: 1,
});

function numero(valor: unknown): number {
  return typeof valor === 'number' && Number.isFinite(valor) ? valor : 0;
}

function numeroOuNull(valor: unknown): number | null {
  return typeof valor === 'number' && Number.isFinite(valor) ? valor : null;
}

function TooltipTendencia({
  active,
  payload,
  label,
}: {
  active?: boolean;
  payload?: Array<{ dataKey?: string; value?: number | string }>;
  label?: string;
}) {
  if (!active || !payload?.length) return null;
  const receita = payload.find((item) => item.dataKey === 'receita')?.value;
  const quantidade = payload.find((item) => item.dataKey === 'quantidade')?.value;
  return (
    <div className="tendencia-produtos-tooltip">
      <strong>{label}</strong>
      <span>Receita: {formatCurrency(Number(receita) || 0)}</span>
      <span>Quantidade: {formatNumber(Number(quantidade) || 0)}</span>
    </div>
  );
}

function tom(valor: number | null): string {
  if (valor == null || valor === 0) return 'is-neutro';
  return valor > 0 ? 'is-positivo' : 'is-negativo';
}

export function TendenciaProdutosView({ tabela }: TendenciaProdutosViewProps) {
  const indice = useMemo(
    () => new Map(tabela.colunas.map((coluna, posicao) => [coluna, posicao])),
    [tabela.colunas],
  );
  const indiceProduto = indice.get('descricao') ?? -1;
  const [ordenacao, setOrdenacao] = useState<OrdenacaoProdutos>('tendencia_desc');
  const [produtoEscolhido, setProdutoEscolhido] = useState('');

  // Resume cada produto uma única vez para permitir reordenar o seletor sem
  // recalcular ou alterar a sequência cronológica usada pelo gráfico.
  const resumosProdutos = useMemo<ResumoProduto[]>(() => {
    if (indiceProduto < 0) return [];
    const posReceita = indice.get('Receita') ?? -1;
    const posQuantidade = indice.get('QTD') ?? -1;
    const posTendencia = indice.get('Tendencia_Pct') ?? -1;
    const linhasPorProduto = new Map<string, Array<TabelaResultado['linhas'][number]>>();

    tabela.linhas.forEach((linha) => {
      const nome = String(linha[indiceProduto] ?? '');
      if (!nome) return;
      const linhas = linhasPorProduto.get(nome) ?? [];
      linhas.push(linha);
      linhasPorProduto.set(nome, linhas);
    });

    return Array.from(linhasPorProduto, ([nome, linhas]) => {
      const ultimaLinha = linhas[linhas.length - 1];
      return {
        nome,
        tendencia: numero(linhas[0]?.[posTendencia]),
        receitaAtual: numero(ultimaLinha?.[posReceita]),
        quantidadeAtual: numero(ultimaLinha?.[posQuantidade]),
      };
    });
  }, [indice, indiceProduto, tabela.linhas]);

  const produtos = useMemo(() => {
    const ordenados = [...resumosProdutos];
    ordenados.sort((a, b) => {
      let diferenca = 0;
      if (ordenacao === 'tendencia_desc') diferenca = b.tendencia - a.tendencia;
      if (ordenacao === 'tendencia_asc') diferenca = a.tendencia - b.tendencia;
      if (ordenacao === 'receita_desc') diferenca = b.receitaAtual - a.receitaAtual;
      if (ordenacao === 'receita_asc') diferenca = a.receitaAtual - b.receitaAtual;
      if (ordenacao === 'quantidade_desc') diferenca = b.quantidadeAtual - a.quantidadeAtual;
      if (ordenacao === 'quantidade_asc') diferenca = a.quantidadeAtual - b.quantidadeAtual;
      if (ordenacao === 'nome_desc') return comparadorNomes.compare(b.nome, a.nome);
      if (ordenacao === 'nome_asc') return comparadorNomes.compare(a.nome, b.nome);
      return diferenca || comparadorNomes.compare(a.nome, b.nome);
    });
    return ordenados.map((produto) => produto.nome);
  }, [ordenacao, resumosProdutos]);
  const produtoAtual = produtos.includes(produtoEscolhido) ? produtoEscolhido : produtos[0] ?? '';

  const linhasProduto = useMemo(
    () => tabela.linhas.filter((linha) => String(linha[indiceProduto] ?? '') === produtoAtual),
    [indiceProduto, produtoAtual, tabela.linhas],
  );

  const pontos = useMemo<PontoTendencia[]>(() => {
    const posPeriodo = indice.get('Periodo') ?? -1;
    const posReceita = indice.get('Receita') ?? -1;
    const posQuantidade = indice.get('QTD') ?? -1;
    const posVariacao = indice.get('Variacao_Percentual') ?? -1;
    const posAnterior = indice.get('Receita_Periodo_Anterior') ?? -1;
    return linhasProduto.map((linha) => ({
      periodo: String(linha[posPeriodo] ?? '—'),
      receita: numero(linha[posReceita]),
      quantidade: numero(linha[posQuantidade]),
      variacao: numeroOuNull(linha[posVariacao]),
      receitaAnterior: numeroOuNull(linha[posAnterior]),
    }));
  }, [indice, linhasProduto]);

  if (!produtoAtual || pontos.length === 0) {
    return <p className="analisador-hint">Sem dados de tendência para exibir.</p>;
  }

  const ultimo = pontos[pontos.length - 1];
  const posTendencia = indice.get('Tendencia_Pct') ?? -1;
  const tendencia = numeroOuNull(linhasProduto[0]?.[posTendencia]);
  const colunasDetalhe = tabela.colunas.filter(
    (coluna) => coluna !== 'descricao' && coluna !== 'Tendencia_Pct',
  );
  const posicoesDetalhe = colunasDetalhe.map((coluna) => tabela.colunas.indexOf(coluna));
  const tabelaDetalhe: TabelaResultado = {
    colunas: colunasDetalhe,
    linhas: linhasProduto.map((linha) => posicoesDetalhe.map((posicao) => linha[posicao])),
  };

  return (
    <div className="tendencia-produtos">
      <div className="tendencia-produtos-cabecalho">
        <div>
          <h3>Evolução por produto</h3>
          <p>Receita e quantidade ao longo dos períodos analisados.</p>
        </div>
        <div className="tendencia-produtos-controles">
          <label className="analisador-campo tendencia-produtos-classificacao">
            <span>Classificar por</span>
            <select
              className="custom-select analisador-select"
              value={ordenacao}
              onChange={(evento) => setOrdenacao(evento.target.value as OrdenacaoProdutos)}
            >
              <option value="tendencia_desc">Tendência: maior → menor</option>
              <option value="tendencia_asc">Tendência: menor → maior</option>
              <option value="receita_desc">Receita atual: maior → menor</option>
              <option value="receita_asc">Receita atual: menor → maior</option>
              <option value="quantidade_desc">Quantidade atual: maior → menor</option>
              <option value="quantidade_asc">Quantidade atual: menor → maior</option>
              <option value="nome_asc">Nome: A → Z</option>
              <option value="nome_desc">Nome: Z → A</option>
            </select>
          </label>
          <label className="analisador-campo tendencia-produtos-seletor">
            <span>Produto exibido</span>
            <select
              className="custom-select analisador-select"
              value={produtoAtual}
              onChange={(evento) => setProdutoEscolhido(evento.target.value)}
            >
              {produtos.map((produto) => <option key={produto} value={produto}>{produto}</option>)}
            </select>
          </label>
        </div>
      </div>

      <div className="tendencia-produtos-kpis">
        <div className="tendencia-produtos-kpi">
          <span>Receita atual</span>
          <strong>{formatCurrency(ultimo.receita)}</strong>
          <small>{ultimo.periodo}</small>
        </div>
        <div className="tendencia-produtos-kpi">
          <span>Quantidade atual</span>
          <strong>{formatNumber(ultimo.quantidade)}</strong>
          <small>{ultimo.periodo}</small>
        </div>
        <div className={`tendencia-produtos-kpi ${tom(ultimo.variacao)}`}>
          <span>Variação no período</span>
          <strong>{ultimo.variacao == null ? '—' : formatPercent(ultimo.variacao)}</strong>
          <small>versus período anterior</small>
        </div>
        <div className={`tendencia-produtos-kpi ${tom(tendencia)}`}>
          <span>Tendência geral</span>
          <strong>{tendencia == null ? '—' : formatPercent(tendencia)}</strong>
          <small>primeira janela × última</small>
        </div>
      </div>

      <div className="tendencia-produtos-grafico" role="img" aria-label={`Evolução de receita e quantidade de ${produtoAtual}`}>
        <ResponsiveContainer width="100%" height={320}>
          <ComposedChart data={pontos} margin={{ top: 16, right: 8, bottom: 4, left: 4 }} accessibilityLayer>
            <defs>
              <linearGradient id="tendenciaReceita" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#dabb6c" stopOpacity={0.38} />
                <stop offset="100%" stopColor="#dabb6c" stopOpacity={0.02} />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="rgba(255,255,255,0.08)" />
            <XAxis dataKey="periodo" tick={{ fill: '#a6a6ad', fontSize: 11 }} axisLine={false} tickLine={false} />
            <YAxis
              yAxisId="receita"
              tickFormatter={(valor) => moedaCompacta.format(Number(valor))}
              tick={{ fill: '#a6a6ad', fontSize: 10 }}
              axisLine={false}
              tickLine={false}
              width={70}
            />
            <YAxis
              yAxisId="quantidade"
              orientation="right"
              tickFormatter={(valor) => formatNumber(Number(valor))}
              tick={{ fill: '#a6a6ad', fontSize: 10 }}
              axisLine={false}
              tickLine={false}
              width={52}
            />
            <Tooltip content={<TooltipTendencia />} cursor={{ stroke: 'rgba(218,187,108,0.35)' }} />
            <Area
              yAxisId="receita"
              type="monotone"
              dataKey="receita"
              name="Receita"
              stroke="#dabb6c"
              strokeWidth={2.5}
              fill="url(#tendenciaReceita)"
              dot={{ r: 3, fill: '#dabb6c', strokeWidth: 0 }}
              activeDot={{ r: 5 }}
            />
            <Line
              yAxisId="quantidade"
              type="monotone"
              dataKey="quantidade"
              name="Quantidade"
              stroke="#60a5fa"
              strokeWidth={2}
              dot={{ r: 3, fill: '#60a5fa', strokeWidth: 0 }}
              activeDot={{ r: 5 }}
            />
          </ComposedChart>
        </ResponsiveContainer>
        <div className="tendencia-produtos-legenda" aria-hidden="true">
          <span><i className="is-receita" /> Receita</span>
          <span><i className="is-quantidade" /> Quantidade</span>
        </div>
      </div>

      <details className="tendencia-produtos-detalhes">
        <summary>Ver dados por período ({pontos.length})</summary>
        <ResultTable tabela={tabelaDetalhe} chave="evolucao_produtos" />
      </details>
    </div>
  );
}
