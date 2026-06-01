# ============================================================================
# analysis/run_qa.py — QA dedektörlerini canlı DB üzerinde çalıştırır (salt-okunur)
# ============================================================================
# Kullanım:
#   python -m analysis.run_qa --country MX --top 30
# ============================================================================

import argparse
import csv

from analysis.detectors import load_matched_rows, detect_over_merge, detect_splits


def main() -> None:
    ap = argparse.ArgumentParser(description="Eşleştirme kalitesi QA dedektörleri")
    ap.add_argument("--country", default=None, help="Ülke kodu filtresi (örn. MX)")
    ap.add_argument("--top", type=int, default=30, help="Gösterilecek aday sayısı")
    ap.add_argument("--threshold", type=float, default=0.3, help="Over-merge örtüşme eşiği")
    ap.add_argument("--csv-prefix", default=None, help="Verilirse <prefix>_overmerge.csv / _splits.csv yazar")
    args = ap.parse_args()

    rows = load_matched_rows(args.country)
    print(f"Yüklenen eşleşmiş kayıt: {len(rows):,}")

    over = detect_over_merge(rows, threshold=args.threshold)
    splits = detect_splits(rows)

    print(f"\n=== OVER-MERGE adayları: {len(over)} (top {args.top}) ===")
    for f in over[: args.top]:
        print(f"  master={f.master_code} üye={f.member_count} örtüşme={f.mean_overlap:.2f} "
              f"stage={f.dominant_match_type} örnek={list(f.sample_names)}")

    print(f"\n=== SPLIT adayları: {len(splits)} (top {args.top}) ===")
    for f in splits[: args.top]:
        print(f"  {f.country} imza={list(f.core_signature)} master_sayisi={len(f.master_codes)} "
              f"kayit={f.affected_rows} örnek={list(f.sample_names)}")

    if args.csv_prefix:
        with open(f"{args.csv_prefix}_overmerge.csv", "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["master_code", "member_count", "mean_overlap", "dominant_match_type", "sample_names"])
            for f in over:
                w.writerow([f.master_code, f.member_count, f"{f.mean_overlap:.3f}",
                            f.dominant_match_type, " | ".join(f.sample_names)])
        with open(f"{args.csv_prefix}_splits.csv", "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["country", "core_signature", "master_count", "affected_rows", "sample_names"])
            for f in splits:
                w.writerow([f.country, " ".join(f.core_signature), len(f.master_codes),
                            f.affected_rows, " | ".join(f.sample_names)])
        print(f"\nCSV yazıldı: {args.csv_prefix}_overmerge.csv / _splits.csv")


if __name__ == "__main__":
    main()
