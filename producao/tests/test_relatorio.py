"""Relatório HTML: dados sintéticos, pasta vazia, seções e frases fixas."""

import json

from src.relatorio.gerar import FRASE_CAMPO, FRASE_CAUSA, SECOES, coletar, gerar, renderizar


def _sem_script(pagina: str) -> str:
    return pagina.split("<script>")[0]


def _arvore(tmp_path):
    (tmp_path / "modelo").mkdir()
    (tmp_path / "config").mkdir()
    (tmp_path / "logs" / "predicoes").mkdir(parents=True)
    (tmp_path / "logs" / "coleta").mkdir()
    (tmp_path / "logs" / "estado").mkdir()
    (tmp_path / "logs" / "alertas").mkdir()
    (tmp_path / "relatorios").mkdir()
    (tmp_path / "docs").mkdir()
    (tmp_path / "modelo" / "modelo_manifest.json").write_text(
        json.dumps(
            {
                "modelo_versao": "rf_v1.0.0",
                "sha256": "sha256:abc",
                "treinado_em": "2026-10-05T20:51:08Z",
                "origem_treinado_em": "teste",
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "config" / "criterios.yaml").write_text(
        "modelo_versao: rf_v1.0.0\nlimiares:\n  macro_f1_transicoes_min: null\n",
        encoding="utf-8",
    )
    (tmp_path / "logs" / "predicoes" / "run.jsonl").write_text(
        json.dumps({"ts_previsao": "2026-10-04T18:44:46Z", "rotulo_real": None, "classe_prevista": "OK"}) + "\n",
        encoding="utf-8",
    )
    (tmp_path / "logs" / "coleta" / "run.jsonl").write_text(
        json.dumps({"fluxo_id": "1_2", "situacoes": {"ok": 12, "timeout": 1, "sem_resultado": 0, "invalida": 2}}) + "\n",
        encoding="utf-8",
    )
    (tmp_path / "logs" / "estado" / "9_2.json").write_text(
        json.dumps({"fluxo_id": "9_2", "estado": "aquecimento"}),
        encoding="utf-8",
    )
    (tmp_path / "logs" / "alertas" / "2026-10-06.jsonl").write_text(
        "\n".join(
            [
                json.dumps({"id": "a1", "regra": "psi_feature_importante", "gravidade": "media", "status": "aberto", "evidencia": {"n": 40}}),
                json.dumps({"id": "a2", "regra": "psi_feature_importante", "gravidade": "media", "status": "resolvido", "evidencia": {"n": 40}}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (tmp_path / "docs" / "decisoes.md").write_text(
        "# Decisões\n\n## 2026-10-06\n\nDecisão sintética do relatório.\n",
        encoding="utf-8",
    )
    (tmp_path / "relatorios" / "campo_2026-10-06.json").write_text(
        json.dumps(
            {
                "n": 40,
                "n_rotulos": 40,
                "fatias": {
                    "geral": {
                        "n": 40,
                        "status": "calculado",
                        "macro_f1": 0.812,
                        "macro_f1_persistencia": 0.7,
                        "ganho": 0.112,
                        "recall_falha": 0.5,
                        "ic_macro_f1": [0.6, 0.9],
                        "por_classe": {
                            "OK": {"precisao": 0.9, "recall": 0.8, "f1": 0.85, "suporte": 30},
                            "RISCO": {"precisao": 0.4, "recall": 0.3, "f1": 0.34, "suporte": 5},
                            "FALHA": {"precisao": 0.5, "recall": 0.5, "f1": 0.5, "suporte": 5},
                        },
                        "matriz": [[30, 0, 0], [0, 5, 0], [0, 0, 5]],
                    },
                    "transicoes": {
                        "n": 40,
                        "status": "calculado",
                        "macro_f1": 0.305,
                        "ganho": 999.5,
                        "persistencia": 0,
                    },
                    "por_continente": {"n": 2, "status": "calculado", "macro_f1": 0.99},
                    "probe_vs_anchor": {"n": 0, "status": "INCONCLUSIVO"},
                    "com_e_sem_anchor_dominante": {"n": 0, "status": "INCONCLUSIVO"},
                },
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "relatorios" / "drift_2026-10-06.json").write_text(
        json.dumps(
            {
                "janelas": [
                    {
                        "nome": "7d",
                        "n": 40,
                        "data_drift": {
                            "n": 40,
                            "status": "alerta",
                            "features": {"razao_rtt_p99": {"psi": 0.42, "status": "alerta", "n": 40}},
                        },
                        "fatias": [{"tipo": "anchor", "chave": 3679, "n": 3, "status": "amostra_insuficiente"}],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )


def test_sintetico_tem_secoes_frases_e_n(tmp_path):
    _arvore(tmp_path)
    pagina = _sem_script(renderizar(coletar(tmp_path)))
    for secao in SECOES:
        assert secao in pagina
    assert FRASE_CAUSA in pagina
    assert FRASE_CAMPO in pagina
    assert "0 (por construção)" in pagina
    assert "0,812 (n=40)" in pagina
    assert "0,420 (n=40)" in pagina
    assert "999,500" not in pagina
    assert "0,990" not in pagina
    assert "campo_2026-10-06.json" in pagina
    assert "Decisão sintética do relatório." in pagina
    assert "a1" in pagina
    assert "resolvido" in pagina
    assert "INCONCLUSIVO" in pagina
    assert "http://" not in pagina
    assert "https://" not in pagina
    destino = gerar(tmp_path, tmp_path / "relatorios" / "producao.html")
    assert destino.is_file()


def test_vazio_nao_quebra_e_avisa(tmp_path):
    pagina = _sem_script(renderizar(coletar(tmp_path)))
    for secao in SECOES:
        assert secao in pagina
    assert FRASE_CAUSA in pagina
    assert FRASE_CAMPO in pagina
    assert "Não há" in pagina
    assert "sem previsões (n=0)" in pagina
    assert "http://" not in pagina
