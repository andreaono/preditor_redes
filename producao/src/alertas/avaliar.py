"""Transforma drift e desempenho em alerta, com deduplicação e cooldown."""

import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
import yaml

from src.ajustes import RAIZ


def carregar_regras(caminho: Path | None = None) -> dict:
    arquivo = caminho or (RAIZ / "config" / "alertas.yaml")
    return yaml.safe_load(arquivo.read_text(encoding="utf-8"))


def _importantes(importancia: dict | None) -> set[str]:
    if not importancia:
        return set()
    valores = [float(valor) for valor in importancia.values()]
    mediana = sorted(valores)[len(valores) // 2]
    return {nome for nome, valor in importancia.items() if float(valor) >= mediana and float(valor) > 0}


def _id(regra: str, chave: str) -> str:
    return hashlib.sha256(f"{regra}:{chave}".encode("utf-8")).hexdigest()[:16]


def _instante(texto: str) -> datetime:
    return datetime.strptime(texto, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def _em_cooldown(anteriores: list[dict], regra: str, chave: str, agora: datetime, horas: int) -> bool:
    limite = agora - timedelta(hours=horas)
    for item in anteriores:
        if item.get("regra") != regra or item.get("chave") != chave:
            continue
        if item.get("status") == "resolvido":
            continue
        if _instante(item["ts"]) >= limite:
            return True
    return False


def _novo(regra: str, gravidade: str, chave: str, evidencia: dict, acao: str, agora: datetime) -> dict:
    return {
        "id": _id(regra, chave),
        "ts": agora.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "regra": regra,
        "chave": chave,
        "gravidade": gravidade,
        "evidencia": evidencia,
        "acao": acao,
        "status": "aberto",
    }


def _janelas_abaixo(historico: list[dict], quantidade: int, limiar: float) -> bool:
    recentes = historico[-quantidade:]
    if len(recentes) < quantidade:
        return False
    for item in recentes:
        if item.get("status") == "amostra_insuficiente":
            return False
        if item.get("macro_f1") is None or float(item["macro_f1"]) >= limiar:
            return False
    return True


def gerar(
    relatorio: dict | None,
    regras: dict,
    historico_desempenho: list[dict] | None = None,
    agora: datetime | None = None,
) -> list[dict]:
    """Aplica as regras. Amostra insuficiente não gera alerta."""
    momento = agora or datetime.now(timezone.utc)
    saida: list[dict] = []
    bloco = regras["regras"]
    if relatorio:
        importantes = _importantes(relatorio.get("importancia_permutacao"))
        for janela in relatorio.get("janelas") or []:
            dados = janela.get("data_drift") or {}
            if dados.get("status") == "amostra_insuficiente":
                continue
            for nome, info in (dados.get("features") or {}).items():
                if info.get("status") != "alerta":
                    continue
                psi = info.get("psi")
                if nome in importantes and psi is not None and psi > bloco["psi_feature_importante"]["limiar"]:
                    saida.append(
                        _novo(
                            "psi_feature_importante",
                            bloco["psi_feature_importante"]["gravidade"],
                            f"{janela.get('nome')}:{nome}",
                            {"psi": psi, "feature": nome, "arquivo": relatorio.get("arquivo")},
                            bloco["psi_feature_importante"]["acao"],
                            momento,
                        )
                    )
            predicao = janela.get("predicao") or {}
            if predicao.get("status") == "alerta":
                saida.append(
                    _novo(
                        "proporcao_classes",
                        bloco["proporcao_classes"]["gravidade"],
                        f"{janela.get('nome')}:proporcao",
                        {"js": predicao.get("js"), "arquivo": relatorio.get("arquivo")},
                        bloco["proporcao_classes"]["acao"],
                        momento,
                    )
                )
            for fatia in janela.get("fatias") or []:
                if fatia.get("status") == "amostra_insuficiente":
                    continue
        coleta = relatorio.get("coleta") or {}
        if coleta.get("falha_coleta") or coleta.get("contrato_invalido"):
            saida.append(
                _novo(
                    "contrato_ou_coleta",
                    bloco["contrato_ou_coleta"]["gravidade"],
                    "coleta",
                    {"falha_coleta": bool(coleta.get("falha_coleta")), "contrato_invalido": bool(coleta.get("contrato_invalido"))},
                    bloco["contrato_ou_coleta"]["acao"],
                    momento,
                )
            )
    piso = float(bloco["macro_f1"]["limiar"])
    quantidade = int(bloco["macro_f1"]["janelas_consecutivas"])
    if _janelas_abaixo(historico_desempenho or [], quantidade, piso):
        saida.append(
            _novo(
                "macro_f1",
                bloco["macro_f1"]["gravidade"],
                "macro_f1",
                {"janelas": (historico_desempenho or [])[-quantidade:], "limiar": piso},
                bloco["macro_f1"]["acao"],
                momento,
            )
        )
    return saida


def filtrar_cooldown(alertas: list[dict], anteriores: list[dict], regras: dict, agora: datetime | None = None) -> list[dict]:
    """Não repete a mesma regra e a mesma chave dentro do cooldown."""
    momento = agora or datetime.now(timezone.utc)
    horas = int(regras["cooldown_horas"])
    return [item for item in alertas if not _em_cooldown(anteriores, item["regra"], item["chave"], momento, horas)]


def _publicar_canais(alerta: dict) -> dict:
    """Arquivo é o canal padrão. E-mail e webhook só existem se o ambiente os definir."""
    alerta = dict(alerta)
    alerta["canais"] = ["arquivo"]
    url = os.environ.get("ALERTA_WEBHOOK_URL", "").strip()
    if url:
        try:
            requests.post(url, json=alerta, timeout=10)
            alerta["canais"].append("webhook")
        except requests.RequestException as erro:
            alerta["webhook_erro"] = str(erro)
    destino = os.environ.get("ALERTA_EMAIL_PARA", "").strip()
    servidor = os.environ.get("ALERTA_SMTP_HOST", "").strip()
    if destino and servidor:
        alerta["canais"].append("email")
        alerta["email_para"] = destino
    elif destino:
        alerta["email"] = "destino definido sem ALERTA_SMTP_HOST; nada foi enviado"
    return alerta


def registrar(alertas: list[dict], pasta: Path, agora: datetime | None = None) -> list[dict]:
    momento = agora or datetime.now(timezone.utc)
    if not alertas:
        return []
    pasta.mkdir(parents=True, exist_ok=True)
    destino = pasta / f"{momento.strftime('%Y-%m-%d')}.jsonl"
    gravados = []
    with destino.open("a", encoding="utf-8") as arquivo:
        for alerta in alertas:
            publicado = _publicar_canais(alerta)
            arquivo.write(json.dumps(publicado, ensure_ascii=False) + "\n")
            gravados.append(publicado)
    return gravados


def ler_anteriores(pasta: Path) -> list[dict]:
    if not pasta.is_dir():
        return []
    linhas = []
    for arquivo in sorted(pasta.glob("*.jsonl")):
        for texto in arquivo.read_text(encoding="utf-8").splitlines():
            if texto.strip():
                linhas.append(json.loads(texto))
    return linhas


def avaliar(relatorio: dict | None, pasta: Path, historico_desempenho: list[dict] | None = None, agora: datetime | None = None, regras: dict | None = None) -> list[dict]:
    """Gera, descarta repetidos e grava os que restam."""
    regras = regras or carregar_regras()
    momento = agora or datetime.now(timezone.utc)
    novos = gerar(relatorio, regras, historico_desempenho, momento)
    aceitos = filtrar_cooldown(novos, ler_anteriores(pasta), regras, momento)
    return registrar(aceitos, pasta, momento)
