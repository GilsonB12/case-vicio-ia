// Leitura dos arquivos estáticos que a tela usa. As funções de parse são puras para poderem ser testadas sem rede.
import Papa from "papaparse";
import type { Candidato, Conjunto, Decisao, Questao, Tema, TipoDecisao, Voto, Votos } from "./tipos";

/** O mínimo de `Response` que a carga usa; nos testes entra um dublê no lugar do `fetch`. */
export interface RespostaMinima {
  ok: boolean;
  status: number;
  headers: { get(nome: string): string | null };
  text(): Promise<string>;
}

export type Buscador = (url: string) => Promise<RespostaMinima>;

const COLUNAS_PUBLICACAO = ["id", "decisao", "tema_central_id", "extras_ids", "confianca", "motivo"];
const COLUNAS_TEMAS = ["tema_id", "parent_id", "disciplina", "nivel", "titulo", "caminho", "descricao", "status"];
const DECISOES_VALIDAS: TipoDecisao[] = ["publicar", "revisar", "fora"];

const ESSENCIAIS = ["publicacao.csv", "questoes.jsonl", "temas.csv"] as const;
const OPCIONAIS = ["decisoes_questoes.jsonl", "votos_llm_questoes.jsonl", "candidatos_questoes_p2.jsonl"] as const;

export function semBom(texto: string): string {
  return texto.replace(/^\uFEFF/, "");
}

/** CSV com cabeçalho; o separador padrão é a vírgula. */
export function lerCsvComCampos(
  texto: string,
  delimitador = ",",
): { linhas: Record<string, string>[]; campos: string[] } {
  const resultado = Papa.parse<Record<string, string>>(semBom(texto), {
    header: true,
    delimiter: delimitador,
    skipEmptyLines: true,
    transformHeader: (cabecalho) => cabecalho.trim(),
  });
  if (resultado.errors.length > 0) {
    const erro = resultado.errors[0];
    const onde = erro.row !== undefined ? ` no registro ${erro.row + 1}` : "";
    throw new Error(`CSV inválido${onde}: ${erro.message}`);
  }
  return { linhas: resultado.data, campos: resultado.meta.fields ?? [] };
}

/** CSV com cabeçalho (RFC 4180: campos entre aspas podem ter vírgula, aspas duplicadas e quebra de linha). */
export function parseCsv(texto: string): Record<string, string>[] {
  return lerCsvComCampos(texto).linhas;
}

/** Um JSON por linha; linhas vazias são ignoradas. */
export function parseJsonl<T = unknown>(texto: string): T[] {
  const itens: T[] = [];
  semBom(texto)
    .split(/\r?\n/)
    .forEach((linha, indice) => {
      if (!linha.trim()) return;
      try {
        itens.push(JSON.parse(linha) as T);
      } catch (erro) {
        throw new Error(`JSON inválido na linha ${indice + 1}: ${(erro as Error).message}`);
      }
    });
  return itens;
}

export function exigirColunas(campos: string[], esperadas: string[], arquivo: string): void {
  const faltando = esperadas.filter((coluna) => !campos.includes(coluna));
  if (faltando.length > 0) throw new Error(`${arquivo} sem as colunas ${faltando.join(", ")}`);
}

function inteiroOuNulo(valor: string | undefined, contexto: string): number | null {
  const limpo = (valor ?? "").trim();
  if (limpo === "") return null;
  const numero = Number(limpo);
  if (!Number.isInteger(numero)) throw new Error(`${contexto}: "${limpo}" não é um id inteiro`);
  return numero;
}

export function numeroOuNulo(valor: unknown): number | null {
  if (valor === null || valor === undefined || valor === "") return null;
  const numero = Number(valor);
  return Number.isFinite(numero) ? numero : null;
}

/** Linhas de temas.csv. */
export function lerTemas(texto: string): Tema[] {
  const { linhas, campos } = lerCsvComCampos(texto);
  exigirColunas(campos, COLUNAS_TEMAS, "temas.csv");
  return linhas.map((linha, i) => {
    const contexto = `temas.csv, registro ${i + 1}`;
    const tema_id = inteiroOuNulo(linha.tema_id, contexto);
    if (tema_id === null) throw new Error(`${contexto}: tema_id vazio`);
    return {
      tema_id,
      parent_id: inteiroOuNulo(linha.parent_id, contexto),
      titulo: linha.titulo ?? "",
      caminho: linha.caminho ?? "",
      nivel: inteiroOuNulo(linha.nivel, contexto) ?? 0,
      disciplina: linha.disciplina ?? "",
      descricao: linha.descricao ?? "",
      ativo: (linha.status ?? "").trim() === "active",
    };
  });
}

/** Linhas de publicacao.csv; `regra` fica nula até ser cruzada com decisoes_questoes.jsonl. */
export function lerPublicacao(texto: string): Decisao[] {
  const { linhas, campos } = lerCsvComCampos(texto);
  exigirColunas(campos, COLUNAS_PUBLICACAO, "publicacao.csv");
  return linhas.map((linha, i) => {
    const contexto = `publicacao.csv, registro ${i + 1}`;
    const decisao = (linha.decisao ?? "").trim() as TipoDecisao;
    if (!DECISOES_VALIDAS.includes(decisao)) throw new Error(`${contexto}: decisão "${decisao}" desconhecida`);
    return {
      id: (linha.id ?? "").trim(),
      decisao,
      tema_central_id: inteiroOuNulo(linha.tema_central_id, contexto),
      extras_ids: (linha.extras_ids ?? "")
        .split(";")
        .map((parte) => inteiroOuNulo(parte, contexto))
        .filter((id): id is number => id !== null),
      confianca: numeroOuNulo(linha.confianca),
      motivo: linha.motivo ?? "",
      regra: null,
    };
  });
}

/** Temas que podem receber questão: nem raiz de disciplina, nem inativo, nem duplicata (descrição vazia). */
export function temasPublicaveis(temas: Tema[]): Tema[] {
  return temas
    .filter((tema) => tema.nivel > 0 && tema.ativo && tema.descricao.trim() !== "")
    .sort((a, b) => a.caminho.localeCompare(b.caminho, "pt-BR"));
}

function normalizar(texto: string): string {
  return texto.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
}

/** Temas cujo caminho contém todas as palavras do termo, sem diferença de acento ou caixa; o id exato também vale. */
export function buscarTemas(temas: Tema[], termo: string): Tema[] {
  const palavras = normalizar(termo).split(/\s+/).filter(Boolean);
  if (palavras.length === 0) return [];
  const id = termo.trim();
  return temas.filter((tema) => {
    if (String(tema.tema_id) === id) return true;
    const caminho = normalizar(tema.caminho);
    return palavras.every((palavra) => caminho.includes(palavra));
  });
}

export interface OpcoesDeTroca {
  /** Candidatos da questão que são publicáveis, na ordem do pipeline. */
  candidatos: Tema[];
  /** Resultado da busca entre todos os publicáveis, sem repetir os candidatos. */
  busca: Tema[];
  /** Quantos publicáveis casaram com a busca antes do limite. */
  totalBusca: number;
}

/** O que a troca de tema oferece: só temas publicáveis, nunca id inexistente, raiz, inativo ou duplicata. */
export function opcoesDeTroca(candidatos: Candidato[], publicaveis: Tema[], termo: string, limite = 50): OpcoesDeTroca {
  const porId = new Map(publicaveis.map((tema) => [tema.tema_id, tema]));
  const vistos = new Set<number>();
  const deCandidatos: Tema[] = [];
  for (const candidato of candidatos) {
    const tema = porId.get(candidato.tema_id);
    if (tema && !vistos.has(tema.tema_id)) {
      vistos.add(tema.tema_id);
      deCandidatos.push(tema);
    }
  }
  const achados = buscarTemas(publicaveis, termo).filter((tema) => !vistos.has(tema.tema_id));
  return { candidatos: deCandidatos, busca: achados.slice(0, limite), totalBusca: achados.length };
}

/** Texto do enunciado sem HTML: `<br>` e fim de parágrafo viram quebra de linha. */
export function limparEnunciado(html: string): string {
  const comQuebras = html.replace(/<br\s*\/?>/gi, "\n").replace(/<\/(p|div|li|tr|h[1-6])>/gi, "$&\n");
  const documento = new DOMParser().parseFromString(comQuebras, "text/html");
  documento.querySelectorAll("script, style").forEach((elemento) => elemento.remove());
  return (documento.body.textContent ?? "")
    .replace(/\u00a0/g, " ")
    .replace(/[ \t]+\n/g, "\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

/** As questões que o professor precisa ver, na ordem do publicacao.csv. */
export function filaRevisar(conjunto: Conjunto): Decisao[] {
  return conjunto.publicacao.filter((decisao) => decisao.decisao === "revisar");
}

function normalizarVoto(bruto: unknown): Voto | null {
  if (bruto === null || typeof bruto !== "object") return null;
  const voto = bruto as Record<string, unknown>;
  return {
    tema_central_id: numeroOuNulo(voto.tema_central_id),
    extras_ids: Array.isArray(voto.extras_ids) ? voto.extras_ids.map(Number).filter(Number.isInteger) : [],
    disciplina: typeof voto.disciplina === "string" ? voto.disciplina : null,
    confianca: numeroOuNulo(voto.confianca),
    justificativa: typeof voto.justificativa === "string" ? voto.justificativa : "",
  };
}

function normalizarQuestao(bruta: Record<string, unknown>): Questao {
  const alternativas: Record<string, string> = {};
  if (bruta.alternativas && typeof bruta.alternativas === "object") {
    for (const [letra, texto] of Object.entries(bruta.alternativas as Record<string, unknown>)) {
      alternativas[letra] = String(texto ?? "");
    }
  }
  return {
    id: String(bruta.id),
    enunciado_html: String(bruta.enunciado_html ?? ""),
    comando: String(bruta.comando ?? ""),
    alternativas,
    disciplina_origem: typeof bruta.disciplina_origem === "string" ? bruta.disciplina_origem : undefined,
    assunto_origem: typeof bruta.assunto_origem === "string" ? bruta.assunto_origem : undefined,
  };
}

/**
 * Busca um arquivo; devolve null quando ele não existe. O servidor do Vite responde 200 com o index.html
 * para caminho inexistente, então HTML também conta como ausente.
 */
export async function buscarArquivo(url: string, buscar: Buscador): Promise<string | null> {
  let resposta: RespostaMinima;
  try {
    resposta = await buscar(url);
  } catch {
    return null;
  }
  if (!resposta.ok) return null;
  if ((resposta.headers.get("content-type") ?? "").includes("text/html")) return null;
  const texto = await resposta.text();
  if (/^\s*(<!doctype html|<html)/i.test(texto)) return null;
  return texto;
}

export function comArquivo<T>(arquivo: string, ler: () => T): T {
  try {
    return ler();
  } catch (erro) {
    throw new Error(`${arquivo}: ${(erro as Error).message}`);
  }
}

export const buscarPadrao: Buscador = (url) => fetch(url, { cache: "no-cache" });

/**
 * Carrega os seis arquivos de `base`. publicacao.csv, questoes.jsonl e temas.csv são obrigatórios;
 * sem os intermediários a tela ainda funciona, com aviso.
 */
export async function carregarTudo(base: string, buscar: Buscador = buscarPadrao): Promise<Conjunto> {
  const raiz = base.replace(/\/+$/, "");
  const nomes = [...ESSENCIAIS, ...OPCIONAIS];
  const textos = await Promise.all(nomes.map((nome) => buscarArquivo(`${raiz}/${nome}`, buscar)));
  const porNome = new Map<string, string | null>(nomes.map((nome, i) => [nome, textos[i]]));

  const faltando = ESSENCIAIS.filter((nome) => porNome.get(nome) === null);
  if (faltando.length > 0) throw new Error(`faltam em ${raiz}/: ${faltando.join(", ")}`);
  const texto = (nome: string) => porNome.get(nome) ?? "";

  const publicacao = comArquivo("publicacao.csv", () => lerPublicacao(texto("publicacao.csv")));
  const questoes = comArquivo("questoes.jsonl", () =>
    parseJsonl<Record<string, unknown>>(texto("questoes.jsonl")).map(normalizarQuestao),
  );
  const temas = comArquivo("temas.csv", () => lerTemas(texto("temas.csv")));

  const avisos = OPCIONAIS.filter((nome) => porNome.get(nome) === null).map(
    (nome) => `${nome} não encontrado em ${raiz}/`,
  );

  const regras = new Map<string, number | null>();
  for (const linha of comArquivo("decisoes_questoes.jsonl", () =>
    parseJsonl<Record<string, unknown>>(texto("decisoes_questoes.jsonl")),
  )) {
    regras.set(String(linha.id), numeroOuNulo(linha.regra));
  }

  const votos = new Map<string, Votos>();
  for (const linha of comArquivo("votos_llm_questoes.jsonl", () =>
    parseJsonl<Record<string, unknown>>(texto("votos_llm_questoes.jsonl")),
  )) {
    const id = String(linha.id);
    votos.set(id, { id, openai: normalizarVoto(linha.openai), anthropic: normalizarVoto(linha.anthropic) });
  }

  const candidatos = new Map<string, Candidato[]>();
  for (const linha of comArquivo("candidatos_questoes_p2.jsonl", () =>
    parseJsonl<{ id: string; candidatos?: Candidato[] }>(texto("candidatos_questoes_p2.jsonl")),
  )) {
    candidatos.set(
      String(linha.id),
      (linha.candidatos ?? []).map((c) => ({
        tema_id: Number(c.tema_id),
        origem: String(c.origem ?? ""),
        similaridade: Number(c.similaridade),
      })),
    );
  }

  return {
    publicacao: publicacao.map((decisao) => ({ ...decisao, regra: regras.get(decisao.id) ?? null })),
    questoes: new Map(questoes.map((questao) => [questao.id, questao])),
    temas: new Map(temas.map((tema) => [tema.tema_id, tema])),
    votos,
    candidatos,
    avisos,
  };
}
