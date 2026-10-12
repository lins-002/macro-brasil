# Macro Brasil

Projeto pessoal (sem fins comerciais) para acompanhar indicadores da
macroeconomia brasileira, usando apenas dados públicos e ferramentas gratuitas.

## Como funciona

- `scripts/atualizar_dados.py` busca as séries na API pública do Banco Central (SGS)
  e salva em `docs/data/*.json`.
- `docs/` contém o site (`index.html`, `style.css`, `app.js`), publicado via GitHub Pages.
  Os gráficos usam Chart.js e leem os JSONs de `docs/data/`.
- (Etapa 3) Uma automação do GitHub Actions roda o script periodicamente.

## Rodar localmente

```bash
pip install -r requirements.txt
python scripts/atualizar_dados.py
```

## Séries atuais

| Arquivo | Série | Código SGS |
|---|---|---|
| `docs/data/ipca.json` | IPCA acumulado em 12 meses | 13522 |
| `docs/data/selic.json` | Meta Selic (só as mudanças) | 432 |

Para adicionar um indicador, inclua um item no dicionário `SERIES` em
`scripts/atualizar_dados.py`.

## Fonte dos dados

Banco Central do Brasil — Sistema Gerenciador de Séries Temporais (SGS).

## Ver o site no seu computador

```bash
cd docs
python -m http.server 8000
```

Abra http://localhost:8000 no navegador (abrir o `index.html` com duplo clique
não funciona, porque o navegador bloqueia a leitura dos JSONs).
