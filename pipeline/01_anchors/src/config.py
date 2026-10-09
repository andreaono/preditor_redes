"""Parâmetros da etapa 1: seleção de anchors-alvo IPv4 do RIPE Atlas.

Todos os caminhos são relativos a esta pasta (pipeline/01_anchors/),
resolvidos a partir da localização deste arquivo.
"""

from pathlib import Path

# ---------------------------------------------------------------------------
# Caminhos
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent.parent
CACHE_DIR = BASE_DIR / "cache"
PROMPT_DIR = BASE_DIR / "prompt"
DATA_DIR = BASE_DIR / "data"
SRC_DIR = BASE_DIR / "src"
TEMPLATE_DIR = BASE_DIR / "template"
ARQUIVO_JSON = DATA_DIR / "anchors_selecionadas.json"
ARQUIVO_HTML = TEMPLATE_DIR / "etapa1_anchors.html"

# ---------------------------------------------------------------------------
# Seleção
# ---------------------------------------------------------------------------

SEED = 42
TOTAL_ANCHORS = 30
PAIS_BRASIL = "BR"
MAX_ANCHORS_POR_ASN = 1
MAX_ANCHORS_POR_ASN_FALLBACK = 2
MAX_EUROPA = 6
ADDRESS_FAMILY = 4

# Nomes usados nas cotas, no JSON e na página.
AFRICA = "África"
AMERICA_DO_NORTE = "América do Norte"
AMERICA_DO_SUL = "América do Sul"
ASIA = "Ásia"
EUROPA = "Europa"
OCEANIA = "Oceania"
ANTARTIDA = "Antártida"
CONTINENTE_EUROPA = EUROPA

# Cotas mínimas. A soma (20) fica abaixo de TOTAL_ANCHORS para deixar
# folga às três faixas de distância e ao teto da Europa (MAX_EUROPA).
# A anchor brasileira conta para a cota da América do Sul.
# Antártida em 0: não há operação regular de anchors do RIPE Atlas lá.
# Se aparecer alguma elegível, COBRIR_TODOS_CONTINENTES inclui ao menos uma.
COTAS_CONTINENTE = {
    AFRICA: 3,
    AMERICA_DO_NORTE: 3,
    AMERICA_DO_SUL: 3,
    ASIA: 5,
    EUROPA: 4,
    OCEANIA: 2,
    ANTARTIDA: 0,
}
COBRIR_TODOS_CONTINENTES = True

# curta: distância < 4000 km; média: 4000 <= d < 10000; longa: d >= 10000.
FAIXAS_KM = {
    "curta": {"max_exclusivo": 4000},
    "media": {"max_exclusivo": 10000},
}
FAIXA_LONGA = "longa"
ORDEM_FAIXAS = ["curta", "media", "longa"]
MIN_POR_FAIXA = 1
RAIO_TERRA_KM = 6371.0

# ---------------------------------------------------------------------------
# API
# Documentação consultada em 2026-10-05:
# https://atlas.ripe.net/docs/apis/rest-api-manual/
# https://atlas.ripe.net/docs/apis/rest-api-reference/anchors/anchors_list/
# https://atlas.ripe.net/docs/apis/rest-api-reference/anchor-measurements/anchor_measurements_list/
# https://atlas.ripe.net/docs/apis/rest-api-reference/measurements/measurements_retrieve/
# probe_status 1 = Connected. status.id 2 da medição = Ongoing.
# ---------------------------------------------------------------------------

URL_ANCHORS = "https://atlas.ripe.net/api/v2/anchors/"
URL_ANCHOR_MEASUREMENTS = "https://atlas.ripe.net/api/v2/anchor-measurements/"
URL_MEASUREMENTS = "https://atlas.ripe.net/api/v2/measurements/"
URL_PROBES = "https://atlas.ripe.net/api/v2/probes/"
TAMANHO_PAGINA = 500
PROBE_STATUS_CONNECTED = 1
STATUS_MEDICAO_ONGOING = 2
NOME_STATUS_ONGOING = "Ongoing"
TIPO_MEDICAO_MESH = "ping"
PARAM_INCLUDE_MEASUREMENT = "measurement"
EXIGIR_MEDICAO_PUBLICA = True

# ---------------------------------------------------------------------------
# Rede e cache
# ---------------------------------------------------------------------------

TIMEOUT_S = 90
MAX_TENTATIVAS = 5
BACKOFF_S = 1.0
CACHE_TTL_HORAS = 24
USER_AGENT = "projeto-preditor-redes/etapa1 (selecao de anchors RIPE Atlas; uso academico)"

# ---------------------------------------------------------------------------
# Página
# ---------------------------------------------------------------------------

TITULO_PAGINA = "Anchors-alvo do RIPE Atlas — Etapa 1"
MAPA_HABILITADO = True
URL_LEAFLET_CDN = "https://unpkg.com/leaflet@1.9.4/dist/"
URL_TILES = "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
ATRIBUICAO_MAPA = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'

TEXTO_MULTIPLAS_ORIGENS = (
    "Uma única relação probe–anchor representa apenas um caminho específico de rede. "
    "Esse caminho pode ser influenciado pela localização da probe, pelo ASN de origem, "
    "pela rota utilizada e pelas condições particulares daquele trajeto. Ao utilizar de "
    "três a cinco probes para a mesma anchor, o projeto observa o mesmo destino a partir "
    "de diferentes caminhos de rede."
)
DIAGRAMA_ORIGENS = (
    "Probe A →\n"
    "Probe B →\n"
    "Probe C → Anchor X\n"
    "Probe D →\n"
    "Probe E →"
)
TITULO_BLOCO_ORIGENS = "Múltiplas origens por anchor"
ROTULO_VAZIO = "—"
ROTULOS_COLUNAS = [
    {"chave": "id", "rotulo": "ID", "tipo": "numero"},
    {"chave": "hostname", "rotulo": "Hostname", "tipo": "texto"},
    {"chave": "fqdn", "rotulo": "FQDN", "tipo": "texto"},
    {"chave": "ip_v4", "rotulo": "IPv4", "tipo": "texto"},
    {"chave": "city", "rotulo": "Cidade", "tipo": "texto"},
    {"chave": "country", "rotulo": "País", "tipo": "texto"},
    {"chave": "company", "rotulo": "Empresa", "tipo": "texto"},
    {"chave": "coordinates", "rotulo": "Coordenadas", "tipo": "texto"},
    {"chave": "asn_v4", "rotulo": "ASN v4", "tipo": "numero"},
    {"chave": "continent", "rotulo": "Continente", "tipo": "texto"},
    {"chave": "region", "rotulo": "Região", "tipo": "texto"},
    {"chave": "mesh_measurement_ids", "rotulo": "Medições mesh IPv4", "tipo": "texto"},
    {"chave": "interval_segundos", "rotulo": "Intervalo (s)", "tipo": "numero"},
    {"chave": "estratos", "rotulo": "Estratos", "tipo": "numero"},
]

# ---------------------------------------------------------------------------
# País → continente e região (geoesquema ONU M49, nomes em português).
# Turquia e Chipre ficam na Ásia Ocidental; a Rússia, na Europa Oriental.
# América Central e Caribe entram no continente América do Norte.
# ---------------------------------------------------------------------------


def _mapa(continente, regiao, codigos):
    saida = {}
    for codigo in codigos.split():
        if codigo in PAIS_META:
            raise ValueError(f"código de país repetido no mapa: {codigo}")
        saida[codigo] = {"continente": continente, "regiao": regiao}
        PAIS_META[codigo] = saida[codigo]
    return saida


PAIS_META = {}

_mapa(AFRICA, "África Setentrional", "DZ EG EH LY MA SD TN")
_mapa(AFRICA, "África Ocidental", "BF BJ CI CV GH GM GN GW LR ML MR NE NG SH SL SN TG")
_mapa(AFRICA, "África Central", "AO CD CF CG CM GA GQ ST TD")
_mapa(AFRICA, "África Oriental", "BI DJ ER ET IO KE KM MG MU MW MZ RE RW SC SO SS TZ UG YT ZM ZW")
_mapa(AFRICA, "África Austral", "BW LS NA SZ ZA")

_mapa(AMERICA_DO_NORTE, "América do Norte", "BM CA GL PM US UM")
_mapa(AMERICA_DO_NORTE, "América Central", "BZ CR GT HN MX NI PA SV")
_mapa(AMERICA_DO_NORTE, "Caribe", "AG AI AW BB BL BQ BS CU CW DM DO GD GP HT JM KN KY LC MF MQ MS PR SX TC TT VC VG VI")

_mapa(AMERICA_DO_SUL, "América do Sul", "AR BO BR CL CO EC FK GF GY PE PY SR UY VE")

_mapa(ASIA, "Ásia Central", "KG KZ TJ TM UZ")
_mapa(ASIA, "Ásia Oriental", "CN HK JP KP KR MN MO TW")
_mapa(ASIA, "Sudeste Asiático", "BN ID KH LA MM MY PH SG TH TL VN")
_mapa(ASIA, "Ásia Meridional", "AF BD BT IN IR LK MV NP PK")
_mapa(ASIA, "Ásia Ocidental", "AE AM AZ BH CY GE IL IQ JO KW LB OM PS QA SA SY TR YE")

_mapa(EUROPA, "Europa Setentrional", "AX DK EE FI FO GB GG IE IM IS JE LT LV NO SE SJ UK")
_mapa(EUROPA, "Europa Ocidental", "AT BE CH DE FR LI LU MC NL")
_mapa(EUROPA, "Europa Oriental", "BG BY CZ HU MD PL RO RU SK UA")
_mapa(EUROPA, "Europa Meridional", "AD AL BA ES GI GR HR IT ME MK MT PT RS SI SM VA XK")

_mapa(OCEANIA, "Austrália e Nova Zelândia", "AU CC CX NF NZ")
_mapa(OCEANIA, "Melanésia", "FJ NC PG SB VU")
_mapa(OCEANIA, "Micronésia", "FM GU KI MH MP NR PW")
_mapa(OCEANIA, "Polinésia", "AS CK NU PF PN TK TO TV WF WS")

_mapa(ANTARTIDA, "Antártida", "AQ BV GS HM TF")

assert CONTINENTE_EUROPA in COTAS_CONTINENTE
assert COTAS_CONTINENTE[CONTINENTE_EUROPA] <= MAX_EUROPA
assert sum(COTAS_CONTINENTE.values()) <= TOTAL_ANCHORS
assert set(FAIXAS_KM) < set(ORDEM_FAIXAS)
assert FAIXA_LONGA in ORDEM_FAIXAS
assert FAIXA_LONGA not in FAIXAS_KM
assert PAIS_BRASIL in PAIS_META
