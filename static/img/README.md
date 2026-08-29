# Logo do cliente

Coloque aqui o logo do cliente com o nome `logo.svg` (ou `.png`).
**Altura recomendada: 64px, fundo transparente.**

## Ordem de busca

A aplicação procura os arquivos abaixo no boot e usa o **primeiro que existir**:

1. `logo.svg`
2. `logo.png`
3. `logo.jpg`
4. `logo.webp`

Se nenhum arquivo existir, o header exibe um wordmark textual elegante com o valor de
`BRAND_NAME` — a página continua íntegra, sem imagem quebrada.

## Recomendações

- Prefira SVG com traços em cor sólida; o logo é renderizado sobre fundo claro **e** escuro.
- Evite margens internas grandes: o header já aplica o espaçamento.
- Largura máxima renderizada: 200px (o excesso é ajustado com `object-fit: contain`).
- Ajuste `BRAND_NAME` e `BRAND_ACCENT_COLOR` no `.env` para casar com a identidade visual.

> O arquivo `logo.svg` presente neste diretório é apenas um placeholder neutro.
> Substitua-o pelo arquivo do cliente — nenhuma alteração de código é necessária.
