"""
Atualiza os dados de combustíveis automotivos da ANP.

A ANP publica os dados em arquivos semestrais (ca-AAAA-01 e ca-AAAA-02) e também em
arquivos mensais, em 3 partes (ex.: 09-dados-abertos-precos-2026-09-gasolina-etanol.csv,
...-diesel-gnv.csv e ...-glp.csv). GLP semestral: glp-AAAA-01 / glp-AAAA-02. Este script
aceita todos esses tipos.

Uso (o mais simples): coloque o arquivo baixado da ANP (o .zip, sem extrair) na
pasta "novos" e rode sem argumentos. No Windows, basta dar duplo clique em
ATUALIZAR_COMBUSTIVEIS.bat. Equivale a:
    python scripts/atualizar_combustiveis.py

Outras opções:
    # Indicar o arquivo direto (neste caso ele NÃO é movido para novos/processados):
    python scripts/atualizar_combustiveis.py "C:/Downloads/ca-2026-02.zip"

    # Só regenerar o JSON do site a partir do consolidado atual:
    python scripts/atualizar_combustiveis.py --so-json

Requer:  pip install pandas

Arquivos:
    fonte/anp_consolidado.csv   base acumulada (soma e contagem por UF/produto/mês)
    docs/data/combustiveis.json arquivo lido pelo site

Regra de atualização: para cada par (mês, produto) presente no arquivo novo, os dados
antigos são SUBSTITUÍDOS pelos novos (nada é somado). Por isso usar o mesmo arquivo
duas vezes, ou o .zip e o .csv extraído dele, não duplica nada. O resto do histórico
não muda. Os 3 arquivos de um mesmo mês (gasolina+etanol, diesel+GNV e GLP) podem ser
processados juntos ou em momentos diferentes.
"""

import argparse
import json
import re
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

try:
    import pandas as pd
except ModuleNotFoundError:
    sys.exit("Falta instalar o pandas. Rode:  python -m pip install pandas")

# ----------------------------------------------------------------------
# Configuração
# ----------------------------------------------------------------------
RAIZ = Path(__file__).resolve().parent.parent
CSV_CONSOLIDADO = RAIZ / "fonte" / "anp_consolidado.csv"
JSON_SAIDA = RAIZ / "docs" / "data" / "combustiveis.json"
PASTA_NOVOS = RAIZ / "novos"  # aqui você coloca o arquivo baixado da ANP
PASTA_PROCESSADOS = PASTA_NOVOS / "processados"  # arquivos já usados vão para cá

# Colunas do arquivo bruto da ANP que usamos
COL_REGIAO = "Regiao - Sigla"
COL_UF = "Estado - Sigla"
COL_PRODUTO = "Produto"
COL_DATA = "Data da Coleta"
COL_VALOR = "Valor de Venda"
COLUNAS_BRUTO = {COL_REGIAO, COL_UF, COL_PRODUTO, COL_DATA, COL_VALOR}
COL_UNIDADE = "Unidade de Medida"  # opcional: usada para manter só o botijão de 13 kg
COLUNAS_LIDAS = COLUNAS_BRUTO | {COL_UNIDADE}

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
    ("GLP", "GLP (botijão 13 kg)", "botijão 13 kg"),
]

TAMANHO_PEDACO = 300_000  # linhas lidas por vez (economiza memória)
# Preços acima do limite são tratados como erro de digitação e ignorados.
# O botijão de GLP custa de ~R$ 80 a ~R$ 170, então precisa de um limite maior.
VALOR_MAXIMO_PADRAO = 100.0
VALOR_MAXIMO_POR_PRODUTO = {"GLP": 500.0}


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
    estat = {"linhas": 0, "sem_valor": 0, "valor_invalido": 0, "sem_data": 0, "outro_tamanho": 0}

    arquivo, pacote = abrir_bruto(caminho)
    try:
        leitor = pd.read_csv(
            arquivo,
            sep=";",
            encoding="latin1",
            dtype=str,
            usecols=lambda c: limpar_nome_coluna(c) in COLUNAS_LIDAS,
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

            produto_up = pedaco[COL_PRODUTO].str.strip().str.upper()
            limite = produto_up.map(VALOR_MAXIMO_POR_PRODUTO).fillna(VALOR_MAXIMO_PADRAO)
            valor_ok = valor.notna() & (valor > 0) & (valor < limite)

            # GLP: mantém só o botijão de 13 kg (ignora outros tamanhos, se houver).
            # Se a coluna de unidade não existir ou estiver vazia, não descarta nada.
            outro_tamanho = pd.Series(False, index=pedaco.index)
            if COL_UNIDADE in pedaco.columns:
                unidade = pedaco[COL_UNIDADE].fillna("").str.replace(" ", "", regex=False)
                outro_tamanho = (
                    produto_up.str.startswith("GLP", na=False)
                    & (unidade != "")
                    & ~unidade.str.contains("13", regex=False)
                )
            tem_chaves = (
                pedaco[COL_UF].notna() & pedaco[COL_PRODUTO].notna() & pedaco[COL_REGIAO].notna()
            )
            ok = valor_ok & data.notna() & tem_chaves & ~outro_tamanho

            estat["linhas"] += len(pedaco)
            estat["sem_valor"] += int(valor.isna().sum())
            estat["valor_invalido"] += int((valor.notna() & ~valor_ok).sum())
            estat["sem_data"] += int(data.isna().sum())
            estat["outro_tamanho"] += int(outro_tamanho.sum())

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
    if estat["outro_tamanho"]:
        print(f"  GLP de outros tamanhos (não é 13 kg) ignorados: {estat['outro_tamanho']}")
    if total["n"].sum() < 1000:
        raise ValueError(f"{caminho.name}: poucas cotações válidas ({total['n'].sum()}).")
    return total


def meses_do_nome(caminho: Path):
    """Deduz os meses esperados no arquivo pelo nome.

    Semestral: ca-AAAA-01 / ca-AAAA-02 (combustíveis) ou glp-AAAA-01 / glp-AAAA-02 (GLP).
    Mensal:    ...precos-AAAA-MM... (ex.: 09-dados-abertos-precos-2026-09-diesel-gnv.csv)
    Devolve (conjunto de meses, descrição) ou (None, None) se não reconhecer.
    """
    nome = caminho.name
    achou = re.search(r"(?<![a-z])(?:ca|glp)-(\d{4})-0([12])(?!\d)", nome, re.IGNORECASE)
    if achou:
        ano, semestre = int(achou.group(1)), int(achou.group(2))
        inicio = 1 if semestre == 1 else 7
        meses = {f"{ano}-{m:02d}" for m in range(inicio, inicio + 6)}
        return meses, f"{semestre}º semestre de {ano}"
    achou = re.search(r"precos-(\d{4})-(0[1-9]|1[0-2])(?!\d)", nome, re.IGNORECASE)
    if achou:
        mes = f"{achou.group(1)}-{achou.group(2)}"
        return {mes}, f"mês {mes}"
    return None, None


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
    """Substitui no consolidado cada par (mês, produto) que existe no arquivo novo.

    Nada é somado ao que já existia: o dado novo toma o lugar do antigo. Assim,
    processar o mesmo arquivo de novo (ou uma cópia dele) não duplica linhas, e os
    produtos que NÃO estão no arquivo (ex.: diesel, ao ler o arquivo de gasolina)
    ficam intactos.
    """
    if permitidos is not None:
        fora = novo[~novo["mes"].isin(permitidos)]
        if len(fora):
            print(
                f"  Aviso: {int(fora['n'].sum())} cotações de outros meses "
                f"({sorted(fora['mes'].unique())}) foram ignoradas."
            )
        novo = novo[novo["mes"].isin(permitidos)]
    if novo.empty:
        raise ValueError(
            "Nenhum dado do mês/semestre indicado no nome do arquivo. "
            "Confira se é o arquivo certo."
        )

    chaves_novas = set(zip(novo["mes"], novo["produto"]))
    sera_trocada = [chave in chaves_novas for chave in zip(consolidado["mes"], consolidado["produto"])]
    antigas = consolidado[sera_trocada]
    resultado = pd.concat(
        [consolidado[[not t for t in sera_trocada]], novo], ignore_index=True
    )
    meses_novos = sorted(novo["mes"].unique())
    produtos = sorted(novo["produto"].unique())
    print(
        f"  Meses: {meses_novos[0]} a {meses_novos[-1]} | produtos: {', '.join(produtos)}"
    )
    print(
        f"  Cotações: {int(novo['n'].sum())} no arquivo; "
        f"{int(antigas['n'].sum())} já existiam e foram substituídas (não somadas)."
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
        "nome": "Preço médio de revenda dos combustíveis automotivos e do GLP",
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
def achar_arquivos_novos():
    """Todos os .zip/.csv dentro de novos/, inclusive em subpastas (exceto processados/)."""
    if not PASTA_NOVOS.exists():
        return []
    achados = [
        p for p in PASTA_NOVOS.rglob("*")
        if p.is_file()
        and p.suffix.lower() in (".zip", ".csv")
        and PASTA_PROCESSADOS not in p.parents
    ]
    return sorted(achados, key=lambda p: (p.name.lower(), str(p)))


def guardar_processado(caminho: Path):
    """Move o arquivo usado para novos/processados/ (nunca sobrescreve outro)."""
    PASTA_PROCESSADOS.mkdir(parents=True, exist_ok=True)
    destino = PASTA_PROCESSADOS / caminho.name
    if destino.exists():
        carimbo = datetime.now().strftime("%Y%m%d-%H%M%S")
        destino = PASTA_PROCESSADOS / f"{caminho.stem}_{carimbo}{caminho.suffix}"
    caminho.replace(destino)


def remover_pastas_vazias(pastas):
    """Apaga subpastas de novos/ que ficaram vazias (rmdir só funciona se vazia)."""
    for pasta in sorted(set(pastas), key=lambda x: len(x.parts), reverse=True):
        if pasta != PASTA_NOVOS and PASTA_NOVOS in pasta.parents:
            try:
                pasta.rmdir()
            except OSError:
                pass


def avisar_produtos_ausentes(df: pd.DataFrame):
    """Avisos que ajudam a notar um arquivo esquecido em novos/.

    1) Algum produto tinha dados no mês anterior mas não no último mês
       (ex.: só 1 dos 2 arquivos do mês foi colocado na pasta).
    2) Meses sem nenhum dado nos últimos 12 meses (buracos recentes).
       Buracos antigos e permanentes (ex.: 2014-06) não são avisados.
    """
    meses = sorted(df["mes"].unique())
    ultimo = meses[-1]

    presentes = set(meses)
    janela = pd.period_range(end=pd.Period(ultimo, freq="M"), periods=12, freq="M")
    buracos = [str(p) for p in janela if str(p) not in presentes and str(p) > meses[0]]
    if buracos:
        print(
            f"\n  AVISO: sem dados nos meses {', '.join(buracos)} "
            "(se existirem arquivos da ANP para esses meses, coloque-os em novos/ também)."
        )

    anteriores = [m for m in meses if m < ultimo]
    if not anteriores:
        return
    anterior = anteriores[-1]  # último mês anterior que tenha dados
    faltando = sorted(
        set(df.loc[df["mes"] == anterior, "produto"])
        - set(df.loc[df["mes"] == ultimo, "produto"])
    )
    if faltando:
        print(
            f"\n  ATENCAO: {', '.join(faltando)} tinha(m) dados em {anterior}, mas não em "
            f"{ultimo}. Faltou colocar algum arquivo do mês na pasta novos? "
            "(Cada mês vem em 3 arquivos: gasolina+etanol, diesel+GNV e GLP.)"
        )


def main() -> int:
    analisador = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    analisador.add_argument(
        "arquivos",
        nargs="*",
        help="(opcional) Arquivo(s) da ANP. Sem isso, o script usa os arquivos da pasta novos/.",
    )
    analisador.add_argument(
        "--so-json",
        action="store_true",
        help="Não lê arquivos novos; só regenera o JSON a partir do consolidado.",
    )
    args = analisador.parse_args()

    try:
        consolidado = ler_consolidado()

        if args.so_json:
            if consolidado.empty:
                raise ValueError(f"{CSV_CONSOLIDADO} não existe ou está vazio.")
            gerar_json(consolidado)
            return 0

        if args.arquivos:
            lista, mover = [Path(t) for t in args.arquivos], False
        else:
            lista, mover = achar_arquivos_novos(), True
            if not lista:
                print(f"Nenhum arquivo novo encontrado em: {PASTA_NOVOS}")
                print(
                    "Baixe os arquivos do mês no site da ANP (3 arquivos: gasolina+etanol, "
                    "diesel+GNV e GLP; ou os arquivos do semestre), coloque nessa pasta e rode de novo."
                )
                print("Nada foi alterado.")
                return 1
            print(f"Arquivos encontrados em novos/: {len(lista)}")

        usados, falhas = [], []
        for caminho in lista:
            try:
                if not caminho.exists():
                    raise FileNotFoundError(f"Arquivo não encontrado: {caminho}")
                permitidos, descricao = meses_do_nome(caminho)
                if permitidos is None:
                    print(
                        f"\n{caminho.name}: não reconheci o mês/semestre pelo nome "
                        "(esperado ca-AAAA-01/02, glp-AAAA-01/02 ou ...precos-AAAA-MM...); "
                        "vou usar todos os meses que estiverem dentro dele."
                    )
                else:
                    print(f"\n{caminho.name}: reconhecido como {descricao}")
                novo = agregar_arquivo(caminho)
                consolidado = mesclar(consolidado, novo, permitidos)
                usados.append(caminho)
            except (ValueError, FileNotFoundError, zipfile.BadZipFile) as erro:
                # Um arquivo com problema não derruba os outros (útil ao carregar o
                # histórico inteiro de uma vez). O consolidado só muda com arquivos válidos.
                print(f"  ERRO neste arquivo (ele será ignorado): {erro}")
                falhas.append((caminho, erro))

        if not usados:
            print("\nNenhum arquivo pôde ser usado. Nada foi alterado.")
            return 1

        avisar_produtos_ausentes(consolidado)

        salvar_consolidado(consolidado)
        gerar_json(consolidado)
        if mover:
            pastas = [c.parent for c in usados]
            for caminho in usados:
                guardar_processado(caminho)
            remover_pastas_vazias(pastas)
            print(f"{len(usados)} arquivo(s) usado(s) foram movidos para: {PASTA_PROCESSADOS}")

        titulo = "PRONTO!" if not falhas else "GRAVADO PARCIALMENTE (veja os erros abaixo)."
        print(f"\n{titulo} Agora envie estes 2 arquivos para o GitHub:")
        print(f"  1) {JSON_SAIDA}   (no GitHub: pasta docs > data)")
        print(f"  2) {CSV_CONSOLIDADO}   (no GitHub: pasta fonte)")

        if falhas:
            onde = " e continuam na pasta novos" if mover else ""
            print(f"\nATENCAO: {len(falhas)} arquivo(s) NÃO foram usados{onde}:")
            for caminho, erro in falhas:
                print(f"  - {caminho.name}: {erro}")
            print(
                "Corrija ou remova esses arquivos e rode de novo. "
                "O que já foi gravado não será duplicado."
            )
            return 1
    except (ValueError, FileNotFoundError, zipfile.BadZipFile) as erro:
        print(f"ERRO: {erro}")
        print("Nada foi alterado.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
