import opentype from 'opentype.js';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const fontPath = path.join(__dirname, '../Outfit-Regular.ttf');
const buf = fs.readFileSync(fontPath);
const font = opentype.parse(buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength));

const fontSize = 56;
const word = 'Prisma';
const strokePad = 14;
let x = 0;
const letters = [];

for (const char of word) {
  const glyph = font.charToGlyph(char);
  const glyphPath = glyph.getPath(x, 0, fontSize);
  letters.push(glyphPath.toPathData(2));
  x += font.getAdvanceWidth(char, fontSize);
}

let combined = new opentype.Path();
x = 0;
for (const char of word) {
  const glyph = font.charToGlyph(char);
  combined.extend(glyph.getPath(x, 0, fontSize));
  x += font.getAdvanceWidth(char, fontSize);
}

const bb = combined.getBoundingBox();
const width = Math.ceil(bb.x2 - bb.x1 + strokePad * 2);
const height = Math.ceil(bb.y2 - bb.y1 + strokePad * 2);
const tx = strokePad - bb.x1;
const ty = strokePad - bb.y1;

const out = `/** Gerado por scripts/gen-prisma-path.mjs — não editar à mão. */
export const LOADING_PRISMA_VIEWBOX = '0 0 ${width} ${height}';
export const LOADING_PRISMA_ASPECT = ${width} / ${height};
export const LOADING_PRISMA_GROUP_TRANSFORM = 'translate(${tx.toFixed(2)}, ${ty.toFixed(2)})';
export const LOADING_PRISMA_LETTERS: readonly string[] = ${JSON.stringify(letters, null, 2)};
`;

fs.writeFileSync(path.join(__dirname, '../src/assets/loadingPrismaPath.ts'), out);
process.stdout.write('wrote loadingPrismaPath.ts\n');
