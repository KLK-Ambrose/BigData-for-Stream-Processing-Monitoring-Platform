import collections
import datetime
import queue
import threading
import time
import tkinter as tk
from tkinter import filedialog

import customtkinter as ctk
import happybase
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from pyhive import hive

# =========================
# 全局配置
# =========================
plt.rcParams["font.sans-serif"] = ["Microsoft YaHei"]
plt.rcParams["axes.unicode_minus"] = False

VM_IP = "192.168.116.128"

ctk.set_appearance_mode("light")
ctk.set_default_color_theme("blue")

# 浅色工业监控风格配色
COLOR_BG = "#eef4f8"
COLOR_CARD = "#f9fcff"
COLOR_PANEL = "#edf3f8"
COLOR_PANEL_2 = "#e3edf5"
COLOR_TEXT = "#183247"
COLOR_MUTED = "#5f7a90"
COLOR_GRID = "#bfd0dd"
COLOR_BORDER = "#c9d8e4"

COLOR_SUCCESS = "#1fa971"
COLOR_WARNING = "#f0a43a"
COLOR_DANGER = "#e35d6a"
COLOR_ACCENT = "#2f8fdd"
COLOR_LOG_BG = "#f4f8fb"


class SensorDashboard(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("水泵流处理监控平台 · 工业监控大屏")
        self.geometry("1520x940")
        self.minsize(1320, 820)
        self.configure(fg_color=COLOR_BG)

        # 运行状态
        self.stop_event = threading.Event()
        self.ui_queue = queue.Queue()
        self.blink_state = False
        self.alarm_mute_until = 0
        self.last_hbase_row = None
        self.last_pred_status = 0.0
        self.last_sample_key = "-"
        self.last_macro = (0, 0)

        # 状态跟踪
        self.source_online = {"hive": None, "hbase": None}
        self.reconnect_count = {"hive": 0, "hbase": 0}

        # 业务指标
        self.session_alert_count = 0
        self.recent_alert_times = collections.deque()
        self.log_records = []

        # 阈值
        self.THRESHOLD_VIB = 650.0
        self.THRESHOLD_TEMP = 45.0

        # 波形缓存
        self.wave_s04 = collections.deque([640.0] * 80, maxlen=80)
        self.wave_s10 = collections.deque([40.0] * 80, maxlen=80)
        self.x_data = list(range(80))

        self._build_ui()
        self._init_plot()

        self.protocol("WM_DELETE_WINDOW", self.on_closing)
        self.after(100, self.process_ui_queue)
        self.after(500, self._pulse_status_badges)
        self.after(1000, self._tick_clock)

        self._start_worker(self.fetch_hive_macro, "hive-worker")
        self._start_worker(self.fetch_hbase_micro, "hbase-worker")

        self.append_log("INFO", "工业监控大屏已启动，正在接入 Hive / HBase 数据源 ...")

    # =========================
    # UI 构建
    # =========================
    def _panel(self, parent, **kwargs):
        defaults = {
            "fg_color": COLOR_CARD,
            "corner_radius": 18,
            "border_width": 1,
            "border_color": COLOR_BORDER,
        }
        defaults.update(kwargs)
        return ctk.CTkFrame(parent, **defaults)

    def _build_ui(self):
        # ===== 顶部头部 =====
        self.frame_header = self._panel(self)
        self.frame_header.pack(fill="x", padx=18, pady=(16, 10))

        top_row = ctk.CTkFrame(self.frame_header, fg_color="transparent")
        top_row.pack(fill="x", padx=16, pady=(14, 8))

        self.lbl_title = ctk.CTkLabel(
            top_row,
            text="🏭 水泵流处理工业监控大屏",
            font=("Microsoft YaHei UI", 30, "bold"),
            text_color=COLOR_TEXT,
        )
        self.lbl_title.pack(side="left")

        self.lbl_clock = ctk.CTkLabel(
            top_row,
            text="----/--/-- --:--:--",
            font=("Consolas", 20, "bold"),
            text_color=COLOR_ACCENT,
        )
        self.lbl_clock.pack(side="right")

        self.lbl_subtitle = ctk.CTkLabel(
            self.frame_header,
            text="实时异常监测 · Hive 宏观统计 · HBase 波形采集 · 线程安全 UI 调度",
            font=("Microsoft YaHei UI", 12),
            text_color=COLOR_MUTED,
        )
        self.lbl_subtitle.pack(anchor="w", padx=18, pady=(0, 10))

        # ===== 状态 / 控制区 =====
        control_row = ctk.CTkFrame(self.frame_header, fg_color="transparent")
        control_row.pack(fill="x", padx=16, pady=(0, 10))

        left_status = ctk.CTkFrame(control_row, fg_color="transparent")
        left_status.pack(side="left")

        self.lbl_hive_status = self._create_badge(
            left_status, "HIVE · 初始化中", COLOR_PANEL
        )
        self.lbl_hive_status.pack(side="left", padx=(0, 8))

        self.lbl_hbase_status = self._create_badge(
            left_status, "HBASE · 初始化中", COLOR_PANEL
        )
        self.lbl_hbase_status.pack(side="left", padx=(0, 8))

        self.lbl_device_state = self._create_badge(
            left_status, "设备状态 · 待机", COLOR_PANEL_2
        )
        self.lbl_device_state.pack(side="left", padx=(0, 8))

        self.lbl_mute_state = self._create_badge(
            left_status, "告警静默 · 关闭", COLOR_PANEL_2
        )
        self.lbl_mute_state.pack(side="left")

        right_controls = ctk.CTkFrame(control_row, fg_color="transparent")
        right_controls.pack(side="right")

        self.btn_mute = ctk.CTkButton(
            right_controls,
            text="静默 5 分钟",
            width=120,
            fg_color="#5fa8d3",
            hover_color="#4c97c3",
            text_color="white",
            command=self.toggle_mute_window,
        )
        self.btn_mute.pack(side="left", padx=6)

        self.btn_export = ctk.CTkButton(
            right_controls,
            text="导出日志",
            width=100,
            fg_color="#7b9cb8",
            hover_color="#688ca8",
            text_color="white",
            command=self.export_logs,
        )
        self.btn_export.pack(side="left", padx=6)

        self.btn_clear = ctk.CTkButton(
            right_controls,
            text="清空日志",
            width=100,
            fg_color="#b4878f",
            hover_color="#a3747d",
            text_color="white",
            command=self.clear_logs,
        )

        self.btn_clear.pack(side="left", padx=6)

        self.lbl_runtime_note = ctk.CTkLabel(
            self.frame_header,
            text="状态：等待首批数据 ...",
            font=("Microsoft YaHei UI", 12),
            text_color=COLOR_MUTED,
        )
        self.lbl_runtime_note.pack(anchor="w", padx=18, pady=(0, 8))

        # ===== KPI 指标 =====
        self.frame_kpis = ctk.CTkFrame(self.frame_header, fg_color="transparent")
        self.frame_kpis.pack(fill="x", padx=16, pady=(0, 10))

        for i in range(5):
            self.frame_kpis.grid_columnconfigure(i, weight=1)

        self.kpi_normal = self._create_kpi_card(
            self.frame_kpis, "历史正常", "0", COLOR_SUCCESS
        )
        self.kpi_anomaly = self._create_kpi_card(
            self.frame_kpis, "历史异常", "0", COLOR_DANGER
        )
        self.kpi_session = self._create_kpi_card(
            self.frame_kpis, "会话告警", "0", COLOR_WARNING
        )
        self.kpi_recent = self._create_kpi_card(
            self.frame_kpis, "近5分钟异常", "0", COLOR_ACCENT
        )
        self.kpi_reconnect = self._create_kpi_card(
            self.frame_kpis, "自动重连", "0", COLOR_TEXT
        )

        for idx, card in enumerate(
            [
                self.kpi_normal,
                self.kpi_anomaly,
                self.kpi_session,
                self.kpi_recent,
                self.kpi_reconnect,
            ]
        ):
            card["frame"].grid(row=0, column=idx, padx=6, sticky="nsew")

        # ===== Hive 比例条 =====
        self.canvas_hive = tk.Canvas(
            self.frame_header,
            height=48,
            bg=COLOR_CARD,
            highlightthickness=0,
            bd=0,
            relief="flat",
        )
        self.canvas_hive.pack(fill="x", padx=18, pady=(0, 14))
        self.canvas_hive.bind("<Configure>", self._on_hive_canvas_resize)

        # ===== 主区域 =====
        self.frame_main = ctk.CTkFrame(self, fg_color="transparent")
        self.frame_main.pack(fill="both", expand=True, padx=18, pady=(0, 16))

        self.frame_left = self._panel(self.frame_main)
        self.frame_left.pack(side="left", fill="both", expand=True, padx=(0, 10))

        self.frame_right = self._panel(self.frame_main, width=390)
        self.frame_right.pack(side="right", fill="y")
        self.frame_right.pack_propagate(False)

        self.lbl_wave_title = ctk.CTkLabel(
            self.frame_left,
            text="📈 实时波形监控",
            font=("Microsoft YaHei UI", 20, "bold"),
            text_color=COLOR_TEXT,
        )
        self.lbl_wave_title.pack(pady=(14, 4))

        self.lbl_last_sample = ctk.CTkLabel(
            self.frame_left,
            text="最近采样：等待数据",
            font=("Consolas", 12),
            text_color=COLOR_MUTED,
        )
        self.lbl_last_sample.pack(pady=(0, 6))

        self.lbl_log_title = ctk.CTkLabel(
            self.frame_right,
            text="📋 事件与诊断日志",
            font=("Microsoft YaHei UI", 20, "bold"),
            text_color=COLOR_TEXT,
        )
        self.lbl_log_title.pack(pady=(14, 10))

        self.log_box = ctk.CTkTextbox(
            self.frame_right,
            fg_color=COLOR_LOG_BG,
            border_width=1,
            border_color=COLOR_BORDER,
            corner_radius=16,
            font=("Consolas", 12),
            text_color=COLOR_TEXT,
        )
        self.log_box.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        self.log_box.insert("1.0", "系统日志已初始化 ...\n" + "=" * 58 + "\n")
        self.log_box.configure(state="disabled")

    def _create_badge(self, parent, text, color):
        return ctk.CTkLabel(
            parent,
            text=text,
            font=("Microsoft YaHei UI", 12, "bold"),
            text_color=COLOR_TEXT,
            fg_color=color,
            corner_radius=14,
        )

    def _create_kpi_card(self, parent, title, initial_value, accent):
        frame = self._panel(parent, fg_color=COLOR_PANEL)
        title_label = ctk.CTkLabel(
            frame,
            text=title,
            font=("Microsoft YaHei UI", 12),
            text_color=COLOR_MUTED,
        )
        title_label.pack(anchor="w", padx=14, pady=(10, 2))

        value_label = ctk.CTkLabel(
            frame,
            text=initial_value,
            font=("Consolas", 24, "bold"),
            text_color=accent,
        )
        value_label.pack(anchor="w", padx=14, pady=(0, 10))

        return {"frame": frame, "value": value_label}

    def _init_plot(self):
        self.fig, (self.ax1, self.ax2) = plt.subplots(
            2, 1, figsize=(9, 6), facecolor=COLOR_CARD
        )
        self.fig.subplots_adjust(
            left=0.07, right=0.97, top=0.95, bottom=0.08, hspace=0.34
        )

        for ax in (self.ax1, self.ax2):
            ax.set_facecolor(COLOR_PANEL)
            ax.grid(True, linestyle=":", color=COLOR_GRID, alpha=0.45)
            ax.tick_params(colors=COLOR_TEXT, labelsize=9)
            ax.set_xticks([])
            for spine in ax.spines.values():
                spine.set_color(COLOR_BORDER)

        self.ax1.set_xlim(0, 79)
        self.ax2.set_xlim(0, 79)
        self.ax1.set_ylim(625, 660)
        self.ax2.set_ylim(32, 55)

        self.ax1.set_title("Sensor 04 · 机器振动频率", color=COLOR_TEXT, fontsize=12)
        self.ax2.set_title("Sensor 10 · 设备表面温度", color=COLOR_TEXT, fontsize=12)

        self.ax1.axhline(
            self.THRESHOLD_VIB, color=COLOR_DANGER, linestyle="--", alpha=0.8
        )
        self.ax2.axhline(
            self.THRESHOLD_TEMP, color=COLOR_DANGER, linestyle="--", alpha=0.8
        )

        self.ax1.text(
            1,
            self.THRESHOLD_VIB + 0.8,
            f"危险阈值: {self.THRESHOLD_VIB}",
            color=COLOR_DANGER,
            fontsize=9,
        )
        self.ax2.text(
            1,
            self.THRESHOLD_TEMP + 0.4,
            f"危险阈值: {self.THRESHOLD_TEMP}",
            color=COLOR_DANGER,
            fontsize=9,
        )

        (self.line_s04,) = self.ax1.plot(
            self.x_data, list(self.wave_s04), color=COLOR_SUCCESS, linewidth=2.4
        )
        (self.line_s10,) = self.ax2.plot(
            self.x_data, list(self.wave_s10), color=COLOR_WARNING, linewidth=2.4
        )

        self.canvas = FigureCanvasTkAgg(self.fig, master=self.frame_left)
        self.canvas.get_tk_widget().configure(bg=COLOR_CARD, highlightthickness=0)
        self.canvas.get_tk_widget().pack(
            fill="both", expand=True, padx=12, pady=(4, 12)
        )
        self.canvas.draw_idle()

    # =========================
    # 线程与调度
    # =========================
    def _start_worker(self, target, name):
        thread = threading.Thread(target=target, name=name, daemon=True)
        thread.start()

    def on_closing(self):
        self.stop_event.set()
        self.destroy()

    def process_ui_queue(self):
        redraw_required = False
        processed = 0

        while processed < 200:
            try:
                event_type, payload = self.ui_queue.get_nowait()
            except queue.Empty:
                break

            processed += 1

            if event_type == "log":
                self.append_log(payload["level"], payload["message"])

            elif event_type == "macro":
                self.handle_macro_update(payload["normal"], payload["anomaly"])

            elif event_type == "status":
                self.update_source_status(
                    payload["source"], payload["online"], payload["detail"]
                )

            elif event_type == "micro":
                self.handle_micro_update(payload)
                redraw_required = True

        if redraw_required:
            self.update_plot(self.last_pred_status)

        if not self.stop_event.is_set() and self.winfo_exists():
            self.after(100, self.process_ui_queue)

    # =========================
    # UI 逻辑
    # =========================
    def handle_macro_update(self, normal_val, anomaly_val):
        self.last_macro = (normal_val, anomaly_val)
        self.kpi_normal["value"].configure(text=str(normal_val))
        self.kpi_anomaly["value"].configure(text=str(anomaly_val))
        self.update_hive_bar(normal_val, anomaly_val)

    def handle_micro_update(self, payload):
        s04 = payload["s04"]
        s10 = payload["s10"]
        pred = payload["pred"]
        key_text = payload["key"]

        self.wave_s04.append(s04)
        self.wave_s10.append(s10)
        self.last_pred_status = pred
        self.last_sample_key = key_text

        self.lbl_last_sample.configure(
            text=f"最近采样 | key={key_text} | S04={s04:.1f} | S10={s10:.1f} | PRED={'ALERT' if pred == 1.0 else 'NORMAL'}"
        )

        if pred == 1.0:
            self.session_alert_count += 1
            self.recent_alert_times.append(time.time())
            self.kpi_session["value"].configure(text=str(self.session_alert_count))

        self._prune_recent_alerts()
        self._update_device_state(pred, s04, s10)

    def _prune_recent_alerts(self):
        now_ts = time.time()
        while self.recent_alert_times and now_ts - self.recent_alert_times[0] > 300:
            self.recent_alert_times.popleft()
        self.kpi_recent["value"].configure(text=str(len(self.recent_alert_times)))

    def _update_device_state(self, pred, s04, s10):
        if self.source_online["hbase"] is False:
            self.lbl_device_state.configure(
                text="设备状态 · 数据中断",
                fg_color=COLOR_WARNING,
                text_color="#101820",
            )
            return

        if pred == 1.0:
            text = f"设备状态 · 异常 (V={s04:.1f} / T={s10:.1f})"
            self.lbl_device_state.configure(
                text=text,
                fg_color=COLOR_DANGER,
                text_color=COLOR_TEXT,
            )
        else:
            self.lbl_device_state.configure(
                text="设备状态 · 运行正常",
                fg_color=COLOR_SUCCESS,
                text_color="#071018",
            )

    def update_plot(self, pred_status):
        self.line_s04.set_ydata(list(self.wave_s04))
        self.line_s10.set_ydata(list(self.wave_s10))
        self.line_s04.set_color(COLOR_DANGER if pred_status == 1.0 else COLOR_SUCCESS)
        self.canvas.draw_idle()

    def update_hive_bar(self, normal_val, anomaly_val):
        width = max(self.canvas_hive.winfo_width(), 320)
        height = max(self.canvas_hive.winfo_height(), 48)

        self.canvas_hive.delete("all")
        pad = 4
        x0, y0 = pad, pad
        x1, y1 = width - pad, height - pad

        self.canvas_hive.create_rectangle(
            x0, y0, x1, y1, fill=COLOR_PANEL_2, outline=COLOR_BORDER, width=1
        )

        total = normal_val + anomaly_val
        if total > 0:
            split_x = x0 + (x1 - x0) * (normal_val / total)
            self.canvas_hive.create_rectangle(
                x0, y0, split_x, y1, fill=COLOR_SUCCESS, outline=""
            )
            self.canvas_hive.create_rectangle(
                split_x, y0, x1, y1, fill=COLOR_DANGER, outline=""
            )

        self.canvas_hive.create_text(
            x0 + 14,
            height / 2,
            text=f"正常: {normal_val}",
            fill=COLOR_TEXT,
            anchor="w",
            font=("Microsoft YaHei UI", 11, "bold"),
        )
        self.canvas_hive.create_text(
            x1 - 14,
            height / 2,
            text=f"异常: {anomaly_val}",
            fill=COLOR_TEXT,
            anchor="e",
            font=("Microsoft YaHei UI", 11, "bold"),
        )

    def _on_hive_canvas_resize(self, _event):
        self.update_hive_bar(*self.last_macro)

    def update_source_status(self, source, online, detail):
        previous = self.source_online[source]
        self.source_online[source] = online

        if previous is False and online is True:
            self.reconnect_count[source] += 1

        total_reconnect = self.reconnect_count["hive"] + self.reconnect_count["hbase"]
        self.kpi_reconnect["value"].configure(text=str(total_reconnect))

        if source == "hive":
            self.lbl_hive_status.configure(
                text=f"HIVE · {'在线' if online else '离线'}"
            )
        else:
            self.lbl_hbase_status.configure(
                text=f"HBASE · {'在线' if online else '离线'}"
            )

        self.lbl_runtime_note.configure(
            text=f"状态：{detail}",
            text_color=COLOR_MUTED if online else COLOR_WARNING,
        )

    def _pulse_status_badges(self):
        self.blink_state = not self.blink_state

        self._apply_badge_color(self.lbl_hive_status, self.source_online["hive"])
        self._apply_badge_color(self.lbl_hbase_status, self.source_online["hbase"])

        if not self.stop_event.is_set() and self.winfo_exists():
            self.after(500, self._pulse_status_badges)

    def _apply_badge_color(self, label, online_state):
        if online_state is True:
            label.configure(fg_color=COLOR_SUCCESS, text_color="#061018")
        elif online_state is False:
            label.configure(
                fg_color=COLOR_DANGER if self.blink_state else COLOR_PANEL,
                text_color=COLOR_TEXT,
            )
        else:
            label.configure(fg_color=COLOR_PANEL, text_color=COLOR_TEXT)

    def _tick_clock(self):
        now = datetime.datetime.now()
        self.lbl_clock.configure(text=now.strftime("%Y-%m-%d %H:%M:%S"))

        if self.alarm_mute_until > time.time():
            remain = int(self.alarm_mute_until - time.time())
            minutes = remain // 60
            seconds = remain % 60
            self.lbl_mute_state.configure(
                text=f"告警静默 · {minutes:02d}:{seconds:02d}",
                fg_color=COLOR_WARNING,
                text_color="#081018",
            )
            self.btn_mute.configure(
                text="取消静默", fg_color="#8f6b2e", hover_color="#a37c35"
            )
        else:
            self.lbl_mute_state.configure(
                text="告警静默 · 关闭",
                fg_color=COLOR_PANEL_2,
                text_color=COLOR_TEXT,
            )
            self.btn_mute.configure(
                text="静默 5 分钟", fg_color="#245d7a", hover_color="#2c769a"
            )

        self._prune_recent_alerts()

        if not self.stop_event.is_set() and self.winfo_exists():
            self.after(1000, self._tick_clock)

    def toggle_mute_window(self):
        if self.alarm_mute_until > time.time():
            self.alarm_mute_until = 0
            self.append_log("INFO", "告警静默已取消，恢复完整告警显示。")
        else:
            self.alarm_mute_until = time.time() + 300
            self.append_log("INFO", "已开启 5 分钟告警静默窗口。")

    def append_log(self, level, message):
        now_str = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
        level = level.upper()

        if level == "ERROR":
            prefix = "🔴"
        elif level == "WARN":
            prefix = "🟠"
        else:
            prefix = "🟢"

        if self.alarm_mute_until > time.time() and level == "ERROR":
            line = f"[{now_str}] {prefix} [静默期仍记录] {message}\n"
        else:
            line = f"[{now_str}] {prefix} {message}\n"

        self.log_records.append(line)

        self.log_box.configure(state="normal")
        self.log_box.insert("end", line)
        self.log_box.see("end")

        total_lines = int(float(self.log_box.index("end-1c").split(".")[0]))
        if total_lines > 260:
            self.log_box.delete("1.0", f"{total_lines - 220}.0")

        self.log_box.configure(state="disabled")

    def clear_logs(self):
        self.log_records.clear()
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.insert("1.0", "日志已清空。\n" + "=" * 58 + "\n")
        self.log_box.configure(state="disabled")
        self.append_log("INFO", "操作员已清空界面日志。")

    def export_logs(self):
        default_name = f"sensor_dashboard_log_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        save_path = filedialog.asksaveasfilename(
            title="导出监控日志",
            defaultextension=".txt",
            initialfile=default_name,
            filetypes=[("Text Files", "*.txt"), ("All Files", "*.*")],
        )

        if not save_path:
            return

        try:
            with open(save_path, "w", encoding="utf-8") as f:
                f.write("水泵流处理工业监控日志\n")
                f.write("=" * 64 + "\n")
                for item in self.log_records:
                    f.write(item)
            self.append_log("INFO", f"日志导出成功：{save_path}")
        except Exception as exc:
            self.append_log("ERROR", f"日志导出失败：{exc}")

    # =========================
    # 数据线程
    # =========================
    def fetch_hive_macro(self):
        while not self.stop_event.is_set():
            conn = None
            cursor = None
            try:
                conn = hive.Connection(
                    host=VM_IP,
                    port=10000,
                    username="root",
                    database="sensor_db",
                )
                cursor = conn.cursor()
                cursor.execute("SELECT pred, COUNT(*) FROM hive_hbase_sensor GROUP BY pred")
                results = cursor.fetchall()

                normal_cnt = sum(r[1] for r in results if float(r[0]) == 0.0)
                anomaly_cnt = sum(r[1] for r in results if float(r[0]) != 0.0)

                self.ui_queue.put(
                    ("macro", {"normal": normal_cnt, "anomaly": anomaly_cnt})
                )
                self.ui_queue.put(
                    (
                        "status",
                        {
                            "source": "hive",
                            "online": True,
                            "detail": "Hive 宏观统计同步成功",
                        },
                    )
                )

            except Exception as exc:
                self.ui_queue.put(
                    (
                        "status",
                        {
                            "source": "hive",
                            "online": False,
                            "detail": f"Hive 同步失败: {exc}",
                        },
                    )
                )
                self.ui_queue.put(
                    ("log", {"level": "WARN", "message": f"Hive 同步失败: {exc}"})
                )

            finally:
                self._safe_close(cursor)
                self._safe_close(conn)

            if self.stop_event.wait(30):
                break

    def fetch_hbase_micro(self):
        while not self.stop_event.is_set():
            conn = None
            try:
                conn = happybase.Connection(VM_IP, port=9090)
                table = conn.table("sensor_wave")

                self.ui_queue.put(
                    (
                        "status",
                        {
                            "source": "hbase",
                            "online": True,
                            "detail": "HBase 实时采样通道已连接",
                        },
                    )
                )

                while not self.stop_event.is_set():
                    # 💡 核心修改 1：倒序极速扫描，每次只拿表里最新的一条数据！
                    scan_kwargs = {"limit": 1, "reverse": True}
                    
                    rows = list(table.scan(**scan_kwargs))

                    if not rows:
                        if self.stop_event.wait(0.1):
                            return
                        continue
                        
                    # 💡 核心修改 2：防重复死锁机制。如果拿到的还是上一秒的老数据，就跳过并休眠 0.1 秒
                    if rows[0][0] == self.last_hbase_row:
                        if self.stop_event.wait(0.1):
                            return
                        continue

                    for key, data in rows:
                        if self.stop_event.is_set():
                            return

                        key_text = self._decode_key(key)

                        try:
                            s04_raw = data.get(b"wave:s04")
                            s10_raw = data.get(b"wave:s10")
                            pred_raw = data.get(b"status:pred")

                            if s04_raw is None or s10_raw is None or pred_raw is None:
                                raise KeyError(
                                    "缺少必要列 wave:s04 / wave:s10 / status:pred"
                                )

                            s04 = float(s04_raw.decode("utf-8"))
                            s10 = float(s10_raw.decode("utf-8"))
                            pred = float(pred_raw.decode("utf-8"))

                            self.last_hbase_row = key

                            self.ui_queue.put(
                                (
                                    "micro",
                                    {
                                        "s04": s04,
                                        "s10": s10,
                                        "pred": pred,
                                        "key": key_text,
                                    },
                                )
                            )

                            if pred == 1.0:
                                anomaly_parts = []
                                if s04 > self.THRESHOLD_VIB:
                                    anomaly_parts.append("振动超标")
                                if s10 > self.THRESHOLD_TEMP:
                                    anomaly_parts.append("温度过高")
                                reason = (
                                    " + ".join(anomaly_parts)
                                    if anomaly_parts
                                    else "未知突变"
                                )

                                self.ui_queue.put(
                                    (
                                        "log",
                                        {
                                            "level": "ERROR",
                                            "message": f"设备告警：{reason} | key={key_text} | S04={s04:.1f} | S10={s10:.1f}",
                                        },
                                    )
                                )

                        except Exception as row_exc:
                            self.last_hbase_row = key
                            self.ui_queue.put(
                                (
                                    "log",
                                    {
                                        "level": "WARN",
                                        "message": f"HBase 行解析失败 [{key_text}]：{row_exc}",
                                    },
                                )
                            )

                        if self.stop_event.wait(0.08):
                            return

            except Exception as exc:
                self.ui_queue.put(
                    (
                        "status",
                        {
                            "source": "hbase",
                            "online": False,
                            "detail": f"HBase 连接/扫描失败: {exc}",
                        },
                    )
                )
                self.ui_queue.put(
                    ("log", {"level": "WARN", "message": f"HBase 连接/扫描失败: {exc}"})
                )
                if self.stop_event.wait(2):
                    break

            finally:
                self._safe_close(conn)

    # =========================
    # 工具方法
    # =========================
    def _safe_close(self, obj):
        if obj is None:
            return
        try:
            obj.close()
        except Exception:
            pass

    def _decode_key(self, key):
        if isinstance(key, bytes):
            return key.decode("utf-8", errors="ignore")
        return str(key)


if __name__ == "__main__":
    app = SensorDashboard()
    app.mainloop()
