// Tela de revisão do professor: fila de questões "revisar", evidências do pipeline e exportação das decisões.
import { Component, useEffect, useMemo, useState, type ReactNode } from "react";
import "./App.css";
import { carregarTudo, filaRevisar, limparEnunciado, opcoesDeTroca, temasPublicaveis } from "./dados";
import { baixar, montarCsvProfessor } from "./exportar";
import { confianca, mensagemDe, resumo } from "./formato";
import type { AcaoProfessor, Conjunto, Decisao, DecisaoProfessor, Tema, Voto } from "./tipos";

type Estado =
  | { fase: "carregando" }
  | { fase: "erro"; detalhes: string[] }
  | { fase: "pronto"; conjunto: Conjunto; exemplo: boolean; motivoExemplo: string };

interface Escolha {
  acao: AcaoProfessor;
  tema_id: number | null;
}

const BASE = import.meta.env.BASE_URL.replace(/\/+$/, "");
const NOME_EXPORTADO = "decisoes_professor.csv";

const ORIGENS: Record<string, string> = {
  tema: "descrição do tema",
  corpus: "questões parecidas",
  pai: "pai de candidato",
};

const ROTULOS_ACAO: Record<AcaoProfessor, string> = {
  confirmar: "confirmada",
  trocar: "trocada",
  fora: "fora",
};

function caminhoDe(temas: Map<number, Tema>, id: number | null): string {
  if (id === null) return "sem tema";
  return temas.get(id)?.caminho ?? `tema ${id} (não está na árvore)`;
}

export default function App() {
  const [estado, setEstado] = useState<Estado>({ fase: "carregando" });

  useEffect(() => {
    let ativo = true;
    async function carregar() {
      try {
        const conjunto = await carregarTudo(`${BASE}/dados`);
        if (ativo) setEstado({ fase: "pronto", conjunto, exemplo: false, motivoExemplo: "" });
      } catch (erroReal) {
        try {
          const conjunto = await carregarTudo(`${BASE}/dados-exemplo`);
          if (ativo) setEstado({ fase: "pronto", conjunto, exemplo: true, motivoExemplo: mensagemDe(erroReal) });
        } catch (erroExemplo) {
          if (ativo) setEstado({ fase: "erro", detalhes: [mensagemDe(erroReal), mensagemDe(erroExemplo)] });
        }
      }
    }
    void carregar();
    return () => {
      ativo = false;
    };
  }, []);

  if (estado.fase === "carregando") {
    return (
      <main className="centro">
        <p className="carregando">Carregando os dados…</p>
      </main>
    );
  }
  if (estado.fase === "erro") return <SemDados detalhes={estado.detalhes} />;
  return (
    <Protecao>
      <Revisao conjunto={estado.conjunto} exemplo={estado.exemplo} motivoExemplo={estado.motivoExemplo} />
    </Protecao>
  );
}

function SemDados({ detalhes }: { detalhes: string[] }) {
  return (
    <main className="centro">
      <div className="cartao-aviso">
        <h1>Não encontrei os dados</h1>
        <p>
          A tela lê arquivos estáticos de <code>public/dados/</code> e, na falta deles, os de exemplo em{" "}
          <code>public/dados-exemplo/</code>. Nenhum dos dois carregou.
        </p>
        <p>
          Na pasta <code>revisao-ui</code>, rode <code>npm run dados</code> para copiar <code>publicacao.csv</code>,{" "}
          <code>questoes.jsonl</code>, <code>temas.csv</code> e os intermediários do pipeline, e recarregue a página.
        </p>
        <details open>
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

/** Se algo quebrar ao desenhar a tela, mostra o erro em vez de uma página em branco. */
class Protecao extends Component<{ children: ReactNode }, { erro: Error | null }> {
  state = { erro: null as Error | null };

  static getDerivedStateFromError(erro: Error) {
    return { erro };
  }

  render() {
    if (this.state.erro) {
      return (
        <main className="centro">
          <div className="cartao-aviso">
            <h1>A tela não conseguiu mostrar estes dados</h1>
            <p>Confira se os arquivos em <code>public/dados/</code> vieram da mesma execução do pipeline.</p>
            <p>
              <code>{this.state.erro.message}</code>
            </p>
          </div>
        </main>
      );
    }
    return this.props.children;
  }
}

interface PropsRevisao {
  conjunto: Conjunto;
  exemplo: boolean;
  motivoExemplo: string;
}

function Revisao({ conjunto, exemplo, motivoExemplo }: PropsRevisao) {
  const fila = useMemo(() => filaRevisar(conjunto), [conjunto]);
  const publicaveis = useMemo(() => temasPublicaveis([...conjunto.temas.values()]), [conjunto]);
  const idsPublicaveis = useMemo(() => new Set(publicaveis.map((tema) => tema.tema_id)), [publicaveis]);
  const textos = useMemo(
    () => new Map(fila.map((d) => [d.id, limparEnunciado(conjunto.questoes.get(d.id)?.enunciado_html ?? "")])),
    [fila, conjunto],
  );

  const [selecionada, setSelecionada] = useState<string | null>(fila[0]?.id ?? null);
  const [escolhas, setEscolhas] = useState<Record<string, Escolha>>({});
  const [observacoes, setObservacoes] = useState<Record<string, string>>({});
  const [naoExportado, setNaoExportado] = useState(false);

  // O estado vive só em memória: avisa antes de fechar a aba com decisões ainda não exportadas.
  useEffect(() => {
    if (!naoExportado) return;
    const avisar = (evento: BeforeUnloadEvent) => evento.preventDefault();
    window.addEventListener("beforeunload", avisar);
    return () => window.removeEventListener("beforeunload", avisar);
  }, [naoExportado]);

  const revisadas = fila.filter((d) => escolhas[d.id]).length;
  const atual = fila.find((d) => d.id === selecionada) ?? null;

  function decidir(id: string, escolha: Escolha) {
    // Defesa extra: nunca registra tema que não seja publicável.
    if (escolha.tema_id !== null && !idsPublicaveis.has(escolha.tema_id)) return;
    setEscolhas((anteriores) => ({ ...anteriores, [id]: escolha }));
    setNaoExportado(true);
  }

  function desfazer(id: string) {
    setEscolhas((anteriores) => {
      const copia = { ...anteriores };
      delete copia[id];
      return copia;
    });
    setNaoExportado(true);
  }

  function anotar(id: string, texto: string) {
    setObservacoes((anteriores) => ({ ...anteriores, [id]: texto }));
    if (escolhas[id]) setNaoExportado(true);
  }

  function proximaPendente() {
    const inicio = fila.findIndex((d) => d.id === selecionada);
    for (let passo = 1; passo <= fila.length; passo++) {
      const candidata = fila[(inicio + passo) % fila.length];
      if (!escolhas[candidata.id]) {
        setSelecionada(candidata.id);
        return;
      }
    }
  }

  function exportar() {
    const linhas: DecisaoProfessor[] = fila
      .filter((d) => escolhas[d.id])
      .map((d) => ({
        id: d.id,
        acao: escolhas[d.id].acao,
        tema_id: escolhas[d.id].tema_id,
        observacao: (observacoes[d.id] ?? "").trim(),
      }));
    baixar(NOME_EXPORTADO, montarCsvProfessor(linhas));
    setNaoExportado(false);
  }

  return (
    <div className="app">
      <header className="topo">
        <div>
          <h1>Revisão de questões</h1>
          <p className="subtitulo">Questões que o classificador mandou para revisão humana</p>
        </div>
        <div className="topo-acoes">
          <span className="contador" aria-live="polite">
            {revisadas} de {fila.length} revisadas
          </span>
          <button
            type="button"
            className="primario"
            onClick={exportar}
            disabled={revisadas === 0}
            title={`Baixa ${NOME_EXPORTADO} com as questões já decididas`}
          >
            Exportar CSV
          </button>
        </div>
      </header>

      {exemplo && (
        <div className="faixa faixa-exemplo" role="status">
          <strong>Usando dados de exemplo.</strong> As questões são inventadas para demonstrar a tela; os temas são os
          da árvore real. Para revisar as questões de verdade, rode <code>npm run dados</code> e recarregue a página.
          <span className="faixa-detalhe"> Motivo: {motivoExemplo}.</span>
        </div>
      )}
      {conjunto.avisos.length > 0 && (
        <div className="faixa faixa-aviso" role="status">
          Alguns intermediários não vieram, então parte das evidências fica em branco: {conjunto.avisos.join("; ")}.
        </div>
      )}

      {fila.length === 0 ? (
        <main className="centro">
          <div className="cartao-aviso">
            <h1>Nenhuma questão para revisar</h1>
            <p>
              O <code>publicacao.csv</code> carregado tem {conjunto.publicacao.length} questões e nenhuma com decisão{" "}
              <code>revisar</code>.
            </p>
          </div>
        </main>
      ) : (
        <div className="corpo">
          <nav className="fila" aria-label="Questões a revisar">
            <ul>
              {fila.map((d) => (
                <ItemFila
                  key={d.id}
                  decisao={d}
                  texto={textos.get(d.id) ?? ""}
                  tema={conjunto.temas.get(d.tema_central_id ?? -1)}
                  escolha={escolhas[d.id]}
                  ativo={d.id === selecionada}
                  aoSelecionar={() => setSelecionada(d.id)}
                />
              ))}
            </ul>
          </nav>
          {atual ? (
            <Painel
              key={atual.id}
              decisao={atual}
              conjunto={conjunto}
              publicaveis={publicaveis}
              idsPublicaveis={idsPublicaveis}
              escolha={escolhas[atual.id]}
              observacao={observacoes[atual.id] ?? ""}
              aoDecidir={(escolha) => decidir(atual.id, escolha)}
              aoDesfazer={() => desfazer(atual.id)}
              aoAnotar={(texto) => anotar(atual.id, texto)}
              aoProxima={proximaPendente}
              haPendentes={revisadas < fila.length}
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
  decisao: Decisao;
  texto: string;
  tema: Tema | undefined;
  escolha: Escolha | undefined;
  ativo: boolean;
  aoSelecionar: () => void;
}

function ItemFila({ decisao, texto, tema, escolha, ativo, aoSelecionar }: PropsItem) {
  return (
    <li>
      <button type="button" className={`item${ativo ? " item-ativo" : ""}`} onClick={aoSelecionar} aria-current={ativo}>
        <span className="item-topo">
          <span className="item-id">{decisao.id}</span>
          <span className={`selo selo-${escolha ? escolha.acao : "pendente"}`}>
            {escolha ? ROTULOS_ACAO[escolha.acao] : "pendente"}
          </span>
        </span>
        <span className="item-texto">{resumo(texto, 120) || "sem enunciado"}</span>
        <span className="item-tema">{tema ? tema.titulo : `tema ${decisao.tema_central_id ?? "—"}`}</span>
        <span className="item-meta">
          confiança {confianca(decisao.confianca)} · {decisao.motivo || "sem motivo"}
        </span>
      </button>
    </li>
  );
}

interface PropsPainel {
  decisao: Decisao;
  conjunto: Conjunto;
  publicaveis: Tema[];
  idsPublicaveis: Set<number>;
  escolha: Escolha | undefined;
  observacao: string;
  aoDecidir: (escolha: Escolha) => void;
  aoDesfazer: () => void;
  aoAnotar: (texto: string) => void;
  aoProxima: () => void;
  haPendentes: boolean;
}

function Painel(props: PropsPainel) {
  const { decisao, conjunto, publicaveis, idsPublicaveis, escolha, observacao } = props;
  const questao = conjunto.questoes.get(decisao.id);
  const votos = conjunto.votos.get(decisao.id);
  const candidatos = conjunto.candidatos.get(decisao.id) ?? [];
  const temas = conjunto.temas;

  const [busca, setBusca] = useState("");
  const [temaEscolhido, setTemaEscolhido] = useState("");

  const opcoes = opcoesDeTroca(candidatos, publicaveis, busca);
  const oferecidos = new Set([...opcoes.candidatos, ...opcoes.busca].map((tema) => tema.tema_id));
  const idEscolhido = temaEscolhido === "" ? null : Number(temaEscolhido);
  const escolhaValida = idEscolhido !== null && oferecidos.has(idEscolhido) && idsPublicaveis.has(idEscolhido);
  const sugestaoPublicavel = decisao.tema_central_id !== null && idsPublicaveis.has(decisao.tema_central_id);

  const escolhidoPor = (temaId: number) =>
    [
      votos?.openai?.tema_central_id === temaId ? "OpenAI" : null,
      votos?.anthropic?.tema_central_id === temaId ? "Anthropic" : null,
    ].filter(Boolean);

  return (
    <main className="painel">
      <header className="painel-topo">
        <h2>{decisao.id}</h2>
        {questao?.disciplina_origem && (
          <span className="etiqueta" title="Classificação que veio com a questão">
            origem: {questao.disciplina_origem}
            {questao.assunto_origem ? ` › ${questao.assunto_origem}` : ""}
          </span>
        )}
        {decisao.regra !== null && <span className="etiqueta">regra {decisao.regra}</span>}
      </header>

      <section className="bloco questao">
        {questao ? (
          <>
            <p className="enunciado">{limparEnunciado(questao.enunciado_html) || "(enunciado vazio)"}</p>
            {questao.comando.trim() && <p className="comando">{questao.comando.trim()}</p>}
            <ol className="alternativas">
              {Object.entries(questao.alternativas).map(([letra, texto]) => (
                <li key={letra}>
                  <span className="letra">{letra})</span> {texto.trim()}
                </li>
              ))}
            </ol>
          </>
        ) : (
          <p className="vazio">Enunciado não encontrado em questoes.jsonl.</p>
        )}
      </section>

      <section className="bloco">
        <h3>Sugestão do classificador</h3>
        <p className="caminho">{caminhoDe(temas, decisao.tema_central_id)}</p>
        <p className="meta">
          confiança {confianca(decisao.confianca)} · {decisao.motivo || "sem motivo"}
        </p>
        {decisao.extras_ids.length > 0 && (
          <div className="meta">
            Temas extras:
            <ul className="lista-simples">
              {decisao.extras_ids.map((id) => (
                <li key={id}>{caminhoDe(temas, id)}</li>
              ))}
            </ul>
          </div>
        )}
      </section>

      <section className="bloco">
        <h3>O que cada modelo escolheu</h3>
        {votos ? (
          <div className="votos">
            <CartaoVoto nome="OpenAI" voto={votos.openai} temas={temas} />
            <CartaoVoto nome="Anthropic" voto={votos.anthropic} temas={temas} />
          </div>
        ) : (
          <p className="vazio">Sem votos dos modelos para esta questão.</p>
        )}
      </section>

      <section className="bloco">
        <h3>Candidatos</h3>
        {candidatos.length > 0 ? (
          <table className="candidatos">
            <thead>
              <tr>
                <th>Tema</th>
                <th>Origem</th>
                <th className="numero">Similaridade</th>
              </tr>
            </thead>
            <tbody>
              {candidatos.map((candidato) => (
                <tr key={candidato.tema_id} className={candidato.tema_id === decisao.tema_central_id ? "sugerido" : ""}>
                  <td>
                    {caminhoDe(temas, candidato.tema_id)}
                    {candidato.tema_id === decisao.tema_central_id && <span className="selo selo-sugestao">sugestão</span>}
                    {escolhidoPor(candidato.tema_id).map((modelo) => (
                      <span key={modelo} className="selo selo-modelo">
                        {modelo}
                      </span>
                    ))}
                    {!idsPublicaveis.has(candidato.tema_id) && <span className="selo selo-alerta">não publicável</span>}
                  </td>
                  <td>{ORIGENS[candidato.origem] ?? candidato.origem}</td>
                  <td className="numero">{confianca(candidato.similaridade)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p className="vazio">Sem candidatos para esta questão.</p>
        )}
      </section>

      <section className="bloco decisao">
        <h3>Sua decisão</h3>
        {escolha && (
          <p className="decidida">
            {escolha.acao === "confirmar" && <>Sugestão confirmada: {caminhoDe(temas, escolha.tema_id)}</>}
            {escolha.acao === "trocar" && <>Tema trocado para: {caminhoDe(temas, escolha.tema_id)}</>}
            {escolha.acao === "fora" && <>Marcada como fora: nenhum tema da árvore serve</>}
            <button type="button" className="discreto" onClick={props.aoDesfazer}>
              Desfazer
            </button>
          </p>
        )}

        <div className="botoes">
          <button
            type="button"
            className="primario"
            disabled={!sugestaoPublicavel}
            title={sugestaoPublicavel ? "Mantém o tema sugerido" : "A sugestão não é um tema publicável; troque o tema"}
            onClick={() => props.aoDecidir({ acao: "confirmar", tema_id: decisao.tema_central_id })}
          >
            Confirmar
          </button>
          <button
            type="button"
            title="Nenhum tema da árvore serve para esta questão"
            onClick={() => props.aoDecidir({ acao: "fora", tema_id: null })}
          >
            Fora
          </button>
        </div>

        <div className="troca-bloco">
          <label htmlFor="busca-tema">Trocar tema</label>
          <input
            id="busca-tema"
            className="busca-tema"
            type="search"
            placeholder="Buscar em todos os temas publicáveis (ex.: prisão preventiva)"
            value={busca}
            onChange={(evento) => setBusca(evento.target.value)}
          />
          <div className="troca-linha">
            <select
              className="troca"
              aria-label="Tema para trocar"
              value={escolhaValida ? temaEscolhido : ""}
              onChange={(evento) => setTemaEscolhido(evento.target.value)}
            >
              <option value="">Escolha um tema…</option>
              {opcoes.candidatos.length > 0 && (
                <optgroup label="Candidatos desta questão">
                  {opcoes.candidatos.map((tema) => (
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
              onClick={() => idEscolhido !== null && props.aoDecidir({ acao: "trocar", tema_id: idEscolhido })}
            >
              Trocar tema
            </button>
          </div>
        </div>

        <label className="observacao">
          Observação
          <textarea
            rows={3}
            placeholder="Opcional; vai junto no CSV exportado"
            value={observacao}
            onChange={(evento) => props.aoAnotar(evento.target.value)}
          />
        </label>

        <div className="botoes">
          <button type="button" className="discreto" onClick={props.aoProxima} disabled={!props.haPendentes}>
            Próxima pendente
          </button>
        </div>
      </section>
    </main>
  );
}

function CartaoVoto({ nome, voto, temas }: { nome: string; voto: Voto | null; temas: Map<number, Tema> }) {
  return (
    <div className="voto">
      <h4>{nome}</h4>
      {voto === null ? (
        <p className="vazio">Sem resposta válida deste modelo.</p>
      ) : (
        <>
          <p className="caminho">
            {voto.tema_central_id === null ? "Nenhum candidato serve" : caminhoDe(temas, voto.tema_central_id)}
          </p>
          <p className="meta">
            disciplina {voto.disciplina ?? "—"} · confiança {confianca(voto.confianca)}
          </p>
          {voto.extras_ids.length > 0 && (
            <p className="meta">extras: {voto.extras_ids.map((id) => caminhoDe(temas, id)).join("; ")}</p>
          )}
          <p className="justificativa">{voto.justificativa || "sem justificativa"}</p>
        </>
      )}
    </div>
  );
}
