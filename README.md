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
| `docs/data/dolar.json` | Dólar comercial (venda), diário | 1 |
| `docs/data/desemprego.json` | Taxa de desocupação (PNAD Contínua) | 24369 |
| `docs/data/ibcbr.json` | IBC-Br com ajuste sazonal (prévia do PIB) | 24364 |
| `docs/data/divida_bruta.json` | Dívida bruta do governo geral (% do PIB) | 13762 |
| `docs/data/focus.json` | Expectativas do mercado (Boletim Focus, mediana): IPCA, Selic, dólar e PIB do ano atual e do próximo | API Olinda |
| `docs/data/combustiveis.json` | Preço médio mensal dos combustíveis e GLP (ANP) | - |

Para adicionar um indicador, inclua um item no dicionário `SERIES` em
`scripts/atualizar_dados.py`.

## Fonte dos dados

Banco Central do Brasil — Sistema Gerenciador de Séries Temporais (SGS) e Expectativas de Mercado (Focus).

## Ver o site no seu computador

```bash
cd docs
python -m http.server 8000
```

Abra http://localhost:8000 no navegador (abrir o `index.html` com duplo clique
não funciona, porque o navegador bloqueia a leitura dos JSONs).

## Combustíveis e GLP (ANP) - rotina mensal

A ANP não tem API; os arquivos são baixados manualmente em
https://www.gov.br/anp/pt-br/centrais-de-conteudo/dados-abertos/serie-historica-de-precos-de-combustiveis

Cada mês vem em **3 arquivos**: `09-dados-abertos-precos-2026-09-gasolina-etanol.csv`,
`09-dados-abertos-precos-2026-09-diesel-gnv.csv` e `09-dados-abertos-precos-2026-09-glp.csv`.
Também funcionam os arquivos semestrais (`ca-2026-02.zip` para combustíveis e `glp-2026-01.csv` para GLP).

1. Baixe os 3 arquivos do mês (não precisa extrair nada).
2. Coloque todos na pasta `novos/` do projeto.
3. Dê duplo clique em `ATUALIZAR_COMBUSTIVEIS.bat` (ou rode `python scripts/atualizar_combustiveis.py`).
4. No GitHub, envie os 2 arquivos que mudaram (entrando na pasta certa antes de enviar):
   - `docs/data/combustiveis.json` (o site lê este)
   - `fonte/anp_consolidado.csv` (base acumulada)

**Carregar o histórico (uma vez):** coloque todos os arquivos semestrais em `novos/` de uma só vez
(ex.: `glp-2005-01` até `glp-2026-01`) e rode. Se algum arquivo tiver problema, os outros são gravados,
o problemático fica em `novos/` e a tela mostra o motivo; depois de corrigir é só rodar de novo.

**Não duplica dados.** Para cada par (mês, produto) presente no arquivo, o script SUBSTITUI o
que já existia, nunca soma. Então colocar o mesmo arquivo duas vezes, o `.zip` e o `.csv`
extraído dele, ou uma pasta extraída repetida, dá exatamente o mesmo resultado.
Se o nome do arquivo indicar um mês e os dados forem de outro, o script recusa esse arquivo.
Se você esquecer um dos 3 arquivos do mês, o script avisa.
Os arquivos usados são movidos para `novos/processados/`.
Para só regenerar o JSON sem arquivo novo: `python scripts/atualizar_combustiveis.py --so-json`.

**No gráfico:** os combustíveis podem ser combinados à vontade. O GLP (botijão de 13 kg, ~R$ 100)
aparece sempre sozinho, porque a escala é diferente: clicar nele limpa os combustíveis, e clicar
num combustível tira o GLP.
