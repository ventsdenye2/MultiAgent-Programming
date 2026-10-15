import csv
import pytest
import ledger


def read_csv(path):
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.reader(f))


@pytest.mark.parametrize("desc", ['购物,日用品', '他说"退款"', '第一行\n第二行'])
def test_csv_escaping_and_order(tmp_path, desc):
    db, out = tmp_path / "db.json", tmp_path / "out.csv"
    ledger.add_record(db, desc, -12.5)
    ledger.add_record(db, "收入", 20)
    ledger.export_csv(db, out)
    assert read_csv(out) == [["desc", "amount"], [desc, "-12.50"],
                             ["收入", "20.00"], ["__net__", "7.50"]]


def test_csv_empty_database(tmp_path):
    out = tmp_path / "out.csv"
    ledger.export_csv(tmp_path / "missing.json", out)
    assert read_csv(out) == [["desc", "amount"], ["__net__", "0.00"]]


def test_csv_negative_net(tmp_path):
    db, out = tmp_path / "db.json", tmp_path / "out.csv"
    ledger.add_record(db, "支出", -30)
    ledger.export_csv(db, out)
    assert read_csv(out)[-1] == ["__net__", "-30.00"]
    assert ledger.summarize(ledger.load_records(db))["expense"] == -30


def test_csv_uses_summarize(tmp_path, monkeypatch):
    calls = []
    def summary(records):
        calls.append(records)
        return {"income": 0, "expense": 0, "net": 42.25}
    monkeypatch.setattr(ledger, "summarize", summary)
    out = tmp_path / "out.csv"
    ledger.export_csv(tmp_path / "missing.json", out)
    assert calls == [[]]
    assert read_csv(out)[-1] == ["__net__", "42.25"]
