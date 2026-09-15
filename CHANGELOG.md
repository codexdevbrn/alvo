# Changelog

Formato: uma seção por versão publicada, mais recente no topo. Histórico é
incremental — entradas antigas nunca são apagadas. O estado atual das telas e
funcionalidades vive em `DOC_TEC.md`, não aqui.

## 1.7.13 — 2026-09-15

### Adicionado

- Tela **Pós precificação**: lê `{empresa}_PRECIFICACAO.csv`, cruza com o
  movimento e mostra o que foi marcado na última rodada e como andou depois
  (lucro/dia, qtd/dia, margem vs alvo). Carrossel dos pares, gráficos mensais
  e lista clicável. Cortes de Relatórios não entram — o dump *é* o recorte.

### Alterado

- Prefetch das telas deixa de ser fila única: prioriza a rota aberta e
  carrega o resto em paralelo (teto de 4).

## 1.7.12 — 2026-09-15

### Adicionado

- Tela **Cortes** na sidebar: configuração de grupos de clientes e produtos
  sai do Relatórios e vira página própria.
- Filtro global de grupos no topo (G1 / G2 / G3 / Demais / Balcão) com
  "Cortes: Com corte" ligado — vale no Dashboard, Clientes, Estoque e
  Vendedores.
- Frase de leitura no topo das telas: o que os números significam, com aviso
  quando o mês está aberto ou a variação parece buraco de dado.

### Alterado

- Despesas ignora mês sem lançamento e competência futura; média e variação
  usam só os meses com valor, sem cauda de zeros até 2027.
- Estoque recorta também os produtos excluídos nos Cortes (antes só
  vendas/CMV sumiam; o item continuava em dinheiro dormindo).
- Toggle "Cortes" passa a refazer as telas já abertas, não só o cache.

### Corrigido

- Dashboard aplica filtro de grupos e exclusão de balcão no summary, iguais
  às outras telas.

## 1.7.11 — 2026-09-15

### Alterado

- Telas de dados mercadológicos deixam de repetir empresa, loja e meses
  fechados — o escopo fica só no topo.
- Dashboard perde o checkbox duplicado de meses fechados na `FilterBar`.

### Corrigido

- Texto ativo do toggle Sintética/Detalhada voltou a contrastar com o ouro.

## 1.7.10 — 2026-09-15

### Alterado

- Meses fechados e cortes de Relatórios sobem para a barra de topo.
- Despesas guarda o período escolhido; venda média vira combobox pesquisável.
- Prefetch de Clientes distingue Visão geral e Base e tags.

## 1.7.9 — 2026-09-15

### Alterado

- Empresa e loja saem da sidebar e vão para o topo direito; venda média do
  Estoque sobe para o mesmo cluster. Aba de estoque "Escopo" passa a se chamar
  "Mapa geral".
- Tela de Vendedores deixa o toggle especial e fica no padrão das outras.
  Clique numa linha abre o caminhar de vendas em gráfico de linha.
- Prefetch sequencial também cobre Fechados / Completo / Mesmo período.
- Configuração de cortes de Relatórios (clientes e produtos) volta a valer
  nas outras telas quando ligada.

### Corrigido

- Despesas não abria no primeiro clique; mapa de estoque abortava o fetch
  inicial.
- Sidebar colapsada com buraco e rodapé esmagado; data do último movimento
  cortada com reticências.
- `despacharProgresso` duplicado quebrava o Vite.

## 1.7.5 — 2026-09-10

### Alterado

- **Fonte de dados trocada de XLSX agregado para o par de CSV bruto.** A fonte
  por empresa deixa de ser `{empresa}/Dados Mais Atacado.xlsx` (mensal,
  pré-agregado) e passa a ser `{empresa}/{empresa}_MOVIMENTO_ATUAL.csv` +
  `{empresa}/{empresa}_PRODUTO.csv` (`;`, aspas duplas), sem subpasta `BI/`.
  `normalizar_base.py::resolver_arquivos_dados` e
  `backend/engine/analise_funil.py::carregar_csv_base_empresa` (novo, substitui
  `carregar_excel_base_empresa`) fazem o join pela chave de produto.
- Schema canônico ganha `CMV`, `Vendedor` (de `NOME_VENDEDOR`, já suportado) e
  `Data_Venda_Diaria` real (de `DATA_MOVIMENTO`), no lugar do mtime do arquivo
  como proxy de data do último movimento. Mês aceita numérico (1–12) além de
  extenso.
- `descricao` passa a vir de `DESCRICAO_HARMONIZADA` (fallback para a descrição
  bruta quando vazia), no lugar do `harm.xlsx` manual e do marcador de texto
  "NÃO HARMONIZADO" dentro da própria coluna.
- Estoque (`GET /api/estoque/*`) passa a vir de `QUANTIDADE_ESTOQUE` do
  `PRODUTO.csv` (`backend/engine/analise_funil.py::montar_estoque_e_vendas`),
  com custo unitário como CMV total ÷ QTD total do produto, no lugar do
  pipeline "Liquidez" (`Dados_Estoque_*`/`Dados_Vendas_*`).

### Removido

- `harmonizar_descricoes.py` — harmonização manual morta; a fonte já traz
  `DESCRICAO_HARMONIZADA`.
- Geração de `Base.csv`/XLSX intermediário por empresa em `normalizar_base.py`
  e `normalizar_todas_empresas.py`.
- Referências ao deploy via XAMPP/Apache em `CLAUDE.md`, `DOC_TEC.md`,
  `README.md`, `AGENTS.md`, `backend/main.py` e
  `backend/tests/test_atualizacoes.py` — modo descontinuado, hoje a
  distribuição é só o executável.

### Corrigido

- `build.ps1` estava salvo em UTF-8 **sem BOM**. O PowerShell (mesmo pwsh 7)
  lê `.ps1` sem BOM pela codepage do console, não UTF-8 — todo acento/em-dash
  do script virava byte inválido e o parser abortava antes de rodar qualquer
  etapa. Isso derrubou duas rodadas de build (1.7.5) com erro de parsing sem
  relação com o código do app. Corrigido regravando o arquivo com BOM UTF-8
  (`EF BB BF`); nenhuma mudança de conteúdo.
- Dois componentes (`ClientesVisaoGeral.tsx`, `EstoqueVisaoGeral.tsx`)
  quebravam o `tsc -b` por repassar `viewBox` sem o tipo esperado pelo SVG —
  achado só na hora do build de release, porque `npm run dev` não roda
  type-check. Corrigido tipando a prop corretamente.

## 1.7.4 — 2026-09-03

### Corrigido

- Rótulo do furo do donut (estoque e clientes) deixa de atravessar o tooltip.
  Era um overlay HTML depois do gráfico: no Recharts 3 o card vai para um
  portal, e o `onMouseEnter` do `Pie` não dispara, então o 66% pintava em cima
  de "Saudável" / "Sem giro". Agora o número é SVG dentro do canvas.
- Texto do furo era "do capital parado": o 66% é fatia do estoque inteiro, não
  do capital já parado. Agora lê "está parado". Subtítulo do card perdeu o
  "parado", porque o donut inclui o saudável.
- Tabela "Maiores clientes" preenche o card. `max-height: 17rem` no wrap e
  `min-width: 640px` herdado do Analisador deixavam o bloco curto e com barra
  nos dois eixos enquanto o card esticava com o par da grade.

## 1.7.3 — 2026-09-03

### Adicionado

- **Tela de Estoque em duas abas.** "Visão geral" mostra capital em estoque,
  capital parado, risco de ruptura e cobertura média (capital ÷ saída mensal a
  custo), donut por situação, fabricantes que mais prendem dinheiro e as pontas
  — ruptura iminente e dinheiro dormindo. "Escopo" continua com o mapa produto a
  produto. Os números da visão geral vêm de `GET /api/estoque/resumo/{empresa}`
  (`montar_resumo_estoque`), agregados da base inteira: a aba não baixa os
  ~1.200 pontos do mapa. As duas saídas passam pelo mesmo `_combinar_estoque_vendas`,
  então mudar a régua de situação move as duas juntas.

## 1.7.2 — 2026-09-03

### Alterado

- Layout da aba "Visão geral" reorganizado por peso de conteúdo. A grade pareava
  cards muito desiguais — a lista de tags tinha 2 linhas ao lado de uma lista de
  20 nomes, e sobrava meio card vazio. Agora cada linha da grade junta pares de
  peso parecido (donut com gráfico, lista com tabela) e volta a esticar junto,
  então as bordas fecham no mesmo ponto.
- "Receita por tag" deixou de ser card e virou faixa de chips no pé do card de
  Concentração, ocupando o vão que sobrava ali entre a legenda e o rodapé.
- Tabela de maiores clientes perdeu a coluna Qtd: em meia largura, cinco colunas
  truncavam nome e valor.

## 1.7.1 — 2026-09-03

### Corrigido

- Listas da aba "Visão geral" (legenda da curva e receita por tag) alinham as
  colunas entre as linhas. Cada `<li>` era um grid próprio, então coluna `auto`
  media o conteúdo daquela linha e "R$ 9.588.864,96" e "R$ 0,00" empurravam
  contagem, barra e percentual para posições diferentes. Agora as colunas vivem
  no `<ul>` e as linhas as herdam por subgrid.
- Filete lateral da tabela de maiores clientes fica verde na alta (+20% ou mais)
  em vez de só existir em vermelho na queda.

## 1.7.0 — 2026-09-03

### Adicionado

- **Tela de Clientes em duas abas.** "Visão geral" é um dashboard da carteira:
  KPIs do mês de referência (clientes ativos, receita, ticket médio e saldo)
  contra a média dos 6 meses anteriores, curva ABC nos cortes do Analisador,
  entrada e saída de clientes nos últimos 12 meses, lista de quem entrou/voltou/
  parou de comprar e receita por tag. "Base e tags" é a tela que já existia —
  busca, marcação de tags e alertas continuam lá.
- `GET /api/clientes/{empresa}/painel` (`backend/analise_clientes.py`) calcula
  tudo no servidor e devolve poucos KB. Movimento da carteira usa uma janela de
  inatividade de 3 meses e conta cada evento **uma vez**: novo é a primeira
  compra da base, recuperado é quem volta depois da janela inteira parado, e
  perdido é quem comprou há exatamente uma janela e não voltou.
- Cliente marcado como balcão fica fora do painel, com a contagem excluída
  visível na tela — consumidor final é uma linha só e afundaria o Pareto.

### Alterado

- Alertas de ritmo e o card de clientes em alerta passaram para a aba
  "Visão geral".
- Helpers de período mensal saíram de `analise_vendedores.py` para
  `backend/periodo_mensal.py`, agora compartilhados com o painel de clientes.

## 1.6.1 — 2026-09-02

### Corrigido

- Tela de Vendedores nasce desligada e só aparece depois de marcada em
  Configurações; layout da ficha do vendedor corrigido.

## 1.6.0 — 2026-09-02

### Adicionado

- **Tela de Vendedores (`/vendedores`)** — ranking do último mês da base contra
  a média dos 6 anteriores, com ficha por vendedor (clientes, produtos,
  fabricantes e alertas de queda). Base sem a coluna de vendedor responde
  indisponível em vez de falhar.

## 1.5.0 — 2026-09-01

### Adicionado

- **Assistente IA (`/assistente`)** — conversa sobre a empresa selecionada na
  barra lateral, usando exclusivamente os arquivos `<clientId>-crm.md` e
  `<clientId>-analise.md` da carteira. Documentos e API key ficam no backend; o
  navegador recebe só metadados de disponibilidade e a resposta final. Histórico
  vive apenas na página e é apagado ao trocar de empresa ou reiniciar a conversa.
  Backend em `backend/chat_ia.py`, rotas `GET /api/ia/contexto` e
  `POST /api/ia/chat`, com limite de perguntas e requisições por máquina.
- **Análises diárias da carteira** (`gerar_analises_ia.py`, `backend/dossie_ia.py`)
  — lote que lê `Carteira/database_dev.xlsx`, os `<clientId>-crm.md` e os
  summaries do Prisma, e grava `<clientId>-analise.md` por empresa com
  correspondência exata. Empresa sem correspondência é ignorada; falha de um
  cliente não interrompe os demais e vira MD com `status: erro`.
  O contexto entregue ao modelo é factual e pré-calculado — o LLM não faz conta.
- **`configurar_ollama.ps1`** — grava a API key do Ollama Cloud como blob DPAPI
  em `%LOCALAPPDATA%\Prisma\secrets`, fora do repositório, legível só pelo mesmo
  usuário do Windows. A chave nunca entra em código, linha de comando ou workbook.
- **`executar_lote_noturno.ps1`** e revisão de `agendar_normalizacao_todas.ps1`
  — o lote normaliza todas as empresas e depois analisa apenas os summaries
  renovados na própria execução. Agendado de segunda a sexta às 02:00, como o
  usuário Windows atual (exigência do DPAPI), com `StartWhenAvailable`.

### Alterado

- **Linguagem visual unificada** (`dashboard/src/index.css` e componentes):
  preenchimento sólido + borda no lugar de vidro. `backdrop-filter` saiu do
  projeto e `box-shadow` ficou restrito a camada flutuante. Tokens `--surface-1..4`
  substituem `rgba(255,255,255,α)`, que mudava de tom conforme o pai; os 26 raios
  distintos viraram dois (`--raio-card`, `--raio-controle`). O acento do StatCard
  virou filete `::before` de 3px, recuado — `border-left` herdava o raio do card
  e curvava nas pontas.
- `backend/relatorio_cliente.py` — painel do cliente revisado.
- `publicar.ps1` e `normalizar_todas_empresas.bat` — ajustes operacionais do
  fluxo de release e do lote.

### Corrigido

- `montar_contexto_prisma` aceitava `hoje`, mas não repassava para `montar_card`,
  que chamava `date.today()` direto. O sinalizador `ultimo_periodo_parcial` era
  calculado contra o relógio real mesmo com data injetada, o que deixava o teste
  `test_contexto_usa_ultimo_mes_fechado` dependente do dia da execução — quebrou
  na virada de agosto para setembro. `hoje` agora desce até `_eh_mes_corrente`.
