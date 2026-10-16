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

/** Uma linha de ancora_para_rotular.csv; `candidatos` e `tema_id_gilson` ficam de fora. */
export interface QuestaoAncora {
  id: string;
  disciplina_origem: string;
  /** Enunciado, "Comando: ..." e "Alternativas:" em linhas separadas. */
  texto: string;
  observacao: string;
}

/** Um tema que o rotulador pesou e descartou. */
export interface AlternativaRotulo {
  tema_id: number | null;
  caminho: string;
  motivo: string;
}

/** Uma linha de ancora_rotulos_modelo_N.jsonl. `tema_id` 0 quer dizer "fora da árvore"; nulo, que veio inválido. */
export interface Rotulo {
  id: string;
  tema_id: number | null;
  caminho: string;
  confianca: number | null;
  justificativa: string;
  alternativas: AlternativaRotulo[];
}

/** O que o professor fez numa questão da âncora: `tema_id` nulo é pendente e 0 é fora da árvore. */
export interface DecisaoAncora {
  tema_id: number | null;
  observacao: string;
}

/** Uma linha de ancora_manual.csv. */
export interface LinhaAncora {
  id: string;
  tema_id: number;
  observacao: string;
}

/** Tudo o que o modo Âncora precisa. */
export interface ConjuntoAncora {
  questoes: QuestaoAncora[];
  temas: Map<number, Tema>;
  rotulos1: Map<string, Rotulo>;
  rotulos2: Map<string, Rotulo>;
  avisos: string[];
}
