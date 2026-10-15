// Exportação das decisões do professor em CSV.
import Papa from "papaparse";
import type { DecisaoProfessor } from "./tipos";

const COLUNAS = ["id", "acao", "tema_id", "observacao"];

/**
 * CSV com cabeçalho `id,acao,tema_id,observacao`. O papaparse cuida do quoting (vírgula, aspas e quebra
 * de linha); a observação vai sempre entre aspas para que um `;` digitado pelo professor não vire coluna
 * em programas que adivinham o separador.
 */
export function montarCsvProfessor(decisoes: DecisaoProfessor[]): string {
  const cabecalho = Papa.unparse([COLUNAS], { newline: "\n" });
  if (decisoes.length === 0) return `${cabecalho}\n`;
  const linhas = decisoes.map((d) => [d.id, d.acao, d.tema_id === null ? "" : String(d.tema_id), d.observacao]);
  const corpo = Papa.unparse(linhas, { quotes: [false, false, false, true], newline: "\n" });
  return `${cabecalho}\n${corpo}\n`;
}

/** Oferece `conteudo` para download com o nome dado. */
export function baixar(nome: string, conteudo: string, tipo = "text/csv;charset=utf-8"): void {
  const url = URL.createObjectURL(new Blob([conteudo], { type: tipo }));
  const link = document.createElement("a");
  link.href = url;
  link.download = nome;
  link.style.display = "none";
  document.body.appendChild(link);
  link.click();
  link.remove();
  // Revogar na hora pode cancelar o download em alguns navegadores.
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
