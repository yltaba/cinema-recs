import io

import recs


def test_utf8_streams_reconfigures_legacy_console(monkeypatch):
    out = io.TextIOWrapper(io.BytesIO(), encoding="cp1252")
    err = io.TextIOWrapper(io.BytesIO(), encoding="cp1252")
    monkeypatch.setattr("sys.stdout", out)
    monkeypatch.setattr("sys.stderr", err)
    recs.utf8_streams()
    assert out.encoding == err.encoding == "utf-8"
    out.write("悪い奴ほどよく眠る")
    out.flush()
    assert out.buffer.getvalue().decode("utf-8") == "悪い奴ほどよく眠る"
