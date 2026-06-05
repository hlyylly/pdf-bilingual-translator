"""PDF 双语翻译 - 桌面版 (CustomTkinter)。
填入 DeepSeek / PaddleOCR 密钥 → 选 PDF → 开始，即可批量生成逐页对照 PDF。
"""
import os
import queue
import threading
import subprocess
import sys
import customtkinter as ctk
from tkinter import filedialog

from pdf_translator import Config, __version__
from pdf_translator.pipeline import translate_pdfs

ctk.set_appearance_mode("System")
ctk.set_default_color_theme("blue")


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title(f"PDF 双语翻译器  v{__version__}")
        self.geometry("860x720")
        self.minsize(760, 640)

        self.pdf_files = []
        self.worker = None
        self._cancel = False
        self.msg_q = queue.Queue()
        self.cfg = Config.load()

        self._build_ui()
        self._fill_config()
        self.after(120, self._drain_queue)

    # ---------------- UI ----------------
    def _build_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(4, weight=1)

        # --- 标题 ---
        ctk.CTkLabel(self, text="PDF 双语对照翻译",
                     font=ctk.CTkFont(size=22, weight="bold")).grid(
            row=0, column=0, padx=20, pady=(16, 4), sticky="w")
        ctk.CTkLabel(self, text="PaddleOCR-VL 解析 · DeepSeek 翻译 · 逐页英中对照",
                     text_color="gray").grid(row=0, column=0, padx=20, pady=(0, 0), sticky="e")

        # --- 密钥区 ---
        keyf = ctk.CTkFrame(self)
        keyf.grid(row=1, column=0, padx=20, pady=8, sticky="ew")
        keyf.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(keyf, text="DeepSeek API Key").grid(row=0, column=0, padx=12, pady=8, sticky="w")
        self.e_ds = ctk.CTkEntry(keyf, placeholder_text="sk-...", show="•")
        self.e_ds.grid(row=0, column=1, padx=8, pady=8, sticky="ew")

        ctk.CTkLabel(keyf, text="PaddleOCR Token").grid(row=1, column=0, padx=12, pady=8, sticky="w")
        self.e_pd = ctk.CTkEntry(keyf, placeholder_text="飞桨 aistudio token", show="•")
        self.e_pd.grid(row=1, column=1, padx=8, pady=8, sticky="ew")

        self.show_var = ctk.StringVar(value="off")
        ctk.CTkSwitch(keyf, text="显示", variable=self.show_var, onvalue="on", offvalue="off",
                      command=self._toggle_show, width=60).grid(row=0, column=2, padx=8)
        ctk.CTkLabel(keyf, text="模型").grid(row=2, column=0, padx=12, pady=8, sticky="w")
        self.e_model = ctk.CTkEntry(keyf)
        self.e_model.grid(row=2, column=1, padx=8, pady=8, sticky="ew")
        ctk.CTkButton(keyf, text="保存密钥", width=80, command=self._save_config).grid(
            row=2, column=2, padx=8, pady=8)

        # --- 文件区 ---
        filef = ctk.CTkFrame(self)
        filef.grid(row=2, column=0, padx=20, pady=8, sticky="ew")
        filef.grid_columnconfigure(0, weight=1)
        self.lbl_files = ctk.CTkLabel(filef, text="未选择 PDF", anchor="w")
        self.lbl_files.grid(row=0, column=0, padx=12, pady=8, sticky="ew")
        btns = ctk.CTkFrame(filef, fg_color="transparent")
        btns.grid(row=0, column=1, padx=8, pady=6)
        ctk.CTkButton(btns, text="添加文件", width=86, command=self._add_files).pack(side="left", padx=4)
        ctk.CTkButton(btns, text="添加文件夹", width=96, command=self._add_folder).pack(side="left", padx=4)
        ctk.CTkButton(btns, text="清空", width=60, fg_color="gray",
                      command=self._clear_files).pack(side="left", padx=4)

        # --- 输出 + 并发 ---
        outf = ctk.CTkFrame(self)
        outf.grid(row=3, column=0, padx=20, pady=8, sticky="ew")
        outf.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(outf, text="输出目录").grid(row=0, column=0, padx=12, pady=8, sticky="w")
        self.e_out = ctk.CTkEntry(outf)
        self.e_out.insert(0, os.path.join(os.getcwd(), "output"))
        self.e_out.grid(row=0, column=1, padx=8, pady=8, sticky="ew")
        ctk.CTkButton(outf, text="浏览", width=60, command=self._pick_out).grid(row=0, column=2, padx=8)

        ctk.CTkLabel(outf, text="PDF并发").grid(row=1, column=0, padx=12, pady=8, sticky="w")
        cf = ctk.CTkFrame(outf, fg_color="transparent")
        cf.grid(row=1, column=1, padx=8, pady=4, sticky="w")
        self.e_cpdf = ctk.CTkEntry(cf, width=60)
        self.e_cpdf.insert(0, str(self.cfg.concurrent_pdf))
        self.e_cpdf.pack(side="left")
        ctk.CTkLabel(cf, text="   翻译并发").pack(side="left")
        self.e_ctr = ctk.CTkEntry(cf, width=60)
        self.e_ctr.insert(0, str(self.cfg.concurrent_translate))
        self.e_ctr.pack(side="left", padx=(8, 0))

        # --- 操作 + 进度 + 日志 ---
        actf = ctk.CTkFrame(self, fg_color="transparent")
        actf.grid(row=4, column=0, padx=20, pady=(4, 0), sticky="nsew")
        actf.grid_columnconfigure(0, weight=1)
        actf.grid_rowconfigure(2, weight=1)

        bar = ctk.CTkFrame(actf, fg_color="transparent")
        bar.grid(row=0, column=0, sticky="ew", pady=4)
        bar.grid_columnconfigure(3, weight=1)
        self.btn_start = ctk.CTkButton(bar, text="▶ 开始翻译", width=120, command=self._start)
        self.btn_start.grid(row=0, column=0, padx=4)
        self.btn_cancel = ctk.CTkButton(bar, text="取消", width=70, fg_color="gray",
                                        state="disabled", command=self._cancel_run)
        self.btn_cancel.grid(row=0, column=1, padx=4)
        self.btn_open = ctk.CTkButton(bar, text="打开输出目录", width=110, command=self._open_out)
        self.btn_open.grid(row=0, column=2, padx=4)
        self.lbl_status = ctk.CTkLabel(bar, text="就绪", text_color="gray")
        self.lbl_status.grid(row=0, column=3, padx=12, sticky="e")

        self.progress = ctk.CTkProgressBar(actf)
        self.progress.set(0)
        self.progress.grid(row=1, column=0, sticky="ew", pady=6)

        self.log = ctk.CTkTextbox(actf, font=ctk.CTkFont(family="Consolas", size=12))
        self.log.grid(row=2, column=0, sticky="nsew", pady=(4, 12))
        self.log.configure(state="disabled")

    # ---------------- helpers ----------------
    def _fill_config(self):
        self.e_ds.insert(0, self.cfg.deepseek_key)
        self.e_pd.insert(0, self.cfg.paddle_token)
        self.e_model.insert(0, self.cfg.deepseek_model)

    def _toggle_show(self):
        ch = "" if self.show_var.get() == "on" else "•"
        self.e_ds.configure(show=ch)
        self.e_pd.configure(show=ch)

    def _read_config(self):
        self.cfg.deepseek_key = self.e_ds.get().strip()
        self.cfg.paddle_token = self.e_pd.get().strip()
        self.cfg.deepseek_model = self.e_model.get().strip() or "deepseek-chat"
        try:
            self.cfg.concurrent_pdf = max(1, int(self.e_cpdf.get()))
            self.cfg.concurrent_translate = max(1, int(self.e_ctr.get()))
        except ValueError:
            pass
        return self.cfg

    def _save_config(self):
        path = self._read_config().save()
        self._status(f"密钥已保存 → {path}")

    def _add_files(self):
        files = filedialog.askopenfilenames(title="选择 PDF", filetypes=[("PDF", "*.pdf")])
        self._add(files)

    def _add_folder(self):
        d = filedialog.askdirectory(title="选择含 PDF 的文件夹")
        if d:
            self._add([os.path.join(d, f) for f in sorted(os.listdir(d))
                       if f.lower().endswith(".pdf") and not f.endswith("-dual.pdf")])

    def _add(self, files):
        for f in files:
            if f and f not in self.pdf_files:
                self.pdf_files.append(f)
        self._refresh_files()

    def _clear_files(self):
        self.pdf_files = []
        self._refresh_files()

    def _refresh_files(self):
        n = len(self.pdf_files)
        if n == 0:
            self.lbl_files.configure(text="未选择 PDF")
        else:
            names = ", ".join(os.path.basename(p) for p in self.pdf_files[:3])
            more = f" 等 {n} 个" if n > 3 else ""
            self.lbl_files.configure(text=f"已选 {n} 个：{names}{more}")

    def _pick_out(self):
        d = filedialog.askdirectory(title="选择输出目录")
        if d:
            self.e_out.delete(0, "end")
            self.e_out.insert(0, d)

    def _open_out(self):
        d = self.e_out.get().strip()
        if d and os.path.isdir(d):
            if sys.platform == "win32":
                os.startfile(d)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", d])
            else:
                subprocess.Popen(["xdg-open", d])

    # ---------------- run ----------------
    def _start(self):
        if self.worker and self.worker.is_alive():
            return
        cfg = self._read_config()
        missing = cfg.validate()
        if missing:
            self._status("✗ 缺少：" + "、".join(missing), err=True)
            return
        if not self.pdf_files:
            self._status("✗ 请先选择 PDF", err=True)
            return
        cfg.save()  # 顺手持久化密钥
        out_dir = self.e_out.get().strip() or "output"
        self._cancel = False
        self.btn_start.configure(state="disabled")
        self.btn_cancel.configure(state="normal")
        self.progress.set(0)
        self._clear_log()

        pdfs = list(self.pdf_files)
        self.worker = threading.Thread(
            target=self._run, args=(pdfs, cfg, out_dir), daemon=True)
        self.worker.start()

    def _run(self, pdfs, cfg, out_dir):
        def log(msg):
            self.msg_q.put(("log", str(msg)))

        def prog(done, total):
            self.msg_q.put(("prog", (done, total)))

        try:
            produced, elapsed = translate_pdfs(
                pdfs, cfg, out_dir, log=log, progress=prog,
                cancel=lambda: self._cancel)
            self.msg_q.put(("done", (len(produced), len(pdfs), elapsed, out_dir)))
        except Exception as e:
            self.msg_q.put(("error", str(e)))

    def _cancel_run(self):
        self._cancel = True
        self._status("正在取消...（等当前任务收尾）")

    # ---------------- queue pump ----------------
    def _drain_queue(self):
        try:
            while True:
                kind, payload = self.msg_q.get_nowait()
                if kind == "log":
                    self._append_log(payload)
                elif kind == "prog":
                    done, total = payload
                    self.progress.set(done / total if total else 0)
                    self._status(f"进度 {done}/{total}")
                elif kind == "done":
                    ok, tot, sec, out_dir = payload
                    self.progress.set(1)
                    self._status(f"✓ 完成 {ok}/{tot}，耗时 {sec:.0f}秒")
                    self._append_log(f"\n✓ 全部完成：{ok}/{tot} 篇，耗时 {sec:.0f} 秒\n输出目录：{out_dir}")
                    self._finish()
                elif kind == "error":
                    self._status("✗ 出错", err=True)
                    self._append_log(f"\n✗ 错误：{payload}")
                    self._finish()
        except queue.Empty:
            pass
        self.after(120, self._drain_queue)

    def _finish(self):
        self.btn_start.configure(state="normal")
        self.btn_cancel.configure(state="disabled")

    # ---------------- small ui ops ----------------
    def _status(self, text, err=False):
        self.lbl_status.configure(text=text, text_color="#d33" if err else "gray")

    def _clear_log(self):
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")

    def _append_log(self, text):
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")


def main():
    App().mainloop()


if __name__ == "__main__":
    main()
