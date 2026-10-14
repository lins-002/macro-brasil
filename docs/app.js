// Macro Brasil - lógica da página.
// Lê os JSONs gerados por scripts/atualizar_dados.py (em docs/data/)
// e desenha os gráficos com Chart.js.
//
// Para adicionar um novo indicador (Etapa 5): inclua um item em INDICADORES,
// um <canvas> e um card de KPI no index.html.

const INDICADORES = [
  {
    id: "ipca",
    arquivo: "data/ipca.json",
    corVar: "--azul",
    escalonado: false, // linha normal (série mensal)
    sufixo: "%",
    casas: 2,
  },
  {
    id: "selic",
    arquivo: "data/selic.json",
    corVar: "--laranja",
    escalonado: true, // degraus: o valor vale até a próxima mudança
    sufixo: "%",
    casas: 2,
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

function preencherKpi(ind, json) {
  const card = document.getElementById(`kpi-${ind.id}`);
  const ultimo = json.dados[json.dados.length - 1];
  card.querySelector(".valor").textContent =
    fmtNumero(ultimo.valor, ind.casas) + ind.sufixo;

  const detalhe = card.querySelector(".detalhe");
  if (ind.id === "selic") {
    detalhe.textContent = "Última mudança em " + fmtDia(ultimaMudanca(json.dados).data);
  } else {
    detalhe.textContent = "Referente a " + fmtMes(ultimo.data);
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

function criarGrafico(ind, json) {
  const cor = css(ind.corVar);
  const ctx = document.getElementById(`grafico-${ind.id}`);

  const pontos = json.dados.map((d) => ({ x: d.data, y: d.valor }));
  if (ind.escalonado) {
    // O JSON guarda só as mudanças; estende o último valor até hoje.
    const hoje = new Date().toISOString().slice(0, 10);
    const ultimo = pontos[pontos.length - 1];
    if (ultimo.x < hoje) pontos.push({ x: hoje, y: ultimo.y });
  }

  estado.graficos[ind.id] = new Chart(ctx, {
    type: "line",
    data: {
      datasets: [
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
        },
      ],
    },
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
          grid: { color: css("--grade") },
          ticks: {
            color: css("--suave"),
            callback: (v) => fmtNumero(v, 0) + ind.sufixo,
          },
        },
      },
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            title: (itens) => {
              const iso = new Date(itens[0].parsed.x).toISOString().slice(0, 10);
              return ind.escalonado ? fmtDia(iso) : fmtMes(iso);
            },
            label: (item) =>
              ` ${fmtNumero(item.parsed.y, ind.casas)}${ind.sufixo} ao ano`,
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
    const ds = grafico.data.datasets[0];
    ds.borderColor = cor;
    ds.backgroundColor = cor;
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
    estado.dados[ind.id] = json;
    preencherKpi(ind, json);
    criarGrafico(ind, json);
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

async function iniciar() {
  configurarBotoes();
  const resultados = await Promise.all(INDICADORES.map(carregar));

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
