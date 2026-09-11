# Documentação técnica — 2D Prisma

Estado atual das telas e funcionalidades, na versão `1.7.5`. Este documento **não
é incremental**: ele descreve o que existe hoje. Histórico de mudanças fica em
`CHANGELOG.md`; as decisões de arquitetura e o "por que" de cada regra ficam em
`CLAUDE.md`.

## Composição

| Parte | Onde | O que é |
|---|---|---|
| Frontend | `dashboard/` | React + Vite + TypeScript, roteado por `react-router-dom` |
| Backend | `backend/` | FastAPI; serve a API e, no modo executável, o próprio `dist` |
| Motor de análise | `backend/engine/` | reaproveitado do app desktop "Monitor" |
| Empacotamento | `build.ps1`, `publicar.ps1`, `instalador/` | executável Windows, canal de atualização |

Duas formas de rodar: dev (Vite 5173 + uvicorn) e executável Windows com ícone na
bandeja (backend escuta só em `127.0.0.1`, sem servidor web externo).

## Telas

Todas as rotas ficam em `dashboard/src/App.tsx`. O escopo (empresa + loja) é
global, escolhido na barra lateral, e vale em todas as telas.

| Rota | Página | O que faz |
|---|---|---|
| `/` | `DashboardPage` | receita e quantidade por período, loja, cliente, fabricante e produto; histórico, breakdowns e modal de detalhe de receita. Lê `summary.json` estático ou `GET /api/dashboard/summary/{empresa}` |
| `/login` | `LoginPage` | autenticação do Analisador (SQLite local) |
| `/config` | `ConfiguracoesPage` | caminhos fonte/trabalho/atualizações, início automático, "manter dados nesta máquina", regeneração e atualização de versão |
| `/monitor` | `MonitorPage` | visão de todas as empresas a partir dos `resumo_monitor.json`; métrica, janela de meses, busca, ordenação e favoritas |
| `/analisador` | `AnalisadorPage` | configuração de exclusões e cortes de clientes e produtos, prévias, catálogo de relatórios e export Excel/PDF/Word |
| `/clientes` | `ClientesPage` | duas abas: "Visão geral" (dashboard da carteira) e "Base e tags" (busca, tags por cliente e catálogo de tags) |
| `/vendedores` | `VendedoresPage` | ranking do último mês da base contra a média dos 6 anteriores e ficha por vendedor; só aparece depois de liberada em Configurações |
| `/estoque` | `EstoquePage` | duas abas: "Visão geral" (capital, ruptura, cobertura e pontas, via `GET /api/estoque/resumo/{empresa}`) e "Escopo" (mapa produto a produto, classificado em saudável, risco de ruptura, sem estoque, estoque negativo, perdendo força, excesso e sem giro) |
| `/assistente` | `AssistenteIAPage` | chat sobre a empresa selecionada, restrito aos MDs de CRM e análise diária |
| `/mercadologico` | `MercadologicoPage` | Pregão Mercadológico embutido numa aba; a URL é constante de produto, não configuração |

## Tela de Clientes

**Aba "Visão geral"** (`GET /api/clientes/{empresa}/painel`,
`backend/analise_clientes.py`): mês de referência é o último `Periodo_Mensal` da
base, comparado à média dos 6 anteriores.

| Bloco | O que mostra |
|---|---|
| KPIs | clientes ativos, receita do mês, ticket médio e saldo da carteira, cada um com a variação contra a média |
| Concentração | curva ABC dos últimos 12 meses, nos mesmos cortes do `config.json` do Analisador, e quantos clientes fazem 80% da receita |
| Entrada e saída | novos, recuperados e perdidos mês a mês nos últimos 12 meses |
| Movimento do mês | nomes de quem entrou, voltou ou parou de comprar (até 20 por evento, do maior valor para o menor) |
| Receita por tag | chips no pé do card de Concentração: peso comercial de cada tag ativa na janela da curva |
| Maiores clientes | receita do mês contra a média, com filete vermelho em queda de 20% ou mais e verde em alta de 20% ou mais |

A janela de inatividade é de 3 meses e cada evento conta **uma vez**: novo é a
primeira compra da base, recuperado é quem volta depois da janela inteira
parado, perdido é quem comprou há exatamente uma janela e não voltou. Cliente
marcado como balcão fica fora do painel, e a contagem excluída aparece na tela.

A fonte só traz ano e mês, então não há como saber se o último mês já fechou; a
tela avisa quando a queda contra a média passa de 40%, para queda de cobertura
de dados não ser lida como queda de venda.

Alertas de ritmo e o card de clientes em alerta vivem nesta aba.

**Aba "Base e tags"**: catálogo de até 5.000 clientes com busca, filtro por tag
e marcação/desmarcação por linha, gravadas em `clientes_tags.json` no escopo.

## Dados

Dois caminhos, gravados em `config_app` (SQLite):

- **Fonte** (somente leitura absoluta): `/{cliente}/{cliente}_MOVIMENTO_ATUAL.csv`
  + `/{cliente}_PRODUTO.csv`, direto na pasta do cliente (sem subpasta), `;` e
  aspas duplas. O app nunca cria, altera, apaga ou renomeia nada aqui.
- **Trabalho** (escrita): `/{cliente}/` com `config.json`,
  `summary_dashboard.json`, `resumo_monitor.json` e, opcionalmente,
  `clientes_harm.json`. Não há mais `Base.csv`/`harm.xlsx` intermediário — a
  base é lida e cacheada em memória por mtime dos dois CSV de origem.

Sem configuração, os dois são resolvidos dentro do OneDrive corporativo
(`backend/caminhos_padrao.py`). Fonte e trabalho não podem ser a mesma pasta nem
uma dentro da outra — o backend recusa antes de qualquer escrita.

O lote noturno (`normalizar_todas_empresas`) regera summary e resumo do
monitor a partir dos CSV da fonte. Sem ele, a primeira pessoa a abrir o
Monitoramento paga a reconstrução (~18 s de CPU mais o download dos summaries).

## Assistente IA e análises da carteira

Fluxo em duas partes, ligadas pelos arquivos MD da pasta `Carteira/`:

1. **Lote diário** (`gerar_analises_ia.py` + `backend/dossie_ia.py`), de segunda a
   sexta às 02:00. Lê `Carteira/database_dev.xlsx`, os `<clientId>-crm.md` e os
   summaries renovados na própria execução; grava apenas
   `Carteira/dossie/<clientId>-analise.md`. `--dry-run` valida entradas e
   mapeamentos sem chamar a nuvem e sem gravar. Empresa sem correspondência exata
   é ignorada; falha em um cliente não interrompe os demais e substitui a análise
   anterior por um MD com `status: erro`. Logs em `logs_agendador/`, sem a chave.
2. **Chat** (`/assistente`, `backend/chat_ia.py`, rotas `GET /api/ia/contexto` e
   `POST /api/ia/chat`). Responde só a partir do CRM e da análise diária da
   empresa selecionada. Bloqueia empresa sem correspondência exata, MD ausente ou
   análise com `status: erro`. Limita perguntas e requisições por máquina. O
   histórico vive na página e some ao trocar de empresa ou reiniciar a conversa.

O contexto entregue ao modelo é factual e pré-calculado (`montar_contexto_prisma`):
períodos, rankings, cards de 12 meses e sinalizadores de qualidade, incluindo mês
parcial e períodos com quantidade negativa. O LLM não faz conta.

Modelo padrão `gpt-oss:120b`, via `https://ollama.com/api/chat`. A API key é
gravada por `configurar_ollama.ps1` como blob DPAPI em
`%LOCALAPPDATA%\Prisma\secrets\ollama_api_key.dpapi`, fora do repositório e
legível só pelo mesmo usuário do Windows — por isso a tarefa agendada roda como o
usuário atual, que precisa estar conectado.

## Segurança operacional

- O Analisador exige login; o Dashboard é público por decisão de produto.
- Rota destrutiva tem proteção própria contra exposição futura por reverse
  proxy: `_exigir_origem_local` cobre `/api/atualizacoes/aplicar`,
  `dados-no-disco` e `inicio-automatico`.
- Nenhum segredo no repositório. A chave do Ollama só existe como blob DPAPI na
  máquina que roda o lote.

## Interface

Preenchimento sólido e borda, sem vidro. `backdrop-filter` não é usado;
`box-shadow` só em camada flutuante (dropdown, popover, tooltip, modal). Card tem
hover de deslocamento, não de elevação. Tokens em `dashboard/src/index.css`
(`:root`) são a fonte única: `--bg-main`/`--sidebar`/`--bg-card`, degraus
`--surface-1..4`, `--border`/`--border-strong`, `--accent` + `--accent-contrast` e
dois raios (`--raio-card` 12px, `--raio-controle` 8px, mais `--raio-pill`).

## Release

`build.ps1` roda, nesta ordem: `npm run build` → `pytest` → PyInstaller do app →
PyInstaller do atualizador → zip + `version.json` com sha256 → instalador Inno
Setup. Teste reprovando aborta a release. `publicar.ps1` copia o zip antes do
`version.json` (senão existe janela com manifesto novo apontando para zip
ausente), põe o instalador na pasta acima do canal e apaga releases obsoletas,
mantendo uma anterior como escada de volta.

Dois atritos conhecidos do ambiente, que não são defeito do produto:

- Os `.ps1` são UTF-8 sem BOM; o Windows PowerShell 5.1 os lê como ANSI e falha no
  parser. Use `pwsh` 7.
- `publicar.ps1` resolve o canal pelo stdout de um `python -c`. Com o console fora
  de UTF-8, o "ç/õ" de `Atualizações` chega corrompido e o script acusa
  "canal nao encontrado" mesmo com a pasta existindo. Contorno: passar a pasta em
  `-Canal`, resolvida no próprio PowerShell (`Get-ChildItem` sob
  `$env:OneDriveCommercial` filtrando `Atualiza*`), e repassar por splat de
  hashtable — splat de array faz o `-Canal` cair no parâmetro posicional.
