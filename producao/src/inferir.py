"""Aplica o artefato empacotado e monta a linha do contrato."""

import time

from src.esquema import linha_log


def inferir(
    artefato: dict,
    features: dict,
    *,
    fluxo_id: str,
    anchor_id: int,
    classe_atual: str,
    run_id: str,
    ts_previsao: str,
    modelo_versao: str,
    modelo_hash: str,
    classes_saida: tuple[str, ...],
) -> dict:
    """Prevê a próxima classe. A probabilidade segue o nome, não a posição do sklearn."""
    inicio = time.perf_counter()
    vetor, ordenadas = artefato["preprocessador"].transformar(features)
    classe = str(artefato["modelo"].predict(vetor)[0])
    probabilidades = artefato["modelo"].predict_proba(vetor)[0]
    latencia = int(round((time.perf_counter() - inicio) * 1000))
    por_nome = {str(nome): float(valor) for nome, valor in zip(artefato["modelo"].classes_, probabilidades)}
    proba = {nome: por_nome[nome] for nome in classes_saida}
    return linha_log(
        run_id=run_id,
        ts_previsao=ts_previsao,
        fluxo_id=fluxo_id,
        anchor_id=anchor_id,
        modelo_versao=modelo_versao,
        modelo_hash=modelo_hash,
        features=ordenadas,
        proba=proba,
        classe_prevista=classe,
        classe_atual=classe_atual,
        latencia_inferencia_ms=latencia,
    )
