"""Votos dos modelos de linguagem: prompt, schema estruturado, cache e retentativas."""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
import time
from pathlib import Path
from typing import Callable, Literal

from pydantic import BaseModel, Field, ValidationError

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


Invocador = Callable[[str], VotoModelo]

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
    ) -> None:
        self.nome = nome
        self.modelo = modelo
        self.invocador = invocador
        # Parâmetros de invocação que mudam a resposta (esforço, max_tokens, método): entram na chave e na pasta do cache.
        self.configuracao = dict(configuracao or {})
        slug = slug_configuracao(self.configuracao)
        self.pasta = pasta_cache / "llm" / nome / (f"{modelo}__{slug}" if slug else modelo)
        self.pasta.mkdir(parents=True, exist_ok=True)
        self.template = template
        self.tentativas = tentativas
        self.espera_base = espera_base
        self.dormir = dormir
        self.chamadas = 0
        self.acertos_cache = 0

    def _arquivo(self, prompt: str) -> Path:
        schema = json.dumps(VotoModelo.model_json_schema(), sort_keys=True)
        configuracao = json.dumps(self.configuracao, sort_keys=True)
        chave = hashlib.sha256(f"{self.modelo}\n{configuracao}\n{prompt}\n{schema}".encode("utf-8")).hexdigest()
        return self.pasta / f"{chave}.json"

    def _ler_cache(self, prompt: str) -> VotoModelo | None:
        arquivo = self._arquivo(prompt)
        if not arquivo.exists():
            return None
        try:
            return VotoModelo.model_validate_json(arquivo.read_text(encoding="utf-8"))
        except Exception:
            arquivo.unlink()
            return None

    def _gravar_cache(self, prompt: str, voto: VotoModelo) -> None:
        self._arquivo(prompt).write_text(voto.model_dump_json(), encoding="utf-8")

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

    def _invocar_com_retentativas(self, prompt: str) -> VotoModelo | None:
        """Chama o modelo com espera exponencial em erro transitório (429, 5xx, conexão, desconhecido).

        Erro 4xx que não é 429 sobe na hora. Resposta fora do schema sobe como ValidationError, para o chamador
        tentar uma vez só com o aviso no prompt, sem passar pelas esperas.
        """
        assert self.invocador is not None
        for tentativa in range(self.tentativas):
            try:
                self.chamadas += 1
                return self.invocador(prompt)
            except VotoInvalidoError:
                raise
            except Exception as erro:
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
        return None

    def classificar(self, texto_questao: str, candidatos: list[Candidato], arvore: ArvoreTemas) -> VotoModelo | None:
        prompt = montar_prompt(self.template, texto_questao, candidatos, arvore)
        em_cache = self._ler_cache(prompt)
        if em_cache is not None:
            try:
                validado = self.validar(em_cache, candidatos, arvore)
            except VotoInvalidoError:
                self._arquivo(prompt).unlink()
            else:
                self.acertos_cache += 1
                return validado
        if self.invocador is None:
            raise ChaveAusenteError(
                f"classificador '{self.nome}' sem chave de API e sem cache para esta questão. "
                "Defina a chave no .env ou use o cache commitado."
            )
        prompt_atual = prompt
        for rodada in range(2):
            try:
                bruto = self._invocar_com_retentativas(prompt_atual)
            except ValidationError as erro:
                resumo = resumir_validacao(erro)
                registro.warning("%s: resposta fora do schema (rodada %d): %s", self.nome, rodada + 1, resumo)
                prompt_atual = prompt + AVISO_VALIDACAO.format(erro=resumo)
                continue
            if bruto is None:
                return None
            try:
                voto = self.validar(bruto, candidatos, arvore)
            except VotoInvalidoError as erro:
                registro.warning("%s: tema %s fora dos candidatos (rodada %d)", self.nome, erro, rodada + 1)
                prompt_atual = prompt + AVISO_RETENTATIVA.format(id=erro)
                continue
            self._gravar_cache(prompt, voto)
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
    estruturado = base.with_structured_output(VotoModelo, method=configuracao["method"])

    def invocar(prompt: str) -> VotoModelo:
        resultado = estruturado.invoke(prompt)
        if not isinstance(resultado, VotoModelo):
            raise RuntimeError(f"{provedor} devolveu algo que não é VotoModelo: {type(resultado)}")
        return resultado

    return invocar


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
    sem_voto_seguidas = {openai.nome: 0, anthropic.nome: 0}
    linhas: list[dict] = []
    for posicao, (id_, texto) in enumerate(zip(df["id"], df["texto"])):
        if limite is not None and posicao >= limite:
            break
        if str(id_) not in candidatos:
            raise KeyError(f"questão {id_} sem candidatos em {caminho_candidatos}; gere os candidatos de novo")
        lista = candidatos[str(id_)]
        voto_a = openai.classificar(texto, lista, arvore)
        voto_b = anthropic.classificar(texto, lista, arvore)
        for classificador, voto in ((openai, voto_a), (anthropic, voto_b)):
            sem_voto_seguidas[classificador.nome] = sem_voto_seguidas[classificador.nome] + 1 if voto is None else 0
            if sem_voto_seguidas[classificador.nome] >= MAXIMO_NONE_CONSECUTIVOS:
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


def verificar_provedores() -> dict[str, str]:
    resultado: dict[str, str] = {}
    for provedor, variavel_modelo, padrao, variavel_chave in (
        ("openai", "MODELO_OPENAI", "gpt-5", "OPENAI_API_KEY"),
        ("anthropic", "MODELO_ANTHROPIC", "claude-sonnet-5-5", "ANTHROPIC_API_KEY"),
    ):
        if not ler_env(variavel_chave):
            resultado[provedor] = f"sem {variavel_chave}"
            continue
        try:
            invocar = criar_invocador(provedor, ler_env(variavel_modelo, padrao) or padrao)
            voto = invocar(
                "Questão de teste: o crime de furto está no Código Penal. "
                "Candidatos:\n- id 1: Penal > Furto\nResponda escolhendo o id 1 com confiança 1."
            )
            resultado[provedor] = "ok" if voto.tema_central_id == 1 else f"respondeu {voto.tema_central_id}"
        except Exception as erro:
            resultado[provedor] = f"erro: {erro}"
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
