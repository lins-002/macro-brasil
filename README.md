# Macro Brasil

Projeto pessoal (sem fins comerciais) para acompanhar indicadores da
macroeconomia brasileira, usando apenas dados públicos e ferramentas gratuitas.

## Como funciona

- `scripts/atualizar_dados.py` busca as séries na API pública do Banco Central (SGS)
  e salva em `data/*.json`.
- `docs/` contém o site (HTML + JavaScript), publicado via GitHub Pages.
- (Etapa 3) Uma automação do GitHub Actions roda o script periodicamente.

## Rodar localmente

```bash
pip install -r requirements.txt
python scripts/atualizar_dados.py
```

## Séries atuais

| Arquivo | Série | Código SGS |
|---|---|---|
| `data/ipca.json` | IPCA acumulado em 12 meses | 13522 |
| `data/selic.json` | Meta Selic (só as mudanças) | 432 |

Para adicionar um indicador, inclua um item no dicionário `SERIES` em
`scripts/atualizar_dados.py`.

## Fonte dos dados

Banco Central do Brasil — Sistema Gerenciador de Séries Temporais (SGS).
