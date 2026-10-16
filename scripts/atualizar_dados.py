"""
Atualiza os dados de macroeconomia brasileira a partir das APIs públicas do
Banco Central (SGS e Expectativas/Focus) e salva em arquivos JSON em docs/data/.

Uso:
    python scripts/atualizar_dados.py

Regras de segurança:
- Se QUALQUER período de uma série falhar, a série NÃO é salva
  (o arquivo antigo é mantido, assim o site nunca fica sem dados).
- A gravação é atômica (arquivo temporário + rename).
"""

import json
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote

import requests

# ----------------------------------------------------------------------
# Configuração
# ----------------------------------------------------------------------
RAIZ = Path(__file__).resolve().parent.parent
# O GitHub Pages só publica o conteúdo de docs/, então os JSONs ficam lá dentro
# para o site conseguir lê-los.
PASTA_DADOS = RAIZ / "docs" / "data"

URL_BASE = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.{codigo}/dados"
TENTATIVAS = 5
ESPERA_SEGUNDOS = 5  # espera crescente entre tentativas: 5s, 10s, 15s, 20s
TIMEOUT = 30
CABECALHOS = {
    "Accept": "application/json",
    "User-Agent": "macro-brasil-projeto-pessoal/1.0",
}
# Erros 4xx (exceto 408 e 429) não adiantam repetir: o pedido em si está errado.
HTTP_REPETIVEIS = {408, 429}

# Para adicionar um novo indicador, basta incluir um item aqui.
# "somente_mudancas": para séries diárias que mudam raramente (ex.: Selic),
# guarda só os dias em que o valor mudou, deixando o JSON bem menor.
SERIES = {
    "ipca": {
        "codigo": 13522,
        "nome": "IPCA - acumulado em 12 meses",
        "unidade": "% a.a.",
        "frequencia": "mensal",
        "inicio": 1995,
        "somente_mudancas": False,
        "fonte": "IBGE / Banco Central do Brasil (SGS 13522)",
    },
    "selic": {
        "codigo": 432,
        "nome": "Meta Selic",
        "unidade": "% a.a.",
        "frequencia": "diaria (salva apenas as mudancas)",
        "inicio": 1990,
        "somente_mudancas": True,
        "fonte": "Banco Central do Brasil (SGS 432)",
    },
    "dolar": {
        "codigo": 1,
        "nome": "Dólar comercial (venda)",
        "unidade": "R$",
        "frequencia": "diaria",
        "inicio": 2000,
        "somente_mudancas": False,
        "fonte": "Banco Central do Brasil (SGS 1)",
    },
    "desemprego": {
        "codigo": 24369,
        "nome": "Taxa de desocupação (PNAD Contínua)",
        "unidade": "%",
        "frequencia": "mensal",
        "inicio": 2012,
        "somente_mudancas": False,
        "fonte": "IBGE / Banco Central do Brasil (SGS 24369)",
    },
    "ibcbr": {
        "codigo": 24364,
        "nome": "IBC-Br (com ajuste sazonal)",
        "unidade": "índice (2002 = 100)",
        "frequencia": "mensal",
        "inicio": 2003,
        "somente_mudancas": False,
        "fonte": "Banco Central do Brasil (SGS 24364)",
    },
    "divida_bruta": {
        "codigo": 13762,
        "nome": "Dívida bruta do governo geral",
        "unidade": "% do PIB",
        "frequencia": "mensal",
        "inicio": 2006,
        "somente_mudancas": False,
        "fonte": "Banco Central do Brasil (SGS 13762)",
    },
    "divida_bruta_valor": {
        "codigo": 13761,
        "nome": "Dívida bruta do governo geral (saldo)",
        "unidade": "R$ milhões",
        "frequencia": "mensal",
        "inicio": 2006,
        "somente_mudancas": False,
        "fonte": "Banco Central do Brasil (SGS 13761)",
    },
}

# Expectativas de mercado (Boletim Focus): API Olinda do Banco Central.
URL_FOCUS = (
    "https://olinda.bcb.gov.br/olinda/servico/Expectativas/versao/v1/odata/"
    "ExpectativasMercadoAnuais"
)
# (nome na API, rótulo no site, unidade, casas decimais)
FOCUS_INDICADORES = [
    ("IPCA", "IPCA", "%", 2),
    ("Selic", "Selic (fim do ano)", "%", 2),
    ("Câmbio", "Dólar (fim do ano)", "R$", 2),
    ("PIB Total", "PIB (crescimento)", "%", 2),
]


# ----------------------------------------------------------------------
# Funções
# ----------------------------------------------------------------------
def gerar_periodos(ano_inicial: int, ano_final: int, anos_por_bloco: int = 10):
    """Divide o intervalo em blocos de até 10 anos.

    A API do BCB limita consultas de séries diárias a 10 anos por requisição.
    Os blocos são gerados até o ano atual (sem datas fixas no código).
    """
    periodos = []
    ano = ano_inicial
    while ano <= ano_final:
        fim = min(ano + anos_por_bloco - 1, ano_final)
        periodos.append((f"01/01/{ano}", f"31/12/{fim}"))
        ano = fim + 1
    return periodos


def pedir_json(url: str, params: dict, descricao: str):
    """GET com retentativas. Retorna o JSON ou levanta RuntimeError."""
    ultimo_erro = None
    for tentativa in range(1, TENTATIVAS + 1):
        definitivo = False
        try:
            resposta = requests.get(
                url, params=params, headers=CABECALHOS, timeout=TIMEOUT
            )
            if resposta.status_code != 200:
                # Mostra o código HTTP e o início da resposta: é o que permite
                # descobrir a causa quando a coleta falha no GitHub Actions.
                trecho = " ".join(resposta.text.split())[:200]
                definitivo = (
                    400 <= resposta.status_code < 500
                    and resposta.status_code not in HTTP_REPETIVEIS
                )
                raise RuntimeError(f"HTTP {resposta.status_code}: {trecho!r}")
            return resposta.json()
        except Exception as erro:  # noqa: BLE001
            ultimo_erro = erro
            print(f"  tentativa {tentativa}/{TENTATIVAS} falhou: {erro}")
            if definitivo:
                break
            if tentativa < TENTATIVAS:
                time.sleep(ESPERA_SEGUNDOS * tentativa)
    raise RuntimeError(f"Falhou ({descricao}): {ultimo_erro}")


def buscar_periodo(codigo: int, data_inicial: str, data_final: str):
    """Busca um período da série SGS. Retorna lista ou levanta erro."""
    params = {
        "formato": "json",
        "dataInicial": data_inicial,
        "dataFinal": data_final,
    }
    dados = pedir_json(
        URL_BASE.format(codigo=codigo), params, f"{data_inicial} a {data_final}"
    )
    if not isinstance(dados, list):
        raise RuntimeError(f"Resposta inesperada: {str(dados)[:100]}")
    return dados


def converter(registros_brutos):
    """Converte para [{'data': 'AAAA-MM-DD', 'valor': float}], ordenado e sem duplicatas."""
    por_data = {}
    for item in registros_brutos:
        valor_txt = item.get("valor")
        if valor_txt in (None, ""):
            continue  # ignora pontos sem valor
        data_iso = datetime.strptime(item["data"], "%d/%m/%Y").date().isoformat()
        por_data[data_iso] = float(valor_txt)
    return [{"data": d, "valor": por_data[d]} for d in sorted(por_data)]


def manter_somente_mudancas(registros):
    """Mantém só os pontos em que o valor mudou.

    O site estende a linha até a data de hoje, então não é preciso guardar o
    último dia. Assim o arquivo só muda quando a Selic realmente muda.
    """
    if not registros:
        return registros
    resultado = [registros[0]]
    for anterior, atual in zip(registros, registros[1:]):
        if atual["valor"] != anterior["valor"]:
            resultado.append(atual)
    return resultado


def salvar_json(caminho: Path, conteudo: dict):
    """Grava de forma atômica para nunca deixar um arquivo corrompido."""
    caminho.parent.mkdir(parents=True, exist_ok=True)
    temporario = caminho.with_suffix(".json.tmp")
    with open(temporario, "w", encoding="utf-8") as f:
        json.dump(conteudo, f, ensure_ascii=False, separators=(",", ":"))
    temporario.replace(caminho)


def salvar_status():
    """Registra quando a coleta rodou com sucesso (todas as séries consultadas).

    O site mostra essa data no rodapé como "última verificação". Ela muda a cada
    execução bem-sucedida, mesmo quando os dados em si não mudaram. Se a coleta
    falhar, o arquivo não é atualizado e a data fica velha, o que denuncia o problema.
    """
    salvar_json(
        PASTA_DADOS / "status.json",
        {
            "verificado_em": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "ok": True,
        },
    )


def atualizar_serie(chave: str, cfg: dict) -> bool:
    print(f"\n=== {cfg['nome']} (SGS {cfg['codigo']}) ===")
    ano_atual = date.today().year
    brutos = []
    try:
        for ini, fim in gerar_periodos(cfg["inicio"], ano_atual):
            print(f"Consultando {ini} a {fim}...")
            lote = buscar_periodo(cfg["codigo"], ini, fim)
            print(f"  {len(lote)} registros")
            brutos.extend(lote)
    except RuntimeError as erro:
        print(f"ERRO: {erro}")
        print(f"Mantendo o arquivo antigo de '{chave}' (se existir).")
        return False

    registros = converter(brutos)
    if len(registros) < 10:
        print("ERRO: poucos registros recebidos, descartando coleta.")
        return False

    total_original = len(registros)
    if cfg["somente_mudancas"]:
        registros = manter_somente_mudancas(registros)

    caminho = PASTA_DADOS / f"{chave}.json"

    # Se os dados são idênticos aos do arquivo atual, não regrava. Assim o
    # GitHub Actions só faz commit quando há informação nova de verdade.
    if caminho.exists():
        try:
            with open(caminho, encoding="utf-8") as f:
                if json.load(f).get("dados") == registros:
                    print(f"Sem mudanças em '{chave}'. Arquivo mantido.")
                    return True
        except (OSError, ValueError):
            pass  # arquivo ilegível: regrava

    conteudo = {
        "serie": chave,
        "codigo_sgs": cfg["codigo"],
        "nome": cfg["nome"],
        "unidade": cfg["unidade"],
        "frequencia": cfg["frequencia"],
        "fonte": cfg["fonte"],
        "atualizado_em": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "dados": registros,
    }
    salvar_json(caminho, conteudo)
    print(
        f"OK: {len(registros)} pontos salvos "
        f"(de {total_original} originais). Último: {registros[-1]}"
    )
    return True


def _num(valor):
    """Converte para float; devolve None se vier vazio ou inválido."""
    try:
        return float(valor)
    except (TypeError, ValueError):
        return None


# O serviço do Banco Central (Olinda) é exigente com o formato do endereço:
# recusou (HTTP 400) a consulta feita com espaços codificados como "+", que é
# o padrão da biblioteca requests. Por isso o endereço é montado à mão, com %20,
# e o script tenta algumas variações até uma funcionar (a que funcionou é
# lembrada para as próximas consultas).
# (descrição, usar $format=json, caracteres que NÃO são codificados, filtro entre parênteses)
FOCUS_VARIANTES = [
    ("espaço como %20", True, "'(),", False),
    ("sem $format (só cabeçalho Accept)", False, "'(),", False),
    ("aspas codificadas (%27)", True, "(),", False),
    ("filtro entre parênteses", True, "'(),", True),
]
_focus_estado = {"variante": None, "respostas": {}}


def _url_focus(nome_api: str, formato: bool, seguros: str, parenteses: bool) -> str:
    filtro = f"Indicador eq '{nome_api}'"
    if parenteses:
        filtro = f"({filtro})"
    partes = [("$filter", filtro), ("$orderby", "Data desc"), ("$top", "1000")]
    if formato:
        partes.append(("$format", "json"))
    consulta = "&".join(f"{k}={quote(v, safe=seguros)}" for k, v in partes)
    return f"{URL_FOCUS}?{consulta}"


def consultar_focus(nome_api: str):
    """Consulta o Focus de um indicador (uma vez por execução) e devolve o JSON."""
    guardada = _focus_estado["respostas"].get(nome_api)
    if guardada is not None:
        return guardada
    indices = list(range(len(FOCUS_VARIANTES)))
    if _focus_estado["variante"] is not None:
        indices.remove(_focus_estado["variante"])
        indices.insert(0, _focus_estado["variante"])
    ultimo_erro = None
    for i in indices:
        descricao, formato, seguros, parenteses = FOCUS_VARIANTES[i]
        url = _url_focus(nome_api, formato, seguros, parenteses)
        try:
            resp = pedir_json(url, None, f"Focus {nome_api} [{descricao}]")
        except RuntimeError as erro:
            ultimo_erro = erro
            print(f"  variante '{descricao}' recusada.")
            continue
        if isinstance(resp, dict) and isinstance(resp.get("value"), list):
            if _focus_estado["variante"] != i:
                print(f"  Focus: consulta aceita com a variante '{descricao}'.")
            _focus_estado["variante"] = i
            _focus_estado["respostas"][nome_api] = resp
            return resp
        ultimo_erro = RuntimeError(f"resposta inesperada: {str(resp)[:100]}")
    raise ultimo_erro


def coletar_focus_indicador(nome_api: str, ano: int):
    """Últimas medianas do Focus para um indicador e um ano de referência.

    Retorna (data_mais_recente, mediana, mediana_4_semanas_antes, minimo, maximo, n).
    """
    # Os 1000 registros mais recentes do indicador cobrem bem mais de 4 semanas
    # de pesquisas. O ano de referência e a base de cálculo são filtrados aqui.
    resp = consultar_focus(nome_api)
    linhas = resp.get("value") if isinstance(resp, dict) else None
    linhas = [
        l for l in (linhas or [])
        if str(l.get("DataReferencia")) == str(ano)
        and str(l.get("baseCalculo")) == "0"
    ]
    if not linhas:
        raise RuntimeError(f"Focus sem dados para {nome_api} {ano}")

    # Alguns indicadores podem ter mais de um "detalhe". Prefere "Fim do ano";
    # se não houver, usa o primeiro que aparecer.
    detalhes = []
    for linha in linhas:
        det = linha.get("IndicadorDetalhe")
        if det not in detalhes:
            detalhes.append(det)
    escolhido = next(
        (d for d in detalhes if d and "fim do ano" in str(d).lower()), detalhes[0]
    )
    linhas = [l for l in linhas if l.get("IndicadorDetalhe") == escolhido]

    por_data = {}
    for linha in linhas:
        mediana = _num(linha.get("Mediana"))
        data = str(linha.get("Data") or "")[:10]
        if mediana is None or len(data) != 10:
            continue
        por_data[data] = (mediana, linha)
    if not por_data:
        raise RuntimeError(f"Focus sem medianas válidas para {nome_api} {ano}")

    datas = sorted(por_data, reverse=True)
    recente = datas[0]
    mediana, linha = por_data[recente]

    # Valor de cerca de 4 semanas antes, para mostrar a tendência.
    limite = (date.fromisoformat(recente) - timedelta(days=28)).isoformat()
    antes = next((d for d in datas if d <= limite), None)
    anterior = por_data[antes][0] if antes else None
    n = linha.get("numeroRespondentes")
    return (
        recente,
        mediana,
        anterior,
        _num(linha.get("Minimo")),
        _num(linha.get("Maximo")),
        int(n) if _num(n) is not None else None,
    )


def atualizar_focus() -> bool:
    print("\n=== Expectativas de mercado (Boletim Focus) ===")
    hoje = date.today()
    anos = [hoje.year, hoje.year + 1]
    indicadores = []
    data_pesquisa = None
    try:
        for nome_api, rotulo, unidade, casas in FOCUS_INDICADORES:
            valores = {}
            for ano in anos:
                recente, med, ant, minimo, maximo, n = coletar_focus_indicador(
                    nome_api, ano
                )
                print(f"  {nome_api} {ano}: mediana {med} ({recente})")
                valores[str(ano)] = {
                    "mediana": med,
                    "anterior": ant,
                    "minimo": minimo,
                    "maximo": maximo,
                    "respondentes": n,
                }
                if data_pesquisa is None or recente > data_pesquisa:
                    data_pesquisa = recente
            indicadores.append(
                {"id": nome_api, "nome": rotulo, "unidade": unidade,
                 "casas": casas, "valores": valores}
            )
    except RuntimeError as erro:
        print(f"ERRO: {erro}")
        print("Mantendo o arquivo antigo do Focus (se existir).")
        return False

    conteudo = {
        "serie": "focus",
        "nome": "Expectativas de mercado (Boletim Focus) - mediana",
        "fonte": "Banco Central do Brasil - Expectativas de Mercado (Focus)",
        "data_pesquisa": data_pesquisa,
        "anos": anos,
        "indicadores": indicadores,
    }
    caminho = PASTA_DADOS / "focus.json"
    if caminho.exists():
        try:
            with open(caminho, encoding="utf-8") as f:
                antigo = json.load(f)
            antigo.pop("atualizado_em", None)
            if antigo == conteudo:
                print("Sem mudanças no Focus. Arquivo mantido.")
                return True
        except (OSError, ValueError):
            pass
    conteudo["atualizado_em"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    salvar_json(caminho, conteudo)
    print(f"OK: Focus salvo (pesquisa de {data_pesquisa}).")
    return True


# PIB: IBGE, Contas Nacionais Trimestrais (SIDRA, tabela 5932, "PIB a preços de
# mercado"). Variáveis: 6561 = contra o mesmo trimestre do ano anterior;
# 6562 = acumulada em 4 trimestres; 6563 = acumulada no ano (contra o mesmo
# período do ano anterior); 6564 = contra o trimestre imediatamente anterior
# (série com ajuste sazonal).
URL_PIB = (
    "https://apisidra.ibge.gov.br/values/t/5932/n1/all/v/6561,6562,6563,6564"
    "/p/all/c11255/90707"
)
PIB_VARIAVEIS = {"6561": "yoy", "6562": "acum_4tri", "6563": "acum_ano", "6564": "qoq"}


def montar_pib(linhas):
    """Transforma a resposta do SIDRA em {'trimestral': [...], 'anual': [...]}.

    Anual: valor = taxa acumulada no ano até o último trimestre divulgado.
    Se esse trimestre não for o 4º, o ano é "parcial" (o site põe asterisco).
    """
    por_periodo = {}
    for linha in linhas:
        campo = PIB_VARIAVEIS.get(str(linha.get("D2C")))
        periodo = str(linha.get("D3C") or "")
        if not campo or len(periodo) != 6 or not periodo.isdigit():
            continue
        valor = _num(linha.get("V"))  # "-", "..." e "X" viram None
        por_periodo.setdefault(periodo, {})[campo] = valor

    trimestral = []
    for periodo in sorted(por_periodo):
        ano, tri = int(periodo[:4]), int(periodo[4:])
        if tri not in (1, 2, 3, 4):
            continue
        item = {"periodo": f"{ano}-T{tri}", "ano": ano, "tri": tri,
                "data": f"{ano}-{(tri - 1) * 3 + 1:02d}-01"}
        item.update({c: por_periodo[periodo].get(c) for c in PIB_VARIAVEIS.values()})
        if all(item[c] is None for c in PIB_VARIAVEIS.values()):
            continue
        trimestral.append(item)

    anual = []
    for ano in sorted({i["ano"] for i in trimestral}):
        com_valor = [i for i in trimestral if i["ano"] == ano and i["acum_ano"] is not None]
        if not com_valor:
            continue
        ultimo = max(com_valor, key=lambda i: i["tri"])
        anual.append({"ano": ano, "valor": ultimo["acum_ano"],
                      "ate_trimestre": ultimo["tri"], "parcial": ultimo["tri"] < 4})
    return {"trimestral": trimestral, "anual": anual}


def atualizar_pib() -> bool:
    print("\n=== PIB (IBGE - Contas Nacionais Trimestrais, SIDRA 5932) ===")
    try:
        resp = pedir_json(URL_PIB, None, "PIB (SIDRA 5932)")
        if not isinstance(resp, list) or len(resp) < 2:
            raise RuntimeError(f"Resposta inesperada: {str(resp)[:100]}")
        # A primeira linha do SIDRA é o cabeçalho (nomes das colunas).
        dados = montar_pib(resp[1:])
    except RuntimeError as erro:
        print(f"ERRO: {erro}")
        print("Mantendo o arquivo antigo do PIB (se existir).")
        return False
    if len(dados["trimestral"]) < 40 or not dados["anual"]:
        print("ERRO: poucos dados do PIB recebidos, descartando coleta.")
        return False

    conteudo = {
        "serie": "pib",
        "nome": "PIB a preços de mercado - variação real",
        "unidade": "%",
        "fonte": "IBGE - Contas Nacionais Trimestrais (SIDRA, tabela 5932)",
        **dados,
    }
    caminho = PASTA_DADOS / "pib.json"
    if caminho.exists():
        try:
            with open(caminho, encoding="utf-8") as f:
                antigo = json.load(f)
            antigo.pop("atualizado_em", None)
            if antigo == conteudo:
                print("Sem mudanças no PIB. Arquivo mantido.")
                return True
        except (OSError, ValueError):
            pass
    conteudo["atualizado_em"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    salvar_json(caminho, conteudo)
    ult = dados["trimestral"][-1]
    print(f"OK: PIB salvo ({len(dados['trimestral'])} trimestres, "
          f"{len(dados['anual'])} anos). Último trimestre: {ult['periodo']}.")
    return True


def main() -> int:
    if "--so-focus" in sys.argv:
        # Teste rápido: só o Boletim Focus (leva poucos segundos).
        ok = atualizar_focus()
        print("focus:", "atualizado" if ok else "FALHOU")
        return 0 if ok else 1
    if "--so-pib" in sys.argv:
        # Teste rápido: só o PIB do IBGE.
        ok = atualizar_pib()
        print("pib:", "atualizado" if ok else "FALHOU")
        return 0 if ok else 1
    resultados = {chave: atualizar_serie(chave, cfg) for chave, cfg in SERIES.items()}
    focus_ok = atualizar_focus()
    pib_ok = atualizar_pib()

    print("\n=== Resumo ===")
    for chave, ok in resultados.items():
        print(f"{chave}: {'atualizado' if ok else 'FALHOU (dados antigos mantidos)'}")
    print(f"focus: {'atualizado' if focus_ok else 'FALHOU (dados antigos mantidos)'}")
    print(f"pib: {'atualizado' if pib_ok else 'FALHOU (dados antigos mantidos)'}")

    # A data de "última verificação" vale para as séries do SGS. O Focus vem de
    # outro serviço do Banco Central: se só ele falhar, a execução ainda é marcada
    # como falha (você é avisado), mas a data de verificação das demais é mantida.
    if all(resultados.values()):
        salvar_status()
    # Código de saída diferente de zero faz o GitHub Actions marcar a execução
    # como falha e te avisar por e-mail.
    return 0 if (all(resultados.values()) and focus_ok and pib_ok) else 1


if __name__ == "__main__":
    sys.exit(main())
