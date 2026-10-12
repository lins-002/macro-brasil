"""
Atualiza os dados de macroeconomia brasileira a partir da API pública do
Banco Central (SGS) e salva em arquivos JSON na pasta data/.

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
from datetime import date, datetime, timezone
from pathlib import Path

import requests

# ----------------------------------------------------------------------
# Configuração
# ----------------------------------------------------------------------
RAIZ = Path(__file__).resolve().parent.parent
# O GitHub Pages só publica o conteúdo de docs/, então os JSONs ficam lá dentro
# para o site conseguir lê-los.
PASTA_DADOS = RAIZ / "docs" / "data"

URL_BASE = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.{codigo}/dados"
TENTATIVAS = 3
ESPERA_SEGUNDOS = 3
TIMEOUT = 30

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
}


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


def buscar_periodo(codigo: int, data_inicial: str, data_final: str):
    """Busca um período com retentativas. Retorna lista ou levanta erro."""
    url = URL_BASE.format(codigo=codigo)
    params = {
        "formato": "json",
        "dataInicial": data_inicial,
        "dataFinal": data_final,
    }
    ultimo_erro = None
    for tentativa in range(1, TENTATIVAS + 1):
        try:
            resposta = requests.get(url, params=params, timeout=TIMEOUT)
            resposta.raise_for_status()
            dados = resposta.json()
            if not isinstance(dados, list):
                raise ValueError(f"Resposta inesperada: {str(dados)[:100]}")
            return dados
        except Exception as erro:  # noqa: BLE001
            ultimo_erro = erro
            print(f"  tentativa {tentativa}/{TENTATIVAS} falhou: {erro}")
            if tentativa < TENTATIVAS:
                time.sleep(ESPERA_SEGUNDOS * tentativa)
    raise RuntimeError(
        f"Falhou após {TENTATIVAS} tentativas "
        f"({data_inicial} a {data_final}): {ultimo_erro}"
    )


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
    """Mantém só os pontos em que o valor mudou (+ o último ponto)."""
    if not registros:
        return registros
    resultado = [registros[0]]
    for anterior, atual in zip(registros, registros[1:]):
        if atual["valor"] != anterior["valor"]:
            resultado.append(atual)
    if resultado[-1] != registros[-1]:
        resultado.append(registros[-1])  # garante a data mais recente
    return resultado


def salvar_json(caminho: Path, conteudo: dict):
    """Grava de forma atômica para nunca deixar um arquivo corrompido."""
    caminho.parent.mkdir(parents=True, exist_ok=True)
    temporario = caminho.with_suffix(".json.tmp")
    with open(temporario, "w", encoding="utf-8") as f:
        json.dump(conteudo, f, ensure_ascii=False, separators=(",", ":"))
    temporario.replace(caminho)


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

    conteudo = {
        "serie": chave,
        "codigo_sgs": cfg["codigo"],
        "nome": cfg["nome"],
        "unidade": cfg["unidade"],
        "frequencia": cfg["frequencia"],
        "fonte": cfg["fonte"],
        "atualizado_em": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "ultimo_ponto": registros[-1],
        "dados": registros,
    }
    salvar_json(PASTA_DADOS / f"{chave}.json", conteudo)
    print(
        f"OK: {len(registros)} pontos salvos "
        f"(de {total_original} originais). Último: {registros[-1]}"
    )
    return True


def main() -> int:
    resultados = {chave: atualizar_serie(chave, cfg) for chave, cfg in SERIES.items()}

    print("\n=== Resumo ===")
    for chave, ok in resultados.items():
        print(f"{chave}: {'atualizado' if ok else 'FALHOU (dados antigos mantidos)'}")

    # Código de saída diferente de zero faz o GitHub Actions marcar a execução
    # como falha e te avisar por e-mail (útil na Etapa 3).
    return 0 if all(resultados.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
