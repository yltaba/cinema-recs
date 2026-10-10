import sys


def utf8_streams() -> None:
    """Console do Windows usa cp1252 por padrão; títulos em japonês etc. quebrariam a saída."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure") and (stream.encoding or "").lower().replace("-", "") != "utf8":
            stream.reconfigure(encoding="utf-8")


def main() -> None:
    utf8_streams()
    from recs.cli import app

    app()
