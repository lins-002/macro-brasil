// Macro Brasil - lógica da página.
// Lê os JSONs gerados por scripts/atualizar_dados.py (em docs/data/)
// e desenha os gráficos com Chart.js.
//
// Para adicionar um novo indicador: inclua um item em INDICADORES,
// um <canvas id="grafico-ID"> e um card <article id="kpi-ID"> no index.html.

// Campos de cada indicador:
//  granularidade: "mes" ou "dia" (formato da data no KPI e no balão)
//  prefixo/sufixo: "R$ " / "%" ao redor do número
//  casas: casas decimais no KPI e no balão; casasEixo: no eixo vertical
//  delta: "pct" (variação em %) ou "pp" (diferença em pontos) ou null
//  rotuloBalao: texto depois do número no balão
const INDICADORES = [
  {
    id: "ipca", arquivo: "data/ipca.json", corVar: "--azul",
    escalonado: false, granularidade: "mes",
    prefixo: "", sufixo: "%", casas: 2, casasEixo: 0, delta: null,
    rotuloBalao: " ao ano",
  },
  {
    id: "selic", arquivo: "data/selic.json", corVar: "--laranja",
    escalonado: true, // degraus: o valor vale até a próxima mudança
    granularidade: "dia",
    prefixo: "", sufixo: "%", casas: 2, casasEixo: 0, delta: null,
    rotuloBalao: " ao ano",
  },
  {
    id: "dolar", arquivo: "data/dolar.json", corVar: "--verde",
    escalonado: false, granularidade: "dia",
    prefixo: "R$ ", sufixo: "", casas: 2, casasEixo: 1, delta: "pct",
    rotuloBalao: "", textoDetalhe: "Venda em ",
  },
  {
    id: "desemprego", arquivo: "data/desemprego.json", corVar: "--vermelho",
    escalonado: false, granularidade: "mes",
    prefixo: "", sufixo: "%", casas: 1, casasEixo: 0, delta: "pp",
    rotuloBalao: " da força de trabalho",
  },
  {
    id: "ibcbr", arquivo: "data/ibcbr.json", corVar: "--roxo",
    escalonado: false, granularidade: "mes",
    prefixo: "", sufixo: "", casas: 1, casasEixo: 0, delta: "pct",
    rotuloBalao: " pontos",
  },
  {
    id: "divida_bruta", arquivo: "data/divida_bruta.json", corVar: "--ciano",
    // Gráfico combinado: colunas com o saldo em R$ (eixo esquerdo, em trilhões)
    // e linha com o % do PIB (eixo direito).
    arquivoValor: "data/divida_bruta_valor.json", corVar2: "--laranja",
    escalonado: false, granularidade: "mes",
    prefixo: "", sufixo: "%", casas: 1, casasEixo: 0, delta: "pp",
    rotuloBalao: " do PIB",
  },
];

const estado = {
  anos: 20, // período selecionado (0 = tudo)
  graficos: {}, // id -> instância do Chart
  dados: {}, // id -> conteúdo do JSON
};

// ---------- utilitários ----------
const css = (nome) =>
  getComputedStyle(document.documentElement).getPropertyValue(nome).trim();

const fmtNumero = (v, casas) =>
  v.toLocaleString("pt-BR", {
    minimumFractionDigits: casas,
    maximumFractionDigits: casas,
  });

// "2024-05-01" -> Date local (evita deslocamento de fuso horário)
const paraData = (iso) => new Date(iso + "T00:00:00");

const fmtDia = (iso) => paraData(iso).toLocaleDateString("pt-BR");
const fmtMes = (iso) =>
  paraData(iso).toLocaleDateString("pt-BR", { month: "long", year: "numeric" });

// ---------- KPIs ----------
function ultimaMudanca(dados) {
  for (let i = dados.length - 1; i > 0; i--) {
    if (dados[i].valor !== dados[i - 1].valor) return dados[i];
  }
  return dados[0];
}

function textoDelta(ind, json) {
  const d = json.dados;
  if (!ind.delta || d.length < 2) return "";
  const atual = d[d.length - 1].valor;
  const antes = d[d.length - 2].valor;
  let dif;
  let unidade;
  if (ind.delta === "pct") {
    dif = ((atual - antes) / antes) * 100;
    unidade = "%";
  } else {
    dif = atual - antes;
    unidade = " p.p.";
  }
  const sinal = dif > 0 ? "+" : dif < 0 ? "−" : "";
  return ` (${sinal}${fmtNumero(Math.abs(dif), 2)}${unidade})`;
}

function preencherKpi(ind, json, extra) {
  const card = document.getElementById(`kpi-${ind.id}`);
  const ultimo = json.dados[json.dados.length - 1];
  card.querySelector(".valor").textContent =
    ind.prefixo + fmtNumero(ultimo.valor, ind.casas) + ind.sufixo;

  const detalhe = card.querySelector(".detalhe");
  if (ind.id === "selic") {
    detalhe.textContent = "Última mudança em " + fmtDia(ultimaMudanca(json.dados).data);
  } else if (ind.granularidade === "dia") {
    detalhe.textContent =
      (ind.textoDetalhe || "Em ") + fmtDia(ultimo.data) + textoDelta(ind, json);
  } else {
    let texto = "Referente a " + fmtMes(ultimo.data) + textoDelta(ind, json);
    const par = extra && extra.dados.find((d) => d.data === ultimo.data);
    if (par) texto += ` · R$ ${fmtNumero(par.valor / 1e6, 2)} tri`;
    detalhe.textContent = texto;
  }
}

function mostrarErro(ind, msg) {
  const el = document.getElementById(`erro-${ind.id}`);
  el.textContent = msg;
  el.hidden = false;
  const card = document.getElementById(`kpi-${ind.id}`);
  card.querySelector(".valor").textContent = "—";
  card.querySelector(".detalhe").textContent = "Dados indisponíveis";
}

// ---------- gráficos ----------
function limiteInferior(json) {
  if (!estado.anos) return undefined;
  const ultimo = paraData(json.dados[json.dados.length - 1].data);
  ultimo.setFullYear(ultimo.getFullYear() - estado.anos);
  return ultimo.getTime();
}

function criarGrafico(ind, json, extra) {
  const cor = css(ind.corVar);
  const ctx = document.getElementById(`grafico-${ind.id}`);

  const pontos = json.dados.map((d) => ({ x: d.data, y: d.valor }));
  if (ind.escalonado) {
    // O JSON guarda só as mudanças; estende o último valor até hoje.
    const hoje = new Date().toISOString().slice(0, 10);
    const ultimo = pontos[pontos.length - 1];
    if (ultimo.x < hoje) pontos.push({ x: hoje, y: ultimo.y });
  }

  const fmtValor = (v) => `${ind.prefixo}${fmtNumero(v, ind.casas)}${ind.sufixo}${ind.rotuloBalao}`;
  let datasets = [
    {
      label: json.nome,
      data: pontos,
      borderColor: cor,
      backgroundColor: cor,
      borderWidth: 2,
      pointRadius: 0,
      pointHoverRadius: 4,
      stepped: ind.escalonado ? "before" : false,
      tension: 0,
      rotulo: fmtValor,
    },
  ];
  const escalas = {};
  if (extra) {
    // Colunas (R$ trilhões, eixo esquerdo) + linha (% do PIB, eixo direito).
    const cor2 = css(ind.corVar2);
    datasets = [
      {
        type: "bar",
        label: "Saldo da dívida (R$ trilhões)",
        data: extra.dados.map((d) => ({ x: d.data, y: d.valor / 1e6 })),
        backgroundColor: cor + "cc",
        borderColor: cor,
        borderWidth: 0,
        yAxisID: "y",
        order: 2,
        rotulo: (v) => `Saldo: R$ ${fmtNumero(v, 2)} tri`,
      },
      {
        type: "line",
        label: "% do PIB",
        data: pontos,
        borderColor: cor2,
        backgroundColor: cor2,
        borderWidth: 2,
        pointRadius: 0,
        pointHoverRadius: 4,
        tension: 0,
        yAxisID: "y1",
        order: 1,
        rotulo: (v) => `${fmtNumero(v, ind.casas)}% do PIB`,
      },
    ];
    escalas.y1 = {
      position: "right",
      grid: { drawOnChartArea: false },
      ticks: { color: css("--suave"), callback: (v) => fmtNumero(v, 0) + "%" },
    };
  }

  estado.graficos[ind.id] = new Chart(ctx, {
    type: extra ? "bar" : "line",
    data: { datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      interaction: { mode: "index", intersect: false },
      scales: {
        x: {
          type: "time",
          min: limiteInferior(json),
          time: { unit: "year" },
          grid: { color: css("--grade") },
          ticks: {
            color: css("--suave"),
            maxRotation: 0,
            autoSkip: true,
            callback: function (valor) {
              const d = new Date(valor);
              const span = this.max - this.min;
              const seisAnos = 6 * 365 * 24 * 3600 * 1000;
              return span <= seisAnos
                ? d.toLocaleDateString("pt-BR", { month: "short", year: "2-digit" })
                : String(d.getFullYear());
            },
          },
        },
        y: {
          position: "left",
          grid: { color: css("--grade") },
          ticks: {
            color: css("--suave"),
            callback: extra
              ? (v) => "R$ " + fmtNumero(v, 0) + " tri"
              : (v) => ind.prefixo + fmtNumero(v, ind.casasEixo) + ind.sufixo,
          },
          ...(extra ? { beginAtZero: true } : {}),
        },
        ...escalas,
      },
      plugins: {
        legend: { display: !!extra, labels: { color: css("--suave"), boxWidth: 12 } },
        tooltip: {
          callbacks: {
            title: (itens) => {
              const iso = new Date(itens[0].parsed.x).toISOString().slice(0, 10);
              return ind.granularidade === "dia" ? fmtDia(iso) : fmtMes(iso);
            },
            label: (item) => " " + item.dataset.rotulo(item.parsed.y),
          },
        },
      },
    },
  });
}

function aplicarPeriodo() {
  for (const ind of INDICADORES) {
    const grafico = estado.graficos[ind.id];
    if (!grafico) continue;
    grafico.options.scales.x.min = limiteInferior(estado.dados[ind.id]);
    grafico.update();
  }
}

// Recolore os gráficos quando o tema claro/escuro do sistema muda.
function aplicarTema() {
  for (const ind of INDICADORES) {
    const grafico = estado.graficos[ind.id];
    if (!grafico) continue;
    const cor = css(ind.corVar);
    const dss = grafico.data.datasets;
    if (dss.length > 1) {
      const cor2 = css(ind.corVar2);
      dss[0].backgroundColor = cor + "cc";
      dss[0].borderColor = cor;
      dss[1].borderColor = cor2;
      dss[1].backgroundColor = cor2;
      grafico.options.scales.y1.ticks.color = css("--suave");
      grafico.options.plugins.legend.labels.color = css("--suave");
    } else {
      dss[0].borderColor = cor;
      dss[0].backgroundColor = cor;
    }
    grafico.options.scales.x.grid.color = css("--grade");
    grafico.options.scales.y.grid.color = css("--grade");
    grafico.options.scales.x.ticks.color = css("--suave");
    grafico.options.scales.y.ticks.color = css("--suave");
    grafico.update();
  }
}

// ---------- carga dos dados ----------
async function carregar(ind) {
  try {
    const resp = await fetch(ind.arquivo, { cache: "no-cache" });
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const json = await resp.json();
    if (!json.dados || json.dados.length === 0) throw new Error("arquivo vazio");
    // Dados extras (opcionais): se falharem, o gráfico sai só com a linha.
    let extra = null;
    if (ind.arquivoValor) {
      try {
        const r2 = await fetch(ind.arquivoValor, { cache: "no-cache" });
        if (r2.ok) {
          const j2 = await r2.json();
          if (j2.dados && j2.dados.length) extra = j2;
        }
      } catch (e) {
        console.warn(ind.id, "série extra indisponível", e);
      }
    }
    estado.dados[ind.id] = json;
    estado.dadosExtra = estado.dadosExtra || {};
    if (extra) estado.dadosExtra[ind.id] = extra;
    preencherKpi(ind, json, extra);
    criarGrafico(ind, json, extra);
    return json;
  } catch (erro) {
    console.error(ind.id, erro);
    mostrarErro(ind, `Não foi possível carregar os dados (${erro.message}).`);
    return null;
  }
}

function configurarBotoes() {
  const botoes = document.querySelectorAll(".controles button");
  botoes.forEach((botao) => {
    botao.addEventListener("click", () => {
      estado.anos = Number(botao.dataset.anos);
      botoes.forEach((b) => b.classList.toggle("ativo", b === botao));
      aplicarPeriodo();
    });
  });
}

// ---------- Boletim Focus (tabela) ----------
function fmtSeta(atual, anterior) {
  if (anterior === null || anterior === undefined) return "";
  const dif = atual - anterior;
  if (Math.abs(dif) < 0.005) return '<span class="tend igual" title="Igual a 4 semanas antes">=</span>';
  const sobe = dif > 0;
  const txt = `${sobe ? "+" : "−"}${fmtNumero(Math.abs(dif), 2)}`;
  return `<span class="tend ${sobe ? "sobe" : "desce"}" title="Há 4 semanas: ${fmtNumero(anterior, 2)}">${sobe ? "▲" : "▼"} ${txt}</span>`;
}

async function carregarFocus() {
  const erro = document.getElementById("erro-focus");
  try {
    const resp = await fetch("data/focus.json", { cache: "no-cache" });
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const json = await resp.json();
    if (!json.indicadores || !json.indicadores.length) throw new Error("arquivo vazio");

    const cabecalho = document.querySelector("#tabela-focus thead");
    cabecalho.innerHTML =
      "<tr><th>Indicador</th>" +
      json.anos.map((a) => `<th>Em ${a}</th>`).join("") +
      "</tr>";

    const corpo = document.querySelector("#tabela-focus tbody");
    corpo.innerHTML = "";
    for (const ind of json.indicadores) {
      const tr = document.createElement("tr");
      const prefixo = ind.unidade === "R$" ? "R$ " : "";
      const sufixo = ind.unidade === "%" ? "%" : "";
      let html = `<td>${ind.nome}</td>`;
      for (const ano of json.anos) {
        const v = ind.valores[String(ano)];
        html += v
          ? `<td>${prefixo}${fmtNumero(v.mediana, ind.casas)}${sufixo}${fmtSeta(v.mediana, v.anterior)}</td>`
          : "<td>—</td>";
      }
      tr.innerHTML = html;
      corpo.appendChild(tr);
    }
    if (json.data_pesquisa) {
      document.getElementById("fonte-focus").textContent =
        `Fonte: Banco Central - Expectativas de Mercado (mediana). Pesquisa de ${fmtDia(json.data_pesquisa)}.`;
    }
    return json;
  } catch (e) {
    console.error("focus", e);
    erro.textContent = `Não foi possível carregar o Focus (${e.message}).`;
    erro.hidden = false;
    return null;
  }
}

async function iniciar() {
  configurarBotoes();
  const [resultados] = await Promise.all([
    Promise.all(INDICADORES.map(carregar)),
    carregarFocus(),
  ]);

  const datas = resultados
    .filter(Boolean)
    .map((j) => j.atualizado_em)
    .filter(Boolean)
    .sort();
  if (datas.length) {
    const quando = new Date(datas[datas.length - 1]).toLocaleString("pt-BR");
    document.getElementById("atualizado").textContent =
      `Última mudança nos dados: ${quando}.`;
  }

  // Data da última coleta automática bem-sucedida (arquivo opcional).
  try {
    const resp = await fetch("data/status.json", { cache: "no-cache" });
    if (resp.ok) {
      const status = await resp.json();
      if (status.verificado_em) {
        const quando = new Date(status.verificado_em).toLocaleString("pt-BR");
        document.getElementById("verificado").textContent =
          `Última verificação automática: ${quando}.`;
      }
    }
  } catch (erro) {
    console.warn("status.json indisponível", erro);
  }

  window
    .matchMedia("(prefers-color-scheme: dark)")
    .addEventListener("change", aplicarTema);
}

iniciar();
