"""Serviço da API: reaproveita o pipeline, com cada peça carregada uma vez só, no primeiro uso."""
from __future__ import annotations

import logging
import threading
from typing import Any, Callable

from classificador import candidatos, custos, decisao, llm, vizinhanca
from classificador.arvore import ArvoreTemas
from classificador.config import CAMINHOS, ler_env
from classificador.dados import carregar_corpus, montar_texto
from classificador.embeddings import EmbeddingsComCache, criar_embeddings
from classificador.indice import Indice, conectar_weaviate

registro = logging.getLogger(__name__)

# A decisão pede um id; a questão avulsa da API não tem, e o id não volta na resposta.
ID_AVULSA = "avulsa"


class _Preguicosa:
    """Atributo construído no primeiro acesso e guardado na instância.

    A trava impede que duas requisições simultâneas construam a mesma peça duas vezes: no Weaviate, a segunda
    construção apagaria a coleção que a primeira acabou de montar. Se a construção falha, nada fica guardado
    e o próximo acesso tenta de novo.
    """

    def __init__(self, fabrica: Callable[[Any], Any]) -> None:
        self._fabrica = fabrica
        self._trava = threading.Lock()
        self.__doc__ = fabrica.__doc__

    def __set_name__(self, dono: type, nome: str) -> None:
        self._nome = nome

    def __get__(self, instancia: Any, dono: type | None = None) -> Any:
        if instancia is None:
            return self
        with self._trava:
            if self._nome not in instancia.__dict__:
                instancia.__dict__[self._nome] = self._fabrica(instancia)
        return instancia.__dict__[self._nome]


class Servico:
    """Classifica uma questão por vez com as mesmas peças do pipeline em lote."""

    def __init__(self) -> None:
        """Não carrega nada: árvore, embeddings, índices, classificadores e limiares nascem no primeiro uso."""

    @_Preguicosa
    def arvore(self) -> ArvoreTemas:
        return ArvoreTemas.carregar()

    @_Preguicosa
    def embeddings(self) -> EmbeddingsComCache:
        return criar_embeddings()

    @_Preguicosa
    def indice_temas(self) -> Indice:
        return candidatos.montar_indice_temas(self.arvore, self.embeddings)

    @_Preguicosa
    def indice_corpus(self) -> Indice | None:
        """Índice do corpus de referência; None sem corpus, e então a vizinhança vota nulo."""
        if not CAMINHOS.corpus.exists():
            registro.warning("corpus ausente em %s; candidatos só pelos temas e vizinhança nula", CAMINHOS.corpus)
            return None
        return candidatos.montar_indice_corpus(carregar_corpus(CAMINHOS.corpus), self.arvore, self.embeddings)

    @_Preguicosa
    def classificadores(self) -> tuple[llm.ClassificadorLLM, llm.ClassificadorLLM]:
        return llm.criar_classificadores()

    @_Preguicosa
    def limiares(self) -> decisao.Limiares:
        return decisao.carregar_limiares()

    @_Preguicosa
    def template(self) -> str:
        """Prompt de classificação; o mesmo que os classificadores carregam."""
        return llm.carregar_prompt()

    def classificar(self, enunciado_html: str, comando: str, alternativas: dict[str, str]) -> dict:
        """Candidatos, os dois votos de modelo, o voto de vizinhança e a decisão para uma questão.

        Sem chave de API e sem cache para a questão, sobe ChaveAusenteError (dos embeddings ou dos modelos).
        """
        arvore = self.arvore
        texto = montar_texto(enunciado_html, comando, alternativas)
        # Embeddings (inclusive os dos índices montados no primeiro uso) e votos entram no livro-razão como api.
        with custos.contexto(etapa="api", alvo="api", id_questao=ID_AVULSA):
            indice_corpus = self.indice_corpus
            lista = candidatos.buscar_candidatos(texto, self.indice_temas, arvore, indice_corpus)
            openai, anthropic = self.classificadores
            voto_a = openai.classificar(texto, lista, arvore)
            voto_b = anthropic.classificar(texto, lista, arvore)
            voto_vizinhanca = (
                vizinhanca.VOTO_NULO if indice_corpus is None else vizinhanca.votar_vizinhanca(texto, indice_corpus, arvore)
            )
        decidido = decisao.decidir(ID_AVULSA, voto_a, voto_b, voto_vizinhanca, lista, arvore, self.limiares)
        return {
            "decisao": decidido.decisao,
            "tema_central_id": decidido.tema_central_id,
            "caminho": None if decidido.tema_central_id is None else arvore.caminho(decidido.tema_central_id),
            "extras_ids": decidido.extras_ids,
            "confianca": decidido.confianca,
            "motivo": decidido.motivo,
            "regra": decidido.regra,
            "candidatos": [
                {"tema_id": c.tema_id, "caminho": arvore.caminho(c.tema_id), "origem": c.origem, "similaridade": c.similaridade}
                for c in lista
            ],
            "votos": {
                "openai": None if voto_a is None else voto_a.model_dump(),
                "anthropic": None if voto_b is None else voto_b.model_dump(),
                "vizinhanca": voto_vizinhanca.para_dict(),
            },
        }

    def saude(self) -> dict:
        """Chaves presentes, Weaviate alcançável (respeitando USAR_WEAVIATE), corpus, votos em cache e limiares."""
        try:
            cliente = conectar_weaviate()
        except Exception as erro:  # USAR_WEAVIATE=sim com o Weaviate fora do ar
            registro.warning("Weaviate indisponível: %s", erro)
            cliente = None
        if cliente is not None:
            cliente.close()
        pasta_votos = CAMINHOS.cache / "llm"
        return {
            "chaves": {"openai": bool(ler_env("OPENAI_API_KEY")), "anthropic": bool(ler_env("ANTHROPIC_API_KEY"))},
            "weaviate": cliente is not None,
            "corpus": CAMINHOS.corpus.exists(),
            "cache_votos": sum(1 for _ in pasta_votos.rglob("*.json")) if pasta_votos.exists() else 0,
            "limiares": self.limiares.para_dict(),
        }

    def temas(self) -> list[dict]:
        """Temas publicáveis (ativos, canônicos, fora das raízes); só a árvore é carregada."""
        arvore = self.arvore
        return [
            {"tema_id": t, "caminho": arvore.caminho(t), "nivel": arvore.nivel(t), "disciplina": arvore.disciplina(t)}
            for t in arvore.candidatos_possiveis()
        ]

    def fechar(self) -> None:
        """Fecha os índices já construídos (no Weaviate, cada um guarda uma conexão)."""
        for nome in ("indice_temas", "indice_corpus"):
            indice = self.__dict__.pop(nome, None)
            if indice is not None:
                indice.fechar()
