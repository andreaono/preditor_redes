"""Referência de drift a partir do treino e da validação. O teste não entra."""

import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.inspection import permutation_importance
from sklearn.metrics import f1_score

from src.ajustes import RAIZ, carregar
from src.drift.metricas import bordas_quantis, proporcoes_nos_bins, psi, taxa_nulos
from src.features_treino import nomes_features

BINS = 10
SEED = 42
N_BLOCOS = 30
N_FLUXOS_BLOCO = 8
N_IMPORTANCIA = 200
REPETICOES_IMPORTANCIA = 3


def _proporcao(serie: pd.Series, classes: tuple[str, ...]) -> dict:
    total = int(serie.shape[0])
    if total == 0:
        return {classe: 0.0 for classe in classes}
    contagem = serie.value_counts()
    return {classe: float(contagem.get(classe, 0) / total) for classe in classes}


def _numero(valor):
    if isinstance(valor, float) and not np.isfinite(valor):
        return None
    if isinstance(valor, (np.floating, np.integer)):
        return valor.item()
    return valor


def calibrar(quadro: pd.DataFrame, nomes: list[str], bordas: dict) -> dict:
    """PSI de blocos do próprio treino. A sugestão não substitui o piso 0,1 / 0,25."""
    fluxos = quadro["id_fluxo"].drop_duplicates().to_numpy()
    gerador = np.random.default_rng(SEED)
    amostras: dict[str, list[float]] = {nome: [] for nome in nomes}
    if fluxos.size < 2:
        return {"blocos": 0, "por_feature": {}}
    for _ in range(N_BLOCOS):
        escolha = gerador.choice(fluxos, size=min(N_FLUXOS_BLOCO, fluxos.size), replace=False)
        bloco = quadro.loc[quadro["id_fluxo"].isin(escolha)]
        for nome in nomes:
            valor = psi(quadro[nome], bloco[nome], bins=BINS, bordas=bordas[nome])
            if np.isfinite(valor):
                amostras[nome].append(float(valor))
    por_feature = {}
    for nome, valores in amostras.items():
        if not valores:
            continue
        serie = np.asarray(valores)
        por_feature[nome] = {
            "mediana": float(np.median(serie)),
            "p95": float(np.quantile(serie, 0.95)),
        }
    p95 = [item["p95"] for item in por_feature.values()]
    sugestao = float(np.median(p95)) if p95 else None
    return {
        "blocos": N_BLOCOS,
        "fluxos_por_bloco": N_FLUXOS_BLOCO,
        "seed": SEED,
        "por_feature": por_feature,
        "sugestao_atencao": sugestao,
        "sugestao_alerta": None if sugestao is None else max(0.25, sugestao * 2),
        "nota": "Os pisos em uso continuam 0,1 e 0,25. A sugestão só informa a variação natural.",
    }


def _importancia(modelo, quadro: pd.DataFrame, nomes: list[str]) -> dict:
    treino = quadro.loc[quadro["split"] == "treino"]
    if len(treino) > N_IMPORTANCIA:
        treino = treino.sample(n=N_IMPORTANCIA, random_state=SEED)
    vetor = treino[nomes].astype(float).to_numpy()
    alvo = treino["alvo"].to_numpy()
    resultado = permutation_importance(
        modelo,
        vetor,
        alvo,
        n_repeats=REPETICOES_IMPORTANCIA,
        random_state=SEED,
        scoring=lambda estimador, x, y: f1_score(y, estimador.predict(x), average="macro", zero_division=0),
        n_jobs=1,
    )
    return {
        nome: float(valor)
        for nome, valor in zip(nomes, resultado.importances_mean)
    }


def gerar(caminho_csv: Path, caminho_saida: Path, modelo=None) -> dict:
    """Quantis, classes e nulos de treino+validação. O split teste é descartado."""
    nomes = nomes_features()
    classes = carregar()["classes"]
    colunas = ["id_fluxo", "split", "alvo", *nomes]
    quadro = pd.read_csv(caminho_csv, usecols=colunas)
    quadro = quadro.loc[quadro["split"].isin(["treino", "validacao"])].copy()
    if "teste" in set(quadro["split"]):
        raise SystemExit("A referência de drift leu o split de teste.")
    for nome in nomes:
        quadro[nome] = pd.to_numeric(quadro[nome], errors="coerce")
    features = {}
    bordas = {}
    for nome in nomes:
        valores = quadro[nome].to_numpy(dtype=float)
        limites = bordas_quantis(valores, BINS)
        bordas[nome] = limites
        serie = quadro[nome]
        finitos = serie[np.isfinite(serie.to_numpy(dtype=float))]
        if len(finitos) > 2000:
            amostra = finitos.sample(n=2000, random_state=SEED).tolist()
        else:
            amostra = finitos.tolist()
        features[nome] = {
            "n": int(np.isfinite(valores).sum()),
            "taxa_nulos": taxa_nulos(valores),
            "taxa_sentinela": float(np.mean(valores == -1)),
            "quantis": [_numero(item) for item in limites],
            "proporcao_bins": proporcoes_nos_bins(valores, limites),
            "amostra": [float(item) for item in amostra],
        }
    documento = {
        "splits": ["treino", "validacao"],
        "teste_excluido": True,
        "n": int(len(quadro)),
        "bins": BINS,
        "features": features,
        "proporcao_classes_reais": _proporcao(quadro["alvo"], classes),
        "proporcao_classes_previstas": None,
        "calibracao_psi": calibrar(quadro, nomes, bordas),
        "importancia_permutacao": None,
        "nota_importancia": "A etapa 8 não gravou importância por permutação. Ela é calculada aqui numa amostra do treino, sem retreinar.",
    }
    if modelo is not None:
        documento["importancia_permutacao"] = _importancia(modelo, quadro, nomes)
        amostra = quadro.loc[quadro["split"] == "treino"]
        if len(amostra) > N_IMPORTANCIA:
            amostra = amostra.sample(n=N_IMPORTANCIA, random_state=SEED)
        previstas = pd.Series(modelo.predict(amostra[nomes].astype(float).to_numpy()))
        documento["proporcao_classes_previstas"] = _proporcao(previstas, classes)
        documento["n_amostra_prevista"] = int(len(amostra))
    caminho_saida.parent.mkdir(parents=True, exist_ok=True)
    caminho_saida.write_text(json.dumps(documento, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return documento


def main() -> int:
    import joblib

    pacote = joblib.load(RAIZ / "modelo" / "modelo_rf_v1.0.0.joblib")
    csv = RAIZ.parent / "pipeline" / "07_rotulagem" / "data" / "dataset_final.csv"
    gerar(csv, RAIZ / "modelo" / "ref_stats.json", modelo=pacote["modelo"])
    print("Referência gravada em modelo/ref_stats.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
