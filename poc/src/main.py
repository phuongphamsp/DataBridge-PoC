"""
DataBridge PoC — CLI Batch Runner
Parses all TRE files → maps to SST inputs → optionally submits via Playwright.

Usage:
    # Dry run (parse + map only, no browser):
    python -m src.main --dry-run

    # Full run (parse + map + Playwright submit):
    python -m src.main

    # Single file:
    python -m src.main --file t01.tre

    # Headful browser (for debugging):
    python -m src.main --no-headless
"""

import argparse
import csv
import json
import sys
import time
from dataclasses import asdict
from pathlib import Path

TRE_DIR = Path(r"D:\DataBridge-PoC\DataBridge from MiTek Drawings to SST solutions\5. TRE & IFC")
OUTPUT_DIR = Path(r"D:\DataBridge-PoC\poc\output")
OUTPUT_CSV = OUTPUT_DIR / "results.csv"
OUTPUT_JSON = OUTPUT_DIR / "results.json"
MAPPED_JSON = OUTPUT_DIR / "mapped_inputs.json"


def get_tre_files(single: str | None = None) -> list[Path]:
    if single:
        p = TRE_DIR / single
        if not p.exists():
            print(f"[ERROR] File not found: {p}")
            sys.exit(1)
        return [p]
    return sorted(TRE_DIR.glob("*.tre"))


def run_dry(files: list[Path]) -> None:
    """Parse + map all files, print summary table, write mapped_inputs.json."""
    from src.parsers.tre_parser import parse_tre
    from src.mappers.sst_mapper import map_tre_to_sst

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    rows = []
    mapped = []
    errors = []

    print(f"\n{'FILE':<20} {'TYPE':<22} {'SPAN':>8} {'PITCH':>7} {'R1':>7} {'U1':>7} {'PLY':>4} {'CONN':<10}")
    print("-" * 90)

    for fp in files:
        try:
            tre = parse_tre(fp)
            sst = map_tre_to_sst(tre)

            conn = sst.connection_type
            print(
                f"{tre.filename:<20} {tre.truss_type_label:<22} "
                f"{tre.span_inches:>8.2f} {tre.pitch_degrees:>7.2f}° "
                f"{tre.reaction1_lbs:>7} {tre.uplift1_lbs:>7} "
                f"{tre.ply:>4}  {conn:<10}"
            )

            rows.append({
                "file": tre.filename,
                "truss_type": tre.truss_type_label,
                "span_in": tre.span_inches,
                "pitch_deg": tre.pitch_degrees,
                "reaction1_lbs": tre.reaction1_lbs,
                "uplift1_lbs": tre.uplift1_lbs,
                "ply": tre.ply,
                "connection_type": conn,
                "skew_deg": tre.skew_degrees,
                "heel_height_in": round(tre.heel_height_inches, 4),
                "species": tre.bottom_chord.species if tre.bottom_chord else "",
                "bc_width": tre.bottom_chord.actual_width if tre.bottom_chord else "",
                "bc_height": tre.bottom_chord.actual_height if tre.bottom_chord else "",
                "is_girder": tre.is_girder,
                "error": "",
            })

            try:
                mapped.append({"file": tre.filename, "input": asdict(sst)})
            except Exception:
                mapped.append({"file": tre.filename, "input": str(sst)})

        except Exception as e:
            print(f"{fp.name:<20} [PARSE ERROR] {e}")
            errors.append({"file": fp.name, "error": str(e)})
            rows.append({"file": fp.name, "error": str(e)})

    print(f"\nProcessed {len(files)} files — {len(errors)} errors.")

    # Write CSV
    if rows:
        fieldnames = list(rows[0].keys())
        with open(OUTPUT_CSV, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        print(f"CSV written: {OUTPUT_CSV}")

    # Write mapped inputs JSON
    with open(MAPPED_JSON, "w") as f:
        json.dump(mapped, f, indent=2, default=str)
    print(f"Mapped inputs JSON: {MAPPED_JSON}")


def run_full(files: list[Path], headless: bool = True) -> None:
    """Parse + map + Playwright submit for all files."""
    from src.parsers.tre_parser import parse_tre
    from src.mappers.sst_mapper import map_tre_to_sst
    from src.integration.sst_playwright import submit_sync

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    all_results = []
    csv_rows = []

    for i, fp in enumerate(files, 1):
        print(f"\n[{i}/{len(files)}] {fp.name} ...", end=" ", flush=True)
        try:
            tre = parse_tre(fp)
            sst = map_tre_to_sst(tre)
        except Exception as e:
            print(f"PARSE ERROR: {e}")
            csv_rows.append({"file": fp.name, "success": False, "error": str(e)})
            continue

        result = submit_sync(sst, fp.name, headless=headless)
        all_results.append(result)

        if result.success:
            n = len(result.hangers)
            top = result.hangers[0].model if n > 0 else "—"
            print(f"OK  ({n} hangers, top: {top})")
        else:
            print(f"FAIL  {result.error}")

        # Flatten for CSV
        for h in result.hangers:
            csv_rows.append({
                "file": fp.name,
                "connection_type": result.connection_type,
                "success": result.success,
                "error": result.error or "",
                "hanger_model": h.model,
                "installed_cost": h.installed_cost,
                "width": h.width,
                "height": h.height,
                "bearing": h.bearing,
                "tf_depth": h.tf_depth,
                "tf_fasteners": h.tf_fasteners,
                "face_fasteners": h.face_fasteners,
                "joist_fasteners": h.joist_fasteners,
                "download_lbs": h.download_lbs,
                "uplift_lbs": h.uplift_lbs,
            })
        if not result.hangers:
            csv_rows.append({
                "file": fp.name,
                "connection_type": result.connection_type,
                "success": result.success,
                "error": result.error or "",
            })

        # Small delay between submissions
        time.sleep(1)

    # Write CSV
    if csv_rows:
        fieldnames = list(csv_rows[0].keys())
        with open(OUTPUT_CSV, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(csv_rows)
        print(f"\nResults CSV: {OUTPUT_CSV}")

    # Write full JSON
    with open(OUTPUT_JSON, "w") as f:
        json.dump(
            [{"file": r.filename, "success": r.success, "error": r.error,
              "hangers": [h.__dict__ for h in r.hangers]} for r in all_results],
            f, indent=2,
        )
    print(f"Results JSON: {OUTPUT_JSON}")


def main() -> None:
    parser = argparse.ArgumentParser(description="DataBridge PoC — TRE → SST batch runner")
    parser.add_argument("--dry-run", action="store_true",
                        help="Parse + map only; no browser submission")
    parser.add_argument("--file", metavar="FILENAME",
                        help="Process a single TRE file (e.g. t01.tre)")
    parser.add_argument("--no-headless", action="store_true",
                        help="Show browser window (useful for debugging)")
    args = parser.parse_args()

    files = get_tre_files(args.file)
    print(f"Found {len(files)} TRE file(s) in {TRE_DIR}")

    if args.dry_run:
        run_dry(files)
    else:
        run_full(files, headless=not args.no_headless)


if __name__ == "__main__":
    main()
