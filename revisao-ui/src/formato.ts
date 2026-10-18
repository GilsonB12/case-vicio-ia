// Formatação de texto usada pela tela.

const formatoConfianca = new Intl.NumberFormat("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

/** Confiança com duas casas, no formato brasileiro; travessão quando não há valor. */
export function confianca(valor: number | null): string {
  return valor === null ? "—" : formatoConfianca.format(valor);
}

/** Texto corrido cortado em `limite` caracteres, com reticências. */
export function resumo(texto: string, limite: number): string {
  const corrido = texto.replace(/\s+/g, " ").trim();
  return corrido.length > limite ? `${corrido.slice(0, limite - 1).trimEnd()}…` : corrido;
}

export function mensagemDe(erro: unknown): string {
  return erro instanceof Error ? erro.message : String(erro);
}
