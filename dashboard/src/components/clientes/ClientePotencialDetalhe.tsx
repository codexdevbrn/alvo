import { useEffect, useState } from 'react';
import { AlertTriangle, Loader2 } from 'lucide-react';
import {
  obterPotencialProdutosCliente,
  type PotencialProdutosClienteResposta,
} from '../../api/client';
import { formatCurrency, formatNumber, formatPercent } from '../../utils/formatters';
import type { ModoPeriodo } from '../../utils/mesesFechados';

interface Props {
  empresa: string;
  cliente: string;
  loja?: string | null;
  modoPeriodo: ModoPeriodo;
  grupos?: string;
}

/** Card que abre logo abaixo da linha clicada em "Maiores potenciais de
 *  compra" — os produtos que mais venderam pro cliente nos meses que
 *  formaram o potencial dele (mesmos 3 meses de maior receita). Inline na
 *  própria lista, não um modal: o cliente pediu explicitamente pra não
 *  interromper o fluxo com uma camada por cima da tela. */
export function ClientePotencialDetalhe({ empresa, cliente, loja = null, modoPeriodo, grupos }: Props) {
  const [dados, setDados] = useState<PotencialProdutosClienteResposta | null>(null);
  const [carregando, setCarregando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);

  useEffect(() => {
    let vivo = true;
    setCarregando(true);
    setErro(null);
    setDados(null);
    void obterPotencialProdutosCliente(empresa, cliente, loja, modoPeriodo, grupos)
      .then((resposta) => {
        if (vivo) setDados(resposta);
      })
      .catch((falha) => {
        if (!vivo) return;
        setErro(falha instanceof Error ? falha.message : 'Falha ao carregar os produtos do cliente.');
      })
      .finally(() => {
        if (vivo) setCarregando(false);
      });
    return () => {
      vivo = false;
    };
  }, [empresa, cliente, loja, modoPeriodo, grupos]);

  const nota = dados?.disponivel
    ? `Meses de maior receita: ${dados.meses.join(', ')}. Potencial (média dos 3): ${formatCurrency(dados.potencial)}.`
    : null;

  return (
    <li className="clientes-potencial-detalhe">
      <div className="clientes-potencial-detalhe-topo">
        <h3 title={cliente}>{cliente}</h3>
        {!carregando && !erro && nota && dados?.disponivel && (
          <p className="clientes-potencial-detalhe-nota" title={nota}>
            Meses de maior receita: <strong>{dados.meses.join(', ')}</strong>.{' '}
            Potencial (média dos 3): <strong>{formatCurrency(dados.potencial)}</strong>.
          </p>
        )}
      </div>

      {carregando && (
        <p className="analisador-hint"><Loader2 size={14} className="dashboard-filter-spinner" /> Carregando produtos…</p>
      )}

      {!carregando && erro && (
        <div className="glass-card glass-card-flat analisador-erro" role="alert">
          <AlertTriangle size={17} /> {erro}
        </div>
      )}

      {!carregando && !erro && dados && !dados.disponivel && (
        <p className="analisador-hint">Histórico insuficiente para calcular o potencial deste cliente.</p>
      )}

      {!carregando && !erro && dados?.disponivel && (
        <>
          {dados.produtos.length === 0 ? (
            <p className="analisador-hint">Sem produto identificado nesses meses.</p>
          ) : (
            <ul className="clientes-potencial-detalhe-produtos">
              {dados.produtos.map((produto, indice) => (
                <li key={produto.descricao}>
                  <p className="clientes-potencial-detalhe-produto-topo">
                    <span className="clientes-ranking-numero">{indice + 1}</span>
                    <strong title={produto.descricao}>{produto.descricao}</strong>
                  </p>
                  <span className="clientes-ranking-valor">{formatCurrency(produto.receita)}</span>
                  <span className="clientes-potencial-detalhe-produto-nota">
                    {formatNumber(produto.qtd)} un. · {formatPercent(produto.participacao, 1)} do período
                  </span>
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </li>
  );
}
