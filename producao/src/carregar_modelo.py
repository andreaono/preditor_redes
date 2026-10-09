"""Abre o artefato empacotado e recusa se o hash não bater com o manifesto."""

import json
import sys
import warnings
from functools import lru_cache
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

import joblib

from src.prever import hash_arquivo

MANIFESTO_PADRAO = "modelo_manifest.json"


def versao_instalada(pacote: str):
    try:
        return version(pacote)
    except PackageNotFoundError:
        return None


def carregar_modelo(caminho, manifesto=None):
    """Confere o SHA-256, avisa se a biblioteca mudou e devolve o artefato."""
    arquivo = Path(caminho)
    if manifesto is None:
        manifesto = arquivo.parent / MANIFESTO_PADRAO
    return _carregar_cacheado(str(Path(arquivo).resolve()), str(Path(manifesto).resolve()))


@lru_cache(maxsize=4)
def _carregar_cacheado(caminho: str, manifesto: str):
    arquivo = Path(caminho)
    manifesto = Path(manifesto)
    if not manifesto.is_file():
        raise RuntimeError(f"Manifesto ausente: {manifesto}")
    documento = json.loads(manifesto.read_text(encoding="utf-8"))
    esperado = documento.get("sha256")
    obtido = hash_arquivo(arquivo)
    if obtido != esperado:
        raise RuntimeError(
            "O hash do artefato não confere com o manifesto. "
            f"Esperado {esperado}, calculado {obtido}. O arquivo pode ter sido alterado."
        )
    gravadas = documento.get("versoes_bibliotecas") or {}
    for pacote in ("scikit-learn", "numpy", "pandas", "joblib"):
        atual = versao_instalada(pacote)
        antiga = gravadas.get(pacote)
        if antiga and atual and antiga != atual:
            warnings.warn(
                f"A versão de {pacote} mudou desde o empacotamento: manifesto {antiga}, ambiente {atual}.",
                RuntimeWarning,
                stacklevel=2,
            )
    pacote = joblib.load(arquivo)
    colunas = list(pacote["colunas_features"])
    if colunas != list(documento["colunas_features"]):
        raise RuntimeError("A ordem das colunas do artefato diverge do manifesto.")
    return pacote


def main(argv=None) -> int:
    argumentos = list(sys.argv[1:] if argv is None else argv)
    if len(argumentos) != 1:
        print("Uso: python -m src.carregar_modelo <arquivo.joblib>")
        return 2
    artefato = carregar_modelo(argumentos[0])
    print(f"Artefato íntegro. Colunas: {len(artefato['colunas_features'])}. Versão das features: {artefato['versao_features']}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
