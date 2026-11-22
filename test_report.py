import shutil
import tempfile
import unittest
from datetime import date
from pathlib import Path

from report import calculate, fmt, money


DATA = Path(__file__).resolve().parent / "data"


def at(day, folder=DATA):
    return calculate(folder, date.fromisoformat(day))


class ReportTests(unittest.TestCase):
    def test_control_date(self):
        a, b = at("2026-11-10").values()
        self.assertEqual([a[k] for k in ("net", "free", "balance", "due")],
                         [31500000, 1500000, 28500000, 20000000])
        self.assertEqual([(w["direct"], w["share"], w["left"]) for w in a["works"]],
                         [(0, 10000000, 0), (0, 10000000, 0), (0, 0, 0),
                          (1500000, 8500000, 0), (0, 0, 10000000), (0, 0, 10000000)])
        self.assertEqual([b[k] for k in ("net", "free", "balance", "due")],
                         [7500000, 2500000, 1500000, 4000000])
        self.assertEqual([w["paid"] for w in b["works"]], [2000000, 3000000, 0])

    def test_signed_and_paid_boundaries(self):
        self.assertFalse(at("2026-08-24"))
        self.assertEqual(at("2026-08-25")["D-1"]["net"], 0)
        self.assertEqual(at("2026-08-30")["D-1"]["net"], 0)
        self.assertEqual(at("2026-09-01")["D-1"]["free"], 30000000)

    def test_refund_boundary(self):
        for day, expected in [("02", 35000000), ("09", 35000000), ("10", 30000000)]:
            self.assertEqual(at("2026-09-" + day)["D-1"]["net"], expected)

    def test_cancellation_boundary(self):
        self.assertEqual(at("2026-10-11")["D-1"]["works"][2]["left"], 10000000)
        self.assertEqual(at("2026-10-12")["D-1"]["works"][2]["left"], 0)

    def test_planned_acceptance_and_overpayment(self):
        for day, paid, free, balance in [("10", 0, 2500000, 1500000), ("11", 2500000, 0, 1500000),
                                         ("12", 4000000, 500000, -500000)]:
            c = at("2026-11-" + day)["D-2"]
            self.assertEqual((c["works"][-1]["paid"], c["free"], c["balance"]), (paid, free, balance))

    def test_earmarked_payment_before_acceptance(self):
        w = at("2026-10-25")["D-1"]["works"][3]
        self.assertEqual((w["state"], w["paid"], w["share"]), ("в плане", 1500000, 0))

    def with_payment(self, record):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        folder = Path(tmp.name)
        for p in DATA.glob("*.csv"):
            shutil.copyfile(p, folder / p.name)
        with (folder / "payments.csv").open("a", encoding="utf-8") as f:
            f.write(record + "\n")
        return folder

    def test_cancelled_direct_payment_is_not_reassigned(self):
        folder = self.with_payment("PX,D-1,W-13,X,0.01,paid,2026-09-01,2026-09-01,")
        c = at("2026-11-10", folder)["D-1"]
        self.assertEqual((c["works"][2]["excess"], c["net"], c["free"]), (1, 31500001, 1500000))

    def test_cross_contract_link_is_rejected(self):
        folder = self.with_payment("PX,D-2,W-13,X,0.01,paid,2026-09-01,2026-09-01,")
        with self.assertRaisesRegex(ValueError, "PX"):
            at("2026-11-10", folder)

    def test_exact_kopecks(self):
        self.assertEqual(fmt(-money("1000.01")), "-1 000,01")
        self.assertEqual(money("0.1"), 10)
        with self.assertRaises(ValueError):
            money("1.005")
