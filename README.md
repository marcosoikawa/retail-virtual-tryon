# Virtual Try-On — Provador Virtual com IA

Aplicação web de demonstração para varejo: o usuário envia uma **foto de corpo inteiro** e
**até 5 peças de roupa**, e recebe duas saídas geradas no **Microsoft Foundry**:

| Saída | Modelo | Descrição |
|---|---|---|
| Foto | `gpt-image-2`, `gpt-image-1-mini`, `FLUX.2-pro` ou `FLUX.2-flex` | A mesma pessoa vestindo as peças, preservando rosto, tom de pele, proporções, pose e iluminação. |
| Vídeo | `sora-2` | Clipe curto de passarela/lookbook animando **a imagem de try-on já gerada** (image-to-video). |

O vídeo nunca é gerado do zero: o primeiro quadro é sempre a foto de try-on, garantindo
continuidade visual entre as duas saídas.

---

## Stack

- **Backend:** Python 3.11+, FastAPI, Uvicorn
- **IA:** GPT Image, FLUX.2 e `sora-2` hospedados no Microsoft Foundry (Azure AI Foundry)
- **SDK:** `openai` (`AsyncAzureOpenAI`) para imagem; chamadas REST assíncronas (`httpx`) para a Video API
- **Auth:** `DefaultAzureCredential` (Entra ID) com fallback para API key via variável de ambiente
- **Frontend:** HTML + CSS + JavaScript vanilla servidos por Jinja2 — sem framework, sem build step

---

## Pré-requisitos

1. Python 3.11 ou superior.
2. Uma assinatura Azure com um recurso **Azure OpenAI / Microsoft Foundry**.
3. Azure CLI (`az login`) se você for usar autenticação sem chave (recomendado).
4. Deployments dos modelos de imagem desejados e do `sora-2` (ver abaixo).

---

## Criando os deployments no Microsoft Foundry

### 1. Criar o recurso

No [portal do Microsoft Foundry](https://ai.azure.com) crie (ou selecione) um projeto e um
recurso Azure OpenAI. Anote o **endpoint** em *Keys and Endpoint*
(ex.: `https://meu-recurso.openai.azure.com`).

### 2. Deployments de imagem

1. Vá em **Models + endpoints → Deploy model → Deploy base model**.
2. Crie deployments para `gpt-image-2` e `gpt-image-1-mini`.
3. Use esses nomes nos deployments ou ajuste `IMAGE_MODEL_DEPLOYMENT` e
  `IMAGE_MINI_MODEL_DEPLOYMENT` no `.env`.
4. Regiões: os modelos de imagem da série GPT-Image ficam disponíveis em um subconjunto
   de regiões — tipicamente **East US, West US 3, Sweden Central, UAE North e Poland Central**.
   Confira a lista atualizada em *Models → Region availability* no portal antes de criar o recurso.

Para habilitar FLUX, crie também deployments globais para `FLUX.2-pro` e/ou
`FLUX.2-flex`. A aplicação usa a API específica da Black Forest Labs, com edição por
múltiplas imagens de referência. Configure `AZURE_FLUX_ENDPOINT` quando esses deployments
estiverem em outro recurso; caso contrário, o endpoint principal será reutilizado.

### 3. Deployment de vídeo — `sora-2`

1. Ainda em **Models + endpoints → Deploy model**, selecione o modelo **Sora 2**.
2. Nomeie o deployment como `sora-2` (ou ajuste `VIDEO_MODEL_DEPLOYMENT`).
3. Regiões: Sora 2 está em **preview** e disponível em um conjunto reduzido de regiões
   (tipicamente **East US 2** e **Sweden Central**). Verifique a disponibilidade atual no portal.
4. **Quota de vídeo:** a cota de vídeo é separada da cota de tokens. Por padrão o serviço
   permite poucos jobs simultâneos por recurso (normalmente **2**). Ajuste
   `MAX_CONCURRENT_VIDEO_JOBS` para não exceder a cota e solicite aumento em
   *Azure Portal → Quotas* quando necessário.

> A Video API é acessada pela **v1 API** (`/openai/v1/videos`) com `api-version=preview`.
> Isso já está configurado em `AZURE_VIDEO_API_VERSION`.

---

## Configurando a autenticação

### Opção A — Entra ID (recomendado, sem segredos)

1. Atribua ao seu usuário (ou à identidade gerenciada da aplicação) a role
   **Cognitive Services User** no recurso, em *Access control (IAM) → Add role assignment*.
2. Faça login localmente:

   ```powershell
   az login
   ```

3. Deixe `AZURE_OPENAI_API_KEY` **vazio** no `.env`.

O escopo do token é configurável em `AZURE_TOKEN_SCOPE`:

- `https://cognitiveservices.azure.com/.default` — recursos Azure OpenAI (padrão).
- `https://ai.azure.com/.default` — projetos Microsoft Foundry.

### Opção B — API key (apenas para testes locais)

Preencha `AZURE_OPENAI_API_KEY` no `.env`. A aplicação passa a usar a chave para imagem e vídeo.
Nunca faça commit desse arquivo — o `.gitignore` já o cobre.

---

## Instalação e execução

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1

pip install -r requirements.txt

Copy-Item .env.example .env    # depois edite o .env com o seu endpoint

uvicorn app.main:app --reload
```

Acesse <http://127.0.0.1:8000>.

Verifique a configuração em <http://127.0.0.1:8000/api/health>:

```json
{
  "status": "ok",
  "foundry_endpoint_configured": true,
  "auth_mode": "entra_id",
  "image": {
    "configured": true,
    "models": {
      "gpt-image-2": { "configured": true, "deployment": "gpt-image-2" },
      "gpt-image-1-mini": { "configured": true, "deployment": "gpt-image-1-mini" },
      "FLUX.2-pro": { "configured": true, "deployment": "FLUX.2-pro" },
      "FLUX.2-flex": { "configured": true, "deployment": "FLUX.2-flex" }
    }
  },
  "video": { "configured": true, "deployment": "sora-2", "active_jobs": 0 }
}
```

---

## Trocando o logo do cliente

Coloque o arquivo em `static/img/` com o nome `logo.svg` (ou `.png`, `.jpg`, `.webp`).
A aplicação procura nessa ordem e usa o primeiro que existir — **sem alterar código**.
Sem nenhum arquivo, o header exibe um wordmark textual baseado em `BRAND_NAME`.

Personalize também:

```dotenv
BRAND_NAME=Minha Marca
BRAND_ACCENT_COLOR=#c0392b
```

Detalhes em [static/img/README.md](static/img/README.md).

---

## API

| Método | Rota | Descrição |
|---|---|---|
| `GET` | `/` | Página única (injeta logo, brand name e accent color) |
| `POST` | `/api/tryon` | `multipart/form-data`: `person`, `garments` (1..5), `image_model`, `background`, `style`, `notes` |
| `POST` | `/api/video` | JSON: `image_id`, `camera_motion`, `duration`, `orientation`, `notes` → `202` com `job_id` |
| `GET` | `/api/video/{job_id}` | `status`, `progress`, `stage`, `video_url`, `error` |
| `DELETE` | `/api/video/{job_id}` | Cancela um job em andamento |
| `GET` | `/api/health` | Status da app e dos deployments |
| `GET` | `/outputs/{uuid}.jpg` | Imagem JPEG gerada |
| `GET` | `/videos/{uuid}.mp4` | MP4 gerado, com suporte a HTTP Range (seek no player) |

---

## Segurança

- Endpoint, chave e deployments vêm exclusivamente de variáveis de ambiente.
- O tipo real dos uploads é validado pelos **magic bytes**, não pela extensão ou `content-type`.
- Os nomes de arquivo são gerados no servidor (UUID v4); o nome enviado pelo cliente é descartado.
- `/outputs/` aceita UUIDs com `.jpg` e, para arquivos legados, `.png`; `/videos/` aceita `.mp4`. Todos resolvem o caminho
  para garantir que ele permanece dentro do diretório (proteção contra path traversal).
- Metadados EXIF são removidos na normalização das imagens (a orientação é aplicada e descartada).
- Rate limiting por IP: `RATE_LIMIT_IMAGE_PER_MINUTE` e `RATE_LIMIT_VIDEO_PER_MINUTE`
  (mais rígido no vídeo, por ser caro), além do teto de `MAX_CONCURRENT_VIDEO_JOBS`.
- Limite de tamanho de requisição e de arquivo (`MAX_UPLOAD_MB`).
- CORS restrito a `ALLOWED_ORIGINS` — sem `*`.

---

## Custo e tempo estimados

| Saída | Tempo típico | Ordem de custo |
|---|---|---|
| Foto (GPT Image ou FLUX.2, JPEG comprimido) | 20–60 s | varia por modelo, tokens ou tarifa por imagem |
| Vídeo (`sora-2`, 720x1280, 8 s) | 1–5 min | cobrado **por segundo de vídeo** — um clipe de 8 s custa cerca de 4× o de 2 s |

O painel calcula cada imagem com a tarifa do modelo selecionado:

| Modelo | Tamanho solicitado ao provedor |
|---|---:|
| `gpt-image-2` | 1024x1536, retrato aceito pela Images Edit API |
| `gpt-image-1-mini` | 1024x1536, menor retrato aceito |
| `FLUX.2-pro` / `FLUX.2-flex` | 300x400 |

O endpoint de edição usado pela aplicação aceita os tamanhos `1024x1024`, `1024x1536` e
`1536x1024` para os modelos GPT Image. O FLUX aceita largura e altura explícitas.
O backend preserva as dimensões retornadas pelo modelo. Para economizar, solicita `quality=low`,
`output_format=jpeg`, `output_compression=80` e uma única imagem (`n=1`).

| Modelo | Entrada de texto / 1M | Entrada de imagem / 1M | Saída de imagem / 1M |
|---|---:|---:|---:|
| `gpt-image-2` | US$ 5,00 | US$ 8,00 | US$ 30,00 |
| `gpt-image-1-mini` | US$ 2,00 | US$ 2,50 | US$ 8,00 |

FLUX.2 é cobrado pelos megapixels das imagens de referência e da saída:

| Medidor | Preço global |
|---|---:|
| FLUX.2 Pro, primeiro MP de saída | US$ 0,03/MP |
| FLUX.2 Pro, MP adicional de saída | US$ 0,015/MP |
| FLUX.2 Pro, imagens de referência | US$ 0,015/MP |
| FLUX.2 Flex, saída | US$ 0,05/MP |
| FLUX.2 Flex, imagens de referência | US$ 0,05/MP |

Para Pro, o custo é `primeiro MP × 0,03 + MP adicional × 0,015 + MP de referências × 0,015`.
Para Flex, é `(MP de saída + MP de referências) × 0,05`. A aplicação mede as dimensões
reais de todas as referências normalizadas e do arquivo retornado pelo provedor.

Na aba **Resultados**, marque uma ou mais linhas em **Por execução** para consolidar somente
essas chamadas. O botão **Todos** volta a incluir todas as execuções. A visão **Consolidado**
recalcula contagens, tempos, tokens, megapixels e custos para a seleção atual. Essa aba considera
somente gerações de imagem; execuções e custos de vídeo permanecem fora dos resultados comparativos.

A projeção usa uma base fixa, não exibida, de 75.000.000 de sessões mensais. O campo somente
leitura **Volume mensal com IA** é calculado como `75.000.000 × penetração`; portanto, a
penetração padrão de 1,5% corresponde a 1.125.000 sessões com IA por mês.

A economia mensal é calculada como `looks mensais × custo de referência no provedor atual
− custo mensal projetado`. A economia anual corresponde ao resultado mensal multiplicado por 12.

O comparativo **GPT-5.6 Luna** usa as tarifas globais de short context por 1 milhão de tokens:
entrada US$ 0,20, entrada em cache US$ 0,02, escrita no cache US$ 0,25 e saída US$ 1,20.
As premissas padrão são 120.000 tokens de entrada por sessão, 100% de leitura do cache e
120.000 tokens escritos no cache por mês. Tokens de saída e todas as premissas financeiras
permanecem editáveis no painel. Esse comparativo considera somente o custo textual; o custo
de Virtual Try-On não entra nas linhas nem nas economias do GPT-5.6 Luna.

Os valores podem ser sobrescritos no `.env`. Preços exatos variam por região e contrato e
mudam com frequência: consulte a
[página de preços do Azure OpenAI](https://azure.microsoft.com/pricing/details/cognitive-services/openai-service/).
Para demonstrações, prefira 4 s a 8 s de duração.

---

## Limitações conhecidas

- **Política de conteúdo do Sora 2:** o modelo recusa imagens de entrada com **rostos humanos
  reais**, pessoas públicas e conteúdo protegido por direitos autorais. Em demos com fotos reais,
  o job de vídeo pode ser bloqueado — a aplicação exibe uma mensagem amigável nesse caso.
  Use modelos sintéticos/consentidos ou enquadramentos sem rosto para a etapa de vídeo.
- **Resoluções de vídeo:** apenas `720x1280` (vertical) e `1280x720` (horizontal). A imagem de
  try-on é recortada (cover, com foco na parte superior) para bater exatamente com o tamanho.
- **Durações:** 4, 8 ou 12 segundos.
- **Concorrência:** o serviço limita jobs de vídeo simultâneos por recurso; a aplicação recusa
  novos jobs com `429` quando saturada.
- **Estado em memória:** o histórico da sessão e o registro de jobs vivem no processo. Reiniciar
  o servidor descarta os jobs em andamento (os arquivos já salvos permanecem em `outputs/` e `videos/`).
- **Single-node:** o rate limiting e o registro de jobs não são compartilhados entre réplicas.
  Para produção multi-instância, troque por Redis ou uma fila dedicada.
- **Fidelidade:** estampas muito pequenas, texto em camisetas e joias finas podem sofrer
  variação. Fotos de corpo inteiro, bem iluminadas e com fundo simples produzem os melhores resultados.
