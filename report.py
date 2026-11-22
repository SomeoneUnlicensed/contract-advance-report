import argparse
import csv
import re
from datetime import date
from pathlib import Path


def money(value):
    if not re.fullmatch(r"[0-9]+(?:\.[0-9]{1,2})?", value):
        raise ValueError(f"некорректная сумма: {value!r}")
    rub, _, kop = value.partition(".")
    return int(rub) * 100 + int(kop.ljust(2, "0"))


def fmt(n):
    rub, kop = divmod(abs(n), 100)
    return f"{'-' if n < 0 else ''}{rub:_},{kop:02}".replace("_", " ")


def rows(folder, name, columns):
    with (folder / f"{name}.csv").open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream, strict=True)
        fields = columns.split()
        if set(reader.fieldnames or []) != set(fields) or len(reader.fieldnames) != len(fields):
            raise ValueError(f"{name}.csv: неверный заголовок")
        seen = set()
        for r in reader:
            key = r[fields[0]]
            if None in r or None in r.values() or not key or key in seen:
                raise ValueError(f"{name}.csv:{reader.line_num}: неполная, лишняя или повторная запись")
            seen.add(key)
            yield r


def event_dates(row, mapping):
    status = row["status"]
    if status not in mapping:
        raise ValueError(f"неизвестный статус: {status}")
    result = {}
    for field in set().union(*mapping.values()):
        raw = row[field]
        if bool(raw) != (field in mapping[status]):
            raise ValueError(f"{status}: проверьте поле {field}")
        result[field] = date.fromisoformat(raw) if raw else None
    return result


def calculate(folder, day):
    contracts = {}
    works = {}
    for r in rows(folder, "contracts", "contract_id contractor amount signed_at"):
        contracts[r["contract_id"]] = dict(name=r["contractor"], amount=money(r["amount"]),
                                           signed=date.fromisoformat(r["signed_at"]), works=[], pool=0)
    for r in rows(folder, "works", "work_id contract_id title price status completed_at cancelled_at"):
        cid = r["contract_id"]
        if cid not in contracts:
            raise ValueError(f"неизвестный договор: {cid}")
        dates = event_dates(r, {"done": ("completed_at",), "cancelled": ("cancelled_at",), "planned": ()})
        done, cancelled = dates["completed_at"], dates["cancelled_at"]
        state = "принята" if done and done <= day else "отменена" if cancelled and cancelled <= day else "в плане"
        work = dict(id=r["work_id"], cid=cid, title=r["title"], price=money(r["price"]),
                    state=state, done=done, direct=0, share=0)
        works[work["id"]] = work
        contracts[cid]["works"].append(work)
    for r in rows(folder, "payments", "payment_id contract_id work_id purpose amount status created_at paid_at refunded_at"):
        cid, wid = r["contract_id"], r["work_id"]
        if cid not in contracts or (wid and (wid not in works or works[wid]["cid"] != cid)):
            raise ValueError(f"{r['payment_id']}: неверная ссылка на договор или работу")
        dates = event_dates(r, {"paid": ("paid_at",), "refunded": ("paid_at", "refunded_at"), "queued": ()})
        paid, refunded = dates["paid_at"], dates["refunded_at"]
        created = date.fromisoformat(r["created_at"])
        amount = money(r["amount"])
        if (paid and created > paid) or (refunded and paid > refunded):
            raise ValueError(f"{r['payment_id']}: нарушен порядок дат")
        if paid and paid <= day and not (refunded and refunded <= day):
            if wid:
                works[wid]["direct"] += amount
            else:
                contracts[cid]["pool"] += amount

    result = {}
    for cid, c in sorted(contracts.items()):
        if c["signed"] > day:
            continue
        group = sorted(c["works"], key=lambda w: w["id"])
        free = c["pool"]
        for w in sorted((w for w in group if w["state"] == "принята"), key=lambda w: (w["done"], w["id"])):
            w["share"] = min(free, max(0, w["price"] - w["direct"]))
            free -= w["share"]
        for w in group:
            w["paid"] = w["direct"] + w["share"]
            due = 0 if w["state"] == "отменена" else w["price"]
            w["left"] = max(0, due - w["paid"])
            w["excess"] = max(0, w["paid"] - due)
        net = sum(w["paid"] for w in group) + free
        result[cid] = dict(**c, net=net, free=free, balance=c["amount"] - net,
                           due=sum(w["left"] for w in group))
        result[cid]["works"] = group
    return result


def render(result, day):
    lines = [f"Отчёт на конец дня {day:%d.%m.%Y}. Все суммы в рублях."]
    if not result:
        lines.append("На эту дату подписанных договоров нет.")
    for cid, c in result.items():
        lines.extend(["", f"{cid}: {c['name']}",
                      "Работа | Статус | Цена | Напрямую | Из общих | Выплачено | Осталось | Сверх цены*"])
        for w in c["works"]:
            amounts = " | ".join(fmt(w[k]) for k in ("price", "direct", "share", "paid", "left", "excess"))
            lines.append(f"{w['id']} {w['title']} | {w['state']} | {amounts}")
        for label, key in (("Сумма договора", "amount"), ("Выплачено за вычетом возвратов", "net"),
                           ("Не разнесено по работам", "free"), ("Остаток по договору (+) / переплата (−)", "balance"),
                           ("Осталось по работам до зачёта свободного аванса", "due")):
            lines.append(f"{label}: {fmt(c[key])}")
    if result:
        lines.append("\n* Для отменённой работы вся невозвращённая выплата показана как превышение.")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Расчёты с подрядчиками на дату")
    parser.add_argument("--date", required=True, type=date.fromisoformat, metavar="ГГГГ-ММ-ДД")
    parser.add_argument("--data", type=Path, default=Path(__file__).resolve().parent / "data")
    args = parser.parse_args()
    try:
        print(render(calculate(args.data, args.date), args.date))
    except (ValueError, OSError, csv.Error) as exc:
        parser.exit(2, f"Ошибка: {exc}\n")


if __name__ == "__main__":
    main()
