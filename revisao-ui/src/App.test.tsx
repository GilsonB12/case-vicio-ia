import { readFileSync } from "node:fs";
import { join } from "node:path";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";

// O URL global do jsdom não resolve file://, então o caminho vai por node:path.
const PASTA_EXEMPLO = join(import.meta.dirname, "..", "public", "dados-exemplo");

/** Simula o servidor do Vite: arquivo inexistente vira index.html com status 200. */
function servidor(servirExemplo: boolean) {
  return vi.fn(async (url: string) => {
    const nome = url.replace(/^\/dados-exemplo\//, "");
    if (servirExemplo && url.startsWith("/dados-exemplo/")) {
      const corpo = readFileSync(join(PASTA_EXEMPLO, nome), "utf-8");
      return new Response(corpo, { status: 200, headers: { "content-type": "text/plain; charset=utf-8" } });
    }
    return new Response("<!doctype html><html></html>", { status: 200, headers: { "content-type": "text/html" } });
  });
}

let raiz: Root;
let palco: HTMLDivElement;

beforeEach(() => {
  palco = document.createElement("div");
  document.body.appendChild(palco);
  raiz = createRoot(palco);
});

afterEach(() => {
  raiz.unmount();
  palco.remove();
  vi.unstubAllGlobals();
});

describe("App", () => {
  it("sem dados reais nem de exemplo mostra uma mensagem em vez de tela branca", async () => {
    vi.stubGlobal("fetch", servidor(false));
    raiz.render(<App />);
    await vi.waitFor(() => expect(palco.textContent).toContain("Não encontrei os dados"));
    expect(palco.textContent).toContain("npm run dados");
  });

  it("sem dados reais usa o exemplo, avisa e mostra a fila de revisar", async () => {
    vi.stubGlobal("fetch", servidor(true));
    raiz.render(<App />);
    await vi.waitFor(() => expect(palco.textContent).toContain("Usando dados de exemplo"));
    expect(palco.querySelectorAll(".fila li")).toHaveLength(4);
    expect(palco.textContent).toContain("0 de 4 revisadas");

    const confirmar = [...palco.querySelectorAll("button")].find((b) => b.textContent === "Confirmar");
    confirmar?.click();
    await vi.waitFor(() => expect(palco.textContent).toContain("1 de 4 revisadas"));
  });

  it("a lista de troca só tem temas publicáveis, inclusive na busca", async () => {
    vi.stubGlobal("fetch", servidor(true));
    raiz.render(<App />);
    await vi.waitFor(() => expect(palco.querySelector("select.troca")).not.toBeNull());
    const opcoes = () =>
      [...palco.querySelectorAll<HTMLOptionElement>("select.troca option")].map((o) => o.value).filter((v) => v !== "");
    expect(opcoes().length).toBeGreaterThan(0);

    const busca = palco.querySelector<HTMLInputElement>("input.busca-tema")!;
    const digitar = (texto: string) => {
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(busca, texto);
      busca.dispatchEvent(new Event("input", { bubbles: true }));
    };

    // 4704 é publicável; 6724 é a duplicata sem descrição com o mesmo título.
    digitar("maria da penha");
    await vi.waitFor(() => expect(opcoes()).toContain("4704"));
    expect(opcoes()).not.toContain("6724");

    // 5078 é inativo e 5062 é a raiz "Penal".
    digitar("penal economico");
    await vi.waitFor(() => expect(opcoes()).not.toContain("4704"));
    expect(opcoes()).not.toContain("5078");
    digitar("penal");
    await vi.waitFor(() => expect(opcoes().length).toBeGreaterThan(5));
    expect(opcoes()).not.toContain("5062");
  });
});
