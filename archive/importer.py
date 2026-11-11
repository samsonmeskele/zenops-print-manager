"""
Importer & Catalog Generator

Scans each client's handout folder, catalogs PDFs into a per-client SQLite
database with computed sheet pricing, and can generate a printable PDF
price catalog per client.
"""

import sqlite3
import os
from pathlib import Path    
from datetime import datetime
from pypdf import PdfReader
from fpdf.enums import XPos, YPos

try:
    from fpdf import FPDF
except ImportError:
    FPDF = None

from config import BASE_HANDOUTS_DIR, PRICE_PER_SHEET, CLIENTS
from common import ensure_dirs, get_db_path, get_grade_number, clear_cache, BASE_CATALOG_DIR


def get_pdf_info(file_path, mode):
    """Return (title, price) for a PDF based on its page count and print mode."""
    try:
        reader = PdfReader(str(file_path))
        num_pages = len(reader.pages)

        if mode == "simplex":
            # 1 page = 1 sheet
            price = num_pages * PRICE_PER_SHEET
        else:
            # duplex: 2 pages = 1 sheet
            import math
            sheets = math.ceil(num_pages / 2)
            price = sheets * PRICE_PER_SHEET

        return file_path.stem, price
    except Exception:
        return file_path.stem, 0.0


def generate_catalog(client_name):
    if not FPDF:
        print("\nError: 'fpdf2' library not found. Run: pip install fpdf2")
        return

    db_path = get_db_path(client_name)
    if not os.path.exists(db_path):
        return

    print(f"\nGenerating catalog for {client_name}...")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT id, grade, subject, price, date_added FROM files ORDER BY grade ASC, subject ASC")
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        print(f"   Empty database for {client_name}, skipping catalog.")
        return

    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("helvetica", size=10)

    pdf.set_font("helvetica", style="B", size=16)
    pdf.cell(0, 10, f"{client_name} Catalog - {datetime.now().strftime('%Y-%m-%d')}",
             align='C', new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(5)

    pdf.set_font("helvetica", style="B", size=10)
    col_widths = [20, 25, 100, 20, 20]
    headers = ["ID", "Grade", "Subject", "Price", "Status"]

    for i, h in enumerate(headers):
        pdf.cell(col_widths[i], 8, h, border=1, align='C')
    pdf.ln()

    pdf.set_font("helvetica", size=9)
    today = datetime.now()

    for row in rows:
        fid, grade, subject, price, date_str = row
        status = "Old"
        try:
            added_date = datetime.strptime(date_str, "%Y-%m-%d")
            if (today - added_date).days <= 45:
                status = "New"
        except Exception:
            pass

        display_subj = (subject[:55] + '..') if len(subject) > 55 else subject

        pdf.cell(col_widths[0], 7, str(fid), border=1, align='C')
        pdf.cell(col_widths[1], 7, str(grade), border=1, align='C')
        pdf.cell(col_widths[2], 7, display_subj, border=1)
        pdf.cell(col_widths[3], 7, f"{price:.0f}", border=1, align='R')
        pdf.cell(col_widths[4], 7, status, border=1, align='C')
        pdf.ln()

    filename = f"{client_name}_Catalog.pdf"
    save_path = os.path.join(BASE_CATALOG_DIR, filename)

    try:
        pdf.output(save_path)
        print(f"Catalog saved: {save_path}")
    except Exception as e:
        print(f"Error saving PDF: {e}")


def process_client_import(client_name, mode):
    print(f"\n--- Processing: {client_name} ({mode}) ---")

    db_path = get_db_path(client_name)

    if os.path.exists(db_path):
        try:
            os.remove(db_path)
            print(f"   Deleted old database: {os.path.basename(db_path)}")
        except Exception as e:
            print(f"   Could not delete DB: {e}")

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS files (
        id INTEGER PRIMARY KEY,
        grade TEXT,
        subject TEXT,
        price REAL,
        location TEXT NOT NULL,
        date_added TEXT
    )
    ''')

    client_folder = os.path.join(BASE_HANDOUTS_DIR, client_name)
    if not os.path.exists(client_folder):
        print(f"   Folder not found: {client_folder}")
        conn.close()
        return

    pdf_files = []
    scan_pattern = '*.pdf' if mode == "simplex" else '*/*.pdf'

    for file_path in Path(client_folder).glob(scan_pattern):
        skip = any(part.lower() == 'old' for part in file_path.parts)
        if not skip:
            pdf_files.append(file_path)

    files_to_insert = []
    today_str = datetime.now().strftime("%Y-%m-%d")
    id_trackers = {}

    print(f"   Scanning {len(pdf_files)} files...")

    for file_path in pdf_files:
        location = str(file_path.resolve())

        if mode == "simplex":
            grade_display = "General"
            grade_key = 10
        else:
            folder_name = file_path.parent.name
            grade_num = get_grade_number(folder_name)
            if grade_num == 0:
                continue
            grade_display = f"Grade {grade_num}"
            grade_key = grade_num

        if grade_key not in id_trackers:
            id_trackers[grade_key] = grade_key * 100

        subject, price = get_pdf_info(file_path, mode)

        id_trackers[grade_key] += 1
        new_id = id_trackers[grade_key]

        files_to_insert.append((new_id, grade_display, subject, price, location, today_str))
        print(f"    [+] {subject} (ID: {new_id}) - {price:.0f}")

    if files_to_insert:
        cursor.executemany("INSERT INTO files VALUES (?, ?, ?, ?, ?, ?)", files_to_insert)
        conn.commit()
        print(f"   Added {len(files_to_insert)} files for {client_name}.")
    else:
        print("   No new files found.")

    conn.close()


def main():
    print("===== ZenOps Importer =====")

    if not os.path.exists(BASE_HANDOUTS_DIR):
        print(f"Critical error: handouts folder not found at {BASE_HANDOUTS_DIR}")
        input("Press Enter to exit...")
        return

    ensure_dirs()
    client_names = list(CLIENTS.keys())
    existing_dbs = [c for c in client_names if os.path.exists(get_db_path(c))]
    is_first_run = len(existing_dbs) == 0

    if is_first_run:
        print("\nFirst run detected. Initializing all databases...")
        clear_cache()
        for client, cfg in CLIENTS.items():
            process_client_import(client, cfg["mode"])
        if input("\nGenerate PDF catalogs for all? (y/n): ").strip().lower() == 'y':
            for client in client_names:
                generate_catalog(client)
    else:
        while True:
            print("\n--- Update Menu ---")
            for i, client in enumerate(client_names):
                print(f"[{i + 1}] Update {client}")
            print(f"[{len(client_names) + 1}] Generate catalogs (all)")
            print("[0] Exit")

            choice = input("Select option: ").strip()
            if choice == '0':
                break
            elif choice == str(len(client_names) + 1):
                for client in client_names:
                    generate_catalog(client)
            else:
                try:
                    idx = int(choice) - 1
                    if 0 <= idx < len(client_names):
                        target = client_names[idx]
                        print("\nClearing temp cache...")
                        clear_cache()
                        process_client_import(target, CLIENTS[target]["mode"])
                        if input(f"Generate catalog for {target}? (y/n): ").strip().lower() == 'y':
                            generate_catalog(target)
                except ValueError:
                    pass

    input("\nPress Enter to exit...")


if __name__ == "__main__":
    main()
