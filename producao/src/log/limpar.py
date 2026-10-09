"""Apaga log bruto vencido. Agregados ficam. --dry-run só lista."""

import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

from src.ajustes import RAIZ

PASTAS_BRUTAS = ("logs/operacional", "logs/coleta_http", "logs/erros", "logs/predicoes")
PASTAS_AGREGADAS = ("relatorios", "logs/predicoes_parquet")


def carregar_retencao(caminho: Path | None = None) -> dict:
    arquivo = caminho or (RAIZ / "config" / "retencao.yaml")
    return yaml.safe_load(arquivo.read_text(encoding="utf-8"))


def vencidos(raiz: Path, agora: datetime, bruto_dias: int) -> list[Path]:
    """Arquivos brutos mais antigos que a retenção. Agregados não entram."""
    limite = agora - timedelta(days=bruto_dias)
    achados: list[Path] = []
    for relativa in PASTAS_BRUTAS:
        pasta = raiz / relativa
        if not pasta.is_dir():
            continue
        for arquivo in pasta.rglob("*"):
            if not arquivo.is_file() or arquivo.name.startswith("."):
                continue
            modificado = datetime.fromtimestamp(arquivo.stat().st_mtime, timezone.utc)
            if modificado < limite:
                achados.append(arquivo)
    return sorted(achados)


def executar(raiz: Path, agora: datetime | None = None, dry_run: bool = True, retencao: dict | None = None) -> list[Path]:
    """Lista ou apaga. O padrão é não apagar."""
    regras = retencao or carregar_retencao()
    momento = agora or datetime.now(timezone.utc)
    alvos = vencidos(raiz, momento, int(regras["bruto_dias"]))
    if dry_run:
        for alvo in alvos:
            print(f"dry-run manteria agregado e apagaria {alvo}")
        if not alvos:
            print("dry-run: nada a apagar.")
        return alvos
    for alvo in alvos:
        alvo.unlink()
        print(f"apagado {alvo}")
    return alvos


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Limpa log bruto vencido.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--raiz", default=str(RAIZ))
    args = parser.parse_args(argv)
    executar(Path(args.raiz), dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
