"""Etapa 7: rotula o Período B, monta janelas e desloca o alvo.

A regra é operacional deste projeto. Cada fluxo é comparado só com o
baseline dele, calculado no Período A. Nada aqui consulta a rede.
"""

import csv
import html
import json
import math
import random
import shutil
import sys
from datetime import datetime, timezone

import numpy as np
import pandas as pd

import config


def configurar_saida():
    """Garante acentos no terminal do Windows."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")


def garantir_pastas():
    """Cria cache, prompt, data e template se ainda não existirem."""
    for pasta in (config.CACHE_DIR, config.PROMPT_DIR, config.DATA_DIR, config.TEMPLATE_DIR):
        pasta.mkdir(parents=True, exist_ok=True)


def copiar_prompt():
    """Copia o enunciado para a pasta desta etapa."""
    if not config.ARQUIVO_PROMPT_ORIGEM.is_file():
        raise SystemExit(f"Prompt de origem ausente: {config.ARQUIVO_PROMPT_ORIGEM}")
    shutil.copyfile(config.ARQUIVO_PROMPT_ORIGEM, config.ARQUIVO_PROMPT)


def id_fluxo(probe_id, anchor_id):
    """Monta id_fluxo no formato da configuração."""
    return config.FORMATO_ID_FLUXO.format(probe_id=probe_id, anchor_id=anchor_id)


def para_numero(serie):
    """Converte texto em número. Vazio continua ausente e não vira zero."""
    texto = serie.replace("", pd.NA)
    return pd.to_numeric(texto, errors="coerce")


def para_unix(texto):
    """Converte um instante ISO com fuso em Unix UTC."""
    momento = datetime.fromisoformat(str(texto))
    if momento.tzinfo is None:
        raise SystemExit(f"Data sem fuso em metadados.json: {texto}")
    return int(momento.timestamp())


def iso_utc(timestamp):
    """Formata um Unix em UTC legível."""
    momento = datetime.fromtimestamp(int(timestamp), timezone.utc)
    return momento.strftime("%Y-%m-%d %H:%M:%S UTC")


def fim_de_numero(valor):
    """True quando o valor é um número finito. Inteiro do numpy também conta."""
    if isinstance(valor, (bool, np.bool_)):
        return False
    if isinstance(valor, (int, float, np.integer, np.floating)):
        return math.isfinite(float(valor))
    return False


def exigir_colunas(quadro, colunas, origem):
    """Aborta se alguma coluna obrigatória não veio no arquivo."""
    faltando = [coluna for coluna in colunas if coluna not in quadro.columns]
    if faltando:
        raise SystemExit(f"Colunas obrigatórias ausentes em {origem}: {', '.join(faltando)}")


def ler_metadados():
    """Lê as janelas e a ordem dos fluxos. As datas não ficam no código."""
    if not config.ARQUIVO_METADADOS_ETAPA5.is_file():
        raise SystemExit(f"Metadados ausentes: {config.ARQUIVO_METADADOS_ETAPA5}")
    documento = json.loads(config.ARQUIVO_METADADOS_ETAPA5.read_text(encoding="utf-8"))
    periodos = {item.get("nome"): item for item in documento.get("periodos", [])}
    if config.PERIODO_A not in periodos or config.PERIODO_B not in periodos:
        raise SystemExit("metadados.json não traz os períodos A e B.")
    janelas = {}
    for nome in (config.PERIODO_A, config.PERIODO_B):
        item = periodos[nome]
        if not item.get("inicio") or not item.get("fim"):
            raise SystemExit(f"Período {nome} sem início ou fim.")
        janelas[nome] = {
            "inicio": item["inicio"],
            "fim": item["fim"],
            "inicio_unix": para_unix(item["inicio"]),
            "fim_unix": para_unix(item["fim"]),
        }
    if janelas["A"]["fim_unix"] > janelas["B"]["inicio_unix"]:
        raise SystemExit("A janela A invade a janela B.")
    documento["janelas"] = janelas
    return documento


def ler_dataset():
    """Lê o dataset do Período B preservando o texto original das features."""
    if not config.ARQUIVO_DATASET_ETAPA5.is_file():
        raise SystemExit(f"Dataset ausente: {config.ARQUIVO_DATASET_ETAPA5}")
    quadro = pd.read_csv(config.ARQUIVO_DATASET_ETAPA5, dtype=str, keep_default_na=False)
    exigir_colunas(quadro, config.COLUNAS_DATASET_ETAPA5, config.FONTE_DATASET)
    return quadro


def ler_baseline():
    """Lê os limites de referência. A chave é anchor_id + probe_id."""
    if not config.ARQUIVO_BASELINE_ETAPA6.is_file():
        raise SystemExit(f"Baseline ausente: {config.ARQUIVO_BASELINE_ETAPA6}")
    quadro = pd.read_csv(config.ARQUIVO_BASELINE_ETAPA6, dtype=str, keep_default_na=False)
    exigir_colunas(quadro, config.COLUNAS_BASELINE_USADAS, config.FONTE_BASELINE)
    duplicados = quadro.duplicated(["anchor_id", "probe_id"])
    if duplicados.any():
        raise SystemExit("O baseline tem mais de uma linha para o mesmo anchor_id e probe_id.")
    return quadro


def aplicar_regra(quadro):
    """Aplica a precedência FALHA > RISCO > OK. A primeira condição encerra.

    Latência ou jitter vazios não entram na comparação e não viram zero.
    perda_pct vazio deixa a classe vazia. Perda severa não consulta a latência.
    """
    quantidade = len(quadro)
    classe = np.full(quantidade, "", dtype=object)
    motivo = np.full(quantidade, "", dtype=object)
    tem = quadro["tem_baseline"].to_numpy(dtype=bool)
    status = quadro["status_baseline"].to_numpy(dtype=object)
    perda = quadro["perda_num"].to_numpy(dtype=float)
    latencia = quadro["latencia_num"].to_numpy(dtype=float)
    jitter = quadro["jitter_num"].to_numpy(dtype=float)
    p95 = quadro["p95_rtt_num"].to_numpy(dtype=float)
    p99 = quadro["p99_rtt_num"].to_numpy(dtype=float)
    p95_jitter = quadro["p95_jitter_num"].to_numpy(dtype=float)

    motivo[~tem] = config.MOTIVO_SEM_BASELINE
    insuficiente = tem & (status != config.STATUS_BASELINE_OK)
    motivo[insuficiente] = config.MOTIVO_BASELINE_INSUFICIENTE

    livre = motivo == ""
    motivo[livre & ~np.isfinite(perda)] = config.MOTIVO_PERDA_VAZIA

    livre = motivo == ""
    falha_perda = livre & np.isfinite(perda) & (perda >= config.LIM_PERDA_FALHA - config.EPS)
    classe[falha_perda] = config.CLASSE_FALHA
    motivo[falha_perda] = config.MOTIVO_PERDA_SEVERA

    livre = motivo == ""
    falha_latencia = livre & np.isfinite(latencia) & np.isfinite(p99) & (latencia > p99)
    classe[falha_latencia] = config.CLASSE_FALHA
    motivo[falha_latencia] = config.MOTIVO_LATENCIA_P99

    livre = motivo == ""
    risco_perda = livre & np.isfinite(perda) & (perda >= config.LIM_PERDA_RISCO - config.EPS)
    classe[risco_perda] = config.CLASSE_RISCO
    motivo[risco_perda] = config.MOTIVO_PERDA_PARCIAL

    livre = motivo == ""
    risco_latencia = livre & np.isfinite(latencia) & np.isfinite(p95) & (latencia > p95)
    classe[risco_latencia] = config.CLASSE_RISCO
    motivo[risco_latencia] = config.MOTIVO_LATENCIA_P95

    livre = motivo == ""
    risco_jitter = livre & np.isfinite(jitter) & np.isfinite(p95_jitter) & (jitter > p95_jitter)
    classe[risco_jitter] = config.CLASSE_RISCO
    motivo[risco_jitter] = config.MOTIVO_JITTER_P95

    livre = motivo == ""
    classe[livre] = config.CLASSE_OK
    motivo[livre] = config.MOTIVO_SEM_ALERTA
    return classe, motivo


def conferir_regra_sintetica():
    """Trava a precedência com casos pequenos, antes de tocar nos dados reais."""
    casos = [
        ("sem baseline", False, "", 0, 1, 0, "", config.MOTIVO_SEM_BASELINE),
        ("insuficiente", True, "INSUFICIENTE", 0, 1, 0, "", config.MOTIVO_BASELINE_INSUFICIENTE),
        ("perda vazia", True, "VALIDO", np.nan, 1, 0, "", config.MOTIVO_PERDA_VAZIA),
        ("cem por cento", True, "VALIDO", 100, 999, 0, config.CLASSE_FALHA, config.MOTIVO_PERDA_SEVERA),
        ("dois de tres", True, "VALIDO", config.LIM_PERDA_FALHA, 1, 0, config.CLASSE_FALHA, config.MOTIVO_PERDA_SEVERA),
        ("limite incluso", True, "VALIDO", config.LIM_PERDA_FALHA - config.EPS, 1, 0, config.CLASSE_FALHA, config.MOTIVO_PERDA_SEVERA),
        ("acima do p99", True, "VALIDO", 0, 30, 0, config.CLASSE_FALHA, config.MOTIVO_LATENCIA_P99),
        ("perda e p99", True, "VALIDO", config.LIM_PERDA_RISCO, 30, 0, config.CLASSE_FALHA, config.MOTIVO_LATENCIA_P99),
        ("um de tres", True, "VALIDO", config.LIM_PERDA_RISCO, 1, 0, config.CLASSE_RISCO, config.MOTIVO_PERDA_PARCIAL),
        ("acima do p95", True, "VALIDO", 0, 12, 0, config.CLASSE_RISCO, config.MOTIVO_LATENCIA_P95),
        ("jitter", True, "VALIDO", 0, 1, 2, config.CLASSE_RISCO, config.MOTIVO_JITTER_P95),
        ("jitter com p95 zero", True, "VALIDO", 0, 1, 0.1, config.CLASSE_RISCO, config.MOTIVO_JITTER_P95),
        ("ok", True, "VALIDO", 0, 1, 0, config.CLASSE_OK, config.MOTIVO_SEM_ALERTA),
        ("latencia vazia", True, "VALIDO", 0, np.nan, np.nan, config.CLASSE_OK, config.MOTIVO_SEM_ALERTA),
    ]
    # P95 de RTT = 10, P99 = 20, P95 de jitter = 1, exceto o caso de jitter zero.
    p95_jitter = [0.0 if nome == "jitter com p95 zero" else 1.0 for nome, *_ in casos]
    quadro = pd.DataFrame(
        {
            "tem_baseline": [item[1] for item in casos],
            "status_baseline": [item[2] for item in casos],
            "perda_num": [item[3] for item in casos],
            "latencia_num": [item[4] for item in casos],
            "jitter_num": [item[5] for item in casos],
            "p95_rtt_num": [10.0] * len(casos),
            "p99_rtt_num": [20.0] * len(casos),
            "p95_jitter_num": p95_jitter,
        }
    )
    classes, motivos = aplicar_regra(quadro)
    for indice, item in enumerate(casos):
        nome, *_resto, classe_esperada, motivo_esperado = item
        if classes[indice] != classe_esperada or motivos[indice] != motivo_esperado:
            raise SystemExit(
                f"A regra falhou no caso sintético '{nome}': "
                f"veio {classes[indice]}/{motivos[indice]}, "
                f"esperado {classe_esperada}/{motivo_esperado}."
            )


def _razao(numerador, denominador):
    """Divisão que fica ausente se faltar operando ou se o denominador for zero."""
    with np.errstate(divide="ignore", invalid="ignore"):
        valor = numerador / denominador
    invalido = numerador.isna() | denominador.isna() | denominador.eq(0) | ~np.isfinite(valor)
    return valor.mask(invalido, np.nan)


def _streak(serie):
    """Conta medições seguidas com perda > 0, terminando na linha atual."""
    positivo = serie.gt(0).fillna(False)
    bloco = (~positivo).cumsum()
    return positivo.groupby(bloco).cumsum().astype(int)


def _coluna_rolling(quadro, origem, tamanho, operacao):
    """Agrega uma coluna olhando só para trás, dentro de cada fluxo."""
    agrupado = quadro.groupby("id_fluxo", sort=False)[origem].rolling(tamanho, min_periods=1)
    if operacao == "mean":
        valores = agrupado.mean()
    elif operacao == "max":
        valores = agrupado.max()
    elif operacao == "sum":
        valores = agrupado.sum()
    else:
        raise SystemExit(f"Operação de janela desconhecida: {operacao}")
    return valores.reset_index(level=0, drop=True)


def calcular_features(quadro):
    """Calcula as features de cada linha usando só o passado do fluxo, inclusive t.

    Razões e janelas sem RTT ficam ausentes aqui. A sentinela entra depois,
    só nas linhas que vão para o dataset final.
    """
    quadro = quadro.sort_values(["id_fluxo", "timestamp"], kind="mergesort").reset_index(drop=True)
    grupo = quadro.groupby("id_fluxo", sort=False)
    rtt_ausente = quadro["rtt_avg_num"].isna() | ~np.isfinite(quadro["rtt_avg_num"])
    quadro["rtt_ausente"] = rtt_ausente.astype(int)
    quadro["perda_pct_feature"] = quadro["perda_num"]
    quadro["razao_rtt_p95"] = _razao(quadro["rtt_avg_num"], quadro["p95_rtt_num"])
    quadro["razao_rtt_p99"] = _razao(quadro["rtt_avg_num"], quadro["p99_rtt_num"])
    quadro["razao_jitter_p95"] = _razao(quadro["jitter_num"], quadro["p95_jitter_num"])
    with np.errstate(divide="ignore", invalid="ignore"):
        amplitude = (quadro["rtt_max_num"] - quadro["rtt_min_num"]) / quadro["rtt_avg_num"]
    amplitude_invalida = (
        rtt_ausente
        | quadro["rtt_min_num"].isna()
        | quadro["rtt_max_num"].isna()
        | quadro["rtt_avg_num"].eq(0)
        | ~np.isfinite(amplitude)
    )
    quadro["amplitude_rtt_rel"] = amplitude.mask(amplitude_invalida, np.nan)
    recorte = quadro["delta_num"].clip(-config.TTL_CLIP, config.TTL_CLIP)
    quadro["delta_ttl_clip"] = recorte.where(quadro["delta_num"].notna(), np.nan)
    quadro["ttl_reset"] = quadro["delta_num"].abs().ge(config.TTL_RESET).fillna(False).astype(int)
    quadro["perdas_consecutivas"] = grupo["perda_num"].transform(_streak)

    for tamanho in config.JANELAS:
        media, rtt, jitter, acima = config.nomes_janela(tamanho)
        quadro[media] = _coluna_rolling(quadro, "perda_num", tamanho, "mean")
        quadro[rtt] = _coluna_rolling(quadro, "razao_rtt_p95", tamanho, "max")
        quadro[jitter] = _coluna_rolling(quadro, "razao_jitter_p95", tamanho, "max")
        indicador = (quadro["razao_rtt_p95"] > 1).astype(float).where(quadro["razao_rtt_p95"].notna())
        quadro["_acima"] = indicador
        quadro["_tem_razao"] = quadro["razao_rtt_p95"].notna().astype(float)
        soma = _coluna_rolling(quadro, "_acima", tamanho, "sum")
        presentes = _coluna_rolling(quadro, "_tem_razao", tamanho, "sum")
        quadro[acima] = soma.where(presentes > 0, np.nan)
    quadro = quadro.drop(columns=["_acima", "_tem_razao"])
    return quadro


def aplicar_sentinela(quadro):
    """Troca NaN e inf das features por -1. Não imputa média nem mediana."""
    dependem_de_rtt = [
        nome
        for nome in config.lista_features()
        if nome not in ("perda_pct", "rtt_ausente", "ttl_reset", "perdas_consecutivas")
    ]
    for nome in dependem_de_rtt:
        valores = pd.to_numeric(quadro[nome], errors="coerce")
        quadro[nome] = valores.where(np.isfinite(valores), config.SENTINELA)
    quadro["perda_pct_feature"] = pd.to_numeric(quadro["perda_pct_feature"], errors="coerce")
    return quadro


def conferir_janela_sintetica():
    """Confere janela, sentinela e descarte de intervalo num fluxo inventado."""
    quadro = pd.DataFrame(
        {
            "id_fluxo": ["a", "a", "a", "a"],
            "timestamp": [0, 240, 480, 720],
            "perda_num": [0.0, 0.0, 100.0, 0.0],
            "rtt_min_num": [10.0, 20.0, np.nan, 10.0],
            "rtt_max_num": [10.0, 30.0, np.nan, 12.0],
            "rtt_avg_num": [10.0, 20.0, np.nan, 11.0],
            "jitter_num": [0.0, 1.0, np.nan, 0.0],
            "delta_num": [0.0, 1.0, np.nan, 80.0],
            "p95_rtt_num": [10.0, 10.0, 10.0, 10.0],
            "p99_rtt_num": [15.0, 15.0, 15.0, 15.0],
            "p95_jitter_num": [0.5, 0.5, 0.5, 0.5],
            "classe": ["OK", "OK", "FALHA", "OK"],
        }
    )
    calculado = aplicar_sentinela(calcular_features(quadro))
    if list(calculado["rtt_ausente"]) != [0, 0, 1, 0]:
        raise SystemExit("rtt_ausente sintético não bateu.")
    if list(calculado["perdas_consecutivas"]) != [0, 0, 1, 0]:
        raise SystemExit("perdas_consecutivas sintético não bateu.")
    if calculado.loc[2, "razao_rtt_p95"] != config.SENTINELA:
        raise SystemExit("A sentinela não entrou na razão sem RTT.")
    if abs(float(calculado.loc[1, "razao_rtt_p95"]) - 2) > config.TOLERANCIA_VERIFICACAO:
        raise SystemExit("razao_rtt_p95 sintética não bateu.")
    media = config.nomes_janela(config.JANELAS[0])[0]
    if abs(float(calculado.loc[2, media]) - (100 / 3)) > 1e-9:
        raise SystemExit("A média da janela sintética não bateu.")
    motivos = motivos_de_descarte(calculado)
    if list(motivos) != ["", "", "", config.MOTIVO_SEM_FUTURO]:
        raise SystemExit(f"Descarte sintético inesperado: {list(motivos)}")
    longo = calculado.copy()
    longo["timestamp"] = [0, 240, 480, 480 + config.GAP_MAX_S + 1]
    motivos_gap = motivos_de_descarte(longo)
    if motivos_gap.iloc[2] != config.MOTIVO_GAP:
        raise SystemExit("O intervalo acima do limite não foi descartado.")


def motivos_de_descarte(quadro):
    """Marca por que uma linha não entra no dataset final. Vazio significa que entra.

    A ordem é: a própria linha sem classe, sem medição t+H, alvo sem rótulo,
    intervalo maior que o limite. Cada linha fica com um único motivo.
    """
    grupo = quadro.groupby("id_fluxo", sort=False)
    futuro_ts = grupo["timestamp"].shift(-config.HORIZONTE)
    futuro_classe = grupo["classe"].shift(-config.HORIZONTE)
    quadro["alvo"] = futuro_classe
    quadro["gap_s"] = futuro_ts - quadro["timestamp"]
    motivo = pd.Series("", index=quadro.index, dtype=object)
    motivo = motivo.mask(quadro["classe"].eq(""), config.MOTIVO_PERDA_VAZIA)
    motivo = motivo.mask(motivo.eq("") & futuro_ts.isna(), config.MOTIVO_SEM_FUTURO)
    motivo = motivo.mask(motivo.eq("") & futuro_classe.eq(""), config.MOTIVO_ALVO_SEM_ROTULO)
    motivo = motivo.mask(motivo.eq("") & quadro["gap_s"].gt(config.GAP_MAX_S), config.MOTIVO_GAP)
    return motivo


def juntar_e_rotular(dataset, baseline):
    """Junta pela chave anchor_id + probe_id e grava classe e motivo."""
    limites = baseline[list(config.COLUNAS_BASELINE_USADAS)].copy()
    quadro = dataset.merge(limites, on=["anchor_id", "probe_id"], how="left", validate="many_to_one")
    quadro["status_baseline"] = quadro["status_baseline"].fillna("")
    for coluna in ("p95_rtt_A", "p99_rtt_A", "p95_jitter_A"):
        quadro[coluna] = quadro[coluna].fillna("")
    quadro["tem_baseline"] = quadro["status_baseline"].ne("")
    quadro["id_fluxo"] = [
        id_fluxo(probe, anchor) for probe, anchor in zip(quadro["probe_id"], quadro["anchor_id"])
    ]
    quadro["perda_num"] = para_numero(quadro["perda_pct"])
    quadro["latencia_num"] = para_numero(quadro["latencia_ms"])
    quadro["jitter_num"] = para_numero(quadro["jitter_ms"])
    quadro["rtt_min_num"] = para_numero(quadro["rtt_min"])
    quadro["rtt_max_num"] = para_numero(quadro["rtt_max"])
    quadro["rtt_avg_num"] = para_numero(quadro["rtt_avg"])
    quadro["delta_num"] = para_numero(quadro["delta_ttl"])
    quadro["timestamp_num"] = para_numero(quadro["timestamp"]).astype("int64")
    quadro["p95_rtt_num"] = para_numero(quadro["p95_rtt_A"])
    quadro["p99_rtt_num"] = para_numero(quadro["p99_rtt_A"])
    quadro["p95_jitter_num"] = para_numero(quadro["p95_jitter_A"])
    classes, motivos = aplicar_regra(quadro)
    quadro["classe"] = classes
    quadro["motivo_rotulagem"] = motivos
    return quadro


def fluxos_desatualizados(quadro):
    """Fluxos em que a latência acima do P99 já é rotina, não exceção."""
    validos = quadro["status_baseline"].eq(config.STATUS_BASELINE_OK)
    if not validos.any():
        return set()
    fracao = (
        quadro.loc[validos]
        .groupby("id_fluxo")["motivo_rotulagem"]
        .apply(lambda serie: float((serie == config.MOTIVO_LATENCIA_P99).mean()))
    )
    return set(fracao[fracao >= config.MAX_FRAC_FALHA_LATENCIA].index)


def preparar_serie(quadro, desatualizados):
    """Tira da série os fluxos que não podem alimentar o dataset final."""
    sem_valido = set(quadro.loc[~quadro["status_baseline"].eq(config.STATUS_BASELINE_OK), "id_fluxo"])
    bloqueados = sem_valido | set(desatualizados)
    serie = quadro.loc[~quadro["id_fluxo"].isin(bloqueados)].copy()
    serie["timestamp"] = serie["timestamp_num"]
    return serie, sem_valido


def atribuir_split(quadro, t0):
    """Separa treino, validação e teste no tempo e marca o embargo."""
    corte_treino = t0 + config.CORTE_TREINO_DIAS * config.SEGUNDOS_DIA
    corte_val = t0 + config.CORTE_VAL_DIAS * config.SEGUNDOS_DIA
    embargo = config.EMBARGO_MIN * config.SEGUNDOS_MINUTO
    if corte_val <= corte_treino + embargo:
        raise SystemExit("O corte de validação não deixa um embargo inteiro depois do treino.")
    instante = quadro["timestamp"]
    split = np.full(len(quadro), "", dtype=object)
    split[instante < corte_treino] = config.SPLIT_TREINO
    validacao = (instante >= corte_treino + embargo) & (instante < corte_val)
    split[validacao.to_numpy()] = config.SPLIT_VALIDACAO
    split[instante >= corte_val + embargo] = config.SPLIT_TESTE
    embargo_treino = (instante >= corte_treino) & (instante < corte_treino + embargo)
    embargo_val = (instante >= corte_val) & (instante < corte_val + embargo)
    em_embargo = embargo_treino | embargo_val
    if ((split == "") & ~em_embargo.to_numpy()).any():
        raise SystemExit("Há linhas fora do treino, da validação, do teste e do embargo.")
    quadro = quadro.copy()
    quadro["split"] = split
    quadro["motivo_embargo"] = np.where(em_embargo, config.MOTIVO_EMBARGO, "")
    return quadro, corte_treino, corte_val, embargo


def montar_exclusoes(quadro, sem_valido, desatualizados, serie, motivo_descarte, candidatos):
    """Conta linhas excluídas por fluxo e motivo."""
    registros = []

    def acrescentar(ids, motivo, origem):
        for fluxo in sorted(ids):
            quantidade = int((origem["id_fluxo"] == fluxo).sum())
            if quantidade:
                registros.append({"id_fluxo": fluxo, "motivo": motivo, "n_linhas": quantidade})

    for motivo in (config.MOTIVO_SEM_BASELINE, config.MOTIVO_BASELINE_INSUFICIENTE):
        ids = set(quadro.loc[quadro["motivo_rotulagem"].eq(motivo), "id_fluxo"])
        acrescentar(ids, motivo, quadro)
    acrescentar(desatualizados, config.MOTIVO_DESATUALIZADO, quadro)
    for motivo in (
        config.MOTIVO_PERDA_VAZIA,
        config.MOTIVO_SEM_FUTURO,
        config.MOTIVO_ALVO_SEM_ROTULO,
        config.MOTIVO_GAP,
    ):
        ids = set(serie.loc[motivo_descarte.eq(motivo), "id_fluxo"])
        acrescentar(ids, motivo, serie.loc[motivo_descarte.eq(motivo)])
    if len(candidatos):
        ids = set(candidatos.loc[candidatos["motivo_embargo"].eq(config.MOTIVO_EMBARGO), "id_fluxo"])
        acrescentar(ids, config.MOTIVO_EMBARGO, candidatos.loc[candidatos["motivo_embargo"].eq(config.MOTIVO_EMBARGO)])
    registros.sort(key=lambda item: (item["motivo"], item["id_fluxo"]))
    return registros


def macro_f1(verdadeiro, previsto):
    """Média não ponderada do F1 das três classes. Classe ausente entra com zero."""
    notas = []
    for classe in config.CLASSES:
        verdadeiro_classe = verdadeiro == classe
        previsto_classe = previsto == classe
        tp = int((verdadeiro_classe & previsto_classe).sum())
        fp = int((~verdadeiro_classe & previsto_classe).sum())
        fn = int((verdadeiro_classe & ~previsto_classe).sum())
        precisao = tp / (tp + fp) if tp + fp else 0.0
        revocacao = tp / (tp + fn) if tp + fn else 0.0
        notas.append(0.0 if precisao + revocacao == 0 else 2 * precisao * revocacao / (precisao + revocacao))
    return sum(notas) / len(notas)


def coluna_feature(nome):
    """A coluna numérica da feature. perda_pct original continua sendo texto."""
    if nome == "perda_pct":
        return "perda_pct_feature"
    return nome


def quase_igual(esquerda, direita):
    """Compara dois números dentro da tolerância da verificação."""
    if not fim_de_numero(esquerda) or not fim_de_numero(direita):
        return False
    return abs(float(esquerda) - float(direita)) <= config.TOLERANCIA_VERIFICACAO


def verificar(quadro, final, serie, sem_valido, desatualizados, cortes):
    """Roda as verificações. FALHOU interrompe a etapa no fim, depois de gravar."""
    resultado = {}

    def selar(nome, ok, detalhe, atencao=False):
        if ok and not atencao:
            estado = "PASSOU"
        elif atencao and ok:
            estado = "ATENCAO"
        else:
            estado = "FALHOU"
        resultado[nome] = {"estado": estado, "detalhe": detalhe}

    perda = quadro["perda_num"]
    latencia = quadro["latencia_num"]
    status_ok = quadro["status_baseline"].eq(config.STATUS_BASELINE_OK)
    severa = status_ok & perda.notna() & (perda >= config.LIM_PERDA_FALHA - config.EPS)
    selar(
        "perda_severa_e_falha",
        bool((quadro.loc[severa, "classe"] == config.CLASSE_FALHA).all()),
        f"{int(severa.sum())} linhas com perda de pelo menos 2/3 e baseline válido.",
    )

    acima_p99 = status_ok & latencia.notna() & quadro["p99_rtt_num"].notna() & (latencia > quadro["p99_rtt_num"]) & perda.notna()
    acima_p95 = status_ok & latencia.notna() & quadro["p95_rtt_num"].notna() & (latencia > quadro["p95_rtt_num"]) & quadro["classe"].ne("")
    p99_ok = quadro.loc[acima_p99, "classe"].eq(config.CLASSE_FALHA).all()
    p95_ok = ~quadro.loc[acima_p95, "classe"].eq(config.CLASSE_OK).any()
    selar(
        "latencia_acima_dos_limites",
        bool(p99_ok and p95_ok),
        f"{int(acima_p99.sum())} linhas acima do P99 e {int(acima_p95.sum())} acima do P95.",
    )

    ok_sem_baseline = quadro["classe"].eq(config.CLASSE_OK) & ~status_ok
    falha = quadro["classe"].eq(config.CLASSE_FALHA)
    falha_por_ttl = falha & ~quadro["motivo_rotulagem"].isin(config.MOTIVOS_FALHA)
    selar(
        "sem_baseline_nao_e_ok",
        not bool(ok_sem_baseline.any()) and not bool(falha_por_ttl.any()),
        "OK exige baseline válido. FALHA só sai por perda severa ou latência acima do P99.",
    )

    vazamento = verificar_vazamento(serie, final)
    selar("sem_vazamento_do_futuro", vazamento["ok"], vazamento["detalhe"], atencao=vazamento["atencao"])

    features = config.lista_features()
    proibidas = sorted(set(features) & set(config.COLUNAS_PROIBIDAS))
    tem_nan = False
    if len(final):
        bloco = pd.DataFrame({nome: pd.to_numeric(final[coluna_feature(nome)], errors="coerce") for nome in features})
        tem_nan = not bool(np.isfinite(bloco.to_numpy(dtype=float)).all())
        alvo_ok = final["alvo"].isin(config.CLASSES).all()
    else:
        alvo_ok = False
    selar(
        "alvo_finito_e_features_sem_nan",
        bool(alvo_ok) and not tem_nan and len(final) > 0,
        f"{len(final)} linhas no dataset final.",
    )
    selar(
        "colunas_proibidas_fora_das_features",
        not proibidas,
        "Nenhuma coluna proibida entre as features." if not proibidas else ", ".join(proibidas),
    )

    ordem = verificar_ordem(final, cortes, sem_valido | desatualizados)
    selar("ordem_temporal_e_duplicatas", ordem["ok"], ordem["detalhe"])

    texto_igual = bool((quadro["latencia_ms"] == quadro["rtt_avg"]).all())
    latencia_vazia = quadro["latencia_ms"].eq("")
    jitter_vazio = quadro["jitter_ms"].eq("")
    perda_vazia = quadro["perda_pct"].eq("")
    vazio_preservado = (
        quadro.loc[latencia_vazia, "latencia_num"].isna().all()
        and quadro.loc[jitter_vazio, "jitter_num"].isna().all()
        and quadro.loc[perda_vazia, "classe"].eq("").all()
        and not (latencia_vazia & quadro["motivo_rotulagem"].isin((config.MOTIVO_LATENCIA_P95, config.MOTIVO_LATENCIA_P99))).any()
        and not (jitter_vazio & quadro["motivo_rotulagem"].eq(config.MOTIVO_JITTER_P95)).any()
    )
    selar(
        "latencia_igual_rtt_e_vazio_preservado",
        texto_igual and bool(vazio_preservado),
        "latencia_ms permanece igual a rtt_avg e vazio não entra na comparação.",
    )
    return resultado


def verificar_vazamento(serie, final):
    """Recalcula amostras só com o passado e confirma que o futuro não muda a feature."""
    if final.empty:
        return {"ok": False, "atencao": False, "detalhe": "Dataset final vazio."}
    quantidade = min(config.N_VERIFICA_VAZAMENTO, len(final))
    atencao = quantidade < config.N_VERIFICA_VAZAMENTO
    gerador = random.Random(config.SEED)
    posicoes = gerador.sample(list(final.index), quantidade)
    recursos = {fluxo: grupo.reset_index(drop=True) for fluxo, grupo in serie.groupby("id_fluxo", sort=False)}
    features = config.lista_features()
    falhas = 0
    for posicao in posicoes:
        linha = final.loc[posicao]
        fluxo = recursos[linha["id_fluxo"]]
        instante = int(linha["timestamp"])
        prefixo = fluxo.loc[fluxo["timestamp"] <= instante].copy()
        recalculado = aplicar_sentinela(calcular_features(prefixo)).iloc[-1]
        if any(not quase_igual(recalculado[coluna_feature(nome)], linha[coluna_feature(nome)]) for nome in features):
            falhas += 1
            continue
        if not (fluxo["timestamp"] > instante).any():
            falhas += 1
            continue
        mutado = fluxo.copy()
        futuro = mutado["timestamp"] > instante
        mutado.loc[futuro, "perda_num"] = 100.0
        mutado.loc[futuro, "rtt_avg_num"] = 99999.0
        mutado.loc[futuro, "rtt_min_num"] = 99999.0
        mutado.loc[futuro, "rtt_max_num"] = 99999.0
        mutado.loc[futuro, "jitter_num"] = 50.0
        mutado.loc[futuro, "delta_num"] = 100.0
        mutado.loc[futuro, "classe"] = config.CLASSE_FALHA
        de_novo = aplicar_sentinela(calcular_features(mutado))
        linha_mutada = de_novo.loc[de_novo["timestamp"] == instante].iloc[0]
        if any(not quase_igual(linha_mutada[coluna_feature(nome)], linha[coluna_feature(nome)]) for nome in features):
            falhas += 1
    detalhe = (
        f"{quantidade} linhas refeitas só com timestamp ≤ t e com o futuro alterado. "
        f"Divergências: {falhas}."
    )
    return {"ok": falhas == 0, "atencao": atencao and falhas == 0, "detalhe": detalhe}


def verificar_ordem(final, cortes, fluxos_excluidos):
    """Confere treino < validação < teste, o embargo e a ausência de duplicatas."""
    if final.empty:
        return {"ok": False, "detalhe": "Dataset final vazio."}
    duplicatas = int(final.duplicated(["id_fluxo", "timestamp"]).sum())
    vazou = sorted(set(final["id_fluxo"]) & set(fluxos_excluidos))
    mensagens = []
    ok = duplicatas == 0 and not vazou
    if duplicatas:
        mensagens.append(f"{duplicatas} duplicatas de id_fluxo e timestamp.")
    if vazou:
        mensagens.append(f"{len(vazou)} fluxos excluídos apareceram no final.")
    cortes_usados = {}
    for nome in config.SPLITS:
        parte = final.loc[final["split"].eq(nome), "timestamp"]
        if parte.empty:
            ok = False
            mensagens.append(f"Split {nome} vazio.")
            continue
        cortes_usados[nome] = (int(parte.min()), int(parte.max()))
    if len(cortes_usados) == 3:
        treino_fim = cortes_usados[config.SPLIT_TREINO][1]
        val_ini, val_fim = cortes_usados[config.SPLIT_VALIDACAO]
        teste_ini = cortes_usados[config.SPLIT_TESTE][0]
        corte_treino, corte_val, embargo = cortes
        if not (treino_fim < corte_treino <= val_ini and val_ini >= corte_treino + embargo and val_fim < corte_val <= teste_ini):
            ok = False
            mensagens.append("A ordem temporal ou o embargo não foi respeitado.")
    if not mensagens:
        mensagens.append("Treino, validação e teste estão em ordem, com embargo e sem duplicatas.")
    return {"ok": ok, "detalhe": " ".join(mensagens)}


def gravar_rotulado(quadro):
    """Grava as features originais, sem acrescentar colunas do baseline."""
    with config.ARQUIVO_ROTULADO.open("w", encoding="utf-8", newline="") as arquivo:
        escritor = csv.writer(arquivo, lineterminator="\n")
        escritor.writerow(config.COLUNAS_ROTULADO)
        colunas = list(config.COLUNAS_DATASET_ETAPA5)
        for valores, classe in zip(quadro[colunas].itertuples(index=False, name=None), quadro["classe"]):
            escritor.writerow([*valores, classe])


def gravar_auditoria(quadro):
    """Explica cada rótulo. Este arquivo não é o dataset de treino."""
    with config.ARQUIVO_AUDITORIA.open("w", encoding="utf-8", newline="") as arquivo:
        escritor = csv.writer(arquivo, lineterminator="\n")
        escritor.writerow(config.COLUNAS_AUDITORIA)
        colunas = list(config.COLUNAS_AUDITORIA)
        for linha in quadro[colunas].itertuples(index=False, name=None):
            escritor.writerow(linha)


def gravar_final(final):
    """Grava metadados, features e o alvo na última coluna."""
    features = config.lista_features()
    saida = pd.DataFrame()
    saida["id_fluxo"] = final["id_fluxo"]
    saida["anchor_id"] = final["anchor_id"]
    saida["probe_id"] = final["probe_id"]
    saida["timestamp"] = final["timestamp"].astype("int64")
    saida["split"] = final["split"]
    saida["classe_atual"] = final["classe"]
    saida["perda_pct"] = final["perda_pct_feature"]
    for nome in features:
        if nome == "perda_pct":
            continue
        saida[nome] = final[nome]
    saida[config.COLUNA_ALVO] = final["alvo"]
    ordem = list(config.COLUNAS_METADADOS_FINAL) + features + [config.COLUNA_ALVO]
    saida[ordem].to_csv(
        config.ARQUIVO_FINAL,
        index=False,
        encoding="utf-8",
        lineterminator="\n",
        float_format=config.FLOAT_FORMAT,
    )


def gravar_exclusoes(registros):
    """Uma linha por fluxo e motivo."""
    with config.ARQUIVO_EXCLUSOES.open("w", encoding="utf-8", newline="") as arquivo:
        escritor = csv.writer(arquivo, lineterminator="\n")
        escritor.writerow(config.COLUNAS_EXCLUSOES)
        for item in registros:
            escritor.writerow([item["id_fluxo"], item["motivo"], item["n_linhas"]])


def para_json(valor):
    """Converte tipos do numpy para JSON simples."""
    if isinstance(valor, dict):
        return {str(chave): para_json(item) for chave, item in valor.items()}
    if isinstance(valor, (list, tuple)):
        return [para_json(item) for item in valor]
    if isinstance(valor, (np.integer,)):
        return int(valor)
    if isinstance(valor, (np.floating,)):
        numero = float(valor)
        return numero if math.isfinite(numero) else None
    if isinstance(valor, float) and not math.isfinite(valor):
        return None
    return valor


def gravar_json(caminho, documento):
    """Grava JSON estável, sem data do relógio."""
    caminho.write_text(json.dumps(para_json(documento), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def contagens(serie, chaves):
    """Conta valores conhecidos, inclusive os que não apareceram."""
    visto = serie.value_counts()
    return {chave: int(visto.get(chave, 0)) for chave in chaves}


def montar_qualidade(quadro, final, registros, verificacoes, janelas, fora_da_janela, jitter_zero, perda_fora, sem_rotulo_severa):
    """Reúne contagens, transição, persistência e o resultado das verificações."""
    classe = quadro["classe"].replace("", config.SEM_ROTULO)
    por_classe = contagens(classe, list(config.CLASSES) + [config.SEM_ROTULO])
    por_motivo = contagens(quadro["motivo_rotulagem"], [regra["motivo"] for regra in config.REGRAS] + list(config.MOTIVOS_SEM_ROTULO))
    sem_rotulo = quadro["classe"].eq("")
    por_motivo_sem = contagens(quadro.loc[sem_rotulo, "motivo_rotulagem"], config.MOTIVOS_SEM_ROTULO)
    alvo_por_split = {}
    persistencia = {}
    for nome in config.SPLITS:
        parte = final.loc[final["split"].eq(nome)]
        alvo_por_split[nome] = contagens(parte["alvo"], config.CLASSES) if len(parte) else {c: 0 for c in config.CLASSES}
        persistencia[nome] = macro_f1(parte["alvo"], parte["classe"]) if len(parte) else None
    matriz = {}
    if len(final):
        cruzada = pd.crosstab(final["classe"], final["alvo"])
        for origem in config.CLASSES:
            matriz[origem] = {
                destino: int(cruzada.at[origem, destino]) if origem in cruzada.index and destino in cruzada.columns else 0
                for destino in config.CLASSES
            }
    else:
        matriz = {origem: {destino: 0 for destino in config.CLASSES} for origem in config.CLASSES}
    return {
        "janela_b": {**janelas[config.PERIODO_B], "fonte": config.FONTE_JANELA},
        "linhas_lidas": int(len(quadro)),
        "fluxos_lidos": int(quadro["id_fluxo"].nunique()),
        "linhas_rotuladas": int(quadro["classe"].ne("").sum()),
        "linhas_sem_rotulo": int(sem_rotulo.sum()),
        "linhas_dataset_final": int(len(final)),
        "fluxos_dataset_final": int(final["id_fluxo"].nunique()) if len(final) else 0,
        "contagem_por_classe": por_classe,
        "contagem_por_motivo": por_motivo,
        "sem_rotulo_por_motivo": por_motivo_sem,
        "alvo_por_split": alvo_por_split,
        "transicao_classe_atual_para_alvo": matriz,
        "baseline_persistencia_macro_f1": persistencia,
        "nota_macro_f1": "A macro-F1 usa as três classes. Classe ausente no split entra com F1 zero. A previsão de persistência repete classe_atual.",
        "avisos": {
            "p95_jitter_zero": jitter_zero,
            "perda_pct_fora_do_conjunto": perda_fora,
            "timestamps_fora_da_janela": fora_da_janela,
        },
        "linhas_sem_rotulo_com_perda_severa": sem_rotulo_severa,
        "exclusoes": registros,
        "verificacoes": verificacoes,
        "sentinela": {
            "valor": config.SENTINELA,
            "uso": "Features que dependem de RTT e não têm RTT utilizável, inclusive divisão por P95 de jitter igual a zero. delta_ttl ausente também usa -1; um delta real de -1 fica igual à sentinela depois do recorte.",
        },
    }


def escolher_fluxo(metadados, final):
    """Prefere um fluxo brasileiro com OK, RISCO e FALHA numa janela curta."""
    if config.HTML_FLUXO:
        if config.HTML_FLUXO not in set(final["id_fluxo"]):
            raise SystemExit(f"HTML_FLUXO não está no dataset final: {config.HTML_FLUXO}")
        return config.HTML_FLUXO
    pais = {}
    ordem = []
    for fluxo, item in metadados.get("fluxos", {}).items():
        ordem.append(fluxo)
        pais[fluxo] = (item.get("destino") or {}).get("pais")
    finais = set(final["id_fluxo"])
    brasil = [fluxo for fluxo in ordem if pais.get(fluxo) == config.PAIS_DESTAQUE and fluxo in finais]

    def janela_com_transicao(fluxo):
        sequencia = final.loc[final["id_fluxo"].eq(fluxo), "classe"].tolist()
        tamanho = config.HTML_TAM_SEQUENCIA
        for inicio in range(0, max(0, len(sequencia) - tamanho + 1)):
            if tem_transicao(sequencia[inicio : inicio + tamanho]):
                return True
        return False

    for fluxo in brasil:
        if janela_com_transicao(fluxo):
            return fluxo
    for fluxo in brasil:
        classes = set(final.loc[final["id_fluxo"].eq(fluxo), "classe"])
        if set(config.CLASSES) <= classes:
            return fluxo
    if brasil:
        return brasil[0]
    for fluxo in ordem:
        if fluxo in finais:
            return fluxo
    if len(final):
        return final["id_fluxo"].iloc[0]
    raise SystemExit(config.TEXTO_INSUFICIENTE)


def tem_transicao(sequencia):
    """True se OK aparece, depois RISCO, depois FALHA."""
    viu_ok = False
    viu_risco = False
    for classe in sequencia:
        if classe == config.CLASSE_OK:
            viu_ok = True
        elif classe == config.CLASSE_RISCO and viu_ok:
            viu_risco = True
        elif classe == config.CLASSE_FALHA and viu_risco:
            return True
    return False


def info_fluxo(metadados, fluxo, p95, p99, p95_jitter):
    """Nome e limites de um fluxo para a página."""
    item = metadados.get("fluxos", {}).get(fluxo, {})
    destino = item.get("destino") or {}
    return {
        "id_fluxo": fluxo,
        "hostname": destino.get("hostname") or "",
        "cidade": destino.get("cidade") or "",
        "pais": destino.get("pais") or "",
        "p95_rtt_A": p95,
        "p99_rtt_A": p99,
        "p95_jitter_A": p95_jitter,
    }


def linha_medicao(linha):
    """Uma execução real, com os números usados na comparação."""
    return {
        "id_fluxo": linha["id_fluxo"],
        "timestamp": int(linha["timestamp_num"]),
        "timestamp_utc": iso_utc(linha["timestamp_num"]),
        "perda_pct": linha["perda_pct"],
        "latencia_ms": linha["latencia_ms"],
        "jitter_ms": linha["jitter_ms"],
        "ttl_changed": linha["ttl_changed"],
        "p95_rtt_A": linha["p95_rtt_A"],
        "p99_rtt_A": linha["p99_rtt_A"],
        "p95_jitter_A": linha["p95_jitter_A"],
        "classe": linha["classe"],
        "motivo_rotulagem": linha["motivo_rotulagem"],
        "latencia_num": None if pd.isna(linha["latencia_num"]) else float(linha["latencia_num"]),
    }


def escolher_medicao(quadro, fluxo, p95_proprio, p95_outro):
    """Escolhe uma medição real que mostre o limite do próprio fluxo."""
    parte = quadro.loc[quadro["id_fluxo"].eq(fluxo)].sort_values("timestamp_num", kind="mergesort")
    if parte.empty:
        return None
    com_latencia = parte.loc[parte["latencia_num"].notna()]
    proprio_ok = fim_de_numero(p95_proprio)
    outro_ok = fim_de_numero(p95_outro)
    if proprio_ok and outro_ok and len(com_latencia):
        preferida = com_latencia.loc[
            (com_latencia["latencia_num"] > p95_proprio) & (com_latencia["latencia_num"] < p95_outro)
        ]
        if len(preferida):
            return linha_medicao(preferida.iloc[0])
    if proprio_ok and len(com_latencia):
        acima = com_latencia.loc[com_latencia["latencia_num"] > p95_proprio]
        if len(acima):
            return linha_medicao(acima.iloc[0])
    if len(com_latencia):
        return linha_medicao(com_latencia.iloc[0])
    return linha_medicao(parte.iloc[0])


def amostra_rotulada(quadro):
    """Dez linhas sorteadas, com as três classes e uma perda de 100%."""
    gerador = random.Random(config.SEED)
    indices = []

    def escolher(mascara):
        candidatos = quadro.index[mascara].tolist()
        if not candidatos:
            return None
        return gerador.choice(candidatos)

    for classe in config.CLASSES:
        indice = escolher(quadro["classe"].eq(classe))
        if indice is not None:
            indices.append(indice)
    perda_total = quadro["perda_num"].eq(100) & quadro["rtt_avg"].eq("") & quadro["classe"].eq(config.CLASSE_FALHA)
    indice_total = escolher(perda_total)
    if indice_total is not None:
        indices.append(indice_total)
    faltam = config.HTML_MAX_LINHAS - len(set(indices))
    resto = [indice for indice in quadro.index.tolist() if indice not in set(indices) and quadro.at[indice, "classe"] != ""]
    if faltam > 0 and resto:
        indices.extend(gerador.sample(resto, min(faltam, len(resto))))
    únicos = list(dict.fromkeys(indices))
    parte = quadro.loc[únicos].sort_values(["timestamp_num", "id_fluxo"], kind="mergesort")
    linhas = []
    for linha in parte.itertuples(index=False):
        linhas.append(
            {
                "id_fluxo": linha.id_fluxo,
                "timestamp": int(linha.timestamp_num),
                "timestamp_utc": iso_utc(linha.timestamp_num),
                "perda_pct": linha.perda_pct,
                "latencia_ms": linha.latencia_ms,
                "jitter_ms": linha.jitter_ms,
                "ttl_changed": linha.ttl_changed,
                "p95_rtt_A": linha.p95_rtt_A,
                "p99_rtt_A": linha.p99_rtt_A,
                "classe": linha.classe,
                "motivo_rotulagem": linha.motivo_rotulagem,
            }
        )
    return linhas


def sequencia_exemplo(final, fluxo):
    """Oito medições consecutivas, de preferência com OK, RISCO e FALHA."""
    parte = final.loc[final["id_fluxo"].eq(fluxo)].sort_values("timestamp", kind="mergesort")
    if parte.empty:
        return []
    tamanho = config.HTML_TAM_SEQUENCIA
    classes = parte["classe"].tolist()
    inicio = 0
    for candidato in range(0, max(0, len(classes) - tamanho + 1)):
        if tem_transicao(classes[candidato : candidato + tamanho]):
            inicio = candidato
            break
    trecho = parte.iloc[inicio : inicio + tamanho]
    colunas = config.FEATURES_SEQUENCIA
    linhas = []
    for linha in trecho.itertuples(index=False):
        features = {}
        for nome in colunas:
            valor = getattr(linha, nome)
            features[nome] = None if not fim_de_numero(valor) else float(valor)
        linhas.append(
            {
                "timestamp": int(linha.timestamp),
                "timestamp_utc": iso_utc(linha.timestamp),
                "classe_atual": linha.classe,
                "alvo": linha.alvo,
                "features": features,
            }
        )
    return linhas


def resumo_splits(final, t0, corte_treino, corte_val):
    """Datas e volumes de cada fatia cronológica."""
    resumo = {"t0": iso_utc(t0), "corte_treino": iso_utc(corte_treino), "corte_validacao": iso_utc(corte_val)}
    for nome in config.SPLITS:
        parte = final.loc[final["split"].eq(nome), "timestamp"]
        resumo[nome] = {
            "linhas": int(len(parte)),
            "inicio": iso_utc(parte.min()) if len(parte) else "",
            "fim": iso_utc(parte.max()) if len(parte) else "",
        }
    return resumo


def construir_amostra(quadro, final, metadados, verificacoes, registros, t0, corte_treino, corte_val):
    """Tudo o que a página precisa, e nada além da amostra."""
    p95 = quadro.groupby("id_fluxo")["p95_rtt_num"].first().to_dict()
    p99 = quadro.groupby("id_fluxo")["p99_rtt_num"].first().to_dict()
    p95j = quadro.groupby("id_fluxo")["p95_jitter_num"].first().to_dict()
    fluxo = escolher_fluxo(metadados, final)
    contraste_id = None
    melhor = -1.0
    for candidato, valor in sorted(p95.items()):
        if candidato == fluxo or not fim_de_numero(valor) or not fim_de_numero(p95.get(fluxo)):
            continue
        distancia = abs(float(valor) - float(p95[fluxo]))
        if distancia > melhor:
            melhor = distancia
            contraste_id = candidato
    medicao = escolher_medicao(quadro, fluxo, p95.get(fluxo), p95.get(contraste_id) if contraste_id else None)
    medicao_contraste = escolher_medicao(quadro, contraste_id, p95.get(contraste_id), None) if contraste_id else None
    distribuicao = contagens(quadro["classe"].replace("", config.SEM_ROTULO), list(config.CLASSES) + [config.SEM_ROTULO])
    exclusoes = {}
    for item in registros:
        bloco = exclusoes.setdefault(item["motivo"], {"fluxos": 0, "linhas": 0})
        bloco["fluxos"] += 1
        bloco["linhas"] += int(item["n_linhas"])
    return {
        "totais": {
            "linhas_b": int(len(quadro)),
            "fluxos_b": int(quadro["id_fluxo"].nunique()),
            "linhas_rotuladas": int(quadro["classe"].ne("").sum()),
            "linhas_sem_rotulo": int(quadro["classe"].eq("").sum()),
            "linhas_final": int(len(final)),
            "fluxos_final": int(final["id_fluxo"].nunique()) if len(final) else 0,
            "features": len(config.lista_features()),
        },
        "fluxo": info_fluxo(metadados, fluxo, p95.get(fluxo), p99.get(fluxo), p95j.get(fluxo)),
        "contraste": info_fluxo(metadados, contraste_id, p95.get(contraste_id), p99.get(contraste_id), p95j.get(contraste_id)) if contraste_id else None,
        "medicao": medicao,
        "medicao_contraste": medicao_contraste,
        "amostra": amostra_rotulada(quadro),
        "distribuicao": distribuicao,
        "sequencia": sequencia_exemplo(final, fluxo),
        "persistencia": {
            nome: macro_f1(final.loc[final["split"].eq(nome), "alvo"], final.loc[final["split"].eq(nome), "classe"])
            if final["split"].eq(nome).any()
            else None
            for nome in config.SPLITS
        },
        "alvo_por_split": {
            nome: contagens(final.loc[final["split"].eq(nome), "alvo"], config.CLASSES)
            for nome in config.SPLITS
        },
        "splits": resumo_splits(final, t0, corte_treino, corte_val),
        "exclusoes": exclusoes,
        "verificacoes": verificacoes,
        "regras": list(config.REGRAS),
        "features": [{"nome": nome, "definicao": texto} for nome, texto in config.definicoes_features()],
        "intervalo_s": (metadados.get("parametros_comuns") or {}).get("interval"),
    }


def texto(valor):
    """Texto de página. Vazio vira o traço combinado."""
    if valor is None or valor == "" or (isinstance(valor, float) and not math.isfinite(valor)):
        return config.ROTULO_VAZIO
    return html.escape(str(valor))


def numero_pagina(valor):
    """Número da página, ou a sentinela nomeada."""
    if not fim_de_numero(valor):
        return config.ROTULO_VAZIO
    if abs(float(valor) - config.SENTINELA) < 1e-9:
        return "−1 sentinela"
    return html.escape(format(float(valor), ".6g"))


def classe_html(classe):
    """Classe com cor e com o nome escrito."""
    if classe not in config.CLASSES:
        return config.ROTULO_VAZIO
    return f'<span class="{classe.lower()}">{html.escape(classe)}</span>'


def celulas(valores):
    """Uma linha de tabela já escapada onde for o caso."""
    return "".join(f"<td>{valor}</td>" for valor in valores)


def gerar_html(amostra):
    """Monta a página só com a amostra e os totais."""
    totais = amostra["totais"]
    fluxo = amostra["fluxo"]
    contraste = amostra["contraste"]
    estilos = f"""
    :root {{ color-scheme: light; --bg:#f3f1ea; --ink:#1c1915; --muted:#5e584e; --card:#fffdf8; --line:#e4ddd0; --accent:#0f6e56; --br:#c45c26; --ok:{config.COR_OK}; --risco:{config.COR_RISCO}; --falha:{config.COR_FALHA}; }}
    html[data-theme="dark"] {{ color-scheme: dark; --bg:#12171a; --ink:#f3f1ea; --muted:#b7b1a6; --card:#1c2428; --line:#314046; --accent:#3dbe9a; --br:#e5925d; --ok:{config.COR_OK_ESCURO}; --risco:{config.COR_RISCO_ESCURO}; --falha:{config.COR_FALHA_ESCURO}; }}
    * {{ box-sizing: border-box; }}
    body {{ margin:0; font-family:"Segoe UI","Helvetica Neue",sans-serif; background:var(--bg); color:var(--ink); font-size:1.12rem; }}
    header, main {{ width:min(1100px, calc(100% - 28px)); margin:0 auto; }}
    header {{ padding:28px 0 8px; display:flex; justify-content:space-between; gap:16px; align-items:flex-start; }}
    h1 {{ margin:8px 0; font-size:2rem; }}
    h2 {{ margin:32px 0 12px; font-size:1.45rem; }}
    a {{ color:var(--br); }}
    p, li {{ line-height:1.45; }}
    .voltar {{ color:var(--accent); text-decoration:none; }}
    button {{ font:inherit; border:1px solid var(--line); background:var(--card); color:var(--ink); border-radius:999px; padding:8px 14px; cursor:pointer; }}
    .cartao, .faixa {{ background:var(--card); border:1px solid var(--line); border-radius:16px; padding:16px; }}
    .grade {{ display:grid; grid-template-columns:1fr 1fr; gap:12px; }}
    .rolagem {{ overflow-x:auto; border:1px solid var(--line); border-radius:12px; }}
    table {{ width:100%; border-collapse:collapse; background:var(--card); }}
    th, td {{ text-align:left; padding:8px 10px; border-bottom:1px solid var(--line); white-space:nowrap; }}
    svg {{ width:100%; height:auto; background:var(--card); border:1px solid var(--line); border-radius:16px; }}
    .ok {{ color:var(--ok); font-weight:700; }}
    .risco {{ color:var(--risco); font-weight:700; }}
    .falha {{ color:var(--falha); font-weight:700; }}
    .trilha {{ height:18px; background:var(--line); border-radius:999px; overflow:hidden; }}
    .miolo {{ height:100%; }}
    .miolo.ok {{ background:var(--ok); }}
    .miolo.risco {{ background:var(--risco); }}
    .miolo.falha {{ background:var(--falha); }}
    .miolo.sem {{ background:var(--muted); }}
    .selo {{ display:inline-block; margin:4px 8px 4px 0; padding:4px 10px; border-radius:999px; border:1px solid var(--line); }}
    code {{ font-family:Consolas,monospace; }}
    @media (max-width:800px) {{ .grade, header {{ display:flex; flex-direction:column; }} }}
    """
    partes = [
        "<!DOCTYPE html>",
        '<html lang="pt-BR">',
        "<head>",
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f"<title>{html.escape(config.TITULO_PAGINA)}</title>",
        f"<style>{estilos}</style>",
        "</head>",
        "<body>",
        "<header><div>",
        f'<a class="voltar" href="{html.escape(config.LINK_INICIO)}">← Início</a>',
        f"<h1>{html.escape(config.TITULO_PAGINA)}</h1>",
        "</div><button id=\"tema\" type=\"button\">Tema escuro</button></header>",
        "<main>",
        "<section><h2>Visão geral</h2>",
        svg_fluxo(totais),
        f"<p>{totais['linhas_b']} linhas de B, {totais['fluxos_b']} fluxos. "
        f"{totais['linhas_rotuladas']} rotuladas, {totais['linhas_sem_rotulo']} sem rótulo. "
        f"Dataset final: {totais['linhas_final']} linhas e {totais['fluxos_final']} fluxos.</p>",
        "</section>",
        "<section><h2>Como o baseline ajudou a rotular</h2>",
        f"<p>{html.escape(config.FRASE_BASELINE)}</p>",
        '<div class="grade">',
        cartao_fluxo(amostra["fluxo"], amostra["medicao"]),
        cartao_fluxo(amostra["contraste"], amostra["medicao_contraste"]) if contraste else f"<article class=\"cartao\"><p>{html.escape(config.TEXTO_INSUFICIENTE)}</p></article>",
        "</div>",
        f"<p>{html.escape(config.AVISO_JUNCAO)}</p>",
        "</section>",
        "<section><h2>Regras de rotulagem</h2>",
        tabela_regras(),
        regua_perda(),
        "<ul>",
        *[f"<li><span class=\"{classe.lower()}\">{classe}</span>: {html.escape(frase)}</li>" for classe, frase in config.TEXTO_CLASSE.items()],
        "</ul>",
        f"<p>{html.escape(config.REGRA_NOME.capitalize())}. {html.escape(config.NOTA_TTL)} {html.escape(config.NOTA_SEM_BASELINE)}</p>",
        "</section>",
        "<section><h2>Dataset usado para rotular</h2>",
        f"<p>As linhas vêm de <code>{html.escape(config.FONTE_DATASET)}</code>, somente do Período B.</p>",
        f"<p>{html.escape(config.AVISO_AMOSTRA.format(mostradas=len(amostra['amostra']), total=totais['linhas_b']))}</p>",
        tabela_amostra_entrada(amostra["amostra"]),
        "</section>",
        "<section><h2>Dataset rotulado</h2>",
        tabela_amostra_rotulo(amostra["amostra"]),
        barras_classe(amostra["distribuicao"], totais["linhas_b"]),
        f"<p>{html.escape(config.NOTA_TAXA_LATENCIA)}</p>",
        f"<p>{html.escape(config.NOTA_RTT_VAZIO)}</p>",
        "</section>",
        "<section><h2>Janela temporal e deslocamento do alvo</h2>",
        svg_tempo(amostra.get("intervalo_s")),
        tabela_sequencia(amostra["sequencia"]),
        "<ul>",
        *[f"<li>{html.escape(frase)}</li>" for frase in config.JUSTIFICATIVAS],
        "</ul>",
        f"<p>{html.escape(config.NOTA_DESCARTE)} O limite de intervalo é {config.GAP_MAX_S} segundos e o horizonte é {config.HORIZONTE} medição.</p>",
        linha_persistencia(amostra["persistencia"]),
        "</section>",
        "<section><h2>Dataset final</h2>",
        resumo_final(amostra),
        "</section>",
        "<section><h2>Cuidados</h2><ul>",
        *[f"<li>{html.escape(frase)}</li>" for frase in config.CUIDADOS],
        "</ul></section>",
        "<section><h2>Próximo passo</h2>",
        f"<p>{html.escape(config.TEXTO_PROXIMO)}</p>",
        "</section>",
        "</main>",
        "<script>",
        "const raiz = document.documentElement;",
        "const botao = document.getElementById('tema');",
        "const salvo = localStorage.getItem('etapa-tema');",
        "const inicial = salvo || (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');",
        "aplicar(inicial);",
        "botao.addEventListener('click', () => {",
        "  const proximo = raiz.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';",
        "  localStorage.setItem('etapa-tema', proximo);",
        "  aplicar(proximo);",
        "});",
        "function aplicar(tema) {",
        "  raiz.setAttribute('data-theme', tema);",
        "  botao.textContent = tema === 'dark' ? 'Tema claro' : 'Tema escuro';",
        "}",
        "</script>",
        "</body></html>",
    ]
    config.ARQUIVO_HTML.write_text("\n".join(partes) + "\n", encoding="utf-8")


def svg_fluxo(totais):
    """Cinco caixas do caminho dos dados, com os totais reais."""
    caixas = [
        ("dataset B", f"{totais['linhas_b']} linhas"),
        ("baseline A", "limites do fluxo"),
        ("regras", f"{totais['linhas_rotuladas']} rótulos"),
        ("rotulado", f"{totais['linhas_sem_rotulo']} sem rótulo"),
        ("final", f"{totais['linhas_final']} linhas"),
    ]
    elementos = [f'<svg viewBox="0 0 1080 150" role="img" aria-label="{html.escape(config.ARIA_FLUXO)}">']
    for indice, (titulo, detalhe) in enumerate(caixas):
        x = 16 + indice * 214
        elementos.append(f'<rect x="{x}" y="28" width="180" height="78" rx="12" fill="none" stroke="currentColor"/>')
        elementos.append(f'<text x="{x + 90}" y="58" text-anchor="middle" fill="currentColor" font-size="18">{html.escape(titulo)}</text>')
        elementos.append(f'<text x="{x + 90}" y="84" text-anchor="middle" fill="currentColor" font-size="14">{html.escape(detalhe)}</text>')
        if indice < len(caixas) - 1:
            elementos.append(f'<text x="{x + 192}" y="74" fill="currentColor" font-size="22">→</text>')
    elementos.append("</svg>")
    return "".join(elementos)


def svg_tempo(intervalo):
    """Diagrama t-11 … t e o alvo em t+1."""
    minutos = []
    if isinstance(intervalo, (int, float)) and intervalo:
        minutos = [int(tamanho * intervalo / 60) for tamanho in config.JANELAS]
    legenda = ", ".join(
        f"{tamanho} medições" + (f" (~{minuto} min)" if minuto else "")
        for tamanho, minuto in zip(config.JANELAS, minutos or [None] * len(config.JANELAS))
    )
    return (
        f'<svg viewBox="0 0 1080 180" role="img" aria-label="{html.escape(config.ARIA_TEMPO)}">'
        '<text x="40" y="36" fill="currentColor" font-size="16">t−11 … t−2  t−1  t</text>'
        '<text x="760" y="36" fill="currentColor" font-size="16">t+1 = alvo</text>'
        '<rect x="40" y="56" width="620" height="22" fill="currentColor" fill-opacity="0.15"/>'
        '<rect x="250" y="86" width="410" height="22" fill="currentColor" fill-opacity="0.28"/>'
        '<rect x="430" y="116" width="230" height="22" fill="currentColor" fill-opacity="0.45"/>'
        '<text x="48" y="73" fill="currentColor" font-size="14">12 medições, só passado, inclui t</text>'
        '<text x="258" y="103" fill="currentColor" font-size="14">6 medições</text>'
        '<text x="438" y="133" fill="currentColor" font-size="14">3 medições</text>'
        '<text x="760" y="100" fill="currentColor" font-size="16">não entra nas features</text>'
        f'<text x="40" y="168" fill="currentColor" font-size="14">{html.escape(config.LEGENDA_FUTURO)} {html.escape(legenda)}</text>'
        "</svg>"
    )


def cartao_fluxo(info, medicao):
    """Baseline de um fluxo e uma medição real de B."""
    if not info or not medicao:
        return f"<article class=\"cartao\"><p>{html.escape(config.TEXTO_INSUFICIENTE)}</p></article>"
    nome = info["hostname"] or info["id_fluxo"]
    return (
        '<article class="cartao">'
        f"<p><code>{texto(info['id_fluxo'])}</code> · {texto(nome)} · {texto(info['pais'])}</p>"
        f"<p>Período A: P95 {numero_pagina(info['p95_rtt_A'])} ms, "
        f"P99 {numero_pagina(info['p99_rtt_A'])} ms, "
        f"P95 do jitter {numero_pagina(info['p95_jitter_A'])} ms.</p>"
        f"<p>{texto(medicao['timestamp_utc'])}: perda {texto(medicao['perda_pct'])}, "
        f"latência {texto(medicao['latencia_ms']) or config.ROTULO_VAZIO} ms, "
        f"jitter {texto(medicao['jitter_ms'])} ms.</p>"
        f"<p>Resultado da {html.escape(config.REGRA_NOME)}: {classe_html(medicao['classe'])} "
        f"({texto(medicao['motivo_rotulagem'])}).</p>"
        "</article>"
    )


def tabela_regras():
    """A regra na ordem em que o código a avalia."""
    linhas = []
    for regra in config.REGRAS:
        linhas.append(
            "<tr>"
            + celulas(
                [
                    texto(regra["condicao"]),
                    classe_html(regra["classe"]),
                    texto(regra["motivo"]),
                ]
            )
            + "</tr>"
        )
    return (
        '<div class="rolagem"><table><thead><tr>'
        "<th>Condição</th><th>Classe</th><th>Motivo</th>"
        "</tr></thead><tbody>"
        + "".join(linhas)
        + "</tbody></table></div>"
    )


def regua_perda():
    """Os quatro valores possíveis com 3 pacotes."""
    marcas = (
        (0, config.CLASSE_OK),
        (config.LIM_PERDA_RISCO, config.CLASSE_RISCO),
        (config.LIM_PERDA_FALHA, config.CLASSE_FALHA),
        (100, config.CLASSE_FALHA),
    )
    itens = "".join(
        f"<li>{texto(f'{valor:.2f}')}% → {classe_html(classe)}</li>" for valor, classe in marcas
    )
    return f"<ul>{itens}</ul><p>{html.escape(config.NOTA_PERDA_PACOTES)}</p>"


def tabela_amostra_entrada(linhas):
    """Colunas de entrada, antes do rótulo."""
    corpo = []
    for linha in linhas:
        latencia = texto(linha["latencia_ms"]) if linha["latencia_ms"] != "" else config.ROTULO_VAZIO
        corpo.append(
            "<tr>"
            + celulas(
                [
                    texto(linha["id_fluxo"]),
                    texto(linha["timestamp_utc"]),
                    texto(linha["perda_pct"]),
                    latencia,
                    texto(linha["jitter_ms"]) if linha["jitter_ms"] != "" else config.ROTULO_VAZIO,
                    texto(linha["ttl_changed"]),
                ]
            )
            + "</tr>"
        )
    return (
        '<div class="rolagem"><table><thead><tr>'
        "<th>id_fluxo</th><th>timestamp (UTC)</th><th>perda_pct</th><th>latencia_ms</th><th>jitter_ms</th><th>ttl_changed</th>"
        "</tr></thead><tbody>"
        + "".join(corpo)
        + "</tbody></table></div>"
    )


def tabela_amostra_rotulo(linhas):
    """A mesma amostra, agora com o limite do fluxo e o rótulo."""
    corpo = []
    for linha in linhas:
        corpo.append(
            "<tr>"
            + celulas(
                [
                    texto(linha["id_fluxo"]),
                    texto(linha["timestamp_utc"]),
                    texto(linha["perda_pct"]) if linha["perda_pct"] != "" else config.ROTULO_VAZIO,
                    texto(linha["latencia_ms"]) if linha["latencia_ms"] != "" else config.ROTULO_VAZIO,
                    texto(linha["jitter_ms"]) if linha["jitter_ms"] != "" else config.ROTULO_VAZIO,
                    texto(linha["p95_rtt_A"]) if linha["p95_rtt_A"] != "" else config.ROTULO_VAZIO,
                    texto(linha["p99_rtt_A"]) if linha["p99_rtt_A"] != "" else config.ROTULO_VAZIO,
                    classe_html(linha["classe"]),
                    texto(linha["motivo_rotulagem"]),
                ]
            )
            + "</tr>"
        )
    return (
        '<div class="rolagem"><table><thead><tr>'
        "<th>id_fluxo</th><th>timestamp (UTC)</th><th>perda_pct</th><th>latencia_ms</th><th>jitter_ms</th>"
        "<th>p95_rtt_A</th><th>p99_rtt_A</th><th>classe</th><th>motivo</th>"
        "</tr></thead><tbody>"
        + "".join(corpo)
        + "</tbody></table></div>"
    )


def barras_classe(distribuicao, total):
    """Quantidade e percentual, inclusive sem rótulo."""
    linhas = [f'<div role="img" aria-label="{html.escape(config.ARIA_BARRAS)}">']
    for nome in list(config.CLASSES) + [config.SEM_ROTULO]:
        quantidade = int(distribuicao.get(nome, 0))
        percentual = (100 * quantidade / total) if total else 0
        css = "sem" if nome == config.SEM_ROTULO else nome.lower()
        rotulo = nome if nome in config.CLASSES else nome
        linhas.append(
            "<p>"
            f'<span class="{css}">{html.escape(rotulo)}</span> '
            f"{quantidade} ({percentual:.2f}%)"
            f'<span class="trilha"><span class="miolo {css}" style="width:{percentual:.2f}%"></span></span>'
            "</p>"
        )
    linhas.append("</div>")
    return "".join(linhas)


def tabela_sequencia(linhas):
    """Liga a classe atual de uma linha ao alvo, que é a classe da linha de baixo."""
    if not linhas:
        return f"<p>{html.escape(config.TEXTO_INSUFICIENTE)}</p>"
    cabecalho = "".join(f"<th>{html.escape(nome)}</th>" for nome in config.FEATURES_SEQUENCIA)
    corpo = []
    for indice, linha in enumerate(linhas):
        proxima = linhas[indice + 1]["classe_atual"] if indice + 1 < len(linhas) else ""
        liga = "↓" if proxima and linha["alvo"] == proxima else ""
        features = "".join(f"<td>{numero_pagina(linha['features'].get(nome))}</td>" for nome in config.FEATURES_SEQUENCIA)
        corpo.append(
            "<tr>"
            f"<td>{texto(linha['timestamp_utc'])}</td>"
            f"<td>{classe_html(linha['classe_atual'])}</td>"
            f"{features}"
            f"<td>{classe_html(linha['alvo'])}</td>"
            f"<td>{liga}</td>"
            "</tr>"
        )
    return (
        f"<p>Fluxo da tabela: medições consecutivas do dataset final. A seta liga <code>classe_atual</code> "
        f"desta linha ao <code>alvo</code>, que é a classe da linha de baixo. {html.escape(config.NOTA_SENTINELA)}</p>"
        '<div class="rolagem"><table><thead><tr>'
        "<th>timestamp (UTC)</th><th>classe_atual (t)</th>"
        f"{cabecalho}<th>alvo (t+1)</th><th></th>"
        "</tr></thead><tbody>"
        + "".join(corpo)
        + "</tbody></table></div>"
    )


def linha_persistencia(persistencia):
    """Macro-F1 de quem só repete a classe atual."""
    partes = []
    for nome in config.SPLITS:
        valor = persistencia.get(nome)
        partes.append(f"{nome} {valor:.4f}" if isinstance(valor, float) else f"{nome} {config.ROTULO_VAZIO}")
    return (
        "<p>Baseline de persistência (prever que o alvo repete a classe atual), macro-F1 por split: "
        + html.escape(", ".join(partes))
        + ".</p>"
    )


def resumo_final(amostra):
    """Papéis das colunas, splits, alvo, exclusões e selos."""
    grupos = (
        ("Metadado", ", ".join(config.COLUNAS_METADADOS_FINAL)),
        ("Feature", f"{amostra['totais']['features']} colunas, normalizadas pelo baseline do próprio fluxo"),
        ("Alvo", "classe da medição seguinte do mesmo fluxo"),
    )
    lista = "".join(f"<li><strong>{html.escape(papel)}.</strong> {html.escape(texto_papel)}</li>" for papel, texto_papel in grupos)
    splits = amostra["splits"]
    fatias = []
    for nome in config.SPLITS:
        item = splits[nome]
        fatias.append(f"<li>{html.escape(nome)}: {item['linhas']} linhas, {texto(item['inicio'])} → {texto(item['fim'])}</li>")
    fatias.append(
        f"<li>Cortes a partir de t0 {texto(splits['t0'])}: treino antes de {texto(splits['corte_treino'])}, "
        f"validação antes de {texto(splits['corte_validacao'])}, com {config.EMBARGO_MIN} min de embargo após cada corte.</li>"
    )
    alvo = []
    for nome in config.SPLITS:
        contagem = amostra["alvo_por_split"][nome]
        alvo.append(f"<li>{html.escape(nome)}: " + ", ".join(f"{classe} {contagem.get(classe, 0)}" for classe in config.CLASSES) + "</li>")
    exclusoes = "".join(
        f"<li>{html.escape(motivo)}: {bloco['fluxos']} fluxos, {bloco['linhas']} linhas</li>"
        for motivo, bloco in amostra["exclusoes"].items()
    ) or f"<li>{html.escape(config.TEXTO_INSUFICIENTE)}</li>"
    selos = "".join(
        f'<span class="selo">{html.escape(nome)}: {html.escape(item["estado"])}</span>'
        for nome, item in amostra["verificacoes"].items()
    )
    return (
        f"<ul>{lista}</ul>"
        f"<h3>Split cronológico</h3><ul>{''.join(fatias)}</ul>"
        f"<h3>Alvo por split</h3><ul>{''.join(alvo)}</ul>"
        f"<h3>Exclusões</h3><ul>{exclusoes}</ul>"
        f"<h3>Verificações</h3><p>{selos}</p>"
    )


def cartao_etapa7(rotuladas, finais):
    """Cartão novo da página inicial. Os cartões antigos não são reescritos."""
    frase = f"{rotuladas} linhas rotuladas. {finais} linhas no dataset final."
    return (
        '<article class="cartao ativo">\n'
        f'      <p class="etapa">{html.escape(config.ROTULO_ETAPA7)}</p>\n'
        f"      <h2>{html.escape(config.TITULO_CARTAO)}</h2>\n"
        f"      <p>{html.escape(frase)}</p>\n"
        f'      <a href="{html.escape(config.LINK_ETAPA7, quote=True)}">Abrir página</a>\n'
        "    </article>"
    )


def atualizar_index(rotuladas, finais):
    """Insere ou substitui só o bloco da Etapa 7."""
    bloco = f"{config.MARCADOR_ETAPA7_INICIO}\n    {cartao_etapa7(rotuladas, finais)}\n    {config.MARCADOR_ETAPA7_FIM}"
    texto_index = config.ARQUIVO_INDEX.read_text(encoding="utf-8")
    if config.MARCADOR_ETAPA7_INICIO in texto_index and config.MARCADOR_ETAPA7_FIM in texto_index:
        inicio = texto_index.index(config.MARCADOR_ETAPA7_INICIO)
        fim = texto_index.index(config.MARCADOR_ETAPA7_FIM) + len(config.MARCADOR_ETAPA7_FIM)
        config.ARQUIVO_INDEX.write_text(texto_index[:inicio] + bloco + texto_index[fim:], encoding="utf-8")
        return
    if config.MARCADOR_ETAPA6_FIM not in texto_index:
        raise SystemExit("O index.html não tem o fim da Etapa 6 para inserir o cartão novo.")
    config.ARQUIVO_INDEX.write_text(
        texto_index.replace(config.MARCADOR_ETAPA6_FIM, config.MARCADOR_ETAPA6_FIM + "\n" + bloco, 1),
        encoding="utf-8",
    )


def avisos_jitter(quadro):
    """Fluxos em que qualquer jitter positivo vira RISCO, porque o P95 de A é zero."""
    validos = quadro["status_baseline"].eq(config.STATUS_BASELINE_OK) & quadro["p95_jitter_num"].eq(0)
    return sorted(quadro.loc[validos, "id_fluxo"].unique())


def perda_fora_do_conjunto(quadro):
    """Perdas que não são 0, 1/3, 2/3 nem 100, dentro da tolerância."""
    perda = quadro["perda_num"]
    presente = perda.notna()
    distancia = np.min(np.abs(perda.to_numpy(dtype=float)[:, None] - np.array(config.VALORES_PERDA_ESPERADOS)), axis=1)
    mascara = presente.to_numpy() & (distancia > config.EPS)
    fora = quadro.loc[mascara, ["id_fluxo", "timestamp", "perda_pct"]]
    exemplos = [
        {"id_fluxo": linha.id_fluxo, "timestamp": linha.timestamp, "perda_pct": linha.perda_pct}
        for linha in fora.head(20).itertuples(index=False)
    ]
    return {"quantidade": int(mascara.sum()), "exemplos": exemplos}


def sem_rotulo_severo(quadro):
    """Perda grave que ficou sem rótulo. É exposta e não é classificada."""
    mascara = (
        quadro["classe"].eq("")
        & quadro["perda_num"].notna()
        & (quadro["perda_num"] >= config.LIM_PERDA_FALHA - config.EPS)
    )
    contagem = quadro.loc[mascara].groupby("id_fluxo").size()
    return [{"id_fluxo": fluxo, "n_linhas": int(quantidade)} for fluxo, quantidade in sorted(contagem.items())]


def montar_features_json(final, t0, corte_treino, corte_val, embargo):
    """Contrato lido pela etapa seguinte."""
    splits = resumo_splits(final, t0, corte_treino, corte_val)
    return {
        "alvo": "classe da medição t+H do mesmo fluxo",
        "features": [nome for nome, _texto in config.definicoes_features()],
        "definicoes": {nome: texto for nome, texto in config.definicoes_features()},
        "metadados": list(config.COLUNAS_METADADOS_FINAL),
        "horizonte": config.HORIZONTE,
        "janelas": list(config.JANELAS),
        "sentinela": config.SENTINELA,
        "splits": splits,
        "parametros": {
            "gap_max_s": config.GAP_MAX_S,
            "ttl_clip": config.TTL_CLIP,
            "ttl_reset": config.TTL_RESET,
            "max_frac_falha_latencia": config.MAX_FRAC_FALHA_LATENCIA,
            "corte_treino_dias": config.CORTE_TREINO_DIAS,
            "corte_val_dias": config.CORTE_VAL_DIAS,
            "embargo_min": config.EMBARGO_MIN,
            "embargo_s": embargo,
            "lim_perda_risco": config.LIM_PERDA_RISCO,
            "lim_perda_falha": config.LIM_PERDA_FALHA,
            "eps": config.EPS,
            "seed": config.SEED,
            "float_format": config.FLOAT_FORMAT,
        },
    }


def imprimir_resumo(qualidade):
    """Mostra o essencial no terminal."""
    print()
    print("=== Resumo da Etapa 7 ===")
    print(f"Linhas lidas: {qualidade['linhas_lidas']}")
    print(f"Rotuladas: {qualidade['linhas_rotuladas']}")
    print(f"Sem rótulo: {qualidade['linhas_sem_rotulo']} {qualidade['sem_rotulo_por_motivo']}")
    print(f"Classes: {qualidade['contagem_por_classe']}")
    print(f"Dataset final: {qualidade['linhas_dataset_final']} linhas, {qualidade['fluxos_dataset_final']} fluxos")
    print(f"Persistência macro-F1: {qualidade['baseline_persistencia_macro_f1']}")
    for nome, item in qualidade["verificacoes"].items():
        print(f"  {item['estado']} {nome}: {item['detalhe']}")
    print(f"CSV rotulado: {config.ARQUIVO_ROTULADO}")
    print(f"CSV final: {config.ARQUIVO_FINAL}")
    print(f"HTML: {config.ARQUIVO_HTML}")


def main():
    """Lê, rotula, desloca o alvo, verifica e publica a página."""
    configurar_saida()
    if config.HORIZONTE < 1:
        raise SystemExit("H < 1 não é aceito.")
    if config.CORTE_VAL_DIAS <= config.CORTE_TREINO_DIAS:
        raise SystemExit("O corte de validação precisa ser depois do corte de treino.")
    garantir_pastas()
    copiar_prompt()
    conferir_regra_sintetica()
    conferir_janela_sintetica()
    metadados = ler_metadados()
    dataset = ler_dataset()
    baseline = ler_baseline()
    print("Rotulando o Período B...")
    quadro = juntar_e_rotular(dataset, baseline)
    duplicatas_entrada = int(quadro.duplicated(["id_fluxo", "timestamp_num"]).sum())
    if duplicatas_entrada:
        raise SystemExit(f"O dataset de entrada tem {duplicatas_entrada} duplicatas de fluxo e timestamp.")
    janelas = metadados["janelas"]
    inicio_b = janelas["B"]["inicio_unix"]
    fim_b = janelas["B"]["fim_unix"]
    inicio_a = janelas["A"]["inicio_unix"]
    fim_a = janelas["A"]["fim_unix"]
    instante = quadro["timestamp_num"]
    fora = (instante < inicio_b) | (instante >= fim_b) | ((instante >= inicio_a) & (instante < fim_a))
    desatualizados = fluxos_desatualizados(quadro)
    serie, sem_valido = preparar_serie(quadro, desatualizados)
    print("Calculando janelas...")
    serie = calcular_features(serie)
    motivo_descarte = motivos_de_descarte(serie)
    candidatos = serie.loc[motivo_descarte.eq("")].copy()
    if candidatos.empty:
        raise SystemExit(config.TEXTO_INSUFICIENTE)
    t0 = int(candidatos["timestamp"].min())
    candidatos, corte_treino, corte_val, embargo = atribuir_split(candidatos, t0)
    final = candidatos.loc[candidatos["motivo_embargo"].eq("")].copy()
    final = aplicar_sentinela(final)
    final["_anchor"] = pd.to_numeric(final["anchor_id"])
    final["_probe"] = pd.to_numeric(final["probe_id"])
    final = final.sort_values(["_anchor", "_probe", "timestamp"], kind="mergesort").reset_index(drop=True)
    verificacoes = verificar(quadro, final, serie, sem_valido, desatualizados, (corte_treino, corte_val, embargo))
    if int(fora.sum()):
        verificacoes["timestamps_na_janela_b"] = {
            "estado": "ATENCAO",
            "detalhe": f"{int(fora.sum())} timestamps fora de B ou dentro de A.",
        }
    else:
        verificacoes["timestamps_na_janela_b"] = {
            "estado": "PASSOU",
            "detalhe": "Todo timestamp está em B e fora de A.",
        }
    registros = montar_exclusoes(quadro, sem_valido, desatualizados, serie, motivo_descarte, candidatos)
    print("Gravando...")
    gravar_rotulado(quadro)
    gravar_auditoria(quadro)
    gravar_final(final)
    gravar_exclusoes(registros)
    qualidade = montar_qualidade(
        quadro,
        final,
        registros,
        verificacoes,
        janelas,
        int(fora.sum()),
        avisos_jitter(quadro),
        perda_fora_do_conjunto(quadro),
        sem_rotulo_severo(quadro),
    )
    gravar_json(config.ARQUIVO_QUALIDADE, qualidade)
    gravar_json(config.ARQUIVO_FEATURES, montar_features_json(final, t0, corte_treino, corte_val, embargo))
    amostra = construir_amostra(quadro, final, metadados, verificacoes, registros, t0, corte_treino, corte_val)
    gravar_json(config.ARQUIVO_AMOSTRA, amostra)
    gerar_html(amostra)
    atualizar_index(qualidade["linhas_rotuladas"], qualidade["linhas_dataset_final"])
    imprimir_resumo(qualidade)
    falhou = [nome for nome, item in verificacoes.items() if item["estado"] == "FALHOU"]
    if falhou:
        raise SystemExit("Verificações que falharam: " + ", ".join(falhou))


if __name__ == "__main__":
    main()
