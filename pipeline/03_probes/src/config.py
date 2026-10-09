"""Parâmetros da etapa 3: probes de origem para cada anchor-alvo.

Os limites numéricos das faixas de distância não ficam aqui: são lidos de
meta.faixas_km no JSON da Etapa 1.
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
ARQUIVO_JSON = DATA_DIR / "probes_selecionadas.json"
ARQUIVO_HTML = TEMPLATE_DIR / "probes.html"
ARQUIVO_INDEX = RAIZ_PROJETO / "index.html"
ARQUIVO_PROMPT_ORIGEM = RAIZ_PROJETO / "3_escolhendo_probes.md"
ARQUIVO_PROMPT = PROMPT_DIR / "etapa3_prompt.md"

# ---------------------------------------------------------------------------
# Seleção
# ---------------------------------------------------------------------------

SEED = 42
ADDRESS_FAMILY = 4
MIN_PROBES = 3
MAX_PROBES = 5
PROBES_QUANDO_POUCAS = 1
MIN_PROBES_COMUNS = 1
STATUS_PROBE_OK = "Connected"
STATUS_MEDICAO_OK = "Ongoing"
TIPO_MEDICAO = "ping"
EXIGIR_MEDICAO_PUBLICA = True
TOTAL_DESTINOS = 30
FAIXA_LONGA = "longa"
ORDEM_FAIXAS = ("curta", "media", "longa")
RAIO_TERRA_KM = 6371.0
CONTINENTE_DESCONHECIDO = "desconhecido"
CHAVE_ANCHORS = "anchors"
CHAVE_FAIXAS = "faixas_km"

# ---------------------------------------------------------------------------
# API
# Participantes: GET /measurements/{id}/?optional_fields=current_probes
# devolve os IDs das probes que participam agora. Não é a rota /results/.
# ---------------------------------------------------------------------------

URL_MEASUREMENTS = "https://atlas.ripe.net/api/v2/measurements/"
URL_PROBES = "https://atlas.ripe.net/api/v2/probes/"
URL_ANCHORS = "https://atlas.ripe.net/api/v2/anchors/"
URL_PAGINA_PROBE = "https://atlas.ripe.net/probes/{id}/"
URL_PAGINA_MEDICAO = "https://atlas.ripe.net/measurements/{id}/"
TAMANHO_PAGINA = 100
LOTE_PROBES = 50
CAMPO_PARTICIPANTES = "current_probes"
CAMPO_PARTICIPANTES_OBJETOS = "probes"
RESULTADOS_JANELA_S = 3600
ENDPOINT_PARTICIPANTES = (
    "GET /api/v2/measurements/{id}/?optional_fields=current_probes"
)

# ---------------------------------------------------------------------------
# Rede e cache
# ---------------------------------------------------------------------------

TIMEOUT_S = 90
MAX_TENTATIVAS = 5
BACKOFF_S = 1.0
PAUSA_S = 0.3
CACHE_TTL_HORAS = 24
USER_AGENT = "projeto-preditor-redes/etapa3 (selecao de probes de origem; uso academico)"

# ---------------------------------------------------------------------------
# Página
# ---------------------------------------------------------------------------

TITULO_PAGINA = "Probes de origem — Etapa 3"
PAIS_DESTAQUE = "BR"
DESTINO_HTML = "BR"
ROTULO_VAZIO = "—"
ROTULO_SIM = "sim"
ROTULO_NAO = "não"
TEXTO_SEM_PROBE = "nenhuma probe elegível"
TEXTO_POUCAS_ORIGENS = "poucas origens"
CAMINHO_DADOS_AVISO = "data/probes_selecionadas.json"
LINK_INICIO = "../../index.html"
LINK_ETAPA3 = "pipeline/03_probes/template/probes.html"
ROTULO_ETAPA3 = "Etapa 3"
TITULO_CARTAO = "Probes de origem"
MARCADOR_ETAPA3_INICIO = "<!-- etapa3:inicio -->"
MARCADOR_ETAPA3_FIM = "<!-- etapa3:fim -->"
MARCADOR_ETAPA2_FIM = "<!-- etapa2:fim -->"
CORES_FAIXA = {"curta": "#0f6e56", "media": "#c45c26", "longa": "#3d5a80"}
ROTULO_FAIXA = {"curta": "curta", "media": "média", "longa": "longa"}
COLUNAS = [
    {"chave": "country", "rotulo": "País destino", "tipo": "texto"},
    {"chave": "city_destino", "rotulo": "Cidade destino", "tipo": "texto"},
    {"chave": "country_code", "rotulo": "País origem", "tipo": "texto"},
    {"chave": "city", "rotulo": "Cidade origem", "tipo": "texto"},
    {"chave": "id", "rotulo": "id_probe", "tipo": "link_probe"},
    {"chave": "measurement_id", "rotulo": "id_medição", "tipo": "link_medicao"},
    {"chave": "is_public", "rotulo": "Pública", "tipo": "bool"},
    {"chave": "status", "rotulo": "Status", "tipo": "badge_status"},
    {"chave": "address_v4", "rotulo": "ip_origem", "tipo": "texto"},
    {"chave": "ip_destino", "rotulo": "ip_destino", "tipo": "texto"},
    {"chave": "distance_km", "rotulo": "Distância (km)", "tipo": "numero"},
    {"chave": "distance_band", "rotulo": "Faixa", "tipo": "badge_faixa"},
]

NOMES_PAIS = {
    "AR": "Argentina",
    "AU": "Austrália",
    "BH": "Bahrein",
    "BO": "Bolívia",
    "BR": "Brasil",
    "CA": "Canadá",
    "CH": "Suíça",
    "CL": "Chile",
    "DE": "Alemanha",
    "DO": "República Dominicana",
    "FR": "França",
    "GH": "Gana",
    "IT": "Itália",
    "JP": "Japão",
    "KZ": "Cazaquistão",
    "LK": "Sri Lanka",
    "LY": "Líbia",
    "MX": "México",
    "MY": "Malásia",
    "NC": "Nova Caledônia",
    "NL": "Países Baixos",
    "PE": "Peru",
    "SE": "Suécia",
    "SL": "Serra Leoa",
    "TT": "Trinidad e Tobago",
    "US": "Estados Unidos",
    "UY": "Uruguai",
    "VE": "Venezuela",
    "VN": "Vietnã",
    "ZA": "África do Sul",
}

LIMITACOES = [
    "A API de probes não informa a cidade. Se a probe é uma anchor, a cidade vem de GET /anchors/; nas demais fica vazia.",
    "Probes sem coordenadas não entram na seleção, porque a faixa de distância origem-destino é obrigatória.",
    "measurement_id de cada vínculo é o menor id entre as medições da Etapa 2 em que a probe participa.",
    "O sorteio com seed 42 só desempata candidatas já ordenadas por id. Com 3 ou 4 elegíveis, todas são mantidas.",
    "Não se baixam resultados. O campo current_probes traz só os IDs participantes.",
]

# País → continente (geoesquema ONU M49), para variar a origem.
PAIS_CONTINENTE = {}


def _paises(continente, codigos):
    for codigo in codigos.split():
        if codigo in PAIS_CONTINENTE:
            raise ValueError(f"código de país repetido: {codigo}")
        PAIS_CONTINENTE[codigo] = continente


_paises("África", "DZ EG EH LY MA SD TN BF BJ CI CV GH GM GN GW LR ML MR NE NG SH SL SN TG AO CD CF CG CM GA GQ ST TD BI DJ ER ET IO KE KM MG MU MW MZ RE RW SC SO SS TZ UG YT ZM ZW BW LS NA SZ ZA")
_paises("América do Norte", "BM CA GL PM US UM BZ CR GT HN MX NI PA SV AG AI AW BB BL BQ BS CU CW DM DO GD GP HT JM KN KY LC MF MQ MS PR SX TC TT VC VG VI")
_paises("América do Sul", "AR BO BR CL CO EC FK GF GY PE PY SR UY VE")
_paises("Ásia", "KG KZ TJ TM UZ CN HK JP KP KR MN MO TW BN ID KH LA MM MY PH SG TH TL VN AF BD BT IN IR LK MV NP PK AE AM AZ BH CY GE IL IQ JO KW LB OM PS QA SA SY TR YE")
_paises("Europa", "AX DK EE FI FO GB GG IE IM IS JE LT LV NO SE SJ UK AT BE CH DE FR LI LU MC NL BG BY CZ HU MD PL RO RU SK UA AD AL BA ES GI GR HR IT ME MK MT PT RS SI SM VA XK")
_paises("Oceania", "AU CC CX NF NZ FJ NC PG SB VU FM GU KI MH MP NR PW AS CK NU PF PN TK TO TV WF WS")
_paises("Antártida", "AQ BV GS HM TF")
