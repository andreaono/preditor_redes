"""Congela os critérios de aceite e confere se o YAML ainda é o mesmo.

O arquivo real nasce com limiares vazios. Congelar esse arquivo é recusado.
O pipeline chama verificar no início e para se o lock não bater.
"""

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

from src.ajustes import RAIZ

ARQUIVO_YAML = RAIZ / "config" / "criterios.yaml"
ARQUIVO_LOCK = RAIZ / "config" / "criterios.lock"

LIMIARES = (
    "macro_f1_transicoes_min",
    "recall_falha_min",
    "ganho_sobre_persistencia_min",
    "antecedencia_media_min_minutos",
)
FATIAS = (
    "geral",
    "transicoes",
    "por_continente",
    "probe_vs_anchor",
    "com_e_sem_anchor_dominante",
)


def hash_arquivo(caminho: Path) -> str:
    """SHA-256 dos bytes do arquivo, incluindo comentários."""
    digest = hashlib.sha256()
    digest.update(caminho.read_bytes())
    return digest.hexdigest()


def _numero_preenchido(valor) -> bool:
    return isinstance(valor, (int, float)) and not isinstance(valor, bool)


def pendencias(documento: dict) -> list[str]:
    """Lista o que ainda impede o congelamento."""
    faltas: list[str] = []
    if not isinstance(documento, dict):
        return ["o YAML não é um mapa"]
    if not documento.get("modelo_versao"):
        faltas.append("modelo_versao")
    fatias = documento.get("fatias")
    if list(fatias or []) != list(FATIAS):
        faltas.append("fatias")
    limiares = documento.get("limiares") or {}
    for nome in LIMIARES:
        if not _numero_preenchido(limiares.get(nome)):
            faltas.append(f"limiares.{nome}")
    if not _numero_preenchido(documento.get("periodo_minimo_coleta_dias")):
        faltas.append("periodo_minimo_coleta_dias")
    for nome in ("minimo_eventos_falha", "minimo_fluxos"):
        if not _numero_preenchido(documento.get(nome)):
            faltas.append(nome)
    bootstrap = documento.get("bootstrap") or {}
    for nome in ("nivel", "iteracoes", "seed", "ic"):
        if bootstrap.get(nome) is None:
            faltas.append(f"bootstrap.{nome}")
    return faltas


def ler(caminho: Path) -> dict:
    return yaml.safe_load(caminho.read_text(encoding="utf-8"))


def congelar(caminho_yaml: Path = ARQUIVO_YAML, caminho_lock: Path = ARQUIVO_LOCK) -> int:
    """Grava o lock se os limiares estão preenchidos e o arquivo não mudou depois."""
    documento = ler(caminho_yaml)
    faltas = pendencias(documento)
    if faltas:
        print("Congelamento recusado. Ainda vazio ou inválido: " + ", ".join(faltas))
        return 1
    resumo = hash_arquivo(caminho_yaml)
    if caminho_lock.is_file():
        guardado = json.loads(caminho_lock.read_text(encoding="utf-8"))
        if guardado.get("sha256") == resumo:
            print(f"Já congelado em {guardado.get('congelado_em')} com o mesmo conteúdo.")
            return 0
        print("O YAML mudou depois do congelamento. O lock anterior foi mantido.")
        return 1
    agora = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    lock = {
        "arquivo": caminho_yaml.name,
        "sha256": resumo,
        "congelado_em": agora,
        "modelo_versao": documento["modelo_versao"],
    }
    caminho_lock.write_text(json.dumps(lock, indent=2) + "\n", encoding="utf-8")
    print(f"Congelado em {agora}")
    print(f"modelo_versao: {documento['modelo_versao']}")
    print(f"sha256: {resumo}")
    return 0


def verificar(caminho_yaml: Path = ARQUIVO_YAML, caminho_lock: Path = ARQUIVO_LOCK) -> int:
    """Recalcula o hash. Código 1 se o lock não existe ou o YAML mudou."""
    if not caminho_lock.is_file():
        print(f"Lock ausente: {caminho_lock}")
        return 1
    if not caminho_yaml.is_file():
        print(f"Critérios ausentes: {caminho_yaml}")
        return 1
    guardado = json.loads(caminho_lock.read_text(encoding="utf-8"))
    atual = hash_arquivo(caminho_yaml)
    if guardado.get("sha256") != atual:
        print("Os critérios mudaram depois do congelamento.")
        print(f"lock: {guardado.get('sha256')}")
        print(f"arquivo: {atual}")
        return 1
    print(f"Critérios íntegros desde {guardado.get('congelado_em')}.")
    return 0


def main(argv: list[str] | None = None) -> int:
    argumentos = list(sys.argv[1:] if argv is None else argv)
    if argumentos not in (["congelar"], ["verificar"]):
        print("Uso: python -m src.congelar_criterios congelar|verificar")
        return 2
    if argumentos[0] == "congelar":
        return congelar()
    return verificar()


if __name__ == "__main__":
    raise SystemExit(main())
