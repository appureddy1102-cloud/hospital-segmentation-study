"""
run_all.py
==========
Runs the entire study end-to-end in dependency order and then rebuilds every
deliverable. This is the single command that reproduces the whole project.

    python src/run_all.py              # full rebuild
    python src/run_all.py --skip-gen   # reuse the existing raw extract
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"

STEPS = [
    ("generate_synthetic_data.py", "Building synthetic raw extract", True),
    ("cleaning.py", "Cleaning + validation", False),
    ("features.py", "Engineering patient features", False),
    ("eda.py", "Exploratory data analysis + statistics", False),
    ("segmentation.py", "RFM + K-means + model selection", False),
    ("stability.py", "Two-period stability and migration", False),
    ("recommendations.py", "Cost-benefit model", False),
    ("model_comparison.py", "Model comparison + KPI verification", False),
    ("build_excel.py", "Building Excel workbook", False),
    ("build_report.py", "Building Word report", False),
    ("build_deck.py", "Building PowerPoint deck", False),
    ("build_dashboard_doc.py", "Building dashboard spec + prototype", False),
    ("build_notebook.py", "Assembling notebook", False),
]


def run(script: str, label: str) -> None:
    t0 = time.time()
    print(f"\n{'='*72}\n▶ {label}  ({script})\n{'='*72}")
    r = subprocess.run([sys.executable, script], cwd=SRC, capture_output=True, text=True)
    dt = time.time() - t0
    if r.returncode != 0:
        print(r.stdout[-3000:])
        print(r.stderr[-4000:])
        raise SystemExit(f"FAILED: {script}")
    tail = [ln for ln in r.stdout.strip().splitlines() if ln.strip()][-4:]
    for ln in tail:
        print("   " + ln)
    print(f"   ✓ done in {dt:.1f}s")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-gen", action="store_true",
                    help="reuse the existing raw extract")
    ap.add_argument("--skip-notebook", action="store_true")
    a = ap.parse_args()

    t0 = time.time()
    for script, label, is_gen in STEPS:
        if is_gen and a.skip_gen:
            print(f"\n⏭  skipping {script} (raw extract reused)")
            continue
        if script == "build_notebook.py" and a.skip_notebook:
            continue
        run(script, label)

    # execute the assembled notebook so committed outputs are real
    print(f"\n{'='*72}\n▶ Executing notebook\n{'='*72}")
    nb = ROOT / "notebooks" / "Hospital_Segmentation_Study.ipynb"
    r = subprocess.run(
        [sys.executable, "-m", "nbconvert", "--to", "notebook", "--execute", "--inplace",
         str(nb), "--ExecutePreprocessor.timeout=2400"],
        cwd=ROOT / "notebooks", capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stderr[-4000:])
        raise SystemExit("FAILED: notebook execution")
    print("   ✓ notebook executed")

    print(f"\n{'='*72}\n✅ COMPLETE in {(time.time()-t0)/60:.1f} minutes\n{'='*72}")
    for p in sorted(ROOT.glob("reports/*")):
        print(f"   {p.relative_to(ROOT)}  ({p.stat().st_size/1e6:.2f} MB)")
    print(f"   figures/  ({len(list((ROOT/'figures').glob('*.png')))} charts)")
    print(f"   dashboards/dashboard_prototype.html")


if __name__ == "__main__":
    main()
