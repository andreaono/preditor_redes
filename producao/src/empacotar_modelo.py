"""Empacota o modelo já treinado, sem retreinar e sem ler o split de teste.

A amostra de conferência sai só de linhas com split treino. O arquivo
Treino/predicoes_amostra.csv citado no enunciado não existe neste repositório.
A amostra gerada fica em modelo/predicoes_amostra.csv.
"""

import csv
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from src.ajustes import RAIZ, carregar
from src.baseline_fluxo import persistencia, regra
from src.features_treino import grupos, nomes_features
from src.preprocessador import PreprocessadorIdentidade
from src.prever import hash_arquivo

N_AMOSTRA = 20
SEED = 42
PASTA_MODELO = RAIZ / "modelo"
ARQUIVO_AMOSTRA = PASTA_MODELO / "predicoes_amostra.csv"
ARQUIVO_MANIFESTO = PASTA_MODELO / "modelo_manifest.json"
ARQUIVO_CARTAO = PASTA_MODELO / "MODEL_CARD.md"

CHAVES_MANIFESTO = (
    "modelo_versao",
    "arquivo",
    "sha256",
    "treinado_em",
    "origem_treinado_em",
    "hash_dataset_treino",
    "descricao_hash_dataset_treino",
    "hash_dataset_final",
    "descricao_hash_dataset_final",
    "colunas_features",
    "grupos_features",
    "hiperparametros",
    "metricas_validacao",
    "metricas_teste",
    "versoes_bibliotecas",
    "seed",
    "commit_git",
    "amostra",
    "preprocessador",
)


def _versao(pacote: str):
    try:
        return version(pacote)
    except PackageNotFoundError:
        return None


def _instante_arquivo(caminho: Path) -> str:
    return datetime.fromtimestamp(caminho.stat().st_mtime, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _commit_git() -> str | None:
    try:
        processo = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=RAIZ.parent,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None
    if processo.returncode != 0:
        return None
    texto = processo.stdout.strip()
    return texto or None


def _hash_split(caminho: Path, split: str) -> tuple[str, int]:
    """Hash das linhas de um split, na ordem do arquivo, com o cabeçalho."""
    digest = hashlib.sha256()
    with caminho.open(newline="", encoding="utf-8") as arquivo:
        leitor = csv.reader(arquivo)
        cabeca = next(leitor)
        indice = cabeca.index("split")
        digest.update(("|".join(cabeca) + "\n").encode("utf-8"))
        quantidade = 0
        for linha in leitor:
            if linha[indice] != split:
                continue
            digest.update(("|".join(linha) + "\n").encode("utf-8"))
            quantidade += 1
    return digest.hexdigest(), quantidade


def _fatia(bloco: dict | None) -> dict | None:
    if not isinstance(bloco, dict):
        return None
    return {
        "n": bloco.get("n"),
        "macro_f1": bloco.get("macro_f1"),
        "recall_falha": bloco.get("recall_falha"),
    }


def _cartao(manifesto: dict) -> str:
    grupos_texto = manifesto["grupos_features"]
    validacao = manifesto["metricas_validacao"]
    teste = manifesto["metricas_teste"]
    return "\n".join(
        [
            "# Cartão do modelo",
            "",
            f"Versão: `{manifesto['modelo_versao']}`. Família: Random Forest. Semente: {manifesto['seed']}.",
            "",
            "O artefato foi empacotado a partir do joblib já escolhido na validação. Não houve novo treino. O split de teste não foi lido para montar a amostra.",
            "",
            "## Dados",
            "",
            f"Data registrada: {manifesto['treinado_em']}. Origem dessa data: {manifesto['origem_treinado_em']}.",
            f"Hash das linhas de treino do dataset final: `{manifesto['hash_dataset_treino']}`. {manifesto['descricao_hash_dataset_treino']}",
            f"Hash do arquivo inteiro do dataset final: `{manifesto['hash_dataset_final']}`. {manifesto['descricao_hash_dataset_final']}",
            "",
            "## Features",
            "",
            "A ordem é a de `lista_features` da etapa 7. Os grupos são instantânea, janela e dinâmica.",
            "",
            f"- instantânea: {', '.join(grupos_texto['instantanea'])}",
            f"- janela: {', '.join(grupos_texto['janela'])}",
            f"- dinâmica: {', '.join(grupos_texto['dinamica'])}",
            "",
            "O pré-processador do artefato é a identidade: o treino não ajustou scaler. A sentinela −1 é aplicada pela função da etapa 7, depois das janelas.",
            "",
            "O treino usou n_jobs=-1. No artefato, a inferência usa n_jobs=1. Com várias threads, a soma das árvores muda a probabilidade em um único bit de um chamado para o outro. A classe não muda. Uma thread deixa a amostra igual ao joblib original, sem retreinar.",
            "",
            "## Hiperparâmetros",
            "",
            "```",
            json.dumps(manifesto["hiperparametros"], ensure_ascii=False, indent=2),
            "```",
            "",
            "## Métricas já calculadas",
            "",
            "Validação, copiada de `pipeline/08_treino/data/resultados_validacao.json`:",
            "",
            "```",
            json.dumps(validacao, ensure_ascii=False, indent=2),
            "```",
            "",
            "Teste, copiado de `pipeline/08_treino/data/avaliacao_teste.json`. Esta cópia não é uma nova avaliação:",
            "",
            "```",
            json.dumps(teste, ensure_ascii=False, indent=2),
            "```",
            "",
            "## Uso e limite",
            "",
            "A previsão é a classe da próxima medição do mesmo fluxo. `classe_atual` fica no log e fora do vetor. O rótulo real chega depois e não entra na conta das features.",
            "",
            "O baseline de um fluxo novo usa a persistência (`classe_atual`) e a regra da etapa 7, importadas, não reescritas. Um fluxo sem baseline válido não recebe classe inventada.",
            "",
            f"Bibliotecas no empacotamento: `{json.dumps(manifesto['versoes_bibliotecas'], ensure_ascii=False)}`.",
            "",
            f"Commit git no empacotamento: `{manifesto['commit_git']}`.",
            "",
            f"Amostra de conferência: `{manifesto['amostra']['arquivo']}`, {manifesto['amostra']['n']} linhas, semente {manifesto['amostra']['seed']}, somente split `{manifesto['amostra']['split']}`.",
            "",
        ]
    )


def empacotar() -> dict:
    """Monta o joblib, o manifesto, o cartão e a amostra de treino."""
    ajustes = carregar()
    features = nomes_features()
    original = ajustes["arquivo_modelo"]
    print("Carregando o joblib original.")
    pacote = joblib.load(original)
    if list(pacote["features"]) != features:
        raise SystemExit("As features do joblib original divergem da etapa 7.")
    modelo = pacote["modelo"]
    if getattr(modelo, "n_jobs", None) not in (1, None):
        modelo.set_params(n_jobs=1)
    dataset = RAIZ.parent / "pipeline" / "07_rotulagem" / "data" / "dataset_final.csv"
    print("Hasheando o dataset final e as linhas de treino.")
    hash_final = hash_arquivo(dataset)
    hash_treino_nu, n_treino = _hash_split(dataset, "treino")
    hash_treino = "sha256:" + hash_treino_nu
    print(f"Linhas de treino no hash: {n_treino}.")
    print("Amostrando só o split treino.")
    quadro = pd.read_csv(dataset, usecols=["id_fluxo", "timestamp", "split", *features])
    treino = quadro.loc[quadro["split"] == "treino"]
    if "teste" in set(treino["split"]):
        raise SystemExit("A amostra de treino contém o split de teste.")
    amostra = treino.sample(n=N_AMOSTRA, random_state=SEED)
    if set(amostra["split"]) != {"treino"}:
        raise SystemExit("A amostra não ficou restrita ao treino.")
    vetor = amostra[features].astype(float).to_numpy()
    classes_previstas = [str(item) for item in modelo.predict(vetor)]
    versao_features = "etapa7-" + hashlib.sha256("\n".join(features).encode("utf-8")).hexdigest()[:12]
    artefato = {
        "modelo": modelo,
        "preprocessador": PreprocessadorIdentidade(features),
        "colunas_features": list(features),
        "classes": [str(item) for item in modelo.classes_],
        "versao_features": versao_features,
        "baseline_persistencia": persistencia,
        "baseline_regra": regra,
    }
    PASTA_MODELO.mkdir(parents=True, exist_ok=True)
    destino = PASTA_MODELO / f"modelo_{ajustes['modelo_versao']}.joblib"
    print(f"Gravando {destino.name}.")
    joblib.dump(artefato, destino)
    recarregado = joblib.load(destino)
    de_novo = [str(item) for item in recarregado["modelo"].predict(vetor)]
    if de_novo != classes_previstas:
        raise SystemExit("O artefato empacotado não reproduziu as classes do joblib original.")
    proba_original = modelo.predict_proba(vetor)
    proba_pacote = recarregado["modelo"].predict_proba(vetor)
    if not np.array_equal(proba_original, proba_pacote):
        raise SystemExit("O artefato empacotado não reproduziu as probabilidades do joblib original.")
    tabela = amostra[["id_fluxo", "timestamp", "split", *features]].copy()
    tabela["classe_prevista"] = classes_previstas
    tabela.to_csv(ARQUIVO_AMOSTRA, index=False)
    escolhido = json.loads(ajustes["arquivo_metadados_modelo"].read_text(encoding="utf-8"))
    validacao_bruta = json.loads((RAIZ.parent / "pipeline" / "08_treino" / "data" / "resultados_validacao.json").read_text(encoding="utf-8"))
    teste_bruto = json.loads((RAIZ.parent / "pipeline" / "08_treino" / "data" / "avaliacao_teste.json").read_text(encoding="utf-8"))
    floresta = validacao_bruta["familias"]["random_forest"]
    manifesto = {
        "modelo_versao": ajustes["modelo_versao"],
        "arquivo": destino.name,
        "sha256": hash_arquivo(destino),
        "treinado_em": _instante_arquivo(original),
        "origem_treinado_em": "mtime UTC do joblib original; o JSON do modelo escolhido não traz um instante de treino separado",
        "hash_dataset_treino": hash_treino,
        "descricao_hash_dataset_treino": (
            f"SHA-256 do cabeçalho mais as {n_treino} linhas com split=treino, "
            "na ordem do arquivo, campos unidos por |. Não inclui validação nem teste."
        ),
        "hash_dataset_final": hash_final,
        "descricao_hash_dataset_final": "SHA-256 dos bytes do arquivo dataset_final.csv, com os três splits.",
        "colunas_features": list(features),
        "grupos_features": grupos(),
        "hiperparametros": escolhido["hiperparametros"],
        "metricas_validacao": {
            "fonte": "pipeline/08_treino/data/resultados_validacao.json",
            "macro_f1_treino": floresta["macro_f1_treino"],
            "macro_f1_validacao": floresta["macro_f1_validacao"],
            "gap": floresta["gap"],
            "recall_falha_validacao": floresta["recall_falha_validacao"],
            "geral": _fatia(floresta["validacao"]["geral"]),
            "transicoes": _fatia(floresta["validacao"]["transicoes"]),
            "inicio_falha": _fatia(floresta["validacao"].get("inicio_falha")),
            "persistencia_geral": _fatia(validacao_bruta["persistencia"]["validacao"]["geral"]),
        },
        "metricas_teste": {
            "fonte": "pipeline/08_treino/data/avaliacao_teste.json",
            "nota": "Cópia da avaliação já executada. Este empacotamento não releu o split de teste.",
            "geral": _fatia(teste_bruto["modelo"]["geral"]),
            "transicoes": _fatia(teste_bruto["modelo"]["transicoes"]),
            "inicio_falha": _fatia(teste_bruto["modelo"].get("inicio_falha")),
            "persistencia_geral": _fatia(teste_bruto["persistencia"]["geral"]),
            "ganho": teste_bruto["ganho"],
            "analise_teste": teste_bruto["analise_teste"],
            "frase_fixa": teste_bruto["frase_fixa"],
        },
        "versoes_bibliotecas": {
            "python": sys.version.split()[0],
            "scikit-learn": _versao("scikit-learn"),
            "numpy": _versao("numpy"),
            "pandas": _versao("pandas"),
            "joblib": _versao("joblib"),
            "xgboost": _versao("xgboost"),
            "xgboost_nota": "nao instalado; o modelo escolhido e o Random Forest" if _versao("xgboost") is None else None,
        },
        "seed": SEED,
        "commit_git": _commit_git(),
        "amostra": {
            "arquivo": "modelo/predicoes_amostra.csv",
            "n": N_AMOSTRA,
            "seed": SEED,
            "split": "treino",
            "origem": "previsao do joblib original sobre linhas do dataset final com split treino",
            "teste_nao_lido": True,
            "proba_identica_ao_original": True,
        },
        "preprocessador": "identidade; sem scaler; sentinela -1 fica na funcao da etapa 7",
        "n_jobs_treino": -1,
        "n_jobs_inferencia": 1,
        "joblib_original": str(original),
        "sha256_joblib_original": hash_arquivo(original),
    }
    faltando = [chave for chave in CHAVES_MANIFESTO if chave not in manifesto]
    if faltando:
        raise SystemExit("Manifesto incompleto: " + ", ".join(faltando))
    ARQUIVO_MANIFESTO.write_text(json.dumps(manifesto, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    ARQUIVO_CARTAO.write_text(_cartao(manifesto), encoding="utf-8")
    print(f"Manifesto: {manifesto['sha256']}")
    print(f"Amostra: {ARQUIVO_AMOSTRA.name}")
    return manifesto


def main() -> int:
    empacotar()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
