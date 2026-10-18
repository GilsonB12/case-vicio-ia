// Tipos dos arquivos que a tela lê, no mesmo formato dos intermediários do pipeline.

export type TipoDecisao = "publicar" | "revisar" | "fora";

/** Uma linha de anexos/questoes.jsonl. */
export interface Questao {
  id: string;
  enunciado_html: string;
  comando: string;
  alternativas: Record<string, string>;
  disciplina_origem?: string;
  assunto_origem?: string;
}

/** Uma linha de anexos/temas.csv. `descricao` vazia marca as duplicatas, que não podem ser oferecidas. */
export interface Tema {
  tema_id: number;
  parent_id: number | null;
  titulo: string;
  caminho: string;
  nivel: number;
  disciplina: string;
  descricao: string;
  ativo: boolean;
}

/** Uma linha de publicacao.csv; `regra` vem de decisoes_questoes.jsonl quando ele existe. */
export interface Decisao {
  id: string;
  decisao: TipoDecisao;
  tema_central_id: number | null;
  extras_ids: number[];
  confianca: number | null;
  motivo: string;
  regra: number | null;
}

/** O voto de um modelo em votos_llm_questoes.jsonl. `tema_central_id` nulo quer dizer "nenhum candidato serve". */
export interface Voto {
  tema_central_id: number | null;
  extras_ids: number[];
  disciplina: string | null;
  confianca: number | null;
  justificativa: string;
}

/** Os dois votos de uma questão; nulo quando o modelo não deu resposta válida. */
export interface Votos {
  id: string;
  openai: Voto | null;
  anthropic: Voto | null;
}

/** Um candidato de candidatos_questoes_p2.jsonl. `origem` é "tema", "corpus" ou "pai". */
export interface Candidato {
  tema_id: number;
  origem: string;
  similaridade: number;
}

export type AcaoProfessor = "confirmar" | "trocar" | "fora";

/** O que o professor decidiu sobre uma questão; é o que vai para o CSV exportado. */
export interface DecisaoProfessor {
  id: string;
  acao: AcaoProfessor;
  tema_id: number | null;
  observacao: string;
}

/** Tudo o que a tela precisa, já indexado por id. */
export interface Conjunto {
  publicacao: Decisao[];
  questoes: Map<string, Questao>;
  temas: Map<number, Tema>;
  votos: Map<string, Votos>;
  candidatos: Map<string, Candidato[]>;
  /** Arquivos opcionais que faltaram, para mostrar na tela. */
  avisos: string[];
}
