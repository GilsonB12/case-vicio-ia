import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import {
  carregarTudo,
  filaRevisar,
  limparEnunciado,
  lerPublicacao,
  lerTemas,
  opcoesDeTroca,
  parseCsv,
  parseJsonl,
  temasPublicaveis,
  type Buscador,
} from "./dados";
import type { Candidato } from "./tipos";

const CABECALHO_TEMAS = "tema_id,parent_id,disciplina,nivel,titulo,caminho,descricao,status";

// Linhas reais de anexos/temas.csv: raiz, dois publicáveis, um inativo e uma duplicata sem descrição.
const TEMAS_CSV = [
  CABECALHO_TEMAS,
  "5465,,Processo Penal,0,Processo Penal,Processo Penal,Disciplina (root). 4112 questões. Inclui 42 temas/topics.,active",
  "5524,5465,Processo Penal,1,Procedimento do Tribunal do Júri,Processo Penal > Procedimento do Tribunal do Júri,Subtema de 'Processo Penal' (Processo Penal). 253 questões no source.,active",
  '5527,5524,Processo Penal,2,"Impronúncia, Desclassificação, Absolvição Sumária e Pronúncia","Processo Penal > Procedimento do Tribunal do Júri > Impronúncia, Desclassificação, Absolvição Sumária e Pronúncia","Subtema de \'Procedimento do Tribunal do Júri\' (Processo Penal). 42 questões no source.",active',
  "5078,5062,Penal,1,Direito penal econômico,Penal > Direito penal econômico,Subtema de 'Penal' (Penal). 50 questões no source.,inactive",
  "6724,5062,Penal,1,Lei Maria da Penha,Penal > Lei Maria da Penha,,active",
  "5160,5157,Penal,2,Roubo,Penal > Dos Crimes Contra o Patrimônio > Roubo,Subtema de 'Dos Crimes Contra o Patrimônio' (Penal). 67 questões no source.,active",
].join("\n");

const PUBLICACAO_CSV =
  "id,decisao,tema_central_id,extras_ids,confianca,motivo\n" +
  'Q0001,revisar,5527,5524;5160,0.62,"modelos divergem: Impronúncia, Desclassificação vs ""Recursos""\nsegunda linha"\n' +
  "Q0002,publicar,5160,,0.91,\n" +
  "Q0003,fora,,,,fora das quatro disciplinas\n";

describe("parseCsv", () => {
  it("lê campo entre aspas com vírgula, aspas duplicadas e quebra de linha", () => {
    const linhas = parseCsv(PUBLICACAO_CSV);
    expect(linhas).toHaveLength(3);
    expect(linhas[0].motivo).toBe('modelos divergem: Impronúncia, Desclassificação vs "Recursos"\nsegunda linha');
    expect(linhas[0].extras_ids).toBe("5524;5160");
    expect(linhas[1].id).toBe("Q0002");
    expect(linhas[2].tema_central_id).toBe("");
  });

  it("tolera BOM e quebras de linha CRLF", () => {
    const linhas = parseCsv("\uFEFFid,valor\r\nQ0001,1\r\nQ0002,2\r\n");
    expect(linhas).toEqual([
      { id: "Q0001", valor: "1" },
      { id: "Q0002", valor: "2" },
    ]);
  });

  it("recusa CSV com aspas sem fechar", () => {
    expect(() => parseCsv('id,motivo\nQ0001,"sem fechar\n')).toThrow(/CSV/);
  });
});

describe("parseJsonl", () => {
  it("ignora linhas vazias e com só espaços", () => {
    const itens = parseJsonl<{ id: string }>('{"id": "Q0001"}\n\n   \n{"id": "Q0002"}\r\n');
    expect(itens.map((i) => i.id)).toEqual(["Q0001", "Q0002"]);
  });

  it("aponta a linha com JSON inválido", () => {
    expect(() => parseJsonl('{"id": "Q0001"}\n{quebrado\n')).toThrow(/linha 2/);
  });
});

describe("lerPublicacao", () => {
  it("converte extras, confiança e tema vazio", () => {
    const [q1, q2, q3] = lerPublicacao(PUBLICACAO_CSV);
    expect(q1).toMatchObject({ id: "Q0001", decisao: "revisar", tema_central_id: 5527, extras_ids: [5524, 5160], confianca: 0.62 });
    expect(q2.extras_ids).toEqual([]);
    expect(q3).toMatchObject({ decisao: "fora", tema_central_id: null, confianca: null, motivo: "fora das quatro disciplinas" });
  });

  it("recusa arquivo sem as colunas esperadas", () => {
    expect(() => lerPublicacao("id,decisao\nQ0001,revisar\n")).toThrow(/tema_central_id/);
  });

  it("recusa decisão desconhecida", () => {
    expect(() => lerPublicacao("id,decisao,tema_central_id,extras_ids,confianca,motivo\nQ0001,talvez,,,,\n")).toThrow(/talvez/);
  });
});

describe("temasPublicaveis", () => {
  it("exclui raiz, inativo e duplicata sem descrição", () => {
    const temas = lerTemas(TEMAS_CSV);
    expect(temas).toHaveLength(6);
    const ids = temasPublicaveis(temas).map((t) => t.tema_id);
    expect(ids.sort()).toEqual([5160, 5524, 5527]);
  });

  it("lê caminho com vírgula e marca o status", () => {
    const temas = new Map(lerTemas(TEMAS_CSV).map((t) => [t.tema_id, t]));
    expect(temas.get(5527)?.caminho).toBe(
      "Processo Penal > Procedimento do Tribunal do Júri > Impronúncia, Desclassificação, Absolvição Sumária e Pronúncia",
    );
    expect(temas.get(5527)?.nivel).toBe(2);
    expect(temas.get(5078)?.ativo).toBe(false);
    expect(temas.get(5465)?.parent_id).toBeNull();
  });
});

describe("opcoesDeTroca", () => {
  const publicaveis = temasPublicaveis(lerTemas(TEMAS_CSV));
  const candidatos: Candidato[] = [
    { tema_id: 6724, origem: "tema", similaridade: 0.7 },
    { tema_id: 5527, origem: "tema", similaridade: 0.66 },
    { tema_id: 5465, origem: "pai", similaridade: 0.6 },
    { tema_id: 9999, origem: "corpus", similaridade: 0.5 },
    { tema_id: 5078, origem: "corpus", similaridade: 0.4 },
  ];

  it("só oferece candidatos publicáveis", () => {
    const opcoes = opcoesDeTroca(candidatos, publicaveis, "");
    expect(opcoes.candidatos.map((t) => t.tema_id)).toEqual([5527]);
    expect(opcoes.busca).toEqual([]);
  });

  it("busca sem acento em todos os publicáveis e não repete candidatos", () => {
    const opcoes = opcoesDeTroca(candidatos, publicaveis, "tribunal juri");
    expect(opcoes.busca.map((t) => t.tema_id)).toEqual([5524]);
  });

  it("a busca nunca devolve tema fora dos publicáveis", () => {
    expect(opcoesDeTroca([], publicaveis, "maria da penha").busca).toEqual([]);
    expect(opcoesDeTroca([], publicaveis, "econômico").busca).toEqual([]);
  });
});

describe("limparEnunciado", () => {
  it("troca <br> por quebra de linha e tira as tags", () => {
    const html = "Analise.<br><br>I - <b>Certo</b>&nbsp;agora<br/>II - errado<script>alert(1)</script>";
    expect(limparEnunciado(html)).toBe("Analise.\n\nI - Certo agora\nII - errado");
  });

  it("não deixa mais de uma linha em branco seguida", () => {
    expect(limparEnunciado("<p>a</p><br><br><br><p>b</p>")).toBe("a\n\nb");
  });
});

/** Buscador falso: serve arquivos de um mapa; o resto é 404. */
function buscadorDe(arquivos: Record<string, string>, tipo = "text/plain"): Buscador {
  return async (url: string) => {
    const corpo = arquivos[url];
    const existe = corpo !== undefined;
    return {
      ok: existe,
      status: existe ? 200 : 404,
      headers: { get: (nome: string) => (nome.toLowerCase() === "content-type" && existe ? tipo : null) },
      text: async () => corpo ?? "",
    };
  };
}

const QUESTOES_JSONL =
  '{"id": "Q0001", "enunciado_html": "No júri,<br>analise.", "comando": "Assinale", "alternativas": {"A": "x", "B": "y"}, "disciplina_origem": "Processo Penal", "assunto_origem": "Júri"}\n' +
  '{"id": "Q0002", "enunciado_html": "Roubo", "comando": "", "alternativas": {"A": "x"}, "disciplina_origem": "Penal", "assunto_origem": "Roubo"}\n';

const ESSENCIAIS = {
  "/dados/publicacao.csv": PUBLICACAO_CSV,
  "/dados/questoes.jsonl": QUESTOES_JSONL,
  "/dados/temas.csv": TEMAS_CSV,
};

describe("carregarTudo", () => {
  it("junta os seis arquivos e traz a regra das decisões", async () => {
    const buscar = buscadorDe({
      ...ESSENCIAIS,
      "/dados/decisoes_questoes.jsonl":
        '{"id": "Q0001", "decisao": "revisar", "tema_central_id": 5527, "extras_ids": [5524], "confianca": 0.62, "motivo": "m", "regra": 4}\n',
      "/dados/votos_llm_questoes.jsonl":
        '{"id": "Q0001", "openai": {"tema_central_id": 5527, "extras_ids": [], "disciplina": "Processo Penal", "confianca": 0.7, "justificativa": "j"}, "anthropic": null}\n',
      "/dados/candidatos_questoes_p2.jsonl":
        '{"id": "Q0001", "candidatos": [{"tema_id": 5527, "origem": "tema", "similaridade": 0.61}]}\n',
    });
    const conjunto = await carregarTudo("/dados", buscar);
    expect(conjunto.publicacao).toHaveLength(3);
    expect(conjunto.questoes.get("Q0001")?.comando).toBe("Assinale");
    expect(conjunto.temas.get(5527)?.nivel).toBe(2);
    expect(conjunto.votos.get("Q0001")?.anthropic).toBeNull();
    expect(conjunto.candidatos.get("Q0001")?.[0].tema_id).toBe(5527);
    expect(conjunto.avisos).toEqual([]);
    const fila = filaRevisar(conjunto);
    expect(fila.map((d) => d.id)).toEqual(["Q0001"]);
    expect(fila[0].regra).toBe(4);
  });

  it("segue sem os intermediários, com aviso de cada um", async () => {
    const conjunto = await carregarTudo("/dados", buscadorDe(ESSENCIAIS));
    expect(conjunto.votos.size).toBe(0);
    expect(conjunto.avisos.join(" ")).toMatch(/decisoes_questoes\.jsonl/);
    expect(conjunto.avisos.join(" ")).toMatch(/votos_llm_questoes\.jsonl/);
    expect(conjunto.avisos.join(" ")).toMatch(/candidatos_questoes_p2\.jsonl/);
    expect(filaRevisar(conjunto)[0].regra).toBeNull();
  });

  it("falha sem publicacao.csv", async () => {
    const semPublicacao = { "/dados/questoes.jsonl": QUESTOES_JSONL, "/dados/temas.csv": TEMAS_CSV };
    await expect(carregarTudo("/dados", buscadorDe(semPublicacao))).rejects.toThrow(/publicacao\.csv/);
  });

  it("trata como ausente o index.html que o servidor do Vite devolve no lugar de arquivo inexistente", async () => {
    const html = "<!doctype html><html><body><div id=\"root\"></div></body></html>";
    const buscar = buscadorDe(
      { "/dados/publicacao.csv": html, "/dados/questoes.jsonl": html, "/dados/temas.csv": html },
      "text/html",
    );
    await expect(carregarTudo("/dados", buscar)).rejects.toThrow(/publicacao\.csv/);
  });
});

describe("dados de exemplo", () => {
  const pasta = join(import.meta.dirname, "..", "public", "dados-exemplo");
  const arquivos = Object.fromEntries(
    [
      "publicacao.csv",
      "questoes.jsonl",
      "temas.csv",
      "decisoes_questoes.jsonl",
      "votos_llm_questoes.jsonl",
      "candidatos_questoes_p2.jsonl",
    ].map((nome) => [`/dados-exemplo/${nome}`, readFileSync(join(pasta, nome), "utf-8")]),
  );

  it("têm 6 questões, 4 a revisar, e só usam temas publicáveis da árvore real", async () => {
    const conjunto = await carregarTudo("/dados-exemplo", buscadorDe(arquivos));
    expect(conjunto.avisos).toEqual([]);
    expect(conjunto.publicacao).toHaveLength(6);
    expect(conjunto.questoes.size).toBe(6);
    expect(filaRevisar(conjunto)).toHaveLength(4);
    const publicaveis = new Set(temasPublicaveis([...conjunto.temas.values()]).map((t) => t.tema_id));
    expect(publicaveis.size).toBe(351);
    const usados: number[] = [];
    for (const d of conjunto.publicacao) {
      expect(conjunto.questoes.has(d.id)).toBe(true);
      if (d.tema_central_id !== null) usados.push(d.tema_central_id, ...d.extras_ids);
      const votos = conjunto.votos.get(d.id);
      for (const voto of [votos?.openai, votos?.anthropic]) {
        if (voto?.tema_central_id != null) usados.push(voto.tema_central_id, ...voto.extras_ids);
      }
      for (const c of conjunto.candidatos.get(d.id) ?? []) usados.push(c.tema_id);
    }
    expect(usados.filter((id) => !publicaveis.has(id))).toEqual([]);
  });
});
