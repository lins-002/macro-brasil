// Macro Brasil - PIB (IBGE, Contas Nacionais Trimestrais).
// Lê docs/data/pib.json e desenha dois gráficos:
//  1) trimestral: colunas = variação sobre o trimestre anterior (com ajuste
//     sazonal); linha = variação sobre o mesmo trimestre do ano anterior;
//  2) anual: crescimento de cada ano. O ano em andamento aparece com asterisco
//     (ex.: "2026*") e mostra o acumulado até o último trimestre divulgado.
// Usa funções de app.js: css(), fmtNumero(), estado (período escolhido).

const PIB = { json: null, graficos: {} };

const pibFmtPct = (v, casas = 1) =>
  (v > 0 ? "+" : v < 0 ? "−" : "") + fmtNumero(Math.abs(v), casas) + "%";

const pibNomeTri = (tri, ano) => `${tri}º trimestre de ${ano}`;

// Último ponto que tem valor no campo pedido.
function pibUltimo(lista, campo) {
  for (let i = lista.length - 1; i >= 0; i--) if (lista[i][campo] != null) return lista[i];
  return null;
}

function pibErro(id, msg) {
  const el = document.getElementById(`erro-${id}`);
  if (el) {
    el.textContent = msg;
    el.hidden = false;
  }
}

function pibPreencherKpi(json) {
  const card = document.getElementById("kpi-pib");
  if (!card) return;
  const u = pibUltimo(json.trimestral, "qoq");
  if (!u) return;
  card.querySelector(".valor").textContent = pibFmtPct(u.qoq);
  const partes = [`${pibNomeTri(u.tri, u.ano)}, contra o trimestre anterior`];
  if (u.yoy != null) partes.push(`${pibFmtPct(u.yoy)} em 12 meses`);
  card.querySelector(".detalhe").textContent = partes.join(" · ");
}

// Quantos trimestres/anos mostrar, conforme os botões de período da página.
function pibRecortar(lista, porAno) {
  const anos = estado.anos; // 0 = tudo
  if (!anos) return lista;
  return lista.slice(-(porAno ? anos : anos * 4));
}

function pibOpcoesBase(rotuloY) {
  return {
    responsive: true,
    maintainAspectRatio: false,
    animation: false,
    interaction: { mode: "index", intersect: false },
    scales: {
      x: {
        grid: { display: false },
        ticks: { color: css("--suave"), maxRotation: 0, autoSkip: true },
      },
      y: {
        grid: { color: css("--grade") },
        ticks: { color: css("--suave"), callback: (v) => fmtNumero(v, 0) + "%" },
        title: { display: !!rotuloY, text: rotuloY, color: css("--suave") },
      },
    },
  };
}

function pibDesenharTrimestral(json) {
  const ctx = document.getElementById("grafico-pib-tri");
  if (!ctx) return;
  if (PIB.graficos.tri) PIB.graficos.tri.destroy();
  const dados = pibRecortar(json.trimestral, false);
  const cor = css("--azul");
  const neg = css("--vermelho");
  const linha = css("--laranja");
  const rotulos = dados.map((d) => `${d.tri}T${String(d.ano).slice(2)}`);

  const opcoes = pibOpcoesBase("");
  opcoes.plugins = {
    legend: { display: true, labels: { color: css("--suave"), boxWidth: 12 } },
    tooltip: {
      callbacks: {
        title: (itens) => {
          const d = dados[itens[0].dataIndex];
          return pibNomeTri(d.tri, d.ano);
        },
        label: (item) =>
          ` ${item.dataset.label}: ${item.parsed.y == null ? "—" : pibFmtPct(item.parsed.y)}`,
      },
    },
  };
  PIB.graficos.tri = new Chart(ctx, {
    type: "bar",
    data: {
      labels: rotulos,
      datasets: [
        {
          type: "bar",
          label: "Contra o trimestre anterior",
          data: dados.map((d) => d.qoq),
          backgroundColor: dados.map((d) => (d.qoq != null && d.qoq < 0 ? neg : cor)),
          order: 2,
        },
        {
          type: "line",
          label: "Contra o mesmo trimestre do ano anterior",
          data: dados.map((d) => d.yoy),
          borderColor: linha,
          backgroundColor: linha,
          borderWidth: 2,
          pointRadius: 0,
          pointHoverRadius: 4,
          tension: 0,
          spanGaps: true,
          order: 1,
        },
      ],
    },
    options: opcoes,
  });
}

function pibDesenharAnual(json) {
  const ctx = document.getElementById("grafico-pib-ano");
  if (!ctx) return;
  if (PIB.graficos.ano) PIB.graficos.ano.destroy();
  const dados = pibRecortar(json.anual, true);
  const cor = css("--azul");
  const neg = css("--vermelho");
  const rotulos = dados.map((d) => (d.parcial ? `${d.ano}*` : String(d.ano)));
  // O ano em andamento fica mais claro, para não ser confundido com um ano fechado.
  const cores = dados.map((d) => {
    const base = d.valor < 0 ? neg : cor;
    return d.parcial ? base + "88" : base;
  });

  const opcoes = pibOpcoesBase("");
  opcoes.plugins = {
    legend: { display: false },
    tooltip: {
      callbacks: {
        title: (itens) => {
          const d = dados[itens[0].dataIndex];
          return d.parcial ? `${d.ano}* (parcial)` : String(d.ano);
        },
        label: (item) => {
          const d = dados[item.dataIndex];
          return d.parcial
            ? ` ${pibFmtPct(d.valor)} acumulado até o ${d.ate_trimestre}º trimestre`
            : ` ${pibFmtPct(d.valor)} no ano`;
        },
      },
    },
  };
  PIB.graficos.ano = new Chart(ctx, {
    type: "bar",
    data: { labels: rotulos, datasets: [{ label: "PIB", data: dados.map((d) => d.valor), backgroundColor: cores }] },
    options: opcoes,
  });

  // Nota explicando o asterisco (só aparece se houver ano em andamento).
  const nota = document.getElementById("nota-pib-ano");
  const parcial = json.anual.find((d) => d.parcial);
  if (nota) {
    nota.textContent = parcial
      ? `* ${parcial.ano} ainda está em andamento: o valor é o acumulado até o ${parcial.ate_trimestre}º trimestre, ` +
        `em relação ao mesmo período de ${parcial.ano - 1}. Vira definitivo quando o 4º trimestre for divulgado.`
      : "";
  }
}

function pibDesenhar() {
  if (!PIB.json) return;
  pibDesenharTrimestral(PIB.json);
  pibDesenharAnual(PIB.json);
}

async function pibIniciar() {
  try {
    const resp = await fetch("data/pib.json", { cache: "no-cache" });
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const json = await resp.json();
    if (!json.trimestral || !json.trimestral.length || !json.anual || !json.anual.length) {
      throw new Error("arquivo vazio");
    }
    PIB.json = json;
    pibPreencherKpi(json);
    pibDesenhar();
    const fonte = document.getElementById("fonte-pib-tri");
    const u = pibUltimo(json.trimestral, "qoq");
    if (fonte && u) {
      fonte.textContent =
        `Variação real do PIB (volume). Fonte: IBGE. Último dado: ${pibNomeTri(u.tri, u.ano)}.`;
    }
  } catch (erro) {
    console.error("pib", erro);
    const msg = `Não foi possível carregar o PIB (${erro.message}).`;
    pibErro("pib-tri", msg);
    pibErro("pib-ano", msg);
    const card = document.getElementById("kpi-pib");
    if (card) {
      card.querySelector(".valor").textContent = "—";
      card.querySelector(".detalhe").textContent = "Dados indisponíveis";
    }
  }
}

// Os botões de período (5, 10, 20 anos, Tudo) valem também para o PIB.
// O app.js atualiza estado.anos primeiro; este ouvinte roda depois.
document.querySelectorAll(".controles button").forEach((botao) => {
  botao.addEventListener("click", pibDesenhar);
});
// Recolore quando o tema claro/escuro do sistema muda.
window
  .matchMedia("(prefers-color-scheme: dark)")
  .addEventListener("change", pibDesenhar);

pibIniciar();
