import type { GpsPar, RecomendacaoGps } from '../../api/client';

/** Rótulos e formatos do GPS na tela A precificar (fora do .tsx por causa do fast refresh). */

export const RECOMENDACOES_GPS: Record<RecomendacaoGps, { rotulo: string; direcao: 'subir' | 'descer' | 'manter'; ajuda: string }> = {
  reajustar: { rotulo: 'Reajustar', direcao: 'subir', ajuda: 'GPS sobe e o A precificar tem prova (ou o custo subiu sem repasse).' },
  etapas: { rotulo: 'Subir em etapas', direcao: 'subir', ajuda: 'GPS sobe, mas a quantidade por dia caiu 15% ou mais: metade do ajuste agora.' },
  oportunidade: { rotulo: 'Oportunidade', direcao: 'subir', ajuda: 'Só o GPS vê espaço para subir; o A precificar não sinalizou.' },
  divergencia: { rotulo: 'Divergência', direcao: 'descer', ajuda: 'O A precificar quer subir e o GPS quer descer: revisar antes de mexer.' },
  reduzir: { rotulo: 'Reduzir', direcao: 'descer', ajuda: 'GPS desce e a quantidade por dia caiu 15% ou mais.' },
  segurar: { rotulo: 'Segurar preço', direcao: 'descer', ajuda: 'GPS desce, mas o custo subiu 2 pp acima do preço: manter a margem, repassando só o custo.' },
  manter: { rotulo: 'Manter', direcao: 'manter', ajuda: 'Já na posição certa da faixa, ou GPS desce sem outro sinal.' },
};

/** Pontos percentuais com duas casas e sinal: "+1,05", "−5,90". */
export function pp(valor: number | null | undefined, comSinal = true): string {
  if (valor == null || !Number.isFinite(valor)) return '—';
  const abs = Math.abs(valor).toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  if (!comSinal || valor === 0) return valor < 0 ? `−${abs}` : abs;
  return `${valor > 0 ? '+' : '−'}${abs}`;
}

export function faixaTexto(faixa: GpsPar['faixa']): string {
  const [minimo, maximo] = faixa;
  if (minimo == null) return `até ${pp(maximo)}`;
  return `${pp(minimo)} a ${pp(maximo)}`;
}

