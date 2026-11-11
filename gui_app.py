"""
SparkMind Print Station - redesigned GUI (v2: faster rendering, pill school filter)

Performance notes
- Catalog rows are read from the databases once and kept in memory (data_cache).
  They reload only when something actually changes (import, delete, new school).
- Catalog cards are built lazily and cached. Filtering/searching just hides and
  shows existing cards instead of destroying and rebuilding everything.
- New cards are built in small batches so the window never freezes.
- Search is debounced, so typing doesn't trigger a re-render on every keystroke.
- Pages only rebuild when their data changed (dirty flags).

Design notes
- Ink-blue sidebar with an amber "spark" marker for the active page
- Teal primary actions, red only for destructive actions
- School filter on Print is a row of pills with file counts that wraps to
  extra lines when there are many schools
"""

import customtkinter as ctk
from tkinter import messagebox, filedialog
import os
import shutil
import math
from pypdf import PdfReader, PdfWriter

# App specific imports (same folder structure as before)
from config import DOCUMENTS_DIR, CACHE_FOLDER, BIN_FOLDER, SUMATRA_EXE, DEFAULT_PRICE_PER_SHEET, PRINTER_KEYWORDS
from db.db import get_db_path, init_db, add_file, get_school_mode, set_school_mode
from lib.matcher import parse_filename
from lib.printer import split_pdf_for_duplex, send_to_printer

try:
    import win32print
except ImportError:
    win32print = None

# ==========================================
# THEME
# ==========================================
C = {
    "bg": "#F3F5F8",
    "surface": "#FFFFFF",
    "surface_alt": "#F8FAFC",
    "border": "#E2E8F0",
    "ink": "#14213D",
    "ink_hover": "#1F2F52",
    "text": "#0F172A",
    "muted": "#64748B",
    "primary": "#0F766E",
    "primary_hover": "#0B5F59",
    "primary_soft": "#E6F4F2",
    "spark": "#F5A524",
    "danger": "#DC2626",
    "danger_hover": "#B91C1C",
    "danger_soft": "#FEE2E2",
    "success": "#16A34A",
    "success_soft": "#DCFCE7",
    "amber_soft": "#FEF3C7",
    "amber_text": "#92400E",
}

FONT = "Segoe UI"
RENDER_BATCH = 10       # catalog cards built per UI tick
SEARCH_DELAY_MS = 200   # debounce for the search box


def font(size=13, weight="normal"):
    return ctk.CTkFont(family=FONT, size=size, weight=weight)


ctk.set_appearance_mode("Light")
ctk.set_default_color_theme("blue")


# ==========================================
# SMALL REUSABLE WIDGETS
# ==========================================
def primary_btn(parent, text, command, width=100, height=34, **kw):
    return ctk.CTkButton(parent, text=text, command=command, width=width, height=height,
                         fg_color=C["primary"], hover_color=C["primary_hover"],
                         text_color="white", corner_radius=8, font=font(13, "bold"), **kw)


def ghost_btn(parent, text, command, width=80, height=34, danger=False, **kw):
    return ctk.CTkButton(parent, text=text, command=command, width=width, height=height,
                         fg_color="transparent",
                         hover_color=C["danger_soft"] if danger else C["primary_soft"],
                         text_color=C["danger"] if danger else C["primary"],
                         border_width=1,
                         border_color=C["danger"] if danger else C["border"],
                         corner_radius=8, font=font(13), **kw)


def chip(parent, text, bg, fg):
    return ctk.CTkLabel(parent, text=text, fg_color=bg, text_color=fg,
                        corner_radius=10, font=font(11, "bold"), height=22, padx=10)


def card(parent, **kw):
    kw.setdefault("fg_color", C["surface"])
    kw.setdefault("corner_radius", 12)
    kw.setdefault("border_width", 1)
    kw.setdefault("border_color", C["border"])
    return ctk.CTkFrame(parent, **kw)


class ZenOpsDashboard(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Spark Mind Print Station")
        self.geometry("1280x800")
        self.minsize(1080, 640)
        self.configure(fg_color=C["bg"])

        self.ensure_directories()

        # State Variables
        self.current_price = DEFAULT_PRICE_PER_SHEET
        self.queue = []
        self.schools = []

        # Data + render caches
        self.data_cache = {}         # school -> list of file dicts
        self.card_cache = {}         # (school, file id) -> catalog card widget
        self._visible_cards = []     # cards currently packed in the catalog
        self._render_token = 0       # cancels stale batched renders
        self._search_job = None
        self.home_dirty = True
        self.catalog_dirty = True
        self.school_filter = None    # None = all schools
        self.pills = {}
        self._pill_width = 0

        # --- MAIN LAYOUT ---
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.setup_sidebar()

        self.main_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.main_frame.grid(row=0, column=1, sticky="nsew", padx=28, pady=24)
        self.main_frame.grid_rowconfigure(0, weight=1)
        self.main_frame.grid_columnconfigure(0, weight=1)

        self.home_frame = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        self.print_frame = ctk.CTkFrame(self.main_frame, fg_color="transparent")

        self.setup_home_ui()
        self.setup_print_ui()

        self.show_home()

    def ensure_directories(self):
        for folder in [DOCUMENTS_DIR, CACHE_FOLDER]:
            os.makedirs(folder, exist_ok=True)

    # ==========================================
    # DATA LAYER (read once, reuse everywhere)
    # ==========================================
    def load_school(self, school):
        """(Re)load one school's active files from its database into memory."""
        try:
            conn = init_db(school)
            rows = conn.execute(
                "SELECT id, grade, subject, price, location FROM files WHERE is_old = 0"
            ).fetchall()
            conn.close()
        except Exception:
            rows = []

        items = []
        for fid, grade, subject, price, loc in rows:
            filename = os.path.basename(loc)
            items.append({
                "id": fid, "school": school, "grade": grade, "subject": subject,
                "price": price, "loc": loc,
                # lowercase search text is built once, not on every keystroke
                "search": f"{filename} {subject} {grade} {fid} {school}".lower(),
            })
        self.data_cache[school] = items

    def sync_schools(self):
        """Scan the schools folder and load any school we haven't loaded yet.
        Cheap when nothing changed. Returns True if the list of schools changed."""
        if os.path.exists(DOCUMENTS_DIR):
            found = sorted(d for d in os.listdir(DOCUMENTS_DIR)
                           if os.path.isdir(os.path.join(DOCUMENTS_DIR, d)))
        else:
            found = []

        changed = found != self.schools
        self.schools = found

        for school in list(self.data_cache):
            if school not in found:
                del self.data_cache[school]
                self.drop_cards(school)

        for school in found:
            if school not in self.data_cache:
                self.load_school(school)
                changed = True

        if changed:
            self.home_dirty = True
            self.catalog_dirty = True
        return changed

    def destroy_card(self, key):
        widget = self.card_cache.pop(key, None)
        if widget is not None:
            if widget in self._visible_cards:
                self._visible_cards.remove(widget)
            widget.destroy()

    def drop_cards(self, school):
        for key in [k for k in self.card_cache if k[0] == school]:
            self.destroy_card(key)

    # ==========================================
    # NAVIGATION & SIDEBAR
    # ==========================================
    def setup_sidebar(self):
        self.sidebar_frame = ctk.CTkFrame(self, width=220, corner_radius=0, fg_color=C["ink"])
        self.sidebar_frame.grid(row=0, column=0, sticky="nsew")
        self.sidebar_frame.grid_propagate(False)
        self.sidebar_frame.grid_rowconfigure(10, weight=1)

        brand = ctk.CTkFrame(self.sidebar_frame, fg_color="transparent")
        brand.grid(row=0, column=0, sticky="w", padx=22, pady=(28, 34))
        ctk.CTkLabel(brand, text="⚡", font=font(26), text_color=C["spark"]).pack(side="left")
        name_box = ctk.CTkFrame(brand, fg_color="transparent")
        name_box.pack(side="left", padx=(8, 0))
        ctk.CTkLabel(name_box, text="SparkMind", font=font(19, "bold"), text_color="white").pack(anchor="w")
        ctk.CTkLabel(name_box, text="Print station", font=font(12), text_color="#94A3B8").pack(anchor="w")

        self.nav_buttons = {}
        self.nav_markers = {}
        for i, (key, label, cmd) in enumerate([
            ("home", "🏠      Schools", self.show_home),
            ("print", "🖨️ Print", self.show_print),
        ], start=1):
            row = ctk.CTkFrame(self.sidebar_frame, fg_color="transparent")
            row.grid(row=i, column=0, sticky="ew", pady=3)
            row.grid_columnconfigure(1, weight=1)

            marker = ctk.CTkFrame(row, width=4, height=36, corner_radius=2, fg_color="transparent")
            marker.grid(row=0, column=0, padx=(0, 0))
            btn = ctk.CTkButton(row, text=label, anchor="w", height=40, corner_radius=8,
                                fg_color="transparent", hover_color=C["ink_hover"],
                                text_color="#CBD5E1", font=font(14), command=cmd)
            btn.grid(row=0, column=1, sticky="ew", padx=(8, 16))
            self.nav_buttons[key] = btn
            self.nav_markers[key] = marker

        self.sidebar_status = ctk.CTkLabel(self.sidebar_frame, text="", font=font(12),
                                           text_color="#94A3B8", justify="left", anchor="w")
        self.sidebar_status.grid(row=11, column=0, sticky="ew", padx=22, pady=(0, 24))

    def set_active_nav(self, key):
        for k, btn in self.nav_buttons.items():
            active = (k == key)
            btn.configure(fg_color=C["ink_hover"] if active else "transparent",
                          text_color="white" if active else "#CBD5E1")
            self.nav_markers[k].configure(fg_color=C["spark"] if active else "transparent")

    def update_sidebar_status(self):
        n = len(self.queue)
        self.sidebar_status.configure(
            text=f"{n} job{'s' if n != 1 else ''} in queue" if n else "Queue is empty")

    def show_home(self):
        self.sync_schools()
        self.print_frame.grid_forget()
        self.home_frame.grid(row=0, column=0, sticky="nsew")
        self.set_active_nav("home")
        if self.home_dirty:
            self._build_schools_ui()
        self.update_sidebar_status()

    def show_print(self):
        self.sync_schools()
        self.home_frame.grid_forget()
        self.print_frame.grid(row=0, column=0, sticky="nsew")
        self.set_active_nav("print")
        if self.catalog_dirty:
            self.rebuild_school_pills()
            self.apply_filter()
            self.catalog_dirty = False
        self.update_print_ui()
        self.update_sidebar_status()

    # ==========================================
    # HOME TAB (Schools & Import)
    # ==========================================
    def setup_home_ui(self):
        header_frame = ctk.CTkFrame(self.home_frame, fg_color="transparent")
        header_frame.pack(fill="x", pady=(0, 18))

        title_box = ctk.CTkFrame(header_frame, fg_color="transparent")
        title_box.pack(side="left")
        ctk.CTkLabel(title_box, text="Schools", font=font(28, "bold"), text_color=C["text"]).pack(anchor="w")
        ctk.CTkLabel(title_box, text="Import worksheets, set duplex mode and manage pricing.",
                     font=font(13), text_color=C["muted"]).pack(anchor="w")

        ghost_btn(header_frame, "📂  Open schools folder", self.open_schools_folder, width=170, height=38).pack(side="right")

        # --- Stats row ---
        stats = ctk.CTkFrame(self.home_frame, fg_color="transparent")
        stats.pack(fill="x", pady=(0, 20))
        stats.grid_columnconfigure((0, 1, 2), weight=1, uniform="stat")

        self.stat_schools = self._stat_card(stats, 0, "Schools")
        self.stat_files = self._stat_card(stats, 1, "Files in catalog")

        price_card = card(stats)
        price_card.grid(row=0, column=2, sticky="nsew", padx=(8, 0))
        ctk.CTkLabel(price_card, text="Price per sheet (Birr)", font=font(12), text_color=C["muted"]).pack(anchor="w", padx=18, pady=(14, 4))
        price_row = ctk.CTkFrame(price_card, fg_color="transparent")
        price_row.pack(fill="x", padx=18, pady=(0, 14))
        self.price_var = ctk.StringVar(value=str(self.current_price))
        self.price_entry = ctk.CTkEntry(price_row, textvariable=self.price_var, width=90, height=34,
                                        font=font(15, "bold"), corner_radius=8,
                                        border_color=C["border"], fg_color=C["surface_alt"], text_color=C["text"])
        self.price_entry.pack(side="left")
        primary_btn(price_row, "Update", self.update_price, width=80).pack(side="left", padx=10)

        # --- Schools grid ---
        ctk.CTkLabel(self.home_frame, text="Your schools", font=font(17, "bold"), text_color=C["text"]).pack(anchor="w", pady=(0, 8))

        self.schools_scroll = ctk.CTkScrollableFrame(self.home_frame, fg_color="transparent")
        self.schools_scroll.pack(fill="both", expand=True)

    def _stat_card(self, parent, col, label):
        c = card(parent)
        c.grid(row=0, column=col, sticky="nsew", padx=(0 if col == 0 else 8, 8))
        ctk.CTkLabel(c, text=label, font=font(12), text_color=C["muted"]).pack(anchor="w", padx=18, pady=(14, 0))
        value = ctk.CTkLabel(c, text="0", font=font(28, "bold"), text_color=C["text"])
        value.pack(anchor="w", padx=18, pady=(0, 12))
        return value

    def open_schools_folder(self):
        os.makedirs(DOCUMENTS_DIR, exist_ok=True)
        os.startfile(DOCUMENTS_DIR)

    def update_price(self):
        try:
            new_price = float(self.price_var.get())
            self.current_price = new_price
            messagebox.showinfo("Price updated", f"Price is now {new_price} Birr per sheet.\nIt applies to files you import from now on.")
        except ValueError:
            messagebox.showerror("Invalid price", "Enter a number, for example 2 or 2.5.")

    def refresh_schools_list(self):
        """Force the Schools page to rebuild (used after add/delete/import)."""
        self.sync_schools()
        self._build_schools_ui()

    def _build_schools_ui(self):
        self.home_dirty = False
        for widget in self.schools_scroll.winfo_children():
            widget.destroy()

        counts = {s: len(self.data_cache.get(s, [])) for s in self.schools}
        self.stat_schools.configure(text=str(len(self.schools)))
        self.stat_files.configure(text=str(sum(counts.values())))

        row, col = 0, 0
        max_cols = 3
        for school in self.schools:
            self.create_school_card(school, counts[school], row, col)
            col += 1
            if col >= max_cols:
                col = 0
                row += 1

        add_tile = ctk.CTkButton(self.schools_scroll, text="＋  Add a school", font=font(15, "bold"),
                                 fg_color="transparent", text_color=C["primary"], hover_color=C["primary_soft"],
                                 border_width=2, border_color=C["primary"], corner_radius=12, height=150,
                                 command=self.open_add_school_modal)
        add_tile.grid(row=row, column=col, padx=8, pady=8, sticky="nsew")

        for i in range(max_cols):
            self.schools_scroll.grid_columnconfigure(i, weight=1, uniform="school")

    def create_school_card(self, school_name, file_count, r, c):
        tile = card(self.schools_scroll, height=150)
        tile.grid(row=r, column=c, padx=8, pady=8, sticky="nsew")
        tile.grid_propagate(False)
        tile.pack_propagate(False)

        top = ctk.CTkFrame(tile, fg_color="transparent")
        top.pack(fill="x", padx=16, pady=(14, 0))

        text_box = ctk.CTkFrame(top, fg_color="transparent")
        text_box.pack(side="left")
        ctk.CTkLabel(text_box, text=school_name, font=font(16, "bold"), text_color=C["text"]).pack(anchor="w")
        ctk.CTkLabel(text_box, text=f"{file_count} file{'s' if file_count != 1 else ''}",
                     font=font(12), text_color=C["muted"]).pack(anchor="w")

        ctk.CTkButton(top, text="🗑️", width=30, height=30, fg_color="transparent",
                      hover_color=C["danger_soft"], text_color=C["danger"], corner_radius=8,
                      command=lambda: self.delete_school(school_name)).pack(side="right", anchor="n")

        saved_mode = get_school_mode(school_name)
        mode_var = ctk.StringVar(value=saved_mode)

        mode_row = ctk.CTkFrame(tile, fg_color="transparent")
        mode_row.pack(fill="x", padx=16, pady=(10, 0))

        mode_chip = chip(mode_row,
                         "Both sides" if saved_mode == "Duplex" else "One side",
                         C["primary_soft"] if saved_mode == "Duplex" else C["amber_soft"],
                         C["primary"] if saved_mode == "Duplex" else C["amber_text"])

        def toggle_mode():
            current_mode = mode_var.get()
            set_school_mode(school_name, current_mode)
            is_d = current_mode == "Duplex"
            mode_chip.configure(text="Both sides" if is_d else "One side",
                                fg_color=C["primary_soft"] if is_d else C["amber_soft"],
                                text_color=C["primary"] if is_d else C["amber_text"])

        switch = ctk.CTkSwitch(mode_row, text="Duplex", variable=mode_var, onvalue="Duplex", offvalue="Simplex",
                               command=toggle_mode, progress_color=C["primary"], font=font(13),
                               text_color=C["text"])
        switch.pack(side="left")
        mode_chip.pack(side="right")

        if saved_mode == "Duplex":
            switch.select()
        else:
            switch.deselect()

        primary_btn(tile, "📁  Import PDFs", lambda s=school_name: self.import_pdfs(s), width=130).pack(
            side="bottom", anchor="e", padx=16, pady=14)

    def delete_school(self, school_name):
        confirm = messagebox.askyesno(
            "Delete school",
            f"Delete '{school_name}'?\n\n"
            f"⚠️ This permanently deletes the school folder, all PDFs inside it, and its database.\n\n"
            f"This cannot be undone."
        )
        if not confirm:
            return

        try:
            school_folder = os.path.join(DOCUMENTS_DIR, school_name)
            if os.path.exists(school_folder):
                shutil.rmtree(school_folder)

            db_path = get_db_path(school_name)
            if os.path.exists(db_path):
                os.remove(db_path)

            self.refresh_schools_list()   # also drops this school's cached data and cards
            messagebox.showinfo("Deleted", f"'{school_name}' was deleted.")

        except Exception as e:
            messagebox.showerror("Could not delete", f"Could not delete school: {e}")

    def open_add_school_modal(self):
        dialog = ctk.CTkToplevel(self)
        dialog.title("Add a school")
        dialog.geometry("420x230")
        dialog.configure(fg_color=C["surface"])
        dialog.attributes("-topmost", True)
        dialog.resizable(False, False)
        dialog.grab_set()

        ctk.CTkLabel(dialog, text="Add a school", font=font(18, "bold"), text_color=C["text"]).pack(anchor="w", padx=24, pady=(22, 2))
        ctk.CTkLabel(dialog, text="Folders for Grade 6 to 12 are created automatically.",
                     font=font(12), text_color=C["muted"]).pack(anchor="w", padx=24)

        name_entry = ctk.CTkEntry(dialog, height=38, corner_radius=8, placeholder_text="School name",
                                  border_color=C["border"], fg_color=C["surface_alt"], text_color=C["text"])
        name_entry.pack(fill="x", padx=24, pady=(16, 14))
        name_entry.focus()

        def confirm(event=None):
            name = name_entry.get().strip()
            if not name:
                messagebox.showerror("Name needed", "Enter a school name.", parent=dialog)
                return

            if any(char in name for char in r'\/:*?"<>|'):
                messagebox.showerror("Invalid name", "The name can't contain any of these: \\ / : * ? \" < > |", parent=dialog)
                return

            path = os.path.join(DOCUMENTS_DIR, name)
            if os.path.exists(path):
                messagebox.showerror("Already exists", "A school with this name already exists.", parent=dialog)
                return

            try:
                os.makedirs(path, exist_ok=True)
                for g in range(6, 13):
                    grade_path = os.path.join(path, f"Grade {g}")
                    os.makedirs(grade_path, exist_ok=True)

                init_db(name).close()
                set_school_mode(name, "Duplex")

                dialog.destroy()
                self.refresh_schools_list()
                messagebox.showinfo("School added", f"'{name}' is ready. Import your PDFs next.")

            except Exception as e:
                messagebox.showerror("Could not create", f"Failed to create folders: {e}")

        name_entry.bind("<Return>", confirm)
        btns = ctk.CTkFrame(dialog, fg_color="transparent")
        btns.pack(fill="x", padx=24)
        primary_btn(btns, "Create school", confirm, width=130, height=36).pack(side="right")
        ghost_btn(btns, "Cancel", dialog.destroy, width=80, height=36).pack(side="right", padx=8)

    def import_pdfs(self, school_name):
        files = filedialog.askopenfilenames(title=f"Select PDFs for {school_name}", filetypes=[("PDF Files", "*.pdf")])
        if not files:
            return

        unmatched = []
        imported = 0
        conn = init_db(school_name)
        is_duplex = get_school_mode(school_name) == "Duplex"

        for file_path in files:
            filename = os.path.basename(file_path)
            grade, subject = parse_filename(filename)

            if grade and subject:
                dest_folder = os.path.join(DOCUMENTS_DIR, school_name, f"Grade {grade}")
                os.makedirs(dest_folder, exist_ok=True)
                dest_path = os.path.join(dest_folder, filename)

                try:
                    shutil.copy2(file_path, dest_path)
                    pages = len(PdfReader(dest_path).pages)
                    sheets = math.ceil(pages / 2) if is_duplex else pages
                    price = sheets * self.current_price

                    add_file(conn, f"Grade {grade}", subject, dest_path, price)
                    imported += 1
                except Exception as e:
                    unmatched.append(f"{filename} (Error: {e})")
            else:
                unmatched.append(filename)

        conn.close()

        msg = f"Imported {imported} file{'s' if imported != 1 else ''} into {school_name}."
        if unmatched:
            msg += f"\n\n⚠️ {len(unmatched)} file{'s' if len(unmatched) != 1 else ''} not matched. Rename them like 'Grade 9 Math.pdf' and try again:\n\n"
            msg += "\n".join(unmatched[:10])
            if len(unmatched) > 10:
                msg += "\n...and more."

        messagebox.showinfo("Import complete", msg)

        # Only this school's data needs reloading
        self.load_school(school_name)
        self.catalog_dirty = True
        self.refresh_schools_list()

    # ==========================================
    # PRINT TAB
    # ==========================================
    def setup_print_ui(self):
        right_pane = card(self.print_frame, width=360, corner_radius=14)
        right_pane.pack(side="right", fill="y", padx=(18, 0))
        right_pane.pack_propagate(False)

        left_pane = ctk.CTkFrame(self.print_frame, fg_color="transparent")
        left_pane.pack(side="left", fill="both", expand=True)

        # --- LEFT PANE (CATALOG) ---
        title_row = ctk.CTkFrame(left_pane, fg_color="transparent")
        title_row.pack(fill="x", pady=(0, 14))
        title_box = ctk.CTkFrame(title_row, fg_color="transparent")
        title_box.pack(side="left")
        ctk.CTkLabel(title_box, text="Catalog", font=font(28, "bold"), text_color=C["text"]).pack(anchor="w")
        ctk.CTkLabel(title_box, text="Find a file, set copies and add it to the queue.",
                     font=font(13), text_color=C["muted"]).pack(anchor="w")
        self.result_label = ctk.CTkLabel(title_row, text="", font=font(13), text_color=C["muted"])
        self.result_label.pack(side="right", anchor="s", pady=(0, 4))

        printer_frame = card(left_pane)
        printer_frame.pack(fill="x", pady=(0, 12))

        ctk.CTkLabel(printer_frame, text="🖨️  Printer", font=font(13, "bold"), text_color=C["text"]).pack(side="left", padx=(16, 10), pady=12)

        self.printer_var = ctk.StringVar()
        self.printer_combo = ctk.CTkComboBox(printer_frame, variable=self.printer_var, width=300, height=34,
                                             corner_radius=8, border_color=C["border"], fg_color=C["surface_alt"],
                                             button_color=C["primary"], button_hover_color=C["primary_hover"],
                                             text_color=C["text"], font=font(13))
        self.printer_combo.pack(side="left", padx=6)
        self.refresh_printers()

        self.lock_btn = ctk.CTkButton(printer_frame, text="🔓  Unlocked", width=120, height=34, corner_radius=8,
                                      fg_color=C["success_soft"], hover_color="#BBF7D0", text_color=C["success"],
                                      font=font(13, "bold"), command=self.toggle_printer_lock)
        self.lock_btn.pack(side="right", padx=16)

        # --- SCHOOL FILTER (pills) ---
        self.pill_bar = ctk.CTkFrame(left_pane, fg_color="transparent")
        self.pill_bar.pack(fill="x", pady=(0, 4))
        self.pill_bar.bind("<Configure>", lambda e: self.layout_pills())

        # --- SEARCH ---
        self.search_var = ctk.StringVar()
        self.search_var.trace_add("write", self.on_search_change)
        search_entry = ctk.CTkEntry(left_pane, placeholder_text="🔍  Search by grade, subject, or file name",
                                    textvariable=self.search_var, height=42, corner_radius=10,
                                    border_color=C["border"], fg_color=C["surface"], text_color=C["text"],
                                    font=font(13))
        search_entry.pack(fill="x", pady=(0, 12))

        self.catalog_scroll = ctk.CTkScrollableFrame(left_pane, fg_color="transparent")
        self.catalog_scroll.pack(fill="both", expand=True)

        # One reusable empty-state block (shown/hidden instead of rebuilt)
        self.empty_box = ctk.CTkFrame(self.catalog_scroll, fg_color="transparent")
        self.empty_icon = ctk.CTkLabel(self.empty_box, text="📂", font=font(34))
        self.empty_icon.pack()
        self.empty_title = ctk.CTkLabel(self.empty_box, text="", font=font(15, "bold"), text_color=C["text"])
        self.empty_title.pack(pady=(6, 2))
        self.empty_hint = ctk.CTkLabel(self.empty_box, text="", font=font(12), text_color=C["muted"], wraplength=300)
        self.empty_hint.pack()

        # --- RIGHT PANE (QUEUE) ---
        q_header = ctk.CTkFrame(right_pane, fg_color="transparent")
        q_header.pack(fill="x", padx=18, pady=(18, 6))
        ctk.CTkLabel(q_header, text="Print queue", font=font(18, "bold"), text_color=C["text"]).pack(side="left")
        self.queue_badge = chip(q_header, "0", C["primary_soft"], C["primary"])
        self.queue_badge.pack(side="left", padx=10)

        self.queue_scroll = ctk.CTkScrollableFrame(right_pane, fg_color=C["surface_alt"], corner_radius=10)
        self.queue_scroll.pack(fill="both", expand=True, padx=14, pady=8)

        summary = ctk.CTkFrame(right_pane, fg_color="transparent")
        summary.pack(fill="x", padx=18, pady=(4, 10))
        ctk.CTkLabel(summary, text="Total", font=font(13), text_color=C["muted"]).pack(side="left")
        self.total_label = ctk.CTkLabel(summary, text="0.00 Birr", font=font(22, "bold"), text_color=C["text"])
        self.total_label.pack(side="right")

        primary_btn(right_pane, "Print batch", self.confirm_and_print, height=46).pack(fill="x", padx=18, pady=(0, 8))
        ghost_btn(right_pane, "Clear queue", self.clear_queue, height=36, danger=True).pack(fill="x", padx=18, pady=(0, 18))

    # ---------- School pills ----------
    def rebuild_school_pills(self):
        for pill in self.pills.values():
            pill.destroy()
        self.pills = {}

        if self.school_filter is not None and self.school_filter not in self.schools:
            self.school_filter = None

        total = sum(len(items) for items in self.data_cache.values())
        entries = [(None, "All schools", total)]
        entries += [(s, s, len(self.data_cache.get(s, []))) for s in self.schools]

        for key, label, count in entries:
            self.pills[key] = ctk.CTkButton(
                self.pill_bar, text=f"{label}   {count}", height=32, corner_radius=16,
                font=font(13, "bold"), border_width=1,
                command=lambda k=key: self.select_school(k))

        self.style_pills()
        self.layout_pills(force=True)
        self.after_idle(lambda: self.layout_pills(force=True))

    def style_pills(self):
        for key, pill in self.pills.items():
            active = key == self.school_filter
            pill.configure(
                fg_color=C["primary"] if active else C["surface"],
                hover_color=C["primary_hover"] if active else C["primary_soft"],
                text_color="white" if active else C["text"],
                border_color=C["primary"] if active else C["border"])

    def layout_pills(self, force=False):
        """Flow the pills left to right and wrap onto new lines when they run out of room."""
        width = self.pill_bar.winfo_width()
        if width <= 1 or not self.pills:
            return
        if not force and width == self._pill_width:
            return
        self._pill_width = width

        x, row, col = 0, 0, 0
        for pill in self.pills.values():
            w = pill.winfo_reqwidth() + 8
            if col > 0 and x + w > width:
                row += 1
                col = 0
                x = 0
            pill.grid(row=row, column=col, padx=(0, 8), pady=(0, 8), sticky="w")
            x += w
            col += 1

    def select_school(self, key):
        if key == self.school_filter:
            return
        self.school_filter = key
        self.style_pills()
        self.apply_filter()

    # ---------- Printers & lock ----------
    def refresh_printers(self):
        printers = []
        if win32print:
            try:
                printers = [p[2] for p in win32print.EnumPrinters(2)]
            except Exception:
                pass
        filtered = [p for p in printers if any(k in p.lower() for k in PRINTER_KEYWORDS)]
        if not filtered:
            filtered = printers
        if not filtered:
            filtered = ["No printers found"]

        self.printer_combo.configure(values=filtered)
        if filtered:
            self.printer_combo.set(filtered[0])

    def set_printer_lock(self, locked):
        if locked:
            self.lock_btn.configure(text="🔒  Locked", fg_color=C["danger_soft"],
                                    hover_color="#FECACA", text_color=C["danger"])
            self.printer_combo.configure(state="disabled")
        else:
            self.lock_btn.configure(text="🔓  Unlocked", fg_color=C["success_soft"],
                                    hover_color="#BBF7D0", text_color=C["success"])
            self.printer_combo.configure(state="normal")

    def is_printer_locked(self):
        return "Locked" in self.lock_btn.cget("text")

    def toggle_printer_lock(self):
        if self.is_printer_locked():
            if self.queue:
                messagebox.showwarning("Queue not empty", "Clear the print queue before changing the printer.")
                return
            self.set_printer_lock(False)
        else:
            if not self.printer_var.get() or "No printers" in self.printer_var.get():
                messagebox.showerror("No printer", "Select a valid printer first.")
                return
            self.set_printer_lock(True)

    def update_print_ui(self):
        if self.queue and not self.is_printer_locked():
            self.set_printer_lock(True)
        self.update_queue_ui()

    # ---------- Catalog rendering ----------
    def _empty_state(self, parent, icon, title, hint):
        """Used by the queue panel (small, rebuilt rarely)."""
        box = ctk.CTkFrame(parent, fg_color="transparent")
        box.pack(fill="x", pady=40)
        ctk.CTkLabel(box, text=icon, font=font(34)).pack()
        ctk.CTkLabel(box, text=title, font=font(15, "bold"), text_color=C["text"]).pack(pady=(6, 2))
        ctk.CTkLabel(box, text=hint, font=font(12), text_color=C["muted"], wraplength=300).pack()

    def on_search_change(self, *args):
        if self._search_job is not None:
            self.after_cancel(self._search_job)
        self._search_job = self.after(SEARCH_DELAY_MS, self.apply_filter)

    def filter_catalog(self, *args):
        """Kept for compatibility with older callers."""
        self.apply_filter()

    def apply_filter(self):
        """Work out which files match, hide everything, then show matches in order.
        Cards are reused from the cache; only never-seen cards get built, in batches."""
        self._search_job = None
        self._render_token += 1
        token = self._render_token

        query = self.search_var.get().lower().strip()
        schools = [self.school_filter] if self.school_filter else self.schools

        matches, total = [], 0
        for school in schools:
            for item in self.data_cache.get(school, []):
                total += 1
                if query and query not in item["search"]:
                    continue
                matches.append(item)

        for widget in self._visible_cards:
            widget.pack_forget()
        self._visible_cards = []
        self.empty_box.pack_forget()

        self.result_label.configure(
            text=f"{len(matches)} of {total} files" if query else f"{total} file{'s' if total != 1 else ''}")

        if not matches:
            if query:
                self.empty_icon.configure(text="🔍")
                self.empty_title.configure(text="No matches")
                self.empty_hint.configure(text="Try a different grade, subject or file name.")
            else:
                self.empty_icon.configure(text="📂")
                self.empty_title.configure(text="No files yet")
                self.empty_hint.configure(text="Go to Schools and import PDFs to fill the catalog.")
            self.empty_box.pack(fill="x", pady=40)
            return

        self._render_batch(token, matches, 0)

    def _render_batch(self, token, matches, start):
        if token != self._render_token:
            return  # a newer filter replaced this render

        end = min(start + RENDER_BATCH, len(matches))
        for item in matches[start:end]:
            key = (item["school"], item["id"])
            widget = self.card_cache.get(key)
            if widget is None:
                widget = self.create_catalog_card(item)
                self.card_cache[key] = widget
            widget.pack(fill="x", pady=4, padx=2)
            self._visible_cards.append(widget)

        if end < len(matches):
            self.after(1, lambda: self._render_batch(token, matches, end))

    def create_catalog_card(self, item):
        fid, school, grade = item["id"], item["school"], item["grade"]
        subject, price, loc = item["subject"], item["price"], item["loc"]

        row = card(self.catalog_scroll, corner_radius=10)

        # Grade badge
        grade_num = grade.replace("Grade", "").strip()
        badge = ctk.CTkFrame(row, width=48, height=48, corner_radius=10, fg_color=C["primary_soft"])
        badge.pack(side="left", padx=(12, 0), pady=12)
        badge.pack_propagate(False)
        ctk.CTkLabel(badge, text=grade_num, font=font(18, "bold"), text_color=C["primary"]).pack(expand=True)

        # Info
        info_frame = ctk.CTkFrame(row, fg_color="transparent")
        info_frame.pack(side="left", fill="both", expand=True, padx=12, pady=10)
        ctk.CTkLabel(info_frame, text=subject, font=font(15, "bold"), text_color=C["text"], anchor="w").pack(anchor="w")
        ctk.CTkLabel(info_frame, text=f"{grade}  •  {school}  •  {price:.0f} Birr",
                     font=font(12), text_color=C["muted"], anchor="w").pack(anchor="w")

        # Controls
        btn_frame = ctk.CTkFrame(row, fg_color="transparent")
        btn_frame.pack(side="right", padx=12)

        copies_var = ctk.StringVar(value="1")

        def step(delta):
            try:
                v = int(copies_var.get())
            except ValueError:
                v = 1
            copies_var.set(str(max(1, v + delta)))

        stepper = ctk.CTkFrame(btn_frame, fg_color=C["surface_alt"], corner_radius=8,
                               border_width=1, border_color=C["border"])
        stepper.pack(side="left", padx=(0, 10))
        ctk.CTkButton(stepper, text="−", width=28, height=30, fg_color="transparent", hover_color=C["border"],
                      text_color=C["text"], corner_radius=6, font=font(15, "bold"),
                      command=lambda: step(-1)).pack(side="left", padx=(2, 0), pady=2)
        ctk.CTkEntry(stepper, textvariable=copies_var, width=40, height=30, justify="center",
                     border_width=0, fg_color="transparent", text_color=C["text"],
                     font=font(13, "bold")).pack(side="left")
        ctk.CTkButton(stepper, text="+", width=28, height=30, fg_color="transparent", hover_color=C["border"],
                      text_color=C["text"], corner_radius=6, font=font(15, "bold"),
                      command=lambda: step(1)).pack(side="left", padx=(0, 2), pady=2)

        ghost_btn(btn_frame, "Open", lambda: self.open_pdf(loc), width=64).pack(side="left", padx=3)
        primary_btn(btn_frame, "Add", lambda: self.add_to_queue(school, subject, loc, price, copies_var), width=64).pack(side="left", padx=3)
        ctk.CTkButton(btn_frame, text="🗑️", width=34, height=34, fg_color="transparent",
                      hover_color=C["danger_soft"], text_color=C["danger"], corner_radius=8,
                      command=lambda: self.soft_delete_pdf(school, fid, loc)).pack(side="left", padx=(3, 0))
        return row

    def open_pdf(self, loc):
        try:
            os.startfile(loc)
        except Exception as e:
            messagebox.showerror("Could not open", f"Could not open PDF: {e}")

    def soft_delete_pdf(self, school, fid, loc):
        if not messagebox.askyesno("Remove file", "Move this file to the 'old' folder?\nIt will no longer show in the catalog."):
            return

        try:
            grade_folder = os.path.dirname(loc)
            old_folder = os.path.join(grade_folder, "old")
            os.makedirs(old_folder, exist_ok=True)

            filename = os.path.basename(loc)
            new_loc = os.path.join(old_folder, filename)
            shutil.move(loc, new_loc)

            conn = init_db(school)
            conn.execute("UPDATE files SET is_old = 1, location = ? WHERE location = ?", (new_loc, loc))
            conn.commit()
            conn.close()

            # Update memory and the UI without reloading anything else
            self.data_cache[school] = [i for i in self.data_cache.get(school, []) if i["id"] != fid]
            self.destroy_card((school, fid))
            self.home_dirty = True
            self.rebuild_school_pills()
            self.apply_filter()
        except Exception as e:
            messagebox.showerror("Could not move", f"Could not move file: {e}")

    # ---------- Queue ----------
    def add_to_queue(self, school, subject, loc, price, copies_var):
        if not self.printer_var.get() or "No printers" in self.printer_var.get():
            messagebox.showwarning("No printer", "Select a printer before adding files to the queue.")
            return

        try:
            copies = int(copies_var.get())
            if copies < 1:
                raise ValueError
        except ValueError:
            messagebox.showerror("Invalid copies", "Copies must be a whole number of 1 or more.")
            return

        if not self.queue:
            self.set_printer_lock(True)

        total_job_price = price * copies

        self.queue.append({
            'school': school,
            'subject': subject,
            'loc': loc,
            'price': total_job_price,
            'copies': copies
        })
        self.update_queue_ui()

    def update_queue_ui(self):
        for widget in self.queue_scroll.winfo_children():
            widget.destroy()

        total = 0
        for i, item in enumerate(self.queue):
            total += item['price']
            frame = ctk.CTkFrame(self.queue_scroll, fg_color=C["surface"], corner_radius=8,
                                 border_width=1, border_color=C["border"])
            frame.pack(fill="x", pady=3, padx=2)

            text_box = ctk.CTkFrame(frame, fg_color="transparent")
            text_box.pack(side="left", fill="x", expand=True, padx=10, pady=8)
            ctk.CTkLabel(text_box, text=item['subject'], font=font(13, "bold"), text_color=C["text"], anchor="w").pack(anchor="w")
            detail = f"{item['school']}  •  {item['price']:.0f} Birr"
            if item['copies'] > 1:
                detail += f"  •  ×{item['copies']}"
            ctk.CTkLabel(text_box, text=detail, font=font(11), text_color=C["muted"], anchor="w").pack(anchor="w")

            ctk.CTkButton(frame, text="✕", width=28, height=28, fg_color="transparent",
                          hover_color=C["danger_soft"], text_color=C["danger"], corner_radius=6,
                          command=lambda idx=i: self.remove_from_queue(idx)).pack(side="right", padx=6)

        if not self.queue:
            self._empty_state(self.queue_scroll, "🧾", "Queue is empty", "Add files from the catalog to print them together.")

        self.queue_badge.configure(text=str(len(self.queue)))
        self.total_label.configure(text=f"{total:.2f} Birr")
        self.update_sidebar_status()

    def remove_from_queue(self, idx):
        del self.queue[idx]
        if not self.queue:
            self.set_printer_lock(False)
        self.update_queue_ui()

    def clear_queue(self):
        self.queue = []
        self.set_printer_lock(False)
        self.update_queue_ui()

    def confirm_and_print(self):
        if not self.queue:
            messagebox.showinfo("Queue is empty", "Add at least one file to the queue first.")
            return

        printer = self.printer_var.get()
        total_price = sum(item['price'] for item in self.queue)

        duplex_jobs = [j for j in self.queue if get_school_mode(j['school']) == "Duplex"]
        simplex_jobs = [j for j in self.queue if get_school_mode(j['school']) == "Simplex"]

        msg = f"🖨️ Printer: {printer}\n\n"
        msg += f"📦 Jobs: {len(self.queue)}\n"
        msg += f"💰 Total: {total_price:.2f} Birr\n\n"
        if duplex_jobs:
            msg += f"📄 Both sides (duplex): {len(duplex_jobs)}\n"
        if simplex_jobs:
            msg += f"📄 One side (simplex): {len(simplex_jobs)}\n"
        msg += "\nStart printing?"

        if not messagebox.askyesno("Confirm print job", msg):
            return

        try:
            self.execute_printing(printer, duplex_jobs, simplex_jobs)
        except Exception as e:
            messagebox.showerror("Print error", str(e))
        finally:
            self.queue = []
            self.update_queue_ui()
            self.set_printer_lock(False)

    def execute_printing(self, printer, duplex_jobs, simplex_jobs):
        if simplex_jobs:
            writer = PdfWriter()
            for job in simplex_jobs:
                reader = PdfReader(job['loc'])
                for _ in range(job['copies']):
                    for page in reader.pages:
                        writer.add_page(page)
            simplex_path = os.path.join(CACHE_FOLDER, "SIMPLEX_BATCH.pdf")
            with open(simplex_path, "wb") as f:
                writer.write(f)
            send_to_printer(simplex_path, printer)

        if duplex_jobs:
            writer = PdfWriter()
            for job in duplex_jobs:
                reader = PdfReader(job['loc'])
                for _ in range(job['copies']):
                    for page in reader.pages:
                        writer.add_page(page)
            duplex_path = os.path.join(CACHE_FOLDER, "DUPLEX_MASTER.pdf")
            with open(duplex_path, "wb") as f:
                writer.write(f)

            odd_path, even_path, has_even = split_pdf_for_duplex(duplex_path, printer)

            send_to_printer(odd_path, printer)

            if has_even:
                ans = messagebox.askyesno(
                    "Flip the paper",
                    "Odd pages are printing.\n\nTake the stack, flip it, and put it back in the tray.\n\nClick Yes to print the even pages.")
                if ans:
                    send_to_printer(even_path, printer)

        messagebox.showinfo("Done", "All jobs were sent to the printer.")


if __name__ == "__main__":
    app = ZenOpsDashboard()
    app.protocol("WM_DELETE_WINDOW", app.destroy)
    app.mainloop()