"""Votos dos modelos de linguagem: prompt, schema estruturado, cache e retentativas."""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import itertools
import json
import logging
import re
import time
from pathlib import Path
from typing import Callable, Literal

from pydantic import BaseModel, Field, ValidationError

from classificador import custos
from classificador.arvore import ArvoreTemas
from classificador.candidatos import Candidato, candidatos_de_dict
from classificador.config import CAMINHOS, ChaveAusenteError, ler_env
from classificador.dados import carregar_corpus, carregar_questoes, escrever_jsonl, ler_jsonl

registro = logging.getLogger(__name__)

Disciplina = Literal["Penal", "Processo Penal", "Legislação Especial", "Criminologia", "Outra"]


class VotoModelo(BaseModel):
    tema_central_id: int | None = Field(description="id do candidato escolhido; nulo se nenhum serve")
    extras_ids: list[int] = Field(default_factory=list, description="outros candidatos que a questão também cobre")
    disciplina: Disciplina = Field(description="disciplina da questão; Outra se não é nenhuma das quatro")
    confianca: float = Field(ge=0, le=1, description="chance de o tema central estar certo")
    justificativa: str = Field(description="no máximo duas frases")


class VotoInvalidoError(ValueError):
    """O modelo escolheu um tema que não estava entre os candidatos."""


# Devolve o voto e o uso de tokens da resposta (no formato de custos.normalizar_uso, ou None se desconhecido).
Invocador = Callable[[str], tuple[VotoModelo, dict | None]]

AVISO_RETENTATIVA = (
    "\n\nATENÇÃO: sua resposta anterior escolheu o id {id}, que NÃO está na lista de candidatos. "
    "Escolha somente um id da lista ou devolva tema_central_id nulo."
)
AVISO_VALIDACAO = (
    "\n\nATENÇÃO: sua resposta anterior não seguiu o schema pedido ({erro}). "
    "Responda de novo seguindo exatamente o schema."
)
MAXIMO_NONE_CONSECUTIVOS = 5
ABREVIACOES_CONFIGURACAO = {
    "effort": "effort-", "reasoning_effort": "effort-", "max_tokens": "max", "method": "", "temperature": "temp",
}


def erro_permanente(erro: Exception) -> bool:
    """Erro 4xx do provedor, exceto 429: chave, modelo ou pedido errado, que não se resolve tentando de novo.

    Os erros dos SDKs da OpenAI e da Anthropic expõem status_code; nada é importado deles aqui.
    """
    status = getattr(erro, "status_code", None)
    return isinstance(status, int) and 400 <= status <= 499 and status != 429


def erro_de_validacao(erro: BaseException) -> ValidationError | None:
    """O ValidationError da resposta, seja o próprio erro, seja a causa dele.

    O parser do LangChain para a Anthropic embrulha o ValidationError numa OutputParserException.
    """
    if isinstance(erro, ValidationError):
        return erro
    if isinstance(erro.__cause__, ValidationError):
        return erro.__cause__
    return None


def resumir_validacao(erro: ValidationError) -> str:
    return "; ".join(
        f"{'.'.join(str(p) for p in e['loc']) or 'resposta'}: {e['msg']}" for e in erro.errors(include_url=False)
    )


def slug_configuracao(configuracao: dict) -> str:
    """Rótulo curto e seguro para nome de pasta, por exemplo effort-low_max4096_json_schema."""
    partes = [f"{ABREVIACOES_CONFIGURACAO.get(chave, chave + '-')}{valor}" for chave, valor in sorted(configuracao.items())]
    return re.sub(r"[^A-Za-z0-9._-]", "-", "_".join(partes))


def _milissegundos(inicio: float) -> float:
    return round((time.perf_counter() - inicio) * 1000, 1)


def carregar_prompt(caminho: Path = CAMINHOS.prompts / "classificar.md") -> str:
    return caminho.read_text(encoding="utf-8")


def formatar_candidatos(candidatos: list[Candidato], arvore: ArvoreTemas) -> str:
    linhas = []
    for c in candidatos:
        documento = arvore.documento(c.tema_id).split("\n", 1)
        linhas.append(f"- id {c.tema_id}: {arvore.caminho(c.tema_id)}")
        if len(documento) > 1 and documento[1].strip():
            linhas.append(f"  {documento[1].strip()}")
    return "\n".join(linhas)


def montar_prompt(template: str, texto_questao: str, candidatos: list[Candidato], arvore: ArvoreTemas) -> str:
    return template.replace("{{QUESTAO}}", texto_questao).replace("{{CANDIDATOS}}", formatar_candidatos(candidatos, arvore))


class ClassificadorLLM:
    def __init__(
        self,
        nome: str,
        modelo: str,
        invocador: Invocador | None,
        pasta_cache: Path,
        template: str,
        tentativas: int = 3,
        espera_base: float = 2.0,
        dormir: Callable[[float], None] = time.sleep,
        configuracao: dict | None = None,
        livro: custos.LivroRazao | None = None,
    ) -> None:
        self.nome = nome
        self.modelo = modelo
        self.invocador = invocador
        # Parâmetros de invocação que mudam a resposta (esforço, max_tokens, método): entram na chave e na pasta do cache.
        self.configuracao = dict(configuracao or {})
        self.slug = slug_configuracao(self.configuracao)
        self.pasta = pasta_cache / "llm" / nome / (f"{modelo}__{self.slug}" if self.slug else modelo)
        self.pasta.mkdir(parents=True, exist_ok=True)
        self.template = template
        self.tentativas = tentativas
        self.espera_base = espera_base
        self.dormir = dormir
        self.livro = livro if livro is not None else custos.LIVRO
        self.chamadas = 0
        self.acertos_cache = 0

    def _arquivo(self, prompt: str) -> Path:
        schema = json.dumps(VotoModelo.model_json_schema(), sort_keys=True)
        configuracao = json.dumps(self.configuracao, sort_keys=True)
        chave = hashlib.sha256(f"{self.modelo}\n{configuracao}\n{prompt}\n{schema}".encode("utf-8")).hexdigest()
        return self.pasta / f"{chave}.json"

    def _ler_cache(self, prompt: str) -> tuple[VotoModelo, dict | None] | None:
        """Voto e uso guardados. O formato antigo, só o voto, é reconhecido pela chave tema_central_id e vem sem uso."""
        arquivo = self._arquivo(prompt)
        if not arquivo.exists():
            return None
        try:
            dados = json.loads(arquivo.read_text(encoding="utf-8"))
            if "tema_central_id" in dados:
                return VotoModelo.model_validate(dados), None
            uso = dados.get("uso")
            return VotoModelo.model_validate(dados["voto"]), uso if isinstance(uso, dict) else None
        except Exception:
            arquivo.unlink()
            return None

    def _gravar_cache(self, prompt: str, voto: VotoModelo, uso: dict | None) -> None:
        conteudo = {"voto": voto.model_dump(mode="json"), "uso": uso, "modelo": self.modelo, "quando": custos.agora_iso()}
        self._arquivo(prompt).write_text(json.dumps(conteudo, ensure_ascii=False), encoding="utf-8")

    def validar(self, voto: VotoModelo, candidatos: list[Candidato], arvore: ArvoreTemas) -> VotoModelo:
        permitidos = {c.tema_id for c in candidatos}
        central = None if voto.tema_central_id is None else arvore.canonico(voto.tema_central_id)
        if central is not None and central not in permitidos:
            raise VotoInvalidoError(str(voto.tema_central_id))
        extras: list[int] = []
        for extra in voto.extras_ids:
            if not arvore.existe(extra):
                continue
            canonico = arvore.canonico(extra)
            if canonico in permitidos and canonico != central and canonico not in extras:
                extras.append(canonico)
        return voto.model_copy(update={"tema_central_id": central, "extras_ids": extras})

    def _invocar_com_retentativas(
        self, prompt: str, anotar: Callable[..., None]
    ) -> tuple[VotoModelo, dict | None, float] | None:
        """Chama o modelo com espera exponencial em erro transitório (429, 5xx, conexão, desconhecido).

        Erro 4xx que não é 429 sobe na hora. Resposta fora do schema sobe como ValidationError, para o chamador
        tentar uma vez só com o aviso no prompt, sem passar pelas esperas. Cada tentativa que falha é anotada no
        livro-razão aqui; a que responde volta com o uso e a latência, e quem chama a anota depois de validar o voto.
        """
        assert self.invocador is not None
        for tentativa in range(self.tentativas):
            inicio = time.perf_counter()
            try:
                self.chamadas += 1
                voto, uso = self.invocador(prompt)
            except Exception as erro:
                # O invocador anexa ao erro de parse o uso da resposta que veio fora do schema.
                anotar(prompt, uso=getattr(erro, "uso_tokens", None), latencia_ms=_milissegundos(inicio), erro=erro)
                if isinstance(erro, VotoInvalidoError):
                    raise
                validacao = erro_de_validacao(erro)
                if validacao is not None:
                    if validacao is erro:
                        raise
                    raise validacao from erro
                if erro_permanente(erro):
                    registro.error("%s: erro permanente na chamada (%s); sem nova tentativa", self.nome, erro)
                    raise
                registro.warning("%s: erro na chamada (%s), tentativa %d/%d", self.nome, erro, tentativa + 1, self.tentativas)
                if tentativa + 1 < self.tentativas:
                    self.dormir(self.espera_base * (2 ** tentativa))
            else:
                return voto, uso, _milissegundos(inicio)
        return None

    def classificar(self, texto_questao: str, candidatos: list[Candidato], arvore: ArvoreTemas) -> VotoModelo | None:
        """Voto validado do cache ou do modelo; cada invocação, de cache ou real, vira uma linha no livro-razão."""
        prompt = montar_prompt(self.template, texto_questao, candidatos, arvore)
        arquivo = self._arquivo(prompt)
        tentativas = itertools.count(1)

        def anotar(enviado: str, origem: str = "api", uso: dict | None = None, latencia_ms: float | None = None,
                   voto: VotoModelo | None = None, erro: BaseException | None = None) -> None:
            self.livro.registrar(
                provedor=self.nome, modelo=self.modelo, configuracao=self.slug, origem=origem,
                tentativa=next(tentativas), hash_prompt=arquivo.stem, tamanho_prompt_chars=len(enviado),
                n_candidatos=len(candidatos), uso=uso, latencia_ms=latencia_ms, sucesso=erro is None,
                erro=None if erro is None else custos.descrever_erro(erro),
                tema_votado=None if voto is None else voto.tema_central_id,
                confianca=None if voto is None else voto.confianca,
            )

        em_cache = self._ler_cache(prompt)
        if em_cache is not None:
            voto_cache, uso_cache = em_cache
            try:
                validado = self.validar(voto_cache, candidatos, arvore)
            except VotoInvalidoError:
                arquivo.unlink()
            else:
                self.acertos_cache += 1
                anotar(prompt, origem="cache", uso=uso_cache, voto=validado)
                return validado
        if self.invocador is None:
            raise ChaveAusenteError(
                f"classificador '{self.nome}' sem chave de API e sem cache para esta questão. "
                "Defina a chave no .env ou use o cache commitado."
            )
        prompt_atual = prompt
        for rodada in range(2):
            try:
                resposta = self._invocar_com_retentativas(prompt_atual, anotar)
            except ValidationError as erro:
                resumo = resumir_validacao(erro)
                registro.warning("%s: resposta fora do schema (rodada %d): %s", self.nome, rodada + 1, resumo)
                prompt_atual = prompt + AVISO_VALIDACAO.format(erro=resumo)
                continue
            if resposta is None:
                return None
            bruto, uso, latencia_ms = resposta
            try:
                voto = self.validar(bruto, candidatos, arvore)
            except VotoInvalidoError as erro:
                anotar(prompt_atual, uso=uso, latencia_ms=latencia_ms, voto=bruto, erro=erro)
                registro.warning("%s: tema %s fora dos candidatos (rodada %d)", self.nome, erro, rodada + 1)
                prompt_atual = prompt + AVISO_RETENTATIVA.format(id=erro)
                continue
            # O voto pago vai para o cache antes da linha: se o livro falhar, a chamada não se perde.
            self._gravar_cache(prompt, voto, uso)
            anotar(prompt_atual, uso=uso, latencia_ms=latencia_ms, voto=voto)
            return voto
        return None


def configuracao_invocador(provedor: str, modelo: str) -> dict:
    """Parâmetros com que criar_invocador chama o modelo; a mesma fonte alimenta a chave do cache."""
    if provedor == "openai":
        if modelo.startswith("gpt-5") or modelo.startswith("o"):
            return {"reasoning_effort": "low", "method": "json_schema"}
        return {"temperature": 0, "method": "json_schema"}
    if provedor == "anthropic":
        # claude-sonnet-5-5 recusa temperature fora do padrão e tool_choice forçado:
        # sem temperature e com a saída estruturada nativa (json_schema) em vez de ferramenta.
        # O raciocínio adaptativo conta em max_tokens: esforço baixo e folga para não truncar o JSON.
        return {"effort": "low", "max_tokens": 4096, "method": "json_schema"}
    raise ValueError(f"provedor desconhecido: {provedor}")


def criar_invocador(provedor: str, modelo: str) -> Invocador:
    configuracao = configuracao_invocador(provedor, modelo)
    parametros = {chave: valor for chave, valor in configuracao.items() if chave != "method"}
    if provedor == "openai":
        from langchain_openai import ChatOpenAI

        base = ChatOpenAI(model=modelo, **parametros)
    else:
        from langchain_anthropic import ChatAnthropic

        # effort é o apelido do campo reasoning_effort no ChatAnthropic.
        base = ChatAnthropic(model=modelo, **parametros)
    # include_raw traz a mensagem crua junto do voto: é dela que sai o uso de tokens.
    estruturado = base.with_structured_output(VotoModelo, method=configuracao["method"], include_raw=True)

    def invocar(prompt: str) -> tuple[VotoModelo, dict | None]:
        return desembrulhar_resposta(estruturado.invoke(prompt), provedor)

    return invocar


def desembrulhar_resposta(resultado: dict, provedor: str) -> tuple[VotoModelo, dict | None]:
    """Voto e uso de tokens da saída de with_structured_output(include_raw=True).

    Com include_raw o LangChain não levanta o erro de parse, devolve-o em parsing_error. Ele sobe aqui como antes,
    com o uso da resposta anexado em `uso_tokens`, para o livro-razão contar também a tentativa fora do schema.
    """
    if not isinstance(resultado, dict):
        raise RuntimeError(f"{provedor} devolveu algo que não é a saída com include_raw: {type(resultado)}")
    uso = custos.normalizar_uso(getattr(resultado.get("raw"), "usage_metadata", None))
    voto = resultado.get("parsed")
    erro = resultado.get("parsing_error")
    if voto is None and erro is not None:
        with contextlib.suppress(AttributeError, TypeError):
            erro.uso_tokens = uso
        raise erro
    if not isinstance(voto, VotoModelo):
        raise RuntimeError(f"{provedor} devolveu algo que não é VotoModelo: {type(voto)}")
    return voto, uso


def criar_classificadores(pasta_cache: Path = CAMINHOS.cache) -> tuple[ClassificadorLLM, ClassificadorLLM]:
    template = carregar_prompt()
    modelo_openai = ler_env("MODELO_OPENAI", "gpt-5") or "gpt-5"
    modelo_anthropic = ler_env("MODELO_ANTHROPIC", "claude-sonnet-5-5") or "claude-sonnet-5-5"
    inv_openai = criar_invocador("openai", modelo_openai) if ler_env("OPENAI_API_KEY") else None
    inv_anthropic = criar_invocador("anthropic", modelo_anthropic) if ler_env("ANTHROPIC_API_KEY") else None
    return (
        ClassificadorLLM("openai", modelo_openai, inv_openai, pasta_cache, template,
                         configuracao=configuracao_invocador("openai", modelo_openai)),
        ClassificadorLLM("anthropic", modelo_anthropic, inv_anthropic, pasta_cache, template,
                         configuracao=configuracao_invocador("anthropic", modelo_anthropic)),
    )


def rodar_votos(
    alvo: str,
    arvore: ArvoreTemas,
    caminho_candidatos: Path,
    classificadores: tuple[ClassificadorLLM, ClassificadorLLM],
    pasta_saida: Path = CAMINHOS.intermediarios,
    limite: int | None = None,
) -> Path:
    df = carregar_questoes() if alvo == "questoes" else carregar_corpus()
    candidatos = {linha["id"]: candidatos_de_dict(linha["candidatos"]) for linha in ler_jsonl(caminho_candidatos)}
    openai, anthropic = classificadores
    # Disjuntor: o mesmo classificador sem voto em várias questões seguidas é chave, cota ou modelo com problema.
    sem_voto_seguidas = [0, 0]
    linhas: list[dict] = []
    for posicao, (id_, texto) in enumerate(zip(df["id"], df["texto"])):
        if limite is not None and posicao >= limite:
            break
        if str(id_) not in candidatos:
            raise KeyError(f"questão {id_} sem candidatos em {caminho_candidatos}; gere os candidatos de novo")
        lista = candidatos[str(id_)]
        with custos.contexto(etapa="votos", alvo=alvo, id_questao=str(id_)):
            voto_a = openai.classificar(texto, lista, arvore)
            voto_b = anthropic.classificar(texto, lista, arvore)
        for posicao_clf, (classificador, voto) in enumerate(((openai, voto_a), (anthropic, voto_b))):
            sem_voto_seguidas[posicao_clf] = sem_voto_seguidas[posicao_clf] + 1 if voto is None else 0
            if sem_voto_seguidas[posicao_clf] >= MAXIMO_NONE_CONSECUTIVOS:
                raise RuntimeError(
                    f"classificador '{classificador.nome}' ficou sem voto em {MAXIMO_NONE_CONSECUTIVOS} questões seguidas "
                    f"(última: {id_}); votação interrompida para não gastar chamadas. Rode `classificar votos --verificar` "
                    "para checar chave, modelo e cota; os votos já obtidos ficam no cache."
                )
        linhas.append({
            "id": str(id_),
            "openai": None if voto_a is None else voto_a.model_dump(),
            "anthropic": None if voto_b is None else voto_b.model_dump(),
        })
        if (posicao + 1) % 25 == 0:
            registro.info("%d questões votadas", posicao + 1)
    saida = pasta_saida / f"votos_llm_{alvo}.jsonl"
    escrever_jsonl(saida, linhas)
    registro.info(
        "gravado %s; chamadas openai=%d anthropic=%d, cache openai=%d anthropic=%d",
        saida, openai.chamadas, anthropic.chamadas, openai.acertos_cache, anthropic.acertos_cache,
    )
    return saida


PROMPT_VERIFICACAO = (
    "Questão de teste: o crime de furto está no Código Penal. "
    "Candidatos:\n- id 1: Penal > Furto\nResponda escolhendo o id 1 com confiança 1."
)


def verificar_provedores(livro: custos.LivroRazao | None = None) -> dict[str, str]:
    """Uma chamada curta por provedor com chave; cada chamada feita vai para o livro-razão na etapa verificar."""
    livro = livro if livro is not None else custos.LIVRO
    resultado: dict[str, str] = {}
    for provedor, variavel_modelo, padrao, variavel_chave in (
        ("openai", "MODELO_OPENAI", "gpt-5", "OPENAI_API_KEY"),
        ("anthropic", "MODELO_ANTHROPIC", "claude-sonnet-5-5", "ANTHROPIC_API_KEY"),
    ):
        if not ler_env(variavel_chave):
            resultado[provedor] = f"sem {variavel_chave}"
            continue
        modelo = ler_env(variavel_modelo, padrao) or padrao
        linha = {"provedor": provedor, "modelo": modelo, "origem": "api", "tentativa": 1,
                 "configuracao": slug_configuracao(configuracao_invocador(provedor, modelo)),
                 "tamanho_prompt_chars": len(PROMPT_VERIFICACAO)}
        inicio: float | None = None
        with custos.contexto(etapa="verificar"):
            try:
                invocar = criar_invocador(provedor, modelo)
                inicio = time.perf_counter()
                voto, uso = invocar(PROMPT_VERIFICACAO)
            except Exception as erro:
                if inicio is not None:
                    livro.registrar(**linha, uso=getattr(erro, "uso_tokens", None), latencia_ms=_milissegundos(inicio),
                                    sucesso=False, erro=custos.descrever_erro(erro))
                resultado[provedor] = f"erro: {erro}"
                continue
            livro.registrar(**linha, uso=uso, latencia_ms=_milissegundos(inicio),
                            tema_votado=voto.tema_central_id, confianca=voto.confianca)
        resultado[provedor] = "ok" if voto.tema_central_id == 1 else f"respondeu {voto.tema_central_id}"
    return resultado


def main(argumentos: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Colhe os votos dos dois modelos de linguagem.")
    parser.add_argument("--alvo", choices=["questoes", "corpus"], default="questoes")
    parser.add_argument("--passada", type=int, choices=[1, 2], default=2)
    parser.add_argument("--limite", type=int, default=None)
    parser.add_argument("--verificar", action="store_true")
    args = parser.parse_args(argumentos)
    if args.verificar:
        for provedor, estado in verificar_provedores().items():
            print(f"{provedor}: {estado}")
        return
    caminho = CAMINHOS.intermediarios / f"candidatos_{args.alvo}_p{args.passada}.jsonl"
    rodar_votos(args.alvo, ArvoreTemas.carregar(), caminho, criar_classificadores(), limite=args.limite)


if __name__ == "__main__":
    main()
