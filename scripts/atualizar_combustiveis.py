"""
Atualiza os dados de combustíveis automotivos da ANP.

A ANP publica arquivos por semestre (ca-AAAA-01 e ca-AAAA-02), e o arquivo do
semestre em andamento é atualizado toda semana. Por isso o fluxo mensal é:
baixar só o arquivo do semestre atual e rodar este script.

Uso:
    # 1) Só regenera o JSON do site a partir do consolidado atual:
    python scripts/atualizar_combustiveis.py

    # 2) Atualiza com um arquivo baixado da ANP (CSV ou ZIP) e regenera o JSON:
    python scripts/atualizar_combustiveis.py "C:/Downloads/ca-2026-02.zip"

Requer:  pip install pandas

Arquivos:
    fonte/anp_consolidado.csv   base acumulada (soma e contagem por UF/produto/mês)
    docs/data/combustiveis.json arquivo lido pelo site

Regra de atualização: os meses do semestre do arquivo novo SUBSTITUEM os meses
correspondentes do consolidado (o resto do histórico não muda). Rodar duas
vezes com o mesmo arquivo dá o mesmo resultado.
"""

import argparse
import json
import re
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

# ----------------------------------------------------------------------
# Configuração
# ----------------------------------------------------------------------
RAIZ = Path(__file__).resolve().parent.parent
CSV_CONSOLIDADO = RAIZ / "fonte" / "anp_consolidado.csv"
JSON_SAIDA = RAIZ / "docs" / "data" / "combustiveis.json"

# Colunas do arquivo bruto da ANP que usamos
COL_REGIAO = "Regiao - Sigla"
COL_UF = "Estado - Sigla"
COL_PRODUTO = "Produto"
COL_DATA = "Data da Coleta"
COL_VALOR = "Valor de Venda"
COLUNAS_BRUTO = {COL_REGIAO, COL_UF, COL_PRODUTO, COL_DATA, COL_VALOR}

# Colunas do consolidado (mesmo formato do seu parser)
COLUNAS_CONSOLIDADO = [
    "Regiao - Sigla",
    "Estado - Sigla",
    "Produto",
    "Ano_Mes",
    "Soma_Valor_Venda",
    "Contagem",
]
COLUNAS_INTERNAS = ["regiao", "uf", "produto", "mes", "soma", "n"]

# (código na ANP, nome exibido, unidade). Ordem = ordem no site.
PRODUTOS = [
    ("GASOLINA", "Gasolina comum", "litro"),
    ("GASOLINA ADITIVADA", "Gasolina aditivada", "litro"),
    ("ETANOL", "Etanol", "litro"),
    ("DIESEL", "Diesel (comum)", "litro"),
    ("DIESEL S10", "Diesel S10", "litro"),
    ("DIESEL S50", "Diesel S50", "litro"),
    ("GNV", "GNV", "m³"),
]

TAMANHO_PEDACO = 300_000  # linhas lidas por vez (economiza memória)
VALOR_MAXIMO = 100.0  # preços acima disso são tratados como erro de digitação


# ----------------------------------------------------------------------
# Leitura do arquivo bruto da ANP
# ----------------------------------------------------------------------
def limpar_nome_coluna(nome: str) -> str:
    """Remove BOM (aparece como 'ï»¿' quando lido como latin1) e espaços."""
    return nome.replace("ï»¿", "").replace("\ufeff", "").strip()


def abrir_bruto(caminho: Path):
    """Abre um CSV ou o primeiro CSV dentro de um ZIP. Retorna (arquivo, zip|None)."""
    if caminho.suffix.lower() == ".zip":
        pacote = zipfile.ZipFile(caminho)
        nomes = sorted(n for n in pacote.namelist() if n.lower().endswith(".csv"))
        if not nomes:
            raise ValueError(f"Nenhum .csv dentro de {caminho.name}")
        if len(nomes) > 1:
            print(f"Aviso: {len(nomes)} CSVs no zip; usando {nomes[0]}")
        return pacote.open(nomes[0]), pacote
    return open(caminho, "rb"), None


def agregar_arquivo(caminho: Path) -> pd.DataFrame:
    """Lê o arquivo bruto e devolve soma e contagem por UF/produto/mês."""
    print(f"Lendo {caminho.name} ...")
    parciais = []
    estat = {"linhas": 0, "sem_valor": 0, "valor_invalido": 0, "sem_data": 0}

    arquivo, pacote = abrir_bruto(caminho)
    try:
        leitor = pd.read_csv(
            arquivo,
            sep=";",
            encoding="latin1",
            dtype=str,
            usecols=lambda c: limpar_nome_coluna(c) in COLUNAS_BRUTO,
            chunksize=TAMANHO_PEDACO,
        )
        for numero, pedaco in enumerate(leitor, start=1):
            pedaco.columns = [limpar_nome_coluna(c) for c in pedaco.columns]
            faltando = COLUNAS_BRUTO - set(pedaco.columns)
            if faltando:
                raise ValueError(
                    f"Colunas não encontradas em {caminho.name}: {sorted(faltando)}. "
                    f"Colunas lidas: {list(pedaco.columns)}"
                )

            valor = pd.to_numeric(
                pedaco[COL_VALOR].str.strip().str.replace(",", ".", regex=False),
                errors="coerce",
            )
            texto_data = pedaco[COL_DATA].str.strip()
            data = pd.to_datetime(texto_data, format="%d/%m/%Y", errors="coerce")
            faltou = data.isna()
            if faltou.any():  # tenta o formato AAAA-MM-DD
                data[faltou] = pd.to_datetime(
                    texto_data[faltou], format="%Y-%m-%d", errors="coerce"
                )

            valor_ok = valor.notna() & (valor > 0) & (valor < VALOR_MAXIMO)
            tem_chaves = (
                pedaco[COL_UF].notna() & pedaco[COL_PRODUTO].notna() & pedaco[COL_REGIAO].notna()
            )
            ok = valor_ok & data.notna() & tem_chaves

            estat["linhas"] += len(pedaco)
            estat["sem_valor"] += int(valor.isna().sum())
            estat["valor_invalido"] += int((valor.notna() & ~valor_ok).sum())
            estat["sem_data"] += int(data.isna().sum())

            limpo = pd.DataFrame(
                {
                    "regiao": pedaco.loc[ok, COL_REGIAO].str.strip(),
                    "uf": pedaco.loc[ok, COL_UF].str.strip(),
                    "produto": pedaco.loc[ok, COL_PRODUTO].str.strip().str.upper(),
                    "mes": data[ok].dt.strftime("%Y-%m"),
                    "valor": valor[ok],
                }
            )
            parciais.append(
                limpo.groupby(["regiao", "uf", "produto", "mes"])
                .agg(soma=("valor", "sum"), n=("valor", "count"))
                .reset_index()
            )
            print(f"  bloco {numero}: {len(pedaco)} linhas")
    finally:
        arquivo.close()
        if pacote is not None:
            pacote.close()

    if not parciais:
        raise ValueError(f"{caminho.name}: arquivo sem dados")

    total = (
        pd.concat(parciais, ignore_index=True)
        .groupby(["regiao", "uf", "produto", "mes"])
        .agg(soma=("soma", "sum"), n=("n", "sum"))
        .reset_index()
    )
    print(
        f"  {estat['linhas']} linhas lidas | sem preço: {estat['sem_valor']} | "
        f"preço inválido: {estat['valor_invalido']} | sem data: {estat['sem_data']}"
    )
    if total["n"].sum() < 1000:
        raise ValueError(f"{caminho.name}: poucas cotações válidas ({total['n'].sum()}).")
    return total


def meses_do_semestre(caminho: Path):
    """Deduz os meses do arquivo a partir do nome (ca-AAAA-01 ou ca-AAAA-02)."""
    achou = re.search(r"ca-(\d{4})-0([12])", caminho.name, re.IGNORECASE)
    if not achou:
        return None
    ano, semestre = int(achou.group(1)), int(achou.group(2))
    inicio = 1 if semestre == 1 else 7
    return {f"{ano}-{m:02d}" for m in range(inicio, inicio + 6)}


# ----------------------------------------------------------------------
# Consolidado
# ----------------------------------------------------------------------
def ler_consolidado() -> pd.DataFrame:
    if not CSV_CONSOLIDADO.exists():
        return pd.DataFrame(columns=COLUNAS_INTERNAS)
    df = pd.read_csv(CSV_CONSOLIDADO, sep=";", decimal=",", encoding="utf-8-sig")
    faltando = set(COLUNAS_CONSOLIDADO) - set(df.columns)
    if faltando:
        raise ValueError(f"{CSV_CONSOLIDADO.name} sem as colunas: {sorted(faltando)}")
    df = df[COLUNAS_CONSOLIDADO]
    df.columns = COLUNAS_INTERNAS
    df["mes"] = df["mes"].astype(str)
    return df


def mesclar(consolidado: pd.DataFrame, novo: pd.DataFrame, permitidos) -> pd.DataFrame:
    """Os meses presentes no arquivo novo substituem os do consolidado."""
    if permitidos is not None:
        fora = novo[~novo["mes"].isin(permitidos)]
        if len(fora):
            print(
                f"  Aviso: {int(fora['n'].sum())} cotações fora do semestre "
                f"({sorted(fora['mes'].unique())}) foram ignoradas."
            )
        novo = novo[novo["mes"].isin(permitidos)]
    if novo.empty:
        raise ValueError("Nenhum mês válido no arquivo para este semestre.")

    meses_novos = sorted(novo["mes"].unique())
    antes = int(consolidado["mes"].isin(meses_novos).sum())
    resultado = pd.concat(
        [consolidado[~consolidado["mes"].isin(meses_novos)], novo], ignore_index=True
    )
    print(
        f"  Meses atualizados: {meses_novos[0]} a {meses_novos[-1]} "
        f"({len(meses_novos)} meses; {antes} linhas antigas -> {len(novo)} novas)"
    )
    return resultado


def salvar_consolidado(df: pd.DataFrame):
    saida = df.sort_values(["regiao", "uf", "produto", "mes"]).copy()
    saida["soma"] = saida["soma"].round(3)
    saida["n"] = saida["n"].astype(int)
    saida.columns = COLUNAS_CONSOLIDADO
    CSV_CONSOLIDADO.parent.mkdir(parents=True, exist_ok=True)
    temporario = CSV_CONSOLIDADO.with_suffix(".csv.tmp")
    saida.to_csv(temporario, index=False, sep=";", decimal=",")
    temporario.replace(CSV_CONSOLIDADO)
    print(f"Consolidado salvo: {CSV_CONSOLIDADO} ({len(saida)} linhas)")


# ----------------------------------------------------------------------
# JSON do site
# ----------------------------------------------------------------------
def gerar_json(df: pd.DataFrame):
    """Formato compacto (colunar): uma lista de meses e, para cada produto,
    listas de preço médio alinhadas a esses meses (null = sem dado)."""
    meses = [str(p) for p in pd.period_range(df["mes"].min(), df["mes"].max(), freq="M")]
    posicao = {m: i for i, m in enumerate(meses)}

    conhecidos = [p[0] for p in PRODUTOS]
    extras = sorted(set(df["produto"]) - set(conhecidos))
    if extras:
        print(f"Aviso: produtos novos incluídos no site: {extras}")
    ordem = [p for p in conhecidos if p in set(df["produto"])] + extras
    nomes = {codigo: (nome, unidade) for codigo, nome, unidade in PRODUTOS}

    def media(soma, n):
        return round(float(soma) / float(n), 3)

    brasil, por_uf = {}, {}
    for produto in ordem:
        parte = df[df["produto"] == produto]

        nacional = parte.groupby("mes")[["soma", "n"]].sum()
        serie = [None] * len(meses)
        for mes, linha in nacional.iterrows():
            serie[posicao[mes]] = media(linha["soma"], linha["n"])
        brasil[produto] = serie

        por_uf[produto] = {}
        for uf, grupo in parte.groupby("uf"):
            serie_uf = [None] * len(meses)
            for mes, soma, n in zip(grupo["mes"], grupo["soma"], grupo["n"]):
                serie_uf[posicao[mes]] = media(soma, n)
            por_uf[produto][uf] = serie_uf

    estados = (
        df[["uf", "regiao"]].drop_duplicates().sort_values("uf").to_dict("records")
    )
    conteudo = {
        "serie": "combustiveis",
        "nome": "Preço médio de revenda dos combustíveis automotivos",
        "fonte": "ANP - Levantamento de Preços de Combustíveis",
        "atualizado_em": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "ultimo_mes": meses[-1],
        "meses": meses,
        "produtos": [
            {
                "id": p,
                "nome": nomes.get(p, (p.title(), "litro"))[0],
                "unidade": nomes.get(p, (p.title(), "litro"))[1],
            }
            for p in ordem
        ],
        "estados": [{"sigla": e["uf"], "regiao": e["regiao"]} for e in estados],
        "brasil": brasil,
        "uf": por_uf,
    }

    JSON_SAIDA.parent.mkdir(parents=True, exist_ok=True)
    temporario = JSON_SAIDA.with_suffix(".json.tmp")
    with open(temporario, "w", encoding="utf-8") as f:
        json.dump(conteudo, f, ensure_ascii=False, separators=(",", ":"))
    temporario.replace(JSON_SAIDA)
    kb = JSON_SAIDA.stat().st_size / 1024
    print(
        f"JSON gerado: {JSON_SAIDA} ({kb:.0f} KB) | {len(meses)} meses "
        f"({meses[0]} a {meses[-1]}) | {len(ordem)} produtos"
    )


# ----------------------------------------------------------------------
def main() -> int:
    analisador = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    analisador.add_argument(
        "arquivos",
        nargs="*",
        help="Arquivo(s) da ANP (.csv ou .zip), ex.: ca-2026-02.zip. "
        "Sem argumentos, só regenera o JSON.",
    )
    args = analisador.parse_args()

    try:
        consolidado = ler_consolidado()
        if args.arquivos:
            for texto in args.arquivos:
                caminho = Path(texto)
                if not caminho.exists():
                    raise FileNotFoundError(f"Arquivo não encontrado: {caminho}")
                permitidos = meses_do_semestre(caminho)
                if permitidos is None:
                    print(
                        "  Aviso: não consegui deduzir o semestre pelo nome do arquivo "
                        "(esperado ca-AAAA-01 ou ca-AAAA-02); usando todos os meses dele."
                    )
                novo = agregar_arquivo(caminho)
                consolidado = mesclar(consolidado, novo, permitidos)
            salvar_consolidado(consolidado)
        elif consolidado.empty:
            raise ValueError(
                f"{CSV_CONSOLIDADO} não existe ou está vazio. "
                "Coloque o consolidado em fonte/ ou passe um arquivo da ANP."
            )
        gerar_json(consolidado)
    except (ValueError, FileNotFoundError, zipfile.BadZipFile) as erro:
        print(f"ERRO: {erro}")
        print("Nada foi alterado.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
