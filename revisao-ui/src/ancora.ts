// Modo Âncora: leitura das 40 questões e dos rótulos dos dois rotuladores, decisões guardadas no navegador e
// exportação de ancora_manual.csv. Tudo aqui é puro ou isolado em try/catch, para poder ser testado sem rede.
import Papa from "papaparse";
import {
  buscarArquivo,
  buscarPadrao,
  buscarTemas,
  comArquivo,
  exigirColunas,
  lerCsvComCampos,
  lerTemas,
  numeroOuNulo,
  semBom,
  type Buscador,
} from "./dados";
import type { AlternativaRotulo, ConjuntoAncora, DecisaoAncora, LinhaAncora, QuestaoAncora, Rotulo, Tema } from "./tipos";

/** `tema_id` que quer dizer "nenhum tema da árvore serve". */
export const TEMA_FORA = 0;

export const ARQUIVO_ANCORA = "ancora_para_rotular.csv";
export const ARQUIVOS_ROTULOS = ["ancora_rotulos_modelo_1.jsonl", "ancora_rotulos_modelo_2.jsonl"] as const;
export const CHAVE_DECISOES = "ancora-decisoes";

const COLUNAS_ANCORA = ["id", "texto"];
const COLUNAS_EXPORTADAS = ["id", "tema_id", "observacao"];
/** Marca de ordem de bytes do UTF-8; o Excel precisa dela para ler os acentos. */
const BOM = String.fromCharCode(0xfeff);

/** Linhas de ancora_para_rotular.csv (separador `;`, BOM opcional, `texto` em várias linhas). */
export function lerAncora(texto: string): QuestaoAncora[] {
  const { linhas, campos } = lerCsvComCampos(texto, ";");
  exigirColunas(campos, COLUNAS_ANCORA, ARQUIVO_ANCORA);
  const vistos = new Set<string>();
  const questoes: QuestaoAncora[] = [];
  for (const linha of linhas) {
    const id = (linha.id ?? "").trim();
    if (!id) continue;
    if (vistos.has(id)) throw new Error(`id ${id} repetido`);
    vistos.add(id);
    questoes.push({
      id,
      disciplina_origem: (linha.disciplina_origem ?? "").trim(),
      texto: (linha.texto ?? "").replace(/\r\n?/g, "\n").trim(),
      observacao: (linha.observacao ?? "").trim(),
    });
  }
  return questoes;
}

function idDeTema(valor: unknown): number | null {
  const numero = numeroOuNulo(valor);
  return numero !== null && Number.isInteger(numero) && numero >= 0 ? numero : null;
}

function textoDe(valor: unknown): string {
  return typeof valor === "string" ? valor.trim() : "";
}

function ehObjeto(valor: unknown): valor is Record<string, unknown> {
  return valor !== null && typeof valor === "object" && !Array.isArray(valor);
}

function lerAlternativas(valor: unknown): AlternativaRotulo[] {
  if (!Array.isArray(valor)) return [];
  return valor.filter(ehObjeto).map((alternativa) => ({
    tema_id: idDeTema(alternativa.tema_id),
    caminho: textoDe(alternativa.caminho),
    motivo: textoDe(alternativa.motivo),
  }));
}

/**
 * Rótulos de um rotulador, indexados pelo id da questão. Arquivo ausente (null) vira mapa vazio. Uma linha
 * que não é JSON ou não tem id é pulada e relatada em `aoIgnorar`, para uma linha ruim não esconder as outras.
 */
export function lerRotulos(texto: string | null, aoIgnorar?: (aviso: string) => void): Map<string, Rotulo> {
  const rotulos = new Map<string, Rotulo>();
  if (texto === null) return rotulos;
  semBom(texto)
    .split(/\r?\n/)
    .forEach((linha, indice) => {
      if (!linha.trim()) return;
      let bruto: unknown;
      try {
        bruto = JSON.parse(linha);
      } catch {
        aoIgnorar?.(`linha ${indice + 1} não é JSON válido; pulei`);
        return;
      }
      const id = ehObjeto(bruto) ? String(bruto.id ?? "").trim() : "";
      if (!ehObjeto(bruto) || !id) {
        aoIgnorar?.(`linha ${indice + 1} sem id; pulei`);
        return;
      }
      rotulos.set(id, {
        id,
        tema_id: idDeTema(bruto.tema_id),
        caminho: textoDe(bruto.caminho),
        confianca: numeroOuNulo(bruto.confianca),
        justificativa: textoDe(bruto.justificativa),
        alternativas: lerAlternativas(bruto.alternativas_consideradas),
      });
    });
  return rotulos;
}

/** Os dois rotuladores propuseram o mesmo tema (fora da árvore também conta). */
export function concordam(a: Rotulo | null | undefined, b: Rotulo | null | undefined): boolean {
  return Boolean(a && b && a.tema_id !== null && a.tema_id === b.tema_id);
}

/**
 * ancora_manual.csv: BOM (para o Excel mostrar os acentos), cabeçalho `id,tema_id,observacao` e uma linha por
 * questão decidida. O papaparse cuida do quoting; a observação vai sempre entre aspas.
 */
export function montarCsvAncora(linhas: LinhaAncora[]): string {
  const cabecalho = Papa.unparse([COLUNAS_EXPORTADAS], { newline: "\n" });
  if (linhas.length === 0) return `${BOM}${cabecalho}\n`;
  const corpo = Papa.unparse(
    linhas.map((linha) => [linha.id, String(linha.tema_id), linha.observacao]),
    { quotes: [false, false, true], newline: "\n" },
  );
  return `${BOM}${cabecalho}\n${corpo}\n`;
}

export interface OpcoesAncora {
  /** Temas propostos pelos rotuladores e as alternativas que eles pesaram, só os publicáveis. */
  propostas: Tema[];
  /** O pai e os irmãos dos temas propostos, para ver a vizinhança na árvore. */
  vizinhos: Tema[];
  /** Resultado da busca entre todos os publicáveis, sem repetir os grupos acima. */
  busca: Tema[];
  totalBusca: number;
}

/** O que a escolha de outro tema oferece; nunca raiz, inativo, duplicata ou id fora da árvore. */
export function opcoesAncora(
  rotulos: (Rotulo | null | undefined)[],
  temas: Map<number, Tema>,
  publicaveis: Tema[],
  termo: string,
  limite = 50,
): OpcoesAncora {
  const porId = new Map(publicaveis.map((tema) => [tema.tema_id, tema]));
  const vistos = new Set<number>();
  const incluir = (lista: Tema[], id: number | null) => {
    const tema = id === null ? undefined : porId.get(id);
    if (tema && !vistos.has(tema.tema_id)) {
      vistos.add(tema.tema_id);
      lista.push(tema);
    }
  };

  const presentes = rotulos.filter((rotulo): rotulo is Rotulo => Boolean(rotulo));
  const propostas: Tema[] = [];
  for (const rotulo of presentes) {
    incluir(propostas, rotulo.tema_id);
    for (const alternativa of rotulo.alternativas) incluir(propostas, alternativa.tema_id);
  }

  const pais = new Set<number>();
  for (const rotulo of presentes) {
    const pai = rotulo.tema_id === null ? null : temas.get(rotulo.tema_id)?.parent_id;
    if (pai !== null && pai !== undefined) pais.add(pai);
  }
  const vizinhos: Tema[] = [];
  for (const tema of publicaveis) {
    if (vizinhos.length >= limite) break;
    if (pais.has(tema.tema_id) || (tema.parent_id !== null && pais.has(tema.parent_id))) incluir(vizinhos, tema.tema_id);
  }

  const achados = buscarTemas(publicaveis, termo).filter((tema) => !vistos.has(tema.tema_id));
  return { propostas, vizinhos, busca: achados.slice(0, limite), totalBusca: achados.length };
}

/** Decisões lidas do navegador: só fica o que tem a forma esperada. */
export function normalizarDecisoes(bruto: unknown): Record<string, DecisaoAncora> {
  if (!ehObjeto(bruto)) return {};
  const decisoes: Record<string, DecisaoAncora> = {};
  for (const [id, valor] of Object.entries(bruto)) {
    if (!ehObjeto(valor)) continue;
    const tema = valor.tema_id;
    const temaValido = tema === null || tema === undefined || (typeof tema === "number" && Number.isInteger(tema) && tema >= 0);
    if (!temaValido) continue;
    decisoes[id] = {
      tema_id: typeof tema === "number" ? tema : null,
      observacao: typeof valor.observacao === "string" ? valor.observacao : "",
    };
  }
  return decisoes;
}

/** Relê as decisões guardadas; sem localStorage (ou com lixo nele) começa do zero. */
export function lerDecisoesSalvas(): Record<string, DecisaoAncora> {
  try {
    const bruto = window.localStorage.getItem(CHAVE_DECISOES);
    return bruto ? normalizarDecisoes(JSON.parse(bruto)) : {};
  } catch {
    return {};
  }
}

/** Guarda as decisões; devolve false quando o navegador não deixa (aba privada, cota, bloqueio). */
export function salvarDecisoes(decisoes: Record<string, DecisaoAncora>): boolean {
  try {
    window.localStorage.setItem(CHAVE_DECISOES, JSON.stringify(decisoes));
    return true;
  } catch {
    return false;
  }
}

/**
 * Carrega a âncora de `base`. Devolve null quando ancora_para_rotular.csv não está lá; sem temas.csv falha.
 * Rotulador sem arquivo aparece como "sem rótulo", com aviso.
 */
export async function carregarAncora(base: string, buscar: Buscador = buscarPadrao): Promise<ConjuntoAncora | null> {
  const raiz = base.replace(/\/+$/, "");
  const nomes = [ARQUIVO_ANCORA, "temas.csv", ...ARQUIVOS_ROTULOS];
  const [textoAncora, textoTemas, ...textosRotulos] = await Promise.all(
    nomes.map((nome) => buscarArquivo(`${raiz}/${nome}`, buscar)),
  );
  if (textoAncora === null) return null;
  if (textoTemas === null) throw new Error(`temas.csv não encontrado em ${raiz}/`);

  const questoes = comArquivo(ARQUIVO_ANCORA, () => lerAncora(textoAncora));
  const temas = comArquivo("temas.csv", () => lerTemas(textoTemas));
  const avisos: string[] = [];
  const [rotulos1, rotulos2] = ARQUIVOS_ROTULOS.map((nome, i) => {
    const texto = textosRotulos[i];
    const rotulador = `Rotulador ${i + 1}`;
    if (texto === null) {
      avisos.push(`${nome} não encontrado em ${raiz}/; o ${rotulador} aparece como sem rótulo`);
      return new Map<string, Rotulo>();
    }
    const rotulos = lerRotulos(texto, (aviso) => avisos.push(`${nome}: ${aviso}`));
    const semRotulo = questoes.filter((questao) => !rotulos.has(questao.id)).length;
    if (semRotulo > 0) avisos.push(`o ${rotulador} não tem rótulo para ${semRotulo} de ${questoes.length} questões`);
    return rotulos;
  });

  return { questoes, temas: new Map(temas.map((tema) => [tema.tema_id, tema])), rotulos1, rotulos2, avisos };
}
