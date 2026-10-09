"""Monta o relatório de drift. Fatia pequena não vira alerta."""

import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
from sklearn.metrics import f1_score, recall_score

from src.ajustes import RAIZ, carregar
from src.drift.metricas import divergencia_js, ks, psi, psi_com_referencia, status_psi, taxa_nulos

ORDEM = {"amostra_insuficiente": 0, "estavel": 1, "atencao": 2, "alerta": 3}


def _pior(statuses: list[str]) -> str:
    if not statuses:
        return "amostra_insuficiente"
    return max(statuses, key=lambda item: ORDEM.get(item, 0))


def faixa_rtt(valor) -> str:
    """Faixa da razão RTT/p95. A sentinela -1 é ausência, não um RTT baixo."""
    try:
        numero = float(valor)
    except (TypeError, ValueError):
        return "sem_rtt"
    if not math.isfinite(numero) or numero == -1:
        return "sem_rtt"
    if numero < 0.8:
        return "abaixo"
    if numero <= 1.2:
        return "tipica"
    return "alta"


def _data_features(referencia: dict, atual: pd.DataFrame, minimo: int, estavel: float, alerta: float) -> dict:
    if len(atual) < minimo:
        return {"n": int(len(atual)), "status": "amostra_insuficiente"}
    por_feature = {}
    statuses = []
    for nome, info in referencia["features"].items():
        if nome not in atual.columns:
            continue
        valor = psi_com_referencia(info["proporcao_bins"], atual[nome], info["quantis"])
        situacao = status_psi(valor, estavel, alerta)
        por_feature[nome] = {
            "psi": None if not math.isfinite(valor) else valor,
            "ks": ks(info.get("amostra") or [], atual[nome]),
            "taxa_nulos": taxa_nulos(atual[nome]),
            "status": situacao,
            "n": int(len(atual)),
        }
        statuses.append(situacao)
    return {"n": int(len(atual)), "status": _pior(statuses), "features": por_feature}


def _qualidade(referencia: dict, atual: pd.DataFrame, minimo: int) -> dict:
    if len(atual) < minimo:
        return {"n": int(len(atual)), "status": "amostra_insuficiente"}
    detalhes = {}
    statuses = []
    for nome, info in referencia["features"].items():
        if nome not in atual.columns:
            continue
        taxa = taxa_nulos(atual[nome])
        base = float(info.get("taxa_nulos") or 0)
        situacao = "alerta" if taxa > base + 0.2 else "estavel"
        detalhes[nome] = {"taxa_nulos": taxa, "referencia": base, "status": situacao}
        statuses.append(situacao)
    return {"n": int(len(atual)), "status": _pior(statuses) if statuses else "estavel", "features": detalhes}


def _predicao(referencia: dict, atual: pd.DataFrame, minimo: int, js_alerta: float) -> dict:
    if "classe_prevista" not in atual.columns or len(atual) < minimo:
        return {"n": int(len(atual)), "status": "amostra_insuficiente"}
    classes = carregar()["classes"]
    contagem = atual["classe_prevista"].value_counts(normalize=True)
    atual_prop = {classe: float(contagem.get(classe, 0)) for classe in classes}
    referencia_prop = referencia.get("proporcao_classes_previstas") or referencia.get("proporcao_classes_reais")
    valor = divergencia_js(referencia_prop, atual_prop)
    situacao = "estavel" if not math.isfinite(valor) or valor < js_alerta / 2 else "atencao"
    if math.isfinite(valor) and valor >= js_alerta:
        situacao = "alerta"
    return {"n": int(len(atual)), "js": None if not math.isfinite(valor) else valor, "proporcao": atual_prop, "status": situacao}


def _desempenho(atual: pd.DataFrame, minimo: int, macro_min: float, recall_min: float) -> dict:
    if "rotulo_real" not in atual.columns:
        return {"n": 0, "status": "amostra_insuficiente"}
    rotuladas = atual.loc[atual["rotulo_real"].notna()]
    if len(rotuladas) < minimo:
        return {"n": int(len(rotuladas)), "status": "amostra_insuficiente"}
    classes = list(carregar()["classes"])
    macro = float(f1_score(rotuladas["rotulo_real"], rotuladas["classe_prevista"], average="macro", labels=classes, zero_division=0))
    recall = float(recall_score(rotuladas["rotulo_real"], rotuladas["classe_prevista"], labels=["FALHA"], average="macro", zero_division=0))
    situacao = "alerta" if macro < macro_min or recall < recall_min else "estavel"
    return {"n": int(len(rotuladas)), "macro_f1": macro, "recall_falha": recall, "status": situacao}


def _rotas(atual: pd.DataFrame, minimo: int) -> list[dict]:
    """RTT alto e persistente, com perda baixa, não é o mesmo que degradação."""
    if "fluxo_id" not in atual.columns or "razao_rtt_p95" not in atual.columns:
        return []
    achados = []
    for fluxo, grupo in atual.groupby("fluxo_id"):
        if len(grupo) < minimo:
            continue
        razao = pd.to_numeric(grupo["razao_rtt_p95"], errors="coerce")
        perda = pd.to_numeric(grupo["perda_pct"], errors="coerce") if "perda_pct" in grupo else pd.Series(dtype=float)
        if razao.median(skipna=True) > 1.5 and (perda.empty or perda.median(skipna=True) < 5):
            achados.append(
                {
                    "fluxo_id": fluxo,
                    "n": int(len(grupo)),
                    "status": "mudanca_de_rota_provavel",
                    "razao_mediana": float(razao.median()),
                }
            )
    return achados


def _aplicar_feriados(quadro: pd.DataFrame, feriados: set[str]) -> pd.DataFrame:
    if quadro.empty or "ts_previsao" not in quadro.columns or not feriados:
        return quadro
    datas = quadro["ts_previsao"].astype(str).str.slice(0, 10)
    return quadro.loc[~datas.isin(feriados)].copy()


def janela(quadro: pd.DataFrame, fim: datetime, horas: int, feriados: set[str]) -> pd.DataFrame:
    """Recorte [fim - horas, fim). Linhas de feriado saem dos dois lados da comparação."""
    inicio = fim - timedelta(hours=horas)
    if quadro.empty or "ts_previsao" not in quadro.columns:
        return quadro.iloc[0:0].copy()
    instantes = pd.to_datetime(quadro["ts_previsao"], utc=True, format="ISO8601")
    mascara = (instantes >= inicio) & (instantes < fim)
    return _aplicar_feriados(quadro.loc[mascara].copy(), feriados)


def avaliar_grupo(referencia: dict, atual: pd.DataFrame, regras: dict) -> dict:
    """Os quatro tipos, numa fatia. Amostra curta não calcula PSI."""
    minimo = int(regras["minimo_amostra"])
    return {
        "n": int(len(atual)),
        "qualidade_dados": _qualidade(referencia, atual, minimo),
        "data_drift": _data_features(referencia, atual, minimo, float(regras["psi_estavel"]), float(regras["psi_alerta"])),
        "predicao": _predicao(referencia, atual, minimo, float(regras["js_alerta"])),
        "desempenho": _desempenho(atual, minimo, float(regras["macro_f1_min"]), float(regras["recall_falha_min"])),
    }


def _ajustar_sazonalidade(grupo: dict, corrente: pd.DataFrame, equivalente: pd.DataFrame, regras: dict) -> dict:
    """Se a semana anterior explica o deslocamento, não é drift."""
    minimo = int(regras["minimo_amostra"])
    features = (grupo.get("data_drift") or {}).get("features") or {}
    if len(corrente) < minimo or len(equivalente) < minimo or not features:
        return grupo
    statuses = []
    for nome, info in features.items():
        if nome not in equivalente.columns or nome not in corrente.columns:
            statuses.append(info["status"])
            continue
        valor = psi(equivalente[nome], corrente[nome])
        situacao = status_psi(valor, float(regras["psi_estavel"]), float(regras["psi_alerta"]))
        info["psi_sazonal"] = None if not math.isfinite(valor) else valor
        info["status_sazonal"] = situacao
        if situacao == "estavel" and info["status"] in ("atencao", "alerta"):
            info["status"] = "estavel"
            info["motivo"] = "diferenca explicada pelo periodo equivalente"
        statuses.append(info["status"])
    grupo["data_drift"]["status"] = _pior(statuses)
    return grupo


def _fatias(referencia: dict, atual: pd.DataFrame, regras: dict, continentes: dict) -> list[dict]:
    minimo = int(regras["minimo_amostra"])
    saida = []
    if "anchor_id" in atual.columns:
        for anchor, grupo in atual.groupby("anchor_id"):
            resumo = avaliar_grupo(referencia, grupo, regras)
            saida.append({"tipo": "anchor", "chave": int(anchor), "n": int(len(grupo)), "status": resumo["data_drift"]["status"] if len(grupo) >= minimo else "amostra_insuficiente"})
        mapa = atual.copy()
        mapa["continente"] = mapa["anchor_id"].map(lambda valor: continentes.get(int(valor), "desconhecido"))
        for nome, grupo in mapa.groupby("continente"):
            saida.append({"tipo": "continente", "chave": nome, "n": int(len(grupo)), "status": avaliar_grupo(referencia, grupo, regras)["data_drift"]["status"] if len(grupo) >= minimo else "amostra_insuficiente"})
    if "razao_rtt_p95" in atual.columns:
        faixas = atual.copy()
        faixas["faixa"] = faixas["razao_rtt_p95"].map(faixa_rtt)
        for nome, grupo in faixas.groupby("faixa"):
            saida.append({"tipo": "faixa_rtt", "chave": nome, "n": int(len(grupo)), "status": avaliar_grupo(referencia, grupo, regras)["data_drift"]["status"] if len(grupo) >= minimo else "amostra_insuficiente"})
    return saida


def montar(referencia: dict, atual: pd.DataFrame, regras: dict, fim: datetime, continentes: dict | None = None, feriados: list[str] | None = None) -> dict:
    """Janelas de 24 h e 7 dias, cada uma contra o período equivalente da semana anterior."""
    mapa = continentes or {}
    feriado = set(feriados or regras.get("feriados") or [])
    janelas = []
    for horas, nome in ((24, "24h"), (24 * 7, "7d")):
        corrente = janela(atual, fim, horas, feriado)
        equivalente = janela(atual, fim - timedelta(days=7), horas, feriado)
        grupo = avaliar_grupo(referencia, corrente, regras)
        if len(equivalente) >= int(regras["minimo_amostra"]) and len(corrente) >= int(regras["minimo_amostra"]):
            grupo["comparacao_sazonal"] = {
                "n_equivalente": int(len(equivalente)),
                "nota": "Mesma duração, sete dias antes, sem as datas de feriado.",
            }
        else:
            grupo["comparacao_sazonal"] = {"n_equivalente": int(len(equivalente)), "status": "amostra_insuficiente"}
        grupo = _ajustar_sazonalidade(grupo, corrente, equivalente, regras)
        grupo["nome"] = nome
        grupo["fatias"] = _fatias(referencia, corrente, regras, mapa)
        janelas.append(grupo)
    return {
        "gerado_em": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "limiares_psi": {"estavel": regras["psi_estavel"], "alerta": regras["psi_alerta"]},
        "importancia_permutacao": referencia.get("importancia_permutacao"),
        "janelas": janelas,
        "mudanca_de_rota_provavel": _rotas(atual, int(regras["minimo_amostra"])),
    }


def gravar(relatorio: dict, pasta: Path, dia: str | None = None) -> Path:
    pasta.mkdir(parents=True, exist_ok=True)
    nome = dia or relatorio["gerado_em"][:10]
    destino = pasta / f"drift_{nome}.json"
    destino.write_text(json.dumps(relatorio, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return destino


def continentes_anchors(caminho: Path | None = None) -> dict[int, str]:
    arquivo = caminho or (RAIZ.parent / "pipeline" / "01_anchors" / "data" / "anchors_selecionadas.json")
    documento = json.loads(arquivo.read_text(encoding="utf-8"))
    return {int(item["id"]): item["continent"] for item in documento["anchors"]}


def carregar_regras(caminho: Path | None = None) -> dict:
    import yaml

    arquivo = caminho or (RAIZ / "config" / "drift.yaml")
    return yaml.safe_load(arquivo.read_text(encoding="utf-8"))


def _ler_predicoes(pasta: Path) -> pd.DataFrame:
    linhas = []
    for arquivo in sorted(pasta.glob("*.jsonl")):
        for texto in arquivo.read_text(encoding="utf-8").splitlines():
            if not texto.strip():
                continue
            item = json.loads(texto)
            registro = dict(item.get("features") or {})
            registro["classe_prevista"] = item.get("classe_prevista")
            registro["rotulo_real"] = item.get("rotulo_real")
            registro["anchor_id"] = item.get("anchor_id")
            registro["fluxo_id"] = item.get("fluxo_id")
            registro["ts_previsao"] = item.get("ts_previsao")
            linhas.append(registro)
    return pd.DataFrame(linhas)


def main() -> int:
    referencia = json.loads((RAIZ / "modelo" / "ref_stats.json").read_text(encoding="utf-8"))
    atual = _ler_predicoes(RAIZ / "logs" / "predicoes")
    regras = carregar_regras()
    relatorio = montar(referencia, atual, regras, datetime.now(timezone.utc), continentes_anchors(), regras.get("feriados"))
    destino = gravar(relatorio, RAIZ / "relatorios")
    print(destino)
    for janela_item in relatorio["janelas"]:
        print(janela_item["nome"], janela_item["data_drift"]["status"], "n=", janela_item["n"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
