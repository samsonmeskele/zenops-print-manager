"""
ZenOps Print Manager - CLI Version

A lightweight terminal tool for batch-printing cataloged handouts for a
single client, with automatic duplex odd/even page splitting.
"""

import sqlite3
import subprocess
import os
import sys
from pypdf import PdfReader, PdfWriter

try:
    import win32print
except ImportError:
    win32print = None

from config import SUMATRA_EXE, PRINTER_KEYWORDS, CLIENTS
from common import CACHE_FOLDER, BIN_FOLDER, get_db_path, ensure_dirs

SUMATRA_PATH = os.path.join(BIN_FOLDER, SUMATRA_EXE)


def setup():
    ensure_dirs()
    if not os.path.exists(SUMATRA_PATH):
        print(f"CRITICAL ERROR: '{SUMATRA_PATH}' is missing.")
        print("   Please download SumatraPDF Portable and place it in the 'bin' folder.")
        input("   Press Enter to exit...")
        sys.exit()


def select_client():
    names = list(CLIENTS.keys())
    print("\n--- Select Client ---")
    for i, name in enumerate(names):
        print(f"[{i + 1}] {name}")
    while True:
        try:
            sel = int(input("Choice: ")) - 1
            if 0 <= sel < len(names):
                return names[sel]
        except ValueError:
            pass


def get_printer():
    print("\n--- Select Printer ---")
    printers = []
    if win32print:
        try:
            printers = [p[2] for p in win32print.EnumPrinters(2)]
        except Exception:
            pass

    if not printers:
        # Make sure that pywin32 is intalled via pip
        print("No printers found via win32print.")
        return None

    filtered = [p for p in printers if any(k in p.lower() for k in PRINTER_KEYWORDS)]
    final_list = filtered[:3] if filtered else printers[:3]

    for i, name in enumerate(final_list):
        print(f"[{i + 1}] {name}")

    while True:
        try:
            sel = int(input("Choice: ")) - 1
            if 0 <= sel < len(final_list):
                return final_list[sel]
        except ValueError:
            pass


def get_print_jobs(conn):
    raw = input("\nEnter IDs (e.g. 101*5, 102) or 's' to search, '000' to exit: ")
    if raw == '000':
        return "EXIT"
    if raw.lower() == 's':
        search_files(conn)
        return "SEARCH"

    jobs = []
    try:
        for item in raw.split(','):
            item = item.strip()
            if not item:
                continue
            if '*' in item:
                fid, copies = item.split('*')
                jobs.append((fid.strip(), int(copies)))
            else:
                jobs.append((item, 1))
        return jobs
    except Exception:
        print("Invalid format.")
        return None


def search_files(conn):
    keyword = input("Search (subject/grade): ").strip()
    if not keyword:
        return
    cursor = conn.cursor()
    cursor.execute("SELECT id, grade, subject, price FROM files WHERE subject LIKE ? OR grade LIKE ?",
                   (f'%{keyword}%', f'%{keyword}%'))
    print("-" * 60)
    for r in cursor.fetchall():
        print(f"{r[0]:<5} | {r[1]:<8} | {r[3]:<6} | {r[2]}")
    print("-" * 60)


def main():
    print("===== ZenOps CLI =====")
    setup()

    client = select_client()
    mode = CLIENTS[client]["mode"]
    db_path = get_db_path(client)

    if not os.path.exists(db_path):
        print(f"No database found for {client}. Run importer.py first.")
        input("Press Enter to exit...")
        return

    printer = get_printer()
    if not printer:
        return

    conn = sqlite3.connect(db_path)

    while True:
        jobs = get_print_jobs(conn)
        if jobs == "EXIT":
            break
        if jobs == "SEARCH" or not jobs:
            continue

        print("\nProcessing batch...")
        cursor = conn.cursor()

        master_writer = PdfWriter()
        total_cost = 0.0
        found_any = False

        for fid, copies in jobs:
            cursor.execute("SELECT location, subject, price FROM files WHERE id=?", (fid,))
            res = cursor.fetchone()
            if not res:
                print(f"ID {fid} not found.")
                continue

            loc, sub, price = res
            print(f"   + Merging: {sub} ({copies} copies)")
            total_cost += (price * copies)
            found_any = True

            try:
                reader = PdfReader(loc)
                for _ in range(copies):
                    for page in reader.pages:
                        master_writer.add_page(page)
            except Exception as e:
                print(f"   Error reading {sub}: {e}")

        if not found_any:
            continue
        print(f"Total batch value: {total_cost:.2f}")

        master_path = os.path.join(CACHE_FOLDER, "CLI_MASTER.pdf")
        with open(master_path, "wb") as f:
            master_writer.write(f)

        if mode == "simplex":
            print(f"\nSending batch of {len(jobs)} jobs (single-sided)...")
            subprocess.run([SUMATRA_PATH, '-print-to', printer, '-silent', master_path], check=True)
            print("\nDone.")
        else:
            odd_writer = PdfWriter()
            even_writer = PdfWriter()

            reader = PdfReader(master_path)
            n = len(reader.pages)

            for i in range(0, n, 2):
                odd_writer.add_page(reader.pages[i])
            for i in reversed(range(1, n, 2)):
                even_writer.add_page(reader.pages[i])

            path_odd = os.path.join(CACHE_FOLDER, "BATCH_ODD.pdf")
            path_even = os.path.join(CACHE_FOLDER, "BATCH_EVEN.pdf")

            with open(path_odd, "wb") as f:
                odd_writer.write(f)

            has_even = len(even_writer.pages) > 0
            if has_even:
                with open(path_even, "wb") as f:
                    even_writer.write(f)

            print(f"\nSending ODD pages (batch of {len(jobs)} jobs)...")
            subprocess.run([SUMATRA_PATH, '-print-to', printer, '-silent', path_odd], check=True)

            if has_even:
                print("\nSTOP.")
                print("1. Wait for printing to finish.")
                print("2. Take the stack EXACTLY as it is (do not shuffle).")
                print("3. Place it back in the tray.")
                opt = input("   Press Enter to print EVEN pages (or 'n' to skip): ")

                if opt.lower() != 'n':
                    print("Sending EVEN pages...")
                    subprocess.run([SUMATRA_PATH, '-print-to', printer, '-silent', path_even], check=True)
            else:
                print("\nDone (single-sided only).")

        print("\n--- Batch complete ---")

    conn.close()


if __name__ == "__main__":
    main()
