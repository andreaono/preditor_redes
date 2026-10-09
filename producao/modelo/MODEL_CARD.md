# Cartão do modelo

Versão: `rf_v1.0.0`. Família: Random Forest. Semente: 42.

O artefato foi empacotado a partir do joblib já escolhido na validação. Não houve novo treino. O split de teste não foi lido para montar a amostra.

## Dados

Data registrada: 2026-10-05T20:51:08Z. Origem dessa data: mtime UTC do joblib original; o JSON do modelo escolhido não traz um instante de treino separado.
Hash das linhas de treino do dataset final: `sha256:a6098ddcb4033ba2756eddcf9bcaee7dbaa1e871617ddcff682786abf9768016`. SHA-256 do cabeçalho mais as 241359 linhas com split=treino, na ordem do arquivo, campos unidos por |. Não inclui validação nem teste.
Hash do arquivo inteiro do dataset final: `sha256:125453f154616b6d02587f9577aab14828002ebc31d8ae053771780058d9b997`. SHA-256 dos bytes do arquivo dataset_final.csv, com os três splits.

## Features

A ordem é a de `lista_features` da etapa 7. Os grupos são instantânea, janela e dinâmica.

- instantânea: perda_pct, rtt_ausente, razao_rtt_p95, razao_rtt_p99, razao_jitter_p95, amplitude_rtt_rel, delta_ttl_clip, ttl_reset
- janela: perda_media_w3, rtt_p95_max_w3, jitter_p95_max_w3, n_rtt_acima_p95_w3, perda_media_w6, rtt_p95_max_w6, jitter_p95_max_w6, n_rtt_acima_p95_w6, perda_media_w12, rtt_p95_max_w12, jitter_p95_max_w12, n_rtt_acima_p95_w12
- dinâmica: perdas_consecutivas

O pré-processador do artefato é a identidade: o treino não ajustou scaler. A sentinela −1 é aplicada pela função da etapa 7, depois das janelas.

O treino usou n_jobs=-1. No artefato, a inferência usa n_jobs=1. Com várias threads, a soma das árvores muda a probabilidade em um único bit de um chamado para o outro. A classe não muda. Uma thread deixa a amostra igual ao joblib original, sem retreinar.

## Hiperparâmetros

```
{
  "n_estimators": 200,
  "max_depth": null,
  "min_samples_leaf": 5,
  "max_features": "sqrt",
  "class_weight": null
}
```

## Métricas já calculadas

Validação, copiada de `8_treino_modelos/data/resultados_validacao.json`:

```
{
  "fonte": "8_treino_modelos/data/resultados_validacao.json",
  "macro_f1_treino": "0.7923841805806866",
  "macro_f1_validacao": "0.7671747956006114",
  "gap": "0.02520938498007519",
  "recall_falha_validacao": "0.7375533428165008",
  "geral": {
    "n": 46490,
    "macro_f1": "0.7671747956006114",
    "recall_falha": "0.7375533428165008"
  },
  "transicoes": {
    "n": 4802,
    "macro_f1": "0.3057137851109986",
    "recall_falha": "0.18115942028985507"
  },
  "inicio_falha": {
    "n": 414,
    "macro_f1": "0.3067484662576687",
    "recall_falha": "0.18115942028985507"
  },
  "persistencia_geral": {
    "n": 46490,
    "macro_f1": "0.7105887942733683",
    "recall_falha": "0.705547652916074"
  }
}
```

Teste, copiado de `8_treino_modelos/data/avaliacao_teste.json`. Esta cópia não é uma nova avaliação:

```
{
  "fonte": "8_treino_modelos/data/avaliacao_teste.json",
  "nota": "Cópia da avaliação já executada. Este empacotamento não releu o split de teste.",
  "geral": {
    "n": 46105,
    "macro_f1": "0.7546021141569271",
    "recall_falha": "0.6954063604240283"
  },
  "transicoes": {
    "n": 4879,
    "macro_f1": "0.28694902022760677",
    "recall_falha": "0.14601769911504425"
  },
  "inicio_falha": {
    "n": 452,
    "macro_f1": "0.25482625482625487",
    "recall_falha": "0.14601769911504425"
  },
  "persistencia_geral": {
    "n": 46105,
    "macro_f1": "0.7108027572032635",
    "recall_falha": "0.680565371024735"
  },
  "ganho": {
    "geral": "0.04379935695366366",
    "transicoes": null,
    "inicio_falha": "0.25482625482625487",
    "sem_anchor_dominante": "0.03779716718283532"
  },
  "analise_teste": [
    "No teste, o modelo antecipa só 14,6% dos inícios de FALHA."
  ],
  "frase_fixa": "O teste não deve ser usado para novos ajustes. Ajustar de novo exige outro conjunto de teste ou nova janela de dados."
}
```

## Uso e limite

A previsão é a classe da próxima medição do mesmo fluxo. `classe_atual` fica no log e fora do vetor. O rótulo real chega depois e não entra na conta das features.

O baseline de um fluxo novo usa a persistência (`classe_atual`) e a regra da etapa 7, importadas, não reescritas. Um fluxo sem baseline válido não recebe classe inventada.

Bibliotecas no empacotamento: `{"python": "3.11.9", "scikit-learn": "1.5.1", "numpy": "2.2.6", "pandas": "2.2.2", "joblib": "1.4.2", "xgboost": null, "xgboost_nota": "nao instalado; o modelo escolhido e o Random Forest"}`.

Commit git no empacotamento: `None`.

Amostra de conferência: `modelo/predicoes_amostra.csv`, 20 linhas, semente 42, somente split `treino`.
