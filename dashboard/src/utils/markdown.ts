/** Tira o frontmatter YAML do topo (a análise diária começa com ele). */
export function semFrontmatter(markdown: string): string {
  return markdown.replace(/^---\r?\n[\s\S]*?\r?\n---\r?\n?/, '');
}
