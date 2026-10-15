"""命令行记账本：记录收支、查看列表、输出汇总。"""
import argparse
import csv
import json
import os

DEFAULT_DB = "ledger.json"


def load_records(db_path):
    if not os.path.exists(db_path):
        return []
    with open(db_path, encoding="utf-8") as f:
        return json.load(f)


def save_records(db_path, records):
    with open(db_path, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)


def add_record(db_path, desc, amount):
    """新增一条记录：amount 为正表示收入，为负表示支出。"""
    records = load_records(db_path)
    records.append({"desc": desc, "amount": amount})
    save_records(db_path, records)


def summarize(records):
    """汇总：返回收入合计、支出合计（负数）、净额。"""
    income = sum(r["amount"] for r in records if r["amount"] > 0)
    expense = sum(r["amount"] for r in records if r["amount"] < 0)
    net = income + expense
    return {"income": income, "expense": expense, "net": net}


def export_csv(db_path, csv_path):
    """把全部记录导出为 CSV，末行为 __net__ 汇总行。"""
    records = load_records(db_path)
    net = summarize(records)["net"]
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["desc", "amount"])
        for r in records:
            writer.writerow([r["desc"], f"{r['amount']:.2f}"])
        writer.writerow(["__net__", f"{net:.2f}"])


def main():
    parser = argparse.ArgumentParser(description="命令行记账本")
    parser.add_argument("--db", default=DEFAULT_DB)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_add = sub.add_parser("add")
    p_add.add_argument("desc")
    p_add.add_argument("amount", type=float)

    sub.add_parser("list")
    sub.add_parser("summary")

    args = parser.parse_args()
    if args.cmd == "add":
        add_record(args.db, args.desc, args.amount)
        print(f"已记录：{args.desc} {args.amount:+.2f}")
    elif args.cmd == "list":
        for r in load_records(args.db):
            print(f"{r['desc']}\t{r['amount']:+.2f}")
    elif args.cmd == "summary":
        s = summarize(load_records(args.db))
        print(f"收入 {s['income']:.2f}  支出 {s['expense']:.2f}  净额 {s['net']:.2f}")


if __name__ == "__main__":
    main()
