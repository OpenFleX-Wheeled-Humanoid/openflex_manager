# Controllers 架构说明

## 概述

控制器层采用模块化设计，将不同功能分离到独立的控制器中，便于维护和扩展。

## 架构图

```
controllers/
├── __init__.py              # 导出所有控制器
├── main_controller.py       # 主控制器（入口，协调子控制器）
├── base_controller.py       # 基础功能控制器
├── arm_controller.py        # 双臂控制器
└── ui_controller.py         # UI 控制器
```

## 各控制器职责

### 1. MainController (主控制器)

**职责**: 作为入口，协调各个子控制器，管理核心业务对象（Robot）

**主要功能**:
- 初始化所有子控制器
- 管理 Robot 实例
- 提供统一的 log 接口（委托给 UIController）
- 应用关闭时的资源清理

**关键方法**:
- `__init__(window)` - 初始化主控制器和所有子控制器
- `_initialize_robot()` - 初始化 Robot 实例
- `shutdown()` - 关闭 Robot 连接和清理资源

### 2. BaseController (基础功能控制器)

**职责**: 管理 CAN 总线、遥操作、MoveIt、VR、LeRobot 等基础功能

**主要功能**:
- CAN 总线管理（启动、关闭、检查）
- 单个 CAN 接口控制
- 遥操作功能
- MoveIt 集成
- VR 模式
- LeRobot 数据采集

**关键方法**:
- `start_can()` - 启动所有 CAN 接口
- `stop_can()` - 关闭所有 CAN 接口
- `check_can()` - 检查 CAN 状态并显示对话框
- `_start_single_can(interface, dialog)` - 启动单个 CAN 接口
- `_stop_single_can(interface, dialog)` - 关闭单个 CAN 接口
- `start_teleop()` - 启动全身遥操作
- `start_moveit()` - 启动 MoveIt
- `enter_vr()` - 进入 VR 模式
- `start_lerobot()` - 启动 LeRobot 数据采集

### 3. ArmController (双臂控制器)

**职责**: 管理双臂电机的使能、失能、零点、运动控制等功能

**主要功能**:
- 电机使能/失能
- 零点设置和回零
- 电机测试
- 关节控制

**关键方法**:
- `enable_motors()` - 使能电机
- `disable_motors()` - 失能电机
- `set_zero()` - 设定零点
- `go_zero()` - 回零
- `test_all_motors()` - 测试所有电机
- `check_motor_status()` - 检查电机状态
- `move_joint_minus(joint_index)` - 关节反向调节
- `move_joint_plus(joint_index)` - 关节正向调节

### 4. UIController (UI 控制器)

**职责**: 管理语言切换、主题切换、日志输出等 UI 相关功能

**主要功能**:
- 多语言切换
- 主题切换（亮色/暗色）
- 日志输出
- 设置持久化

**关键方法**:
- `set_language(language_code, persist=True)` - 设置语言
- `toggle_theme()` - 切换主题
- `log(message, level="INFO")` - 输出日志
- `_apply_saved_settings()` - 应用保存的设置

## 使用方式

### 在 main.py 中初始化

```python
from controllers import MainController

app = QApplication(sys.argv)
window = OpenFlexMainWindow()
controller = MainController(window)
window.controller = controller
window.show()
return app.exec()
```

### 子控制器之间的通信

子控制器通过 `main_controller` 引用访问其他控制器：

```python
# 在 ArmController 中访问 log 方法
self.log = main_controller.log  # 实际上是 UIController.log

# 在 BaseController 中访问 Robot 实例
robot = main_controller.robot
```

## 扩展指南

### 添加新功能

1. **确定功能归属**: 判断新功能应该属于哪个控制器
   - CAN、遥操、MoveIt、VR、LeRobot → `BaseController`
   - 电机控制、运动控制 → `ArmController`
   - UI 相关 → `UIController`
   - 新的独立模块 → 创建新的控制器

2. **在对应控制器中添加方法**:
   ```python
   def new_feature(self):
       """新功能描述"""
       self.log("执行新功能", "INFO")
       # 实现逻辑
   ```

3. **在 `_wire_signals()` 中连接信号**:
   ```python
   def _wire_signals(self):
       # ... 现有信号连接
       self.window.btn_new_feature.clicked.connect(self.new_feature)
   ```

### 创建新的控制器

如果需要添加大量新功能（如头部控制、升降台控制、底盘控制），建议创建新的控制器：

1. **创建新文件** `controllers/head_controller.py`:
   ```python
   class HeadController:
       def __init__(self, main_controller):
           self.main = main_controller
           self.window = main_controller.window
           self.robot = main_controller.robot
           self.log = main_controller.log
           self._wire_signals()

       def _wire_signals(self):
           # 连接信号
           pass

       def control_head(self):
           # 头部控制逻辑
           pass
   ```

2. **在 MainController 中初始化**:
   ```python
   from .head_controller import HeadController

   class MainController:
       def __init__(self, window):
           # ... 现有初始化
           self.head_controller = HeadController(self)
   ```

3. **在 `__init__.py` 中导出**:
   ```python
   from .head_controller import HeadController

   __all__ = [
       'MainController',
       'BaseController',
       'ArmController',
       'UIController',
       'HeadController',  # 新增
   ]
   ```

## 优势

✓ **职责分离清晰**: 每个控制器专注于特定功能，代码易于理解
✓ **易于维护**: 修改某个功能只需修改对应控制器，不影响其他部分
✓ **易于扩展**: 添加新功能只需在对应控制器中添加方法，或创建新控制器
✓ **避免臃肿**: 单个文件不会过于庞大，保持代码清晰
✓ **独立测试**: 每个控制器可以独立测试
✓ **团队协作**: 不同开发者可以同时修改不同控制器，减少冲突

## 注意事项

1. **初始化顺序**: UIController 必须先初始化，因为其他控制器需要使用 log 方法
2. **循环引用**: 避免子控制器之间直接引用，应通过 main_controller 访问
3. **Robot 引用**: Robot 实例在 MainController 中管理，子控制器通过 `main_controller.robot` 访问
4. **信号连接**: 所有信号连接应在 `_wire_signals()` 方法中完成，便于管理
