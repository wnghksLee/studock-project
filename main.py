import customtkinter as ctk
import tkinter as tk
from tkinter import messagebox, simpledialog
import threading
import time
import json
import os
from datetime import date

# ── 테마 설정 ──────────────────────────────────────
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

DATA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "study_data.json")

SUBJECT_COLORS = [
    "#4F86C6", "#E07B54", "#57A773", "#C46E9E",
    "#E8B84B", "#7B68EE", "#20B2AA", "#FF7F7F"
]

# ── 데이터 저장/불러오기 ───────────────────────────────
def load_data():
    if not os.path.exists(DATA_FILE):
        return {"subjects": {}}
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def fmt_time(seconds):
    h = int(seconds) // 3600
    m = (int(seconds) % 3600) // 60
    s = int(seconds) % 60
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"

def fmt_hours(seconds):
    h = seconds / 3600
    return f"{h:.1f}h"

# ── 과목 추가 팝업창 ─────────────────────────
class AddSubjectDialog(ctk.CTkToplevel):
    def __init__(self, parent, existing_names):
        super().__init__(parent)
        self.title("과목 추가")
        self.geometry("360x280")
        self.resizable(False, False)
        self.grab_set()
        self.result = None
        self.existing_names = existing_names

        ctk.CTkLabel(self, text="📚 새 과목 추가", font=ctk.CTkFont(size=18, weight="bold")).pack(pady=(24, 4))

        ctk.CTkLabel(self, text="과목명", font=ctk.CTkFont(size=13)).pack(anchor="w", padx=32)
        self.name_entry = ctk.CTkEntry(self, placeholder_text="예: 수학, 영어, 물리학", width=296)
        self.name_entry.pack(padx=32, pady=(4, 12))

        ctk.CTkLabel(self, text="목표 시간 (분)", font=ctk.CTkFont(size=13)).pack(anchor="w", padx=32)
        self.time_entry = ctk.CTkEntry(self, placeholder_text="예: 60 (분 단위)", width=296)
        self.time_entry.pack(padx=32, pady=(4, 20))

        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(fill="x", padx=32)
        ctk.CTkButton(btn_frame, text="취소", fg_color="gray30", hover_color="gray40",
                      width=130, command=self.destroy).pack(side="left")
        ctk.CTkButton(btn_frame, text="추가", width=130, command=self._submit).pack(side="right")

        self.name_entry.focus()
        self.bind("<Return>", lambda e: self._submit())

    def _submit(self):
        name = self.name_entry.get().strip()
        raw = self.time_entry.get().strip()
        if not name:
            messagebox.showerror("오류", "과목명을 입력해주세요.", parent=self); return
        if name in self.existing_names:
            messagebox.showerror("오류", f"'{name}' 과목이 이미 존재합니다.", parent=self); return
        try:
            minutes = int(raw)
            if minutes <= 0: raise ValueError
        except ValueError:
            messagebox.showerror("오류", "목표 시간을 올바른 양수 숫자(분)로 입력해주세요.", parent=self); return
        self.result = {"name": name, "goal_seconds": minutes * 60}
        self.destroy()

# ── 과목 카드 위젯 ───────────────────────────────────
class SubjectCard(ctk.CTkFrame):
    def __init__(self, parent, name, data, color, on_delete, on_update_goal, tick_callback):
        super().__init__(parent, corner_radius=14, border_width=2, border_color=color)
        self.name = name
        self.data = data
        self.color = color
        self.on_delete = on_delete
        self.on_update_goal = on_update_goal
        self.tick_callback = tick_callback

        self._running = False
        self._start_time = None
        self._elapsed = data.get("elapsed_seconds", 0)
        self._thread = None

        self._build()
        self._refresh_ui()

    def _build(self):
        # 상단 헤더 (과목명 + 삭제 버튼)
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=14, pady=(12, 4))

        dot = ctk.CTkLabel(header, text="●", text_color=self.color,
                           font=ctk.CTkFont(size=14))
        dot.pack(side="left", padx=(0, 6))

        self.name_label = ctk.CTkLabel(header, text=self.name,
                                       font=ctk.CTkFont(size=15, weight="bold"))
        self.name_label.pack(side="left")

        ctk.CTkButton(header, text="✕", width=28, height=28, fg_color="gray25",
                      hover_color="#c0392b", corner_radius=8,
                      font=ctk.CTkFont(size=11),
                      command=self._delete).pack(side="right")

        # 타이머 숫자 표시
        self.timer_label = ctk.CTkLabel(self, text="00:00",
                                        font=ctk.CTkFont(size=32, weight="bold"),
                                        text_color=self.color)
        self.timer_label.pack(pady=(6, 2))

        # 목표 달성률 진행 바
        self.progress_bar = ctk.CTkProgressBar(self, width=220, corner_radius=6,
                                                progress_color=self.color)
        self.progress_bar.pack(pady=(2, 4))
        self.progress_bar.set(0)

        # 경과시간 / 목표시간 텍스트
        goal_row = ctk.CTkFrame(self, fg_color="transparent")
        goal_row.pack(pady=(0, 8))
        self.goal_label = ctk.CTkLabel(goal_row, text="", font=ctk.CTkFont(size=11),
                                       text_color="gray70")
        self.goal_label.pack(side="left", padx=(0, 8))
        ctk.CTkButton(goal_row, text="✏️", width=28, height=24, fg_color="gray25",
                      hover_color="gray35", corner_radius=6,
                      font=ctk.CTkFont(size=11),
                      command=self._edit_goal).pack(side="left")

        # 시작/초기화 버튼
        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.pack(pady=(0, 14))

        self.start_btn = ctk.CTkButton(btn_row, text="▶  시작", width=100,
                                       fg_color=self.color, hover_color=self.color,
                                       corner_radius=10, command=self._toggle)
        self.start_btn.pack(side="left", padx=4)

        ctk.CTkButton(btn_row, text="↺  초기화", width=90, fg_color="gray30",
                      hover_color="gray40", corner_radius=10,
                      command=self._reset).pack(side="left", padx=4)

    def _refresh_ui(self):
        self.timer_label.configure(text=fmt_time(self._elapsed))
        goal = self.data.get("goal_seconds", 3600)
        ratio = min(self._elapsed / goal, 1.0) if goal > 0 else 0
        self.progress_bar.set(ratio)
        pct = int(ratio * 100)
        elapsed_str = fmt_time(self._elapsed)
        goal_str = fmt_time(goal)
        self.goal_label.configure(text=f"{elapsed_str} / {goal_str}  ({pct}%)")

    def _toggle(self):
        if self._running:
            self._pause()
        else:
            self._start()

    def _start(self):
        self._running = True
        self._start_time = time.time()
        self.start_btn.configure(text="⏸  일시정지")
        self._thread = threading.Thread(target=self._tick_loop, daemon=True)
        self._thread.start()

    def _pause(self):
        self._running = False
        self.start_btn.configure(text="▶  시작")
        self.data["elapsed_seconds"] = self._elapsed
        self.tick_callback()

    def _reset(self):
        was_running = self._running
        self._running = False
        self._elapsed = 0
        self.data["elapsed_seconds"] = 0
        self.start_btn.configure(text="▶  시작")
        self._refresh_ui()
        self.tick_callback()

    def _tick_loop(self):
        base = self._elapsed
        t0 = time.time()
        while self._running:
            self._elapsed = base + (time.time() - t0)
            self.after(0, self._refresh_ui)
            time.sleep(0.5)

    def _delete(self):
        if self._running:
            self._running = False
        if messagebox.askyesno("삭제 확인", f"'{self.name}' 과목을 삭제할까요?"):
            self.on_delete(self.name)

    def _edit_goal(self):
        val = simpledialog.askinteger("목표 시간 수정",
                                      f"'{self.name}' 의 새 목표 시간 (분):",
                                      minvalue=1, maxvalue=9999)
        if val:
            self.data["goal_seconds"] = val * 60
            self._refresh_ui()
            self.on_update_goal()

    def stop(self):
        self._running = False
        self.data["elapsed_seconds"] = self._elapsed

# ── 메인 앱 ───────────────────────────────────
class StudyApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("📚 Studock")
        self.geometry("860x620")
        self.minsize(700, 500)

        self.data = load_data()
        self.cards = {}
        self._color_idx = 0

        self._build_ui()
        self._load_subjects()

        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self):
        # 왼쪽 사이드바
        self.sidebar = ctk.CTkFrame(self, width=220, corner_radius=0)
        self.sidebar.pack(side="left", fill="y", padx=0, pady=0)
        self.sidebar.pack_propagate(False)

        ctk.CTkLabel(self.sidebar, text="📚", font=ctk.CTkFont(size=36)).pack(pady=(28, 4))
        ctk.CTkLabel(self.sidebar, text="Studock",
                     font=ctk.CTkFont(size=17, weight="bold")).pack()
        ctk.CTkLabel(self.sidebar, text="오늘의 학습 관리",
                     font=ctk.CTkFont(size=11), text_color="gray60").pack(pady=(2, 24))

        ctk.CTkButton(self.sidebar, text="＋  과목 추가", height=40,
                      corner_radius=10, command=self._add_subject).pack(padx=20, pady=4)

        ctk.CTkButton(self.sidebar, text="⏹  전체 중지", height=36,
                      fg_color="gray30", hover_color="gray40",
                      corner_radius=10, command=self._stop_all).pack(padx=20, pady=4)

        # 학습 통계 박스
        ctk.CTkLabel(self.sidebar, text="오늘의 통계",
                     font=ctk.CTkFont(size=12, weight="bold"),
                     text_color="gray60").pack(anchor="w", padx=24, pady=(24, 6))

        self.stats_frame = ctk.CTkFrame(self.sidebar, fg_color="gray17", corner_radius=10)
        self.stats_frame.pack(fill="x", padx=16, pady=4)

        self.total_label = ctk.CTkLabel(self.stats_frame, text="총 학습: 00:00",
                                        font=ctk.CTkFont(size=12))
        self.total_label.pack(pady=(10, 2))
        self.subject_count_label = ctk.CTkLabel(self.stats_frame, text="과목 수: 0개",
                                                 font=ctk.CTkFont(size=12), text_color="gray70")
        self.subject_count_label.pack(pady=(2, 10))

        # 다크/라이트 모드 전환
        ctk.CTkLabel(self.sidebar, text="테마", font=ctk.CTkFont(size=11),
                     text_color="gray50").pack(anchor="w", padx=24, pady=(20, 2))
        self.theme_switch = ctk.CTkSwitch(self.sidebar, text="라이트 모드",
                                          command=self._toggle_theme)
        self.theme_switch.pack(anchor="w", padx=24)

        # 오른쪽 메인 영역
        self.main_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.main_frame.pack(side="right", fill="both", expand=True, padx=16, pady=16)

        top_bar = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        top_bar.pack(fill="x", pady=(0, 12))
        ctk.CTkLabel(top_bar, text="과목별 타이머",
                     font=ctk.CTkFont(size=20, weight="bold")).pack(side="left")

        # 카드들 들어갈 스크롤 영역
        self.scroll = ctk.CTkScrollableFrame(self.main_frame, fg_color="transparent")
        self.scroll.pack(fill="both", expand=True)

        # 과목이 하나도 없을 때 안내 문구
        self.empty_label = ctk.CTkLabel(
            self.scroll,
            text="아직 과목이 없어요 😊\n왼쪽 '＋ 과목 추가' 버튼을 눌러 시작하세요!",
            font=ctk.CTkFont(size=14), text_color="gray55"
        )

    def _load_subjects(self):
        for name, info in self.data["subjects"].items():
            color = info.get("color", SUBJECT_COLORS[self._color_idx % len(SUBJECT_COLORS)])
            self._color_idx += 1
            self._create_card(name, info, color)
        self._refresh_layout()

    def _create_card(self, name, info, color):
        card = SubjectCard(
            self.scroll, name, info, color,
            on_delete=self._delete_subject,
            on_update_goal=self._save,
            tick_callback=self._update_stats
        )
        self.cards[name] = card
        self._update_stats()

    def _refresh_layout(self):
        # 카드 전부 지우고 2열로 다시 배치
        for widget in self.scroll.winfo_children():
            widget.grid_forget()

        names = list(self.cards.keys())
        if not names:
            self.empty_label.pack(pady=80)
            return

        self.empty_label.pack_forget()
        self.scroll.columnconfigure(0, weight=1)
        self.scroll.columnconfigure(1, weight=1)

        for i, name in enumerate(names):
            row, col = divmod(i, 2)
            self.cards[name].grid(row=row, column=col, padx=8, pady=8, sticky="nsew")

    def _add_subject(self):
        dlg = AddSubjectDialog(self, list(self.data["subjects"].keys()))
        self.wait_window(dlg)
        if dlg.result:
            name = dlg.result["name"]
            color = SUBJECT_COLORS[self._color_idx % len(SUBJECT_COLORS)]
            self._color_idx += 1
            info = {
                "goal_seconds": dlg.result["goal_seconds"],
                "elapsed_seconds": 0,
                "color": color
            }
            self.data["subjects"][name] = info
            self._create_card(name, info, color)
            self._refresh_layout()
            self._save()

    def _delete_subject(self, name):
        card = self.cards.pop(name, None)
        if card:
            card.destroy()
        self.data["subjects"].pop(name, None)
        self._refresh_layout()
        self._save()

    def _stop_all(self):
        for card in self.cards.values():
            if card._running:
                card._pause()

    def _update_stats(self):
        total = sum(c._elapsed for c in self.cards.values())
        self.total_label.configure(text=f"총 학습: {fmt_time(total)}")
        self.subject_count_label.configure(text=f"과목 수: {len(self.cards)}개")

    def _toggle_theme(self):
        if self.theme_switch.get():
            ctk.set_appearance_mode("light")
        else:
            ctk.set_appearance_mode("dark")

    def _save(self):
        save_data(self.data)

    def _on_close(self):
        for card in self.cards.values():
            card.stop()
        self._save()
        self.destroy()


if __name__ == "__main__":
    app = StudyApp()
    app.mainloop()
