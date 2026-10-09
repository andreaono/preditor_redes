"""Parâmetros da etapa 5: períodos A (baseline) e B (dataset) e features.

As datas estão preenchidas de propósito. Se inicio ou fim ficarem vazios, a
coleta aborta. A janela é fechada à direita: o instante final de A é o
inicial de B, sem sobreposição.

B termina em 2026-10-05T18:00:00Z, o mesmo fim de hora UTC do ensaio da
Etapa 4. A são os sete dias imediatamente anteriores. Nada disso é
calculado em silêncio na hora de rodar.
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
ARQUIVO_ANCHORS_ETAPA1 = RAIZ_PROJETO / "pipeline" / "01_anchors" / "data" / "anchors_selecionadas.json"
ARQUIVO_MEDICOES_ETAPA2 = RAIZ_PROJETO / "pipeline" / "02_medicoes" / "data" / "medicoes_ping_ongoing.json"
ARQUIVO_PROBES_ETAPA3 = RAIZ_PROJETO / "pipeline" / "03_probes" / "data" / "probes_selecionadas.json"
ARQUIVO_CSV_BRUTO = DATA_DIR / "fluxo_bruto.csv"
ARQUIVO_DATASET = DATA_DIR / "dataset_processado.csv"
ARQUIVO_BASELINE = DATA_DIR / "baseline_ttl_por_par.csv"
ARQUIVO_EXCLUSOES = DATA_DIR / "exclusoes_processamento.csv"
ARQUIVO_QUALIDADE = DATA_DIR / "qualidade_processamento.json"
ARQUIVO_METADADOS = DATA_DIR / "metadados.json"
ARQUIVO_HTML = TEMPLATE_DIR / "periodos.html"
ARQUIVO_INDEX = RAIZ_PROJETO / "index.html"
ARQUIVO_PROMPT_ORIGEM = RAIZ_PROJETO / "5_criar_dataset_baseline_base.md"
ARQUIVO_PROMPT = PROMPT_DIR / "etapa5_prompt.md"

# ---------------------------------------------------------------------------
# Coleta
# ---------------------------------------------------------------------------

ADDRESS_FAMILY = 4
TIPO_MEDICAO = "ping"
STATUS_ONGOING_NOME = "Ongoing"
FUSO = "UTC"
FORMATO_ID_FLUXO = "{probe_id}_{anchor_id}"
# Com intervalo de 240 s, sete dias esperam 2520 execuções. 80% ainda exige
# a maior parte da semana e deixa de fora probe que só apareceu num trecho curto.
COBERTURA_MINIMA_PERCENT = 80
PERIODO_BASELINE = "A"
PERIODO_DATASET = "B"
CLASSE_AMBOS = "A+B"
CLASSE_SO_DATASET = "B"
CLASSE_SO_BASELINE = "A"
CLASSE_NENHUM = "nenhum"
ORDEM_CLASSES = (CLASSE_AMBOS, CLASSE_SO_DATASET, CLASSE_SO_BASELINE, CLASSE_NENHUM)

PERIODOS = (
    {
        "nome": "A",
        "inicio": "2026-09-21T18:00:00+00:00",
        "fim": "2026-09-28T18:00:00+00:00",
        "papel": "baseline",
        "justificativa": (
            "Sete dias imediatamente anteriores ao período B. "
            "Servem somente para calcular a mediana do TTL de cada par. "
            "Nenhuma linha deste período entra no dataset."
        ),
    },
    {
        "nome": "B",
        "inicio": "2026-09-28T18:00:00+00:00",
        "fim": "2026-10-05T18:00:00+00:00",
        "papel": "dataset",
        "justificativa": (
            "Sete dias de linhas do dataset, encerrados em 2026-10-05T18:00:00Z, "
            "o fim da hora UTC já usado no ensaio da Etapa 4. "
            "O baseline não é recalculado com estas linhas."
        ),
    },
)

MOTIVO_OK = "ok"
MOTIVO_SEM_RESULTADO = "sem resultados na janela"
MOTIVO_COBERTURA = "cobertura abaixo do mínimo ({cobertura}%)"
MOTIVO_TTL = "menos de {n} amostras de TTL em A"
MOTIVO_REDE = "erro de rede ({mensagem})"
CASAS_MOTIVO_COBERTURA = 2
CASAS_COBERTURA = 4

COLUNAS_CSV_BRUTO = [
    "id_fluxo",
    "periodo",
    "anchor_id",
    "anchor_ip",
    "probe_id",
    "probe_ip",
    "msm_id",
    "ttl",
    "result",
    "dup",
    "rcvd",
    "sent",
    "min",
    "max",
    "avg",
    "timestamp",
    "type",
    "packets",
    "interval",
]

CHAVE_ANCHORS = "anchors"
CHAVE_PROBES = "probes"
CHAVE_MEDICOES = "medicoes"
CAMPO_ID = "id"
CAMPO_MEASUREMENT_ID = "measurement_id"
CAMPO_AF = "af"
CAMPO_COUNTRY = "country"
CAMPO_COUNTRY_CODE = "country_code"
CAMPO_CITY = "city"
CAMPO_IS_ANCHOR = "is_anchor"
CAMPO_IP = "ip_v4"
CAMPO_ADDRESS = "address_v4"
CAMPO_HOSTNAME = "hostname"
CAMPO_IS_DISABLED = "is_disabled"
CAMPO_STATUS = "status"
CAMPO_STATUS_NOME = "name"
CAMPO_INTERVAL = "interval"
CAMPO_PACKETS = "packets"
CAMPO_TYPE = "type"
CAMPO_IS_PUBLIC = "is_public"
CAMPO_PRB_ID = "prb_id"
CAMPO_SRC = "src_addr"
CAMPO_DST = "dst_addr"
CAMPO_TIMESTAMP = "timestamp"
CAMPO_TTL = "ttl"
CAMPO_RESULT = "result"
CAMPO_SENT = "sent"
CAMPO_RCVD = "rcvd"
CAMPO_MIN = "min"
CAMPO_MAX = "max"
CAMPO_AVG = "avg"
CAMPO_DUP = "dup"
CAMPO_RTT = "rtt"
MARCADOR_TIMEOUT = "x"
CAMPOS_MEDICAO = ("id", "interval", "is_public", "packets", "target", "target_ip", "type", "af")
CAMPOS_ANCHOR = (
    "id",
    "hostname",
    "fqdn",
    "probe",
    "ip_v4",
    "city",
    "country",
    "company",
    "geometry",
    "is_disabled",
)
CAMPOS_RESULTADO_LINHA = ("ttl", "result", "dup", "rcvd", "sent", "min", "max", "avg", "timestamp", "type")

# ---------------------------------------------------------------------------
# Processamento
# ---------------------------------------------------------------------------

MIN_AMOSTRAS_BASELINE = 30
TOLERANCIA_DIVERGENCIA_MS = 0.01
COM_DATETIME = False
COLUNA_DATETIME = "datetime_utc"
COLUNAS_DATASET = [
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
]
COLUNAS_BASELINE = [
    "anchor_id",
    "probe_id",
    "ttl_baseline",
    "n_amostras_A",
    "ttl_min_A",
    "ttl_max_A",
    "n_ttl_distintos_A",
]
COLUNAS_EXCLUSOES = ["anchor_id", "probe_id", "msm_id", "id_fluxo", "motivo", "n"]
ETAPA_QUALIDADE = "5"
MOTIVO_AF = "af da medição divergente entre as fontes ou diferente de 4"
MOTIVO_TIPO = "medição não é ping Ongoing"
MOTIVO_ANCHOR_DESATIVADA = "anchor com is_disabled diferente de false"
MOTIVO_TIPO_LINHA = "type diferente de ping"
MOTIVO_TIMESTAMP = "timestamp fora da janela do período"
CHAVE_FEATURES = "features"

FEATURES = [
    {"feature": "anchor_id", "origem": "fluxo", "tipo": "Original", "formula": "id da anchor de destino", "unidade": "—", "interpretacao": "Identifica o destino. Não é o msm_id nem o probe_id."},
    {"feature": "probe_id", "origem": "prb_id", "tipo": "Original", "formula": "valor retornado", "unidade": "—", "interpretacao": "Identifica a probe de origem."},
    {"feature": "rtt_min", "origem": "min", "tipo": "Original/recalculável", "formula": "usar min; se ausente, min(rtts)", "unidade": "ms", "interpretacao": "Menor RTT da execução. Vazio se a perda for 100%."},
    {"feature": "rtt_max", "origem": "max", "tipo": "Original/recalculável", "formula": "usar max; se ausente, max(rtts)", "unidade": "ms", "interpretacao": "Maior RTT da execução. Vazio se a perda for 100%."},
    {"feature": "rtt_avg", "origem": "avg", "tipo": "Original/recalculável", "formula": "usar avg; se ausente, sum(rtts)/len(rtts)", "unidade": "ms", "interpretacao": "RTT médio da execução. Vazio se a perda for 100%."},
    {"feature": "perda_pct", "origem": "sent, rcvd", "tipo": "Derivada", "formula": "((sent − rcvd) / sent) × 100, só se sent > 0", "unidade": "%", "interpretacao": "Percentual de pacotes sem resposta. 100 quando rcvd é 0. Vazio se sent é 0."},
    {"feature": "jitter_ms", "origem": "result[].rtt", "tipo": "Derivada", "formula": "statistics.pstdev(rtts); 0 se há 1 RTT; vazio se nenhum", "unidade": "ms", "interpretacao": "Dispersão dos RTTs da execução. Com 3 pacotes, a amostra é pequena."},
    {"feature": "ttl", "origem": "ttl", "tipo": "Original", "formula": "valor retornado, sem alterar", "unidade": "—", "interpretacao": "TTL observado no pacote de resposta. Não é número de hops."},
    {"feature": "ttl_baseline", "origem": "ttl em A", "tipo": "Derivada", "formula": "mediana de ttl por par somente no período A", "unidade": "—", "interpretacao": "TTL típico do par antes do dataset. Vazio se o par não tem baseline."},
    {"feature": "delta_ttl", "origem": "ttl, ttl_baseline", "tipo": "Derivada", "formula": "ttl − ttl_baseline, com sinal", "unidade": "—", "interpretacao": "Quanto o TTL se afastou do histórico. Negativo também é válido. Vazio sem baseline ou sem ttl."},
    {"feature": "ttl_changed", "origem": "delta_ttl", "tipo": "Derivada", "formula": "int(delta_ttl != 0)", "unidade": "0/1", "interpretacao": "1 só indica que o TTL mudou em relação ao par. Não é falha de rede."},
    {"feature": "latencia_ms", "origem": "rtt_avg", "tipo": "Renomeada", "formula": "latencia_ms = rtt_avg", "unidade": "ms", "interpretacao": "O mesmo valor de rtt_avg. As duas colunas são colineares."},
    {"feature": "timestamp", "origem": "timestamp", "tipo": "Original", "formula": "Unix timestamp original", "unidade": "s (UTC)", "interpretacao": "Instante da execução. No dataset, cai dentro da janela B."},
]

CUIDADOS_ML = [
    "Vazamento: ttl_baseline usa somente o período A. Nenhuma linha de B entra nessa mediana, e nenhuma linha de A entra no dataset.",
    "latencia_ms e rtt_avg são a mesma informação. Usar as duas juntas é colinearidade.",
    "ttl_changed não é rótulo de falha. O valor 1 significa apenas que o TTL diferiu do histórico do par.",
    "Não preencher vazios com 0. Zero seria um TTL, uma perda ou um jitter reais.",
    "jitter_ms depende de poucas amostras: cada execução manda 3 pacotes.",
    "Pares sem baseline ficam com ttl_baseline, delta_ttl e ttl_changed vazios. Não misture esses fluxos com os demais sem uma decisão explícita.",
]

# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

URL_MEASUREMENTS = "https://atlas.ripe.net/api/v2/measurements/{id}/"
URL_ANCHORS = "https://atlas.ripe.net/api/v2/anchors/{id}/"
URL_RESULTS = "https://atlas.ripe.net/api/v2/measurements/{msm_id}/results/"
URL_PAGINA_PROBE = "https://atlas.ripe.net/probes/{id}/"
URL_PAGINA_MEDICAO = "https://atlas.ripe.net/measurements/{id}/"
PARAM_PROBE_IDS = "probe_ids"
PARAM_START = "start"
PARAM_STOP = "stop"
PARAM_FORMAT = "format"
FORMATO_RESULTADOS = "json"
ORDEM_PARAMS_RESULTS = (PARAM_PROBE_IDS, PARAM_START, PARAM_STOP, PARAM_FORMAT)
MAX_BYTES_RESPOSTA = 40_000_000

# ---------------------------------------------------------------------------
# Rede e cache
# ---------------------------------------------------------------------------

TIMEOUT_S = 180
MAX_TENTATIVAS = 5
BACKOFF_S = 2.0
PAUSA_S = 0.4
CACHE_TTL_HORAS = 24
USER_AGENT = "projeto-preditor-redes/etapa5 (periodos A e B; uso academico)"

# ---------------------------------------------------------------------------
# Página
# ---------------------------------------------------------------------------

TITULO_PAGINA = "Períodos e dataset — Etapa 5"
PAIS_DESTAQUE = "BR"
# None: primeiro fluxo A+B cuja anchor de destino é a do Brasil.
HTML_FLUXO = None
HTML_MAX_LINHAS = 10
ROTULO_VAZIO = "—"
ROTULO_SIM = "sim"
ROTULO_NAO = "não"
LINK_INICIO = "../../index.html"
LINK_ETAPA5 = "pipeline/05_periodos/template/periodos.html"
ROTULO_ETAPA5 = "Etapa 5"
TITULO_CARTAO = "Períodos e dataset"
MARCADOR_ETAPA5_INICIO = "<!-- etapa5:inicio -->"
MARCADOR_ETAPA5_FIM = "<!-- etapa5:fim -->"
MARCADOR_ETAPA4_FIM = "<!-- etapa4:fim -->"
CAMINHO_DATASET_AVISO = "data/dataset_processado.csv"
AVISO_AMOSTRA = "Amostra: {mostradas} de {total} linhas. Dados completos em `{caminho}`."
LEGENDA_TEMPO = "A: só calcula `ttl_baseline`; B: linhas do dataset. O baseline não entra no dataset."
TITULO_PIPELINE = "Pipeline de construção"
ROTULO_SO_A = "só período A"
ROTULO_SO_B = "só período B"
ROTULO_JUNCAO = "junção por par"
ROTULO_JUNCAO_CHAVE = "probe_id + anchor_id"
ROTULO_PIPELINE_MEDIANA = "mediana do TTL por par"
ROTULO_PIPELINE_BASELINE = "ttl_baseline"
ROTULO_PIPELINE_RTTS = "extração de rtts"
ROTULO_PIPELINE_FEATURES = "features"
SEPARADOR_PIPELINE = " · "
TEXTO_REGRA = (
    "Um fluxo entra no período se a cobertura é de pelo menos {cobertura}% "
    "do que o intervalo da medição faria esperar. Em A, também são necessárias "
    "pelo menos {amostras} amostras de TTL válidas para haver baseline."
)
TEXTO_CIDADE = (
    "A API de probes não informa a cidade. Se a origem é uma anchor, a cidade vem do campo já gravado na Etapa 3; senão fica null e a página mostra —."
)
LIMITACOES = [
    TEXTO_CIDADE,
    "O dataset final é somente IPv4. Medição com af divergente ou diferente de 4 fica de fora, com motivo em exclusoes_processamento.csv.",
    "ttl_changed igual a 1 não é falha de rede.",
    "O TTL observado não é número de hops.",
]
LIMITE_LISTA_QUALIDADE = 15
COR_A = "#0f6e56"
COR_B = "#c45c26"
COR_A_ESCURO = "#3dbe9a"
COR_B_ESCURO = "#e5925d"
SELOS = (
    "A e B sem sobreposição",
    "0 linhas de A no dataset",
)
COLUNAS_GLOSSARIO_FEATURE = ("Feature", "Origem", "Original/Derivada", "Fórmula", "Unidade", "Interpretação")
TITULO_CUIDADOS = "Cuidados em ML"
TITULO_QUALIDADE = "Qualidade"
TITULO_EXEMPLO = "Exemplo trabalhado"
ROTULO_EXEMPLO_LINHA = "Linha do período B"
TITULO_AMOSTRA = "Amostra do dataset final"
TITULO_FEATURES = "Construção das features"
TITULO_FLUXOS = "Fluxos"
TITULO_PARAMETROS = "Parâmetros da coleta"
ROTULO_PERDA_TOTAL = "Perda 100%"
ROTULO_TTL_AUSENTE = "TTL ausente"
ARIA_PIPELINE = (
    "Trilha A lê o fluxo bruto do período A, calcula a mediana do TTL por par e produz ttl_baseline. "
    "Trilha B lê o fluxo bruto do período B, extrai os rtts e calcula as features. "
    "As duas trilhas se juntam por par probe_id e anchor_id em dataset_processado.csv. "
    "Nenhuma linha de A entra no dataset."
)
