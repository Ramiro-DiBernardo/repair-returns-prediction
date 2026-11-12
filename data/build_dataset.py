"""
Build the modeling dataset from the anonymized phone repair lab workbook.

Source: demo/laboratorio_demo.xlsx from
https://github.com/Ramiro-DiBernardo/powerbi-laboratorio-celulares
(technician names, employee IDs and IMEIs were already replaced with fake ones).

The workbook has one sheet per technician, filled by hand. This script:
  1. reads every technician sheet and finds the columns by name (with synonyms),
  2. keeps the rows logged at the "Reparador" (repair) workstation,
  3. normalizes status, business unit, repair level and free-text notes,
  4. links visits of the same device (by IMEI) to compute the target:
     did a repaired device come back to a repair bench within 60 days?
  5. replaces the IMEI with a numeric device_id and writes data/repairs.csv.

Usage:
    python data/build_dataset.py path/to/laboratorio_demo.xlsx
"""
import re
import sys
import unicodedata
from pathlib import Path

import pandas as pd

RETURN_WINDOW_DAYS = 60
NOT_TECHNICIAN_SHEETS = {"-", "Datos", "Desbloqueo y Reescritura", "Egresados",
                         "Mensual 2026", "Consolidado", "Procesados OQC mensual"}
SYNONYMS = {
    "date": ["fecha procesado"],
    "imei": ["imei"],
    "workstation": ["puesto"],
    "business_unit": ["negocio", "bbti", "online"],
    "status": ["estado"],
    "repair_level": ["nivel reparacion", "nivel de reparacion"],
    "notes": ["observaciones"],
}


def norm(value) -> str:
    """Lowercase, strip accents and collapse spaces."""
    if pd.isna(value):
        return ""
    text = unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", text.lower()).strip()


def read_sheet(book: pd.ExcelFile, sheet: str) -> pd.DataFrame:
    raw = book.parse(sheet, dtype=str)
    by_name = {norm(c): c for c in raw.columns}
    out = pd.DataFrame({"technician": sheet}, index=raw.index)
    for field, names in SYNONYMS.items():
        col = next((by_name[n] for n in names if n in by_name), None)
        out[field] = raw[col] if col is not None else None
    return out


def main(xlsx_path: str) -> None:
    book = pd.ExcelFile(xlsx_path)
    sheets = [s for s in book.sheet_names if s not in NOT_TECHNICIAN_SHEETS]
    df = pd.concat([read_sheet(book, s) for s in sheets], ignore_index=True)

    for col in ["workstation", "business_unit", "status", "repair_level", "notes"]:
        df[col] = df[col].map(norm)
    df["imei"] = df["imei"].astype(str).str.extract(r"(\d{15})")[0]
    df["date"] = pd.to_datetime(df["date"], errors="coerce")

    repairs = df[(df["workstation"] == "reparador") & df["imei"].notna() & df["date"].notna()]
    repairs = repairs.sort_values(["date"], kind="stable").copy()

    by_device = repairs.groupby("imei")
    repairs["visit_number"] = by_device.cumcount() + 1
    repairs["next_visit"] = by_device["date"].shift(-1)
    repairs["days_to_next_visit"] = (repairs["next_visit"] - repairs["date"]).dt.days
    repairs["returned_60d"] = repairs["days_to_next_visit"].between(1, RETURN_WINDOW_DAYS).astype(int)

    repairs["repair_level"] = repairs["repair_level"].str.extract(r"nivel (\d)")[0].fillna("not logged")
    repairs["repair_level"] = repairs["repair_level"].replace(
        {"0": "0 software", "1": "1 mechanical adjustment", "2": "2 part replacement", "3": "3 screen replacement"})
    repairs["business_unit"] = repairs["business_unit"].str.upper().replace("", "NOT LOGGED")
    repairs["device_id"] = pd.factorize(repairs["imei"])[0] + 1

    cols = ["device_id", "date", "technician", "business_unit", "status", "repair_level",
            "notes", "visit_number", "days_to_next_visit", "returned_60d"]
    out = Path(__file__).with_name("repairs.csv")
    repairs[cols].to_csv(out, index=False)
    print(f"{len(repairs):,} repair-bench visits written to {out}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "laboratorio_demo.xlsx")
