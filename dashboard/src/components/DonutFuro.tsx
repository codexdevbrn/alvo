/** Número no furo do donut, em SVG.

 * Overlay HTML depois do gráfico pintava em cima do tooltip: no Recharts 3 o
 * card vai para um portal, e o `onMouseEnter` do `Pie` não dispara — o 66%
 * atravessava "Saudável" / "Sem giro". Texto SVG vive no canvas, abaixo do
 * HTML do tooltip.
 */
export function DonutFuro({
  valor,
  legenda,
  viewBox,
}: {
  valor: string;
  legenda: string;
  viewBox?: { cx?: number; cy?: number };
}) {
  const cx = viewBox?.cx;
  const cy = viewBox?.cy;
  if (cx == null || cy == null) return null;
  return (
    <text x={cx} y={cy} textAnchor="middle" pointerEvents="none">
      <tspan x={cx} dy="-0.35em" className="donut-furo-valor">{valor}</tspan>
      <tspan x={cx} dy="1.45em" className="donut-furo-legenda">{legenda}</tspan>
    </text>
  );
}
