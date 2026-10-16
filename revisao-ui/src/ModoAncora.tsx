// Modo Âncora: o professor fecha o gabarito de referência das 40 questões a partir das propostas de dois
// rotuladores independentes e exporta ancora_manual.csv. As decisões ficam guardadas no navegador.
import { useEffect, useMemo, useState } from "react";
import {
  ARQUIVO_ANCORA,
  carregarAncora,
  concordam,
  lerDecisoesSalvas,
  montarCsvAncora,
  opcoesAncora,
  salvarDecisoes,
  TEMA_FORA,
} from "./ancora";
import { temasPublicaveis } from "./dados";
import { baixar } from "./exportar";
import { confianca, mensagemDe, resumo } from "./formato";
import type { ConjuntoAncora, DecisaoAncora, LinhaAncora, QuestaoAncora, Rotulo, Tema } from "./tipos";

type Estado =
  | { fase: "carregando" }
  | { fase: "sem-ancora"; detalhes: string[] }
  | { fase: "pronto"; conjunto: ConjuntoAncora; exemplo: boolean; motivoExemplo: string };

const BASE = import.meta.env.BASE_URL.replace(/\/+$/, "");
const NOME_EXPORTADO = "ancora_manual.csv";
const ROTULADORES = ["Rotulador 1", "Rotulador 2"] as const;

/** Lê de public/dados/; sem a âncora lá (ou com erro nela), cai em public/dados-exemplo/. */
async function carregarComReserva(): Promise<Estado> {
  let motivo: string;
  try {
    const real = await carregarAncora(`${BASE}/dados`);
    if (real) return { fase: "pronto", conjunto: real, exemplo: false, motivoExemplo: "" };
    motivo = `${ARQUIVO_ANCORA} não está em public/dados/`;
  } catch (erro) {
    motivo = mensagemDe(erro);
  }
  try {
    const exemplo = await carregarAncora(`${BASE}/dados-exemplo`);
    if (exemplo) return { fase: "pronto", conjunto: exemplo, exemplo: true, motivoExemplo: motivo };
    return { fase: "sem-ancora", detalhes: [motivo, `${ARQUIVO_ANCORA} também não está em public/dados-exemplo/`] };
  } catch (erro) {
    return { fase: "sem-ancora", detalhes: [motivo, mensagemDe(erro)] };
  }
}

export default function ModoAncora() {
  const [estado, setEstado] = useState<Estado>({ fase: "carregando" });

  useEffect(() => {
    let ativo = true;
    void carregarComReserva().then((novo) => {
      if (ativo) setEstado(novo);
    });
    return () => {
      ativo = false;
    };
  }, []);

  if (estado.fase === "carregando") {
    return (
      <main className="centro">
        <p className="carregando">Carregando a âncora…</p>
      </main>
    );
  }
  if (estado.fase === "sem-ancora") return <SemAncora detalhes={estado.detalhes} />;
  return <TelaAncora conjunto={estado.conjunto} exemplo={estado.exemplo} motivoExemplo={estado.motivoExemplo} />;
}

function SemAncora({ detalhes }: { detalhes: string[] }) {
  return (
    <main className="centro">
      <div className="cartao-aviso">
        <h1>Não encontrei a âncora</h1>
        <p>
          O modo Âncora lê <code>{ARQUIVO_ANCORA}</code>, os rótulos <code>ancora_rotulos_modelo_1.jsonl</code> e{" "}
          <code>ancora_rotulos_modelo_2.jsonl</code> e <code>temas.csv</code> de <code>public/dados/</code>.
        </p>
        <p>
          Na pasta <code>revisao-ui</code>, rode <code>npm run dados</code> para copiar esses arquivos de{" "}
          <code>data/</code> e recarregue a página. A fila de revisão continua disponível no outro modo.
        </p>
        <details>
          <summary>O que deu errado</summary>
          <ul>
            {detalhes.map((detalhe) => (
              <li key={detalhe}>
                <code>{detalhe}</code>
              </li>
            ))}
          </ul>
        </details>
      </div>
    </main>
  );
}

function decidida(decisao: DecisaoAncora | undefined): decisao is DecisaoAncora & { tema_id: number } {
  return decisao !== undefined && decisao.tema_id !== null;
}

/** Caminho do tema pela árvore; o que o rotulador escreveu só aparece quando o id não está nela. */
function caminhoTema(temas: Map<number, Tema>, id: number | null, escrito = ""): string {
  if (id === TEMA_FORA) return "Fora da árvore";
  if (id === null) return escrito ? `${escrito} (sem tema_id válido)` : "sem tema_id válido";
  const tema = temas.get(id);
  if (tema) return tema.caminho;
  return `tema ${id} (não está na árvore)${escrito ? `: ${escrito}` : ""}`;
}

function situacaoRotulos(r1: Rotulo | undefined, r2: Rotulo | undefined): string {
  if (r1 && r2) return concordam(r1, r2) ? "rotuladores concordam" : "rotuladores divergem";
  if (r1 || r2) return `só o ${r1 ? ROTULADORES[0] : ROTULADORES[1]} rotulou`;
  return "sem rótulo";
}

interface PropsTela {
  conjunto: ConjuntoAncora;
  exemplo: boolean;
  motivoExemplo: string;
}

function TelaAncora({ conjunto, exemplo, motivoExemplo }: PropsTela) {
  const { questoes, temas, rotulos1, rotulos2, avisos } = conjunto;
  const publicaveis = useMemo(() => temasPublicaveis([...temas.values()]), [temas]);
  const idsPublicaveis = useMemo(() => new Set(publicaveis.map((tema) => tema.tema_id)), [publicaveis]);
  const valido = (id: number) => id === TEMA_FORA || idsPublicaveis.has(id);

  // Decisão guardada com tema que não é mais publicável volta a pendente; a observação fica.
  const [decisoes, setDecisoes] = useState<Record<string, DecisaoAncora>>(() => {
    const salvas = lerDecisoesSalvas();
    for (const [id, decisao] of Object.entries(salvas)) {
      if (decisao.tema_id !== null && !valido(decisao.tema_id)) salvas[id] = { ...decisao, tema_id: null };
    }
    return salvas;
  });
  const [salvou, setSalvou] = useState(true);
  const [selecionada, setSelecionada] = useState<string | null>(questoes[0]?.id ?? null);
  const [avisoExportacao, setAvisoExportacao] = useState<string | null>(null);

  useEffect(() => {
    setSalvou(salvarDecisoes(decisoes));
  }, [decisoes]);

  // Sem localStorage as decisões só vivem na aba: avisa antes de fechá-la.
  useEffect(() => {
    if (salvou) return;
    const avisar = (evento: BeforeUnloadEvent) => evento.preventDefault();
    window.addEventListener("beforeunload", avisar);
    return () => window.removeEventListener("beforeunload", avisar);
  }, [salvou]);

  const porId = useMemo(() => new Map(questoes.map((questao) => [questao.id, questao])), [questoes]);
  const totalDecididas = questoes.filter((questao) => decidida(decisoes[questao.id])).length;
  const atual = selecionada === null ? null : (porId.get(selecionada) ?? null);

  const observacaoDe = (id: string) => decisoes[id]?.observacao ?? porId.get(id)?.observacao ?? "";

  function decidir(id: string, tema_id: number) {
    if (!valido(tema_id)) return;
    setDecisoes((anteriores) => ({
      ...anteriores,
      [id]: { tema_id, observacao: anteriores[id]?.observacao ?? porId.get(id)?.observacao ?? "" },
    }));
  }

  function desfazer(id: string) {
    setDecisoes((anteriores) =>
      anteriores[id] ? { ...anteriores, [id]: { ...anteriores[id], tema_id: null } } : anteriores,
    );
  }

  function anotar(id: string, texto: string) {
    setDecisoes((anteriores) => ({ ...anteriores, [id]: { tema_id: anteriores[id]?.tema_id ?? null, observacao: texto } }));
  }

  function proximaPendente() {
    const inicio = questoes.findIndex((questao) => questao.id === selecionada);
    for (let passo = 1; passo <= questoes.length; passo++) {
      const candidata = questoes[(inicio + passo) % questoes.length];
      if (!decidida(decisoes[candidata.id])) {
        setSelecionada(candidata.id);
        return;
      }
    }
  }

  function exportar() {
    const linhas: LinhaAncora[] = questoes.flatMap((questao) => {
      const decisao = decisoes[questao.id];
      if (!decidida(decisao) || !valido(decisao.tema_id)) return [];
      return [{ id: questao.id, tema_id: decisao.tema_id, observacao: decisao.observacao.trim() }];
    });
    baixar(NOME_EXPORTADO, montarCsvAncora(linhas));
    const faltam = questoes.length - linhas.length;
    setAvisoExportacao(
      faltam > 0
        ? `${NOME_EXPORTADO} saiu com ${linhas.length} de ${questoes.length} questões; ${faltam} ainda pendentes ficaram de fora.`
        : null,
    );
  }

  const faltam = questoes.length - totalDecididas;

  return (
    <div className="app ancora">
      <header className="topo">
        <div>
          <h1>Âncora: gabarito de referência</h1>
          <p className="subtitulo">
            Dois rotuladores independentes propõem um tema para cada questão; o tema final é o seu
          </p>
        </div>
        <div className="topo-acoes">
          <span className="contador" aria-live="polite">
            {totalDecididas} de {questoes.length} decididas
          </span>
          <button
            type="button"
            className="primario"
            onClick={exportar}
            disabled={totalDecididas === 0}
            title={
              faltam > 0
                ? `Ainda faltam ${faltam}; o arquivo sai só com as ${totalDecididas} decididas`
                : `Baixa ${NOME_EXPORTADO} com as ${totalDecididas} questões`
            }
          >
            Exportar {NOME_EXPORTADO}
          </button>
        </div>
      </header>

      {exemplo && (
        <div className="faixa faixa-exemplo" role="status">
          <strong>Usando dados de exemplo.</strong> As 40 questões são as do case, mas os rótulos são inventados para
          demonstrar a tela e só cobrem algumas questões. Para usar os rótulos de verdade, rode{" "}
          <code>npm run dados</code> e recarregue a página.
          <span className="faixa-detalhe"> Motivo: {motivoExemplo}.</span>
        </div>
      )}
      {avisos.length > 0 && (
        <div className="faixa faixa-aviso" role="status">
          {avisos.join("; ")}.
        </div>
      )}
      {!salvou && (
        <div className="faixa faixa-perigo" role="alert">
          O navegador não deixou guardar as decisões; elas somem se a página for recarregada. Exporte antes de fechar
          a aba.
        </div>
      )}
      {avisoExportacao && (
        <div className="faixa faixa-exemplo" role="status">
          {avisoExportacao}
          <button type="button" className="discreto" onClick={() => setAvisoExportacao(null)}>
            Fechar
          </button>
        </div>
      )}

      {questoes.length === 0 ? (
        <main className="centro">
          <div className="cartao-aviso">
            <h1>A âncora está vazia</h1>
            <p>
              <code>{ARQUIVO_ANCORA}</code> carregou, mas não tem nenhuma questão.
            </p>
          </div>
        </main>
      ) : (
        <div className="corpo">
          <nav className="fila" aria-label="Questões da âncora">
            <ul>
              {questoes.map((questao) => (
                <ItemAncora
                  key={questao.id}
                  questao={questao}
                  decisao={decisoes[questao.id]}
                  temas={temas}
                  situacao={situacaoRotulos(rotulos1.get(questao.id), rotulos2.get(questao.id))}
                  ativo={questao.id === selecionada}
                  aoSelecionar={() => setSelecionada(questao.id)}
                />
              ))}
            </ul>
          </nav>
          {atual ? (
            <PainelAncora
              key={atual.id}
              questao={atual}
              rotulos={[rotulos1.get(atual.id), rotulos2.get(atual.id)]}
              temas={temas}
              publicaveis={publicaveis}
              valido={valido}
              decisao={decisoes[atual.id]}
              observacao={observacaoDe(atual.id)}
              aoDecidir={(tema_id) => decidir(atual.id, tema_id)}
              aoDesfazer={() => desfazer(atual.id)}
              aoAnotar={(texto) => anotar(atual.id, texto)}
              aoProxima={proximaPendente}
              haPendentes={faltam > 0}
            />
          ) : (
            <main className="painel centro">
              <p className="vazio">Escolha uma questão na lista.</p>
            </main>
          )}
        </div>
      )}
    </div>
  );
}

interface PropsItem {
  questao: QuestaoAncora;
  decisao: DecisaoAncora | undefined;
  temas: Map<number, Tema>;
  situacao: string;
  ativo: boolean;
  aoSelecionar: () => void;
}

function ItemAncora({ questao, decisao, temas, situacao, ativo, aoSelecionar }: PropsItem) {
  const feita = decidida(decisao);
  return (
    <li>
      <button type="button" className={`item${ativo ? " item-ativo" : ""}`} onClick={aoSelecionar} aria-current={ativo}>
        <span className="item-topo">
          <span className="item-id">{questao.id}</span>
          <span className={`selo selo-${feita ? "decidida" : "pendente"}`}>{feita ? "decidida" : "pendente"}</span>
        </span>
        <span className="item-texto">{resumo(questao.texto, 110) || "sem texto"}</span>
        {feita && (
          <span className="item-tema">
            {decisao.tema_id === TEMA_FORA ? "Fora da árvore" : (temas.get(decisao.tema_id)?.titulo ?? `tema ${decisao.tema_id}`)}
          </span>
        )}
        <span className="item-meta">{situacao}</span>
      </button>
    </li>
  );
}

interface PropsPainel {
  questao: QuestaoAncora;
  rotulos: [Rotulo | undefined, Rotulo | undefined];
  temas: Map<number, Tema>;
  publicaveis: Tema[];
  valido: (id: number) => boolean;
  decisao: DecisaoAncora | undefined;
  observacao: string;
  aoDecidir: (tema_id: number) => void;
  aoDesfazer: () => void;
  aoAnotar: (texto: string) => void;
  aoProxima: () => void;
  haPendentes: boolean;
}

function PainelAncora(props: PropsPainel) {
  const { questao, rotulos, temas, publicaveis, valido, decisao, observacao } = props;
  const [busca, setBusca] = useState("");
  const [temaEscolhido, setTemaEscolhido] = useState("");

  const iguais = concordam(rotulos[0], rotulos[1]);
  const opcoes = opcoesAncora(rotulos, temas, publicaveis, busca);
  const oferecidos = new Set([...opcoes.propostas, ...opcoes.vizinhos, ...opcoes.busca].map((tema) => tema.tema_id));
  const idEscolhido = temaEscolhido === "" ? null : Number(temaEscolhido);
  const escolhaValida = idEscolhido !== null && oferecidos.has(idEscolhido) && valido(idEscolhido);
  const feita = decidida(decisao);

  const quemPropos = (temaId: number) =>
    ROTULADORES.filter((_, i) => rotulos[i]?.tema_id === temaId).join(" e ");

  return (
    <main className="painel">
      <header className="painel-topo">
        <h2>{questao.id}</h2>
        {questao.disciplina_origem && (
          <span className="etiqueta" title="Disciplina que veio com a questão">
            origem: {questao.disciplina_origem}
          </span>
        )}
      </header>

      <section className="bloco questao">
        <p className="enunciado">{questao.texto || "(texto vazio)"}</p>
      </section>

      <section className="bloco">
        <h3>Propostas dos rotuladores</h3>
        {rotulos[0] && rotulos[1] && (
          <p className={`concordancia ${iguais ? "concordancia-sim" : "concordancia-nao"}`}>
            {iguais ? "Os dois rotuladores propõem o mesmo tema." : "Os rotuladores propõem temas diferentes."}
          </p>
        )}
        <div className="votos">
          {ROTULADORES.map((nome, i) => (
            <CartaoRotulador
              key={nome}
              nome={nome}
              rotulo={rotulos[i]}
              temas={temas}
              valido={valido}
              concorda={iguais}
            />
          ))}
        </div>
      </section>

      <section className="bloco decisao">
        <h3>Sua decisão</h3>
        {feita && (
          <p className="decidida">
            {decisao.tema_id === TEMA_FORA ? "Fora da árvore: nenhum tema serve" : `Tema final: ${caminhoTema(temas, decisao.tema_id)}`}
            {quemPropos(decisao.tema_id) && <span className="selo selo-modelo">= {quemPropos(decisao.tema_id)}</span>}
          </p>
        )}

        <div className="botoes">
          {ROTULADORES.map((nome, i) => {
            const rotulo = rotulos[i];
            const aceitavel = rotulo !== undefined && rotulo.tema_id !== null && valido(rotulo.tema_id);
            const motivo = !rotulo
              ? `O ${nome} não tem rótulo para esta questão`
              : aceitavel
                ? `Usa o tema do ${nome}: ${caminhoTema(temas, rotulo.tema_id, rotulo.caminho)}`
                : `O tema do ${nome} não é publicável; escolha outro abaixo`;
            return (
              <button
                key={nome}
                type="button"
                className="primario"
                disabled={!aceitavel}
                title={motivo}
                aria-pressed={feita && aceitavel && decisao.tema_id === rotulo.tema_id}
                onClick={() => rotulo?.tema_id != null && props.aoDecidir(rotulo.tema_id)}
              >
                Aceitar {nome}
              </button>
            );
          })}
          <button
            type="button"
            title="Nenhum tema da árvore serve para esta questão (tema_id 0)"
            aria-pressed={feita && decisao.tema_id === TEMA_FORA}
            onClick={() => props.aoDecidir(TEMA_FORA)}
          >
            Fora da árvore
          </button>
        </div>

        <div className="troca-bloco">
          <label htmlFor="ancora-busca-tema">Outro tema</label>
          <input
            id="ancora-busca-tema"
            className="ancora-busca"
            type="search"
            placeholder="Buscar em todos os temas publicáveis (ex.: furto qualificado)"
            value={busca}
            onChange={(evento) => setBusca(evento.target.value)}
          />
          <div className="troca-linha">
            <select
              className="ancora-troca"
              aria-label="Outro tema"
              value={escolhaValida ? temaEscolhido : ""}
              onChange={(evento) => setTemaEscolhido(evento.target.value)}
            >
              <option value="">Escolha um tema…</option>
              {opcoes.propostas.length > 0 && (
                <optgroup label="Propostas e alternativas dos rotuladores">
                  {opcoes.propostas.map((tema) => (
                    <option key={tema.tema_id} value={tema.tema_id}>
                      {tema.caminho}
                    </option>
                  ))}
                </optgroup>
              )}
              {opcoes.vizinhos.length > 0 && (
                <optgroup label="Vizinhos na árvore">
                  {opcoes.vizinhos.map((tema) => (
                    <option key={tema.tema_id} value={tema.tema_id}>
                      {tema.caminho}
                    </option>
                  ))}
                </optgroup>
              )}
              {busca.trim() !== "" && (
                <optgroup
                  label={
                    opcoes.totalBusca > opcoes.busca.length
                      ? `Busca: ${opcoes.busca.length} de ${opcoes.totalBusca}, refine o termo`
                      : `Busca: ${opcoes.busca.length} ${opcoes.busca.length === 1 ? "tema" : "temas"}`
                  }
                >
                  {opcoes.busca.map((tema) => (
                    <option key={tema.tema_id} value={tema.tema_id}>
                      {tema.caminho}
                    </option>
                  ))}
                </optgroup>
              )}
            </select>
            <button
              type="button"
              disabled={!escolhaValida}
              onClick={() => idEscolhido !== null && props.aoDecidir(idEscolhido)}
            >
              Usar este tema
            </button>
          </div>
        </div>

        <label className="observacao">
          Comentário
          <textarea
            rows={3}
            placeholder="Opcional; vai na coluna observacao do CSV"
            value={observacao}
            onChange={(evento) => props.aoAnotar(evento.target.value)}
          />
        </label>

        <div className="botoes">
          <button type="button" className="discreto" onClick={props.aoProxima} disabled={!props.haPendentes}>
            Próxima pendente
          </button>
          <button type="button" className="discreto" onClick={props.aoDesfazer} disabled={!feita}>
            Desfazer
          </button>
        </div>
      </section>
    </main>
  );
}

interface PropsCartao {
  nome: string;
  rotulo: Rotulo | undefined;
  temas: Map<number, Tema>;
  valido: (id: number) => boolean;
  concorda: boolean;
}

function CartaoRotulador({ nome, rotulo, temas, valido, concorda }: PropsCartao) {
  const temaArvore = rotulo?.tema_id ? temas.get(rotulo.tema_id) : undefined;
  const escritoDiferente =
    temaArvore !== undefined && rotulo !== undefined && rotulo.caminho !== "" && rotulo.caminho !== temaArvore.caminho;
  return (
    <div className={`voto rotulador${concorda ? " voto-concorda" : ""}`}>
      <h4>
        <span className="rotulador-nome">{nome}</span>
        {concorda && <span className="selo selo-concorda">mesmo tema</span>}
      </h4>
      {!rotulo ? (
        <p className="vazio">Sem rótulo para esta questão.</p>
      ) : (
        <>
          <p className="caminho">
            {caminhoTema(temas, rotulo.tema_id, rotulo.caminho)}
            {rotulo.tema_id !== null && rotulo.tema_id !== TEMA_FORA && temaArvore && !valido(rotulo.tema_id) && (
              <span className="selo selo-alerta">não publicável</span>
            )}
          </p>
          {escritoDiferente && <p className="meta">O rotulador escreveu outro caminho: {rotulo.caminho}</p>}
          <p className="meta">
            {rotulo.tema_id !== null && rotulo.tema_id !== TEMA_FORA && <>tema {rotulo.tema_id} · </>}
            confiança {confianca(rotulo.confianca)}
          </p>
          <p className="justificativa">{rotulo.justificativa || "sem justificativa"}</p>
          <div className="consideradas">
            <p className="meta">Alternativas consideradas</p>
            {rotulo.alternativas.length > 0 ? (
              <ul className="lista-simples">
                {rotulo.alternativas.map((alternativa, i) => (
                  <li key={`${alternativa.tema_id}-${i}`}>
                    <span className="consideradas-caminho">
                      {caminhoTema(temas, alternativa.tema_id, alternativa.caminho)}
                    </span>
                    {alternativa.motivo && <span className="consideradas-motivo">: {alternativa.motivo}</span>}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="vazio consideradas-vazio">Nenhuma registrada.</p>
            )}
          </div>
        </>
      )}
    </div>
  );
}
