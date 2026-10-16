"""As sete regras que decidem entre publicar, revisar e fora."""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path

from classificador.arvore import ArvoreTemas
from classificador.candidatos import Candidato, candidatos_de_dict
from classificador.config import CAMINHOS
from classificador.dados import escrever_jsonl, ler_jsonl
from classificador.llm import VotoModelo
from classificador.vizinhanca import VotoVizinhanca

registro = logging.getLogger(__name__)


@dataclass(frozen=True)
class Limiares:
    publicar: float = 0.80
    pai: float = 0.70
    contradicao: float = 0.60

    def para_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def de_dict(dados: dict) -> "Limiares":
        return Limiares(float(dados["publicar"]), float(dados["pai"]), float(dados["contradicao"]))


@dataclass
class Decisao:
    id: str
    decisao: str
    tema_central_id: int | None
    extras_ids: list[int] = field(default_factory=list)
    confianca: float | None = None
    motivo: str = ""
    regra: int = 0

    def para_dict(self) -> dict:
        return asdict(self)


def _extras(arvore: ArvoreTemas, central: int | None, *fontes: list[int]) -> list[int]:
    saida: list[int] = []
    for fonte in fontes:
        for tema in fonte:
            if not arvore.existe(tema):
                continue
            canonico = arvore.canonico(tema)
            if arvore.publicavel(canonico) and canonico != central and canonico not in saida:
                saida.append(canonico)
    return saida


def _contradiz(vizinhanca: VotoVizinhanca | None, tema: int, arvore: ArvoreTemas, limiares: Limiares) -> bool:
    if vizinhanca is None or vizinhanca.tema_nivel1 is None:
        return False
    return vizinhanca.peso_nivel1 >= limiares.contradicao and arvore.ancestral_nivel1(tema) != vizinhanca.tema_nivel1


def decidir(
    id_: str,
    voto_a: VotoModelo | None,
    voto_b: VotoModelo | None,
    vizinhanca: VotoVizinhanca | None,
    candidatos: list[Candidato],
    arvore: ArvoreTemas,
    limiares: Limiares,
) -> Decisao:
    primeiro_candidato = candidatos[0].tema_id if candidatos else None
    # Extras de toda decisão com tema: a união dos extras dos votos que existem; só a regra 3 soma os dois temas.
    extras_votos = [voto.extras_ids for voto in (voto_a, voto_b) if voto is not None]

    # Regra 7: algum modelo não respondeu.
    if voto_a is None or voto_b is None:
        existente = voto_a or voto_b
        if existente is not None and existente.tema_central_id is not None:
            return Decisao(id_, "revisar", existente.tema_central_id, _extras(arvore, existente.tema_central_id, *extras_votos),
                           existente.confianca, "modelo sem resposta válida", 7)
        return Decisao(id_, "revisar", primeiro_candidato, _extras(arvore, primeiro_candidato, *extras_votos), None,
                       "modelo sem resposta válida", 7)

    # Regra 1: os dois dizem que a questão é de outra disciplina.
    if voto_a.disciplina == "Outra" and voto_b.disciplina == "Outra":
        return Decisao(id_, "fora", None, [], None, f"fora das quatro disciplinas: {voto_a.justificativa}", 1)

    ta, tb = voto_a.tema_central_id, voto_b.tema_central_id

    # Regra 6: um ou os dois não acharam candidato.
    if ta is None and tb is None:
        if voto_a.disciplina != "Outra" and voto_b.disciplina != "Outra":
            # Questão das quatro disciplinas sem tema na lista: o professor revisa, com o tema mais próximo do assunto
            # que os modelos descreveram (o primeiro vindo do reparo) ou, sem reparo, o primeiro candidato.
            reparo = next((c.tema_id for c in candidatos if c.origem == "reparo"), None)
            sugestao = reparo if reparo is not None else primeiro_candidato
            if sugestao is None:
                return Decisao(id_, "fora", None, [], None, f"nenhum tema da árvore cobre o assunto: {voto_a.justificativa}", 6)
            return Decisao(id_, "revisar", sugestao, _extras(arvore, sugestao, *extras_votos), None,
                           f"nenhum modelo achou tema que cubra a questão; assunto descrito: {voto_a.justificativa}", 6)
        return Decisao(id_, "revisar", primeiro_candidato, _extras(arvore, primeiro_candidato, *extras_votos), None,
                       "um modelo diz fora das disciplinas, outro diz que nenhum candidato serve", 6)
    if ta is None or tb is None:
        outro = voto_b if ta is None else voto_a
        assert outro.tema_central_id is not None
        return Decisao(id_, "revisar", outro.tema_central_id, _extras(arvore, outro.tema_central_id, *extras_votos),
                       outro.confianca, "um modelo não achou candidato; sugestão do outro", 6)

    assert ta is not None and tb is not None
    conf_min = min(voto_a.confianca, voto_b.confianca)

    # Regras 2 e 5: mesmo tema.
    if ta == tb:
        extras = _extras(arvore, ta, *extras_votos)
        if _contradiz(vizinhanca, ta, arvore, limiares):
            assert vizinhanca is not None and vizinhanca.tema_nivel1 is not None
            motivo = f"vizinhança aponta {arvore.caminho(vizinhanca.tema_nivel1)} com peso {vizinhanca.peso_nivel1:.2f}"
            return Decisao(id_, "revisar", ta, extras, conf_min, motivo, 5)
        if conf_min < limiares.publicar:
            return Decisao(id_, "revisar", ta, extras, conf_min, f"confiança {conf_min:.2f} abaixo do limiar {limiares.publicar:.2f}", 5)
        return Decisao(id_, "publicar", ta, extras, conf_min, "", 2)

    # Regra 3: temas diferentes no mesmo ramo.
    if arvore.mesmo_ramo(ta, tb):
        pai = arvore.ancestral_nivel1(ta)
        extras = _extras(arvore, pai, [ta, tb], *extras_votos)
        if conf_min >= limiares.pai:
            return Decisao(id_, "publicar", pai, extras, conf_min, "", 3)
        return Decisao(id_, "revisar", pai, extras, conf_min,
                       f"irmãos {arvore.titulo(ta)} e {arvore.titulo(tb)} abaixo do limiar do pai {limiares.pai:.2f}", 3)

    # Regra 4: ramos diferentes. Sugestão: o voto apoiado pela vizinhança; sem apoio, o de maior confiança.
    escolhido: VotoModelo | None = None
    if vizinhanca is not None and vizinhanca.tema_nivel1 is not None:
        if arvore.ancestral_nivel1(ta) == vizinhanca.tema_nivel1:
            escolhido = voto_a
        elif arvore.ancestral_nivel1(tb) == vizinhanca.tema_nivel1:
            escolhido = voto_b
    if escolhido is None:
        escolhido = voto_b if voto_b.confianca > voto_a.confianca else voto_a
    assert escolhido.tema_central_id is not None
    motivo = f"modelos divergem: {arvore.caminho(ta)} vs {arvore.caminho(tb)}"
    return Decisao(id_, "revisar", escolhido.tema_central_id, _extras(arvore, escolhido.tema_central_id, *extras_votos),
                   escolhido.confianca, motivo, 4)


def carregar_limiares(pasta: Path = CAMINHOS.intermediarios) -> Limiares:
    arquivo = pasta / "limiares.json"
    if arquivo.exists():
        return Limiares.de_dict(json.loads(arquivo.read_text(encoding="utf-8")))
    registro.warning("limiares.json ausente; usando os padrões %s", Limiares())
    return Limiares()


def carregar_candidatos(alvo: str, pasta: Path = CAMINHOS.intermediarios, passada: int = 2) -> dict[str, list[Candidato]]:
    """Listas de candidatos por questão: as da passada e, na passada 2, a lista ampliada do reparo onde ela existe."""
    candidatos = {l["id"]: candidatos_de_dict(l["candidatos"]) for l in ler_jsonl(pasta / f"candidatos_{alvo}_p{passada}.jsonl")}
    caminho_reparo = pasta / f"candidatos_{alvo}_reparo.jsonl"
    if passada == 2 and caminho_reparo.exists():
        for linha in ler_jsonl(caminho_reparo):
            candidatos[linha["id"]] = candidatos_de_dict(linha["candidatos"])
    return candidatos


def rodar_decisoes(
    alvo: str,
    arvore: ArvoreTemas,
    limiares: Limiares,
    pasta: Path = CAMINHOS.intermediarios,
    passada: int = 2,
) -> Path:
    votos = ler_jsonl(pasta / f"votos_llm_{alvo}.jsonl")
    caminho_viz = pasta / f"vizinhanca_{alvo}.jsonl"
    vizinhancas = {l["id"]: VotoVizinhanca.de_dict(l) for l in ler_jsonl(caminho_viz)} if caminho_viz.exists() else {}
    candidatos = carregar_candidatos(alvo, pasta, passada)
    linhas: list[dict] = []
    for linha in votos:
        id_ = linha["id"]
        voto_a = None if linha.get("openai") is None else VotoModelo.model_validate(linha["openai"])
        voto_b = None if linha.get("anthropic") is None else VotoModelo.model_validate(linha["anthropic"])
        decisao = decidir(id_, voto_a, voto_b, vizinhancas.get(id_), candidatos.get(id_, []), arvore, limiares)
        if decisao.decisao == "publicar" and (decisao.tema_central_id is None or not arvore.publicavel(decisao.tema_central_id)):
            raise ValueError(
                f"questão {id_}: decisão publicar sem tema publicável (tema {decisao.tema_central_id}, regra {decisao.regra})"
            )
        if decisao.decisao == "revisar" and decisao.tema_central_id is None:
            raise ValueError(f"questão {id_}: decisão revisar sem tema sugerido (regra {decisao.regra})")
        linhas.append(decisao.para_dict())
    saida = pasta / f"decisoes_{alvo}.jsonl"
    escrever_jsonl(saida, linhas)
    contagem = {d: sum(1 for l in linhas if l["decisao"] == d) for d in ("publicar", "revisar", "fora")}
    registro.info("gravado %s: %s", saida, contagem)
    return saida
