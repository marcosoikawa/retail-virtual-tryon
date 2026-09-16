# Prompt — Aplicação de Virtual Try-On (Provador Virtual com IA)

> Cole o conteúdo abaixo em um agente de codificação (Copilot Agent, Claude Code, etc.) para gerar a aplicação completa.

---

## Papel

Você é um engenheiro full-stack sênior especializado em Python, aplicações de IA generativa e design de interfaces. Construa uma aplicação web de **Virtual Try-On** (provador virtual) pronta para demonstração a clientes de varejo.

## Objetivo

O usuário envia:
1. **Uma foto de corpo inteiro** (a pessoa).
2. **Uma ou mais fotos de peças de roupa** (camiseta, calça, jaqueta, vestido, tênis, acessórios).

A aplicação entrega uma saída:

- **Imagem (gpt-image-2):** uma foto realista da **mesma pessoa vestindo as peças enviadas**, preservando rosto, tom de pele, proporções corporais, pose e iluminação da foto original.

## Stack obrigatória

| Camada | Tecnologia |
|---|---|
| Backend | Python 3.11+, **FastAPI**, Uvicorn |
| Modelo de imagem | **gpt-image-2** hospedado no **Microsoft Foundry (Azure AI Foundry)** |
| SDK | `openai` (cliente `AzureOpenAI`) apontando para o endpoint do Foundry |
| Autenticação | `DefaultAzureCredential` (Entra ID) com fallback para API key via variável de ambiente |
| Frontend | HTML + CSS + JavaScript vanilla servidos por Jinja2 — **sem framework JS, sem build step** |
| Config | `python-dotenv` + `.env` (nunca commitar segredos) |

## Estrutura de pastas exigida

```
retail-virtual-tryon/
├── app/
│   ├── main.py               # FastAPI: rotas e ciclo de vida
│   ├── config.py             # Settings via pydantic-settings / env vars
│   ├── tryon_service.py      # Integração com Foundry / gpt-image-2
│   ├── image_utils.py        # Validação, redimensionamento, conversão, EXIF
│   └── templates/
│       └── index.html
├── static/
│   ├── css/styles.css
│   ├── js/app.js
│   └── img/                  # <- LOGO DO CLIENTE AQUI
│       ├── README.md         # instruções: substitua logo.png/logo.svg
│       └── logo.svg          # placeholder neutro
├── outputs/                  # imagens geradas (gitignored)
├── .env.example
├── .gitignore
├── requirements.txt
└── README.md
```

### Regra do logo do cliente (importante)

- O logo deve ser carregado dinamicamente de `static/img/`.
- Ordem de busca no boot da aplicação: `logo.svg` → `logo.png` → `logo.jpg` → `logo.webp`. Use o primeiro que existir.
- Se nenhum arquivo existir, exiba um wordmark textual elegante como fallback (sem quebrar a página, sem imagem quebrada).
- Permita customizar o nome da marca e a cor de destaque por variáveis de ambiente: `BRAND_NAME`, `BRAND_ACCENT_COLOR`.
- Documente em `static/img/README.md`: "Coloque aqui o logo do cliente com o nome `logo.svg` (ou .png). Altura recomendada: 64px, fundo transparente."

## Integração com Foundry / gpt-image-2

Implemente em `app/tryon_service.py`:

- Cliente `AzureOpenAI` configurado com `azure_endpoint`, `api_version` e credencial (token provider do Entra ID ou `api_key`).
- Use o endpoint de **edição de imagem** (`client.images.edit`) com `model="gpt-image-2"`, passando **a foto do corpo como imagem primária e as fotos das roupas como imagens de referência adicionais** (a API aceita lista de imagens).
- Parâmetros configuráveis: `size` (ex.: `1024x1536` para retrato de corpo inteiro), `quality`, `n=1`, `input_fidelity="high"` para preservar o rosto.
- A resposta vem em base64 — decodifique, salve em `outputs/` com nome baseado em UUID e retorne também um data URL para exibição imediata.
- Todas as chamadas de rede devem ser **assíncronas ou executadas em thread pool**, nunca bloqueando o event loop.
- Implemente retry com backoff exponencial para erros 429/5xx (máximo 3 tentativas).
- Timeout explícito (ex.: 180s) e mensagens de erro legíveis para o usuário final.

### Engenharia do prompt de geração

Construa o prompt enviado ao gpt-image-2 combinando:

1. Instrução base fixa: gerar uma foto fotorrealista da **pessoa da primeira imagem** vestindo as peças das imagens seguintes; preservar identidade facial, penteado, tom de pele, tipo físico, pose e enquadramento; substituir apenas as roupas.
2. Regras de qualidade: caimento natural do tecido, dobras e sombras coerentes, iluminação e temperatura de cor consistentes com a foto original, respeitar estampas/logos/cores exatas das peças, sem distorções em mãos e rosto, sem texto sobreposto, sem marca d'água.
3. Campos opcionais escolhidos pelo usuário na UI, injetados no prompt: **cenário de fundo** (estúdio neutro / rua urbana / manter original), **estilo de foto** (e-commerce, lookbook, casual), **observações livres** (campo de texto).

## Requisitos da interface

Página única, moderna, limpa, sofisticada — nível de portfólio de agência de design.

**Layout**
- Header fixo, translúcido com `backdrop-filter: blur()`, com logo do cliente à esquerda e nome da aplicação.
- Hero enxuto: título, subtítulo de uma linha, sem ruído visual.
- Área de trabalho em **duas colunas** (desktop) que colapsa para uma coluna (mobile):
  - **Esquerda — Entradas:** card de upload da foto de corpo (dropzone grande com preview) + card de upload das peças (múltiplos arquivos, grade de miniaturas com botão de remover em cada uma) + controles de cenário/estilo/observações + botão primário "Gerar Look".
  - **Direita — Resultado:** área de preview com estado vazio ilustrado, estado de carregamento (skeleton + barra de progresso + mensagens rotativas do tipo "Analisando o caimento das peças…") e estado final com a imagem gerada.
- Ações no resultado (foto): **Baixar**, **Comparar** (slider antes/depois arrastável sobre a foto original), **Gerar novamente**.
- Galeria horizontal no rodapé com o histórico da sessão e miniaturas clicáveis.

**Design system**
- Defina tokens em CSS custom properties: cores, espaçamentos, raios, sombras, tipografia.
- Paleta clara e neutra (off-white, cinzas quentes, texto quase preto) com **uma** cor de destaque derivada de `BRAND_ACCENT_COLOR`.
- Tipografia: `Inter` (ou system font stack) — títulos com `letter-spacing` negativo e peso 600/700.
- Cantos arredondados (12–20px), sombras suaves em camadas, bordas de 1px em cinza muito claro.
- Suporte a **tema claro e escuro** via `prefers-color-scheme` e um toggle manual persistido em `localStorage`.
- Micro-interações: hover elevando cards, transições de 150–250ms com easing suave, dropzone que muda de estado no drag-over, fade-in na imagem gerada.
- Respeite `prefers-reduced-motion`.

**Acessibilidade**
- HTML semântico, labels associados aos inputs, `aria-live="polite"` na área de status, foco visível, contraste mínimo AA, navegação completa por teclado, `alt` descritivo nas imagens.

**UX de upload**
- Drag & drop + clique para selecionar + colar da área de transferência (Ctrl+V).
- Validação no cliente e no servidor: formatos `jpg/jpeg/png/webp`, tamanho máximo 10 MB por arquivo, máximo 5 peças de roupa.
- Mensagens de erro claras em toasts não bloqueantes.

## API do backend

| Método | Rota | Descrição |
|---|---|---|
| `GET` | `/` | Renderiza a página (injeta logo, brand name e accent color) |
| `POST` | `/api/tryon` | `multipart/form-data`: `person` (1 arquivo), `garments` (1..5 arquivos), `background`, `style`, `notes`. Retorna JSON com `image_data_url`, `output_path`, `elapsed_ms` |
| `GET` | `/api/health` | Status da app e se o Foundry está configurado |
| `GET` | `/outputs/{filename}` | Serve imagem gerada (valide o nome do arquivo contra path traversal) |

## Segurança (obrigatório)

- **Nunca** hardcode endpoint, chave ou deployment no código — apenas via variáveis de ambiente.
- Valide o **tipo real** do arquivo pelos magic bytes (não confie na extensão nem no `content-type`).
- Sanitize e gere nomes de arquivo no servidor (UUID); nunca use o nome enviado pelo cliente.
- Proteja `/outputs/{filename}` contra path traversal (aceite apenas nomes UUID com extensão de imagem permitida).
- Limite de tamanho de requisição e rate limiting simples por IP no endpoint de geração.
- Remova metadados EXIF das imagens enviadas antes de processar.
- CORS restrito; sem `allow_origins=["*"]` em produção.
- `.gitignore` cobrindo `.env`, `outputs/`, `__pycache__/`, `.venv/`.

## Qualidade de código

- Type hints completos, funções curtas e coesas, separação clara entre rota / serviço / utilitário.
- Logging estruturado (`logging`) com nível configurável — sem `print`.
- Tratamento de exceções específico: erro de configuração, erro de upload, erro do provedor de IA e timeout.
- Sem comentários óbvios; comente apenas decisões não evidentes.

## Entregáveis

1. Todos os arquivos da estrutura acima, funcionando de ponta a ponta.
2. `requirements.txt` com versões fixadas.
3. `.env.example` documentando: `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_API_VERSION`, `AZURE_OPENAI_API_KEY` (opcional), `IMAGE_MODEL_DEPLOYMENT=gpt-image-2`, `BRAND_NAME`, `BRAND_ACCENT_COLOR`, `MAX_GARMENTS` e `LOG_LEVEL`.
4. `README.md` com: pré-requisitos, como criar o deployment `gpt-image-2` no Microsoft Foundry, como configurar autenticação, como trocar o logo do cliente, comandos de execução (`uvicorn app.main:app --reload`), custo/tempo estimado e limitações conhecidas.

## Critérios de aceitação

- [ ] `pip install -r requirements.txt && uvicorn app.main:app --reload` sobe a aplicação sem erros.
- [ ] Envio de 1 foto de corpo + 2 peças retorna uma imagem gerada em tela.
- [ ] Substituir `static/img/logo.svg` pelo logo do cliente atualiza o header sem alterar código.
- [ ] Sem logo, a página continua bonita com o fallback textual.
- [ ] Layout íntegro em 1440px, 1024px e 390px de largura.
- [ ] Nenhum segredo presente no código-fonte.
- [ ] Estados de carregamento e de erro tratados visualmente.

## O que NÃO fazer

- Não usar React, Vue, Next.js, Tailwind CDN ou qualquer build step.
- Não usar bibliotecas de UI pesadas — o CSS deve ser autoral.
- Não gravar imagens de usuários em banco de dados nem enviá-las a serviços de terceiros além do Foundry.
- Não gerar código placeholder do tipo `# TODO: implementar` — entregue funcional.
