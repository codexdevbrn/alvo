import { Cell, Pie, PieChart, ResponsiveContainer } from 'recharts';

/** Velocímetro (meio-donut) da métrica "% receita não harmonizada". Três faixas
 *  porque o número sozinho não diz se 22% é bom ou ruim — a cor e o selo dizem. */
const FAIXAS = [
  { ate: 15, rotulo: 'Bom', cor: 'var(--success)' },
  { ate: 35, rotulo: 'Atenção', cor: 'var(--warning)' },
  { ate: Infinity, rotulo: 'Crítico', cor: 'var(--danger)' },
];

function faixaPara(valor: number) {
  return FAIXAS.find((faixa) => valor <= faixa.ate) ?? FAIXAS[FAIXAS.length - 1];
}

export function GaugeMonitor({ valor }: { valor: number }) {
  const pct = Math.max(0, Math.min(100, valor));
  const faixa = faixaPara(pct);
  const dados = [
    { nome: 'valor', v: pct, cor: faixa.cor },
    { nome: 'resto', v: 100 - pct, cor: 'var(--surface-3)' },
  ];

  return (
    <div className="monitor-gauge">
      <ResponsiveContainer width="100%" height="100%">
        <PieChart margin={{ top: 0, right: 0, bottom: 0, left: 0 }}>
          <Pie
            key={pct.toFixed(1)}
            data={dados}
            dataKey="v"
            nameKey="nome"
            cx="50%"
            cy={90}
            startAngle={180}
            endAngle={0}
            innerRadius={50}
            outerRadius={76}
            cornerRadius={5}
            stroke="none"
            isAnimationActive
            animationBegin={0}
            animationDuration={800}
            animationEasing="ease-out"
          >
            {dados.map((fatia) => (
              <Cell key={fatia.nome} fill={fatia.cor} />
            ))}
          </Pie>
        </PieChart>
      </ResponsiveContainer>

      <span className="monitor-gauge-marca monitor-gauge-marca-min">0%</span>
      <span className="monitor-gauge-marca monitor-gauge-marca-max">100%</span>

      <div className="monitor-gauge-leitura">
        <strong style={{ color: faixa.cor }}>{pct.toFixed(1)}%</strong>
        <span className="monitor-gauge-selo" style={{ color: faixa.cor, borderColor: faixa.cor }}>
          {faixa.rotulo}
        </span>
      </div>
    </div>
  );
}
