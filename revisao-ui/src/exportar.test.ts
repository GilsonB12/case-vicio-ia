import Papa from "papaparse";
import { describe, expect, it } from "vitest";
import { montarCsvProfessor } from "./exportar";
import type { DecisaoProfessor } from "./tipos";

const DECISOES: DecisaoProfessor[] = [
  { id: "Q0001", acao: "confirmar", tema_id: 5527, observacao: "" },
  {
    id: "Q0002",
    acao: "trocar",
    tema_id: 5160,
    observacao: 'É roubo impróprio; a violência veio depois, "logo após" a subtração,\nart. 157, § 1º',
  },
  { id: "Q0003", acao: "fora", tema_id: null, observacao: "Direito Civil; não é penal" },
];

describe("montarCsvProfessor", () => {
  it("começa pelo cabeçalho id,acao,tema_id,observacao", () => {
    const csv = montarCsvProfessor(DECISOES);
    expect(csv.split(/\r?\n/)[0]).toBe("id,acao,tema_id,observacao");
  });

  it("faz ida e volta com ;, aspas e quebra de linha na observação", () => {
    const csv = montarCsvProfessor(DECISOES);
    const lido = Papa.parse<Record<string, string>>(csv, { header: true, skipEmptyLines: true });
    expect(lido.errors).toEqual([]);
    expect(lido.data).toEqual([
      { id: "Q0001", acao: "confirmar", tema_id: "5527", observacao: "" },
      { id: "Q0002", acao: "trocar", tema_id: "5160", observacao: DECISOES[1].observacao },
      { id: "Q0003", acao: "fora", tema_id: "", observacao: "Direito Civil; não é penal" },
    ]);
  });

  it("põe a observação entre aspas mesmo quando só tem ;", () => {
    const csv = montarCsvProfessor([DECISOES[2]]);
    expect(csv).toContain('Q0003,fora,,"Direito Civil; não é penal"');
  });

  it("sem decisões devolve só o cabeçalho", () => {
    expect(montarCsvProfessor([]).trim()).toBe("id,acao,tema_id,observacao");
  });
});
