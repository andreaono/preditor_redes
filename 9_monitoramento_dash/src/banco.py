"""SQLite do monitoramento. O coletor escreve; a API lê."""

import json
import sqlite3
from pathlib import Path

import config


ESQUEMA = """
CREATE TABLE IF NOT EXISTS medicoes (
    id INTEGER PRIMARY KEY,
    id_fluxo TEXT NOT NULL,
    msm_id INTEGER,
    probe_id INTEGER,
    timestamp INTEGER NOT NULL,
    min REAL,
    max REAL,
    avg REAL,
    sent INTEGER,
    rcvd INTEGER,
    ttl REAL,
    result TEXT,
    perda_pct REAL,
    jitter_ms REAL,
    latencia_ms REAL,
    ttl_baseline REAL,
    delta_ttl REAL,
    ttl_changed INTEGER,
    classe_real TEXT,
    motivo_rotulagem TEXT,
    lacuna INTEGER NOT NULL DEFAULT 0,
    origem TEXT NOT NULL,
    UNIQUE (msm_id, probe_id, timestamp)
);
CREATE TABLE IF NOT EXISTS previsoes (
    id INTEGER PRIMARY KEY,
    id_fluxo TEXT NOT NULL,
    timestamp_t INTEGER NOT NULL,
    features TEXT,
    prob_OK REAL,
    prob_RISCO REAL,
    prob_FALHA REAL,
    previsto TEXT,
    persistencia TEXT,
    real TEXT,
    acerto INTEGER,
    aquecimento INTEGER NOT NULL DEFAULT 0,
    lacuna INTEGER NOT NULL DEFAULT 0,
    modelo_hash TEXT,
    criado_em TEXT NOT NULL,
    UNIQUE (id_fluxo, timestamp_t)
);
CREATE TABLE IF NOT EXISTS eventos_log (
    id INTEGER PRIMARY KEY,
    ts TEXT NOT NULL,
    nivel TEXT NOT NULL,
    tipo TEXT NOT NULL,
    mensagem TEXT NOT NULL,
    dados TEXT
);
CREATE INDEX IF NOT EXISTS idx_medicoes_fluxo_ts ON medicoes (id_fluxo, timestamp);
CREATE INDEX IF NOT EXISTS idx_previsoes_fluxo_ts ON previsoes (id_fluxo, timestamp_t);
CREATE INDEX IF NOT EXISTS idx_eventos_ts ON eventos_log (ts);
"""


def criar(caminho: Path | None = None) -> Path:
    """Cria o arquivo e as tabelas. Não apaga linhas já gravadas."""
    config.garantir_pastas()
    destino = Path(caminho) if caminho is not None else config.ARQUIVO_DB
    destino.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(destino) as conexao:
        conexao.executescript(ESQUEMA)
        conexao.commit()
    return destino


def conectar(caminho: Path | None = None) -> sqlite3.Connection:
    """Conexão de escrita, usada só pelo coletor."""
    destino = criar(caminho)
    conexao = sqlite3.connect(destino)
    conexao.row_factory = sqlite3.Row
    return conexao


def conectar_leitura(caminho: Path | None = None) -> sqlite3.Connection | None:
    """Abre só para ler. Arquivo ausente não é criado."""
    destino = Path(caminho) if caminho is not None else config.ARQUIVO_DB
    if not destino.is_file():
        return None
    uri = destino.resolve().as_uri() + "?mode=ro"
    conexao = sqlite3.connect(uri, uri=True)
    conexao.row_factory = sqlite3.Row
    return conexao


def inserir_medicao(conexao: sqlite3.Connection, linha: dict) -> bool:
    """Insere uma medição. Devolve False se a chave já existia."""
    colunas = (
        "id_fluxo", "msm_id", "probe_id", "timestamp", "min", "max", "avg", "sent", "rcvd",
        "ttl", "result", "perda_pct", "jitter_ms", "latencia_ms", "ttl_baseline", "delta_ttl",
        "ttl_changed", "classe_real", "motivo_rotulagem", "lacuna", "origem",
    )
    valores = [linha.get(nome) for nome in colunas]
    if isinstance(valores[10], (dict, list)):
        valores[10] = json.dumps(valores[10], ensure_ascii=False)
    cur = conexao.execute(
        f"INSERT OR IGNORE INTO medicoes ({', '.join(colunas)}) VALUES ({', '.join('?' * len(colunas))})",
        valores,
    )
    return cur.rowcount == 1


def inserir_previsao(conexao: sqlite3.Connection, linha: dict) -> None:
    """Grava ou substitui a previsão daquele timestamp."""
    features = linha.get("features")
    if not isinstance(features, str):
        features = json.dumps(features or {}, ensure_ascii=False)
    conexao.execute(
        """
        INSERT INTO previsoes (
            id_fluxo, timestamp_t, features, prob_OK, prob_RISCO, prob_FALHA, previsto,
            persistencia, real, acerto, aquecimento, lacuna, modelo_hash, criado_em
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id_fluxo, timestamp_t) DO UPDATE SET
            features=excluded.features,
            prob_OK=excluded.prob_OK,
            prob_RISCO=excluded.prob_RISCO,
            prob_FALHA=excluded.prob_FALHA,
            previsto=excluded.previsto,
            persistencia=excluded.persistencia,
            aquecimento=excluded.aquecimento,
            lacuna=excluded.lacuna,
            modelo_hash=excluded.modelo_hash
        """,
        (
            linha["id_fluxo"], linha["timestamp_t"], features, linha.get("prob_OK"), linha.get("prob_RISCO"),
            linha.get("prob_FALHA"), linha.get("previsto"), linha.get("persistencia"), linha.get("real"),
            linha.get("acerto"), int(linha.get("aquecimento") or 0), int(linha.get("lacuna") or 0),
            linha.get("modelo_hash"), linha["criado_em"],
        ),
    )


def fechar_previsao(conexao: sqlite3.Connection, id_fluxo: str, timestamp_t: int, real: str, lacuna: int) -> None:
    """Preenche o rótulo real da previsão feita em t quando t+1 chega."""
    conexao.execute(
        """
        UPDATE previsoes
        SET real = ?, acerto = CASE WHEN previsto = ? THEN 1 ELSE 0 END, lacuna = CASE WHEN ? = 1 THEN 1 ELSE lacuna END
        WHERE id_fluxo = ? AND timestamp_t = ?
        """,
        (real, real, lacuna, id_fluxo, timestamp_t),
    )


def inserir_evento(conexao: sqlite3.Connection, ts: str, nivel: str, tipo: str, mensagem: str, dados: dict | None) -> None:
    """Uma linha de log estruturado."""
    conexao.execute(
        "INSERT INTO eventos_log (ts, nivel, tipo, mensagem, dados) VALUES (?, ?, ?, ?, ?)",
        (ts, nivel, tipo, mensagem, json.dumps(dados or {}, ensure_ascii=False)),
    )


