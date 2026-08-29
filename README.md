# ZenOps Print Manager

A small suite of Python tools for managing and batch-printing catalogued PDF
handouts across multiple clients, with automatic per-sheet pricing and
duplex (front/back) print splitting.

## Why I built this

I was managing print jobs for several clients, each with hundreds of PDF
handouts organized by grade/category. Manually calculating per-sheet pricing
and manually handling duplex printing (most consumer printers don't reliably
auto-duplex thin paper) was slow and error-prone. This project automates
that whole workflow: catalog the PDFs, price them by page count, and print
them in the correct odd/even sequence for manual-flip duplex printing.

## What it does

- **`importer.py`** — Scans a client's handout folder, reads each PDF's page
  count, calculates a price per sheet, and stores everything in a local
  SQLite database. Can also generate a printable price catalog per client.
- **`gui_app.py`** — A desktop app (Tkinter) for browsing the catalog, building
  a print queue across multiple clients, and sending batches to a printer.
  Handles duplex jobs by automatically splitting into odd/even page batches
  and prompting you to flip the paper between passes.
- **`cli_app.py`** — A lightweight terminal version of the same batch-print
  workflow, for quick print runs without the GUI.

Each client can be configured as either:
- **Duplex** — front-and-back printing, 2 PDF pages = 1 physical sheet
- **Simplex** — single-sided printing, printed as-is with no odd/even split

## Tech used

Python, SQLite, Tkinter, [pypdf](https://pypi.org/project/pypdf/) for PDF
reading/merging/splitting, [fpdf2](https://pypi.org/project/fpdf2/) for
catalog generation, and [SumatraPDF](https://www.sumatrapdfreader.org/) as a
lightweight silent-printing command-line backend.

## Setup

1. **Clone and install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

2. **Configure your local settings:**
   ```bash
   cp config.example.py config.py
   ```
   Edit `config.py` with your real folder paths and client list. This file
   is gitignored, so your local paths never get committed.

3. **Download [SumatraPDF Portable](https://www.sumatrapdfreader.org/download-free-pdf-viewer)**
   and place the `.exe` in a `bin/` folder inside your configured
   `BASE_SCRIPT_DIR`.

4. **Organize your handouts** under `BASE_HANDOUTS_DIR`, with one subfolder
   per client. For duplex clients, further organize by grade-numbered
   subfolders (e.g. `ClientA/Grade 5/Math.pdf`).

5. **Run the importer first** to build the database:
   ```bash
   python importer.py
   ```

6. **Then run either interface:**
   ```bash
   python gui_app.py
   # or
   python cli_app.py
   ```

## Notes

- Windows-only for actual printing (relies on `pywin32` for printer
  enumeration and SumatraPDF's Windows print backend). The importer and
  database logic are cross-platform.
- Client names and folder paths in this repo are placeholders — see
  `config.example.py`. Real business data is kept out of version control.

## License

MIT — see [LICENSE](LICENSE).
