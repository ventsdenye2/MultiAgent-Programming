import csv

from ledger import add_record, load_records, summarize


def export_csv(*args):
    # 新功能缺失不应阻止独立验证子任务一。
    from ledger import export_csv as implementation
    return implementation(*args)


def seed(db):
    add_record(db, "工资", 8000)
    add_record(db, "房租", -2500)
    add_record(db, "餐饮", -300.5)


def test_summarize_net(tmp_path):
    db = tmp_path / "l.json"
    seed(str(db))
    s = summarize(load_records(str(db)))
    assert s["income"] == 8000
    assert s["expense"] == -2800.5
    assert round(s["net"], 2) == 5199.5


def test_summarize_empty(tmp_path):
    s = summarize([])
    assert s == {"income": 0, "expense": 0, "net": 0}


def test_export_csv_rows(tmp_path):
    db = tmp_path / "l.json"
    out = tmp_path / "out.csv"
    seed(str(db))
    export_csv(str(db), str(out))
    with open(out, encoding="utf-8") as f:
        rows = list(csv.reader(f))
    assert rows[0] == ["desc", "amount"]
    assert rows[1] == ["工资", "8000.00"]
    assert rows[2] == ["房租", "-2500.00"]
    assert rows[3] == ["餐饮", "-300.50"]
    assert len(rows) == 5


def test_export_csv_net_row(tmp_path):
    db = tmp_path / "l.json"
    out = tmp_path / "out.csv"
    seed(str(db))
    export_csv(str(db), str(out))
    with open(out, encoding="utf-8") as f:
        rows = list(csv.reader(f))
    assert rows[-1] == ["__net__", "5199.50"]
