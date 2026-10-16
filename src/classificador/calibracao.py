"""Calibração: precisão por célula (regra × faixa) no corpus, reponderação, varredura de limiares, âncora e previsao.txt."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from classificador.ancora import TEMA_FORA, carregar_ancora_manual
from classificador.arvore import ArvoreTemas
from classificador.candidatos import Candidato, candidatos_de_dict
from classificador.config import CAMINHOS, SEMENTE
from classificador.dados import carregar_corpus, ler_jsonl
from classificador.decisao import Decisao, Limiares, decidir
from classificador.llm import VotoModelo
from classificador.vizinhanca import VotoVizinhanca

registro = logging.getLogger(__name__)

FAIXAS = [(0.0, 0.6), (0.6, 0.7), (0.7, 0.8), (0.8, 0.9), (0.9, 1.01)]
ROTULOS = ["0.0-0.6", "0.6-0.7", "0.7-0.8", "0.8-0.9", "0.9-1.0"]
GRADE_PADRAO = [round(x, 2) for x in np.arange(0.5, 0.951, 0.05)]
ALVO_PRECISAO = 0.97
PISO_PRECISAO = 0.95
N_MINIMO_CELULA = 5
PRIOR_JEFFREYS = 0.5


def faixa_de(confianca: float | None) -> str:
    if confianca is None or (isinstance(confianca, float) and np.isnan(confianca)):
        return "sem"
    for (_, fim), rotulo in zip(FAIXAS, ROTULOS):
        if confianca < fim:
            return rotulo
    return ROTULOS[-1]


@dataclass
class Entrada:
    id: str
    voto_a: VotoModelo | None
    voto_b: VotoModelo | None
    vizinhanca: VotoVizinhanca | None
    candidatos: list[Candidato]
    verdadeiro: int | None


def carregar_entradas(alvo: str, pasta: Path, arvore: ArvoreTemas, passada: int = 2) -> list[Entrada]:
    caminho_votos = pasta / f"votos_llm_{alvo}.jsonl"
    if not caminho_votos.exists():
        raise FileNotFoundError(f"{caminho_votos} não existe; rode os votos de '{alvo}' antes de calibrar")
    votos = ler_jsonl(caminho_votos)
    caminho_viz = pasta / f"vizinhanca_{alvo}.jsonl"
    vizinhancas = {l["id"]: VotoVizinhanca.de_dict(l) for l in ler_jsonl(caminho_viz)} if caminho_viz.exists() else {}
    candidatos = {l["id"]: candidatos_de_dict(l["candidatos"]) for l in ler_jsonl(pasta / f"candidatos_{alvo}_p{passada}.jsonl")}
    verdadeiros: dict[str, int] = {}
    if alvo == "corpus":
        corpus = carregar_corpus()
        verdadeiros = {str(i): arvore.canonico(int(t)) for i, t in zip(corpus["id"], corpus["tema_id"])}
    entradas = []
    for linha in votos:
        id_ = linha["id"]
        entradas.append(Entrada(
            id=id_,
            voto_a=None if linha.get("openai") is None else VotoModelo.model_validate(linha["openai"]),
            voto_b=None if linha.get("anthropic") is None else VotoModelo.model_validate(linha["anthropic"]),
            vizinhanca=vizinhancas.get(id_),
            candidatos=candidatos.get(id_, []),
            verdadeiro=verdadeiros.get(id_),
        ))
    return entradas


def decidir_todas(entradas: list[Entrada], arvore: ArvoreTemas, limiares: Limiares) -> list[Decisao]:
    return [decidir(e.id, e.voto_a, e.voto_b, e.vizinhanca, e.candidatos, arvore, limiares) for e in entradas]


def avaliar(decisoes: list[Decisao], entradas: list[Entrada], arvore: ArvoreTemas) -> pd.DataFrame:
    verdadeiros = {e.id: e.verdadeiro for e in entradas}
    linhas = []
    for d in decisoes:
        verdadeiro = verdadeiros.get(d.id)
        acerto = None
        if d.tema_central_id is not None and verdadeiro is not None:
            acerto = arvore.acerto(d.tema_central_id, verdadeiro)
        linhas.append({
            "id": d.id, "decisao": d.decisao, "regra": d.regra, "confianca": d.confianca,
            "faixa": faixa_de(d.confianca), "tema_decidido": d.tema_central_id,
            "tema_verdadeiro": verdadeiro, "acerto": acerto,
        })
    return pd.DataFrame(linhas, columns=["id", "decisao", "regra", "confianca", "faixa", "tema_decidido", "tema_verdadeiro", "acerto"])


def tabela_faixas(avaliacao: pd.DataFrame) -> pd.DataFrame:
    publicadas = avaliacao[(avaliacao["decisao"] == "publicar") & avaliacao["acerto"].notna()].copy()
    if publicadas.empty:
        return pd.DataFrame(columns=["regra", "faixa", "n", "acertos", "precisao"])
    publicadas["acerto"] = publicadas["acerto"].astype(bool)
    grupo = publicadas.groupby(["regra", "faixa"])["acerto"].agg(n="size", acertos="sum").reset_index()
    grupo["precisao"] = grupo["acertos"] / grupo["n"]
    return grupo


def precisao_suavizada(acertos: float, n: float) -> float:
    """Média da posterior Beta com prior de Jeffreys: (acertos + 0.5) / (n + 1)."""
    assert n > 0, "precisão suavizada exige pelo menos uma questão"
    return (acertos + PRIOR_JEFFREYS) / (n + 2 * PRIOR_JEFFREYS)


def _unidades_usadas(tabela: pd.DataFrame, publicadas: pd.DataFrame) -> list[tuple[float, float, int]]:
    """Resolve cada publicada do alvo na sua unidade do corpus e devolve (acertos, n, publicadas que a usam).

    A unidade é a célula (regra, faixa) se ela tem pelo menos N_MINIMO_CELULA questões do corpus; senão a faixa
    somada sobre as regras, se ela tem pelo menos N_MINIMO_CELULA; senão o corpus inteiro.
    """
    por_celula = {(int(r.regra), r.faixa): (float(r.acertos), float(r.n)) for r in tabela.itertuples()}
    por_faixa = {f: (float(r.acertos), float(r.n)) for f, r in tabela.groupby("faixa")[["n", "acertos"]].sum().iterrows()}
    global_ = (float(tabela["acertos"].sum()), float(tabela["n"].sum()))
    usadas: dict[tuple, list] = {}
    for linha in publicadas.itertuples():
        celula = (int(linha.regra), linha.faixa)
        if celula in por_celula and por_celula[celula][1] >= N_MINIMO_CELULA:
            chave, contagem = ("celula", celula), por_celula[celula]
        elif linha.faixa in por_faixa and por_faixa[linha.faixa][1] >= N_MINIMO_CELULA:
            chave, contagem = ("faixa", linha.faixa), por_faixa[linha.faixa]
        else:
            chave, contagem = ("global",), global_
        usadas.setdefault(chave, [contagem[0], contagem[1], 0])[2] += 1
    return [(acertos, n, peso) for acertos, n, peso in usadas.values()]


def precisao_reponderada(tabela: pd.DataFrame, avaliacao_questoes: pd.DataFrame) -> float:
    """Precisão prevista para as publicadas do alvo, reponderada pela distribuição delas nas células do corpus.

    Cada publicada do alvo recebe a precisão suavizada (Jeffreys) da sua célula (regra, faixa) no corpus, desde que a
    célula tenha pelo menos N_MINIMO_CELULA questões; senão a da faixa somada sobre as regras, com o mesmo mínimo;
    senão a do corpus inteiro. O resultado é a média sobre as publicadas, ou seja, ponderada pela contagem de cada
    unidade. Sem publicadas no alvo ou tabela vazia, devolve 0.0.
    """
    publicadas = avaliacao_questoes[avaliacao_questoes["decisao"] == "publicar"]
    if publicadas.empty or tabela.empty:
        return 0.0
    soma = sum(peso * precisao_suavizada(acertos, n) for acertos, n, peso in _unidades_usadas(tabela, publicadas))
    return soma / len(publicadas)


def bootstrap_precisao(
    avaliacao_corpus: pd.DataFrame,
    avaliacao_questoes: pd.DataFrame,
    repeticoes: int,
    semente: int = SEMENTE,
) -> tuple[float, float]:
    """Intervalo de 95% da precisão prevista por simulação da posterior Beta por célula.

    O nome ficou por compatibilidade; o método não reamostra mais o corpus, porque a reamostragem dá intervalo de
    largura zero em célula pequena toda certa (3 de 3 dava [1.0, 1.0]). A tabela do corpus é montada uma vez; cada
    publicada do alvo é resolvida na sua unidade (célula, faixa ou corpus inteiro) pela mesma regra de recuo de
    precisao_reponderada. Em cada repetição, cada unidade usada sorteia p ~ Beta(acertos + 0.5, erros + 0.5) e a
    estimativa é a média dos p ponderada pelas publicadas do alvo em cada unidade. Devolve os percentis 2.5 e 97.5
    das repetições, ou (0.0, 0.0) quando não há publicadas no corpus ou no alvo.
    """
    tabela = tabela_faixas(avaliacao_corpus)
    publicadas = avaliacao_questoes[avaliacao_questoes["decisao"] == "publicar"]
    if tabela.empty or publicadas.empty:
        return 0.0, 0.0
    unidades = np.array(_unidades_usadas(tabela, publicadas), dtype=float)
    acertos, n, pesos = unidades[:, 0], unidades[:, 1], unidades[:, 2]
    gerador = np.random.default_rng(semente)
    sorteios = gerador.beta(acertos + PRIOR_JEFFREYS, n - acertos + PRIOR_JEFFREYS, size=(repeticoes, len(unidades)))
    estimativas = sorteios @ pesos / pesos.sum()
    return float(np.percentile(estimativas, 2.5)), float(np.percentile(estimativas, 97.5))


def varrer_limiares(
    entradas_corpus: list[Entrada],
    entradas_questoes: list[Entrada],
    arvore: ArvoreTemas,
    grade: list[float] = GRADE_PADRAO,
    contradicao: float = 0.6,
    repeticoes: int = 200,
) -> pd.DataFrame:
    linhas = []
    total = len(entradas_questoes)
    for publicar in grade:
        for pai in grade:
            limiares = Limiares(publicar=publicar, pai=pai, contradicao=contradicao)
            aval_c = avaliar(decidir_todas(entradas_corpus, arvore, limiares), entradas_corpus, arvore)
            aval_q = avaliar(decidir_todas(entradas_questoes, arvore, limiares), entradas_questoes, arvore)
            tabela = tabela_faixas(aval_c)
            n_pub = int((aval_q["decisao"] == "publicar").sum())
            precisao_corpus = float(tabela["acertos"].sum() / tabela["n"].sum()) if not tabela.empty else 0.0
            inferior, superior = bootstrap_precisao(aval_c, aval_q, repeticoes)
            linhas.append({
                "publicar": publicar, "pai": pai, "n_publicadas": n_pub,
                "cobertura": n_pub / total if total else 0.0,
                "precisao_corpus": precisao_corpus,
                "precisao_prevista": precisao_reponderada(tabela, aval_q),
                "limite_inferior": inferior, "limite_superior": superior,
            })
    return pd.DataFrame(linhas)


def _atinge_alvo(varredura: pd.DataFrame, alvo: float, piso: float) -> pd.Series:
    return (varredura["precisao_prevista"] >= alvo) & (varredura["limite_inferior"] >= piso)


def escolher_limiares(
    varredura: pd.DataFrame,
    alvo: float = ALVO_PRECISAO,
    piso: float = PISO_PRECISAO,
    contradicao: float = 0.6,
) -> tuple[Limiares, int]:
    """Escolhe o par de limiares por uma escada de critérios e devolve (limiares, degrau).

    Degrau 0: precisão prevista >= alvo e limite inferior >= piso; maior cobertura (desempate: prevista, inferior).
    Degrau 1: limite inferior >= piso; maior cobertura (desempate: inferior).
    Degrau 2: precisão prevista >= alvo; maior limite inferior (desempate: cobertura).
    Degrau 3: qualquer par; maior limite inferior (desempate: cobertura).
    """
    prevista_ok = varredura["precisao_prevista"] >= alvo
    inferior_ok = varredura["limite_inferior"] >= piso
    escada = [
        (_atinge_alvo(varredura, alvo, piso), ["cobertura", "precisao_prevista", "limite_inferior"]),
        (inferior_ok, ["cobertura", "limite_inferior"]),
        (prevista_ok, ["limite_inferior", "cobertura"]),
        (pd.Series(True, index=varredura.index), ["limite_inferior", "cobertura"]),
    ]
    avisos = {
        1: "nenhum par atinge precisão prevista %.2f com limite inferior %.2f; degrau 1: maior cobertura com o piso",
        2: "nenhum par atinge precisão prevista %.2f com limite inferior %.2f nem o piso sozinho; degrau 2: maior limite inferior com a meta",
        3: "nenhum par atinge precisão prevista %.2f nem limite inferior %.2f; degrau 3: maior limite inferior",
    }
    for degrau, (mascara, ordem) in enumerate(escada):
        aptas = varredura[mascara]
        if aptas.empty:
            continue
        if degrau:
            registro.warning(avisos[degrau], alvo, piso)
        melhor = aptas.sort_values(ordem, ascending=False).iloc[0]
        return Limiares(publicar=float(melhor["publicar"]), pai=float(melhor["pai"]), contradicao=contradicao), degrau
    raise ValueError("varredura de limiares vazia; não há par para escolher")


def comparar_ancora(avaliacao_questoes: pd.DataFrame, ancora: pd.DataFrame, arvore: ArvoreTemas, tabela: pd.DataFrame) -> dict:
    rotulos = {str(i): int(t) for i, t in zip(ancora["id"], ancora["tema_id"])}
    publicadas = avaliacao_questoes[(avaliacao_questoes["decisao"] == "publicar") & avaliacao_questoes["id"].isin(rotulos)]
    if publicadas.empty:
        return {"n_publicadas_na_ancora": 0, "acertos": 0, "precisao_observada": None, "precisao_prevista_para_elas": None}
    # Âncora fora da árvore (nenhum tema serve): publicar qualquer tema é erro.
    acertos = sum(
        rotulos[l.id] != TEMA_FORA and arvore.acerto(int(l.tema_decidido), rotulos[l.id]) for l in publicadas.itertuples()
    )
    return {
        "n_publicadas_na_ancora": int(len(publicadas)),
        "acertos": int(acertos),
        "precisao_observada": acertos / len(publicadas),
        "precisao_prevista_para_elas": precisao_reponderada(tabela, publicadas),
    }


def ajustar_intervalo(inferior: float, superior: float, observado: float | None) -> tuple[float, float]:
    if observado is None:
        return inferior, superior
    return min(inferior, observado), max(superior, observado)


def escrever_previsao(
    caminho: Path,
    precisao: float,
    intervalo: tuple[float, float],
    cobertura: float,
    intervalo_cobertura: tuple[float, float],
    texto: str,
) -> Path:
    conteudo = (
        f"precisao_prevista: {precisao:.2f}   # fração das publicadas que estará certa\n"
        f"precisao_intervalo: {intervalo[0]:.2f}-{intervalo[1]:.2f}\n"
        f"cobertura_prevista: {cobertura:.2f}  # fração das questões que você publicou\n"
        f"cobertura_intervalo: {intervalo_cobertura[0]:.2f}-{intervalo_cobertura[1]:.2f}\n"
        f"\n{texto.strip()}\n"
    )
    caminho.write_text(conteudo, encoding="utf-8")
    return caminho


def _frase_degrau(degrau: int) -> str:
    """Como o par de limiares foi escolhido, em português corrido, para cada degrau da escada de seleção."""
    if degrau == 0:
        return (
            f"foram escolhidos por varredura, maximizando cobertura sujeita a precisão prevista de pelo menos {ALVO_PRECISAO:.2f} "
            f"e limite inferior do intervalo de pelo menos {PISO_PRECISAO:.2f}. É o primeiro critério da escada de seleção, "
            f"o único que cumpre a meta inteira."
        )
    descida = (
        f"saíram de uma varredura em que nenhum par de limiares atingiu ao mesmo tempo a meta de precisão prevista "
        f"{ALVO_PRECISAO:.2f} e o piso de {PISO_PRECISAO:.2f} para o limite inferior, então a escolha desceu a escada de seleção."
    )
    if degrau == 1:
        return descida + (
            f" Usamos o segundo critério: entre os pares com limite inferior de pelo menos {PISO_PRECISAO:.2f}, o de maior "
            f"cobertura, abrindo mão da meta de precisão prevista."
        )
    if degrau == 2:
        return descida + (
            f" Usamos o terceiro critério: nenhum par teve limite inferior de pelo menos {PISO_PRECISAO:.2f}, então, entre os "
            f"pares com precisão prevista de pelo menos {ALVO_PRECISAO:.2f}, ficou o de maior limite inferior."
        )
    return descida + " Usamos o último critério: nenhum par cumpriu sequer uma das duas condições, então ficou o de maior limite inferior."


def montar_texto_previsao(resumo: dict) -> str:
    ancora = resumo.get("ancora")
    degrau = resumo["degrau"]
    n_ancora = resumo.get("n_ancora", 0)
    escolha = _frase_degrau(degrau)
    if not resumo["alvo_atingido"]:
        condicoes = (
            f"a meta de precisão prevista {ALVO_PRECISAO:.2f} e o piso de {PISO_PRECISAO:.2f} para o limite inferior"
            if degrau == 0 else "as duas condições"
        )
        escolha += (
            f" Com os números finais, o par escolhido não cumpre ao mesmo tempo {condicoes}, e a previsão de precisão no "
            f"topo deste arquivo reflete esse par."
        )
    elif degrau > 0:
        escolha += f" Com os números finais, de {resumo['repeticoes_final']} sorteios, o par escolhido cumpre as duas condições."
    partes = [
        "Como chegamos nos números.",
        f"Não há gabarito das 359 questões, então a precisão foi estimada num corpus de referência de {resumo['n_corpus']} "
        f"questões reais de concurso com tema conhecido, coletado por agentes a partir da própria árvore de temas. "
        f"O pipeline rodou sobre esse corpus com cada questão excluída da própria vizinhança, e medimos a precisão "
        f"das publicadas por regra de decisão e faixa de confiança, com a régua da Vício: certo se igual, pai ou filho.",
        f"O corpus é mais fácil que as 359, que vieram de lixeiras. A precisão prevista é a média, sobre as publicadas "
        f"entre as 359, da precisão no corpus da célula (regra de decisão × faixa de confiança) em que cada uma cai, com "
        f"suavização de Jeffreys ((acertos + {PRIOR_JEFFREYS:.1f}) / (n + {2 * PRIOR_JEFFREYS:.0f})). Quando a célula "
        f"tem menos de {N_MINIMO_CELULA} questões do corpus, recua para a faixa; quando a faixa também tem menos de "
        f"{N_MINIMO_CELULA}, para o corpus inteiro. Essa reponderação corrige só a diferença na mistura de regras de decisão "
        f"e faixas de confiança entre o corpus e as 359. Ela supõe que, dentro de uma célula, a chance de acerto é a mesma "
        f"no corpus e nas 359; a única checagem dessa suposição é a âncora manual, que, com poucas questões publicadas, só "
        f"detecta diferenças grandes. O intervalo de 95% vem de simulação da posterior Beta de cada célula, "
        f"com {resumo['repeticoes_final']} sorteios.",
        f"Os limiares de publicação ({resumo['limiares']['publicar']:.2f} no tema, {resumo['limiares']['pai']:.2f} no pai) "
        f"{escolha} Os limiares foram escolhidos no mesmo corpus usado para estimar a precisão, o que pode deixar a "
        f"estimativa um pouco otimista.",
    ]
    if ancora is None:
        partes.append("Não houve âncora manual disponível na calibração; o intervalo reflete só o corpus.")
    elif not ancora["n_publicadas_na_ancora"]:
        partes.append(
            f"A âncora manual de {n_ancora} questões rotuladas às cegas não tinha nenhuma questão publicada para comparar; "
            "o intervalo reflete só o corpus."
        )
    else:
        if resumo.get("intervalo_alargado"):
            conclusao = (
                f"O intervalo foi alargado para conter a observação; depois do alargamento, o limite inferior é "
                f"{resumo['precisao_intervalo'][0]:.2f} (antes, {resumo['intervalo_bruto'][0]:.2f})."
            )
        else:
            conclusao = "A observação cabe no intervalo."
        partes.append(
            f"Checagem com âncora manual: das {ancora['n_publicadas_na_ancora']} questões publicadas que estavam na "
            f"âncora de {n_ancora} rotuladas às cegas, {ancora['acertos']} estavam certas "
            f"(observado {ancora['precisao_observada']:.2f}, previsto {ancora['precisao_prevista_para_elas']:.2f}). "
            f"{conclusao}"
        )
    partes.append(
        f"Cobertura: {resumo['n_publicadas']} de {resumo['n_questoes']} questões publicadas. "
        f"É um número observado, não previsto, por isso o intervalo é estreito."
    )
    return "\n\n".join(partes)


def rodar_calibracao(
    arvore: ArvoreTemas,
    pasta: Path = CAMINHOS.intermediarios,
    caminho_ancora: Path = CAMINHOS.ancora_manual,
    contradicao: float = 0.6,
    repeticoes_varredura: int = 200,
    repeticoes_final: int = 1000,
) -> dict:
    entradas_corpus = carregar_entradas("corpus", pasta, arvore)
    entradas_questoes = carregar_entradas("questoes", pasta, arvore)
    varredura = varrer_limiares(entradas_corpus, entradas_questoes, arvore, contradicao=contradicao, repeticoes=repeticoes_varredura)
    varredura.to_csv(pasta / "calibracao_varredura.csv", index=False)
    limiares, degrau = escolher_limiares(varredura, contradicao=contradicao)
    # Degrau 0 é exatamente "algum par da varredura cumpre meta e piso".
    varredura_atingiu_alvo = degrau == 0
    (pasta / "limiares.json").write_text(json.dumps(limiares.para_dict(), indent=2), encoding="utf-8")

    aval_c = avaliar(decidir_todas(entradas_corpus, arvore, limiares), entradas_corpus, arvore)
    aval_q = avaliar(decidir_todas(entradas_questoes, arvore, limiares), entradas_questoes, arvore)
    aval_c.to_csv(pasta / "avaliacao_corpus.csv", index=False)
    tabela = tabela_faixas(aval_c)
    tabela.to_csv(pasta / "calibracao_faixas.csv", index=False)
    precisao = precisao_reponderada(tabela, aval_q)
    inferior, superior = bootstrap_precisao(aval_c, aval_q, repeticoes_final)
    # O alvo é julgado nos números finais (o intervalo de repeticoes_final), não na linha da varredura.
    alvo_atingido = bool(precisao >= ALVO_PRECISAO and inferior >= PISO_PRECISAO)

    ancora_resultado = None
    n_ancora = 0
    if caminho_ancora.exists():
        ancora = carregar_ancora_manual(arvore, caminho_ancora)
        n_ancora = len(ancora)
        ancora_resultado = comparar_ancora(aval_q, ancora, arvore, tabela)
    else:
        registro.warning("âncora manual ausente em %s; intervalo reflete só o corpus", caminho_ancora)
    observado = None if ancora_resultado is None else ancora_resultado["precisao_observada"]
    inferior_final, superior_final = ajustar_intervalo(inferior, superior, observado)

    n_pub = int((aval_q["decisao"] == "publicar").sum())
    cobertura = n_pub / len(aval_q) if len(aval_q) else 0.0
    resumo = {
        "limiares": limiares.para_dict(),
        "n_corpus": len(entradas_corpus),
        "n_questoes": len(aval_q),
        "n_publicadas": n_pub,
        "cobertura": cobertura,
        "cobertura_intervalo": [max(0.0, cobertura - 0.01), min(1.0, cobertura + 0.01)],
        "precisao_prevista": precisao,
        "precisao_intervalo": [inferior_final, superior_final],
        "intervalo_bruto": [inferior, superior],
        "intervalo_alargado": (inferior_final, superior_final) != (inferior, superior),
        "ancora": ancora_resultado,
        "n_ancora": n_ancora,
        "repeticoes_final": repeticoes_final,
        "degrau": degrau,
        "varredura_atingiu_alvo": varredura_atingiu_alvo,
        "alvo_atingido": alvo_atingido,
    }
    (pasta / "calibracao_resumo.json").write_text(json.dumps(resumo, indent=2, ensure_ascii=False), encoding="utf-8")
    registro.info("limiares %s; precisão prevista %.3f [%.3f, %.3f]; cobertura %.3f", limiares, precisao, inferior_final, superior_final, cobertura)
    return resumo
