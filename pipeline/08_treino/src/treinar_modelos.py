"""Etapa 8: compara persistência, Naive Bayes, árvore e floresta.

O teste só é lido com --avaliar-teste. A escolha do modelo usa a validação.
"""

import argparse
import csv
import html
import itertools
import json
import math
import random
import shutil
import sys
import time
from datetime import datetime, timezone

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.naive_bayes import GaussianNB
from sklearn.tree import DecisionTreeClassifier

import config


def configurar_saida():
    """Garante acentos no terminal do Windows."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")


def garantir_pastas():
    """Cria as pastas desta etapa."""
    for pasta in (config.CACHE_DIR, config.PROMPT_DIR, config.DATA_DIR, config.MODELOS_DIR, config.TEMPLATE_DIR):
        pasta.mkdir(parents=True, exist_ok=True)


def copiar_prompt():
    """Copia o enunciado para a pasta da etapa."""
    if not config.ARQUIVO_PROMPT_ORIGEM.is_file():
        raise SystemExit(f"Prompt de origem ausente: {config.ARQUIVO_PROMPT_ORIGEM}")
    shutil.copyfile(config.ARQUIVO_PROMPT_ORIGEM, config.ARQUIVO_PROMPT)


def ler_json(caminho):
    """Lê um JSON da etapa anterior ou desta."""
    if not caminho.is_file():
        raise SystemExit(f"Arquivo ausente: {caminho}")
    return json.loads(caminho.read_text(encoding="utf-8"))


def gravar_json(caminho, documento):
    """Grava JSON estável. A data do relógio só entra na reavaliação forçada do teste."""
    caminho.write_text(json.dumps(para_json(documento), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def para_json(valor):
    """Converte numpy e ausentes para JSON."""
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
    if valor is None or isinstance(valor, (str, int, bool)):
        return valor
    return str(valor)


def numero(valor):
    """Float finito, ou None quando o valor não é um número."""
    if valor is None or isinstance(valor, bool):
        return None
    try:
        saida = float(valor)
    except (TypeError, ValueError):
        return None
    return saida if math.isfinite(saida) else None


def br(valor, casas=None):
    """Número em formato brasileiro. Ausente vira traço."""
    if valor is None:
        return config.ROTULO_VAZIO
    try:
        numero = float(valor)
    except (TypeError, ValueError):
        return config.ROTULO_VAZIO
    if not math.isfinite(numero):
        return config.ROTULO_VAZIO
    casas = config.CASAS_DECIMAIS if casas is None else casas
    return f"{numero:.{casas}f}".replace(".", ",")


def br_pct(valor):
    """Proporção em percentual com uma casa."""
    if valor is None:
        return config.ROTULO_VAZIO
    return br(float(valor) * 100, 1) + "%"


def iso_de_unix(timestamp):
    """Unix em UTC legível."""
    momento = datetime.fromtimestamp(int(timestamp), timezone.utc)
    return momento.strftime(config.FORMATO_DATA_SPLIT)


def parse_data_split(texto):
    """Lê a data já gravada em features.json."""
    return datetime.strptime(texto, config.FORMATO_DATA_SPLIT).replace(tzinfo=timezone.utc)


def ler_tabela(splits):
    """Lê só os splits pedidos. O teste não entra no treino."""
    if not config.ARQUIVO_DATASET_FINAL_ETAPA7.is_file():
        raise SystemExit(f"Dataset final ausente: {config.ARQUIVO_DATASET_FINAL_ETAPA7}")
    partes = []
    for bloco in pd.read_csv(config.ARQUIVO_DATASET_FINAL_ETAPA7, chunksize=100000):
        manter = bloco["split"].isin(splits)
        if manter.any():
            partes.append(bloco.loc[manter])
    if not partes:
        raise SystemExit(config.TEXTO_INSUFICIENTE)
    return pd.concat(partes, ignore_index=True)


def conferir_entrada(quadro, features):
    """Aborta se faltar feature, se houver coluna proibida ou se o número não for finito."""
    faltando = [nome for nome in features if nome not in quadro.columns]
    if faltando:
        raise SystemExit("Features ausentes no dataset final: " + ", ".join(faltando))
    proibidas = [nome for nome in features if nome in config.COLUNAS_PROIBIDAS]
    if proibidas:
        raise SystemExit("Colunas proibidas entre as features: " + ", ".join(proibidas))
    matriz = quadro.loc[:, list(features)].apply(pd.to_numeric, errors="coerce").to_numpy(dtype=np.float64)
    if not np.isfinite(matriz).all():
        raise SystemExit("Há NaN ou inf nas features. O treino não imputa esses valores.")
    alvos = set(quadro["alvo"].astype(str).unique())
    if not alvos <= set(config.CLASSES):
        raise SystemExit(f"Alvo fora de {config.CLASSES}: {sorted(alvos - set(config.CLASSES))}")
    return np.ascontiguousarray(matriz)


def fatia_metricas(y_verdadeiro, y_previsto):
    """Precisão, recall, F1, macro-F1, acurácia e a matriz 3×3.

    Classe ausente fica null e sai da média. Nunca vira zero.
    """
    verdadeiro = np.asarray(y_verdadeiro).astype(str)
    previsto = np.asarray(y_previsto).astype(str)
    por_classe = {}
    f1_presentes = []
    suporte_presentes = []
    matriz = []
    for classe in config.CLASSES:
        eh_real = verdadeiro == classe
        eh_previsto = previsto == classe
        suporte = int(eh_real.sum())
        tp = int((eh_real & eh_previsto).sum())
        fp = int((~eh_real & eh_previsto).sum())
        fn = int((eh_real & ~eh_previsto).sum())
        linha = [int(((verdadeiro == classe) & (previsto == outra)).sum()) for outra in config.CLASSES]
        matriz.append(linha)
        if suporte == 0:
            por_classe[classe] = {"precisao": None, "recall": None, "f1": None, "suporte": 0}
            continue
        precisao = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / suporte
        f1 = 0.0 if precisao + recall == 0 else 2 * precisao * recall / (precisao + recall)
        por_classe[classe] = {"precisao": precisao, "recall": recall, "f1": f1, "suporte": suporte}
        f1_presentes.append(f1)
        suporte_presentes.append(suporte)
    total = int(len(verdadeiro))
    macro = sum(f1_presentes) / len(f1_presentes) if f1_presentes else None
    ponderado = (
        sum(f1 * suporte for f1, suporte in zip(f1_presentes, suporte_presentes)) / sum(suporte_presentes)
        if suporte_presentes
        else None
    )
    acuracia = float((verdadeiro == previsto).mean()) if total else None
    return {
        "n": total,
        "por_classe": por_classe,
        "macro_f1": macro,
        "f1_ponderado": ponderado,
        "acuracia": acuracia,
        "matriz": matriz,
        "recall_falha": por_classe[config.CLASSES[2]]["recall"],
        "f1_falha": por_classe[config.CLASSES[2]]["f1"],
    }


def anchor_dominante(anchor, y_verdadeiro):
    """Anchor com mais linhas FALHA. Empate fica com o menor id."""
    falha = np.asarray(y_verdadeiro).astype(str) == config.CLASSES[2]
    if not falha.any():
        return None, None
    identificadores = np.asarray(anchor).astype(str)[falha]
    valores, contagens = np.unique(identificadores, return_counts=True)
    ordem = sorted(range(len(valores)), key=lambda i: (-int(contagens[i]), valores[i]))
    escolhido = str(valores[ordem[0]])
    fracao = float(contagens[ordem[0]] / falha.sum())
    return escolhido, fracao


def avaliar_fatias(y_verdadeiro, y_previsto, classe_atual, anchor):
    """As quatro fatias e o anchor que concentra as FALHA."""
    verdadeiro = np.asarray(y_verdadeiro).astype(str)
    previsto = np.asarray(y_previsto).astype(str)
    atual = np.asarray(classe_atual).astype(str)
    anchors = np.asarray(anchor).astype(str)
    saida = {"geral": fatia_metricas(verdadeiro, previsto)}
    transicao = atual != verdadeiro
    saida["transicoes"] = fatia_metricas(verdadeiro[transicao], previsto[transicao]) if transicao.any() else fatia_metricas([], [])
    inicio = (atual != config.CLASSES[2]) & (verdadeiro == config.CLASSES[2])
    saida["inicio_falha"] = fatia_metricas(verdadeiro[inicio], previsto[inicio]) if inicio.any() else fatia_metricas([], [])
    dominante, fracao = anchor_dominante(anchors, verdadeiro)
    if dominante is None:
        saida["sem_anchor_dominante"] = fatia_metricas(verdadeiro, previsto)
    else:
        fora = anchors != dominante
        saida["sem_anchor_dominante"] = fatia_metricas(verdadeiro[fora], previsto[fora])
    saida["anchor_dominante"] = {"anchor_id": dominante, "fracao_falha_anchor_dominante": fracao}
    return saida


def ganho(modelo, persistencia, fatia):
    """Diferença de macro-F1. Em transições a persistência é zero por construção."""
    if fatia == "transicoes":
        return None
    esquerda = modelo[fatia]["macro_f1"]
    direita = persistencia[fatia]["macro_f1"]
    if esquerda is None or direita is None:
        return None
    return esquerda - direita


def texto_hiperparametros(params):
    """Texto estável da grade, na ordem em que os parâmetros foram definidos."""
    partes = []
    for chave, valor in params.items():
        if valor is None and chave == "max_depth":
            mostrado = config.ROTULO_SEM_LIMITE
        elif valor is None:
            mostrado = config.ROTULO_NENHUM
        else:
            mostrado = valor
        partes.append(f"{chave}={mostrado}")
    return ";".join(partes)


def criar_modelo(familia, params):
    """Instancia o algoritmo com a semente fixa. O Naive Bayes não tem class_weight."""
    if familia == "naive_bayes":
        return GaussianNB(var_smoothing=params["var_smoothing"])
    if familia == "arvore_decisao":
        return DecisionTreeClassifier(
            max_depth=params["max_depth"],
            min_samples_leaf=params["min_samples_leaf"],
            class_weight=params["class_weight"],
            random_state=config.SEED,
        )
    return RandomForestClassifier(
        n_estimators=params["n_estimators"],
        max_depth=params["max_depth"],
        min_samples_leaf=params["min_samples_leaf"],
        max_features=params["max_features"],
        class_weight=params["class_weight"],
        random_state=config.SEED,
        n_jobs=config.N_JOBS,
    )


def candidatos_da_grade(familia):
    """Produto cartesiano da grade, do mais simples ao mais complexo na ordem do config."""
    grade = config.GRADES[familia]
    chaves = list(grade)
    for ordem, combinacao in enumerate(itertools.product(*(grade[chave] for chave in chaves))):
        yield ordem, dict(zip(chaves, combinacao))


def chave_desempate(item):
    """Maior macro-F1, depois menor gap, depois o modelo mais simples."""
    params = item["params"]
    profundidade = params.get("max_depth", 0)
    if profundidade is None:
        profundidade = config.PROFUNDIDADE_COMPLEXA
    arvores = int(params.get("n_estimators", 0))
    return (
        -item["macro_f1_validacao"],
        item["gap"],
        config.ALGORITMOS.index(item["familia"]),
        profundidade,
        arvores,
        item["ordem"],
    )


def treinar_familia(familia, x_treino, y_treino, x_val, y_val, atual_val, anchor_val):
    """Treina cada candidato e devolve a grade e o melhor pela validação."""
    registros = []
    melhor = None
    inicio = time.perf_counter()
    for ordem, params in candidatos_da_grade(familia):
        modelo = criar_modelo(familia, params)
        modelo.fit(x_treino, y_treino)
        pred_treino = modelo.predict(x_treino)
        pred_val = modelo.predict(x_val)
        metricas_treino = fatia_metricas(y_treino, pred_treino)
        metricas_val = avaliar_fatias(y_val, pred_val, atual_val, anchor_val)
        macro_treino = metricas_treino["macro_f1"]
        macro_val = metricas_val["geral"]["macro_f1"]
        item = {
            "familia": familia,
            "ordem": ordem,
            "params": params,
            "hiperparametros": texto_hiperparametros(params),
            "macro_f1_treino": macro_treino,
            "macro_f1_validacao": macro_val,
            "gap": macro_treino - macro_val,
            "f1_falha_validacao": metricas_val["geral"]["f1_falha"],
            "recall_falha_validacao": metricas_val["geral"]["recall_falha"],
            "validacao": metricas_val,
        }
        registros.append(item)
        if melhor is None or chave_desempate(item) < chave_desempate(melhor):
            melhor = {**item, "modelo": modelo}
        print(f"  {familia} {item['hiperparametros']} val={macro_val:.4f} gap={item['gap']:.4f}")
    melhor["tempo_s"] = time.perf_counter() - inicio
    return registros, melhor


def rotulos_ramos(feature, limiar):
    """Esquerda é sim (feature <= limiar). Sentinela quando o corte separa o -1."""
    if feature in config.FEATURES_DEPENDENTES_RTT and limiar is not None and limiar < 0:
        return config.ROTULO_SENTINELA, config.ROTULO_NAO
    return config.ROTULO_SIM, config.ROTULO_NAO


def classe_majoritaria(contagem):
    """A classe com mais linhas reais. Empate fica com a primeira de OK, RISCO, FALHA."""
    melhor = config.CLASSES[0]
    maior = -1
    for classe in config.CLASSES:
        if contagem[classe] > maior:
            maior = contagem[classe]
            melhor = classe
    return melhor


def extrair_nos(modelo, x_treino, y_treino, features, niveis=None):
    """Conta classes reais em cada nó. Não usa tree_.value nas barras."""
    arvore = modelo.tree_
    indicador = modelo.decision_path(x_treino)
    contagens = {}
    for classe in config.CLASSES:
        mascara = np.asarray(y_treino).astype(str) == classe
        if mascara.any():
            contagens[classe] = np.asarray(indicador[mascara].sum(axis=0)).ravel().astype(int)
        else:
            contagens[classe] = np.zeros(arvore.node_count, dtype=int)
    amostras = np.zeros(arvore.node_count, dtype=int)
    for classe in config.CLASSES:
        amostras += contagens[classe]
    profundidade = np.zeros(arvore.node_count, dtype=int)
    pilha = [(0, 0)]
    while pilha:
        no, nivel = pilha.pop()
        profundidade[no] = nivel
        esquerda = int(arvore.children_left[no])
        direita = int(arvore.children_right[no])
        if esquerda != -1:
            pilha.append((esquerda, nivel + 1))
            pilha.append((direita, nivel + 1))
    limite = None if niveis is None else niveis - 1
    nos = []
    for no in range(arvore.node_count):
        if amostras[no] < config.ARVORE_MIN_AMOSTRAS_NO:
            continue
        if limite is not None and profundidade[no] > limite:
            continue
        folha = int(arvore.children_left[no]) == -1
        continua = bool(limite is not None and profundidade[no] == limite and not folha)
        feature = None
        limiar = None
        rotulo_esq, rotulo_dir = config.ROTULO_SIM, config.ROTULO_NAO
        if not folha:
            indice = int(arvore.feature[no])
            feature = features[indice]
            limiar = float(arvore.threshold[no])
            rotulo_esq, rotulo_dir = rotulos_ramos(feature, limiar)
        contagem = {classe: int(contagens[classe][no]) for classe in config.CLASSES}
        valores = arvore.value[no][0]
        prevista = str(modelo.classes_[int(np.argmax(valores))])
        nos.append(
            {
                "id": int(no),
                "profundidade": int(profundidade[no]),
                "folha": folha or continua,
                "continua": continua,
                "feature": feature,
                "limiar": limiar,
                "esquerda": None if folha or continua else int(arvore.children_left[no]),
                "direita": None if folha or continua else int(arvore.children_right[no]),
                "amostras": int(amostras[no]),
                "contagem": contagem,
                "majoritaria": classe_majoritaria(contagem),
                "prevista": prevista,
                "rotulo_esquerda": rotulo_esq,
                "rotulo_direita": rotulo_dir,
            }
        )
    return nos


def caminho_ate(nos, destino):
    """Caminho da raiz até um nó, para realçar a folha mais pura de FALHA."""
    indice = {no["id"]: no for no in nos}
    trilha = []

    def busca(no_id):
        trilha.append(no_id)
        if no_id == destino:
            return True
        no = indice[no_id]
        for filho in (no["esquerda"], no["direita"]):
            if filho in indice and busca(filho):
                return True
        trilha.pop()
        return False

    if nos and busca(nos[0]["id"]):
        return trilha
    return []


def folha_mais_pura_falha(nos):
    """Folha com a maior proporção real de FALHA."""
    folhas = [no for no in nos if no["folha"] and not no["continua"]]
    if not folhas:
        folhas = [no for no in nos if no["folha"]]
    if not folhas:
        return None

    def chave(no):
        proporcao = no["contagem"][config.CLASSES[2]] / no["amostras"] if no["amostras"] else 0
        return (proporcao, no["contagem"][config.CLASSES[2]], -no["id"])

    return max(folhas, key=chave)


def texto_caminho(nos, trilha):
    """Frase do caminho realçado, com os limiares reais."""
    if len(trilha) < 2:
        return config.TEXTO_INSUFICIENTE
    indice = {no["id"]: no for no in nos}
    partes = []
    for atual, seguinte in zip(trilha, trilha[1:]):
        no = indice[atual]
        limiar = br(no["limiar"], config.ARVORE_CASAS_LIMIAR)
        if seguinte == no["esquerda"]:
            if no["rotulo_esquerda"] == config.ROTULO_SENTINELA:
                partes.append(f"{no['feature']} {config.ROTULO_SENTINELA}")
            else:
                partes.append(f"{no['feature']} <= {limiar}")
        else:
            partes.append(f"{no['feature']} > {limiar}")
    folha = indice[trilha[-1]]
    return "se " + " e ".join(partes) + f", então {folha['prevista']}"


def montar_documento_arvore(modelo, x_treino, y_treino, features, niveis, origem, n_arvores):
    """JSON da árvore ilustrativa ou do pedaço, contado só no treino."""
    nos = extrair_nos(modelo, x_treino, y_treino, features, niveis)
    folha = folha_mais_pura_falha(nos)
    trilha = caminho_ate(nos, folha["id"]) if folha else []
    return {
        "origem": origem,
        "n_arvores": int(n_arvores),
        "profundidade_total": int(modelo.get_depth()),
        "n_folhas": int(modelo.get_n_leaves()),
        "nos": nos,
        "caminho_falha": trilha,
        "texto_caminho": texto_caminho(nos, trilha),
        "contagem_em": config.SPLIT_TREINO,
    }


def desenhar_arvore(documento, aria):
    """SVG da árvore. Nós cortados levam reticências."""
    nos = documento["nos"]
    if not nos:
        return f"<p>{html.escape(config.TEXTO_INSUFICIENTE)}</p>"
    indice = {no["id"]: no for no in nos}
    realce = set(documento.get("caminho_falha") or [])
    cursor = [0]
    pos = {}

    def visitar(no_id, nivel):
        no = indice[no_id]
        filhos = []
        if not no["folha"]:
            for filho in (no["esquerda"], no["direita"]):
                if filho in indice:
                    filhos.append(filho)
        if not filhos:
            x = cursor[0]
            cursor[0] += 1
            pos[no_id] = (x, nivel)
            return x
        xs = [visitar(filho, nivel + 1) for filho in filhos]
        x = sum(xs) / len(xs)
        pos[no_id] = (x, nivel)
        return x

    visitar(nos[0]["id"], 0)
    passo_x = config.ARVORE_PASSO_X
    passo_y = config.ARVORE_PASSO_Y
    largura_no = config.ARVORE_LARGURA_NO
    altura_no = config.ARVORE_ALTURA_NO
    largura = max(pos.values(), key=lambda item: item[0])[0] * passo_x + largura_no + 40
    altura = max(item[1] for item in pos.values()) * passo_y + altura_no + 36
    partes = [
        f'<svg viewBox="0 0 {largura:.0f} {altura:.0f}" role="img" aria-label="{html.escape(aria)}">'
    ]
    for no in nos:
        if no["folha"]:
            continue
        x1, y1 = pos[no["id"]]
        for filho, rotulo in ((no["esquerda"], no["rotulo_esquerda"]), (no["direita"], no["rotulo_direita"])):
            if filho not in pos:
                continue
            x2, y2 = pos[filho]
            px1 = 20 + x1 * passo_x + largura_no / 2
            py1 = 16 + y1 * passo_y + altura_no
            px2 = 20 + x2 * passo_x + largura_no / 2
            py2 = 16 + y2 * passo_y
            forte = ' stroke-width="3"' if no["id"] in realce and filho in realce else ' stroke-width="1.4"'
            partes.append(f'<line x1="{px1:.1f}" y1="{py1:.1f}" x2="{px2:.1f}" y2="{py2:.1f}" stroke="currentColor"{forte}/>')
            partes.append(
                f'<text x="{(px1 + px2) / 2:.1f}" y="{(py1 + py2) / 2:.1f}" fill="currentColor" font-size="12" text-anchor="middle">{html.escape(rotulo)}</text>'
            )
    for no in nos:
        x, y = pos[no["id"]]
        px = 20 + x * passo_x
        py = 16 + y * passo_y
        borda = ' stroke-width="3"' if no["id"] in realce else ' stroke-width="1.2"'
        partes.append(f'<rect x="{px:.1f}" y="{py:.1f}" width="{largura_no}" height="{altura_no}" rx="10" fill="none" stroke="currentColor"{borda}/>')
        if no["feature"] and not no["continua"]:
            pergunta = f"{no['feature']} &lt;= {html.escape(br(no['limiar'], config.ARVORE_CASAS_LIMIAR))}"
            partes.append(f'<text x="{px + 8:.1f}" y="{py + 22:.1f}" fill="currentColor" font-size="12">{pergunta}</text>')
            partes.append(
                f'<text x="{px + 8:.1f}" y="{py + 42:.1f}" fill="currentColor" font-size="12">amostras {no["amostras"]}</text>'
            )
            partes.append(
                f'<text x="{px + 8:.1f}" y="{py + 62:.1f}" fill="currentColor" font-size="13" class="{classe_svg(no["majoritaria"])}">{html.escape(no["majoritaria"])}</text>'
            )
        else:
            titulo = "…" if no["continua"] else no["prevista"]
            classe = "" if no["continua"] else classe_svg(no["prevista"])
            partes.append(
                f'<text x="{px + 8:.1f}" y="{py + 22:.1f}" fill="currentColor" font-size="14" class="{classe}">{html.escape(titulo)}</text>'
            )
            partes.append(
                f'<text x="{px + 8:.1f}" y="{py + 42:.1f}" fill="currentColor" font-size="12">amostras {no["amostras"]}</text>'
            )
            if not no["continua"]:
                partes.append(barra_no(px + 8, py + 58, largura_no - 16, 18, no["contagem"], no["amostras"]))
    partes.append("</svg>")
    return "".join(partes)


def barra_no(x, y, largura, altura, contagem, amostras):
    """Barra empilhada com a proporção real das três classes."""
    if not amostras:
        return ""
    cursor = x
    partes = []
    for classe, cor in zip(config.CLASSES, (config.COR_OK, config.COR_RISCO, config.COR_FALHA)):
        fatia = largura * contagem[classe] / amostras
        if fatia <= 0:
            continue
        partes.append(f'<rect x="{cursor:.1f}" y="{y:.1f}" width="{fatia:.1f}" height="{altura}" fill="{cor}"/>')
        cursor += fatia
    return "".join(partes)


def frases_validacao(escolhido, persistencia_val, familias):
    """Frases da análise A. Cada uma só entra se a condição for verdadeira."""
    frases = []
    gap = escolhido["gap"]
    macro_treino = escolhido["macro_f1_treino"]
    macro_val = escolhido["macro_f1_validacao"]
    recall = escolhido["validacao"]["geral"]["recall_falha"]
    inicio = escolhido["validacao"]["inicio_falha"]["recall_falha"]
    fracao = escolhido["validacao"]["anchor_dominante"]["fracao_falha_anchor_dominante"]
    anchor = escolhido["validacao"]["anchor_dominante"]["anchor_id"]
    ganho_geral = ganho(escolhido["validacao"], persistencia_val, "geral")
    ganho_anchor = ganho(escolhido["validacao"], persistencia_val, "sem_anchor_dominante")
    if gap > config.LIM_OVERFIT_GAP:
        frases.append(
            f"O macro-F1 cai {br(gap)} pontos do treino para a validação: overfitting. "
            "Reduzir max_depth, aumentar min_samples_leaf."
        )
    if macro_treino < config.LIM_MACRO_F1_BAIXO and macro_val < config.LIM_MACRO_F1_BAIXO:
        frases.append("Treino e validação baixos: modelo simples demais ou features fracas. Rever features e janelas.")
    if recall is not None and recall < config.LIM_RECALL_FALHA:
        frases.append(f"O modelo recupera só {br_pct(recall)} das FALHA. Testar class_weight e rever as features.")
    if ganho_geral is not None and ganho_geral < config.LIM_GANHO_PEQUENO:
        frases.append(f"O ganho sobre a persistência é de {br(ganho_geral)} pontos: pequeno. Rever features e janelas.")
    if inicio is not None and inicio < config.LIM_RECALL_INICIO:
        frases.append(f"O modelo antecipa só {br_pct(inicio)} dos inícios de FALHA.")
    if (fracao is not None and fracao > config.LIM_ANCHOR_DOMINANTE) or (
        ganho_anchor is not None and ganho_anchor < config.LIM_GANHO_PEQUENO
    ):
        frases.append(
            f"O resultado depende do anchor {anchor} ({br_pct(fracao)} das FALHA). "
            "Rever a divisão por fluxo ou anchor."
        )
    nb = familias["naive_bayes"]["macro_f1_validacao"]
    arvore = familias["arvore_decisao"]["macro_f1_validacao"]
    if nb < arvore:
        frases.append("O Naive Bayes ficou abaixo: a suposição de independência não vale para features em janela.")
    for fatia in config.FATIAS:
        if fatia == "transicoes":
            continue
        diferenca = ganho(escolhido["validacao"], persistencia_val, fatia)
        if diferenca is not None and diferenca < 0:
            frases.append(f"Na fatia {fatia}, o modelo é pior que a persistência.")
    if not frases:
        frases.append(config.TEXTO_NENHUMA_RESSALVA)
    return frases


def frases_teste(teste, macro_validacao):
    """Frases da análise B. Não sugerem novo ajuste além do aviso fixo."""
    frases = []
    macro_teste = numero(teste["modelo"]["geral"]["macro_f1"])
    macro_validacao = numero(macro_validacao)
    if macro_teste is not None and macro_validacao is not None and macro_validacao - macro_teste > config.LIM_QUEDA_TESTE:
        frases.append(
            f"O macro-F1 caiu {br(macro_validacao - macro_teste)} pontos da validação para o teste: "
            "o modelo generalizou menos que o esperado."
        )
    ganho_geral = numero(teste["ganho"]["geral"])
    if ganho_geral is not None and ganho_geral < config.LIM_GANHO_PEQUENO:
        frases.append(f"No teste, o ganho sobre a persistência é de {br(ganho_geral)} pontos: pequeno.")
    inicio = numero(teste["modelo"]["inicio_falha"]["recall_falha"])
    if inicio is not None and inicio < config.LIM_RECALL_INICIO:
        frases.append(f"No teste, o modelo antecipa só {br_pct(inicio)} dos inícios de FALHA.")
    for fatia in config.FATIAS:
        if fatia == "transicoes":
            continue
        diferenca = numero(teste["ganho"][fatia])
        if diferenca is not None and diferenca < 0:
            frases.append(f"Na fatia {fatia} do teste, o modelo é pior que a persistência.")
    return frases


def amostra_dataset(quadro, features_amostra):
    """Oito linhas com as três classes no alvo, sorteadas pela semente."""
    gerador = random.Random(config.SEED)
    indices = []
    for classe in config.CLASSES:
        candidatos = quadro.index[quadro["alvo"].astype(str) == classe].tolist()
        if candidatos:
            indices.append(gerador.choice(candidatos))
    faltam = config.HTML_MAX_LINHAS - len(set(indices))
    resto = [i for i in quadro.index.tolist() if i not in set(indices)]
    if faltam > 0 and resto:
        indices.extend(gerador.sample(resto, min(faltam, len(resto))))
    parte = quadro.loc[list(dict.fromkeys(indices))].sort_values(["timestamp", "id_fluxo"], kind="mergesort")
    linhas = []
    for linha in parte.itertuples(index=False):
        features = {}
        for nome in features_amostra:
            valor = getattr(linha, nome)
            features[nome] = None if pd.isna(valor) else float(valor)
        linhas.append(
            {
                "id_fluxo": str(linha.id_fluxo),
                "timestamp_utc": iso_de_unix(linha.timestamp),
                "split": str(linha.split),
                "classe_atual": str(linha.classe_atual),
                "alvo": str(linha.alvo),
                "features": features,
            }
        )
    return linhas


def conferencia_persistencia(calculado, referencia):
    """Compara o macro-F1 refeito com o da Etapa 7."""
    saida = {}
    for split in (config.SPLIT_TREINO, config.SPLIT_VALIDACAO):
        novo = calculado[split]["geral"]["macro_f1"]
        antigo = referencia.get(split)
        diferenca = None if novo is None or antigo is None else abs(novo - antigo)
        estado = "PASSOU" if diferenca is not None and diferenca <= config.TOLERANCIA_PERSISTENCIA else "ATENCAO"
        saida[split] = {"calculado": novo, "referencia": antigo, "diferenca": diferenca, "estado": estado}
    return saida


def matriz_confere(metricas):
    """A soma da matriz é n e cada linha soma o suporte da classe."""
    matriz = metricas["matriz"]
    if sum(sum(linha) for linha in matriz) != metricas["n"]:
        return False
    for i, classe in enumerate(config.CLASSES):
        if sum(matriz[i]) != metricas["por_classe"][classe]["suporte"]:
            return False
    return True


def verificar(estado):
    """Junta as verificações. FALHOU interrompe depois de gravar."""
    return estado


def sem_modelo(item):
    """Tira o objeto sklearn antes de gravar JSON."""
    return {chave: valor for chave, valor in item.items() if chave != "modelo"}


def gravar_grade(registros):
    """Uma linha por candidato da busca."""
    with config.ARQUIVO_GRADE.open("w", encoding="utf-8", newline="") as arquivo:
        escritor = csv.writer(arquivo, lineterminator="\n")
        escritor.writerow(config.COLUNAS_GRADE)
        for item in registros:
            escritor.writerow(
                [
                    item["familia"],
                    item["hiperparametros"],
                    item["macro_f1_treino"],
                    item["macro_f1_validacao"],
                    item["gap"],
                    "" if item["f1_falha_validacao"] is None else item["f1_falha_validacao"],
                    "" if item["recall_falha_validacao"] is None else item["recall_falha_validacao"],
                ]
            )


def params_json(params):
    """None vira null. A profundidade sem limite fica null, não um número inventado."""
    saida = {}
    for chave, valor in params.items():
        saida[chave] = valor
    return saida


def treinar():
    """Treina, escolhe pela validação e publica a página sem ler o teste."""
    configurar_saida()
    garantir_pastas()
    copiar_prompt()
    features_doc = ler_json(config.ARQUIVO_FEATURES_ETAPA7)
    qualidade = ler_json(config.ARQUIVO_QUALIDADE_ETAPA7)
    features = list(features_doc["features"])
    quadro = ler_tabela(config.SPLITS_AJUSTE)
    if config.SPLIT_TESTE in set(quadro["split"].astype(str)):
        raise SystemExit("O split teste foi carregado durante o ajuste. Isso não é permitido.")
    matriz = conferir_entrada(quadro, features)
    y = quadro["alvo"].astype(str).to_numpy()
    atual = quadro["classe_atual"].astype(str).to_numpy()
    anchor = quadro["anchor_id"].astype(str).to_numpy()
    timestamp = pd.to_numeric(quadro["timestamp"]).to_numpy(dtype=np.int64)
    treino = quadro["split"].astype(str).to_numpy() == config.SPLIT_TREINO
    val = ~treino
    if int(timestamp[treino].max()) >= int(timestamp[val].min()):
        raise SystemExit("A ordem temporal quebrou: há validação antes do fim do treino.")
    x_treino, y_treino = matriz[treino], y[treino]
    x_val, y_val = matriz[val], y[val]
    print(f"Treino: {len(y_treino)} linhas. Validação: {len(y_val)} linhas. Teste não carregado.")
    persistencia_treino = avaliar_fatias(y_treino, atual[treino], atual[treino], anchor[treino])
    persistencia_val = avaliar_fatias(y_val, atual[val], atual[val], anchor[val])
    sempre_ok = {
        config.SPLIT_TREINO: float((y_treino == config.CLASSE_OK).mean()),
        config.SPLIT_VALIDACAO: float((y_val == config.CLASSE_OK).mean()),
    }
    registros = []
    melhores = {}
    for familia in config.ALGORITMOS:
        print(familia)
        grade, melhor = treinar_familia(familia, x_treino, y_treino, x_val, y_val, atual[val], anchor[val])
        registros.extend(grade)
        melhores[familia] = melhor
    escolhido = min(melhores.values(), key=chave_desempate)
    print(f"Escolhido: {escolhido['familia']} {escolhido['hiperparametros']}")
    params_arvore = melhores["arvore_decisao"]["params"]
    ilustrativa = DecisionTreeClassifier(
        max_depth=config.ARVORE_ILUSTRATIVA_PROFUNDIDADE,
        min_samples_leaf=params_arvore["min_samples_leaf"],
        class_weight=params_arvore["class_weight"],
        random_state=config.SEED,
    )
    ilustrativa.fit(x_treino, y_treino)
    doc_ilustrativa = montar_documento_arvore(
        ilustrativa, x_treino, y_treino, features, None, config.ORIGEM_ARVORE, 1
    )
    doc_ilustrativa["hiperparametros"] = {
        "max_depth": config.ARVORE_ILUSTRATIVA_PROFUNDIDADE,
        "min_samples_leaf": params_arvore["min_samples_leaf"],
        "class_weight": params_arvore["class_weight"],
    }
    doc_ilustrativa["macro_f1_treino"] = fatia_metricas(y_treino, ilustrativa.predict(x_treino))["macro_f1"]
    doc_ilustrativa["macro_f1_validacao"] = fatia_metricas(y_val, ilustrativa.predict(x_val))["macro_f1"]
    doc_ilustrativa["entra_na_escolha"] = False
    doc_pedaco = None
    if escolhido["familia"] == "arvore_decisao":
        doc_pedaco = montar_documento_arvore(
            escolhido["modelo"], x_treino, y_treino, features, config.ARVORE_NIVEIS_PEDACO, config.ORIGEM_ARVORE, 1
        )
    elif escolhido["familia"] == "random_forest":
        doc_pedaco = montar_documento_arvore(
            escolhido["modelo"].estimators_[0],
            x_treino,
            y_treino,
            features,
            config.ARVORE_NIVEIS_PEDACO,
            config.ORIGEM_FLORESTA,
            escolhido["modelo"].n_estimators,
        )
        doc_pedaco["nota_contagem"] = config.AVISO_CONTAGEM_FLORESTA
    conferencia = conferencia_persistencia(
        {config.SPLIT_TREINO: persistencia_treino, config.SPLIT_VALIDACAO: persistencia_val},
        qualidade["baseline_persistencia_macro_f1"],
    )
    verificacoes = {
        "features_so_do_json": {"estado": "PASSOU", "detalhe": f"{len(features)} features de features.json, sem coluna proibida e sem NaN."},
        "ordem_temporal": {"estado": "PASSOU", "detalhe": "O maior timestamp de treino é anterior ao menor da validação."},
        "teste_fora_do_ajuste": {"estado": "PASSOU", "detalhe": "O split teste não foi carregado nesta execução."},
        "matriz_de_confusao": {
            "estado": "PASSOU" if matriz_confere(escolhido["validacao"]["geral"]) else "FALHOU",
            "detalhe": "A soma da matriz é o número de linhas e cada linha soma o suporte.",
        },
        "persistencia_confere": {
            "estado": "PASSOU" if all(item["estado"] == "PASSOU" for item in conferencia.values()) else "ATENCAO",
            "detalhe": "Macro-F1 da persistência comparado ao da Etapa 7.",
        },
        "escolha_pela_validacao": {
            "estado": "PASSOU" if escolhido["macro_f1_validacao"] == max(item["macro_f1_validacao"] for item in registros) else "FALHOU",
            "detalhe": "O escolhido tem o maior macro-F1 de validação da grade.",
        },
        "lock_do_teste": {"estado": "ATENCAO", "detalhe": "O teste ainda não foi avaliado."},
        "determinismo": {
            "estado": "ATENCAO",
            "detalhe": "O script usa SEED e a ordem da grade. A igualdade byte a byte é conferida repetindo a execução. O tempo de treino pode variar.",
        },
        "arvore_ilustrativa": verificacao_arvore(doc_ilustrativa, features, len(y_treino)),
        "contagem_so_treino": {
            "estado": "PASSOU" if doc_ilustrativa["nos"] and doc_ilustrativa["nos"][0]["amostras"] == len(y_treino) else "FALHOU",
            "detalhe": "A raiz da árvore ilustrativa conta todas as linhas de treino e nenhuma de validação.",
        },
    }
    if doc_pedaco and doc_pedaco["nos"] and doc_pedaco["nos"][0]["amostras"] != len(y_treino):
        verificacoes["contagem_so_treino"] = {
            "estado": "FALHOU",
            "detalhe": "O pedaço não foi contado só no treino.",
        }
    resultados = {
        "distribuicao_alvo": qualidade["alvo_por_split"],
        "persistencia_referencia": qualidade["baseline_persistencia_macro_f1"],
        "conferencia_persistencia": conferencia,
        "sempre_ok": sempre_ok,
        "persistencia": {config.SPLIT_TREINO: persistencia_treino, config.SPLIT_VALIDACAO: persistencia_val},
        "familias": {
            familia: {
                "hiperparametros": melhores[familia]["hiperparametros"],
                "params": params_json(melhores[familia]["params"]),
                "macro_f1_treino": melhores[familia]["macro_f1_treino"],
                "macro_f1_validacao": melhores[familia]["macro_f1_validacao"],
                "gap": melhores[familia]["gap"],
                "f1_falha_validacao": melhores[familia]["f1_falha_validacao"],
                "recall_falha_validacao": melhores[familia]["recall_falha_validacao"],
                "validacao": melhores[familia]["validacao"],
                "tempo_s": round(melhores[familia]["tempo_s"], 3),
            }
            for familia in config.ALGORITMOS
        },
        "escolhido": escolhido["familia"],
        "supera_persistencia_na_validacao": ganho(escolhido["validacao"], persistencia_val, "geral") > 0,
        "analise_validacao": frases_validacao(escolhido, persistencia_val, melhores),
        "avisos": [config.AVISO_NB_PESO, config.AVISO_NB_SENTINELA],
    }
    modelo_json = {
        "familia": escolhido["familia"],
        "hiperparametros": params_json(escolhido["params"]),
        "hiperparametros_texto": escolhido["hiperparametros"],
        "macro_f1_validacao": escolhido["macro_f1_validacao"],
        "criterio": config.METRICA_SELECAO,
        "desempate": "maior macro-F1 de validação; empate pelo menor gap; depois o modelo mais simples",
        "features": features,
    }
    gravar_grade(registros)
    gravar_json(config.ARQUIVO_VALIDACAO, resultados)
    gravar_json(config.ARQUIVO_ESCOLHIDO, modelo_json)
    joblib.dump(
        {"modelo": escolhido["modelo"], "familia": escolhido["familia"], "features": features, "params": params_json(escolhido["params"])},
        config.ARQUIVO_MODELO,
    )
    gravar_json(config.ARQUIVO_ARVORE_ILUSTRATIVA, doc_ilustrativa)
    if doc_pedaco is None:
        if config.ARQUIVO_ARVORE_PEDACO.exists():
            config.ARQUIVO_ARVORE_PEDACO.unlink()
    else:
        gravar_json(config.ARQUIVO_ARVORE_PEDACO, doc_pedaco)
    teste = ler_json(config.ARQUIVO_TESTE) if config.ARQUIVO_LOCK.is_file() and config.ARQUIVO_TESTE.is_file() else None
    resumo = montar_resumo(quadro, features, features_doc, resultados, modelo_json, doc_ilustrativa, doc_pedaco, teste)
    gravar_json(config.ARQUIVO_RESUMO_PAGINA, resumo)
    gravar_json(config.ARQUIVO_VERIFICACAO, verificacoes)
    gerar_html(resumo)
    atualizar_index(modelo_json, teste)
    imprimir_resumo(resultados, modelo_json, teste)
    falhou = [nome for nome, item in verificacoes.items() if item["estado"] == "FALHOU"]
    if falhou:
        raise SystemExit("Verificações que falharam: " + ", ".join(falhou))


def verificacao_arvore(documento, features, n_treino):
    """Profundidade, soma das folhas e features usadas."""
    if documento["profundidade_total"] > config.ARVORE_ILUSTRATIVA_PROFUNDIDADE:
        return {"estado": "FALHOU", "detalhe": "A árvore ilustrativa passou da profundidade combinada."}
    folhas = [no for no in documento["nos"] if no["folha"] and not no["continua"]]
    soma = sum(no["amostras"] for no in folhas)
    if soma != n_treino:
        return {"estado": "FALHOU", "detalhe": f"As folhas somam {soma} linhas, e o treino tem {n_treino}."}
    usadas = {no["feature"] for no in documento["nos"] if no["feature"]}
    if not usadas <= set(features):
        return {"estado": "FALHOU", "detalhe": "A árvore usou feature fora de features.json."}
    if usadas & set(config.COLUNAS_PROIBIDAS):
        return {"estado": "FALHOU", "detalhe": "A árvore usou coluna de metadado."}
    return {"estado": "PASSOU", "detalhe": f"Profundidade {documento['profundidade_total']}, folhas somam {soma}."}


def avaliar_teste(forcar):
    """Lê o teste uma vez. Recusa a segunda leitura sem a flag de força."""
    configurar_saida()
    if not config.ARQUIVO_ESCOLHIDO.is_file() or not config.ARQUIVO_MODELO.is_file():
        raise SystemExit("Rode o treino antes de avaliar o teste.")
    if config.ARQUIVO_LOCK.is_file() and not forcar:
        raise SystemExit(
            "O teste já foi avaliado. Para repetir, use --forcar-reavaliar-teste. "
            "O teste não deve ser usado para novos ajustes."
        )
    pacote = joblib.load(config.ARQUIVO_MODELO)
    modelo_json = ler_json(config.ARQUIVO_ESCOLHIDO)
    resultados = ler_json(config.ARQUIVO_VALIDACAO)
    features = list(pacote["features"])
    quadro = ler_tabela((config.SPLIT_TESTE,))
    if set(quadro["split"].astype(str)) != {config.SPLIT_TESTE}:
        raise SystemExit("A avaliação do teste carregou outro split.")
    matriz = conferir_entrada(quadro, features)
    y = quadro["alvo"].astype(str).to_numpy()
    atual = quadro["classe_atual"].astype(str).to_numpy()
    anchor = quadro["anchor_id"].astype(str).to_numpy()
    previsto = pacote["modelo"].predict(matriz)
    modelo = avaliar_fatias(y, previsto, atual, anchor)
    persistencia = avaliar_fatias(y, atual, atual, anchor)
    ganhos = {fatia: ganho(modelo, persistencia, fatia) for fatia in config.FATIAS}
    anterior = ler_json(config.ARQUIVO_TESTE) if forcar and config.ARQUIVO_TESTE.is_file() else {}
    reavaliacoes = list(anterior.get("reavaliacoes") or [])
    if forcar and config.ARQUIVO_LOCK.is_file():
        reavaliacoes.append(
            {
                "em": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00"),
                "motivo": "forcar-reavaliar-teste",
            }
        )
    documento = {
        "familia": modelo_json["familia"],
        "modelo": modelo,
        "persistencia": persistencia,
        "ganho": ganhos,
        "analise_teste": frases_teste({"modelo": modelo, "ganho": ganhos}, modelo_json["macro_f1_validacao"]),
        "reavaliacoes": reavaliacoes,
        "frase_fixa": config.TEXTO_TESTE_FIXO,
    }
    gravar_json(config.ARQUIVO_TESTE, documento)
    config.ARQUIVO_LOCK.write_text("avaliado\n", encoding="utf-8")
    features_doc = ler_json(config.ARQUIVO_FEATURES_ETAPA7)
    ilustrativa = ler_json(config.ARQUIVO_ARVORE_ILUSTRATIVA)
    pedaco = ler_json(config.ARQUIVO_ARVORE_PEDACO) if config.ARQUIVO_ARVORE_PEDACO.is_file() else None
    quadro_amostra = ler_tabela(config.SPLITS_AJUSTE)
    resumo = montar_resumo(
        quadro_amostra,
        features,
        features_doc,
        resultados,
        modelo_json,
        ilustrativa,
        pedaco,
        documento,
    )
    gravar_json(config.ARQUIVO_RESUMO_PAGINA, resumo)
    verificacoes = ler_json(config.ARQUIVO_VERIFICACAO) if config.ARQUIVO_VERIFICACAO.is_file() else {}
    verificacoes["lock_do_teste"] = {"estado": "PASSOU", "detalhe": "O lock foi gravado depois da única leitura do teste."}
    verificacoes["teste_fora_do_ajuste"] = {
        "estado": "PASSOU",
        "detalhe": "O teste foi lido só em --avaliar-teste, depois da escolha.",
    }
    gravar_json(config.ARQUIVO_VERIFICACAO, verificacoes)
    gerar_html(resumo)
    atualizar_index(modelo_json, documento)
    print()
    print("=== Teste da Etapa 8 ===")
    print(f"Macro-F1 teste: {documento['modelo']['geral']['macro_f1']}")
    print(f"Persistência teste: {documento['persistencia']['geral']['macro_f1']}")
    print(f"Ganho: {documento['ganho']['geral']}")
    for frase in documento["analise_teste"]:
        print(frase)
    print(config.TEXTO_TESTE_FIXO)


def montar_resumo(quadro, features, features_doc, resultados, modelo_json, ilustrativa, pedaco, teste):
    """O que a página mostra, sem o dataset inteiro."""
    svg_ilustrativa = desenhar_arvore(ilustrativa, config.ARIA_ARVORE)
    svg_pedaco = desenhar_arvore(pedaco, config.ARIA_ARVORE) if pedaco else None
    return {
        "totais": {
            "linhas": int(sum(features_doc["splits"][nome]["linhas"] for nome in config.SPLITS_AJUSTE) + features_doc["splits"][config.SPLIT_TESTE]["linhas"]),
            "linhas_ajuste": int(len(quadro)),
            "fluxos": int(quadro["id_fluxo"].nunique()) if "id_fluxo" in quadro.columns else None,
            "features": len(features),
        },
        "amostra": amostra_dataset(quadro, [nome for nome in config.FEATURES_AMOSTRA if nome in features]),
        "splits": features_doc["splits"],
        "distribuicao": resultados["distribuicao_alvo"],
        "persistencia": {
            "treino": resultados["persistencia"][config.SPLIT_TREINO]["geral"]["macro_f1"],
            "validacao": resultados["persistencia"][config.SPLIT_VALIDACAO]["geral"]["macro_f1"],
            "f1_falha_validacao": resultados["persistencia"][config.SPLIT_VALIDACAO]["geral"]["f1_falha"],
            "recall_falha_validacao": resultados["persistencia"][config.SPLIT_VALIDACAO]["geral"]["recall_falha"],
        },
        "sempre_ok": resultados["sempre_ok"],
        "familias": {
            familia: {
                "hiperparametros": resultados["familias"][familia]["hiperparametros"],
                "macro_f1_treino": resultados["familias"][familia]["macro_f1_treino"],
                "macro_f1_validacao": resultados["familias"][familia]["macro_f1_validacao"],
                "gap": resultados["familias"][familia]["gap"],
                "f1_falha_validacao": resultados["familias"][familia]["f1_falha_validacao"],
                "recall_falha_validacao": resultados["familias"][familia]["recall_falha_validacao"],
                "matriz": resultados["familias"][familia]["validacao"]["geral"]["matriz"],
                "por_classe": resultados["familias"][familia]["validacao"]["geral"]["por_classe"],
            }
            for familia in config.ALGORITMOS
        },
        "escolhido": modelo_json,
        "supera_persistencia": resultados["supera_persistencia_na_validacao"],
        "analise_validacao": resultados["analise_validacao"],
        "ilustrativa": {
            "macro_f1_treino": ilustrativa["macro_f1_treino"],
            "macro_f1_validacao": ilustrativa["macro_f1_validacao"],
            "profundidade_total": ilustrativa["profundidade_total"],
            "n_folhas": ilustrativa["n_folhas"],
            "texto_caminho": ilustrativa["texto_caminho"],
            "svg": svg_ilustrativa,
        },
        "pedaco": None
        if pedaco is None
        else {
            "origem": pedaco["origem"],
            "n_arvores": pedaco["n_arvores"],
            "profundidade_total": pedaco["profundidade_total"],
            "n_folhas": pedaco["n_folhas"],
            "nota_contagem": pedaco.get("nota_contagem"),
            "svg": svg_pedaco,
        },
        "teste": None
        if teste is None
        else {
            "macro_f1": teste["modelo"]["geral"]["macro_f1"],
            "acuracia": teste["modelo"]["geral"]["acuracia"],
            "f1_ponderado": teste["modelo"]["geral"]["f1_ponderado"],
            "por_classe": teste["modelo"]["geral"]["por_classe"],
            "matriz": teste["modelo"]["geral"]["matriz"],
            "persistencia_macro_f1": teste["persistencia"]["geral"]["macro_f1"],
            "persistencia_acuracia": teste["persistencia"]["geral"]["acuracia"],
            "persistencia_f1_ponderado": teste["persistencia"]["geral"]["f1_ponderado"],
            "persistencia_por_classe": teste["persistencia"]["geral"]["por_classe"],
            "fatias": {
                fatia: {
                    "n": teste["modelo"][fatia]["n"],
                    "macro_f1": teste["modelo"][fatia]["macro_f1"],
                    "persistencia": teste["persistencia"][fatia]["macro_f1"],
                    "ganho": teste["ganho"][fatia],
                    "recall_falha": teste["modelo"][fatia]["recall_falha"],
                }
                for fatia in config.FATIAS
            },
            "anchor": teste["modelo"]["anchor_dominante"],
            "analise": teste["analise_teste"],
        },
        "embargo_min": features_doc.get("parametros", {}).get("embargo_min"),
    }


def gerar_html(resumo):
    """Encaminha a página para gerar_pagina, sem retreinar."""
    import gerar_pagina
    gerar_pagina.escrever_pagina(
        gerar_pagina.preparar_pagina(resumo, ler_json(config.ARQUIVO_VALIDACAO))
    )



def svg_ciclo():
    """Doze passos e a seta da análise de volta aos hiperparâmetros."""
    partes = [f'<svg viewBox="0 0 1080 250" role="img" aria-label="{html.escape(config.ARIA_CICLO)}">']
    for indice, nome in enumerate(config.PASSOS_CICLO):
        coluna = indice % 6
        linha = indice // 6
        x = 16 + coluna * 178
        y = 24 + linha * 110
        partes.append(f'<rect x="{x}" y="{y}" width="160" height="64" rx="10" fill="none" stroke="currentColor"/>')
        partes.append(f'<text x="{x + 80}" y="{y + 28}" text-anchor="middle" fill="currentColor" font-size="13">{indice + 1}</text>')
        partes.append(f'<text x="{x + 80}" y="{y + 48}" text-anchor="middle" fill="currentColor" font-size="11">{html.escape(nome)}</text>')
    partes.append('<path d="M620 188 C620 230, 120 230, 120 188" fill="none" stroke="currentColor" stroke-width="1.6"/>')
    partes.append('<text x="360" y="242" text-anchor="middle" fill="currentColor" font-size="13">análise volta aos hiperparâmetros</text>')
    partes.append("</svg>")
    return "".join(partes)


def svg_tempo():
    """Passado até t, alvo em t+1."""
    return (
        f'<svg viewBox="0 0 1080 90" role="img" aria-label="{html.escape(config.ARIA_TEMPO)}">'
        '<text x="40" y="40" fill="currentColor" font-size="18">t−11 … t → features</text>'
        '<text x="620" y="40" fill="currentColor" font-size="18">t+1 → alvo</text>'
        '<text x="40" y="72" fill="currentColor" font-size="14">o futuro não entra nas features</text>'
        "</svg>"
    )


def svg_splits(resumo):
    """Treino, validação e teste com o embargo entre eles."""
    splits = resumo["splits"]
    nomes = (config.SPLIT_TREINO, config.SPLIT_VALIDACAO, config.SPLIT_TESTE)
    partes = [f'<svg viewBox="0 0 1080 120" role="img" aria-label="{html.escape(config.ARIA_SPLITS)}">']
    x = 20
    for nome in nomes:
        item = splits[nome]
        largura = 280
        partes.append(f'<rect x="{x}" y="20" width="{largura}" height="48" rx="8" fill="currentColor" fill-opacity="0.12" stroke="currentColor"/>')
        partes.append(
            f'<text x="{x + 12}" y="48" fill="currentColor" font-size="14">{html.escape(nome)} · {item["linhas"]} · {html.escape(item["inicio"][:10])}</text>'
        )
        x += largura + 16
        if nome != config.SPLIT_TESTE:
            partes.append(f'<text x="{x - 8}" y="48" fill="currentColor" font-size="12">embargo</text>')
            x += 70
    embargo = resumo.get("embargo_min")
    if embargo is not None:
        partes.append(f'<text x="20" y="100" fill="currentColor" font-size="14">Embargo de {html.escape(str(embargo))} min entre os cortes. Datas de features.json.</text>')
    partes.append("</svg>")
    return "".join(partes)


def barras_alvo(distribuicao):
    """Barras da distribuição do alvo em cada split."""
    cores = {
        config.CLASSES[0]: "var(--ok)",
        config.CLASSES[1]: "var(--risco)",
        config.CLASSES[2]: "var(--falha)",
    }
    partes = [f'<svg viewBox="0 0 1080 200" role="img" aria-label="{html.escape(config.ARIA_DISTRIBUICAO)}">']
    for indice, split in enumerate((config.SPLIT_TREINO, config.SPLIT_VALIDACAO, config.SPLIT_TESTE)):
        bloco = distribuicao.get(split) or {}
        total = sum(bloco.values()) or 1
        y = 18 + indice * 62
        partes.append(f'<text x="8" y="{y + 18}" fill="currentColor" font-size="14">{html.escape(split)}</text>')
        x = 130.0
        for classe in config.CLASSES:
            quantidade = bloco.get(classe, 0)
            largura = 560.0 * quantidade / total
            if largura > 0:
                partes.append(
                    f'<rect x="{x:.1f}" y="{y}" width="{largura:.1f}" height="26" fill="{cores[classe]}"/>'
                )
            x += largura
        texto = "  ".join(
            f"{classe} {bloco.get(classe, 0)} ({br(100 * bloco.get(classe, 0) / total, 1)}%)"
            for classe in config.CLASSES
        )
        partes.append(f'<text x="8" y="{y + 48}" fill="currentColor" font-size="12">{html.escape(texto)}</text>')
    partes.append("</svg>")
    return "".join(partes)


def classe_svg(classe):
    """Classe CSS da cor, para o texto dentro do SVG."""
    if classe not in config.CLASSES:
        return ""
    return classe.lower()


def classe_html(classe):
    """Cor e texto da classe."""
    if classe not in config.CLASSES:
        return config.ROTULO_VAZIO
    return f'<span class="{classe.lower()}">{html.escape(classe)}</span>'


def valor_feature(valor):
    """Sentinela com selo; o resto em formato brasileiro."""
    if valor is None:
        return config.ROTULO_VAZIO
    if abs(float(valor) - (-1)) <= config.TOLERANCIA_SENTINELA:
        return '<span class="selo">sentinela</span>'
    return html.escape(br(valor))


def tabela_amostra(linhas):
    """Amostra colorida por papel da coluna."""
    cabecalho = (
        "<th class=\"meta\">id_fluxo</th><th class=\"meta\">timestamp</th><th class=\"meta\">split</th>"
        "<th class=\"meta\">classe_atual</th>"
        + "".join(f'<th class="feat">{html.escape(nome)}</th>' for nome in config.FEATURES_AMOSTRA)
        + '<th class="alvo">alvo</th>'
    )
    corpo = []
    for linha in linhas:
        features = "".join(f'<td class="feat">{valor_feature(linha["features"].get(nome))}</td>' for nome in config.FEATURES_AMOSTRA)
        corpo.append(
            "<tr>"
            f'<td class="meta">{html.escape(linha["id_fluxo"])}</td>'
            f'<td class="meta">{html.escape(linha["timestamp_utc"])}</td>'
            f'<td class="meta">{html.escape(linha["split"])}</td>'
            f'<td class="meta">{classe_html(linha["classe_atual"])}</td>'
            f"{features}"
            f'<td class="alvo">{classe_html(linha["alvo"])}</td>'
            "</tr>"
        )
    return f'<div class="rolagem"><table><thead><tr>{cabecalho}</tr></thead><tbody>{"".join(corpo)}</tbody></table></div>'


def cartao_algoritmo(familia):
    """Cartão com a ideia, a lição e o limite."""
    cartao = config.CARTAO_ALGORITMO[familia]
    return (
        '<article class="cartao">'
        f"<h3>{html.escape(cartao['nome'])}</h3>"
        f"<p>{html.escape(cartao['ideia'])}</p>"
        f"<p>{html.escape(cartao['ensina'])}</p>"
        f"<p>{html.escape(cartao['limite'])}</p>"
        "</article>"
    )


def secao_pedaco(pedaco):
    """Topo da árvore escolhida, ou o aviso de que o Naive Bayes não tem árvore."""
    if pedaco is None:
        return "<p>O modelo escolhido é o Naive Bayes. Ele não tem árvore, então este bloco não aparece.</p>"
    nota = pedaco.get("nota_contagem") or ""
    origem = "uma árvore da floresta" if pedaco["origem"] == config.ORIGEM_FLORESTA else "a árvore escolhida"
    return (
        "<h3>Pedaço da árvore escolhida</h3>"
        f"<p>{html.escape(origem)}; profundidade total {pedaco['profundidade_total']}, "
        f"{pedaco['n_folhas']} folhas"
        + (f", {pedaco['n_arvores']} árvores na floresta" if pedaco["n_arvores"] > 1 else "")
        + ". Os nós com … continuam fora da figura.</p>"
        f'<div class="rolagem">{pedaco["svg"]}</div>'
        f"<p>{html.escape(nota)}</p>"
    )


def texto_tamanho(resumo):
    """Por que a árvore escolhida não cabe inteira, quando ela existe."""
    pedaco = resumo["pedaco"]
    if pedaco is None:
        return ""
    return (
        f"<p>A árvore usada no modelo tem profundidade {pedaco['profundidade_total']} e "
        f"{pedaco['n_folhas']} folhas. Por isso a página mostra só os primeiros níveis.</p>"
    )


def tabela_grades(resumo):
    """O que foi testado e o valor escolhido em cada família."""
    linhas = []
    for familia in config.ALGORITMOS:
        testado = ", ".join(f"{chave}: {valores_grade(chave, valores)}" for chave, valores in config.GRADES[familia].items())
        linhas.append(
            "<tr>"
            f"<td>{html.escape(config.CARTAO_ALGORITMO[familia]['nome'])}</td>"
            f"<td>{html.escape(testado)}</td>"
            f"<td>{html.escape(resumo['familias'][familia]['hiperparametros'])}</td>"
            "</tr>"
        )
    return (
        '<div class="rolagem"><table><thead><tr><th>Família</th><th>Testado</th><th>Escolhido na família</th></tr></thead><tbody>'
        + "".join(linhas)
        + "</tbody></table></div>"
    )


def valores_grade(chave, valores):
    """Lista legível, com sem limite e nenhum no lugar de null."""
    partes = []
    for valor in valores:
        if valor is None and chave == "max_depth":
            partes.append(config.ROTULO_SEM_LIMITE)
        elif valor is None:
            partes.append(config.ROTULO_NENHUM)
        else:
            partes.append(str(valor))
    return ", ".join(partes)


def barras_f1(resumo):
    """Treino e validação da persistência e dos três melhores."""
    series = [("Persistência", resumo["persistencia"]["treino"], resumo["persistencia"]["validacao"], None)]
    for familia in config.ALGORITMOS:
        item = resumo["familias"][familia]
        series.append((config.CARTAO_ALGORITMO[familia]["nome"], item["macro_f1_treino"], item["macro_f1_validacao"], item["gap"]))
    partes = [f'<svg viewBox="0 0 1080 220" role="img" aria-label="{html.escape(config.ARIA_BARRAS)}">']
    for indice, (nome, treino, val, gap) in enumerate(series):
        x = 40 + indice * 250
        partes.append(f'<text x="{x}" y="20" fill="currentColor" font-size="14">{html.escape(nome)}</text>')
        for deslocamento, valor, rotulo in ((0, treino, "treino"), (28, val, "validação")):
            altura = 0 if valor is None else max(0.0, float(valor)) * 120
            partes.append(f'<rect x="{x + deslocamento}" y="{160 - altura:.1f}" width="22" height="{altura:.1f}" fill="currentColor" fill-opacity="0.35"/>')
            partes.append(f'<text x="{x + deslocamento}" y="{176}" fill="currentColor" font-size="11">{html.escape(rotulo)} {html.escape(br(valor))}</text>')
        if gap is not None:
            partes.append(f'<text x="{x}" y="204" fill="currentColor" font-size="12">gap {html.escape(br(gap))}</text>')
    partes.append("</svg>")
    destaque = config.CARTAO_ALGORITMO[resumo["escolhido"]["familia"]]["nome"]
    return "".join(partes) + f"<p>Em destaque na escolha: {html.escape(destaque)}. {html.escape(config.AVISO_ESCOLHA)}</p>"


def tabela_validacao(resumo):
    """Persistência e os três algoritmos na validação."""
    linhas = [
        (
            "Persistência",
            resumo["persistencia"]["treino"],
            resumo["persistencia"]["validacao"],
            float(resumo["persistencia"]["treino"]) - float(resumo["persistencia"]["validacao"]),
            resumo["persistencia"]["f1_falha_validacao"],
            resumo["persistencia"]["recall_falha_validacao"],
            False,
        )
    ]
    for familia in config.ALGORITMOS:
        item = resumo["familias"][familia]
        linhas.append(
            (
                config.CARTAO_ALGORITMO[familia]["nome"],
                item["macro_f1_treino"],
                item["macro_f1_validacao"],
                item["gap"],
                item["f1_falha_validacao"],
                item["recall_falha_validacao"],
                familia == resumo["escolhido"]["familia"],
            )
        )
    corpo = []
    for nome, treino, val, gap, f1, recall, escolhido in linhas:
        corpo.append(
            f'<tr class="{"escolhido" if escolhido else ""}">'
            f"<td>{html.escape(nome)}</td><td>{html.escape(br(treino))}</td><td>{html.escape(br(val))}</td>"
            f"<td>{html.escape(br(gap))}</td><td>{html.escape(br(f1))}</td><td>{html.escape(br(recall))}</td></tr>"
        )
    return (
        '<div class="rolagem"><table><thead><tr>'
        "<th>Modelo</th><th>macro-F1 treino</th><th>macro-F1 validação</th><th>gap</th><th>F1 FALHA</th><th>recall FALHA</th>"
        f"</tr></thead><tbody>{''.join(corpo)}</tbody></table></div>"
    )


def matriz_html(matriz, por_classe, titulo):
    """Contagem e proporção da linha."""
    cabecalho = "".join(f"<th>{classe_html(classe)}</th>" for classe in config.CLASSES)
    corpo = []
    for i, classe in enumerate(config.CLASSES):
        suporte = por_classe[classe]["suporte"] or 1
        celulas = "".join(
            f"<td>{matriz[i][j]} ({html.escape(br(100 * matriz[i][j] / suporte, 1))}%)</td>" for j in range(len(config.CLASSES))
        )
        corpo.append(f"<tr><th>{classe_html(classe)}</th>{celulas}</tr>")
    return (
        f"<p>{html.escape(titulo)}</p>"
        f'<div class="rolagem"><table><thead><tr><th></th>{cabecalho}</tr></thead><tbody>{"".join(corpo)}</tbody></table></div>'
    )


def secao_teste(teste):
    """Relatório do teste, ou o aviso de que ele ainda não foi lido."""
    if teste is None:
        return f"<p>{html.escape(config.TEXTO_TESTE_AUSENTE)}</p>"
    linhas = []
    for classe in config.CLASSES:
        modelo = teste["por_classe"][classe]
        base = teste["persistencia_por_classe"][classe]
        linhas.append(
            "<tr>"
            f"<td>{classe_html(classe)}</td>"
            f"<td>{html.escape(br(modelo['precisao']))}</td><td>{html.escape(br(modelo['recall']))}</td><td>{html.escape(br(modelo['f1']))}</td><td>{modelo['suporte']}</td>"
            f"<td>{html.escape(br(base['precisao']))}</td><td>{html.escape(br(base['recall']))}</td><td>{html.escape(br(base['f1']))}</td>"
            "</tr>"
        )
    linhas.append(
        "<tr><td>macro</td>"
        f"<td colspan=\"3\">{html.escape(br(teste['macro_f1']))}</td><td></td>"
        f"<td colspan=\"3\">{html.escape(br(teste['persistencia_macro_f1']))}</td></tr>"
    )
    linhas.append(
        "<tr><td>ponderada</td>"
        f"<td colspan=\"3\">{html.escape(br(teste['f1_ponderado']))}</td><td></td>"
        f"<td colspan=\"3\">{html.escape(br(teste['persistencia_f1_ponderado']))}</td></tr>"
    )
    fatias = []
    for nome in config.FATIAS:
        item = teste["fatias"][nome]
        persistencia = config.TEXTO_ZERO_CONSTRUCAO if nome == "transicoes" else br(item["persistencia"])
        ganho_txt = config.ROTULO_VAZIO if nome == "transicoes" or item["ganho"] is None else br(item["ganho"])
        fatias.append(
            f"<tr><td>{html.escape(nome)}</td><td>{item['n']}</td><td>{html.escape(br(item['macro_f1']))}</td>"
            f"<td>{html.escape(persistencia)}</td><td>{html.escape(ganho_txt)}</td></tr>"
        )
    anchor = teste["anchor"]
    return (
        "<p>Modelo escolhido e persistência, lado a lado.</p>"
        f"<p>Acurácia do escolhido: {html.escape(br(teste['acuracia']))}. "
        f"Macro-F1: {html.escape(br(teste['macro_f1']))}. "
        f"F1 ponderado: {html.escape(br(teste['f1_ponderado']))}.</p>"
        '<div class="rolagem"><table><thead><tr><th>Classe</th><th>precisão</th><th>recall</th><th>F1</th><th>suporte</th>'
        "<th>precisão persistência</th><th>recall persistência</th><th>F1 persistência</th></tr></thead><tbody>"
        + "".join(linhas)
        + "</tbody></table></div>"
        + matriz_html(teste["matriz"], teste["por_classe"], config.TEXTO_MATRIZ_TESTE)
        + '<div class="rolagem"><table><thead><tr><th>Fatia</th><th>n</th><th>macro-F1 modelo</th><th>macro-F1 persistência</th><th>ganho</th></tr></thead><tbody>'
        + "".join(fatias)
        + "</tbody></table></div>"
        + f"<p>Anchor dominante no teste: {html.escape(str(anchor['anchor_id']))}, "
        f"{html.escape(br_pct(anchor['fracao_falha_anchor_dominante']))} das FALHA.</p>"
    )


def secao_analise_teste(teste):
    """Frases B e o aviso fixo."""
    if teste is None:
        return f"<p>{html.escape(config.TEXTO_TESTE_AUSENTE)}</p><p>{html.escape(config.TEXTO_TESTE_FIXO)}</p>"
    itens = "".join(f"<li>{html.escape(frase)}</li>" for frase in teste["analise"]) or f"<li>{html.escape(config.TEXTO_NENHUMA_RESSALVA)}</li>"
    return f"<ul>{itens}</ul><p>{html.escape(config.TEXTO_TESTE_FIXO)}</p>"


def cartao_etapa8(modelo_json, teste):
    """Cartão novo. Os cartões anteriores permanecem."""
    nome = config.CARTAO_ALGORITMO[modelo_json["familia"]]["nome"]
    frase = f"{nome}. Macro-F1 de validação {br(modelo_json['macro_f1_validacao'])}."
    if teste is not None:
        frase += f" Teste {br(teste['modelo']['geral']['macro_f1'])}."
    return (
        '<article class="cartao ativo">\n'
        f'      <p class="etapa">{html.escape(config.ROTULO_ETAPA8)}</p>\n'
        f"      <h2>{html.escape(config.TITULO_CARTAO)}</h2>\n"
        f"      <p>{html.escape(frase)}</p>\n"
        f'      <a href="{html.escape(config.LINK_ETAPA8, quote=True)}">Abrir página</a>\n'
        "    </article>"
    )


def atualizar_index(modelo_json, teste):
    """Substitui só o bloco da Etapa 8."""
    bloco = f"{config.MARCADOR_ETAPA8_INICIO}\n    {cartao_etapa8(modelo_json, teste)}\n    {config.MARCADOR_ETAPA8_FIM}"
    texto = config.ARQUIVO_INDEX.read_text(encoding="utf-8")
    if config.MARCADOR_ETAPA8_INICIO in texto and config.MARCADOR_ETAPA8_FIM in texto:
        inicio = texto.index(config.MARCADOR_ETAPA8_INICIO)
        fim = texto.index(config.MARCADOR_ETAPA8_FIM) + len(config.MARCADOR_ETAPA8_FIM)
        config.ARQUIVO_INDEX.write_text(texto[:inicio] + bloco + texto[fim:], encoding="utf-8")
        return
    if config.MARCADOR_ETAPA7_FIM not in texto:
        raise SystemExit("O index.html não tem o fim da Etapa 7.")
    config.ARQUIVO_INDEX.write_text(
        texto.replace(config.MARCADOR_ETAPA7_FIM, config.MARCADOR_ETAPA7_FIM + "\n" + bloco, 1),
        encoding="utf-8",
    )


def imprimir_resumo(resultados, modelo_json, teste):
    """Resumo do treino no terminal."""
    print()
    print("=== Resumo da Etapa 8 ===")
    print(f"Escolhido: {modelo_json['familia']} {modelo_json['hiperparametros_texto']}")
    print(f"Macro-F1 validação: {modelo_json['macro_f1_validacao']}")
    print(f"Persistência validação: {resultados['persistencia'][config.SPLIT_VALIDACAO]['geral']['macro_f1']}")
    print(f"Supera a persistência: {resultados['supera_persistencia_na_validacao']}")
    for familia in config.ALGORITMOS:
        item = resultados["familias"][familia]
        print(f"  {familia}: val={item['macro_f1_validacao']:.4f} gap={item['gap']:.4f} tempo={item['tempo_s']}s")
    for frase in resultados["analise_validacao"]:
        print(frase)
    if teste is None:
        print("Teste ainda não avaliado.")


def main():
    """Treino por padrão. O teste é um comando separado."""
    parser = argparse.ArgumentParser(description="Treina e compara os modelos da etapa 8.")
    parser.add_argument("--avaliar-teste", action="store_true")
    parser.add_argument("--forcar-reavaliar-teste", action="store_true")
    args = parser.parse_args()
    if args.avaliar_teste or args.forcar_reavaliar_teste:
        avaliar_teste(forcar=args.forcar_reavaliar_teste)
    else:
        treinar()


if __name__ == "__main__":
    main()
