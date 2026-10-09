"""Parâmetros da etapa 7: rotulagem do Período B e dataset final.

Não há datas aqui. As janelas vêm de metadados.json da Etapa 5.
Esta etapa não consulta a API. A regra é operacional deste projeto.
"""

from pathlib import Path

# ---------------------------------------------------------------------------
# Caminhos
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent.parent
RAIZ_PROJETO = BASE_DIR.parent.parent
CACHE_DIR = BASE_DIR / "cache"
PROMPT_DIR = BASE_DIR / "prompt"
DATA_DIR = BASE_DIR / "data"
SRC_DIR = BASE_DIR / "src"
TEMPLATE_DIR = BASE_DIR / "template"
ARQUIVO_DATASET_ETAPA5 = RAIZ_PROJETO / "pipeline" / "05_periodos" / "data" / "dataset_processado.csv"
ARQUIVO_METADADOS_ETAPA5 = RAIZ_PROJETO / "pipeline" / "05_periodos" / "data" / "metadados.json"
ARQUIVO_BASELINE_ETAPA6 = RAIZ_PROJETO / "pipeline" / "06_baseline" / "data" / "baseline_rotulacao_por_fluxo.csv"
ARQUIVO_ROTULADO = DATA_DIR / "dataset_rotulado.csv"
ARQUIVO_AUDITORIA = DATA_DIR / "auditoria_rotulagem.csv"
ARQUIVO_FINAL = DATA_DIR / "dataset_final.csv"
ARQUIVO_FEATURES = DATA_DIR / "features.json"
ARQUIVO_EXCLUSOES = DATA_DIR / "exclusoes.csv"
ARQUIVO_QUALIDADE = DATA_DIR / "qualidade_rotulagem.json"
ARQUIVO_AMOSTRA = DATA_DIR / "amostra_rotulagem.json"
ARQUIVO_HTML = TEMPLATE_DIR / "rotulagem.html"
ARQUIVO_INDEX = RAIZ_PROJETO / "index.html"
ARQUIVO_PROMPT_ORIGEM = RAIZ_PROJETO / "7_rotular_dataset.md"
ARQUIVO_PROMPT = PROMPT_DIR / "etapa7_prompt.md"
FONTE_JANELA = "pipeline/05_periodos/data/metadados.json"
FONTE_DATASET = "pipeline/05_periodos/data/dataset_processado.csv"
FONTE_BASELINE = "pipeline/06_baseline/data/baseline_rotulacao_por_fluxo.csv"

# ---------------------------------------------------------------------------
# Rotulagem
# ---------------------------------------------------------------------------

# Com 3 pacotes, 1 perdido é 100/3 e 2 perdidos são 200/3.
LIM_PERDA_RISCO = 100 / 3
LIM_PERDA_FALHA = 200 / 3
EPS = 0.01
STATUS_BASELINE_OK = "VALIDO"
CLASSES = ("OK", "RISCO", "FALHA")
CLASSE_OK = "OK"
CLASSE_RISCO = "RISCO"
CLASSE_FALHA = "FALHA"
SEM_ROTULO = "sem rótulo"
FORMATO_ID_FLUXO = "{probe_id}_{anchor_id}"
PERIODO_A = "A"
PERIODO_B = "B"
VALORES_PERDA_ESPERADOS = (0, LIM_PERDA_RISCO, LIM_PERDA_FALHA, 100)

MOTIVO_PERDA_SEVERA = "perda_severa"
MOTIVO_LATENCIA_P99 = "latencia_acima_p99"
MOTIVO_PERDA_PARCIAL = "perda_parcial"
MOTIVO_LATENCIA_P95 = "latencia_acima_p95"
MOTIVO_JITTER_P95 = "jitter_acima_p95"
MOTIVO_SEM_ALERTA = "sem_alerta"
MOTIVO_SEM_BASELINE = "baseline_nao_encontrado"
MOTIVO_BASELINE_INSUFICIENTE = "baseline_insuficiente"
MOTIVO_PERDA_VAZIA = "perda_pct_vazio"
MOTIVOS_SEM_ROTULO = (
    MOTIVO_SEM_BASELINE,
    MOTIVO_BASELINE_INSUFICIENTE,
    MOTIVO_PERDA_VAZIA,
)
MOTIVOS_FALHA = (MOTIVO_PERDA_SEVERA, MOTIVO_LATENCIA_P99)
MOTIVOS_EXCLUSAO_FLUXO = (
    MOTIVO_SEM_BASELINE,
    MOTIVO_BASELINE_INSUFICIENTE,
    "baseline_desatualizado",
)

# Ordem de precedência. A primeira condição verdadeira encerra a avaliação.
REGRAS = (
    {
        "condicao": "perda_pct ≥ 200/3 − 0,01 (2 de 3 pacotes perdidos)",
        "classe": CLASSE_FALHA,
        "motivo": MOTIVO_PERDA_SEVERA,
    },
    {
        "condicao": "latencia_ms > P99 de RTT do próprio fluxo",
        "classe": CLASSE_FALHA,
        "motivo": MOTIVO_LATENCIA_P99,
    },
    {
        "condicao": "perda_pct ≥ 100/3 − 0,01 (1 de 3 pacotes perdido)",
        "classe": CLASSE_RISCO,
        "motivo": MOTIVO_PERDA_PARCIAL,
    },
    {
        "condicao": "latencia_ms > P95 de RTT do próprio fluxo",
        "classe": CLASSE_RISCO,
        "motivo": MOTIVO_LATENCIA_P95,
    },
    {
        "condicao": "jitter_ms > P95 de jitter do próprio fluxo",
        "classe": CLASSE_RISCO,
        "motivo": MOTIVO_JITTER_P95,
    },
    {
        "condicao": "nenhuma das condições acima",
        "classe": CLASSE_OK,
        "motivo": MOTIVO_SEM_ALERTA,
    },
)

TEXTO_CLASSE = {
    CLASSE_OK: "Sem sinais relevantes de degradação nesta execução. Não quer dizer que a rede é perfeita.",
    CLASSE_RISCO: "A comunicação existe, mas há instabilidade ou degradação nesta execução.",
    CLASSE_FALHA: "Indisponibilidade ou degradação severa nesta execução.",
}

# ---------------------------------------------------------------------------
# Alvo, janelas, exclusões e split
# ---------------------------------------------------------------------------

HORIZONTE = 1
JANELAS = (3, 6, 12)
GAP_MAX_S = 600
SENTINELA = -1
TTL_CLIP = 16
TTL_RESET = 64
MAX_FRAC_FALHA_LATENCIA = 0.5
CORTE_TREINO_DIAS = 5
CORTE_VAL_DIAS = 6
EMBARGO_MIN = 60
SEGUNDOS_DIA = 86400
SEGUNDOS_MINUTO = 60
N_VERIFICA_VAZAMENTO = 200
TOLERANCIA_VERIFICACAO = 1e-6
SEED = 42
FLOAT_FORMAT = "%.6g"
SPLIT_TREINO = "treino"
SPLIT_VALIDACAO = "validacao"
SPLIT_TESTE = "teste"
SPLITS = (SPLIT_TREINO, SPLIT_VALIDACAO, SPLIT_TESTE)

MOTIVO_DESATUALIZADO = "baseline_desatualizado"
MOTIVO_SEM_FUTURO = "sem_medicao_t_mais_h"
MOTIVO_ALVO_SEM_ROTULO = "alvo_sem_rotulo"
MOTIVO_GAP = "intervalo_acima_de_gap"
MOTIVO_EMBARGO = "embargo"

FEATURES_INSTANTANEAS = (
    "perda_pct",
    "rtt_ausente",
    "razao_rtt_p95",
    "razao_rtt_p99",
    "razao_jitter_p95",
    "amplitude_rtt_rel",
    "delta_ttl_clip",
    "ttl_reset",
)
FEATURE_DINAMICA = "perdas_consecutivas"
PREFIXO_JANELA = {
    "perda_media": "média de perda_pct na janela, ignorando vazios",
    "rtt_p95_max": "máximo de razao_rtt_p95 na janela",
    "jitter_p95_max": "máximo de razao_jitter_p95 na janela",
    "n_rtt_acima_p95": "número de medições da janela com razao_rtt_p95 > 1",
}

COLUNAS_METADADOS_FINAL = (
    "id_fluxo",
    "anchor_id",
    "probe_id",
    "timestamp",
    "split",
    "classe_atual",
)
COLUNA_ALVO = "alvo"
COLUNAS_PROIBIDAS = (
    "anchor_id",
    "probe_id",
    "timestamp",
    "classe",
    "classe_atual",
    "motivo_rotulagem",
    "ttl",
    "ttl_baseline",
    "latencia_ms",
    "rtt_min",
    "rtt_max",
    "rtt_avg",
    "jitter_ms",
    "p95_rtt_A",
    "p99_rtt_A",
    "p95_jitter_A",
)

COLUNAS_DATASET_ETAPA5 = (
    "anchor_id",
    "probe_id",
    "rtt_min",
    "rtt_max",
    "rtt_avg",
    "perda_pct",
    "jitter_ms",
    "ttl",
    "ttl_baseline",
    "delta_ttl",
    "ttl_changed",
    "latencia_ms",
    "timestamp",
)
COLUNAS_ROTULADO = COLUNAS_DATASET_ETAPA5 + ("classe",)
COLUNAS_AUDITORIA = (
    "anchor_id",
    "probe_id",
    "timestamp",
    "perda_pct",
    "latencia_ms",
    "jitter_ms",
    "p95_rtt_A",
    "p99_rtt_A",
    "p95_jitter_A",
    "classe",
    "motivo_rotulagem",
)
COLUNAS_BASELINE_USADAS = (
    "anchor_id",
    "probe_id",
    "p95_rtt_A",
    "p99_rtt_A",
    "p95_jitter_A",
    "status_baseline",
)
COLUNAS_EXCLUSOES = ("id_fluxo", "motivo", "n_linhas")
FEATURES_SEQUENCIA = (
    "razao_rtt_p95",
    "razao_jitter_p95",
    "perda_media_w3",
    "perdas_consecutivas",
)

# ---------------------------------------------------------------------------
# Página
# ---------------------------------------------------------------------------

TITULO_PAGINA = "Rotulagem e dataset final — Etapa 7"
PAIS_DESTAQUE = "BR"
HTML_FLUXO = None
HTML_MAX_LINHAS = 10
HTML_TAM_SEQUENCIA = 8
ROTULO_VAZIO = "—"
LINK_INICIO = "../../index.html"
LINK_ETAPA7 = "pipeline/07_rotulagem/template/rotulagem.html"
ROTULO_ETAPA7 = "Etapa 7"
TITULO_CARTAO = "Rotulagem e alvo"
MARCADOR_ETAPA7_INICIO = "<!-- etapa7:inicio -->"
MARCADOR_ETAPA7_FIM = "<!-- etapa7:fim -->"
MARCADOR_ETAPA6_FIM = "<!-- etapa6:fim -->"
CASAS_EXIBICAO = 2
TEXTO_INSUFICIENTE = "Dados insuficientes para este cálculo."
REGRA_NOME = "regra operacional adotada neste projeto"
FRASE_BASELINE = "O mesmo valor pode ser normal em um fluxo e anormal em outro."
AVISO_JUNCAO = (
    "A junção é por anchor_id + probe_id. Os dados do Período A não entram no dataset: "
    "só os limites de referência de cada fluxo são consultados."
)
AVISO_AMOSTRA = "Amostra: {mostradas} de {total} linhas. Dados completos em data/dataset_rotulado.csv."
NOTA_RTT_VAZIO = "Perda de 100%: o RTT fica vazio e a classe sai pela perda, sem comparar latência."
NOTA_TAXA_LATENCIA = (
    "RISCO e FALHA por latência têm taxa mínima esperada por construção: "
    "o P95 e o P99 foram definidos para deixar cerca de 5% e 1% do histórico de A acima deles."
)
NOTA_SENTINELA = (
    "O valor -1 é sentinela: a feature dependia de RTT e não havia RTT utilizável. "
    "Não é uma latência negativa e não foi imputada."
)
NOTA_TTL = "ttl_changed = 1 não é falha. O TTL não entra na regra."
NOTA_SEM_BASELINE = "Sem baseline válido a classe fica vazia. Nunca vira OK."
NOTA_PERDA_PACOTES = "Com 3 pacotes por execução não faz sentido falar em 1% ou 5% de perda."
NOTA_DESCARTE = (
    "classe_atual não é feature. As últimas medições de cada fluxo, as que não têm "
    "alvo rotulado e as com intervalo maior que o limite são descartadas."
)
LEGENDA_FUTURO = "O futuro nunca entra nas features."
TITULO_PROXIMO = "Próximo passo"
TEXTO_PROXIMO = "Treinar e avaliar modelos com o dataset_final.csv e o split cronológico."
JUSTIFICATIVAS = (
    "A regra usa a perda, a latência e o jitter da própria linha. Prever a classe dessa mesma linha com essas colunas apenas repetiria a regra.",
    "Prever a medição seguinte transforma o problema em antecipação do estado do fluxo, a partir do histórico recente.",
    "As features só usam medições até t. O rótulo de t+1 nunca entra nas features.",
    "Dá para medir o ganho do modelo contra o baseline de persistência, que repete a classe atual como previsão da próxima.",
)
CUIDADOS = (
    "As classes são uma regra operacional adotada neste projeto, não verdades universais sobre redes.",
    "O modelo pode reproduzir a parte da regra baseada em perda, mas os limiares de latência e jitter vêm do baseline de cada fluxo e não são colunas.",
    "ttl_changed = 1 não é falha.",
    "O alvo é desbalanceado: a acurácia engana.",
    "anchor_id e probe_id podem levar à memorização de fluxos.",
    "O Período B tem só 7 dias.",
)
COR_OK = "#1b7f4e"
COR_RISCO = "#a67c00"
COR_FALHA = "#a33b32"
COR_OK_ESCURO = "#3dbe9a"
COR_RISCO_ESCURO = "#e6c35c"
COR_FALHA_ESCURO = "#e07068"
COR_A = "#0f6e56"
COR_B = "#c45c26"
COR_A_ESCURO = "#3dbe9a"
COR_B_ESCURO = "#e5925d"
ARIA_FLUXO = "Fluxo dos dados: dataset do Período B e baseline do Período A, regras, dataset rotulado, janelas com alvo deslocado e dataset final."
ARIA_TEMPO = "Linha do tempo: janelas de 3, 6 e 12 medições até t viram features; a medição t+1 é só o alvo."
ARIA_BARRAS = "Barras com a quantidade e o percentual de OK, RISCO, FALHA e linhas sem rótulo."


def nomes_janela(tamanho):
    """Nomes das quatro features de uma janela de `tamanho` medições."""
    return (
        f"perda_media_w{tamanho}",
        f"rtt_p95_max_w{tamanho}",
        f"jitter_p95_max_w{tamanho}",
        f"n_rtt_acima_p95_w{tamanho}",
    )


def lista_features():
    """Ordem oficial das features do dataset final."""
    nomes = list(FEATURES_INSTANTANEAS)
    for tamanho in JANELAS:
        nomes.extend(nomes_janela(tamanho))
    nomes.append(FEATURE_DINAMICA)
    return nomes


def definicoes_features():
    """Texto de cada feature, na mesma ordem de lista_features."""
    texto = {
        "perda_pct": "Perda de pacotes da execução t, em percentual.",
        "rtt_ausente": "1 se rtt_avg está vazio; 0 se há RTT médio.",
        "razao_rtt_p95": "rtt_avg dividido pelo P95 de RTT do próprio fluxo.",
        "razao_rtt_p99": "rtt_avg dividido pelo P99 de RTT do próprio fluxo.",
        "razao_jitter_p95": "jitter_ms dividido pelo P95 de jitter do próprio fluxo.",
        "amplitude_rtt_rel": "(rtt_max − rtt_min) / rtt_avg na execução t.",
        "delta_ttl_clip": "delta_ttl limitado ao intervalo [-16, 16]. Se o delta falta, usa a sentinela.",
        "ttl_reset": "1 se o valor absoluto de delta_ttl é pelo menos 64. Delta ausente não é reinício.",
        FEATURE_DINAMICA: "Medições seguidas, terminando em t, com perda maior que 0.",
    }
    for tamanho in JANELAS:
        media, rtt, jitter, n_acima = nomes_janela(tamanho)
        texto[media] = f"Média de perda_pct nas últimas {tamanho} medições, incluindo t, ignorando vazios."
        texto[rtt] = f"Máximo de razao_rtt_p95 nas últimas {tamanho} medições, incluindo t."
        texto[jitter] = f"Máximo de razao_jitter_p95 nas últimas {tamanho} medições, incluindo t."
        texto[n_acima] = f"Quantas das últimas {tamanho} medições, incluindo t, têm razao_rtt_p95 maior que 1."
    return [(nome, texto[nome]) for nome in lista_features()]
