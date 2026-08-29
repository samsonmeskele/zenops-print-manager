"""
ZenOps Print Manager - GUI Print Station

A Tkinter desktop app for browsing cataloged handouts per client, building
a print queue, and batch-printing with automatic duplex odd/even splitting
via SumatraPDF.
"""

import tkinter as tk
from tkinter import ttk, messagebox
import sqlite3
import os
import subprocess
from datetime import datetime
from pypdf import PdfReader, PdfWriter

try:
    import win32print
except ImportError:
    win32print = None

from config import SUMATRA_EXE, PRINTER_KEYWORDS, CLIENTS
from common import BASE_DB_DIR, CACHE_FOLDER, BIN_FOLDER, BASE_SCRIPT_DIR, get_db_path

SUMATRA_PATH = os.path.join(BIN_FOLDER, SUMATRA_EXE)
IMPORTER_SCRIPT = os.path.join(BASE_SCRIPT_DIR, 'importer.py')
CLIENT_NAMES = list(CLIENTS.keys())


class ZenOpsPro:
    def __init__(self, root):
        self.root = root
        self.root.title("ZenOps Print Station")
        self.root.geometry("1200x750")

        self.check_environment()
        self.job_queue = []
        os.makedirs(CACHE_FOLDER, exist_ok=True)

        self.paned_window = ttk.PanedWindow(root, orient=tk.HORIZONTAL)
        self.paned_window.pack(fill=tk.BOTH, expand=True)

        self.left_frame = tk.Frame(self.paned_window, width=850, padx=5, pady=5)
        self.paned_window.add(self.left_frame, weight=3)

        self.right_frame = tk.Frame(self.paned_window, width=350, bg="#e6e6e6", padx=10, pady=10)
        self.paned_window.add(self.right_frame, weight=1)

        self.setup_right_panel()
        self.setup_left_panel_structure()

        self.all_files = []
        self.current_client = CLIENT_NAMES[0]
        self.refresh_printers()
        self.load_client_data(self.current_client)

    def check_environment(self):
        if not os.path.exists(SUMATRA_PATH):
            messagebox.showerror("Missing component", f"SumatraPDF not found!\nExpected: {SUMATRA_PATH}")

    def run_importer(self):
        if os.path.exists(IMPORTER_SCRIPT):
            try:
                subprocess.Popen(['python', IMPORTER_SCRIPT], cwd=BASE_SCRIPT_DIR, shell=True)
            except Exception as e:
                messagebox.showerror("Error", f"Failed to launch importer: {e}")
        else:
            messagebox.showerror("Missing file", "Could not find 'importer.py'")

    def setup_left_panel_structure(self):
        top_bar = tk.Frame(self.left_frame)
        top_bar.pack(fill="x", pady=(0, 10))

        tk.Label(top_bar, text="Printer:").pack(side="left")
        self.printer_var = tk.StringVar()
        self.printer_dropdown = ttk.Combobox(top_bar, textvariable=self.printer_var, width=30, state="readonly")
        self.printer_dropdown.pack(side="left", padx=5)

        tk.Button(top_bar, text="Importer", command=self.run_importer, bg="#607D8B", fg="white").pack(side="left", padx=10)
        tk.Button(top_bar, text="Refresh DB", command=lambda: self.load_client_data(self.current_client)).pack(side="right")

        search_frame = tk.Frame(self.left_frame)
        search_frame.pack(fill="x", pady=(0, 5))
        tk.Label(search_frame, text="Search:").pack(side="left")
        self.search_var = tk.StringVar()
        self.search_var.trace("w", self.filter_data)
        self.search_entry = tk.Entry(search_frame, textvariable=self.search_var, width=40)
        self.search_entry.pack(side="left", padx=5)
        self.search_entry.bind('<Return>', lambda e: self.add_to_queue())

        self.notebook = ttk.Notebook(self.left_frame)
        self.notebook.pack(fill="both", expand=True)
        self.notebook.bind("<<NotebookTabChanged>>", self.on_tab_change)

        for client in CLIENT_NAMES:
            frame = tk.Frame(self.notebook)
            self.notebook.add(frame, text=f"  {client}  ")

        self.tree_frame = tk.Frame(self.left_frame)
        self.tree_frame.pack(fill="both", expand=True)

        columns = ("ID", "Recent", "Grade", "Subject", "Price")
        self.tree = ttk.Treeview(self.tree_frame, columns=columns, show="headings", height=18)

        self.tree.heading("ID", text="ID")
        self.tree.heading("Recent", text="Status")
        self.tree.heading("Grade", text="Grade")
        self.tree.heading("Subject", text="Subject")
        self.tree.heading("Price", text="Price")

        self.tree.column("ID", width=60, anchor="center")
        self.tree.column("Recent", width=60, anchor="center")
        self.tree.column("Grade", width=80, anchor="center")
        self.tree.column("Subject", width=400)
        self.tree.column("Price", width=60, anchor="e")

        scrollbar = ttk.Scrollbar(self.tree_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscroll=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.tree.pack(fill="both", expand=True)

        self.tree.tag_configure('new_item', foreground='green', font=('Segoe UI', 9, 'bold'))
        self.tree.tag_configure('old_item', foreground='black')

        self.tree.bind("<Double-1>", lambda e: self.add_to_queue())

        self.context_menu = tk.Menu(self.root, tearoff=0)
        self.context_menu.add_command(label="Open PDF", command=self.open_selected_pdf)
        self.context_menu.add_command(label="Add to Queue", command=self.add_to_queue)
        self.tree.bind("<Button-3>", self.show_context_menu)

        add_bar = tk.Frame(self.left_frame, pady=10)
        add_bar.pack(fill="x")
        tk.Label(add_bar, text="Copies:").pack(side="left")
        self.copies_var = tk.IntVar(value=1)
        self.copies_entry = tk.Entry(add_bar, textvariable=self.copies_var, width=5)
        self.copies_entry.pack(side="left", padx=5)
        self.copies_entry.bind('<Return>', lambda e: self.add_to_queue())

        tk.Button(add_bar, text="ADD TO QUEUE", command=self.add_to_queue, bg="#2196F3", fg="white",
                  font=("Arial", 10, "bold")).pack(side="left", padx=10)

    def setup_right_panel(self):
        tk.Label(self.right_frame, text="PRINT QUEUE", bg="#e6e6e6", font=("Arial", 12, "bold")).pack(pady=(0, 10))
        self.queue_list = tk.Listbox(self.right_frame, height=25, selectmode=tk.EXTENDED)
        self.queue_list.pack(fill="both", expand=True)
        self.total_label = tk.Label(self.right_frame, text="Jobs: 0 | Total: 0.00", bg="#e6e6e6", font=("Arial", 10, "bold"))
        self.total_label.pack(pady=10)

        btn_frame = tk.Frame(self.right_frame, bg="#e6e6e6")
        btn_frame.pack(fill="x")
        tk.Button(btn_frame, text="Remove", command=self.remove_from_queue).pack(side="left", expand=True, fill="x")
        tk.Button(btn_frame, text="PROCESS", command=self.process_batch, bg="red", fg="white").pack(side="left", expand=True, fill="x")

    def show_context_menu(self, event):
        item = self.tree.identify_row(event.y)
        if item:
            self.tree.selection_set(item)
            self.context_menu.post(event.x_root, event.y_root)

    def on_tab_change(self, event):
        tab_id = self.notebook.index(self.notebook.select())
        self.current_client = CLIENT_NAMES[tab_id]
        self.load_client_data(self.current_client)

    def refresh_printers(self):
        if win32print:
            try:
                all_printers = [p[2] for p in win32print.EnumPrinters(2)]
                final_list = [p for p in all_printers if any(k in p.lower() for k in PRINTER_KEYWORDS)]
                if not final_list:
                    final_list = ["No matching printer found"]
                self.printer_dropdown['values'] = final_list
                self.printer_dropdown.current(0)
            except Exception:
                self.printer_dropdown['values'] = ["Error loading printers"]
        else:
            self.printer_dropdown['values'] = ["Default (pywin32 missing)"]
            self.printer_dropdown.current(0)

    def load_client_data(self, client_name):
        self.tree.delete(*self.tree.get_children())
        db_path = get_db_path(client_name)

        if not os.path.exists(db_path):
            self.all_files = []
            return

        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT id, grade, subject, price, location, date_added FROM files ORDER BY date_added DESC, id ASC")
            self.all_files = cursor.fetchall()
            self.update_table(self.all_files)
        except Exception as e:
            messagebox.showerror("DB error", str(e))
        finally:
            conn.close()

    def update_table(self, rows):
        for item in self.tree.get_children():
            self.tree.delete(item)
        today = datetime.now()
        for row in rows:
            fid, grade, subject, price, location, date_str = row
            recent_status, tag = "Old", "old_item"
            if date_str:
                try:
                    if (today - datetime.strptime(date_str, "%Y-%m-%d")).days <= 45:
                        recent_status, tag = "New", "new_item"
                except Exception:
                    pass

            self.tree.insert("", "end", values=(fid, recent_status, grade, subject, f"{price:.0f}"), tags=(tag,))

    def filter_data(self, *args):
        query = self.search_var.get().lower()
        if not query:
            self.update_table(self.all_files)
            return
        filtered = [row for row in self.all_files if
                    (str(row[0]) in query) or (query in row[2].lower()) or (query in row[1].lower())]
        self.update_table(filtered)

    def open_selected_pdf(self):
        selected = self.tree.selection()
        if not selected:
            return
        val = self.tree.item(selected[0])['values']
        fid_display = val[0]
        found_file = next((r for r in self.all_files if str(r[0]) == str(fid_display)), None)
        if found_file:
            try:
                os.startfile(found_file[4])
            except Exception as e:
                messagebox.showerror("Error", f"Cannot open file: {e}")

    def add_to_queue(self):
        selected = self.tree.selection()
        if not selected:
            return
        try:
            copies = self.copies_var.get()
            if copies < 1:
                raise ValueError
        except Exception:
            return

        for item_id in selected:
            val = self.tree.item(item_id)['values']
            fid_display = val[0]
            found_file = next((r for r in self.all_files if str(r[0]) == str(fid_display)), None)
            if found_file:
                fid, grade, subject, price, location, _ = found_file
                job = {'id': fid, 'subject': subject, 'copies': copies, 'price': price,
                       'location': location, 'client': self.current_client}
                self.job_queue.append(job)
                self.queue_list.insert(tk.END, f"[{self.current_client}] {subject} ({copies}x) - {price * copies:.0f}")

        self.update_totals()
        self.tree.selection_remove(self.tree.selection())
        self.search_entry.focus()
        self.search_entry.select_range(0, tk.END)

    def remove_from_queue(self):
        for i in reversed(self.queue_list.curselection()):
            self.queue_list.delete(i)
            del self.job_queue[i]
        self.update_totals()

    def update_totals(self):
        total = sum(j['price'] * j['copies'] for j in self.job_queue)
        self.total_label.config(text=f"Jobs: {len(self.job_queue)} | Total: {total:.0f}")

    def process_batch(self):
        if not self.job_queue:
            return
        printer = self.printer_var.get()
        if not printer or "No matching" in printer:
            return messagebox.showerror("Error", "Select a valid printer.")
        if not os.path.exists(SUMATRA_PATH):
            return messagebox.showerror("Error", "SumatraPDF missing in bin folder.")

        if not messagebox.askyesno("Print", f"Print {len(self.job_queue)} jobs?"):
            return

        simplex_jobs = [j for j in self.job_queue if CLIENTS[j['client']]["mode"] == "simplex"]
        duplex_jobs = [j for j in self.job_queue if CLIENTS[j['client']]["mode"] != "simplex"]

        if simplex_jobs:
            try:
                writer = PdfWriter()
                for job in simplex_jobs:
                    reader = PdfReader(job['location'])
                    for _ in range(job['copies']):
                        for page in reader.pages:
                            writer.add_page(page)

                path = os.path.join(CACHE_FOLDER, "BATCH_SIMPLEX.pdf")
                with open(path, 'wb') as f:
                    writer.write(f)

                subprocess.run([SUMATRA_PATH, '-print-to', printer, '-silent', path], check=True)
            except Exception as e:
                messagebox.showerror("Simplex print error", str(e))
                return

        if duplex_jobs:
            try:
                master_writer = PdfWriter()
                for job in duplex_jobs:
                    reader = PdfReader(job['location'])
                    for _ in range(job['copies']):
                        for page in reader.pages:
                            master_writer.add_page(page)

                master_path = os.path.join(CACHE_FOLDER, "BATCH_DUPLEX_TEMP.pdf")
                with open(master_path, 'wb') as f:
                    master_writer.write(f)

                reader = PdfReader(master_path)
                odd_writer = PdfWriter()
                even_writer = PdfWriter()
                n = len(reader.pages)

                for i in range(0, n, 2):
                    odd_writer.add_page(reader.pages[i])
                for i in reversed(range(1, n, 2)):
                    even_writer.add_page(reader.pages[i])

                cache_odd = os.path.join(CACHE_FOLDER, "BATCH_ODD.pdf")
                cache_even = os.path.join(CACHE_FOLDER, "BATCH_EVEN.pdf")

                with open(cache_odd, 'wb') as f:
                    odd_writer.write(f)
                has_even = len(even_writer.pages) > 0
                if has_even:
                    with open(cache_even, 'wb') as f:
                        even_writer.write(f)

                subprocess.run([SUMATRA_PATH, '-print-to', printer, '-silent', cache_odd], check=True)

                if has_even:
                    msg = "DUPLEX BATCH:\n\nODD pages sent. Flip paper and put in tray.\n\nClick YES to print EVEN pages."
                    if messagebox.askyesno("Flip paper", msg):
                        subprocess.run([SUMATRA_PATH, '-print-to', printer, '-silent', cache_even], check=True)
            except Exception as e:
                messagebox.showerror("Duplex print error", str(e))
                return

        self.job_queue.clear()
        self.queue_list.delete(0, tk.END)
        self.update_totals()
        messagebox.showinfo("Done", "All jobs sent to printer.")


if __name__ == "__main__":
    root = tk.Tk()
    ZenOpsPro(root)
    root.mainloop()
