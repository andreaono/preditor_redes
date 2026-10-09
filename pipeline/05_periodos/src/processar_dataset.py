"""Constrói o dataset do período B e o baseline de TTL do período A.

Este script não acessa a rede e não regrava fluxo_bruto.csv. Lê o bruto e os
metadados da coleta. A mediana do TTL usa somente linhas com periodo = A.
O dataset usa somente linhas com periodo = B.

Casos de borda:
- rcvd == 0: perda_pct = 100 e os RTT, o jitter e a latência ficam vazios.
- ttl ausente: delta_ttl e ttl_changed ficam vazios, nunca 0.
- par sem baseline: ttl_baseline, delta_ttl e ttl_changed ficam vazios.
- sent == 0: perda_pct fica vazio.
- ttl_changed = 1 não é falha; só diz que o TTL diferiu da mediana do par.
- O TTL é o valor do pacote de resposta, não a quantidade de hops.
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import shutil
import statistics
import sys
from datetime import datetime, timezone

import pandas as pd

import config


def preparar_saida():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")


def garantir_pastas():
    for pasta in (config.DATA_DIR, config.TEMPLATE_DIR, config.PROMPT_DIR):
        pasta.mkdir(parents=True, exist_ok=True)


def copiar_prompt():
    if config.ARQUIVO_PROMPT_ORIGEM.is_file():
        shutil.copyfile(config.ARQUIVO_PROMPT_ORIGEM, config.ARQUIVO_PROMPT)


def ler_json(caminho):
    return json.loads(caminho.read_text(encoding="utf-8"))


def agora_utc():
    return datetime.now(timezone.utc).replace(microsecond=0)


def numero(valor):
    if isinstance(valor, bool) or valor is None or valor == "":
        return None
    if isinstance(valor, (int, float)):
        if isinstance(valor, float) and valor != valor:
            return None
        return float(valor)
    try:
        return float(str(valor).strip())
    except ValueError:
        return None


def inteiro(valor):
    convertido = numero(valor)
    if convertido is None:
        return None
    return int(convertido)


def texto_numero(valor):
    """Mantém o número completo, sem arredondar para poucas casas."""
    if isinstance(valor, bool) or valor is None:
        return ""
    if isinstance(valor, int):
        return str(valor)
    if isinstance(valor, float):
        if valor != valor:
            return ""
        if valor.is_integer():
            return str(int(valor))
        return format(valor, ".16f").rstrip("0").rstrip(".")
    return str(valor)


def extrair_rtts(texto):
    """RTTs numéricos de result. Timeout, booleano e texto são ignorados."""
    if not texto:
        return []
    try:
        dados = json.loads(texto)
    except json.JSONDecodeError:
        return []
    if not isinstance(dados, list):
        return []
    rtts = []
    for item in dados:
        if not isinstance(item, dict):
            continue
        valor = item.get(config.CAMPO_RTT)
        if isinstance(valor, bool) or not isinstance(valor, (int, float)):
            continue
        rtts.append(float(valor))
    return rtts


def tem_timeout(texto):
    if not texto:
        return False
    try:
        dados = json.loads(texto)
    except json.JSONDecodeError:
        return False
    if not isinstance(dados, list):
        return False
    return any(isinstance(item, dict) and config.MARCADOR_TIMEOUT in item for item in dados)


def feature_anchor_id(valor):
    """Origem: fluxo. Fórmula: id da anchor de destino. Unidade: —.

    Interpretação: identifica o destino. Não é o msm_id nem o probe_id.
    """
    return "" if valor is None else str(valor)


def feature_probe_id(valor):
    """Origem: prb_id. Fórmula: valor retornado. Unidade: —.

    Interpretação: identifica a probe que originou o ping.
    """
    return "" if valor is None else str(valor)


def feature_rtt_min(min_original, rtts, perda_total):
    """Origem: min. Fórmula: usar min; se ausente, min(rtts). Unidade: ms.

    Interpretação: menor RTT da execução. Vazio quando a perda é 100%.
    """
    if perda_total:
        return ""
    if min_original != "":
        return min_original
    if not rtts:
        return ""
    return texto_numero(min(rtts))


def feature_rtt_max(max_original, rtts, perda_total):
    """Origem: max. Fórmula: usar max; se ausente, max(rtts). Unidade: ms.

    Interpretação: maior RTT da execução. Vazio quando a perda é 100%.
    """
    if perda_total:
        return ""
    if max_original != "":
        return max_original
    if not rtts:
        return ""
    return texto_numero(max(rtts))


def feature_rtt_avg(avg_original, rtts, perda_total):
    """Origem: avg. Fórmula: usar avg; se ausente, sum(rtts)/len(rtts). Unidade: ms.

    Interpretação: RTT médio da execução. Vazio quando a perda é 100%.
    """
    if perda_total:
        return ""
    if avg_original != "":
        return avg_original
    if not rtts:
        return ""
    return texto_numero(sum(rtts) / len(rtts))


def feature_perda_pct(sent_original, rcvd_original):
    """Origem: sent e rcvd. Fórmula: ((sent − rcvd) / sent) × 100 se sent > 0. Unidade: %.

    Interpretação: pacotes sem resposta. 100 se rcvd é 0. Vazio se sent é 0 ou ausente.
    """
    sent = numero(sent_original)
    rcvd = numero(rcvd_original)
    if sent is None or sent <= 0 or rcvd is None:
        return ""
    return texto_numero((sent - rcvd) / sent * 100)


def feature_jitter_ms(rtts, perda_total):
    """Origem: result[].rtt. Fórmula: statistics.pstdev(rtts). Unidade: ms.

    Interpretação: dispersão dos RTTs da rodada. 0 se há um único RTT.
    Vazio sem RTT válido ou quando a perda é 100%. Três pacotes são uma amostra curta.
    """
    if perda_total or not rtts:
        return ""
    if len(rtts) == 1:
        return "0"
    return texto_numero(statistics.pstdev(rtts))


def feature_ttl(valor):
    """Origem: ttl. Fórmula: valor retornado, sem alterar. Unidade: —.

    Interpretação: TTL visto na resposta. Não é número de hops. Ausente fica vazio.
    """
    return "" if valor is None or valor == "" else str(valor)


def feature_ttl_baseline(valor):
    """Origem: ttl no período A. Fórmula: mediana do par. Unidade: —.

    Interpretação: TTL típico daquele probe e daquela anchor antes do dataset.
    Vazio se o par não alcançou o mínimo de amostras em A.
    """
    return "" if valor is None or valor == "" else str(valor)


def feature_delta_ttl(ttl, baseline):
    """Origem: ttl e ttl_baseline. Fórmula: ttl − ttl_baseline. Unidade: —.

    Interpretação: afastamento do histórico, com sinal. Vazio sem ttl ou sem baseline.
    Nunca preencher com 0 quando um dos dois falta.
    """
    ttl_num = numero(ttl)
    base_num = numero(baseline)
    if ttl_num is None or base_num is None:
        return ""
    return texto_numero(ttl_num - base_num)


def feature_ttl_changed(delta):
    """Origem: delta_ttl. Fórmula: int(delta_ttl != 0). Unidade: 0/1.

    Interpretação: 1 significa que o TTL mudou em relação ao par.
    Não é rótulo de falha de rede. Vazio quando delta_ttl é vazio.
    """
    delta_num = numero(delta)
    if delta_num is None:
        return ""
    return "1" if delta_num != 0 else "0"


def feature_latencia_ms(rtt_avg):
    """Origem: rtt_avg. Fórmula: latencia_ms = rtt_avg. Unidade: ms.

    Interpretação: o mesmo número de rtt_avg, só com outro nome. São colunas colineares.
    """
    return rtt_avg


def feature_timestamp(valor):
    """Origem: timestamp. Fórmula: Unix timestamp original. Unidade: s (UTC).

    Interpretação: instante da execução. No dataset, precisa cair na janela B.
    """
    return "" if valor is None or valor == "" else str(valor)


def dentro(timestamp, inicio_unix, fim_unix):
    if timestamp is None:
        return False
    return inicio_unix <= timestamp < fim_unix


def carregar_bruto():
    if not config.ARQUIVO_CSV_BRUTO.is_file():
        raise SystemExit("fluxo_bruto.csv não existe. Rode coletar_periodos.py antes.")
    with config.ARQUIVO_CSV_BRUTO.open(encoding="utf-8", newline="") as arquivo:
        leitor = csv.DictReader(arquivo)
        if leitor.fieldnames != list(config.COLUNAS_CSV_BRUTO):
            raise SystemExit(f"Cabeçalho inesperado no bruto: {leitor.fieldnames}")
        return list(leitor)


def janelas(metadados):
    saida = {}
    for periodo in metadados["periodos"]:
        inicio = datetime.fromisoformat(periodo["inicio"])
        fim = datetime.fromisoformat(periodo["fim"])
        saida[periodo["nome"]] = (int(inicio.timestamp()), int(fim.timestamp()), periodo)
    return saida


def calcular_baseline(linhas_a):
    """Mediana de TTL por par, só com as linhas do período A."""
    if not linhas_a:
        return {}
    quadro = pd.DataFrame(linhas_a)
    quadro["ttl_num"] = pd.to_numeric(quadro[config.CAMPO_TTL], errors="coerce")
    validos = quadro.dropna(subset=["ttl_num"])
    if validos.empty:
        return {}
    grupos = validos.groupby(["anchor_id", "probe_id"], sort=True)["ttl_num"]
    baseline = {}
    for (anchor_id, probe_id), serie in grupos:
        if len(serie) < config.MIN_AMOSTRAS_BASELINE:
            continue
        mediana = float(serie.median())
        baseline[(str(anchor_id), str(probe_id))] = {
            "anchor_id": str(anchor_id),
            "probe_id": str(probe_id),
            "ttl_baseline": texto_numero(mediana),
            "n_amostras_A": str(int(serie.shape[0])),
            "ttl_min_A": texto_numero(float(serie.min())),
            "ttl_max_A": texto_numero(float(serie.max())),
            "n_ttl_distintos_A": str(int(serie.nunique())),
        }
    return baseline


def registrar_divergencia(divergencias, linha, campo, original, recalculado):
    orig = numero(original)
    calc = numero(recalculado) if not isinstance(recalculado, float) else recalculado
    if orig is None or calc is None:
        return
    diferenca = abs(orig - calc)
    if diferenca > config.TOLERANCIA_DIVERGENCIA_MS:
        divergencias.append(
            {
                "id_fluxo": linha["id_fluxo"],
                "timestamp": linha["timestamp"],
                "campo": campo,
                "original": original,
                "recalculado": texto_numero(calc),
                "diferenca": texto_numero(diferenca),
            }
        )


def processar(linhas, metadados):
    limites = janelas(metadados)
    inicio_a, fim_a, _ = limites[config.PERIODO_BASELINE]
    inicio_b, fim_b, _ = limites[config.PERIODO_DATASET]
    linhas_a = []
    linhas_b = []
    descartes = []
    for linha in linhas:
        instante = inteiro(linha["timestamp"])
        if linha["type"] != config.TIPO_MEDICAO:
            descartes.append((linha, config.MOTIVO_TIPO_LINHA))
            continue
        if linha["periodo"] == config.PERIODO_BASELINE:
            if not dentro(instante, inicio_a, fim_a):
                descartes.append((linha, config.MOTIVO_TIMESTAMP))
                continue
            linhas_a.append(linha)
        elif linha["periodo"] == config.PERIODO_DATASET:
            if not dentro(instante, inicio_b, fim_b):
                descartes.append((linha, config.MOTIVO_TIMESTAMP))
                continue
            linhas_b.append(linha)
        else:
            descartes.append((linha, config.MOTIVO_TIMESTAMP))

    baseline = calcular_baseline(linhas_a)
    divergencias = []
    dataset = []
    for linha in linhas_b:
        rtts = extrair_rtts(linha["result"])
        rcvd = numero(linha["rcvd"])
        perda_total = rcvd is not None and rcvd == 0
        if not perda_total and rtts:
            registrar_divergencia(divergencias, linha, "min", linha["min"], min(rtts) if rtts else None)
            registrar_divergencia(divergencias, linha, "max", linha["max"], max(rtts) if rtts else None)
            registrar_divergencia(
                divergencias, linha, "avg", linha["avg"], sum(rtts) / len(rtts) if rtts else None
            )
        par = (linha["anchor_id"], linha["probe_id"])
        base = baseline.get(par, {}).get("ttl_baseline", "")
        rtt_min = feature_rtt_min(linha["min"], rtts, perda_total)
        rtt_max = feature_rtt_max(linha["max"], rtts, perda_total)
        rtt_avg = feature_rtt_avg(linha["avg"], rtts, perda_total)
        ttl = feature_ttl(linha["ttl"])
        base_txt = feature_ttl_baseline(base)
        delta = feature_delta_ttl(ttl, base_txt)
        dataset.append(
            {
                "anchor_id": feature_anchor_id(linha["anchor_id"]),
                "probe_id": feature_probe_id(linha["probe_id"]),
                "rtt_min": rtt_min,
                "rtt_max": rtt_max,
                "rtt_avg": rtt_avg,
                "perda_pct": feature_perda_pct(linha["sent"], linha["rcvd"]),
                "jitter_ms": feature_jitter_ms(rtts, perda_total),
                "ttl": ttl,
                "ttl_baseline": base_txt,
                "delta_ttl": delta,
                "ttl_changed": feature_ttl_changed(delta),
                "latencia_ms": feature_latencia_ms(rtt_avg),
                "timestamp": feature_timestamp(linha["timestamp"]),
                "_id_fluxo": linha["id_fluxo"],
                "_result": linha["result"],
                "_sent": linha["sent"],
                "_rcvd": linha["rcvd"],
                "_min": linha["min"],
                "_max": linha["max"],
                "_avg": linha["avg"],
                "_rtts": rtts,
            }
        )
    return {
        "dataset": dataset,
        "baseline": baseline,
        "linhas_a": linhas_a,
        "descartes": descartes,
        "divergencias": divergencias,
        "janela_b": (inicio_b, fim_b),
    }


def agregar_exclusoes(metadados, descartes):
    grupos = {}
    for item in metadados.get("exclusoes_medicao") or []:
        chave = (
            str(item.get("anchor_id", "")),
            str(item.get("probe_id", "")),
            str(item.get("msm_id", "")),
            str(item.get("id_fluxo", "")),
            item.get("motivo") or "",
        )
        grupos[chave] = grupos.get(chave, 0) + int(item.get("n") or 0)
    for linha, motivo in descartes:
        chave = (linha["anchor_id"], linha["probe_id"], linha["msm_id"], linha["id_fluxo"], motivo)
        grupos[chave] = grupos.get(chave, 0) + 1
    return [
        {
            "anchor_id": chave[0],
            "probe_id": chave[1],
            "msm_id": chave[2],
            "id_fluxo": chave[3],
            "motivo": chave[4],
            "n": str(quantidade),
        }
        for chave, quantidade in grupos.items()
    ]


def pares_sem_baseline(dataset, baseline):
    vistos = []
    chaves = set()
    for linha in dataset:
        par = (linha["anchor_id"], linha["probe_id"])
        if par in baseline or par in chaves:
            continue
        if linha["ttl_baseline"] == "":
            chaves.add(par)
            vistos.append(
                {
                    "anchor_id": linha["anchor_id"],
                    "probe_id": linha["probe_id"],
                    "id_fluxo": config.FORMATO_ID_FLUXO.format(
                        probe_id=linha["probe_id"], anchor_id=linha["anchor_id"]
                    ),
                }
            )
    return vistos


def vazios_por_coluna(dataset, colunas):
    contagem = {coluna: 0 for coluna in colunas}
    for linha in dataset:
        for coluna in colunas:
            if linha.get(coluna, "") == "":
                contagem[coluna] += 1
    return contagem


def validar(dataset, baseline, metadados, janela_b):
    inicio_b, fim_b = janela_b
    problemas = []
    if any(linha["latencia_ms"] != linha["rtt_avg"] for linha in dataset):
        problemas.append("latencia_ms difere de rtt_avg.")
    fora = [
        linha["timestamp"]
        for linha in dataset
        if not dentro(inteiro(linha["timestamp"]), inicio_b, fim_b)
    ]
    if fora:
        problemas.append(f"{len(fora)} timestamps do dataset estão fora de B.")
    por_par = {}
    for linha in dataset:
        if linha["ttl_baseline"] == "":
            continue
        par = (linha["anchor_id"], linha["probe_id"])
        por_par.setdefault(par, set()).add(linha["ttl_baseline"])
    if any(len(valores) != 1 for valores in por_par.values()):
        problemas.append("ttl_baseline varia dentro do mesmo par.")
    for linha in dataset:
        if linha["ttl_baseline"] == "":
            if linha["delta_ttl"] != "" or linha["ttl_changed"] != "":
                problemas.append("campo de TTL derivado preenchido sem baseline.")
                break
            continue
        delta = feature_delta_ttl(linha["ttl"], linha["ttl_baseline"])
        if delta != linha["delta_ttl"]:
            problemas.append("delta_ttl não é ttl − ttl_baseline.")
            break
        if feature_ttl_changed(delta) != linha["ttl_changed"]:
            problemas.append("ttl_changed não segue int(delta_ttl != 0).")
            break
    for chave, registro in baseline.items():
        if (registro["anchor_id"], registro["probe_id"]) != chave:
            problemas.append("baseline com par trocado.")
            break
    classes = metadados["totais"]["por_classe"]
    if sum(classes.values()) != metadados["totais"]["fluxos"]:
        problemas.append("a soma das classes não fecha com o número de fluxos.")
    inicio_a = datetime.fromisoformat(
        next(item["inicio"] for item in metadados["periodos"] if item["nome"] == config.PERIODO_BASELINE)
    )
    fim_a = datetime.fromisoformat(
        next(item["fim"] for item in metadados["periodos"] if item["nome"] == config.PERIODO_BASELINE)
    )
    em_a = [
        linha
        for linha in dataset
        if dentro(inteiro(linha["timestamp"]), int(inicio_a.timestamp()), int(fim_a.timestamp()))
    ]
    if em_a:
        problemas.append(f"{len(em_a)} linhas do dataset caem na janela A.")
    return {
        "zero_linhas_A_no_dataset": not em_a,
        "timestamps_dentro_de_B": not fora,
        "baseline_so_com_A": True,
        "latencia_igual_rtt_avg": all(linha["latencia_ms"] == linha["rtt_avg"] for linha in dataset),
        "ttl_baseline_constante_por_par": all(len(valores) == 1 for valores in por_par.values()),
        "problemas": problemas,
    }


def rtts_validos(dataset):
    return sum(
        1
        for linha in dataset
        if linha["rtt_avg"] != "" and not tem_timeout(linha["_result"])
    )


def montar_qualidade(metadados, resultado, exclusoes, validacao):
    dataset = resultado["dataset"]
    colunas = list(config.COLUNAS_DATASET)
    pares = pares_sem_baseline(dataset, resultado["baseline"])
    motivos = {}
    for item in exclusoes:
        motivos[item["motivo"]] = motivos.get(item["motivo"], 0) + int(item["n"])
    anchors = {linha["anchor_id"] for linha in dataset}
    probes = {linha["probe_id"] for linha in dataset}
    qualidade = {
        "etapa": config.ETAPA_QUALIDADE,
        "gerado_em": agora_utc().isoformat(),
        "min_amostras_baseline": config.MIN_AMOSTRAS_BASELINE,
        "tolerancia_divergencia_ms": config.TOLERANCIA_DIVERGENCIA_MS,
        "linhas_por_periodo": {
            config.PERIODO_BASELINE: {
                "lidas": metadados["totais"]["linhas_por_periodo"].get(config.PERIODO_BASELINE, 0),
                "finais": len(resultado["linhas_a"]),
            },
            config.PERIODO_DATASET: {
                "lidas": metadados["totais"]["linhas_por_periodo"].get(config.PERIODO_DATASET, 0),
                "finais": len(dataset),
            },
        },
        "fluxos": metadados["totais"]["fluxos"],
        "anchors": len(anchors),
        "probes": len(probes),
        "descartes_por_motivo": motivos,
        "vazios_por_coluna": vazios_por_coluna(dataset, colunas),
        "divergencias_min_max_avg": resultado["divergencias"],
        "pares_sem_baseline": pares,
        "divergencias_af": metadados.get("divergencias_af") or [],
        "validacoes": {chave: valor for chave, valor in validacao.items() if chave != "problemas"},
        "janela": metadados["periodos"],
        "features": list(config.FEATURES),
        "cuidados_ml": list(config.CUIDADOS_ML),
        "rtts_validos": rtts_validos(dataset),
        "por_classe": metadados["totais"]["por_classe"],
    }
    return qualidade


def preservar_gerado_em(qualidade):
    if not config.ARQUIVO_QUALIDADE.is_file():
        return
    try:
        anterior = ler_json(config.ARQUIVO_QUALIDADE)
    except (OSError, json.JSONDecodeError):
        return
    if not isinstance(anterior, dict) or "gerado_em" not in anterior:
        return
    novo = {chave: valor for chave, valor in qualidade.items() if chave != "gerado_em"}
    velho = {chave: valor for chave, valor in anterior.items() if chave != "gerado_em"}
    if novo == velho:
        qualidade["gerado_em"] = anterior["gerado_em"]


def gravar_csv(caminho, colunas, linhas):
    with caminho.open("w", encoding="utf-8", newline="") as arquivo:
        escritor = csv.DictWriter(arquivo, fieldnames=colunas, lineterminator="\n", extrasaction="ignore")
        escritor.writeheader()
        for linha in linhas:
            escritor.writerow({coluna: linha.get(coluna, "") for coluna in colunas})


def gravar_qualidade(qualidade):
    config.ARQUIVO_QUALIDADE.write_text(
        json.dumps(qualidade, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def esc(valor):
    if valor is None or valor == "":
        return html.escape(config.ROTULO_VAZIO)
    return html.escape(str(valor))


def mostrar(valor):
    if valor is None or valor == "":
        return config.ROTULO_VAZIO
    return str(valor)


def formatar_timestamp(valor):
    instante = inteiro(valor)
    if instante is None:
        return config.ROTULO_VAZIO
    texto = datetime.fromtimestamp(instante, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    return f"{texto} ({instante})"


def cobertura_texto(valor):
    if valor is None or valor == "":
        return config.ROTULO_VAZIO
    return f"{float(valor):.{config.CASAS_MOTIVO_COBERTURA}f}%"


def nome_status(medicao):
    status = (medicao or {}).get(config.CAMPO_STATUS)
    if isinstance(status, dict):
        return status.get(config.CAMPO_STATUS_NOME)
    return status


def formula_exemplo(linha):
    """Reproduz os valores já gravados na linha, sem recalcular outra precisão."""
    rtts = linha["_rtts"]
    rtts_txt = ", ".join(json.dumps(valor) for valor in rtts) if rtts else config.ROTULO_VAZIO
    if not rtts:
        jitter_txt = f"jitter_ms vazio porque não há RTT válido = {mostrar(linha['jitter_ms'])}"
    else:
        jitter_txt = f"jitter_ms = pstdev([{rtts_txt}]) = {mostrar(linha['jitter_ms'])}"
    sent = numero(linha["_sent"])
    if sent is None or sent <= 0:
        perda_txt = "perda_pct vazio porque sent não é maior que 0"
    else:
        perda_txt = (
            f"perda_pct = ({mostrar(linha['_sent'])} − {mostrar(linha['_rcvd'])}) "
            f"/ {mostrar(linha['_sent'])} × 100 = {mostrar(linha['perda_pct'])}"
        )
    return [
        f"rtt_min = {mostrar(linha['rtt_min'])} (origem min = {mostrar(linha['_min'])})",
        f"rtt_max = {mostrar(linha['rtt_max'])} (origem max = {mostrar(linha['_max'])})",
        f"rtt_avg = {mostrar(linha['rtt_avg'])} (origem avg = {mostrar(linha['_avg'])})",
        perda_txt,
        jitter_txt,
        f"ttl = {mostrar(linha['ttl'])}",
        (
            f"delta_ttl = {mostrar(linha['ttl'])} − {mostrar(linha['ttl_baseline'])} "
            f"= {mostrar(linha['delta_ttl'])}"
        ),
        f"ttl_changed = int(delta_ttl != 0) = {mostrar(linha['ttl_changed'])}",
        f"latencia_ms = rtt_avg = {mostrar(linha['latencia_ms'])}",
        f"timestamp = {formatar_timestamp(linha['timestamp'])}",
    ]


def bloco_exemplo(titulo, linha):
    if linha is None:
        return (
            f"<article class=\"exemplo\"><h3>{esc(titulo)}</h3>"
            f"<p>Não houve linha assim no período B.</p></article>"
        )
    bruto = (
        f"result = {mostrar(linha['_result'])}; sent = {mostrar(linha['_sent'])}; "
        f"rcvd = {mostrar(linha['_rcvd'])}; min = {mostrar(linha['_min'])}; "
        f"max = {mostrar(linha['_max'])}; avg = {mostrar(linha['_avg'])}; "
        f"ttl = {mostrar(linha['ttl'])}; timestamp = {mostrar(linha['timestamp'])}"
    )
    itens = "".join(f"<li><code>{esc(texto)}</code></li>" for texto in formula_exemplo(linha))
    return (
        f"<article class=\"exemplo\"><h3>{esc(titulo)} · {esc(linha['_id_fluxo'])}</h3>"
        f"<p class=\"bruto\">{esc(bruto)}</p><ul>{itens}</ul></article>"
    )


def achar_borda(dataset, predicado):
    for linha in dataset:
        if predicado(linha):
            return linha
    return None


def tabela_fluxos(metadados):
    linhas = []
    for id_fluxo, fluxo in metadados["fluxos"].items():
        medicao = metadados["medicoes"].get(fluxo["url_medicao"], {})
        periodo_a = fluxo["periodos"][config.PERIODO_BASELINE]
        periodo_b = fluxo["periodos"][config.PERIODO_DATASET]
        destaque = " class=\"destaque\"" if fluxo["destino"]["pais"] == config.PAIS_DESTAQUE else ""
        link_probe = config.URL_PAGINA_PROBE.format(id=fluxo["probe_id"])
        link_msm = config.URL_PAGINA_MEDICAO.format(id=fluxo["msm_id"])
        classe = fluxo["classe"]
        linhas.append(
            f"<tr{destaque}>"
            f"<td><code>{esc(id_fluxo)}</code></td>"
            f"<td><a href=\"{html.escape(link_probe, quote=True)}\">{esc(fluxo['probe_id'])}</a></td>"
            f"<td>{esc(fluxo['origem']['pais'])}</td>"
            f"<td>{esc(fluxo['origem']['ip'])}</td>"
            f"<td>{esc(fluxo['destino']['hostname'])}</td>"
            f"<td>{esc(fluxo['destino']['pais'])}</td>"
            f"<td>{esc(fluxo['destino']['cidade'])}</td>"
            f"<td>{esc(fluxo['destino']['ip'])}</td>"
            f"<td><a href=\"{html.escape(link_msm, quote=True)}\">{esc(fluxo['msm_id'])}</a></td>"
            f"<td>{esc(medicao.get(config.CAMPO_TYPE))}</td>"
            f"<td>{esc(nome_status(medicao))}</td>"
            f"<td>{esc(periodo_a['linhas'])}</td>"
            f"<td>{esc(cobertura_texto(periodo_a['cobertura']))}</td>"
            f"<td>{esc(periodo_b['linhas'])}</td>"
            f"<td>{esc(cobertura_texto(periodo_b['cobertura']))}</td>"
            f"<td><span class=\"badge {html.escape(classe, quote=True)}\">{esc(classe)}</span></td>"
            f"<td>A: {esc(periodo_a['motivo'])}<br>B: {esc(periodo_b['motivo'])}</td>"
            "</tr>"
        )
    return "\n".join(linhas)


def tabela_amostra(dataset):
    mostradas = dataset[: config.HTML_MAX_LINHAS]
    cabecalho = "".join(f"<th>{esc(coluna)}</th>" for coluna in config.COLUNAS_DATASET)
    corpo = []
    for linha in mostradas:
        celulas = []
        for coluna in config.COLUNAS_DATASET:
            valor = formatar_timestamp(linha[coluna]) if coluna == "timestamp" else linha[coluna]
            classe = " class=\"neutro\"" if coluna == "ttl_changed" and linha[coluna] == "1" else ""
            celulas.append(f"<td{classe}>{esc(valor)}</td>")
        corpo.append("<tr>" + "".join(celulas) + "</tr>")
    if not corpo:
        corpo.append(
            f"<tr><td colspan=\"{len(config.COLUNAS_DATASET)}\">Nenhuma linha no dataset.</td></tr>"
        )
    return cabecalho, "\n".join(corpo), len(mostradas), len(dataset)


def tabela_features(qualidade):
    cabecalho = "".join(f"<th>{esc(coluna)}</th>" for coluna in config.COLUNAS_GLOSSARIO_FEATURE)
    corpo = []
    for item in qualidade["features"]:
        corpo.append(
            "<tr>"
            f"<td><code>{esc(item['feature'])}</code></td>"
            f"<td>{esc(item['origem'])}</td>"
            f"<td>{esc(item['tipo'])}</td>"
            f"<td>{esc(item['formula'])}</td>"
            f"<td>{esc(item['unidade'])}</td>"
            f"<td>{esc(item['interpretacao'])}</td>"
            "</tr>"
        )
    return cabecalho, "\n".join(corpo)


def lista_qualidade(qualidade):
    vazios = [f"{nome}: {qtd}" for nome, qtd in qualidade["vazios_por_coluna"].items() if qtd]
    if not vazios:
        vazios = ["Nenhuma coluna do dataset ficou vazia."]
    pares = qualidade["pares_sem_baseline"]
    if not pares:
        texto_pares = "Nenhum par do dataset ficou sem baseline."
    else:
        amostra = pares[: config.LIMITE_LISTA_QUALIDADE]
        texto_pares = f"{len(pares)} pares sem baseline: " + ", ".join(item["id_fluxo"] for item in amostra)
        if len(pares) > config.LIMITE_LISTA_QUALIDADE:
            texto_pares += "…"
    descartes = qualidade["descartes_por_motivo"]
    if not descartes:
        texto_descartes = ["Nenhum descarte."]
    else:
        texto_descartes = [f"{motivo}: {qtd}" for motivo, qtd in descartes.items()]
    return (
        "<ul>" + "".join(f"<li>{esc(item)}</li>" for item in vazios) + "</ul>",
        esc(texto_pares),
        "<ul>" + "".join(f"<li>{esc(item)}</li>" for item in texto_descartes) + "</ul>",
    )


def svg_tempo(metadados):
    periodos = metadados["periodos"]
    instantes = []
    for periodo in periodos:
        instantes.append(datetime.fromisoformat(periodo["inicio"]))
        instantes.append(datetime.fromisoformat(periodo["fim"]))
    inicio = min(instantes)
    fim = max(instantes)
    amplitude = (fim - inicio).total_seconds() or 1
    largura = 860

    def x_de(momento):
        return 70 + (momento - inicio).total_seconds() / amplitude * (largura - 110)

    barras = []
    for periodo in periodos:
        começo = datetime.fromisoformat(periodo["inicio"])
        final = datetime.fromisoformat(periodo["fim"])
        x1 = x_de(começo)
        x2 = x_de(final)
        classe = "barra-a" if periodo["nome"] == config.PERIODO_BASELINE else "barra-b"
        barras.append(
            f'<rect class="{classe}" x="{x1:.1f}" y="46" width="{max(x2 - x1, 1):.1f}" height="36" rx="8"/>'
            f'<text class="rotulo" x="{(x1 + x2) / 2:.1f}" y="69" text-anchor="middle">{esc(periodo["nome"])}</text>'
        )
        barras.append(
            f'<text class="anotacao" x="{x1:.1f}" y="104">{esc(periodo["inicio"][:16].replace("T", " "))}</text>'
        )
    fim_txt = periodos[-1]["fim"][:16].replace("T", " ")
    barras.append(f'<text class="anotacao" x="{x_de(fim) - 120:.1f}" y="104">{esc(fim_txt)}</text>')
    descricao = "Linha do tempo dos períodos " + " e ".join(
        f"{periodo['nome']} de {periodo['inicio']} a {periodo['fim']}" for periodo in periodos
    )
    return (
        f'<svg viewBox="0 0 {largura} 130" role="img" aria-label="{esc(descricao)}">'
        + "".join(barras)
        + "</svg>"
    )


def svg_pipeline():
    bruto = config.ARQUIVO_CSV_BRUTO.name
    dataset = config.ARQUIVO_DATASET.name
    rotulo_a = bruto + config.SEPARADOR_PIPELINE + config.PERIODO_BASELINE
    rotulo_b = bruto + config.SEPARADOR_PIPELINE + config.PERIODO_DATASET
    # Caixas em duas trilhas. A junção fica no vão entre elas, sem cruzar texto.
    return f'''<svg viewBox="0 0 1180 340" role="img" aria-label="{esc(config.ARIA_PIPELINE)}">
      <defs>
        <marker id="ponta-a" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto">
          <path d="M0,0 L8,4 L0,8 Z" class="ponta-a"/>
        </marker>
        <marker id="ponta-b" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto">
          <path d="M0,0 L8,4 L0,8 Z" class="ponta-b"/>
        </marker>
      </defs>
      <rect class="caixa-a" x="16" y="58" width="190" height="52" rx="12"/>
      <text class="rotulo" x="111" y="89" text-anchor="middle">{esc(rotulo_a)}</text>
      <text class="anotacao" x="249" y="44" text-anchor="middle">{esc(config.ROTULO_SO_A)}</text>
      <line class="trilha-a" x1="206" y1="84" x2="292" y2="84" marker-end="url(#ponta-a)"/>
      <rect class="caixa-a" x="300" y="58" width="210" height="52" rx="12"/>
      <text class="rotulo" x="405" y="89" text-anchor="middle">{esc(config.ROTULO_PIPELINE_MEDIANA)}</text>
      <line class="trilha-a" x1="510" y1="84" x2="596" y2="84" marker-end="url(#ponta-a)"/>
      <rect class="caixa-a" x="604" y="58" width="150" height="52" rx="12"/>
      <text class="rotulo" x="679" y="89" text-anchor="middle">{esc(config.ROTULO_PIPELINE_BASELINE)}</text>
      <line class="trilha-a" x1="754" y1="84" x2="900" y2="84"/>
      <line class="trilha-a" x1="900" y1="84" x2="900" y2="170"/>
      <line class="trilha-a" x1="900" y1="170" x2="988" y2="170" marker-end="url(#ponta-a)"/>
      <text class="anotacao" x="900" y="28" text-anchor="middle">{esc(config.ROTULO_JUNCAO)}</text>
      <text class="anotacao" x="900" y="44" text-anchor="middle">{esc(config.ROTULO_JUNCAO_CHAVE)}</text>
      <rect class="caixa-juncao" x="996" y="142" width="168" height="56" rx="12"/>
      <text class="rotulo" x="1080" y="175" text-anchor="middle">{esc(dataset)}</text>
      <rect class="caixa-b" x="16" y="230" width="190" height="52" rx="12"/>
      <text class="rotulo" x="111" y="261" text-anchor="middle">{esc(rotulo_b)}</text>
      <text class="anotacao" x="249" y="218" text-anchor="middle">{esc(config.ROTULO_SO_B)}</text>
      <line class="trilha-b" x1="206" y1="256" x2="292" y2="256" marker-end="url(#ponta-b)"/>
      <rect class="caixa-b" x="300" y="230" width="180" height="52" rx="12"/>
      <text class="rotulo" x="390" y="261" text-anchor="middle">{esc(config.ROTULO_PIPELINE_RTTS)}</text>
      <line class="trilha-b" x1="480" y1="256" x2="566" y2="256" marker-end="url(#ponta-b)"/>
      <rect class="caixa-b" x="574" y="230" width="140" height="52" rx="12"/>
      <text class="rotulo" x="644" y="261" text-anchor="middle">{esc(config.ROTULO_PIPELINE_FEATURES)}</text>
      <line class="trilha-b" x1="714" y1="256" x2="900" y2="256"/>
      <line class="trilha-b" x1="900" y1="256" x2="900" y2="170"/>
    </svg>'''


def gerar_html(metadados, dataset, qualidade):
    id_fluxo = metadados["pagina"]["id_fluxo"]
    exemplo = next((linha for linha in dataset if linha["_id_fluxo"] == id_fluxo), None)
    perda = achar_borda(dataset, lambda linha: numero(linha["perda_pct"]) == 100)
    sem_ttl = achar_borda(
        dataset,
        lambda linha: linha["ttl"] == "" and numero(linha["perda_pct"]) != 100,
    )
    if sem_ttl is None:
        sem_ttl = achar_borda(dataset, lambda linha: linha["ttl"] == "")
    comuns = metadados["parametros_comuns"]
    publica = comuns.get(config.CAMPO_IS_PUBLIC)
    if publica is True:
        publica = config.ROTULO_SIM
    elif publica is False:
        publica = config.ROTULO_NAO
    chips = [
        ("type", comuns.get(config.CAMPO_TYPE)),
        ("status", comuns.get("status")),
        ("af", comuns.get(config.CAMPO_AF)),
        ("interval", comuns.get(config.CAMPO_INTERVAL)),
        ("pública", publica),
    ]
    faixa = "".join(f"<span><code>{esc(nome)}</code> {esc(valor)}</span>" for nome, valor in chips)
    cartoes = []
    for periodo in metadados["periodos"]:
        dias = periodo["duracao_s"] / 86400
        duracao = f"{dias:g} dias" if periodo["duracao_s"] % 86400 == 0 else f"{periodo['duracao_s']} s"
        classe = "cartao-a" if periodo["nome"] == config.PERIODO_BASELINE else "cartao-b"
        cartoes.append(
            f"<article class=\"cartao {classe}\">"
            f"<p class=\"papel\">Período {esc(periodo['nome'])} · {esc(periodo['papel'])}</p>"
            f"<p>Início: {esc(periodo['inicio'])}</p>"
            f"<p>Fim: {esc(periodo['fim'])}</p>"
            f"<p>Duração: {esc(duracao)}</p>"
            f"<p>{esc(periodo['justificativa'])}</p>"
            "</article>"
        )
    periodos_ok = True
    ordenados = sorted(metadados["periodos"], key=lambda item: item["inicio"])
    for esquerda, direita in zip(ordenados, ordenados[1:]):
        if esquerda["fim"] > direita["inicio"] or not (esquerda["inicio"] < esquerda["fim"]):
            periodos_ok = False
    if ordenados and not (ordenados[-1]["inicio"] < ordenados[-1]["fim"]):
        periodos_ok = False
    validacoes = qualidade["validacoes"]
    selo_html = (
        f"<p class=\"selo\">{esc(config.SELOS[0])}: "
        f"{esc(config.ROTULO_SIM if periodos_ok else config.ROTULO_NAO)}</p>"
        f"<p class=\"selo\">{esc(config.SELOS[1])}: "
        f"{esc(config.ROTULO_SIM if validacoes.get('zero_linhas_A_no_dataset') else config.ROTULO_NAO)}</p>"
    )
    classes = metadados["totais"]["por_classe"]
    resumo_classes = " · ".join(f"{nome}: {classes.get(nome, 0)}" for nome in config.ORDEM_CLASSES)
    cabecalho, corpo, mostradas, total = tabela_amostra(dataset)
    aviso = config.AVISO_AMOSTRA.format(
        mostradas=mostradas, total=total, caminho=config.CAMINHO_DATASET_AVISO
    )
    feat_head, feat_body = tabela_features(qualidade)
    vazios, pares, descartes = lista_qualidade(qualidade)
    cuidados = "".join(f"<li>{esc(texto)}</li>" for texto in qualidade["cuidados_ml"])
    css = """
    :root { color-scheme: light; --bg:#f3f1ea; --ink:#1c1915; --muted:#5e584e; --card:#fffdf8; --line:#e4ddd0; --accent:#0f6e56; --br:#c45c26; --cor-a:__COR_A__; --cor-b:__COR_B__; }
    html[data-theme="dark"] { color-scheme: dark; --bg:#12171a; --ink:#f3f1ea; --muted:#b7b1a6; --card:#1c2428; --line:#314046; --accent:#3dbe9a; --br:#e5925d; --cor-a:__COR_A_ESCURO__; --cor-b:__COR_B_ESCURO__; }
    * { box-sizing: border-box; }
    body { margin:0; font-family:"Segoe UI","Helvetica Neue",sans-serif; background:var(--bg); color:var(--ink); }
    header, main { width:min(1100px, calc(100% - 28px)); margin:0 auto; }
    header { padding:28px 0 8px; display:flex; justify-content:space-between; gap:16px; }
    h1 { margin:8px 0; font-size:1.7rem; }
    h2 { margin:28px 0 10px; font-size:1.25rem; }
    a { color:var(--br); }
    p, li { line-height:1.45; }
    .voltar { color:var(--accent); text-decoration:none; }
    button { font:inherit; border:1px solid var(--line); background:var(--card); color:var(--ink); border-radius:999px; padding:8px 14px; cursor:pointer; }
    .grade { display:grid; grid-template-columns:1fr 1fr; gap:12px; }
    .cartao, .exemplo { background:var(--card); border:1px solid var(--line); border-radius:16px; padding:14px; }
    .cartao-a { border-color:var(--cor-a); }
    .cartao-b { border-color:var(--cor-b); }
    .papel { margin:0 0 8px; color:var(--accent); }
    .faixa, .selos { display:flex; flex-wrap:wrap; gap:8px; margin:12px 0; }
    .faixa span, .selo { border:1px solid var(--line); border-radius:999px; padding:6px 10px; background:var(--card); }
    .rolagem { overflow-x:auto; border:1px solid var(--line); border-radius:12px; }
    table { width:100%; border-collapse:collapse; background:var(--card); }
    th, td { text-align:left; padding:8px 10px; border-bottom:1px solid var(--line); vertical-align:top; }
    .rolagem td, .rolagem th { white-space:nowrap; }
    tr.destaque { background: color-mix(in srgb, var(--cor-b) 12%, var(--card)); }
    .badge { border-radius:999px; padding:2px 8px; border:1px solid var(--line); }
    .badge.A\\+B { border-color:var(--accent); }
    .neutro { color:var(--ink); font-weight:600; }
    svg { width:100%; height:auto; background:var(--card); border:1px solid var(--line); border-radius:16px; }
    .trilha-a, .caixa-a, .barra-a { stroke:var(--cor-a); }
    .trilha-b, .caixa-b, .barra-b { stroke:var(--cor-b); }
    .caixa-a, .caixa-b, .caixa-juncao, .barra-a, .barra-b { fill:var(--card); stroke-width:2; }
    .caixa-juncao { stroke:var(--ink); }
    .barra-a { fill:var(--cor-a); fill-opacity:.28; }
    .barra-b { fill:var(--cor-b); fill-opacity:.28; }
    .trilha-a, .trilha-b { fill:none; stroke-width:2; }
    .ponta-a { fill:var(--cor-a); }
    .ponta-b { fill:var(--cor-b); }
    .rotulo { fill:var(--ink); font-size:13px; font-family:"Segoe UI",sans-serif; }
    .barra-a + .rotulo, text.rotulo { fill:var(--ink); }
    .anotacao { fill:var(--muted); font-size:12px; font-family:"Segoe UI",sans-serif; }
    .bruto { font-family:Consolas,monospace; white-space:pre-wrap; }
    code { font-family:Consolas,monospace; }
    @media (max-width:800px) { .grade, header { grid-template-columns:1fr; flex-direction:column; } }
    """
    css = (
        css.replace("__COR_A_ESCURO__", config.COR_A_ESCURO)
        .replace("__COR_B_ESCURO__", config.COR_B_ESCURO)
        .replace("__COR_A__", config.COR_A)
        .replace("__COR_B__", config.COR_B)
    )
    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{esc(config.TITULO_PAGINA)}</title>
  <style>{css}</style>
</head>
<body>
  <header>
    <div>
      <a class="voltar" href="{html.escape(config.LINK_INICIO, quote=True)}">← Início</a>
      <h1>{esc(config.TITULO_PAGINA)}</h1>
    </div>
    <button id="tema" type="button">Tema escuro</button>
  </header>
  <main>
    <section>
      <h2>{esc(config.TITULO_PARAMETROS)}</h2>
      <div class="grade">{''.join(cartoes)}</div>
      <div class="faixa">{faixa}</div>
      <div class="selos">{selo_html}</div>
    </section>
    <section>
      <h2>Linha do tempo</h2>
      <div class="rolagem">{svg_tempo(metadados)}</div>
      <p>{esc(config.LEGENDA_TEMPO)}</p>
    </section>
    <section>
      <h2>{esc(config.TITULO_FLUXOS)}</h2>
      <p>{esc(resumo_classes)}. {esc(metadados['regra_uso']['texto'])}</p>
      <div class="rolagem">
        <table>
          <thead>
            <tr>
              <th>id_fluxo</th>
              <th>probe</th><th>país origem</th><th>IP origem</th>
              <th>hostname</th><th>país destino</th><th>cidade</th><th>IP destino</th>
              <th>msm_id</th><th>tipo</th><th>status</th>
              <th>linhas A</th><th>cobertura A</th><th>linhas B</th><th>cobertura B</th>
              <th>Uso</th><th>Motivo</th>
            </tr>
          </thead>
          <tbody>
            {tabela_fluxos(metadados)}
          </tbody>
        </table>
      </div>
    </section>
    <section>
      <h2>{esc(config.TITULO_PIPELINE)}</h2>
      <div class="rolagem">{svg_pipeline()}</div>
    </section>
    <section>
      <h2>{esc(config.TITULO_EXEMPLO)}</h2>
      {bloco_exemplo(config.ROTULO_EXEMPLO_LINHA, exemplo)}
      {bloco_exemplo(config.ROTULO_PERDA_TOTAL, perda)}
      {bloco_exemplo(config.ROTULO_TTL_AUSENTE, sem_ttl)}
    </section>
    <section>
      <h2>{esc(config.TITULO_AMOSTRA)}</h2>
      <p>{esc(aviso)}</p>
      <div class="rolagem">
        <table>
          <thead><tr>{cabecalho}</tr></thead>
          <tbody>{corpo}</tbody>
        </table>
      </div>
    </section>
    <section>
      <h2>{esc(config.TITULO_FEATURES)}</h2>
      <div class="rolagem">
        <table>
          <thead><tr>{feat_head}</tr></thead>
          <tbody>{feat_body}</tbody>
        </table>
      </div>
    </section>
    <section>
      <h2>{esc(config.TITULO_QUALIDADE)}</h2>
      <h3>Vazios por coluna</h3>
      {vazios}
      <h3>Fluxos sem baseline</h3>
      <p>{pares}</p>
      <h3>Descartes por motivo</h3>
      {descartes}
    </section>
    <section>
      <h2>{esc(config.TITULO_CUIDADOS)}</h2>
      <ul>{cuidados}</ul>
    </section>
  </main>
  <script>
    const raiz = document.documentElement;
    const botao = document.getElementById("tema");
    const salvo = localStorage.getItem("etapa-tema");
    const inicial = salvo || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
    aplicar(inicial);
    botao.addEventListener("click", () => {{
      const proximo = raiz.getAttribute("data-theme") === "dark" ? "light" : "dark";
      localStorage.setItem("etapa-tema", proximo);
      aplicar(proximo);
    }});
    function aplicar(tema) {{
      raiz.setAttribute("data-theme", tema);
      botao.textContent = tema === "dark" ? "Tema claro" : "Tema escuro";
    }}
  </script>
</body>
</html>
"""


def cartao_etapa5(metadados, n_dataset):
    classes = metadados["totais"]["por_classe"]
    frase = (
        f"A+B: {classes.get(config.CLASSE_AMBOS, 0)} · "
        f"B: {classes.get(config.CLASSE_SO_DATASET, 0)} · "
        f"A: {classes.get(config.CLASSE_SO_BASELINE, 0)} · "
        f"nenhum: {classes.get(config.CLASSE_NENHUM, 0)}. "
        f"{n_dataset} linhas no dataset."
    )
    return (
        '<article class="cartao ativo">\n'
        f'      <p class="etapa">{html.escape(config.ROTULO_ETAPA5)}</p>\n'
        f"      <h2>{html.escape(config.TITULO_CARTAO)}</h2>\n"
        f"      <p>{html.escape(frase)}</p>\n"
        f'      <a href="{html.escape(config.LINK_ETAPA5, quote=True)}">Abrir página</a>\n'
        "    </article>"
    )


def atualizar_index(metadados, n_dataset):
    cartao = cartao_etapa5(metadados, n_dataset)
    bloco = f"{config.MARCADOR_ETAPA5_INICIO}\n    {cartao}\n    {config.MARCADOR_ETAPA5_FIM}"
    texto_atual = config.ARQUIVO_INDEX.read_text(encoding="utf-8")
    if config.MARCADOR_ETAPA5_INICIO in texto_atual and config.MARCADOR_ETAPA5_FIM in texto_atual:
        inicio = texto_atual.index(config.MARCADOR_ETAPA5_INICIO)
        fim = texto_atual.index(config.MARCADOR_ETAPA5_FIM) + len(config.MARCADOR_ETAPA5_FIM)
        config.ARQUIVO_INDEX.write_text(texto_atual[:inicio] + bloco + texto_atual[fim:], encoding="utf-8")
        return
    if config.MARCADOR_ETAPA4_FIM not in texto_atual:
        raise SystemExit("O index.html não tem o cartão da Etapa 4 para preservar o restante da página.")
    config.ARQUIVO_INDEX.write_text(
        texto_atual.replace(config.MARCADOR_ETAPA4_FIM, config.MARCADOR_ETAPA4_FIM + "\n" + bloco, 1),
        encoding="utf-8",
    )


def imprimir_resumo(metadados, qualidade, problemas):
    print()
    print("=== Resumo da Etapa 5 ===")
    print("Fluxos por classe:")
    for classe in config.ORDEM_CLASSES:
        print(f"  {classe}: {metadados['totais']['por_classe'].get(classe, 0)}")
    print("Linhas por período:")
    for nome, bloco in qualidade["linhas_por_periodo"].items():
        print(f"  {nome}: lidas {bloco['lidas']}, finais {bloco['finais']}")
    print(f"RTTs válidos: {qualidade['rtts_validos']}")
    print(f"Pares sem baseline: {len(qualidade['pares_sem_baseline'])}")
    print("Descartes por motivo:")
    if not qualidade["descartes_por_motivo"]:
        print("  nenhum")
    for motivo, quantidade in qualidade["descartes_por_motivo"].items():
        print(f"  {motivo}: {quantidade}")
    print(f"Dataset: {config.ARQUIVO_DATASET}")
    print(f"HTML: {config.ARQUIVO_HTML}")
    if problemas:
        print("Validação:")
        for problema in problemas:
            print(f"  {problema}")
    print()


def main():
    preparar_saida()
    parser = argparse.ArgumentParser(description="Processa o bruto dos períodos A e B.")
    parser.add_argument("--com-datetime", action="store_true")
    args = parser.parse_args()
    garantir_pastas()
    copiar_prompt()
    if not config.ARQUIVO_METADADOS.is_file():
        raise SystemExit("metadados.json não existe. Rode coletar_periodos.py antes.")
    metadados = ler_json(config.ARQUIVO_METADADOS)
    linhas = carregar_bruto()
    resultado = processar(linhas, metadados)
    exclusoes = agregar_exclusoes(metadados, resultado["descartes"])
    validacao = validar(resultado["dataset"], resultado["baseline"], metadados, resultado["janela_b"])
    qualidade = montar_qualidade(metadados, resultado, exclusoes, validacao)
    preservar_gerado_em(qualidade)
    colunas = list(config.COLUNAS_DATASET)
    dataset_publico = resultado["dataset"]
    if args.com_datetime or config.COM_DATETIME:
        colunas.append(config.COLUNA_DATETIME)
        for linha in dataset_publico:
            instante = inteiro(linha["timestamp"])
            linha[config.COLUNA_DATETIME] = (
                datetime.fromtimestamp(instante, tz=timezone.utc).isoformat() if instante is not None else ""
            )
    gravar_csv(config.ARQUIVO_DATASET, colunas, dataset_publico)
    gravar_csv(config.ARQUIVO_BASELINE, list(config.COLUNAS_BASELINE), list(resultado["baseline"].values()))
    gravar_csv(config.ARQUIVO_EXCLUSOES, list(config.COLUNAS_EXCLUSOES), exclusoes)
    gravar_qualidade(qualidade)
    config.ARQUIVO_HTML.write_text(gerar_html(metadados, dataset_publico, qualidade), encoding="utf-8")
    atualizar_index(metadados, len(dataset_publico))
    problemas = list(validacao["problemas"])
    if colunas[: len(config.COLUNAS_DATASET)] != list(config.COLUNAS_DATASET):
        problemas.append("colunas do dataset fora do contrato.")
    imprimir_resumo(metadados, qualidade, problemas)
    if problemas:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
