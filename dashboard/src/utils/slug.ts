/** Slug estável para ids de grupo (acentos → ASCII, não-alfanum → `_`). */
export function slugId(rotulo: string): string {
  return (
    rotulo
      .normalize('NFD')
      .replace(/[\u0300-\u036f]/g, '')
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, '_')
      .replace(/^_|_$/g, '')
      .slice(0, 48) || 'grupo'
  );
}
