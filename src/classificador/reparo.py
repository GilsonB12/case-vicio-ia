"""Reparo de candidatos: a justificativa do voto nulo busca temas no índice e os dois modelos revotam.

Quando um modelo devolve tema_central_id nulo, a justificativa dele diz qual seria o assunto. Esse texto vira
consulta no índice de temas; os temas que ainda não estavam entre os candidatos entram na lista e os dois modelos
votam de novo sobre ela. Os votos originais ficam guardados na linha, em antes_do_reparo.
"""
from __future__ import annotations

import logging
from pathlib import Path

from langchain_core.embeddings import Embeddings

from classificador import custos
from classificador.arvore import ArvoreTemas
from classificador.candidatos import Candidato, candidatos_de_dict, candidatos_para_dict, montar_indice_temas
from classificador.config import CAMINHOS
from classificador.dados import carregar_corpus, carregar_questoes, escrever_jsonl, ler_jsonl
from classificador.indice import Indice, criar_indice
from classificador.llm import MAXIMO_NONE_CONSECUTIVOS, ClassificadorLLM, VotoModelo

registro = logging.getLogger(__name__)

K_REPARO = 5
TETO_REPARO = 18
# Mesma ordem da tupla de criar_classificadores e das chaves de votos_llm_*.jsonl.
PROVEDORES = ("openai", "anthropic")


def _voto_nulo(voto: dict | None) -> bool:
    """O modelo respondeu, mas nenhum candidato serviu."""
    return voto is not None and voto.get("tema_central_id") is None


def elegivel(linha: dict) -> bool:
    """Algum modelo respondeu sem tema. Fica de fora a questão que os dois põem em outra disciplina (regra 1)."""
    votos = [linha.get(provedor) for provedor in PROVEDORES]
    if not any(_voto_nulo(voto) for voto in votos):
        return False
    return not all(voto is not None and voto.get("disciplina") == "Outra" for voto in votos)


def expandir_candidatos(
    candidatos: list[Candidato],
    votos: dict,
    indice_temas: Indice,
    arvore: ArvoreTemas,
    k: int,
    teto: int,
) -> tuple[list[Candidato], list[int]]:
    """Lista ampliada e ids dos temas novos.

    `votos` traz os votos serializados por provedor, como numa linha de votos_llm_*.jsonl. Cada voto nulo busca
    k temas pela justificativa; os publicáveis que faltam entram com origem "reparo" e, se forem de nível 2, o pai
    entra com origem "pai". Os originais ficam na ordem em que vieram; os novos vão depois, por similaridade
    decrescente, até o teto.
    """
    presentes = {c.tema_id for c in candidatos}
    novos: dict[int, Candidato] = {}

    def registrar(tema_id: int, origem: str, similaridade: float) -> None:
        atual = novos.get(tema_id)
        if atual is None:
            novos[tema_id] = Candidato(tema_id, origem, similaridade)
        elif similaridade > atual.similaridade:
            novos[tema_id] = Candidato(tema_id, atual.origem, similaridade)

    for provedor in PROVEDORES:
        voto = votos.get(provedor)
        if not _voto_nulo(voto):
            continue
        consulta = str(voto.get("justificativa") or "").strip()
        if not consulta:
            continue
        for resultado in indice_temas.buscar(consulta, k):
            tema_id = arvore.canonico(int(resultado.metadados["tema_id"]))
            if arvore.publicavel(tema_id) and tema_id not in presentes:
                registrar(tema_id, "reparo", resultado.similaridade)
    for candidato in list(novos.values()):
        if arvore.nivel(candidato.tema_id) == 2:
            pai = arvore.pai(candidato.tema_id)
            if pai is not None and arvore.publicavel(pai) and pai not in presentes:
                registrar(pai, "pai", candidato.similaridade)
    # Na mesma similaridade o pai vem antes do filho; assim o corte no teto nunca leva o filho sem o pai.
    ordenados = sorted(novos.values(), key=lambda c: (-c.similaridade, arvore.nivel(c.tema_id)))
    acrescentados = ordenados[: max(0, teto - len(candidatos))]
    return list(candidatos) + acrescentados, [c.tema_id for c in acrescentados]


def _restaurar(linha: dict) -> dict:
    """A linha como saiu dos votos, sem o reparo de uma rodada anterior."""
    base = {chave: valor for chave, valor in linha.items() if chave not in ("reparo", "antes_do_reparo")}
    base.update(linha.get("antes_do_reparo") or {})
    return base


def _serializar(voto: VotoModelo | None) -> dict | None:
    return None if voto is None else voto.model_dump()


def _contadores(classificadores: tuple) -> dict[str, tuple[int, int]] | None:
    """Chamadas e acertos de cache por provedor, quando os classificadores expõem esses contadores."""
    if not all(hasattr(c, "chamadas") and hasattr(c, "acertos_cache") for c in classificadores):
        return None
    return {provedor: (c.chamadas, c.acertos_cache) for provedor, c in zip(PROVEDORES, classificadores)}


def rodar_reparo(
    alvo: str,
    arvore: ArvoreTemas,
    embeddings: Embeddings,
    classificadores: tuple[ClassificadorLLM, ClassificadorLLM],
    pasta: Path = CAMINHOS.intermediarios,
    criar=criar_indice,
    recalcular: bool = False,
    k_reparo: int = K_REPARO,
    teto: int = TETO_REPARO,
) -> Path:
    """Reescreve votos_llm_{alvo}.jsonl com os votos revotados e grava candidatos_{alvo}_reparo.jsonl.

    Linhas já reparadas são puladas; com recalcular, o reparo é refeito a partir dos votos originais.
    """
    if alvo not in {"questoes", "corpus"}:
        raise ValueError("alvo deve ser 'questoes' ou 'corpus'")
    caminho_votos = pasta / f"votos_llm_{alvo}.jsonl"
    caminho_candidatos = pasta / f"candidatos_{alvo}_p2.jsonl"
    caminho_reparo = pasta / f"candidatos_{alvo}_reparo.jsonl"
    for caminho, comando in (
        (caminho_votos, f"classificar votos --alvo {alvo}"),
        (caminho_candidatos, f"classificar candidatos --alvo {alvo} --passada 2"),
    ):
        if not caminho.exists():
            raise FileNotFoundError(f"{caminho} não existe; rode `{comando}` antes do reparo")

    linhas = [_restaurar(linha) if recalcular else linha for linha in ler_jsonl(caminho_votos)]
    puladas = sum(1 for linha in linhas if "reparo" in linha)
    pendentes = [posicao for posicao, linha in enumerate(linhas) if "reparo" not in linha and elegivel(linha)]
    # Sem recalcular, as listas ampliadas das questões já reparadas continuam no arquivo de candidatos do reparo.
    anteriores = {}
    if not recalcular and caminho_reparo.exists():
        anteriores = {str(l["id"]): l["candidatos"] for l in ler_jsonl(caminho_reparo)}

    saida = list(linhas)
    listas: dict[str, list[Candidato]] = {}
    resolvidos = 0
    antes = _contadores(classificadores)
    if pendentes:
        candidatos = {str(l["id"]): candidatos_de_dict(l["candidatos"]) for l in ler_jsonl(caminho_candidatos)}
        df = carregar_questoes() if alvo == "questoes" else carregar_corpus()
        textos = {str(i): t for i, t in zip(df["id"], df["texto"])}
        sem_voto_seguidas = [0] * len(PROVEDORES)
        indice: Indice | None = None
        try:
            with custos.contexto(etapa="reparo", alvo=alvo):
                indice = montar_indice_temas(arvore, embeddings, criar)
            for posicao in pendentes:
                linha = linhas[posicao]
                id_ = str(linha["id"])
                if id_ not in candidatos:
                    raise KeyError(f"questão {id_} sem candidatos em {caminho_candidatos}; gere os candidatos de novo")
                if id_ not in textos:
                    raise KeyError(f"questão {id_} dos votos não está entre as questões do alvo '{alvo}'")
                # A busca pela justificativa (embedding) e as revotações entram no livro-razão com a questão.
                with custos.contexto(etapa="reparo", alvo=alvo, id_questao=id_):
                    lista, novos = expandir_candidatos(candidatos[id_], linha, indice, arvore, k_reparo, teto)
                    if not novos:
                        saida[posicao] = {**linha, "reparo": {"novos": [], "revotado": False}}
                        continue
                    revotos: dict[str, dict | None] = {}
                    for indice_clf, (provedor, classificador) in enumerate(zip(PROVEDORES, classificadores)):
                        voto = classificador.classificar(textos[id_], lista, arvore)
                        # Disjuntor, como nos votos: sem voto várias vezes seguidas é chave, cota ou modelo com problema.
                        sem_voto_seguidas[indice_clf] = sem_voto_seguidas[indice_clf] + 1 if voto is None else 0
                        if sem_voto_seguidas[indice_clf] >= MAXIMO_NONE_CONSECUTIVOS:
                            raise RuntimeError(
                                f"classificador '{getattr(classificador, 'nome', provedor)}' ficou sem voto em "
                                f"{MAXIMO_NONE_CONSECUTIVOS} revotações seguidas (última: {id_}); reparo interrompido "
                                "sem regravar os votos. Rode `classificar votos --verificar` para checar chave, modelo e cota."
                            )
                        revotos[provedor] = _serializar(voto)
                        if _voto_nulo(linha.get(provedor)) and voto is not None and voto.tema_central_id is not None:
                            resolvidos += 1
                    saida[posicao] = {
                        **linha,
                        **revotos,
                        "antes_do_reparo": {provedor: linha.get(provedor) for provedor in PROVEDORES},
                        "reparo": {"novos": novos, "revotado": True},
                    }
                    listas[id_] = lista
        finally:
            # O Weaviate abre uma conexão por índice; o substituto em memória ignora o fechamento.
            if indice is not None:
                indice.fechar()

    linhas_reparo: list[dict] = []
    for linha in saida:
        if not (linha.get("reparo") or {}).get("revotado"):
            continue
        id_ = str(linha["id"])
        if id_ in listas:
            linhas_reparo.append({"id": id_, "candidatos": candidatos_para_dict(listas[id_])})
        elif id_ in anteriores:
            linhas_reparo.append({"id": id_, "candidatos": anteriores[id_]})
        else:
            registro.warning("questão %s revotada numa rodada anterior sem lista em %s; rode o reparo com --recalcular",
                             id_, caminho_reparo)
    escrever_jsonl(caminho_votos, saida)
    escrever_jsonl(caminho_reparo, linhas_reparo)

    resumo = (
        f"reparo {alvo}: {len(pendentes)} elegíveis, {len(listas)} revotadas, {len(pendentes) - len(listas)} sem tema novo, "
        f"{puladas} já reparadas e puladas; {resolvidos} votos nulos deixaram de ser nulos"
    )
    depois = _contadores(classificadores)
    if antes is not None and depois is not None:
        chamadas = " ".join(f"{p}={depois[p][0] - antes[p][0]}" for p in PROVEDORES)
        cache = " ".join(f"{p}={depois[p][1] - antes[p][1]}" for p in PROVEDORES)
        resumo += f"; chamadas {chamadas}, cache {cache}"
    registro.info("gravado %s e %s; %s", caminho_votos, caminho_reparo, resumo)
    return caminho_votos
