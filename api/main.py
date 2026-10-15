"""Rotas da API: `GET /saude`, `GET /temas` e `POST /classificar`.

Execução: `uv run uvicorn api.main:app --reload --port 8000`.
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from api.servico import Servico
from classificador.config import ChaveAusenteError


@asynccontextmanager
async def ciclo_de_vida(app: FastAPI):
    yield
    servico.fechar()


app = FastAPI(title="Classificador de tópicos", lifespan=ciclo_de_vida)
# Nada é carregado aqui: o serviço monta cada peça na primeira requisição que precisa dela.
servico = Servico()


class Entrada(BaseModel):
    enunciado_html: str = Field(description="enunciado da questão, com ou sem HTML")
    comando: str = Field("", description="comando da questão; vazio quando não há")
    alternativas: dict[str, str] = Field(description='texto de cada alternativa pela letra, como {"A": "..."}')


@app.get("/saude")
def saude() -> dict:
    """Chaves de API presentes, Weaviate alcançável, corpus, votos em cache e limiares em uso."""
    return servico.saude()


@app.get("/temas")
def temas() -> list[dict]:
    """Temas publicáveis: ativos, canônicos e fora das raízes de disciplina."""
    return servico.temas()


@app.post("/classificar")
def classificar(entrada: Entrada) -> dict:
    """Decisão (publicar, revisar ou fora), tema central, extras, confiança, motivo, candidatos e os três votos."""
    try:
        return servico.classificar(entrada.enunciado_html, entrada.comando, entrada.alternativas)
    except ChaveAusenteError as erro:
        raise HTTPException(status_code=503, detail=str(erro)) from erro
