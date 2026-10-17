// Pulso Macro - navegação por seções (abas no menu horizontal).
// Cada seção é um <section id="sec-NOME">; o endereço #NOME abre a seção
// (o botão "voltar" do navegador e links diretos funcionam).

const SECOES = ["juros", "macro", "combustiveis", "breve"];
const SECOES_COM_PERIODO = ["juros", "macro"]; // as que usam os botões de período
const TITULOS = {
  juros: "Juros e inflação",
  macro: "Macroeconomia",
  combustiveis: "Combustíveis",
  breve: "Outras categorias",
};

function secaoAtual() {
  const id = location.hash.replace("#", "");
  return SECOES.includes(id) ? id : "juros";
}

function mostrarSecao() {
  const atual = secaoAtual();
  for (const id of SECOES) {
    document.getElementById(`sec-${id}`).hidden = id !== atual;
  }
  document.querySelectorAll(".aba").forEach((a) => {
    const ativa = a.dataset.secao === atual;
    a.classList.toggle("ativa", ativa);
    if (ativa) a.setAttribute("aria-current", "page");
    else a.removeAttribute("aria-current");
  });
  document.getElementById("barra-periodo").hidden = !SECOES_COM_PERIODO.includes(atual);
  document.title = `${TITULOS[atual]} - Pulso Macro`;
  window.scrollTo(0, 0);
  // Gráficos desenhados enquanto a seção estava escondida precisam se ajustar.
  requestAnimationFrame(() => {
    if (window.Chart && Chart.instances) {
      Object.values(Chart.instances).forEach((g) => g.resize());
    }
  });
}

window.addEventListener("hashchange", mostrarSecao);
mostrarSecao();
