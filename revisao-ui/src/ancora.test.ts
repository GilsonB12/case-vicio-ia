import { readFileSync } from "node:fs";
import { join } from "node:path";
import Papa from "papaparse";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  CHAVE_DECISOES,
  carregarAncora,
  concordam,
  lerAncora,
  lerDecisoesSalvas,
  lerRotulos,
  montarCsvAncora,
  normalizarDecisoes,
  opcoesAncora,
  salvarDecisoes,
  TEMA_FORA,
} from "./ancora";
import { lerTemas, temasPublicaveis, type Buscador } from "./dados";
import type { Rotulo } from "./tipos";

const BOM = String.fromCharCode(0xfeff);

// Duas linhas no formato de data/ancora_para_rotular.csv: `;`, BOM, CRLF entre registros e texto com quebras de linha.
const ANCORA_CSV =
  BOM +
  "id;disciplina_origem;texto;candidatos;tema_id_gilson;observacao\r\n" +
  'Q0009;Direito Penal;"“Ariel”, com 21 anos, arromba a joalheria; leva R$ 5.000,00. Responderá por:\n' +
  "Comando: Assinale a alternativa correta.\n" +
  "Alternativas:\n" +
  "A) furto de coisa comum.\n" +
  'B) furto qualificado.";consulte docs/projeto/arvore-temas.md;;\r\n' +
  'Q0013;Processo Penal;"Sobre o juiz das garantias, assinale a alternativa ""EXCETO"":\n' +
  'Alternativas:\nA) Julgar o habeas corpus.";consulte docs/projeto/arvore-temas.md;5503;revisar depois\r\n';

const ROTULOS_JSONL =
  '{"id": "Q0009", "tema_id": 5159, "caminho": "Penal > Dos Crimes Contra o Patrimônio > Furto", "confianca": 0.9, "justificativa": "Subtração com rompimento de obstáculo.", "alternativas_consideradas": [{"tema_id": 5157, "caminho": "Penal > Dos Crimes Contra o Patrimônio", "motivo": "mais genérico"}]}\n' +
  "\n" +
  '{"id": "Q0013", "tema_id": 0, "caminho": "fora da árvore", "confianca": 0.4, "justificativa": "Nenhum tema serve.", "alternativas_consideradas": []}\r\n';

function rotulo(id: string, tema_id: number | null): Rotulo {
  return { id, tema_id, caminho: "", confianca: null, justificativa: "", alternativas: [] };
}

describe("lerAncora", () => {
  it("lê o CSV com ;, BOM e texto em várias linhas", () => {
    const questoes = lerAncora(ANCORA_CSV);
    expect(questoes).toHaveLength(2);
    expect(questoes[0]).toEqual({
      id: "Q0009",
      disciplina_origem: "Direito Penal",
      texto:
        "“Ariel”, com 21 anos, arromba a joalheria; leva R$ 5.000,00. Responderá por:\n" +
        "Comando: Assinale a alternativa correta.\nAlternativas:\nA) furto de coisa comum.\nB) furto qualificado.",
      observacao: "",
    });
    expect(questoes[1].id).toBe("Q0013");
    expect(questoes[1].texto).toBe('Sobre o juiz das garantias, assinale a alternativa "EXCETO":\nAlternativas:\nA) Julgar o habeas corpus.');
    expect(questoes[1].observacao).toBe("revisar depois");
    expect(Object.keys(questoes[1])).not.toContain("tema_id_gilson");
  });

  it("recusa arquivo sem a coluna texto", () => {
    expect(() => lerAncora("id;disciplina_origem\nQ0009;Penal\n")).toThrow(/texto/);
  });

  it("recusa id repetido", () => {
    expect(() => lerAncora("id;texto\nQ0009;a\nQ0009;b\n")).toThrow(/Q0009/);
  });
});

describe("lerRotulos", () => {
  it("indexa por id, lê alternativas e mantém tema_id 0 como fora da árvore", () => {
    const rotulos = lerRotulos(ROTULOS_JSONL);
    expect(rotulos.size).toBe(2);
    expect(rotulos.get("Q0009")).toEqual({
      id: "Q0009",
      tema_id: 5159,
      caminho: "Penal > Dos Crimes Contra o Patrimônio > Furto",
      confianca: 0.9,
      justificativa: "Subtração com rompimento de obstáculo.",
      alternativas: [{ tema_id: 5157, caminho: "Penal > Dos Crimes Contra o Patrimônio", motivo: "mais genérico" }],
    });
    expect(rotulos.get("Q0013")?.tema_id).toBe(TEMA_FORA);
    expect(TEMA_FORA).toBe(0);
    expect(rotulos.get("Q0013")?.alternativas).toEqual([]);
  });

  it("arquivo ausente vira mapa vazio", () => {
    expect(lerRotulos(null).size).toBe(0);
  });

  it("pula linha quebrada e avisa, sem perder as outras", () => {
    const avisos: string[] = [];
    const rotulos = lerRotulos('{"id": "Q0001", "tema_id": 5159}\n{quebrado\n{"tema_id": 1}\n', (aviso) => avisos.push(aviso));
    expect([...rotulos.keys()]).toEqual(["Q0001"]);
    expect(avisos).toHaveLength(2);
    expect(avisos[0]).toMatch(/linha 2/);
  });
});

describe("concordam", () => {
  it("mesmo tema_id concorda", () => {
    expect(concordam(rotulo("Q1", 5159), rotulo("Q1", 5159))).toBe(true);
    expect(concordam(rotulo("Q1", 0), rotulo("Q1", 0))).toBe(true);
  });

  it("tema_id diferente não concorda", () => {
    expect(concordam(rotulo("Q1", 5159), rotulo("Q1", 5160))).toBe(false);
  });

  it("rotulador ausente ou sem tema não concorda", () => {
    expect(concordam(rotulo("Q1", 5159), undefined)).toBe(false);
    expect(concordam(undefined, rotulo("Q1", 5159))).toBe(false);
    expect(concordam(undefined, undefined)).toBe(false);
    expect(concordam(rotulo("Q1", null), rotulo("Q1", null))).toBe(false);
  });
});

describe("montarCsvAncora", () => {
  const LINHAS = [
    { id: "Q0009", tema_id: 5159, observacao: "" },
    { id: "Q0013", tema_id: 5503, observacao: "Juiz das garantias, art. 3º-B;\nnão é inquérito em geral" },
    { id: "Q0077", tema_id: TEMA_FORA, observacao: "Genocídio" },
  ];

  it("começa com BOM e cabeçalho id,tema_id,observacao", () => {
    const csv = montarCsvAncora(LINHAS);
    expect(csv.charCodeAt(0)).toBe(0xfeff);
    expect(csv.slice(1).split("\n")[0]).toBe("id,tema_id,observacao");
  });

  it("põe entre aspas o comentário com vírgula e quebra de linha e faz ida e volta", () => {
    const csv = montarCsvAncora(LINHAS);
    expect(csv).toContain('Q0013,5503,"Juiz das garantias, art. 3º-B;\nnão é inquérito em geral"');
    const lido = Papa.parse<Record<string, string>>(csv.slice(1), { header: true, skipEmptyLines: true });
    expect(lido.errors).toEqual([]);
    expect(lido.data).toEqual([
      { id: "Q0009", tema_id: "5159", observacao: "" },
      { id: "Q0013", tema_id: "5503", observacao: LINHAS[1].observacao },
      { id: "Q0077", tema_id: "0", observacao: "Genocídio" },
    ]);
  });

  it("sem decisões sai só o cabeçalho", () => {
    expect(montarCsvAncora([])).toBe(BOM + "id,tema_id,observacao\n");
  });
});

describe("opcoesAncora", () => {
  const CSV_TEMAS = [
    "tema_id,parent_id,disciplina,nivel,titulo,caminho,descricao,status",
    "5062,,Penal,0,Penal,Penal,Disciplina (root).,active",
    "5157,5062,Penal,1,Dos Crimes Contra o Patrimônio,Penal > Dos Crimes Contra o Patrimônio,d,active",
    "5159,5157,Penal,2,Furto,Penal > Dos Crimes Contra o Patrimônio > Furto,d,active",
    "5160,5157,Penal,2,Roubo,Penal > Dos Crimes Contra o Patrimônio > Roubo,d,active",
    "6000,5157,Penal,2,Furto,Penal > Dos Crimes Contra o Patrimônio > Furto,,active",
    "5191,5062,Penal,1,Punibilidade,Penal > Punibilidade,d,active",
  ].join("\n");
  const temasLista = lerTemas(CSV_TEMAS);
  const temas = new Map(temasLista.map((t) => [t.tema_id, t]));
  const publicaveis = temasPublicaveis(temasLista);

  it("oferece as propostas e alternativas publicáveis e os vizinhos na árvore, sem repetir", () => {
    const r1: Rotulo = { ...rotulo("Q1", 5159), alternativas: [{ tema_id: 6000, caminho: "", motivo: "" }, { tema_id: 5062, caminho: "", motivo: "" }] };
    const r2 = rotulo("Q1", 5159);
    const opcoes = opcoesAncora([r1, r2], temas, publicaveis, "");
    expect(opcoes.propostas.map((t) => t.tema_id)).toEqual([5159]);
    expect(opcoes.vizinhos.map((t) => t.tema_id)).toEqual([5157, 5160]);
    expect(opcoes.busca).toEqual([]);
  });

  it("a busca cobre todos os publicáveis e não devolve o que já está oferecido", () => {
    const opcoes = opcoesAncora([rotulo("Q1", 5159), undefined], temas, publicaveis, "punibilidade");
    expect(opcoes.busca.map((t) => t.tema_id)).toEqual([5191]);
    expect(opcoesAncora([undefined, undefined], temas, publicaveis, "furto").busca.map((t) => t.tema_id)).toEqual([5159]);
  });
});

describe("decisões salvas no navegador", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    try {
      window.localStorage.clear();
    } catch {
      // nada a limpar
    }
  });

  it("guarda e relê pela chave ancora-decisoes", () => {
    expect(CHAVE_DECISOES).toBe("ancora-decisoes");
    expect(salvarDecisoes({ Q0009: { tema_id: 5159, observacao: "ok" } })).toBe(true);
    expect(lerDecisoesSalvas()).toEqual({ Q0009: { tema_id: 5159, observacao: "ok" } });
  });

  it("descarta entrada malformada", () => {
    expect(
      normalizarDecisoes({ Q1: { tema_id: 5159, observacao: "a" }, Q2: { tema_id: "x" }, Q3: null, Q4: { tema_id: null, observacao: "só nota" } }),
    ).toEqual({ Q1: { tema_id: 5159, observacao: "a" }, Q4: { tema_id: null, observacao: "só nota" } });
    expect(normalizarDecisoes("lixo")).toEqual({});
    window.localStorage.setItem(CHAVE_DECISOES, "{nao é json");
    expect(lerDecisoesSalvas()).toEqual({});
  });

  it("sem localStorage não quebra", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("SecurityError");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("QuotaExceededError");
    });
    expect(lerDecisoesSalvas()).toEqual({});
    expect(salvarDecisoes({ Q0009: { tema_id: 5159, observacao: "" } })).toBe(false);
  });
});

/** Buscador falso: serve arquivos de um mapa; o resto é 404. */
function buscadorDe(arquivos: Record<string, string>): Buscador {
  return async (url: string) => {
    const corpo = arquivos[url];
    const existe = corpo !== undefined;
    return {
      ok: existe,
      status: existe ? 200 : 404,
      headers: { get: (nome: string) => (nome.toLowerCase() === "content-type" && existe ? "text/plain" : null) },
      text: async () => corpo ?? "",
    };
  };
}

const PASTA_EXEMPLO = join(import.meta.dirname, "..", "public", "dados-exemplo");
const TEMAS_REAIS = readFileSync(join(PASTA_EXEMPLO, "temas.csv"), "utf-8");

describe("carregarAncora", () => {
  it("sem ancora_para_rotular.csv devolve null", async () => {
    expect(await carregarAncora("/dados", buscadorDe({ "/dados/temas.csv": TEMAS_REAIS }))).toBeNull();
  });

  it("segue com um rotulador só e avisa do arquivo que faltou", async () => {
    const conjunto = await carregarAncora(
      "/dados",
      buscadorDe({
        "/dados/ancora_para_rotular.csv": ANCORA_CSV,
        "/dados/temas.csv": TEMAS_REAIS,
        "/dados/ancora_rotulos_modelo_1.jsonl": ROTULOS_JSONL,
      }),
    );
    expect(conjunto?.questoes.map((q) => q.id)).toEqual(["Q0009", "Q0013"]);
    expect(conjunto?.rotulos1.get("Q0009")?.tema_id).toBe(5159);
    expect(conjunto?.rotulos2.size).toBe(0);
    expect(conjunto?.avisos.join(" ")).toMatch(/ancora_rotulos_modelo_2\.jsonl/);
    expect(conjunto?.avisos.join(" ")).not.toMatch(/ancora_rotulos_modelo_1\.jsonl/);
  });

  it("falha sem temas.csv", async () => {
    await expect(carregarAncora("/dados", buscadorDe({ "/dados/ancora_para_rotular.csv": ANCORA_CSV }))).rejects.toThrow(/temas\.csv/);
  });

  it("os dados de exemplo têm as 40 questões e rótulos só com temas publicáveis ou fora da árvore", async () => {
    const nomes = ["ancora_para_rotular.csv", "ancora_rotulos_modelo_1.jsonl", "ancora_rotulos_modelo_2.jsonl", "temas.csv"];
    const arquivos = Object.fromEntries(nomes.map((nome) => [`/dados-exemplo/${nome}`, readFileSync(join(PASTA_EXEMPLO, nome), "utf-8")]));
    const conjunto = await carregarAncora("/dados-exemplo", buscadorDe(arquivos));
    expect(conjunto).not.toBeNull();
    if (!conjunto) return;
    expect(conjunto.questoes).toHaveLength(40);
    expect(conjunto.rotulos1.size).toBe(5);
    expect(conjunto.rotulos2.size).toBe(5);
    const ids = new Set(conjunto.questoes.map((q) => q.id));
    const publicaveis = new Set(temasPublicaveis([...conjunto.temas.values()]).map((t) => t.tema_id));
    for (const rotulos of [conjunto.rotulos1, conjunto.rotulos2]) {
      for (const r of rotulos.values()) {
        expect(ids.has(r.id)).toBe(true);
        for (const id of [r.tema_id, ...r.alternativas.map((a) => a.tema_id)]) {
          expect(id === TEMA_FORA || (id !== null && publicaveis.has(id))).toBe(true);
        }
        if (r.tema_id !== TEMA_FORA) expect(r.caminho).toBe(conjunto.temas.get(r.tema_id ?? -1)?.caminho);
      }
    }
  });
});
