"""Главная страница: состояние обхода и быстрые действия."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from app.core import autotest, winapi
from app.core.config import config
from app.core.engine import MODE_PROCESS, MODE_SERVICE, engine
from app.core.strategies import GAME_FILTER_LABELS
from app.ui.context import AppContext
from app.ui.pages.base import Banner, Page
from app.ui.widgets import (
    Button,
    Card,
    Divider,
    IconLabel,
    Spinner,
    StatItem,
    faint_label,
    section_label,
)


class HomePage(Page):
    def __init__(self, context: AppContext) -> None:
        super().__init__(
            context,
            "Обход блокировок",
            "Выберите стратегию и включите обход. Если сервис не открывается — "
            "смените стратегию или запустите автоподбор.",
        )
        self._busy = False
        self._check_worker = None

        self._build_banners()
        self._build_hero()
        self._build_quick_check()

        context.status_changed.connect(self._on_status)
        self.apply_theme()

    # --- построение ------------------------------------------------------

    def _build_banners(self) -> None:
        self.banner_admin = Banner(
            self.context, "warning",
            "Программа запущена без прав администратора — обход не сможет "
            "загрузить драйвер WinDivert. Перезапустите её от имени администратора.",
            kind="error",
        )
        self.banner_admin.setVisible(not winapi.is_admin())
        self.body.addWidget(self.banner_admin)

        self.banner_vpn = Banner(
            self.context, "globe",
            "", kind="warn", action_text="Не показывать",
        )
        self.banner_vpn.action.clicked.connect(self._dismiss_vpn_warning)
        self.banner_vpn.setVisible(False)
        self.body.addWidget(self.banner_vpn)

    def _build_hero(self) -> None:
        card = Card(padding=22, spacing=18)

        top = QHBoxLayout()
        top.setSpacing(16)

        self.state_icon = IconLabel("shield", self.context.color("text_faint"), 44)
        top.addWidget(self.state_icon, 0, Qt.AlignmentFlag.AlignTop)

        text_box = QVBoxLayout()
        text_box.setSpacing(4)
        self.state_title = QLabel("Обход выключен")
        title_font = QFont()
        title_font.setPointSize(17)
        title_font.setWeight(QFont.Weight.DemiBold)
        self.state_title.setFont(title_font)
        text_box.addWidget(self.state_title)

        self.state_detail = QLabel("Нажмите «Запустить», чтобы включить обход.")
        self.state_detail.setObjectName("Muted")
        self.state_detail.setWordWrap(True)
        text_box.addWidget(self.state_detail)
        top.addLayout(text_box, 1)

        self.spinner = Spinner(22, self.context.color("accent"))
        top.addWidget(self.spinner, 0, Qt.AlignmentFlag.AlignTop)

        card.add_layout(top)
        card.add(Divider())

        controls = QHBoxLayout()
        controls.setSpacing(10)

        self.strategy_box = QComboBox()
        self.strategy_box.setMinimumWidth(260)
        self.strategy_box.currentIndexChanged.connect(self._on_strategy_picked)
        controls.addWidget(self.strategy_box, 1)

        self.mode_box = QComboBox()
        self.mode_box.addItem("Служба Windows", MODE_SERVICE)
        self.mode_box.addItem("Процесс", MODE_PROCESS)
        self.mode_box.setToolTip(
            "Служба работает всегда, в том числе после перезагрузки.\n"
            "Процесс живёт, пока открыта программа."
        )
        self.mode_box.currentIndexChanged.connect(self._on_mode_picked)
        controls.addWidget(self.mode_box)

        card.add_layout(controls)

        buttons = QHBoxLayout()
        buttons.setSpacing(10)
        self.btn_toggle = Button("Запустить", variant="primary", size="large")
        self.btn_toggle.clicked.connect(self.toggle_bypass)
        buttons.addWidget(self.btn_toggle)

        self.btn_restart = Button("Перезапустить")
        self.btn_restart.clicked.connect(self.restart_bypass)
        buttons.addWidget(self.btn_restart)

        self.btn_autopick = Button("Автоподбор стратегии")
        self.btn_autopick.clicked.connect(
            lambda: self.context.navigate.emit("strategies")
        )
        buttons.addWidget(self.btn_autopick)
        buttons.addStretch(1)
        card.add_layout(buttons)

        card.add(Divider())

        stats = QGridLayout()
        stats.setHorizontalSpacing(28)
        stats.setVerticalSpacing(10)
        self.stat_mode = StatItem("Режим", "—")
        self.stat_strategy = StatItem("Стратегия", "—")
        self.stat_game = StatItem("Игровой фильтр", "—")
        self.stat_uptime = StatItem("Время работы", "—")
        for column, item in enumerate(
            (self.stat_mode, self.stat_strategy, self.stat_game, self.stat_uptime)
        ):
            stats.addWidget(item, 0, column)
        stats.setColumnStretch(4, 1)
        card.add_layout(stats)

        self.body.addWidget(card)

        self._uptime_timer = QTimer(self)
        self._uptime_timer.timeout.connect(self._refresh_uptime)
        self._uptime_timer.start(1000)

    def _build_quick_check(self) -> None:
        card = Card(padding=20, spacing=14)

        header = QHBoxLayout()
        header.setSpacing(10)
        header.addWidget(section_label("Проверка доступности"))
        header.addStretch(1)
        self.check_spinner = Spinner(16, self.context.color("accent"))
        header.addWidget(self.check_spinner)
        self.btn_check = Button("Проверить", variant="soft")
        self.btn_check.clicked.connect(self.run_quick_check)
        header.addWidget(self.btn_check)
        card.add_layout(header)

        card.add(faint_label(
            "Открываем несколько адресов Discord, YouTube и Google напрямую, "
            "без прокси. Так видно, работает ли обход прямо сейчас."
        ))

        self.results_box = QWidget()
        self.results_layout = QVBoxLayout(self.results_box)
        self.results_layout.setContentsMargins(0, 0, 0, 0)
        self.results_layout.setSpacing(7)
        card.add(self.results_box)

        self.body.addWidget(card)

    # --- реакции ---------------------------------------------------------

    def on_activate(self) -> None:
        self._reload_strategies()
        self.context.refresh_status(force=True)
        self._update_vpn_banner()

    def apply_theme(self) -> None:
        self.spinner.set_color(self.context.color("accent"))
        self.check_spinner.set_color(self.context.color("accent"))
        self.btn_toggle.set_icon(
            "stop" if self.context.status.running else "play",
            self.context.color("on_accent"), 18,
        )
        self.btn_restart.set_icon("refresh", self.context.color("text_dim"), 17)
        self.btn_autopick.set_icon("bolt", self.context.color("text_dim"), 17)
        self.btn_check.set_icon("globe", self.context.color("accent_text"), 17)
        self._paint_state(self.context.status)

    def _reload_strategies(self) -> None:
        items = self.context.load_strategies()
        current = str(config.get("last_strategy"))
        self.strategy_box.blockSignals(True)
        self.strategy_box.clear()
        for strategy in items:
            label = strategy.title
            if strategy.badge:
                label = f"{strategy.title}  ·  {strategy.badge}"
            self.strategy_box.addItem(label, strategy.id)
        index = self.strategy_box.findData(current)
        if index >= 0:
            self.strategy_box.setCurrentIndex(index)
        self.strategy_box.blockSignals(False)

        mode_index = self.mode_box.findData(str(config.get("run_mode")))
        if mode_index >= 0:
            self.mode_box.blockSignals(True)
            self.mode_box.setCurrentIndex(mode_index)
            self.mode_box.blockSignals(False)

    def _on_strategy_picked(self) -> None:
        value = self.strategy_box.currentData()
        if value:
            config.set("last_strategy", value)

    def _on_mode_picked(self) -> None:
        value = self.mode_box.currentData()
        if value:
            config.set("run_mode", value)

    def _on_status(self, status) -> None:
        self._paint_state(status)

    def _paint_state(self, status) -> None:
        running = status.running
        self.state_title.setText("Обход работает" if running else "Обход выключен")
        self.state_icon.set_icon("shield_check" if running else "shield")
        self.state_icon.set_color(
            self.context.color("success") if running else self.context.color("text_faint")
        )
        self.btn_toggle.setText("Остановить" if running else "Запустить")
        self.btn_toggle.set_icon(
            "stop" if running else "play", self.context.color("on_accent"), 18
        )
        self.btn_restart.setEnabled(running and not self._busy)

        if running:
            if status.external:
                self.state_detail.setText(
                    "winws.exe запущен вне программы. Остановите его, чтобы "
                    "управлять обходом отсюда."
                )
            else:
                self.state_detail.setText(
                    "Трафик Discord, YouTube и остальных сайтов из списка идёт "
                    "в обход блокировки."
                )
        else:
            self.state_detail.setText("Нажмите «Запустить», чтобы включить обход.")

        self.stat_mode.set_value(status.mode_label)
        strategy = self.context.current_strategy()
        self.stat_strategy.set_value(strategy.title if strategy else "—")
        self.stat_game.set_value(
            GAME_FILTER_LABELS.get(self.context.current_game_filter(), "—")
        )
        self._refresh_uptime()

    def _refresh_uptime(self) -> None:
        if not self.context.status.running:
            self.stat_uptime.set_value("—")
            return
        seconds = engine.uptime_seconds()
        if not seconds:
            self.stat_uptime.set_value("—")
            return
        hours, remainder = divmod(seconds, 3600)
        minutes, secs = divmod(remainder, 60)
        self.stat_uptime.set_value(
            f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"
        )

    def _update_vpn_banner(self) -> None:
        if not config.get("warn_about_vpn", True):
            self.banner_vpn.setVisible(False)
            return
        adapters = winapi.active_vpn_adapters()
        if not adapters:
            self.banner_vpn.setVisible(False)
            return
        names = ", ".join(sorted({adapter.name for adapter in adapters})[:3])
        self.banner_vpn.set_text(
            f"Обнаружен активный VPN ({names}). Через туннель трафик и так идёт "
            "мимо блокировок, а zapret может с ним конфликтовать. "
            "Для проверки стратегий VPN лучше отключить."
        )
        self.banner_vpn.setVisible(True)

    def _dismiss_vpn_warning(self) -> None:
        config.set("warn_about_vpn", False)
        self.banner_vpn.setVisible(False)
        self.context.ok("Предупреждение о VPN отключено. Вернуть можно в настройках.")

    # --- управление обходом ----------------------------------------------

    def toggle_bypass(self) -> None:
        if self._busy:
            return
        if self.context.status.running:
            self.stop_bypass()
        else:
            self.start_bypass()

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.btn_toggle.setEnabled(not busy)
        self.btn_restart.setEnabled(not busy and self.context.status.running)
        self.strategy_box.setEnabled(not busy)
        self.mode_box.setEnabled(not busy)
        if busy:
            self.spinner.start()
        else:
            self.spinner.stop()

    def start_bypass(self) -> None:
        strategy = self.context.current_strategy()
        if strategy is None:
            self.context.error("Стратегия не найдена. Проверьте вкладку «Обновления».")
            return
        mode = str(self.mode_box.currentData() or config.get("run_mode"))
        self._set_busy(True)
        self.state_detail.setText("Запускаем обход…")

        from app.ui.widgets import Worker

        worker = Worker(self)
        worker.finished.connect(lambda _: self._after_start(strategy.title))
        worker.failed.connect(self._after_error)
        worker.run(engine.start, strategy, mode)
        self._worker = worker

    def _after_start(self, title: str) -> None:
        self._set_busy(False)
        self.context.refresh_status(force=True)
        self.context.ok(f"Обход включён — стратегия «{title}»")

    def _after_error(self, message: str) -> None:
        self._set_busy(False)
        self.context.refresh_status(force=True)
        self.context.error(message)

    def stop_bypass(self) -> None:
        self._set_busy(True)
        self.state_detail.setText("Останавливаем…")

        from app.ui.widgets import Worker

        worker = Worker(self)
        worker.finished.connect(lambda _: self._after_stop())
        worker.failed.connect(self._after_error)
        worker.run(engine.stop)
        self._worker = worker

    def _after_stop(self) -> None:
        self._set_busy(False)
        self.context.refresh_status(force=True)
        self.context.ok("Обход остановлен")

    def restart_bypass(self) -> None:
        strategy = self.context.current_strategy()
        if strategy is None:
            return
        mode = str(self.mode_box.currentData() or config.get("run_mode"))
        self._set_busy(True)

        from app.ui.widgets import Worker

        worker = Worker(self)
        worker.finished.connect(lambda _: self._after_start(strategy.title))
        worker.failed.connect(self._after_error)
        worker.run(engine.restart, strategy, mode)
        self._worker = worker

    # --- быстрая проверка ------------------------------------------------

    def run_quick_check(self) -> None:
        if self._check_worker is not None and self._check_worker.busy():
            return
        while self.results_layout.count():
            item = self.results_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        self.btn_check.setEnabled(False)
        self.check_spinner.start()

        from app.ui.widgets import Worker

        worker = Worker(self)
        worker.finished.connect(self._show_check_results)
        worker.failed.connect(self._check_failed)
        worker.run(autotest.quick_check)
        self._check_worker = worker

    def _check_failed(self, message: str) -> None:
        self.btn_check.setEnabled(True)
        self.check_spinner.stop()
        self.context.error(f"Проверка не удалась: {message}")

    def _show_check_results(self, results) -> None:
        self.btn_check.setEnabled(True)
        self.check_spinner.stop()

        for item in results:
            line = QWidget()
            layout = QHBoxLayout(line)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(10)

            token = "success" if item.ok else "danger"
            icon = IconLabel(
                "check" if item.ok else "cross", self.context.color(token), 16
            )
            layout.addWidget(icon)

            name = QLabel(item.target.key or item.target.label)
            layout.addWidget(name)

            address = QLabel(item.target.label)
            address.setObjectName("Faint")
            layout.addWidget(address)
            layout.addStretch(1)

            timing = QLabel(f"{item.ms:.0f} мс" if item.ok else "нет ответа")
            timing.setObjectName("Faint")
            layout.addWidget(timing)

            self.results_layout.addWidget(line)

        failed = [item for item in results if not item.ok]
        if not failed:
            self.context.ok("Все адреса открываются")
        elif self.context.status.running:
            self.context.warn(
                f"Не открылось адресов: {len(failed)}. Попробуйте другую стратегию."
            )
        else:
            self.context.warn(
                f"Не открылось адресов: {len(failed)}. Включите обход и проверьте снова."
            )
