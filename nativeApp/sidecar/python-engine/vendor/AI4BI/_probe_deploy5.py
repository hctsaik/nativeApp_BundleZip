"""Focused deployment probe — Round 5: the diagnostic core only.
Categories: (1) yield commonality/excursion, (2) bottleneck/capacity/WIP-CT,
(3) SPC/process anomaly. Drive these to multi-agent >=95 with statistical rigor,
population transparency, and actionable next-steps.
"""
import io
from ai4bi.analysis.executor import Executor
from ai4bi.ai.nl2proposal import NL2ProposalService
from ai4bi.report.fab_template import build_fab_demo_report, fab_contracts

c = fab_contracts()
svc = NL2ProposalService()
report = build_fab_demo_report()
ex = Executor(extra_contracts=c)
convo = {}


def ask(p):
    return svc.propose(p, report, None, contracts=c, executor=ex, conversation_state=convo)


def describe(r):
    tbl = getattr(r, "result_table", None)
    head = "" if tbl is None else " | ".join(str(x) for x in list(tbl.columns)[:8])
    n = None if tbl is None else len(tbl)
    return getattr(r, "message", None), head, n


SCENARIOS = [
    # --- yield commonality / excursion ---
    ("P1 commonality+sig", "良率低於 80% 的批，有沒有共同走過某台機台？顯著嗎？"),
    ("P2 excursion when", "最近良率有沒有哪幾批突然掉下來？什麼時候掉的？"),
    ("P3 worst-wafer common tool", "缺陷最多的那些晶圓，是不是常經過同一台 etch 機台？"),
    # --- bottleneck / capacity / WIP-CT ---
    ("P4 bottleneck drift", "這幾週瓶頸站有沒有換過？"),
    ("P5 wip vs ct", "WIP 越高 cycle time 是不是越長？相關多少？"),
    ("P6 capacity headroom", "哪個區還有產能餘裕可以多接單？"),
    ("P7 oee honesty", "ETCH-02 的 OEE 是多少？這個數字可靠嗎？"),
    # --- SPC / process anomaly ---
    ("P8 spc outlier+honesty", "queue time 有沒有哪台機台超出管制界限？這算 SPC 嗎？"),
    ("P9 queue-yield corr", "queue time 最長的批良率有比較差嗎？相關係數？"),
    ("P10 rework yield impact", "有重工的批良率是不是比較差？差多少、顯著嗎？"),
]

out = io.open("_probe_deploy5_out.txt", "w", encoding="utf-8")
for tag, q in SCENARIOS:
    out.write(f"\n=== {tag} ===\nQ: {q}\n")
    try:
        msg, head, n = describe(ask(q))
        out.write(f"  rows={n} cols=[{head}]\n  MSG: {msg}\n")
    except Exception as e:
        import traceback
        out.write(f"  ERROR {type(e).__name__}: {e}\n  "
                  + traceback.format_exc().replace("\n", "\n  ") + "\n")
out.close()
print("done")
