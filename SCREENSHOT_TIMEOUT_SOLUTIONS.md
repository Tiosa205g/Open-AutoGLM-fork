# 截图超时问题诊断与解决方案

## 问题现象
```
Screenshot error: Command '['adb', 'shell', 'screencap', '-p', '/sdcard/tmp.png']' timed out after 10 seconds
```

## 可能原因

即使数据线始终连接，仍可能出现超时，主要原因包括：

### 1. **设备性能问题**
- 设备 CPU 使用率过高（其他应用占用资源）
- RAM 不足，系统需要垃圾回收
- 存储空间不足或磁盘 I/O 缓慢
- 系统陷入卡顿状态

### 2. **ADB 连接问题**
- ADB 连接不稳定（虽然仍连接状态）
- USB 总线带宽限制
- 驱动程序问题导致通信延迟
- ADB daemon 进程缓慢响应

### 3. **屏幕捕获操作延迟**
- 屏幕内容复杂，编码耗时
- 分辨率过高（如 4K 屏幕）
- GPU 繁忙导致帧缓冲区锁定延迟
- 某些应用在录屏时故意延迟

### 4. **网络 ADB（WiFi 连接）**
- WiFi 信号不稳定，丢包导致重传
- 网络延迟累积
- 设备功耗模式降低网络优先级

### 5. **系统级限制**
- Android 安全机制（某些系统拒绝快速连续截图）
- SELinux 权限检查导致延迟
- 某些 ROM 的截图速度本身较慢

## 已实现的解决方案

### ✅ 1. 动态超时配置（30秒）
```python
# 配置文件: phone_agent/config/timing.py
screencap_timeout: float = 30.0  # 改为 30 秒（原为 10 秒）
```

**环境变量控制：**
```bash
# Windows PowerShell
$env:PHONE_AGENT_SCREENCAP_TIMEOUT = "45"

# Linux/Mac
export PHONE_AGENT_SCREENCAP_TIMEOUT=45
```

### ✅ 2. 自动重试机制
- 失败时自动重试最多 2 次
- 重试间隔 1 秒，避免持续失败
- 提供详细重试日志

```python
max_retries: int = 2  # 最多重试 2 次
```

### ✅ 3. 分离 pull 超时
```python
pull_timeout: float = 10.0  # 从设备拉取文件的独立超时
```

### ✅ 4. 更好的错误处理
- 区分超时和其他错误
- 详细的错误日志记录
- 优雅降级为黑色占位图

## 使用方法

### 方法 1: 修改配置文件（推荐）
编辑 `phone_agent/config/timing.py`：
```python
@dataclass
class ScreenshotTimingConfig:
    screencap_timeout: float = 45.0  # 调整为你的设备需要的时间
    pull_timeout: float = 15.0
    max_retries: int = 3
```

### 方法 2: 环境变量（临时调整）
```bash
# Windows
set PHONE_AGENT_SCREENCAP_TIMEOUT=45
set PHONE_AGENT_PULL_TIMEOUT=15
set PHONE_AGENT_SCREENSHOT_MAX_RETRIES=3

# Linux/Mac
export PHONE_AGENT_SCREENCAP_TIMEOUT=45
export PHONE_AGENT_PULL_TIMEOUT=15
export PHONE_AGENT_SCREENSHOT_MAX_RETRIES=3
```

### 方法 3: 代码调用
```python
from phone_agent.config.timing import update_timing_config, ScreenshotTimingConfig

# 创建自定义配置
custom_screenshot = ScreenshotTimingConfig(
    screencap_timeout=60.0,  # 60 秒
    pull_timeout=20.0,
    max_retries=3
)

# 更新全局配置
update_timing_config(screenshot=custom_screenshot)
```

## 进一步诊断步骤

如果仍然超时，按顺序尝试以下步骤：

### 1. 检查 ADB 连接状态
```bash
adb devices
adb shell getprop ro.build.version.release  # 检查 Android 版本
```

### 2. 手动测试截图命令
```bash
# 直接在设备上截图（不通过 ADB）
adb shell screencap -p /sdcard/test.png
adb pull /sdcard/test.png  # 测量拉取速度

# 测量耗时
time adb shell screencap -p /sdcard/test.png
time adb pull /sdcard/test.png
```

### 3. 检查设备资源占用
```bash
adb shell top -n 1  # 查看 CPU 和内存使用
adb shell df        # 检查存储空间
```

### 4. 如果使用 WiFi ADB，改用 USB
```bash
adb usb  # 切换回 USB 连接
```

### 5. 重启 ADB 服务
```bash
adb kill-server
adb start-server
adb devices
```

## 推荐的超时参数

根据不同场景推荐配置：

| 场景 | screencap_timeout | pull_timeout | 说明 |
|------|------------------|-------------|------|
| **USB 连接，新设备** | 15 秒 | 5 秒 | 快速连接 |
| **USB 连接，旧设备** | 30 秒 | 10 秒 | 标准配置（当前默认）|
| **WiFi 连接** | 45 秒 | 15 秒 | 网络延迟大 |
| **高分辨率设备** | 60 秒 | 20 秒 | 4K 屏幕 |

## 监控和日志

启用详细日志以诊断问题：
```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

日志输出示例：
```
Screenshot timeout (attempt 1/3), retrying...
Screenshot timeout (attempt 2/3), retrying...
Screenshot error: Command '...' timed out after 30 seconds
```

## 总结

该修复通过以下方式改进了截图超时问题：
1. ✅ 增加默认超时时间（10秒 → 30秒）
2. ✅ 添加自动重试机制（最多 3 次尝试）
3. ✅ 支持动态配置超时时间
4. ✅ 改进错误处理和日志记录
5. ✅ 允许根据设备和网络条件调整参数
