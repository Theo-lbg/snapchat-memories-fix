#!/usr/bin/env python3
"""Interface graphique (Tkinter) de Snapchat Memories Fixer.

Tkinter fait partie de la bibliothèque standard Python -- aucune dépendance
supplémentaire n'est nécessaire pour lancer cette interface depuis les
sources.
"""

from __future__ import annotations

import os
import queue
import shutil
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from snapfixer import core

APP_TITLE = "Snapchat Memories Fixer"
WINDOW_SIZE = "820x760"
GB = 1024 ** 3


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry(WINDOW_SIZE)
        self.minsize(680, 520)

        self.source_var = tk.StringVar()
        self.output_var = tk.StringVar()
        self.merge_overlay_var = tk.BooleanVar(value=True)
        self.dry_run_var = tk.BooleanVar(value=False)
        self.only_overlay_videos_var = tk.BooleanVar(value=False)
        self.repair_var = tk.BooleanVar(value=False)
        self.use_limit_var = tk.BooleanVar(value=False)
        self.limit_var = tk.StringVar(value="50")
        self.space_note_var = tk.StringVar(value="")

        self._queue: "queue.Queue" = queue.Queue()
        self._worker: threading.Thread | None = None

        self._build_ui()
        self.after(100, self._poll_queue)
        self.after(200, self._check_ffmpeg)

    # ------------------------------------------------------------------ UI

    def _build_ui(self):
        pad = {"padx": 10, "pady": 6}

        header = ttk.Frame(self)
        header.pack(fill="x", **pad)
        ttk.Label(header, text=APP_TITLE, font=("TkDefaultFont", 16, "bold")).pack(anchor="w")
        ttk.Label(
            header,
            text=(
                "Récupère les dates, heures, GPS et superpositions (texte/dessins) de votre "
                "export Snapchat (« Télécharger mes données »), et écrit une bibliothèque "
                "de photos/vidéos correctement datées."
            ),
            wraplength=780,
            justify="left",
        ).pack(anchor="w", pady=(2, 0))

        source_frame = ttk.LabelFrame(self, text="Export Snapchat (zip ou dossier primaire)")
        source_frame.pack(fill="x", **pad)
        row = ttk.Frame(source_frame)
        row.pack(fill="x", padx=8, pady=8)
        ttk.Entry(row, textvariable=self.source_var).pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="Choisir un .zip…", command=self._choose_source_zip).pack(side="left", padx=(8, 0))
        ttk.Button(row, text="Choisir un dossier…", command=self._choose_source_folder).pack(side="left", padx=(6, 0))

        output_frame = ttk.LabelFrame(self, text="Dossier de destination")
        output_frame.pack(fill="x", **pad)
        row2 = ttk.Frame(output_frame)
        row2.pack(fill="x", padx=8, pady=8)
        ttk.Entry(row2, textvariable=self.output_var).pack(side="left", fill="x", expand=True)
        ttk.Button(row2, text="Choisir…", command=self._choose_output).pack(side="left", padx=(8, 0))

        opts_frame = ttk.LabelFrame(self, text="Options")
        opts_frame.pack(fill="x", **pad)

        row3 = ttk.Frame(opts_frame)
        row3.pack(fill="x", padx=8, pady=(8, 4))
        ttk.Checkbutton(
            row3, text="Fusionner les superpositions (-overlay.png) sur les photos/vidéos",
            variable=self.merge_overlay_var,
        ).pack(side="left")

        row3b = ttk.Frame(opts_frame)
        row3b.pack(fill="x", padx=8, pady=4)
        ttk.Checkbutton(
            row3b,
            text="Ne retraiter que les vidéos avec superposition (répare une sortie déjà générée, dans le même dossier)",
            variable=self.only_overlay_videos_var,
        ).pack(side="left")

        row3c = ttk.Frame(opts_frame)
        row3c.pack(fill="x", padx=8, pady=4)
        ttk.Checkbutton(
            row3c,
            text="Réparer un dossier déjà corrigé (sans l'export d'origine) : le choisir comme source ci-dessus",
            variable=self.repair_var,
        ).pack(side="left")

        row4 = ttk.Frame(opts_frame)
        row4.pack(fill="x", padx=8, pady=4)
        ttk.Checkbutton(row4, text="Simulation (afficher sans rien écrire)", variable=self.dry_run_var).pack(side="left")

        row5 = ttk.Frame(opts_frame)
        row5.pack(fill="x", padx=8, pady=(4, 8))
        ttk.Checkbutton(
            row5, text="Limiter à un échantillon de test :", variable=self.use_limit_var,
        ).pack(side="left")
        ttk.Entry(row5, textvariable=self.limit_var, width=8).pack(side="left", padx=(6, 0))
        ttk.Label(row5, text="fichiers (pour vérifier avant de tout lancer)").pack(side="left", padx=(4, 0))

        space_frame = ttk.Frame(self)
        space_frame.pack(fill="x", **pad)
        ttk.Label(space_frame, textvariable=self.space_note_var, foreground="#a06000").pack(anchor="w")

        action_frame = ttk.Frame(self)
        action_frame.pack(fill="x", **pad)
        self.run_button = ttk.Button(action_frame, text="Corriger mes souvenirs", command=self._start)
        self.run_button.pack(side="left")
        self.progress = ttk.Progressbar(action_frame, mode="determinate")
        self.progress.pack(side="left", fill="x", expand=True, padx=(10, 0))

        log_frame = ttk.LabelFrame(self, text="Journal")
        log_frame.pack(fill="both", expand=True, **pad)
        self.log_text = tk.Text(log_frame, wrap="word", state="disabled", height=16)
        self.log_text.pack(fill="both", expand=True, padx=8, pady=8)

    # -------------------------------------------------------------- events

    def _check_ffmpeg(self):
        if shutil.which("ffmpeg"):
            return
        if sys.platform == "darwin":
            howto = "Terminal : «brew install ffmpeg» (installe d'abord Homebrew sur brew.sh si besoin)."
        elif sys.platform == "win32":
            howto = (
                "Le plus simple : «winget install ffmpeg» dans un Terminal, "
                "ou installe-le depuis ffmpeg.org et ajoute-le au PATH."
            )
        else:
            howto = "Installe le paquet ffmpeg de ta distribution (ex: apt install ffmpeg)."
        messagebox.showwarning(
            APP_TITLE,
            "ffmpeg est introuvable sur cet ordinateur : les vidéos ne pourront pas être "
            "corrigées (les photos, oui). " + howto,
        )

    def _choose_source_zip(self):
        chosen = filedialog.askopenfilename(title="Choisir le zip de l'export Snapchat", filetypes=[("Zip", "*.zip")])
        if chosen:
            self.source_var.set(chosen)
            self._update_space_note()

    def _choose_source_folder(self):
        chosen = filedialog.askdirectory(title="Choisir le dossier primaire de l'export Snapchat")
        if chosen:
            self.source_var.set(chosen)
            self._update_space_note()

    def _choose_output(self):
        chosen = filedialog.askdirectory(title="Choisir le dossier de destination")
        if chosen:
            self.output_var.set(chosen)
            self._update_space_note()

    def _update_space_note(self):
        source = self.source_var.get().strip()
        output = self.output_var.get().strip()
        if not source or not os.path.exists(source):
            self.space_note_var.set("")
            return
        try:
            estimate = core.estimate_source_bytes(Path(source))
        except OSError:
            self.space_note_var.set("")
            return
        note = f"Taille source ≈ {estimate / GB:.1f} Go (estimation, la sortie sera d'un ordre de grandeur similaire)."
        check_dir = output if output and os.path.isdir(output) else os.path.expanduser("~")
        try:
            free = shutil.disk_usage(check_dir).free
            note += f" Espace libre à destination : {free / GB:.1f} Go."
            if free < estimate:
                note += " ⚠ Espace probablement insuffisant pour un traitement complet."
        except OSError:
            pass
        self.space_note_var.set(note)

    def _log(self, message: str):
        self.log_text.configure(state="normal")
        self.log_text.insert("end", message + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _start(self):
        source = self.source_var.get().strip()
        output = self.output_var.get().strip()
        if self.repair_var.get():
            if not source or not os.path.isdir(source):
                messagebox.showerror(APP_TITLE, "Choisis comme source le dossier déjà corrigé à réparer.")
                return
            if self._worker and self._worker.is_alive():
                return
            self.log_text.configure(state="normal")
            self.log_text.delete("1.0", "end")
            self.log_text.configure(state="disabled")
            self.progress["value"] = 0
            self.run_button.configure(state="disabled")
            self._worker = threading.Thread(
                target=self._run_repair_worker, args=(Path(source), self.dry_run_var.get()), daemon=True
            )
            self._worker.start()
            return
        if not source or not os.path.exists(source):
            messagebox.showerror(APP_TITLE, "Choisis d'abord un export Snapchat valide (zip ou dossier).")
            return
        if not output:
            messagebox.showerror(APP_TITLE, "Choisis d'abord un dossier de destination.")
            return
        if self._worker and self._worker.is_alive():
            return

        limit = None
        if self.use_limit_var.get():
            raw = self.limit_var.get().strip()
            if not raw.isdigit() or int(raw) <= 0:
                messagebox.showerror(APP_TITLE, "L'échantillon de test doit être un nombre entier positif.")
                return
            limit = int(raw)

        self._update_space_note()
        if not limit and not self.dry_run_var.get() and not self.only_overlay_videos_var.get():
            estimate = core.estimate_source_bytes(Path(source))
            os.makedirs(output, exist_ok=True)
            free = shutil.disk_usage(output).free
            if free < estimate:
                proceed = messagebox.askyesno(
                    APP_TITLE,
                    f"Espace libre à destination ({free / GB:.1f} Go) inférieur à la taille "
                    f"source estimée ({estimate / GB:.1f} Go). Le traitement complet risque de "
                    f"remplir le disque. Continuer quand même ?\n\n"
                    f"Astuce : cochez « échantillon de test » pour vérifier sur un petit "
                    f"nombre de fichiers avant de tout lancer.",
                )
                if not proceed:
                    return

        options = core.Options(
            merge_overlay=self.merge_overlay_var.get(),
            dry_run=self.dry_run_var.get(),
            limit=limit,
            only_overlay_videos=self.only_overlay_videos_var.get(),
        )

        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")
        self.progress["value"] = 0
        self.run_button.configure(state="disabled")

        self._worker = threading.Thread(target=self._run_worker, args=(Path(source), Path(output), options), daemon=True)
        self._worker.start()

    def _run_repair_worker(self, folder: Path, dry_run: bool):
        try:
            def on_progress(i, total, result):
                self._queue.put(("progress", i, total, result))

            summary = core.repair_folder(folder, dry_run=dry_run, on_progress=on_progress)
            msg = f"Terminé. {summary.ok}/{summary.total} vidéo(s) réparée(s) dans {folder}."
            if summary.total == 0:
                msg = "Rien à réparer : aucune vidéo en plage de couleurs non standard dans ce dossier."
            if summary.failed:
                msg += f" {summary.failed} échec(s), voir le journal ci-dessus."
            self._queue.put(("done", msg))
        except Exception as exc:  # noqa: BLE001 - surface any failure to the user
            self._queue.put(("error", str(exc)))

    def _run_worker(self, source: Path, output: Path, options: core.Options):
        try:
            def on_progress(i, total, result):
                self._queue.put(("progress", i, total, result))

            summary = core.run(source, output, options, on_progress=on_progress)
            msg = f"Terminé. {summary.ok}/{summary.total} fichier(s) écrit(s) dans {output}."
            if summary.failed:
                msg += f" {summary.failed} échec(s), voir le journal ci-dessus."
            msg += f"\n{summary.fallback_count} item(s) sans correspondance JSON exacte (date seule, pas d'heure/GPS)."
            self._queue.put(("done", msg))
        except core.SourceError as exc:
            self._queue.put(("error", str(exc)))
        except Exception as exc:  # noqa: BLE001 - surface any unexpected failure to the user
            self._queue.put(("error", str(exc)))

    def _poll_queue(self):
        try:
            while True:
                item = self._queue.get_nowait()
                kind = item[0]
                if kind == "progress":
                    _, i, total, result = item
                    self.progress["maximum"] = total
                    self.progress["value"] = i
                    self._log(self._format_result(i, total, result))
                elif kind == "done":
                    self._log("\n" + item[1])
                    self.run_button.configure(state="normal")
                elif kind == "error":
                    self._log(f"\nErreur : {item[1]}")
                    messagebox.showerror(APP_TITLE, f"Une erreur est survenue :\n{item[1]}")
                    self.run_button.configure(state="normal")
        except queue.Empty:
            pass
        self.after(100, self._poll_queue)

    @staticmethod
    def _format_result(i: int, total: int, result: core.ItemResult) -> str:
        prefix = f"[{i}/{total}] {result.name}"
        if result.skipped:
            return f"{prefix} — simulation, ignoré"
        if not result.ok:
            return f"{prefix} — ÉCHEC : {result.message}"
        if result.timestamp is None:
            return f"{prefix} — réparée"
        gps_note = "" if result.has_gps else " (date seule, pas de correspondance JSON exacte)"
        return f"{prefix} -> {result.outname} ({result.timestamp:%d/%m/%Y %H:%M}){gps_note}"


def main():
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
