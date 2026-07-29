# openflex_manager

[English](./README.md) | 中文

---

![封面](./image/cover.gif)

基于 PySide6 和 `openflex_driver` 的 OpenFlex 整机硬件管理界面。

## 概述

`openflex_manager` 是面向调试、标定和维护人员的桌面控制工具。它通过 SocketCAN 直接连接 OpenFlex 的双臂、头部、升降台和四轮转向底盘，提供 CAN 接口管理、电机使能与失能、零点标定、手动运动、状态查询和实时监控等功能。

本目录当前以 Python 源码应用的形式运行，不是可由 `colcon` 构建或通过 `ros2 run` 启动的 ROS 2 包。

## 功能

- **CAN 总线管理**：启动、关闭和检查 CAN 接口，也可在状态对话框中单独操作某个接口
- **头部控制**：控制偏航和俯仰电机，使能/失能、主动/被动设零、回零、步进运动和实时监控
- **双臂控制**：按左臂、右臂或双臂执行使能/失能、设零、MIT 回零、关节步进和电机状态检查
- **升降台控制**：支持速度/位置模式、点动、目标位置运动、快速停止、设零、回原点和状态监控
- **底盘控制**：支持整车前后/横移/旋转、线速度与角速度调节，以及四个转向和驱动模块的独立控制
- **底盘标定与诊断**：电机扫描、转向轮设零/回零、急停和实时状态查询
- **界面设置**：支持中文、英文、日文和俄文，提供亮色/暗色主题及分级日志输出
- **资源清理**：窗口关闭时停止监控和运动，并关闭各硬件连接

## CAN 配置

默认映射来自 [`config/app_settings.yaml`](./config/app_settings.yaml)：

| 接口 | 波特率 | 功能 |
|------|--------|------|
| `can0` | 1 Mbps | 右臂（Robstride） |
| `can1` | 1 Mbps | 左臂（Robstride） |
| `can2` | 1 Mbps | 头部偏航/俯仰（RS00，默认 ID 1、2） |
| `can3` | 1 Mbps | 升降台（CANopen，默认节点 ID 16） |
| `can4` | 1 Mbps | 底盘驱动轮（UM10540，默认节点 ID 1-4） |
| `can5` | 1 Mbps | 底盘转向轮（RS 系列，默认电机 ID 5-8） |

如实际接线不同，请在启动前修改配置文件。应用不会在初始化 `Robot` 时自动启动 CAN，需在界面中点击“启动 CAN”。

## 使用方法

```bash
# 进入应用目录
cd ~/openflex_all/openflex_ws/src/openflex_integrated/openflex_manager

# 使用安装了依赖和 openflex_driver 的 Python 环境启动
python3 main.py
```

启动后的建议操作顺序：

1. 确认机器人周围无人员和障碍物，底盘轮离地或有足够安全空间。
2. 点击“启动 CAN”，再通过“检查 CAN”确认所需接口均已启动。
3. 进入对应子系统页面，检查电机状态后再使能电机。
4. 完成调试后先停止运动并失能电机，再关闭应用和 CAN 接口。

## 配置

主要设置保存在 [`config/app_settings.yaml`](./config/app_settings.yaml)，修改后需重启应用。常用配置包括：

| 配置项 | 说明 |
|--------|------|
| `language`、`theme` | 界面语言和主题 |
| `can_driver` | CAN 适配器驱动，支持值由 `openflex_driver` 决定，例如 `kcan`、`peak_usb` |
| `right_arm_can`、`left_arm_can` | 左右臂 CAN 接口 |
| `head_enabled`、`head_can`、`head_motor_ids` | 头部启用状态、接口和电机 ID |
| `column_enabled`、`column_can`、`column_node_id` | 升降台启用状态、接口和节点 ID |
| `steering_can`、`driving_can` | 底盘转向与驱动 CAN 接口 |
| `*_limit*`、`*_max_*` | 各子系统的运动和输入限制 |
| `sudo_password` | CAN 接口操作使用的 sudo 密码；如需配置，请限制文件权限且不要提交真实密码 |

`config/translations/` 保存四种语言的 YAML 文案，`config/theme.qss` 保存界面主题样式。

## 目录结构

```text
openflex_manager/
├── main.py                 # 应用入口
├── config/                 # 应用设置、主题和翻译
├── controllers/            # CAN、双臂、头部、升降台和底盘控制逻辑
├── ui/                     # 主窗口、状态对话框和界面资源
├── utils/                  # 国际化、设置持久化和输入限制
├── scripts/                # 硬件诊断、标定和测试脚本
└── image/                  # 文档图片
```

## 前置条件

- Linux 系统及 SocketCAN 支持
- Python 3.10 或兼容版本
- Python 包：`PySide6`、`PyYAML`、`python-can`
- `openflex_driver` Python 包，且应与本应用的头部、升降台和底盘 API 版本匹配
- 已正确安装并识别的 CAN 适配器驱动
- 启动/关闭 CAN 网络接口所需的 sudo 权限
- 与配置文件一致的 OpenFlex 电机、CAN 接口及节点 ID

## 安全提示

该应用会直接使能电机并发送运动指令。设零、回零、点动和底盘运动前必须确认机械限位、急停装置和作业空间安全。不要仅依赖图形界面的“急停”按钮替代硬件急停。首次调试或修改运动限制后，应使用低速并逐个子系统验证。

## 许可证

本作品采用知识共享 署名-非商业性使用-相同方式共享 4.0 国际许可协议（CC BY-NC-SA 4.0）进行许可。

版权所有 (c) 2026 成都长数机器人有限公司 (Chengdu Changshu Robot Co., Ltd.)

详情请参阅 [LICENSE](./LICENSE) 文件或访问：<http://creativecommons.org/licenses/by-nc-sa/4.0/>

## 致谢

本项目是 OpenArmX 机器人平台生态系统的一部分，面向协作机器人领域的研究、调试和工业应用。

---

## 联系我们

### 成都长数机器人有限公司

**Chengdu Changshu Robotics Co., Ltd.**

| 联系方式 | 信息 |
|---------|------|
| 邮箱 | [openarmrobot@gmail.com](mailto:openarmrobot@gmail.com) |
| 电话/微信 | +86-17746530375 |
| 官网 | <https://openarmx.com/> |
| 文档 | <http://docs.openarmx.com/> |
| 地址 | 天津经济技术开发区西区新业八街11号华诚机械厂 |
| 联系人 | 王先生 |
