// Copia para public/dados/ os arquivos do pipeline que a tela lê. O que não existe é pulado com aviso;
// sem publicacao.csv, questoes.jsonl e temas.csv a tela cai nos dados de exemplo.
import { copyFileSync, existsSync, mkdirSync } from "node:fs";
import { fileURLToPath } from "node:url";

const repositorio = new URL("../../", import.meta.url);
const destino = new URL("../public/dados/", import.meta.url);

const ARQUIVOS = [
  "publicacao.csv",
  "anexos/questoes.jsonl",
  "anexos/temas.csv",
  "data/intermediarios/decisoes_questoes.jsonl",
  "data/intermediarios/votos_llm_questoes.jsonl",
  "data/intermediarios/candidatos_questoes_p2.jsonl",
];

mkdirSync(destino, { recursive: true });
let copiados = 0;
for (const relativo of ARQUIVOS) {
  const origem = new URL(relativo, repositorio);
  const nome = relativo.split("/").pop();
  if (!existsSync(origem)) {
    console.warn(`aviso: ${relativo} não existe; pulei`);
    continue;
  }
  copyFileSync(origem, new URL(nome, destino));
  console.log(`copiado: ${relativo}`);
  copiados++;
}
console.log(`${copiados} de ${ARQUIVOS.length} arquivos em ${fileURLToPath(destino)}`);
