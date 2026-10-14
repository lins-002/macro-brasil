// Combustíveis (ANP): preço médio mensal com filtros de estado, período e tipo.
// Lê docs/data/combustiveis.json (gerado por scripts/atualizar_combustiveis.py).
// Usa helpers definidos em app.js (css, fmtNumero, fmtMes, paraData), que é
// carregado antes deste arquivo.

const COMB_ARQUIVO = "data/combustiveis.json";

// Cores fixas por produto (paleta amigável a daltonismo, boa em tema claro e escuro)
const COMB_CORES = {
  "GASOLINA": "#0072B2",
  "GASOLINA ADITIVADA": "#56B4E9",
  "ETANOL": "#009E73",
  "DIESEL": "#D55E00",
  "DIESEL S10": "#E69F00",
  "DIESEL S50": "#CC79A7",
  "GNV": "#8a8f98",
};
const COMB_COR_PADRAO = "#8a8f98";

const COMB_PADRAO = ["GASOLINA", "ETANOL", "DIESEL S10"];

const NOMES_UF = {
  AC: "Acre", AL: "Alagoas", AM: "Amazonas", AP: "Amapá", BA: "Bahia",
  CE: "Ceará", DF: "Distrito Federal", ES: "Espírito Santo", GO: "Goiás",
  MA: "Maranhão", MG: "Minas Gerais", MS: "Mato Grosso do Sul", MT: "Mato Grosso",
  PA: "Pará", PB: "Paraíba", PE: "Pernambuco", PI: "Piauí", PR: "Paraná",
  RJ: "Rio de Janeiro", RN: "Rio Grande do Norte", RO: "Rondônia", RR: "Roraima",
  RS: "Rio Grande do Sul", SC: "Santa Catarina", SE: "Sergipe", SP: "São Paulo",
  TO: "Tocantins",
};

const MESES_ABREV = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"];

const comb = {
  json: null,
  grafico: null,
  uf: "BR", // "BR" = média nacional
  selecionados: new Set(COMB_PADRAO),
  de: null, // "AAAA-MM"
  ate: null,
};

// ---------- utilitários ----------
const combFmtMesAno = (m) => `${MESES_ABREV[Number(m.slice(5, 7)) - 1]}/${m.slice(0, 4)}`;
const combMesValido = (m) => /^\d{4}-(0[1-9]|1[0-2])$/.test(m || "");

// Soma n meses a um "AAAA-MM" (n pode ser negativo)
function combSomarMeses(m, n) {
  const total = Number(m.slice(0, 4)) * 12 + (Number(m.slice(5, 7)) - 1) + n;
  const ano = Math.floor(total / 12);
  return `${ano}-${String((total % 12) + 1).padStart(2, "0")}`;
}

function combSerie(produtoId) {
  const { json, uf } = comb;
  if (uf === "BR") return json.brasil[produtoId];
  const porUf = json.uf[produtoId];
  return porUf && porUf[uf] ? porUf[uf] : null; // null = produto sem dado neste estado
}

function combIndices() {
  const { meses } = comb.json;
  let i0 = meses.findIndex((m) => m >= comb.de);
  if (i0 === -1) i0 = meses.length;
  let i1 = meses.length - 1;
  while (i1 >= 0 && meses[i1] > comb.ate) i1--;
  return [i0, i1];
}

// ---------- KPI da gasolina ----------
function combPreencherKpi() {
  const card = document.getElementById("kpi-gasolina");
  const serie = comb.json.brasil["GASOLINA"];
  if (!serie) return;
  let i = serie.length - 1;
  while (i >= 0 && serie[i] === null) i--;
  if (i < 0) return;

  card.querySelector(".valor").textContent = "R$ " + fmtNumero(serie[i], 2);
  const mes = combFmtMesAno(comb.json.meses[i]);
  const antes = i >= 12 ? serie[i - 12] : null;
  const detalhe = card.querySelector(".detalhe");
  if (antes) {
    const var12 = (serie[i] / antes - 1) * 100;
    const sinal = var12 > 0 ? "+" : "";
    detalhe.textContent = `${sinal}${fmtNumero(var12, 1)}% em 12 meses (${mes})`;
  } else {
    detalhe.textContent = `Referente a ${mes}`;
  }
}

// ---------- controles ----------
function combMontarControles() {
  const { json } = comb;

  // Estado
  const select = document.getElementById("comb-uf");
  select.innerHTML = "";
  const opcaoBR = new Option("Brasil (média nacional)", "BR");
  select.add(opcaoBR);
  json.estados
    .map((e) => e.sigla)
    .sort((a, b) => (NOMES_UF[a] || a).localeCompare(NOMES_UF[b] || b, "pt-BR"))
    .forEach((sigla) => select.add(new Option(NOMES_UF[sigla] || sigla, sigla)));
  select.value = comb.uf;
  select.addEventListener("change", () => {
    comb.uf = select.value;
    combAtualizar();
  });

  // Período
  const primeiro = json.meses[0];
  const ultimo = json.meses[json.meses.length - 1];
  comb.de = primeiro;
  comb.ate = ultimo;
  const inputDe = document.getElementById("comb-de");
  const inputAte = document.getElementById("comb-ate");
  for (const input of [inputDe, inputAte]) {
    input.min = primeiro;
    input.max = ultimo;
  }
  inputDe.value = comb.de;
  inputAte.value = comb.ate;

  const aoMudarPeriodo = () => {
    const erro = document.getElementById("erro-comb");
    const de = inputDe.value;
    const ate = inputAte.value;
    if (!combMesValido(de) || !combMesValido(ate) || de > ate) {
      erro.textContent = "Período inválido: use meses no formato AAAA-MM, com 'De' anterior a 'Até'.";
      erro.hidden = false;
      return;
    }
    erro.hidden = true;
    comb.de = de < primeiro ? primeiro : de;
    comb.ate = ate > ultimo ? ultimo : ate;
    combMarcarAtalho(null);
    combAtualizar();
  };
  inputDe.addEventListener("change", aoMudarPeriodo);
  inputAte.addEventListener("change", aoMudarPeriodo);

  // Atalhos (relativos ao último mês disponível)
  document.querySelectorAll("#comb-atalhos button").forEach((botao) => {
    botao.addEventListener("click", () => {
      const n = Number(botao.dataset.meses);
      comb.ate = ultimo;
      comb.de = n === 0 ? primeiro : combSomarMeses(ultimo, -(n - 1));
      if (comb.de < primeiro) comb.de = primeiro;
      inputDe.value = comb.de;
      inputAte.value = comb.ate;
      document.getElementById("erro-comb").hidden = true;
      combMarcarAtalho(botao);
      combAtualizar();
    });
  });

  // Tipos de combustível (chips)
  const area = document.getElementById("comb-produtos");
  area.innerHTML = "";
  json.produtos.forEach((p) => {
    const botao = document.createElement("button");
    botao.type = "button";
    botao.className = "chip";
    botao.dataset.id = p.id;
    botao.setAttribute("aria-pressed", String(comb.selecionados.has(p.id)));
    const bolinha = document.createElement("span");
    bolinha.className = "bolinha";
    bolinha.style.background = COMB_CORES[p.id] || COMB_COR_PADRAO;
    botao.append(bolinha, document.createTextNode(p.nome));
    botao.addEventListener("click", () => {
      if (comb.selecionados.has(p.id)) {
        if (comb.selecionados.size === 1) return; // mantém pelo menos um
        comb.selecionados.delete(p.id);
      } else {
        comb.selecionados.add(p.id);
      }
      botao.setAttribute("aria-pressed", String(comb.selecionados.has(p.id)));
      combAtualizar();
    });
    area.append(botao);
  });
}

function combMarcarAtalho(ativo) {
  document
    .querySelectorAll("#comb-atalhos button")
    .forEach((b) => b.classList.toggle("ativo", b === ativo));
}

// ---------- gráfico ----------
function combDatasets() {
  const { json } = comb;
  const [i0, i1] = combIndices();
  const datasets = [];
  for (const produto of json.produtos) {
    if (!comb.selecionados.has(produto.id)) continue;
    const serie = combSerie(produto.id);
    const cor = COMB_CORES[produto.id] || COMB_COR_PADRAO;
    const pontos = [];
    if (serie) {
      for (let i = i0; i <= i1; i++) pontos.push({ x: json.meses[i] + "-01", y: serie[i] });
    }
    const temDado = pontos.some((p) => p.y !== null);
    datasets.push({
      label: temDado ? produto.nome : `${produto.nome} (sem dados)`,
      produtoId: produto.id,
      unidade: produto.unidade,
      data: temDado ? pontos : [],
      borderColor: cor,
      backgroundColor: cor,
      borderWidth: 2,
      pointRadius: 0,
      pointHoverRadius: 4,
      tension: 0,
      spanGaps: true, // liga a linha por cima de meses sem coleta
    });
  }
  return datasets;
}

function combCriarGrafico() {
  const ctx = document.getElementById("grafico-comb");
  comb.grafico = new Chart(ctx, {
    type: "line",
    data: { datasets: combDatasets() },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      interaction: { mode: "index", intersect: false },
      scales: {
        x: {
          type: "time",
          grid: { color: css("--grade") },
          ticks: {
            color: css("--suave"),
            maxRotation: 0,
            autoSkip: true,
            callback: function (valor) {
              const d = new Date(valor);
              const span = this.max - this.min;
              const tresAnos = 3 * 365 * 24 * 3600 * 1000;
              return span <= tresAnos
                ? `${MESES_ABREV[d.getMonth()]}/${String(d.getFullYear()).slice(2)}`
                : String(d.getFullYear());
            },
          },
        },
        y: {
          grid: { color: css("--grade") },
          ticks: {
            color: css("--suave"),
            callback: (v) => "R$ " + fmtNumero(v, 2),
          },
        },
      },
      plugins: {
        legend: {
          position: "bottom",
          onClick: () => {}, // a seleção é feita pelos botões acima
          labels: { color: css("--texto"), usePointStyle: true, boxWidth: 8 },
        },
        tooltip: {
          callbacks: {
            title: (itens) => {
              const iso = new Date(itens[0].parsed.x).toISOString().slice(0, 10);
              return fmtMes(iso);
            },
            label: (item) => {
              const ds = item.dataset;
              return ` ${ds.label}: R$ ${fmtNumero(item.parsed.y, 2)}/${ds.unidade}`;
            },
          },
        },
      },
    },
  });
}

function combAtualizar() {
  if (!comb.grafico) return;
  comb.grafico.data.datasets = combDatasets();
  comb.grafico.update();

  const nome = comb.uf === "BR" ? "Brasil" : NOMES_UF[comb.uf] || comb.uf;
  document.getElementById("comb-uf").setAttribute("aria-label", `Estado: ${nome}`);
}

function combAplicarTema() {
  if (!comb.grafico) return;
  const o = comb.grafico.options;
  o.scales.x.grid.color = css("--grade");
  o.scales.y.grid.color = css("--grade");
  o.scales.x.ticks.color = css("--suave");
  o.scales.y.ticks.color = css("--suave");
  o.plugins.legend.labels.color = css("--texto");
  comb.grafico.update();
}

// ---------- início ----------
async function combIniciar() {
  const erro = document.getElementById("erro-comb");
  try {
    const resp = await fetch(COMB_ARQUIVO, { cache: "no-cache" });
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const json = await resp.json();
    if (!json.meses || !json.meses.length) throw new Error("arquivo vazio");
    comb.json = json;

    document.getElementById("fonte-comb").textContent =
      `Fonte: ANP - Levantamento de Preços de Combustíveis. Dados até ${combFmtMesAno(json.ultimo_mes)}.`;

    combPreencherKpi();
    combMontarControles();
    combCriarGrafico();
    window
      .matchMedia("(prefers-color-scheme: dark)")
      .addEventListener("change", combAplicarTema);
  } catch (e) {
    console.error("combustiveis", e);
    erro.textContent = `Não foi possível carregar os dados de combustíveis (${e.message}).`;
    erro.hidden = false;
    const card = document.getElementById("kpi-gasolina");
    card.querySelector(".valor").textContent = "—";
    card.querySelector(".detalhe").textContent = "Dados indisponíveis";
  }
}

combIniciar();
