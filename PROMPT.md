# Prompt — Aplicação de Virtual Try-On (Provador Virtual com IA)

> Cole o conteúdo abaixo em um agente de codificação (Copilot Agent, Claude Code, etc.) para gerar a aplicação completa.

---

## Papel

Você é um engenheiro full-stack sênior especializado em Python, aplicações de IA generativa e design de interfaces. Construa uma aplicação web de **Virtual Try-On** (provador virtual) pronta para demonstração a clientes de varejo.

## Objetivo

O usuário envia:
1. **Uma foto de corpo inteiro** (a pessoa).
2. **Uma ou mais fotos de peças de roupa** (camiseta, calça, jaqueta, vestido, tênis, acessórios).

A aplicação entrega **duas saídas**:

- **Imagem (gpt-image-2):** uma foto realista da **mesma pessoa vestindo as peças enviadas**, preservando rosto, tom de pele, proporções corporais, pose e iluminação da foto original.
- **Vídeo (sora-2):** um clipe curto de passarela/lookbook animando o look gerado — a pessoa se move naturalmente (giro, caminhada, mudança de pose) mantendo identidade e as peças consistentes quadro a quadro.

O vídeo é gerado **a partir da imagem de try-on** (image-to-video), nunca do zero, garantindo continuidade visual entre as duas saídas.

## Stack obrigatória

| Camada | Tecnologia |
|---|---|
| Backend | Python 3.11+, **FastAPI**, Uvicorn |
| Modelo de imagem | **gpt-image-2** hospedado no **Microsoft Foundry (Azure AI Foundry)** |
| Modelo de vídeo | **sora-2** hospedado no **Microsoft Foundry (Azure AI Foundry)** |
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
│   ├── video_service.py      # Integração com Foundry / sora-2 (image-to-video)
│   ├── jobs.py               # Registro em memória dos jobs de vídeo (status/progresso)
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
├── videos/                   # vídeos gerados .mp4 (gitignored)
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

## Integração com Foundry / sora-2 (geração de vídeo)

Implemente em `app/video_service.py`, isolado do serviço de imagem:

- Use a **Video API do Foundry** com `model="sora-2"`, no modo **image-to-video**: envie a imagem de try-on já gerada como frame de referência inicial.
- Fluxo assíncrono obrigatório em três etapas: **criar job** → **fazer polling do status** (`queued` / `in_progress` / `completed` / `failed`) → **baixar o conteúdo** do vídeo gerado.
- Nunca faça polling bloqueante no event loop: use `asyncio.sleep` com intervalo crescente (ex.: 3s → 10s) e teto máximo de espera configurável (`VIDEO_TIMEOUT_SECONDS`, padrão 600s).
- Parâmetros configuráveis por env e expostos na UI: `duration` (4, 8 ou 12 segundos), `resolution` / `size` (ex.: `720x1280` vertical, `1280x720` horizontal), `n_variants=1`.
- A resolução do vídeo deve respeitar a **proporção da imagem de origem** — não distorça o look gerado.
- Salve o `.mp4` em `videos/` com nome UUID e sirva por rota dedicada com suporte a **HTTP Range requests** (streaming/seek no player).
- Se a imagem de try-on ainda não existir, o endpoint de vídeo deve retornar `409 Conflict` com mensagem clara.
- Trate explicitamente rejeições por política de conteúdo do provedor, retornando mensagem amigável em vez de stack trace.

### Prompt de vídeo enviado ao sora-2

Monte o prompt combinando:

1. Instrução base: animar a pessoa da imagem de referência mantendo **identidade facial, corte de cabelo, tipo físico e as roupas exatamente iguais**, sem trocar cores, estampas ou modelagem.
2. Direção de câmera escolhida na UI: **passarela** (caminhada frontal lenta em direção à câmera), **giro 360°** (rotação suave sobre o próprio eixo mostrando o caimento), **detalhe do tecido** (câmera aproxima e revela textura), **estático elegante** (leve movimento corporal com câmera parada).
3. Regras de qualidade: movimento humano natural e fisicamente plausível, tecido com caimento e inércia realistas, iluminação estável e coerente com a imagem, sem morphing de rosto ou mãos, sem texto/legenda/marca d'água, sem cortes bruscos de cena.
4. Observações livres do usuário (mesmo campo de texto da geração de imagem, reaproveitado).

## Requisitos da interface

Página única, moderna, limpa, sofisticada — nível de portfólio de agência de design.

**Layout**
- Header fixo, translúcido com `backdrop-filter: blur()`, com logo do cliente à esquerda e nome da aplicação.
- Hero enxuto: título, subtítulo de uma linha, sem ruído visual.
- Área de trabalho em **duas colunas** (desktop) que colapsa para uma coluna (mobile):
  - **Esquerda — Entradas:** card de upload da foto de corpo (dropzone grande com preview) + card de upload das peças (múltiplos arquivos, grade de miniaturas com botão de remover em cada uma) + controles de cenário/estilo/observações + botão primário "Gerar Look".
  - **Direita — Resultado:** área de preview com abas **Foto** e **Vídeo**, estado vazio ilustrado, estado de carregamento (skeleton + barra de progresso + mensagens rotativas do tipo "Analisando o caimento das peças…"), e estado final com a imagem gerada.
- Ações no resultado (foto): **Baixar**, **Comparar** (slider antes/depois arrastável sobre a foto original), **Gerar novamente**.
- **Bloco de vídeo**, habilitado somente após a imagem existir:
  - Seletor de **movimento de câmera** (passarela / giro 360° / detalhe do tecido / estático), **duração** (4s, 8s, 12s) e **orientação** (vertical 9:16 ou horizontal 16:9).
  - Botão secundário **"Gerar Vídeo do Look"**.
  - Enquanto processa: barra de progresso com etapas nomeadas (Enviando → Na fila → Renderizando → Finalizando), tempo decorrido e botão **Cancelar**; aviso de que vídeo leva mais tempo que a foto.
  - Ao concluir: player `<video>` nativo com `controls`, `loop`, `playsinline` e `poster` apontando para a imagem de try-on; ações **Baixar MP4** e **Gerar novamente**.
- Galeria horizontal no rodapé com o histórico da sessão (miniaturas clicáveis, com selo indicando se o item tem vídeo).

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
| `POST` | `/api/video` | JSON: `image_id`, `camera_motion`, `duration`, `orientation`, `notes`. Cria o job no sora-2 e retorna `job_id` imediatamente (`202 Accepted`) |
| `GET` | `/api/video/{job_id}` | Status do job: `status`, `progress`, `video_url` quando concluído, `error` quando falhar |
| `DELETE` | `/api/video/{job_id}` | Cancela um job em andamento |
| `GET` | `/api/health` | Status da app e se o Foundry está configurado (imagem e vídeo) |
| `GET` | `/outputs/{filename}` | Serve imagem gerada (valide o nome do arquivo contra path traversal) |
| `GET` | `/videos/{filename}` | Serve o MP4 gerado com suporte a Range requests (valide contra path traversal) |

## Segurança (obrigatório)

- **Nunca** hardcode endpoint, chave ou deployment no código — apenas via variáveis de ambiente.
- Valide o **tipo real** do arquivo pelos magic bytes (não confie na extensão nem no `content-type`).
- Sanitize e gere nomes de arquivo no servidor (UUID); nunca use o nome enviado pelo cliente.
- Proteja `/outputs/{filename}` e `/videos/{filename}` contra path traversal (aceite apenas `[a-f0-9-]{36}\.png` e `[a-f0-9-]{36}\.mp4`).
- Limite de tamanho de requisição e rate limiting simples por IP nos endpoints de geração — o de vídeo com limite mais rígido por ser caro.
- Limite o número de jobs de vídeo simultâneos (`MAX_CONCURRENT_VIDEO_JOBS`) e recuse novos jobs com `429` quando saturado.
- `image_id` recebido em `/api/video` deve ser validado contra o formato UUID e a existência do arquivo — nunca concatenado direto em caminho.
- Remova metadados EXIF das imagens enviadas antes de processar.
- CORS restrito; sem `allow_origins=["*"]` em produção.
- `.gitignore` cobrindo `.env`, `outputs/`, `videos/`, `__pycache__/`, `.venv/`.

## Qualidade de código

- Type hints completos, funções curtas e coesas, separação clara entre rota / serviço / utilitário.
- Logging estruturado (`logging`) com nível configurável — sem `print`.
- Tratamento de exceções específico: erro de configuração, erro de upload, erro do provedor de IA, timeout, job de vídeo falho ou cancelado.
- Sem comentários óbvios; comente apenas decisões não evidentes.

## Entregáveis

1. Todos os arquivos da estrutura acima, funcionando de ponta a ponta.
2. `requirements.txt` com versões fixadas.
3. `.env.example` documentando: `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_API_VERSION`, `AZURE_OPENAI_API_KEY` (opcional), `IMAGE_MODEL_DEPLOYMENT=gpt-image-2`, `VIDEO_MODEL_DEPLOYMENT=sora-2`, `VIDEO_DEFAULT_DURATION`, `VIDEO_DEFAULT_RESOLUTION`, `VIDEO_TIMEOUT_SECONDS`, `MAX_CONCURRENT_VIDEO_JOBS`, `BRAND_NAME`, `BRAND_ACCENT_COLOR`, `MAX_GARMENTS`, `LOG_LEVEL`.
4. `README.md` com: pré-requisitos, como criar os deployments `gpt-image-2` e `sora-2` no Microsoft Foundry (incluindo regiões suportadas e quota de vídeo), como configurar autenticação, como trocar o logo do cliente, comandos de execução (`uvicorn app.main:app --reload`), custo/tempo estimado por vídeo e limitações conhecidas.

## Critérios de aceitação

- [ ] `pip install -r requirements.txt && uvicorn app.main:app --reload` sobe a aplicação sem erros.
- [ ] Envio de 1 foto de corpo + 2 peças retorna uma imagem gerada em tela.
- [ ] A partir da imagem gerada, "Gerar Vídeo do Look" cria um job, mostra progresso e entrega um MP4 reproduzível na página.
- [ ] O MP4 pode ser baixado e sofrer seek no player (Range requests funcionando).
- [ ] Cancelar um job de vídeo em andamento devolve a UI ao estado anterior sem erro.
- [ ] Substituir `static/img/logo.svg` pelo logo do cliente atualiza o header sem alterar código.
- [ ] Sem logo, a página continua bonita com o fallback textual.
- [ ] Layout íntegro em 1440px, 1024px e 390px de largura.
- [ ] Nenhum segredo presente no código-fonte.
- [ ] Estados de carregamento e de erro tratados visualmente.

## O que NÃO fazer

- Não usar React, Vue, Next.js, Tailwind CDN ou qualquer build step.
- Não usar bibliotecas de UI pesadas — o CSS deve ser autoral.
- Não gravar imagens de usuários em banco de dados nem enviá-las a serviços de terceiros além do Foundry.
- Não gerar o vídeo de forma síncrona dentro do request HTTP — sempre job + polling.
- Não gerar vídeo do zero (text-to-video): o frame inicial é sempre a imagem de try-on.
- Não gerar código placeholder do tipo `# TODO: implementar` — entregue funcional.
