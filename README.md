# Virtual Try-On — Provador Virtual com IA

Aplicação web de demonstração para varejo: o usuário envia uma **foto de corpo inteiro** e
**até 5 peças de roupa**, e recebe uma composição visual gerada no **Microsoft Foundry**:

| Saída | Modelo | Descrição |
|---|---|---|
| Foto | `gpt-image-2` | A mesma pessoa vestindo as peças, preservando rosto, tom de pele, proporções, pose e iluminação. |

---

## Stack

- **Backend:** Python 3.11+, FastAPI, Uvicorn
- **IA:** GPT Image 2 hospedado no Microsoft Foundry (Azure AI Foundry)
- **SDK:** `openai` (`AsyncAzureOpenAI`) para geração de imagem
- **Auth:** `DefaultAzureCredential` (Entra ID) com fallback para API key via variável de ambiente
- **Frontend:** HTML + CSS + JavaScript vanilla servidos por Jinja2 — sem framework, sem build step

---

## Pré-requisitos

1. Python 3.11 ou superior.
2. Uma assinatura Azure com um recurso **Azure OpenAI / Microsoft Foundry**.
3. [Azure CLI](https://learn.microsoft.com/en-us/cli/azure/install-azure-cli?view=azure-cli-latest)
  (`az login`) se você for usar autenticação sem chave (recomendado).
4. Deployment do modelo `gpt-image-2` (ver abaixo).

---

## Criando os deployments no Microsoft Foundry

### 1. Criar o recurso

No [portal do Microsoft Foundry](https://ai.azure.com) crie (ou selecione) um projeto e um
recurso Azure OpenAI. Anote o **endpoint** em *Keys and Endpoint*
(ex.: `https://meu-recurso.services.ai.azure.com`).

### 2. Deployment de imagem

1. Vá em **Models + endpoints → Deploy model → Deploy base model**.
2. Crie um deployment para `gpt-image-2`.
3. Use esse nome no deployment ou ajuste `IMAGE_MODEL_DEPLOYMENT` no `.env`.
4. Para o `gpt-image-2` versão `2026-04-21` em Global Standard, a documentação atual lista
  **East US 2, West US 3, Poland Central, Sweden Central e UAE North**. Confira a
  [disponibilidade regional oficial](https://learn.microsoft.com/azure/foundry/foundry-models/concepts/models-sold-directly-by-azure-region-availability)
  antes de criar o recurso.

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

O token Entra ID é solicitado exclusivamente com o escopo do Microsoft Foundry:
`https://ai.azure.com/.default`.

### Opção B — API key (apenas para testes locais)

Preencha `AZURE_OPENAI_API_KEY` no `.env`. A aplicação passa a usar a chave para gerar imagens.
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
      "gpt-image-2": { "configured": true, "deployment": "gpt-image-2" }
    }
  }
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
| `GET` | `/api/health` | Status da app e do deployment |
| `GET` | `/outputs/{uuid}.jpg` | Imagem JPEG gerada |

---

## Segurança

- Endpoint, chave e deployments vêm exclusivamente de variáveis de ambiente.
- O tipo real dos uploads é validado pelos **magic bytes**, não pela extensão ou `content-type`.
- Fotos da pessoa são reduzidas proporcionalmente para até `600x800`; imagens das roupas,
  para até `200x232`. Imagens menores não são ampliadas.
- Os nomes de arquivo são gerados no servidor (UUID v4); o nome enviado pelo cliente é descartado.
- `/outputs/` aceita UUIDs com `.jpg` e, para arquivos legados, `.png`, sempre validando
  que o caminho permanece dentro do diretório (proteção contra path traversal).
- Metadados EXIF são removidos na normalização das imagens (a orientação é aplicada e descartada).
- Rate limiting por IP configurado por `RATE_LIMIT_IMAGE_PER_MINUTE`.
- Limite de tamanho de requisição e de arquivo (`MAX_UPLOAD_MB`).
- CORS restrito a `ALLOWED_ORIGINS` — sem `*`.

---

## Custo e tempo estimados

| Saída | Tempo típico | Ordem de custo |
|---|---|---|
| Foto (GPT Image 2, JPEG comprimido) | 20–60 s | varia conforme o uso de tokens |

O painel calcula cada imagem com a tarifa do GPT Image 2 em implantação **Global Standard**:

| Modelo | Tamanho solicitado ao provedor |
|---|---:|
| `gpt-image-2` | 1024x1536, retrato aceito pela Images Edit API |

O endpoint de edição usado pela aplicação aceita os tamanhos `1024x1024`, `1024x1536` e
`1536x1024` para o GPT Image 2.
O backend preserva as dimensões retornadas pelo modelo. Para economizar, solicita `quality=low`,
`output_format=jpeg`, `output_compression=80` e uma única imagem (`n=1`).

| Modelo | Texto de entrada / 1M | Texto em cache / 1M | Imagem de entrada / 1M | Imagem em cache / 1M | Imagem de saída / 1M |
|---|---:|---:|---:|---:|---:|
| `gpt-image-2` Global | US$ 5,00 | US$ 1,25 | US$ 8,00 | US$ 2,00 | US$ 30,00 |

Valores consultados na [tabela oficial de preços do Azure OpenAI](https://azure.microsoft.com/pricing/details/azure-openai/)
em 16 de setembro de 2026. O estimador da aplicação usa as tarifas sem cache para os tokens
reportados pela API. Os preços podem variar conforme contrato, moeda e modalidade de implantação.

Na aba **Resultados**, marque uma ou mais linhas em **Por execução** para consolidar somente
essas chamadas. O botão **Todos** volta a incluir todas as execuções. A visão **Consolidado**
recalcula contagens, tempos, tokens, megapixels e custos para a seleção atual.

A projeção usa **67.500 sessões com IA por mês** como valor inicial. O campo
**Volume mensal com IA** é editável e atualiza os cálculos do consolidado e do comparativo Luna.

A economia mensal é calculada como `looks mensais × custo de referência de outro fornecedor
− custo mensal projetado`. A economia anual corresponde ao resultado mensal multiplicado por 12.

O comparativo **GPT-5.6 Luna** usa as tarifas globais de short context por 1 milhão de tokens:
entrada US$ 0,20, entrada em cache US$ 0,02, escrita no cache US$ 0,25 e saída US$ 1,20.
As premissas padrão são 120.000 tokens de entrada por sessão, 100% de leitura do cache e
120.000 tokens escritos no cache por mês. Tokens de saída e todas as premissas financeiras
permanecem editáveis no painel. Esse comparativo considera somente o custo textual; o custo
de Virtual Try-On não entra nas linhas nem nas economias do GPT-5.6 Luna.

As tarifas sem cache do GPT Image 2 podem ser sobrescritas no `.env` pelas variáveis
`GPT_IMAGE_2_INPUT_TEXT_PRICE_PER_1M`, `GPT_IMAGE_2_INPUT_IMAGE_PRICE_PER_1M` e
`GPT_IMAGE_2_OUTPUT_IMAGE_PRICE_PER_1M`.

---

## Limitações conhecidas

- **Estado em memória:** o histórico da sessão vive no processo e é reiniciado com o servidor.
- **Single-node:** o rate limiting e as métricas em memória não são compartilhados entre réplicas.
  Para produção multi-instância, use um armazenamento compartilhado, como Redis.
- **Fidelidade:** estampas muito pequenas, texto em camisetas e joias finas podem sofrer
  variação. Fotos de corpo inteiro, bem iluminadas e com fundo simples produzem os melhores resultados.
