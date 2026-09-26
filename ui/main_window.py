from pathlib import Path
import re

from PySide6.QtCore import QEvent, QEventLoop, QObject, QSize, Qt
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenuBar,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QSplitter,
    QStyle,
    QStackedWidget,
    QTableWidget,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
from utils.i18n import t
from utils.input_limits import (
    CHASSIS_DRIVING_DECIMALS,
    CHASSIS_DRIVING_MAX_RPM,
    CHASSIS_DRIVING_SINGLE_STEP_RPM,
    CHASSIS_STEERING_DECIMALS,
    CHASSIS_STEERING_LIMIT_DEG,
    CHASSIS_STEERING_SINGLE_STEP_DEG,
    COLUMN_POSITION_DECIMALS,
    COLUMN_POSITION_MAX_M,
    COLUMN_POSITION_MIN_M,
    COLUMN_POSITION_SINGLE_STEP_M,
    COLUMN_SPEED_DECIMALS,
    COLUMN_SPEED_MAX_MPS,
    COLUMN_SPEED_MIN_MPS,
    COLUMN_SPEED_SINGLE_STEP_MPS,
    HEAD_STEP_DECIMALS,
    HEAD_STEP_MAX_DEG,
    HEAD_STEP_MIN_DEG,
    HEAD_STEP_SINGLE_STEP_DEG,
    configure_double_spinbox,
)

CHASSIS_SPEED_SLIDER_SCALE = 100
CONTROL_PANEL_MIN_WIDTH = 260


class MotorManagementPage(QWidget):
    """Embeddable motor-management UI with no business logic."""

    def __init__(self, initial_theme="light"):
        super().__init__()
        if initial_theme not in {"light", "dark"}:
            raise ValueError(f"unsupported motor-management theme: {initial_theme}")
        self.resize(1200, 820)
        self._placeholder_labels = {}
        self._tab_keys = ["tab_head", "tab_dual_arm", "tab_column", "tab_base"]
        self._suppress_chassis_tab_prompt = False
        self.current_theme = initial_theme
        self.controller = None  # Controller 引用，用于在关闭时清理资源
        self._apply_window_icon()
        self._build_ui()
        self.retranslate_ui()
        self.apply_theme(self.current_theme)

    def shutdown(self):
        """Stop controller-owned activity when the page or host closes."""
        if self.controller:
            self.controller.shutdown()
            self.controller = None

    def closeEvent(self, event):
        """窗口关闭事件，清理资源"""
        self.shutdown()
        event.accept()

    def _apply_window_icon(self):
        icon_path = Path(__file__).parent / "texture" / "icon.png"
        self.setWindowIcon(QIcon(str(icon_path)))

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(10)

        root.addWidget(self._build_menu())

        self.top_group = self._build_top_controls()
        root.addWidget(self.top_group)

        main_area = QHBoxLayout()
        main_area.setSpacing(10)
        root.addLayout(main_area, 1)

        left_panel = self._build_left_panel()
        left_panel.setMinimumWidth(CONTROL_PANEL_MIN_WIDTH + 48)
        main_area.addWidget(left_panel, 2)

        right_panel = self._build_right_log_panel()
        right_panel.setMinimumWidth(0)
        main_area.addWidget(right_panel, 1)

    def _protect_control_panel_width(self, widget: QWidget) -> QWidget:
        widget.setMinimumWidth(CONTROL_PANEL_MIN_WIDTH)
        widget.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)
        return widget

    def _build_horizontal_state_splitter(
        self, object_name: str, control_widget: QWidget, state_widget: QWidget
    ) -> QSplitter:
        """Create a user-resizable control/state split for a device tab."""
        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        splitter.setObjectName(object_name)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(control_widget)
        splitter.addWidget(state_widget)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([CONTROL_PANEL_MIN_WIDTH, CONTROL_PANEL_MIN_WIDTH * 2])
        return splitter

    def _build_menu(self):
        menu_bar = QMenuBar(self)
        self.menu_bar = menu_bar
        self.menu_language = menu_bar.addMenu("")
        self.menu_help = menu_bar.addMenu("")

        self.action_chinese = QAction(self)
        self.action_english = QAction(self)
        self.action_japanese = QAction(self)
        self.action_russian = QAction(self)
        self.action_about = QAction(self)

        self.menu_language.addAction(self.action_chinese)
        self.menu_language.addAction(self.action_english)
        self.menu_language.addAction(self.action_japanese)
        self.menu_language.addAction(self.action_russian)
        self.menu_help.addAction(self.action_about)
        return menu_bar

    def _build_top_controls(self):
        group = QGroupBox("", self)
        layout = QHBoxLayout(group)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        self.btn_start_can = QPushButton()
        self.btn_stop_can = QPushButton()
        self.btn_check_can = QPushButton()

        left_buttons = [self.btn_start_can, self.btn_stop_can, self.btn_check_can]
        for btn in left_buttons:
            layout.addWidget(btn)

        for btn in left_buttons:
            btn.setMinimumWidth(100)  # 设置最小宽度
            btn.setFixedHeight(32)     # 固定高度

        layout.addStretch(1)
        self.btn_theme_toggle = QPushButton()
        self.btn_theme_toggle.setObjectName("themeToggleButton")
        self.btn_theme_toggle.setFixedSize(32, 32)
        self.btn_theme_toggle.setIconSize(QSize(18, 18))
        layout.addWidget(self.btn_theme_toggle)
        return group

    def _build_left_panel(self):
        self.left_tabs = QTabWidget(self)
        self.left_tabs.addTab(self._build_head_page(), "")
        self.left_tabs.addTab(self._build_dual_arm_page(), "")
        self.left_tabs.addTab(self._build_column_page(), "")
        self.left_tabs.addTab(self._build_chassis_page(), "")
        self._chassis_tab_index = self.left_tabs.count() - 1
        self.left_tabs.currentChanged.connect(self._on_left_tab_changed)
        return self.left_tabs

    def _build_dual_arm_page(self):
        container = QWidget(self)
        container.setObjectName("leftTabContent")
        layout = QHBoxLayout(container)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        self.left_control_column = self._build_motor_controls_column()
        self._protect_control_panel_width(self.left_control_column)

        self.state_panel = self._build_motor_state_panel()
        self.state_panel.setMinimumWidth(0)
        layout.addWidget(self._build_horizontal_state_splitter(
            "dualArmStateSplitter", self.left_control_column, self.state_panel
        ))
        return container

    def _build_head_page(self):
        container = QWidget(self)
        container.setObjectName("leftTabContent")
        layout = QHBoxLayout(container)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        scroll = QScrollArea(self)
        scroll.setObjectName("headScrollArea")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.viewport().setObjectName("headScrollViewport")
        scroll.setWidget(self._build_head_controls_column())
        self._protect_control_panel_width(scroll)

        self.head_state_panel = self._build_head_state_panel()
        self.head_state_panel.setObjectName("headStatePanel")
        self.head_state_panel.setMinimumWidth(0)
        layout.addWidget(self._build_horizontal_state_splitter(
            "headStateSplitter", scroll, self.head_state_panel
        ))
        return container

    def _add_head_section_title(self, layout, attr_name: str):
        label = QLabel()
        label.setObjectName("headSectionTitle")
        setattr(self, attr_name, label)
        layout.addWidget(label)
        return label

    def _add_head_divider(self, layout):
        line = QFrame()
        line.setObjectName("headDivider")
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Plain)
        line.setFixedHeight(1)
        layout.addWidget(line)

    def _build_head_controls_column(self):
        container = QWidget(self)
        container.setObjectName("headControlPanel")
        layout = QVBoxLayout(container)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(8)

        self._add_head_section_title(layout, "label_head_power_title")
        power_row = QHBoxLayout()
        self.btn_head_enable = QPushButton()
        self.btn_head_disable = QPushButton()
        power_row.addWidget(self.btn_head_enable)
        power_row.addWidget(self.btn_head_disable)
        layout.addLayout(power_row)

        self.btn_head_connect = QPushButton()
        self.btn_head_disconnect = QPushButton()
        self.label_head_tool_title = QLabel()
        self.label_head_tool_title.setVisible(False)
        self.btn_head_connect.setVisible(False)
        self.btn_head_disconnect.setVisible(False)

        self._add_head_divider(layout)

        self._add_head_section_title(layout, "label_head_motion_title")
        step_row = QHBoxLayout()
        self.label_head_step = QLabel()
        self.spin_head_step = QDoubleSpinBox()
        configure_double_spinbox(
            self.spin_head_step,
            HEAD_STEP_MIN_DEG,
            HEAD_STEP_MAX_DEG,
            HEAD_STEP_DECIMALS,
            HEAD_STEP_SINGLE_STEP_DEG,
            value=5.0,
        )
        step_row.addWidget(self.label_head_step)
        step_row.addWidget(self.spin_head_step, 1)
        layout.addLayout(step_row)

        self.head_joint_name_labels = []
        self.head_joint_value_labels = []
        self.head_joint_controls = []
        head_joint_keys = ("head_joint_yaw", "head_joint_pitch")
        head_motor_ids = (1, 2)
        for idx, (key, motor_id) in enumerate(zip(head_joint_keys, head_motor_ids)):
            block = QVBoxLayout()
            block.setSpacing(4)

            row = QHBoxLayout()
            name_label = QLabel()
            name_label.setObjectName("headJointNameLabel")
            setattr(self, key, name_label)
            self.head_joint_name_labels.append(name_label)
            row.addWidget(name_label)

            minus = QPushButton("-")
            plus = QPushButton("+")
            minus.setObjectName(f"btn_head_j{idx}_minus")
            plus.setObjectName(f"btn_head_j{idx}_plus")
            setattr(self, f"btn_head_j{idx}_minus", minus)
            setattr(self, f"btn_head_j{idx}_plus", plus)
            minus.setMinimumWidth(36)
            plus.setMinimumWidth(36)
            minus.setMinimumHeight(36)
            plus.setMinimumHeight(36)

            value_label = QLabel("--")
            value_label.setObjectName("headJointValueLabel")
            value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.head_joint_value_labels.append(value_label)

            row.addWidget(minus)
            row.addWidget(value_label, 1)
            row.addWidget(plus)
            block.addLayout(row)

            zero_row = QHBoxLayout()
            btn_zero_passive = QPushButton()
            btn_zero_active = QPushButton()
            btn_go_zero = QPushButton()
            for btn in (btn_zero_passive, btn_zero_active, btn_go_zero):
                btn.setMinimumHeight(30)
                zero_row.addWidget(btn)
            block.addLayout(zero_row)

            self.head_joint_controls.append({
                "motor_id": motor_id,
                "btn_zero_passive": btn_zero_passive,
                "btn_zero_active": btn_zero_active,
                "btn_go_zero": btn_go_zero,
            })
            layout.addLayout(block)

        self._add_head_divider(layout)

        layout.addStretch(1)
        return container

    def get_head_step_deg(self) -> float:
        return float(self.spin_head_step.value())

    def apply_head_step_limits(
        self,
        min_deg: float = HEAD_STEP_MIN_DEG,
        max_deg: float = HEAD_STEP_MAX_DEG,
        default_deg: float | None = None,
    ) -> None:
        configure_double_spinbox(
            self.spin_head_step,
            min_deg,
            max_deg,
            HEAD_STEP_DECIMALS,
            HEAD_STEP_SINGLE_STEP_DEG,
            default_deg,
        )

    def _build_head_state_panel(self):
        group = QGroupBox()
        layout = QVBoxLayout(group)

        self.head_table = QTableWidget(0, 9)
        self.head_table.verticalHeader().setVisible(False)
        self.head_table.setMinimumWidth(0)
        self.head_table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        layout.addWidget(self.head_table, 1)

        button_row = QHBoxLayout()
        self.btn_head_sync = QPushButton()
        self.btn_head_toggle_monitor = QPushButton()
        button_row.addWidget(self.btn_head_sync)
        button_row.addWidget(self.btn_head_toggle_monitor)
        button_row.addStretch(1)
        layout.addLayout(button_row)
        return group

    def _build_column_page(self):
        container = QWidget(self)
        container.setObjectName("leftTabContent")
        layout = QHBoxLayout(container)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        scroll = QScrollArea(self)
        scroll.setObjectName("columnScrollArea")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.viewport().setObjectName("columnScrollViewport")
        scroll.setWidget(self._build_column_controls_column())
        self._protect_control_panel_width(scroll)

        self.column_state_panel = self._build_column_state_panel()
        self.column_state_panel.setObjectName("columnStatePanel")
        self.column_state_panel.setMinimumWidth(0)
        layout.addWidget(self._build_horizontal_state_splitter(
            "columnStateSplitter", scroll, self.column_state_panel
        ))
        return container

    def _add_column_section_title(self, layout, attr_name: str):
        label = QLabel()
        label.setObjectName("columnSectionTitle")
        setattr(self, attr_name, label)
        layout.addWidget(label)
        return label

    def _add_column_divider(self, layout):
        line = QFrame()
        line.setObjectName("columnDivider")
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Plain)
        line.setFixedHeight(1)
        layout.addWidget(line)

    def _build_column_controls_column(self):
        container = QWidget(self)
        container.setObjectName("columnControlPanel")
        layout = QVBoxLayout(container)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(8)

        self._add_column_section_title(layout, "label_column_power_title")
        power_row = QHBoxLayout()
        self.btn_column_enable = QPushButton()
        self.btn_column_disable = QPushButton()
        self.btn_column_estop = QPushButton()
        power_row.addWidget(self.btn_column_enable)
        power_row.addWidget(self.btn_column_disable)
        power_row.addWidget(self.btn_column_estop)
        layout.addLayout(power_row)

        self.btn_column_connect = QPushButton()
        self.btn_column_disconnect = QPushButton()
        self.label_column_tool_title = QLabel()
        self.label_column_tool_title.setVisible(False)
        self.btn_column_connect.setVisible(False)
        self.btn_column_disconnect.setVisible(False)

        self._add_column_divider(layout)

        self._add_column_section_title(layout, "label_column_mode_title")
        mode_row = QHBoxLayout()
        self.btn_column_mode_velocity = QPushButton()
        self.btn_column_mode_position = QPushButton()
        for btn in (self.btn_column_mode_velocity, self.btn_column_mode_position):
            btn.setCheckable(True)
            btn.setMinimumHeight(36)
            mode_row.addWidget(btn, 1)
        layout.addLayout(mode_row)

        self._add_column_divider(layout)

        self.column_velocity_panel = QWidget()
        velocity_panel_layout = QVBoxLayout(self.column_velocity_panel)
        velocity_panel_layout.setContentsMargins(0, 0, 0, 0)
        velocity_panel_layout.setSpacing(8)
        self._add_column_section_title(velocity_panel_layout, "label_column_velocity_title")
        velocity_layout = QVBoxLayout()

        jog_speed_row = QHBoxLayout()
        self.label_column_jog_speed = QLabel()
        self.spin_column_jog_speed = QDoubleSpinBox()
        configure_double_spinbox(
            self.spin_column_jog_speed,
            COLUMN_SPEED_MIN_MPS,
            COLUMN_SPEED_MAX_MPS,
            COLUMN_SPEED_DECIMALS,
            COLUMN_SPEED_SINGLE_STEP_MPS,
            value=0.05,
        )
        jog_speed_row.addWidget(self.label_column_jog_speed)
        jog_speed_row.addWidget(self.spin_column_jog_speed, 1)
        velocity_layout.addLayout(jog_speed_row)

        jog_row = QHBoxLayout()
        self.btn_column_jog_up = QPushButton()
        self.btn_column_jog_down = QPushButton()
        for btn in (self.btn_column_jog_up, self.btn_column_jog_down):
            btn.setMinimumHeight(40)
        jog_row.addWidget(self.btn_column_jog_up, 1)
        jog_row.addWidget(self.btn_column_jog_down, 1)
        velocity_layout.addLayout(jog_row)
        velocity_panel_layout.addLayout(velocity_layout)
        layout.addWidget(self.column_velocity_panel)

        self.column_mode_divider = QFrame()
        self.column_mode_divider.setObjectName("columnDivider")
        self.column_mode_divider.setFrameShape(QFrame.Shape.HLine)
        self.column_mode_divider.setFrameShadow(QFrame.Shadow.Plain)
        self.column_mode_divider.setFixedHeight(1)
        layout.addWidget(self.column_mode_divider)

        self.column_position_panel = QWidget()
        position_panel_layout = QVBoxLayout(self.column_position_panel)
        position_panel_layout.setContentsMargins(0, 0, 0, 0)
        position_panel_layout.setSpacing(8)
        self._add_column_section_title(position_panel_layout, "label_column_position_title")
        position_layout = QVBoxLayout()

        target_row = QHBoxLayout()
        self.label_column_target = QLabel()
        self.spin_column_target = QDoubleSpinBox()
        configure_double_spinbox(
            self.spin_column_target,
            COLUMN_POSITION_MIN_M,
            COLUMN_POSITION_MAX_M,
            COLUMN_POSITION_DECIMALS,
            COLUMN_POSITION_SINGLE_STEP_M,
            value=0.0,
        )
        target_row.addWidget(self.label_column_target)
        target_row.addWidget(self.spin_column_target, 1)
        position_layout.addLayout(target_row)

        profile_speed_row = QHBoxLayout()
        self.label_column_move_speed = QLabel()
        self.spin_column_move_speed = QDoubleSpinBox()
        configure_double_spinbox(
            self.spin_column_move_speed,
            COLUMN_SPEED_MIN_MPS,
            COLUMN_SPEED_MAX_MPS,
            COLUMN_SPEED_DECIMALS,
            COLUMN_SPEED_SINGLE_STEP_MPS,
            value=0.05,
        )
        profile_speed_row.addWidget(self.label_column_move_speed)
        profile_speed_row.addWidget(self.spin_column_move_speed, 1)
        position_layout.addLayout(profile_speed_row)

        position_btn_row = QHBoxLayout()
        self.btn_column_move_to = QPushButton()
        self.btn_column_stop = QPushButton()
        for btn in (self.btn_column_move_to, self.btn_column_stop):
            btn.setMinimumHeight(40)
        position_btn_row.addWidget(self.btn_column_move_to)
        position_btn_row.addWidget(self.btn_column_stop)
        position_layout.addLayout(position_btn_row)
        position_panel_layout.addLayout(position_layout)
        layout.addWidget(self.column_position_panel)
        self.column_position_panel.setVisible(False)
        self.column_mode_divider.setVisible(False)

        self._add_column_divider(layout)

        self._add_column_section_title(layout, "label_column_homing_title")
        homing_row = QHBoxLayout()
        self.btn_column_set_zero = QPushButton()
        self.btn_column_return_home = QPushButton()
        self.btn_column_stop_homing = QPushButton()
        homing_row.addWidget(self.btn_column_set_zero)
        homing_row.addWidget(self.btn_column_return_home)
        homing_row.addWidget(self.btn_column_stop_homing)
        layout.addLayout(homing_row)

        self.label_column_detail = QLabel()
        self.label_column_detail.setObjectName("columnDetailLabel")
        self.label_column_detail.setWordWrap(True)
        layout.addWidget(self.label_column_detail)

        layout.addStretch(1)
        return container

    def get_column_target_position_m(self) -> float:
        return float(self.spin_column_target.value())

    def get_column_move_speed_mps(self) -> float:
        return float(self.spin_column_move_speed.value())

    def get_column_jog_speed_mps(self) -> float:
        return float(self.spin_column_jog_speed.value())

    def set_column_target_position_m(self, position_m: float) -> None:
        self.spin_column_target.setValue(float(position_m))

    def apply_column_position_limits(self, min_m: float, max_m: float, max_speed_mps: float = 0.1):
        lo = float(min_m)
        hi = max(lo, float(max_m))
        configure_double_spinbox(
            self.spin_column_target,
            lo,
            hi,
            COLUMN_POSITION_DECIMALS,
            COLUMN_POSITION_SINGLE_STEP_M,
        )
        lim = max(COLUMN_SPEED_MIN_MPS, float(max_speed_mps))
        for spin in (self.spin_column_move_speed, self.spin_column_jog_speed):
            configure_double_spinbox(
                spin,
                COLUMN_SPEED_MIN_MPS,
                lim,
                COLUMN_SPEED_DECIMALS,
                COLUMN_SPEED_SINGLE_STEP_MPS,
            )
            spin.setValue(min(float(spin.value()), lim))

    def _build_column_state_panel(self):
        group = QGroupBox()
        layout = QVBoxLayout(group)

        self.column_table = QTableWidget(0, 9)
        self.column_table.verticalHeader().setVisible(False)
        self.column_table.setMinimumWidth(0)
        self.column_table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        layout.addWidget(self.column_table, 1)

        button_row = QHBoxLayout()
        self.btn_column_check = QPushButton()
        self.btn_column_toggle_monitor = QPushButton()
        button_row.addWidget(self.btn_column_check)
        button_row.addWidget(self.btn_column_toggle_monitor)
        button_row.addStretch(1)
        layout.addLayout(button_row)
        return group

    def _build_chassis_page(self):
        container = QWidget(self)
        container.setObjectName("leftTabContent")
        layout = QHBoxLayout(container)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        scroll = QScrollArea(self)
        scroll.setObjectName("chassisScrollArea")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.viewport().setObjectName("chassisScrollViewport")
        scroll.setWidget(self._build_chassis_controls_column())
        self._protect_control_panel_width(scroll)

        self.chassis_state_panel = self._build_chassis_state_panel()
        self.chassis_state_panel.setObjectName("chassisStatePanel")
        self.chassis_state_panel.setMinimumWidth(0)
        layout.addWidget(self._build_horizontal_state_splitter(
            "chassisStateSplitter", scroll, self.chassis_state_panel
        ))
        return container

    def _add_chassis_section_title(self, layout, attr_name: str):
        label = QLabel()
        label.setObjectName("chassisSectionTitle")
        setattr(self, attr_name, label)
        layout.addWidget(label)
        return label

    def _add_chassis_divider(self, layout):
        line = QFrame()
        line.setObjectName("chassisDivider")
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Plain)
        line.setFixedHeight(1)
        layout.addWidget(line)

    def _build_chassis_controls_column(self):
        container = QWidget(self)
        container.setObjectName("chassisControlPanel")
        layout = QVBoxLayout(container)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(8)

        self._add_chassis_section_title(layout, "label_chassis_power_title")
        power_row = QHBoxLayout()
        self.btn_chassis_enable = QPushButton()
        self.btn_chassis_disable = QPushButton()
        self.btn_chassis_estop = QPushButton()
        power_row.addWidget(self.btn_chassis_enable)
        power_row.addWidget(self.btn_chassis_disable)
        power_row.addWidget(self.btn_chassis_estop)
        layout.addLayout(power_row)
        self.btn_chassis_connect = QPushButton()
        self.btn_chassis_scan = QPushButton()
        self.btn_chassis_stop = QPushButton()
        self.btn_chassis_connect.setVisible(False)
        self.btn_chassis_stop.setVisible(False)

        self._add_chassis_divider(layout)

        switch_row = QHBoxLayout()
        self.btn_chassis_switch_view = QPushButton()
        self.btn_chassis_switch_view.setMinimumHeight(32)
        self.btn_chassis_switch_view.clicked.connect(self._toggle_chassis_control_view)
        switch_row.addWidget(self.btn_chassis_switch_view)
        layout.addLayout(switch_row)

        self.chassis_control_stack = QStackedWidget()
        self.chassis_control_stack.setObjectName("chassisControlStack")
        self.chassis_control_stack.addWidget(self._build_chassis_motor_panel())
        self.chassis_control_stack.addWidget(self._build_chassis_motion_panel())
        layout.addWidget(self.chassis_control_stack, 1)

        self._chassis_control_view = "motion"
        self.chassis_control_stack.setCurrentIndex(1)
        self._update_chassis_view_toggle_button_text()
        return container

    def _build_chassis_motor_panel(self):
        panel = QWidget()
        panel.setObjectName("chassisMotorPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self._add_chassis_section_title(layout, "label_chassis_um_title")
        self.chassis_um_controls = {}
        for module_key in ("FL", "FR", "BL", "BR"):
            row, controls = self._build_chassis_um_motor_row(module_key)
            layout.addWidget(row)
            self.chassis_um_controls[module_key] = controls

        self._add_chassis_divider(layout)

        self._add_chassis_section_title(layout, "label_chassis_rs_title")
        self.chassis_rs_controls = {}
        for module_key in ("FL", "FR", "BL", "BR"):
            row, controls = self._build_chassis_rs_motor_row(module_key)
            layout.addWidget(row)
            self.chassis_rs_controls[module_key] = controls

        layout.addStretch(1)
        return panel

    def _build_chassis_motion_panel(self):
        panel = QWidget()
        panel.setObjectName("chassisMotionPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self._add_chassis_section_title(layout, "label_chassis_motion_title")
        self.chassis_motion_section = QWidget()
        self.chassis_motion_section.setObjectName("chassisSectionBody")
        motion_layout = QVBoxLayout(self.chassis_motion_section)
        motion_layout.setContentsMargins(0, 0, 0, 0)
        motion_layout.setSpacing(8)

        speed_row = QHBoxLayout()
        self.label_chassis_linear_speed = QLabel()
        self.slider_chassis_linear_speed = QSlider(Qt.Orientation.Horizontal)
        self.slider_chassis_linear_speed.setRange(0, 200)
        self.slider_chassis_linear_speed.setValue(10)
        self.label_chassis_linear_speed_value = QLabel()
        self.label_chassis_linear_speed_value.setMinimumWidth(72)
        self.label_chassis_linear_speed_value.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        speed_row.addWidget(self.label_chassis_linear_speed)
        speed_row.addWidget(self.slider_chassis_linear_speed, 1)
        speed_row.addWidget(self.label_chassis_linear_speed_value)
        motion_layout.addLayout(speed_row)

        omega_row = QHBoxLayout()
        self.label_chassis_angular_speed = QLabel()
        self.slider_chassis_angular_speed = QSlider(Qt.Orientation.Horizontal)
        self.slider_chassis_angular_speed.setRange(0, 300)
        self.slider_chassis_angular_speed.setValue(10)
        self.label_chassis_angular_speed_value = QLabel()
        self.label_chassis_angular_speed_value.setMinimumWidth(72)
        self.label_chassis_angular_speed_value.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        omega_row.addWidget(self.label_chassis_angular_speed)
        omega_row.addWidget(self.slider_chassis_angular_speed, 1)
        omega_row.addWidget(self.label_chassis_angular_speed_value)
        motion_layout.addLayout(omega_row)

        self.slider_chassis_linear_speed.valueChanged.connect(
            self._update_chassis_linear_speed_label
        )
        self.slider_chassis_angular_speed.valueChanged.connect(
            self._update_chassis_angular_speed_label
        )
        self._update_chassis_linear_speed_label(self.slider_chassis_linear_speed.value())
        self._update_chassis_angular_speed_label(self.slider_chassis_angular_speed.value())

        motion_grid = QGridLayout()
        motion_grid.setSpacing(6)
        self.btn_chassis_forward = QPushButton()
        self.btn_chassis_backward = QPushButton()
        self.btn_chassis_left = QPushButton()
        self.btn_chassis_right = QPushButton()
        self.btn_chassis_rotate_left = QPushButton()
        self.btn_chassis_rotate_right = QPushButton()
        self.btn_chassis_motion_stop = QPushButton()
        for btn in (
            self.btn_chassis_forward,
            self.btn_chassis_backward,
            self.btn_chassis_left,
            self.btn_chassis_right,
            self.btn_chassis_rotate_left,
            self.btn_chassis_rotate_right,
        ):
            btn.setMinimumHeight(36)
            btn.setCheckable(False)
        self.btn_chassis_motion_stop.setMinimumHeight(36)
        motion_grid.addWidget(self.btn_chassis_forward, 0, 1)
        motion_grid.addWidget(self.btn_chassis_left, 1, 0)
        motion_grid.addWidget(self.btn_chassis_motion_stop, 1, 1)
        motion_grid.addWidget(self.btn_chassis_right, 1, 2)
        motion_grid.addWidget(self.btn_chassis_rotate_left, 2, 0)
        motion_grid.addWidget(self.btn_chassis_backward, 2, 1)
        motion_grid.addWidget(self.btn_chassis_rotate_right, 2, 2)
        motion_layout.addLayout(motion_grid)
        layout.addWidget(self.chassis_motion_section)
        layout.addStretch(1)
        return panel

    def _toggle_chassis_control_view(self):
        if getattr(self, "_chassis_control_view", "motion") == "motor":
            self._chassis_control_view = "motion"
            self.chassis_control_stack.setCurrentIndex(1)
        else:
            self._show_chassis_motor_safety_dialog()
            self._chassis_control_view = "motor"
            self.chassis_control_stack.setCurrentIndex(0)
        self._update_chassis_view_toggle_button_text()

    def _on_left_tab_changed(self, index: int):
        if self._suppress_chassis_tab_prompt:
            return
        if index == getattr(self, "_chassis_tab_index", 3):
            self._show_chassis_motion_safety_dialog()

    def _show_chassis_motion_safety_dialog(self):
        dialog = QMessageBox(self)
        dialog.setIcon(QMessageBox.Icon.Warning)
        dialog.setWindowTitle(t("dialog_chassis_motion_safety_title"))
        dialog.setTextFormat(Qt.TextFormat.PlainText)
        dialog.setText(t("dialog_chassis_motion_safety_message"))
        dialog.setInformativeText(t("dialog_chassis_motion_safety_informative"))
        dialog.setStandardButtons(QMessageBox.StandardButton.Ok)
        dialog.exec()

    def _chassis_status_panel_anchor(self) -> QWidget | None:
        """底盘页右侧「底盘状态面板」模块（与头部状态面板同布局）。"""
        anchor = self.findChild(QWidget, "chassisStatePanel")
        if anchor is None:
            anchor = getattr(self, "chassis_state_panel", None)
        if anchor is None or not hasattr(self, "left_tabs"):
            return anchor

        for index in range(self.left_tabs.count()):
            page = self.left_tabs.widget(index)
            if page is not None and page.isAncestorOf(anchor):
                if self.left_tabs.currentIndex() != index:
                    self._suppress_chassis_tab_prompt = True
                    try:
                        self.left_tabs.setCurrentIndex(index)
                    finally:
                        self._suppress_chassis_tab_prompt = False
                break

        widget: QWidget | None = anchor
        while widget is not None:
            widget.updateGeometry()
            layout = widget.layout()
            if layout is not None:
                layout.activate()
            widget = widget.parentWidget()

        QApplication.processEvents()
        return anchor

    def _chassis_safety_overlay_stylesheet(self) -> str:
        """底盘安全提示遮罩样式，跟随当前主题保证对比度。"""
        panel_bg = self.theme_color("panel_bg", "#141b24")
        text_color = self.theme_color("text_color", "#f1f5f9")
        border_color = self.theme_color("border_color", "#3d4f63")
        btn_bg = self.theme_color("btn_bg", "#a8b0bd")
        btn_text = self.theme_color("btn_text", "#0f1419")
        btn_hover_bg = self.theme_color("btn_hover_bg", "#c8cfd8")
        return (
            "QWidget#chassisSafetyOverlay { background-color: rgba(0, 0, 0, 110); }"
            f"QFrame#chassisSafetyCard {{"
            f" background-color: {panel_bg};"
            f" border: 1px solid {border_color};"
            f" border-radius: 8px;"
            f" }}"
            f"QLabel#chassisSafetyTitle {{"
            f" color: {text_color};"
            f" font-size: 15px;"
            f" font-weight: bold;"
            f" }}"
            f"QLabel#chassisSafetyMessage {{"
            f" color: {text_color};"
            f" font-size: 15px;"
            f" }}"
            f"QDialogButtonBox QPushButton {{"
            f" background-color: {btn_bg};"
            f" color: {btn_text};"
            f" border: 1px solid {border_color};"
            f" border-radius: 5px;"
            f" min-width: 72px;"
            f" min-height: 28px;"
            f" font-size: 13px;"
            f" font-weight: 600;"
            f" }}"
            f"QDialogButtonBox QPushButton:hover {{"
            f" background-color: {btn_hover_bg};"
            f" }}"
        )

    def _show_chassis_motor_safety_dialog(self):
        """单电机测试安全提示：在底盘状态面板内部几何正中心弹出。"""
        anchor = self._chassis_status_panel_anchor() or self

        overlay = QWidget(anchor)
        overlay.setObjectName("chassisSafetyOverlay")
        overlay.setGeometry(anchor.rect())
        overlay.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        overlay.setStyleSheet(self._chassis_safety_overlay_stylesheet())

        outer = QVBoxLayout(overlay)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addStretch(1)

        center_row = QHBoxLayout()
        center_row.addStretch(1)

        card = QFrame(overlay)
        card.setObjectName("chassisSafetyCard")
        card.setMinimumWidth(400)
        card.setMaximumWidth(460)

        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(32, 28, 32, 24)
        card_layout.setSpacing(16)

        title = QLabel(t("dialog_chassis_motor_safety_title"))
        title.setObjectName("chassisSafetyTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_layout.addWidget(title)

        icon = QLabel()
        icon.setPixmap(
            self.style()
            .standardIcon(QStyle.StandardPixmap.SP_MessageBoxWarning)
            .pixmap(44, 44)
        )
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_layout.addWidget(icon)

        message = QLabel(t("dialog_chassis_motor_safety_message"))
        message.setObjectName("chassisSafetyMessage")
        message.setWordWrap(True)
        message.setAlignment(
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter
        )
        card_layout.addWidget(message)

        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        button_box.setCenterButtons(True)
        card_layout.addWidget(button_box)

        center_row.addWidget(card)
        center_row.addStretch(1)
        outer.addLayout(center_row)
        outer.addStretch(1)

        class _OverlayResizeFilter(QObject):
            def __init__(self, panel_widget: QWidget, overlay_widget: QWidget):
                super().__init__(panel_widget)
                self._overlay = overlay_widget

            def eventFilter(self, watched: QObject, event: QEvent) -> bool:
                if (
                    watched is self.parent()
                    and event.type() == QEvent.Type.Resize
                ):
                    self._overlay.setGeometry(watched.rect())
                return False

        resize_filter = _OverlayResizeFilter(anchor, overlay)
        anchor.installEventFilter(resize_filter)

        loop = QEventLoop()

        def _close_overlay() -> None:
            anchor.removeEventFilter(resize_filter)
            overlay.deleteLater()
            loop.quit()

        button_box.accepted.connect(_close_overlay)
        overlay.show()
        overlay.raise_()
        loop.exec()

    def _update_chassis_view_toggle_button_text(self):
        btn = getattr(self, "btn_chassis_switch_view", None)
        if btn is None:
            return
        if getattr(self, "_chassis_control_view", "motion") == "motor":
            btn.setText(t("btn_chassis_switch_to_motion"))
        else:
            btn.setText(t("btn_chassis_switch_to_motor"))

    def _update_chassis_linear_speed_label(self, slider_value: int) -> None:
        speed = slider_value / CHASSIS_SPEED_SLIDER_SCALE
        self.label_chassis_linear_speed_value.setText(
            f"{speed:.2f}{t('suffix_chassis_linear_speed')}"
        )

    def _update_chassis_angular_speed_label(self, slider_value: int) -> None:
        speed = slider_value / CHASSIS_SPEED_SLIDER_SCALE
        self.label_chassis_angular_speed_value.setText(
            f"{speed:.2f}{t('suffix_chassis_angular_speed')}"
        )

    def apply_chassis_speed_slider_limits(
        self,
        max_linear_m_s: float,
        max_angular_rad_s: float,
    ) -> None:
        max_lin = max(1, int(round(max_linear_m_s * CHASSIS_SPEED_SLIDER_SCALE)))
        max_ang = max(1, int(round(max_angular_rad_s * CHASSIS_SPEED_SLIDER_SCALE)))
        self.slider_chassis_linear_speed.setRange(0, max_lin)
        self.slider_chassis_angular_speed.setRange(0, max_ang)
        if self.slider_chassis_linear_speed.value() > max_lin:
            self.slider_chassis_linear_speed.setValue(max_lin)
        if self.slider_chassis_angular_speed.value() > max_ang:
            self.slider_chassis_angular_speed.setValue(max_ang)
        self._update_chassis_linear_speed_label(self.slider_chassis_linear_speed.value())
        self._update_chassis_angular_speed_label(self.slider_chassis_angular_speed.value())

    def set_chassis_linear_speed_m_s(self, speed_m_s: float) -> None:
        value = int(round(max(0.0, float(speed_m_s)) * CHASSIS_SPEED_SLIDER_SCALE))
        self.slider_chassis_linear_speed.setValue(
            min(value, self.slider_chassis_linear_speed.maximum())
        )

    def set_chassis_angular_speed_rad_s(self, speed_rad_s: float) -> None:
        value = int(round(max(0.0, float(speed_rad_s)) * CHASSIS_SPEED_SLIDER_SCALE))
        self.slider_chassis_angular_speed.setValue(
            min(value, self.slider_chassis_angular_speed.maximum())
        )

    def get_chassis_linear_speed_m_s(self) -> float:
        return self.slider_chassis_linear_speed.value() / CHASSIS_SPEED_SLIDER_SCALE

    def get_chassis_angular_speed_rad_s(self) -> float:
        return self.slider_chassis_angular_speed.value() / CHASSIS_SPEED_SLIDER_SCALE

    def _build_chassis_um_motor_row(self, module_key: str):
        row = QWidget()
        row.setObjectName("chassisMotorRow")
        row_layout = QVBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(4)

        title = QLabel()
        title.setObjectName("chassisMotorTitle")
        row_layout.addWidget(title)

        btn_row = QHBoxLayout()
        btn_enable = QPushButton()
        btn_disable = QPushButton()
        for btn in (btn_enable, btn_disable):
            btn.setMinimumHeight(30)
            btn_row.addWidget(btn)
        row_layout.addLayout(btn_row)

        speed_row = QHBoxLayout()
        label_speed = QLabel()
        spin_speed = QDoubleSpinBox()
        configure_double_spinbox(
            spin_speed,
            -CHASSIS_DRIVING_MAX_RPM,
            CHASSIS_DRIVING_MAX_RPM,
            CHASSIS_DRIVING_DECIMALS,
            CHASSIS_DRIVING_SINGLE_STEP_RPM,
            value=0.0,
        )
        btn_start = QPushButton()
        btn_stop = QPushButton()
        for btn in (btn_start, btn_stop):
            btn.setMinimumHeight(30)
        speed_row.addWidget(label_speed)
        speed_row.addWidget(spin_speed, 1)
        speed_row.addWidget(btn_start)
        speed_row.addWidget(btn_stop)
        row_layout.addLayout(speed_row)

        return row, {
            "module": module_key,
            "title": title,
            "btn_enable": btn_enable,
            "btn_disable": btn_disable,
            "label_speed": label_speed,
            "spin_speed": spin_speed,
            "btn_start": btn_start,
            "btn_stop": btn_stop,
        }

    def _build_chassis_rs_motor_row(self, module_key: str):
        row = QWidget()
        row.setObjectName("chassisMotorRow")
        row_layout = QVBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(4)

        title = QLabel()
        title.setObjectName("chassisMotorTitle")
        row_layout.addWidget(title)

        btn_row = QHBoxLayout()
        btn_enable = QPushButton()
        btn_disable = QPushButton()
        for btn in (btn_enable, btn_disable):
            btn.setMinimumHeight(30)
            btn_row.addWidget(btn)
        row_layout.addLayout(btn_row)

        zero_row = QHBoxLayout()
        btn_zero_manual = QPushButton()
        btn_zero_auto = QPushButton()
        btn_go_zero = QPushButton()
        for btn in (btn_zero_manual, btn_zero_auto, btn_go_zero):
            btn.setMinimumHeight(30)
            zero_row.addWidget(btn)
        row_layout.addLayout(zero_row)

        angle_row = QHBoxLayout()
        label_angle = QLabel()
        spin_angle = QDoubleSpinBox()
        configure_double_spinbox(
            spin_angle,
            -CHASSIS_STEERING_LIMIT_DEG,
            CHASSIS_STEERING_LIMIT_DEG,
            CHASSIS_STEERING_DECIMALS,
            CHASSIS_STEERING_SINGLE_STEP_DEG,
            value=0.0,
        )
        btn_minus = QPushButton("-")
        btn_plus = QPushButton("+")
        for btn in (btn_minus, btn_plus):
            btn.setFixedSize(32, 30)
            btn.setAutoRepeat(True)
            btn.setAutoRepeatDelay(400)
            btn.setAutoRepeatInterval(120)
        btn_apply = QPushButton()
        angle_row.addWidget(label_angle)
        angle_row.addWidget(btn_minus)
        angle_row.addWidget(spin_angle, 1)
        angle_row.addWidget(btn_plus)
        angle_row.addWidget(btn_apply)
        row_layout.addLayout(angle_row)

        return row, {
            "module": module_key,
            "title": title,
            "btn_enable": btn_enable,
            "btn_disable": btn_disable,
            "btn_zero_manual": btn_zero_manual,
            "btn_zero_auto": btn_zero_auto,
            "btn_go_zero": btn_go_zero,
            "label_angle": label_angle,
            "spin_angle": spin_angle,
            "btn_angle_minus": btn_minus,
            "btn_angle_plus": btn_plus,
            "btn_apply_angle": btn_apply,
        }

    def apply_chassis_um_speed_limits(self, max_rpm: float):
        lim = max(CHASSIS_DRIVING_SINGLE_STEP_RPM, float(max_rpm))
        for ctrl in getattr(self, "chassis_um_controls", {}).values():
            spin = ctrl.get("spin_speed")
            if spin is not None:
                configure_double_spinbox(
                    spin,
                    -lim,
                    lim,
                    CHASSIS_DRIVING_DECIMALS,
                    CHASSIS_DRIVING_SINGLE_STEP_RPM,
                )

    def apply_chassis_rs_angle_limits(self, max_deg: float):
        lim = max(CHASSIS_STEERING_SINGLE_STEP_DEG, float(max_deg))
        for ctrl in getattr(self, "chassis_rs_controls", {}).values():
            spin = ctrl.get("spin_angle")
            if spin is not None:
                configure_double_spinbox(
                    spin,
                    -lim,
                    lim,
                    CHASSIS_STEERING_DECIMALS,
                    min(CHASSIS_STEERING_SINGLE_STEP_DEG, lim),
                )

    def _build_chassis_state_panel(self):
        group = QGroupBox()
        layout = QVBoxLayout(group)

        self.chassis_table = QTableWidget(0, 10)
        self.chassis_table.verticalHeader().setVisible(False)
        self.chassis_table.setMinimumWidth(0)
        self.chassis_table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        layout.addWidget(self.chassis_table, 1)

        button_row = QHBoxLayout()
        button_row.setSpacing(10)
        button_row.addWidget(self.btn_chassis_scan)
        self.btn_chassis_toggle_monitor = QPushButton()
        button_row.addWidget(self.btn_chassis_toggle_monitor)
        button_row.addStretch(1)
        layout.addLayout(button_row)
        return group

    def _build_placeholder_page(self, tab_key):
        page = QWidget(self)
        page.setObjectName("leftTabContent")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(14, 14, 14, 14)
        label = QLabel()
        layout.addWidget(label)
        self._placeholder_labels[tab_key] = label
        layout.addStretch(1)
        return page

    def _build_motor_controls_column(self):
        container = QWidget(self)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        self.power_group = QGroupBox()
        power_layout = QHBoxLayout(self.power_group)
        self.btn_enable_arm = QPushButton()
        self.btn_disable_arm = QPushButton()
        power_layout.addWidget(self.btn_enable_arm)
        power_layout.addWidget(self.btn_disable_arm)

        self.zero_group = QGroupBox()
        zero_layout = QHBoxLayout(self.zero_group)
        self.btn_set_zero_arm = QPushButton()
        self.btn_go_zero_arm = QPushButton()
        zero_layout.addWidget(self.btn_set_zero_arm)
        zero_layout.addWidget(self.btn_go_zero_arm)

        self.control_group = QGroupBox()
        control_layout = QVBoxLayout(self.control_group)
        speed_row = QHBoxLayout()
        self.label_speed = QLabel()
        speed_row.addWidget(self.label_speed)
        self.slider_speed = QSlider(Qt.Orientation.Horizontal)
        self.slider_speed.setMinimum(0)
        self.slider_speed.setMaximum(100)
        self.slider_speed.setValue(50)
        speed_row.addWidget(self.slider_speed)
        # 添加步长数值显示框
        self.spinbox_step = QDoubleSpinBox()
        self.spinbox_step.setMinimum(0.0)
        self.spinbox_step.setMaximum(10.0)
        self.spinbox_step.setSingleStep(0.1)
        self.spinbox_step.setDecimals(1)
        self.spinbox_step.setValue(5.0)
        self.spinbox_step.setFixedWidth(80)
        speed_row.addWidget(self.spinbox_step)
        control_layout.addLayout(speed_row)

        arm_select_row = QHBoxLayout()
        self.label_arm_target = QLabel()
        arm_select_row.addWidget(self.label_arm_target)
        self.arm_target_combo = QComboBox()
        arm_select_row.addWidget(self.arm_target_combo, 1)
        control_layout.addLayout(arm_select_row)

        self.joint_name_labels = []
        self.joint_rows = []
        for index in range(8):
            row = QHBoxLayout()
            name_label = QLabel()
            self.joint_name_labels.append(name_label)
            row.addWidget(name_label)

            btn_minus = QPushButton("-")
            btn_plus = QPushButton("+")
            btn_minus.setMinimumWidth(36)
            btn_plus.setMinimumWidth(36)
            value_label = QLabel()

            row.addWidget(btn_minus)
            row.addWidget(value_label)
            row.addWidget(btn_plus)
            control_layout.addLayout(row)
            self.joint_rows.append((index, btn_minus, value_label, btn_plus))

        self.btn_test_all_motors = QPushButton()
        # 移除最大宽度限制，让按钮自适应文字长度
        control_layout.addWidget(self.btn_test_all_motors)
        control_layout.addStretch(1)

        layout.addWidget(self.power_group)
        layout.addWidget(self.zero_group)
        layout.addWidget(self.control_group, 1)
        return container

    def get_joint_display_name(self, joint_index):
        joint_labels = t("arm_joint_labels")
        joint_name = joint_labels[joint_index] if joint_index < len(joint_labels) else f"J{joint_index + 1}"
        return f"{self.get_selected_arm_display_name()} {joint_name}"

    def get_selected_arm_display_name(self):
        arm_code = self.get_selected_arm_code()
        if arm_code == "L":
            return t("arm_left_short")
        if arm_code == "R":
            return t("arm_right_short")
        return t("arm_right_short")  # 默认右臂

    def get_selected_arm_code(self):
        code = self.arm_target_combo.currentData()
        if code in {"L", "R"}:
            return code
        return "R"  # 默认右臂

    def _build_motor_state_panel(self):
        group = QGroupBox()
        layout = QVBoxLayout(group)

        self.motor_table = QTableWidget(0, 8)
        self.motor_table.verticalHeader().setVisible(False)
        self.motor_table.setMinimumWidth(0)
        self.motor_table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        layout.addWidget(self.motor_table, 1)

        # 按钮行
        button_row = QHBoxLayout()
        button_row.setSpacing(10)

        self.btn_one_click_check = QPushButton()
        self.btn_toggle_monitor = QPushButton()

        button_row.addWidget(self.btn_one_click_check)
        button_row.addWidget(self.btn_toggle_monitor)
        button_row.addStretch(1)

        layout.addLayout(button_row)

        return group

    def _build_right_log_panel(self):
        panel = QWidget(self)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.output_label = QLabel()
        self.output_label.setFixedHeight(self.left_tabs.tabBar().sizeHint().height())
        self.output_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self.output_label)

        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setMinimumWidth(0)
        layout.addWidget(self.log_output, 1)
        return panel

    def retranslate_ui(self):
        self.setWindowTitle(t("window_title"))

        self.menu_language.setTitle(t("menu_language"))
        self.menu_help.setTitle(t("menu_help"))

        self.action_chinese.setText(t("action_lang_zh"))
        self.action_english.setText(t("action_lang_en"))
        self.action_japanese.setText(t("action_lang_ja"))
        self.action_russian.setText(t("action_lang_ru"))
        self.action_about.setText(t("action_about"))

        self.btn_start_can.setText(t("btn_start_can"))
        self.btn_stop_can.setText(t("btn_stop_can"))
        self.btn_check_can.setText(t("btn_check_can"))
        for index, tab_key in enumerate(self._tab_keys):
            tab_title = t(tab_key)
            self.left_tabs.setTabText(index, tab_title)
            if tab_key in self._placeholder_labels:
                self._placeholder_labels[tab_key].setText(t("placeholder_content", name=tab_title))

        self.power_group.setTitle(t("group_motor_enable"))
        self.btn_enable_arm.setText(t("btn_enable"))
        self.btn_disable_arm.setText(t("btn_disable"))

        self.zero_group.setTitle(t("group_motor_zero"))
        self.btn_set_zero_arm.setText(t("btn_set_zero"))
        self.btn_go_zero_arm.setText(t("btn_go_zero"))

        self.control_group.setTitle(t("group_motor_control"))
        self.label_speed.setText(t("label_speed"))
        self.label_arm_target.setText(t("label_arm_target"))

        combo_index = self.arm_target_combo.currentIndex()
        self.arm_target_combo.blockSignals(True)
        self.arm_target_combo.clear()
        self.arm_target_combo.addItem(t("arm_left_title"), "L")
        self.arm_target_combo.addItem(t("arm_right_title"), "R")
        self.arm_target_combo.setCurrentIndex(combo_index if combo_index >= 0 else 1)
        self.arm_target_combo.blockSignals(False)

        joint_labels = t("arm_joint_labels")
        for idx, label in enumerate(self.joint_name_labels):
            if idx < len(joint_labels):
                label.setText(joint_labels[idx])
        for _, _, value_label, _ in self.joint_rows:
            value_label.setText("--")  # 初始化为未知
        self.btn_test_all_motors.setText(t("btn_test_all_motors"))

        self.state_panel.setTitle(t("group_motor_status"))
        self.motor_table.setHorizontalHeaderLabels(t("motor_headers"))
        self.btn_one_click_check.setText(t("btn_one_click_check"))
        self.btn_toggle_monitor.setText(t("btn_start_monitor"))

        self.label_chassis_power_title.setText(t("group_chassis_enable"))
        self.btn_chassis_enable.setText(t("btn_enable"))
        self.btn_chassis_disable.setText(t("btn_disable"))
        self.btn_chassis_estop.setText(t("btn_chassis_estop"))
        self._update_chassis_connect_button_text()
        self.btn_chassis_stop.setText(t("btn_chassis_stop"))
        self._update_chassis_view_toggle_button_text()

        self.label_chassis_um_title.setText(t("group_chassis_um_motors"))
        self.label_chassis_rs_title.setText(t("group_chassis_rs_motors"))
        module_cn = {
            "FL": t("chassis_module_FL"),
            "FR": t("chassis_module_FR"),
            "BL": t("chassis_module_BL"),
            "BR": t("chassis_module_BR"),
        }
        driving_ids = {"FL": 1, "FR": 2, "BL": 3, "BR": 4}
        steering_ids = {"FL": 5, "FR": 6, "BL": 7, "BR": 8}
        if self.controller and getattr(self.controller, "chassis_controller", None):
            ch = self.controller.chassis_controller.chassis
            if ch:
                for name in ("FL", "FR", "BL", "BR"):
                    cfg = ch.modules.get(name)
                    if cfg:
                        driving_ids[name] = cfg.driving_id
                        steering_ids[name] = cfg.steering_id
        for name, ctrl in getattr(self, "chassis_um_controls", {}).items():
            ctrl["title"].setText(
                t("chassis_motor_um_label", module=module_cn.get(name, name), id=driving_ids.get(name, ""))
            )
            ctrl["btn_enable"].setText(t("btn_enable"))
            ctrl["btn_disable"].setText(t("btn_disable"))
            ctrl["label_speed"].setText(t("label_chassis_motor_speed"))
            ctrl["spin_speed"].setSuffix(" RPM")
            ctrl["btn_start"].setText(t("btn_chassis_um_start"))
            ctrl["btn_stop"].setText(t("btn_chassis_um_stop"))
        for name, ctrl in getattr(self, "chassis_rs_controls", {}).items():
            ctrl["title"].setText(
                t("chassis_motor_rs_label", module=module_cn.get(name, name), id=steering_ids.get(name, ""))
            )
            ctrl["btn_enable"].setText(t("btn_enable"))
            ctrl["btn_disable"].setText(t("btn_disable"))
            ctrl["btn_zero_manual"].setText(t("btn_chassis_zero_manual"))
            ctrl["btn_zero_auto"].setText(t("btn_chassis_zero_auto"))
            ctrl["btn_go_zero"].setText(t("btn_go_zero"))
            ctrl["label_angle"].setText(t("label_chassis_motor_angle"))
            ctrl["spin_angle"].setSuffix(t("suffix_head_step_deg"))
            ctrl["btn_apply_angle"].setText(t("btn_chassis_apply_angle"))

        self.label_chassis_motion_title.setText(t("group_chassis_motion"))
        self.label_chassis_linear_speed.setText(t("label_chassis_linear_speed"))
        self.label_chassis_angular_speed.setText(t("label_chassis_angular_speed"))
        self._update_chassis_linear_speed_label(self.slider_chassis_linear_speed.value())
        self._update_chassis_angular_speed_label(self.slider_chassis_angular_speed.value())
        self.btn_chassis_forward.setText(t("btn_chassis_forward"))
        self.btn_chassis_backward.setText(t("btn_chassis_backward"))
        self.btn_chassis_left.setText(t("btn_chassis_left"))
        self.btn_chassis_right.setText(t("btn_chassis_right"))
        self.btn_chassis_rotate_left.setText(t("btn_chassis_rotate_left"))
        self.btn_chassis_rotate_right.setText(t("btn_chassis_rotate_right"))
        self.btn_chassis_motion_stop.setText(t("btn_chassis_motion_stop"))

        self.chassis_state_panel.setTitle(t("group_chassis_status"))
        self.chassis_table.setHorizontalHeaderLabels(t("chassis_headers"))
        self.btn_chassis_scan.setText(t("btn_chassis_scan"))
        monitor_btn = getattr(self, "btn_chassis_toggle_monitor", None)
        if monitor_btn is not None:
            if getattr(self.controller, "chassis_controller", None) and self.controller.chassis_controller.is_monitoring:
                monitor_btn.setText(t("btn_stop_monitor"))
            else:
                monitor_btn.setText(t("btn_start_monitor"))

        self.label_head_power_title.setText(t("group_head_enable"))
        self.btn_head_enable.setText(t("btn_enable"))
        self.btn_head_disable.setText(t("btn_disable"))
        self.label_head_tool_title.setText(t("group_head_tools"))
        self._update_head_tool_buttons()
        self.btn_head_sync.setText(t("btn_head_check_can"))
        self.label_head_motion_title.setText(t("group_head_motion"))
        self.label_head_step.setText(t("label_head_step"))
        self.spin_head_step.setSuffix(t("suffix_head_step_deg"))
        self.head_joint_yaw.setText(t("head_joint_yaw"))
        self.head_joint_pitch.setText(t("head_joint_pitch"))
        for ctrl in getattr(self, "head_joint_controls", []):
            ctrl["btn_zero_passive"].setText(t("btn_head_zero_manual"))
            ctrl["btn_zero_active"].setText(t("btn_head_zero_auto"))
            ctrl["btn_go_zero"].setText(t("btn_go_zero"))
        self.btn_head_sync.setText(t("btn_one_click_check"))
        self.head_state_panel.setTitle(t("group_head_status"))
        self.head_table.setHorizontalHeaderLabels(t("head_headers"))
        head_monitor = getattr(self, "btn_head_toggle_monitor", None)
        if head_monitor is not None:
            if getattr(self.controller, "head_controller", None) and self.controller.head_controller.is_monitoring:
                head_monitor.setText(t("btn_stop_monitor"))
            else:
                head_monitor.setText(t("btn_start_monitor"))

        self.label_column_power_title.setText(t("group_column_enable"))
        self.btn_column_enable.setText(t("btn_enable"))
        self.btn_column_disable.setText(t("btn_disable"))
        self.label_column_tool_title.setText(t("group_column_tools"))
        self._update_column_tool_buttons()
        self.btn_column_estop.setText(t("btn_column_estop"))
        self.label_column_mode_title.setText(t("group_column_mode"))
        self.btn_column_mode_velocity.setText(t("btn_column_mode_velocity"))
        self.btn_column_mode_position.setText(t("btn_column_mode_position"))
        self.label_column_motion_title = getattr(self, "label_column_motion_title", None)
        if self.label_column_motion_title is not None:
            self.label_column_motion_title.setText(t("group_column_motion"))
        self.label_column_velocity_title.setText(t("group_column_velocity"))
        self.label_column_jog_speed.setText(t("label_column_jog_speed"))
        self.spin_column_jog_speed.setSuffix(t("suffix_column_move_speed"))
        self.btn_column_jog_up.setText(t("btn_column_jog_up"))
        self.btn_column_jog_down.setText(t("btn_column_jog_down"))
        self.label_column_position_title.setText(t("group_column_position"))
        self.label_column_target.setText(t("label_column_target"))
        self.spin_column_target.setSuffix(t("suffix_column_target"))
        self.label_column_move_speed.setText(t("label_column_profile_speed"))
        self.spin_column_move_speed.setSuffix(t("suffix_column_move_speed"))
        self.btn_column_move_to.setText(t("btn_column_move_to"))
        self.btn_column_stop.setText(t("btn_column_stop"))
        self.label_column_homing_title.setText(t("group_column_homing"))
        self.btn_column_set_zero.setText(t("btn_column_set_zero"))
        self.btn_column_return_home.setText(t("btn_column_return_home"))
        self.btn_column_stop_homing.setText(t("btn_column_stop_homing"))
        self.column_state_panel.setTitle(t("group_column_status"))
        self.column_table.setHorizontalHeaderLabels(t("column_headers"))
        self.btn_column_check.setText(t("btn_one_click_check"))
        col_monitor = getattr(self, "btn_column_toggle_monitor", None)
        if col_monitor is not None:
            if getattr(self.controller, "column_controller", None) and self.controller.column_controller.is_monitoring:
                col_monitor.setText(t("btn_stop_monitor"))
            else:
                col_monitor.setText(t("btn_start_monitor"))

        self.output_label.setText(t("label_output"))
        self.output_label.setFixedHeight(self.left_tabs.tabBar().sizeHint().height())
        self._update_theme_toggle_tooltip()

    def _update_chassis_connect_button_text(self):
        connected = False
        if self.controller and getattr(self.controller, "chassis_controller", None):
            connected = self.controller.chassis_controller.is_connected
        self.btn_chassis_connect.setText(
            t("btn_chassis_disconnect") if connected else t("btn_chassis_connect")
        )

    def _update_head_tool_buttons(self):
        connected = False
        if self.controller and getattr(self.controller, "head_controller", None):
            connected = self.controller.head_controller.is_connected
        self.btn_head_connect.setText(t("btn_head_connect"))
        self.btn_head_disconnect.setText(t("btn_head_disconnect"))
        self.btn_head_connect.setEnabled(not connected)
        self.btn_head_disconnect.setEnabled(connected)

    def _update_column_tool_buttons(self):
        connected = False
        if self.controller and getattr(self.controller, "column_controller", None):
            connected = self.controller.column_controller.is_connected
        self.btn_column_connect.setText(t("btn_column_connect"))
        self.btn_column_disconnect.setText(t("btn_column_disconnect"))
        self.btn_column_connect.setEnabled(not connected)
        self.btn_column_disconnect.setEnabled(connected)

    def _update_theme_toggle_tooltip(self):
        if self.current_theme == "light":
            self.btn_theme_toggle.setToolTip(t("theme_tooltip_switch_to_dark"))
        else:
            self.btn_theme_toggle.setToolTip(t("theme_tooltip_switch_to_light"))

    def apply_theme(self, theme_name):
        palette = self._theme_palette(theme_name)
        self._current_palette = palette
        qss_text = self._load_theme_qss()
        texture_dir = Path(__file__).resolve().parent / "texture"
        qss_text = qss_text.replace(
            "{spin_arrow_up}",
            str(texture_dir / "spin_arrow_up.svg"),
        )
        qss_text = qss_text.replace(
            "{spin_arrow_down}",
            str(texture_dir / "spin_arrow_down.svg"),
        )
        for key, value in palette.items():
            qss_text = qss_text.replace(f"{{{key}}}", value)
        self.setStyleSheet(qss_text)
        self.current_theme = theme_name
        target_theme_icon = "dark.png" if theme_name == "light" else "light.png"
        icon_path = Path(__file__).parent / "texture" / target_theme_icon
        self.btn_theme_toggle.setIcon(QIcon(str(icon_path)))
        self._update_theme_toggle_tooltip()

    def theme_color(self, key, fallback=""):
        return getattr(self, "_current_palette", {}).get(key, fallback)

    def _load_theme_qss(self):
        qss_path = Path(__file__).resolve().parent.parent / "config" / "theme.qss"
        raw = qss_path.read_text(encoding="utf-8")
        # Strip palette comment blocks before returning QSS text
        return re.sub(r"/\*\s*\[palette:[^\]]+\].*?\[/palette:[^\]]+\]\s*\*/", "", raw, flags=re.DOTALL)

    def _theme_palette(self, theme_name):
        qss_path = Path(__file__).resolve().parent.parent / "config" / "theme.qss"
        raw = qss_path.read_text(encoding="utf-8")
        pattern = rf"/\*\s*\[palette:{re.escape(theme_name)}\](.*?)\[/palette:{re.escape(theme_name)}\]\s*\*/"
        match = re.search(pattern, raw, re.DOTALL)
        if not match:
            return {}
        palette = {}
        for line in match.group(1).splitlines():
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                key, _, value = line.partition("=")
                palette[key.strip()] = value.strip()
        return palette


class OpenFlexMainWindow(QMainWindow):
    """Standalone host retained for the original manager entry point."""

    def __init__(self):
        super().__init__()
        self.resize(1200, 820)
        self.motor_page = MotorManagementPage()
        self.setCentralWidget(self.motor_page)
        self.setWindowTitle(self.motor_page.windowTitle())
        self.setWindowIcon(self.motor_page.windowIcon())

    @property
    def controller(self):
        return self.motor_page.controller

    @controller.setter
    def controller(self, controller):
        self.motor_page.controller = controller

    def closeEvent(self, event):
        self.motor_page.shutdown()
        event.accept()
