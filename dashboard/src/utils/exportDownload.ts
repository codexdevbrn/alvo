/** Helpers de download no cliente (CSV / XLSX / PNG a partir de SVG). */

import * as XLSX from 'xlsx';

function dispararDownload(blob: Blob, nomeArquivo: string) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = nomeArquivo;
  link.click();
  URL.revokeObjectURL(url);
}

function escaparCsv(valor: unknown): string {
  if (valor === null || valor === undefined) return '';
  const s = String(valor);
  if (/[";\n\r]/.test(s)) return `"${s.replace(/"/g, '""')}"`;
  return s;
}

function celulaParaPlanilha(valor: unknown): string | number | boolean {
  if (valor === null || valor === undefined) return '';
  if (typeof valor === 'number' || typeof valor === 'boolean') return valor;
  if (typeof valor === 'bigint') return Number(valor);
  return String(valor);
}

/** CSV com BOM e separador `;` (abre bem no Excel pt-BR). */
export function baixarCsv(
  colunas: string[],
  linhas: unknown[][],
  nomeArquivo: string,
) {
  const sep = ';';
  const corpo = [
    colunas.map(escaparCsv).join(sep),
    ...linhas.map((linha) => linha.map(escaparCsv).join(sep)),
  ].join('\r\n');
  const blob = new Blob([`\uFEFF${corpo}`], { type: 'text/csv;charset=utf-8' });
  dispararDownload(blob, nomeArquivo.endsWith('.csv') ? nomeArquivo : `${nomeArquivo}.csv`);
}

/** XLSX real (SheetJS) com cabeçalhos e linhas da tabela visível. */
export function baixarXlsx(
  colunas: string[],
  linhas: unknown[][],
  nomeArquivo: string,
  nomeAba = 'Tabela',
) {
  const dados: (string | number | boolean)[][] = [
    colunas,
    ...linhas.map((linha) => colunas.map((_, i) => celulaParaPlanilha(linha[i]))),
  ];
  const sheet = XLSX.utils.aoa_to_sheet(dados);
  sheet['!cols'] = colunas.map((c, i) => {
    const maxLen = Math.max(
      c.length,
      ...linhas.slice(0, 200).map((linha) => String(linha[i] ?? '').length),
    );
    return { wch: Math.min(Math.max(maxLen + 2, 10), 48) };
  });
  const wb = XLSX.utils.book_new();
  XLSX.utils.book_append_sheet(wb, sheet, nomeAba.slice(0, 31) || 'Tabela');
  const buf = XLSX.write(wb, { bookType: 'xlsx', type: 'array' }) as number[];
  const blob = new Blob([new Uint8Array(buf)], {
    type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  });
  dispararDownload(blob, nomeArquivo.endsWith('.xlsx') ? nomeArquivo : `${nomeArquivo}.xlsx`);
}

/**
 * Rasteriza o primeiro SVG dentro do container para PNG.
 * Inclui fundo escuro para combinar com o tema do Analisador.
 */
export function baixarSvgComoPng(
  container: HTMLElement,
  nomeArquivo: string,
  fundo = '#0f172a',
): Promise<void> {
  const svg = container.querySelector('svg');
  if (!svg) {
    return Promise.reject(new Error('Nenhum gráfico SVG encontrado para exportar.'));
  }

  const clone = svg.cloneNode(true) as SVGSVGElement;
  const bbox = svg.getBoundingClientRect();
  const width = Math.max(Math.ceil(bbox.width), Number(svg.getAttribute('width')) || 800);
  const height = Math.max(Math.ceil(bbox.height), Number(svg.getAttribute('height')) || 360);

  clone.setAttribute('xmlns', 'http://www.w3.org/2000/svg');
  clone.setAttribute('width', String(width));
  clone.setAttribute('height', String(height));
  if (!clone.getAttribute('viewBox')) {
    clone.setAttribute('viewBox', `0 0 ${width} ${height}`);
  }

  const bg = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
  bg.setAttribute('width', '100%');
  bg.setAttribute('height', '100%');
  bg.setAttribute('fill', fundo);
  clone.insertBefore(bg, clone.firstChild);

  const xml = new XMLSerializer().serializeToString(clone);
  const svgBlob = new Blob([xml], { type: 'image/svg+xml;charset=utf-8' });
  const url = URL.createObjectURL(svgBlob);

  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => {
      try {
        const canvas = document.createElement('canvas');
        const scale = Math.min(2, window.devicePixelRatio || 1);
        canvas.width = Math.round(width * scale);
        canvas.height = Math.round(height * scale);
        const ctx = canvas.getContext('2d');
        if (!ctx) {
          URL.revokeObjectURL(url);
          reject(new Error('Canvas indisponível.'));
          return;
        }
        ctx.scale(scale, scale);
        ctx.fillStyle = fundo;
        ctx.fillRect(0, 0, width, height);
        ctx.drawImage(img, 0, 0, width, height);
        URL.revokeObjectURL(url);
        canvas.toBlob((blob) => {
          if (!blob) {
            reject(new Error('Falha ao gerar PNG.'));
            return;
          }
          dispararDownload(blob, nomeArquivo.endsWith('.png') ? nomeArquivo : `${nomeArquivo}.png`);
          resolve();
        }, 'image/png');
      } catch (err) {
        URL.revokeObjectURL(url);
        reject(err instanceof Error ? err : new Error('Falha ao exportar PNG.'));
      }
    };
    img.onerror = () => {
      URL.revokeObjectURL(url);
      reject(new Error('Falha ao carregar SVG para PNG.'));
    };
    img.src = url;
  });
}
