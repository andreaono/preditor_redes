"""Parâmetros da etapa 2: medições ping IPv4 ongoing com as anchors como destino.

Caminhos resolvidos a partir deste arquivo.
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
ARQUIVO_JSON = DATA_DIR / "medicoes_ping_ongoing.json"
ARQUIVO_HTML = TEMPLATE_DIR / "medicoes.html"
ARQUIVO_INDEX = RAIZ_PROJETO / "index.html"
ARQUIVO_PROMPT_ORIGEM = RAIZ_PROJETO / "2_medicoes_ping.md" / "prompt" / "2_medicoes_ping.md"
ARQUIVO_PROMPT = PROMPT_DIR / "etapa2_prompt.md"

# ---------------------------------------------------------------------------
# Filtros
# Confirmados em 2026-10-05 na anchor BR (id 3679): status 2 = Ongoing.
# ---------------------------------------------------------------------------

ADDRESS_FAMILY = 4
TIPO_MEDICAO = "ping"
STATUS_ONGOING_ID = 2
STATUS_ONGOING_NOME = "Ongoing"
TOTAL_ANCHORS = 30
CHAVE_LISTA_ANCHORS = "anchors"
CAMPO_MESH_IDS = "mesh_measurement_ids"
FILTROS_ALVO = ("target", "target_ip")
CAMPO_DO_FILTRO = {
    "target": "fqdn",
    "target_ip": "ip_v4",
}

# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

URL_MEASUREMENTS = "https://atlas.ripe.net/api/v2/measurements/"
URL_ANCHOR_MEASUREMENTS = "https://atlas.ripe.net/api/v2/anchor-measurements/"
URL_ANCHORS = "https://atlas.ripe.net/api/v2/anchors/"
URL_PAGINA_MEDICAO = "https://atlas.ripe.net/measurements/{id}/"
TAMANHO_PAGINA = 100

ESTRATEGIA_BUSCA = (
    "Para cada anchor da chave anchors, consultar GET /measurements/ com "
    "type=ping, af=4 e status=2, primeiro com target=<fqdn> e depois com "
    "target_ip=<ip_v4>. Deduplicar por id. Não usar target_asn. "
    "Todo mesh_measurement_ids ausente dessa busca é conferido em "
    "GET /measurements/{id}/, sem baixar /results/."
)
LIMITACOES = [
    "target_asn filtra o AS inteiro, não a anchor, e fica de fora da busca.",
    "GET /anchors/{id}/measurements/ respondeu 405 na anchor 3679 e não é usado.",
    "A listagem completa de anchor-measurements não é repetida: a Etapa 1 já gravou os IDs mesh, e o filtro type desse endpoint é ignorado pela API.",
    "Somente metadados são baixados; URLs de /results/ não são consultadas.",
]

# ---------------------------------------------------------------------------
# Rede e cache
# ---------------------------------------------------------------------------

TIMEOUT_S = 60
MAX_TENTATIVAS = 5
BACKOFF_S = 1.0
PAUSA_S = 0.4
CACHE_TTL_HORAS = 24
USER_AGENT = "projeto-preditor-redes/etapa2 (medicoes ping ongoing; uso academico)"

# ---------------------------------------------------------------------------
# Página
# ---------------------------------------------------------------------------

TITULO_PAGINA = "Medições ping ongoing — Etapa 2"
PAIS_DESTAQUE = "BR"
SEED = 42
HTML_MAX_ANCHORS = 5
HTML_MAX_MEDICOES_POR_ANCHOR = 5
ROTULO_VAZIO = "—"
TEXTO_SEM_MEDICAO = "nenhuma medição ongoing encontrada"
CAMINHO_DADOS_AVISO = "data/medicoes_ping_ongoing.json"
LINK_INICIO = "../../index.html"
LINK_ETAPA1 = "pipeline/01_anchors/template/etapa1_anchors.html"
LINK_ETAPA2 = "pipeline/02_medicoes/template/medicoes.html"
MARCADOR_ETAPA2_INICIO = "<!-- etapa2:inicio -->"
MARCADOR_ETAPA2_FIM = "<!-- etapa2:fim -->"
ROTULO_ETAPA1 = "Etapa 1"
ROTULO_ETAPA2 = "Etapa 2"
TITULO_INDEX = "Preditor de redes — RIPE Atlas"
TEXTO_ETAPA1 = "30 anchors-alvo IPv4 escolhidas por amostragem estratificada."
CAMPOS_MEDICAO = (
    "id",
    "type",
    "status",
    "af",
    "interval",
    "is_public",
    "description",
    "start_time",
    "target",
    "target_ip",
    "participant_count",
)
CAMPOS_ANCHOR = ("id", "hostname", "fqdn", "ip_v4", "city", "country")
COLUNAS = [
    {"chave": "country", "rotulo": "País", "tipo": "texto"},
    {"chave": "city", "rotulo": "Cidade", "tipo": "texto"},
    {"chave": "hostname", "rotulo": "Hostname", "tipo": "texto"},
    {"chave": "id", "rotulo": "Medição", "tipo": "numero"},
    {"chave": "type", "rotulo": "Tipo", "tipo": "texto"},
    {"chave": "participant_count", "rotulo": "Participantes", "tipo": "numero"},
    {"chave": "status", "rotulo": "Status", "tipo": "texto"},
]
