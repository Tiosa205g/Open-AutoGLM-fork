# AI 模型 API 超时问题解决方案

## 问题现象
```
httpcore.ConnectTimeout: _ssl.c:983: The handshake operation timed out
openai.APITimeoutError: Request timed out.
```

## 错误分析

这是 **网络连接到 AI 模型服务器** 的超时问题，不是截图或设备问题。

### 超时发生的阶段

1. **SSL 握手超时** (`_ssl.c:983: The handshake operation timed out`)
   - 建立 HTTPS 连接时 SSL/TLS 握手失败
   - 通常由网络延迟、防火墙、代理配置问题引起

2. **API 请求超时** (`openai.APITimeoutError`)
   - OpenAI 客户端等待响应超时
   - 可能原因：模型推理时间长、网络不稳定、服务器负载高

## 常见原因

### 1. **网络连接问题** ⚠️
- 网络不稳定或延迟高
- 防火墙或代理配置阻止连接
- DNS 解析慢
- 跨境网络连接问题

### 2. **代理配置问题**
```python
# 如果使用代理但配置不当
httpx 使用系统代理或环境变量 HTTP_PROXY/HTTPS_PROXY
```

### 3. **模型服务器问题**
- 服务器响应慢或过载
- 模型推理时间过长
- 服务器临时不可用

### 4. **超时设置过短**
- 原代码 **没有设置超时时间**（使用 httpx 默认值）
- 默认超时可能只有 5-10 秒，对于 AI 推理不够

## 已实施的解决方案 ✅

### 1️⃣ **配置化超时设置**

在 `phone_agent/config/timing.py` 中新增：

```python
@dataclass
class ModelTimingConfig:
    # 连接超时：30 秒（建立 TCP/SSL 连接）
    connect_timeout: float = 30.0
    
    # 读取超时：300 秒（5 分钟，等待模型推理响应）
    read_timeout: float = 300.0
    
    # 写入超时：30 秒（发送请求数据）
    write_timeout: float = 30.0
    
    # 连接池超时：30 秒（从连接池获取连接）
    pool_timeout: float = 30.0
    
    # 最大重试次数：3 次
    max_retries: int = 3
    
    # 重试间隔：2 秒
    retry_delay: float = 2.0
```

### 2️⃣ **自动重试机制**

- **连接超时**和**API 超时**自动重试最多 3 次
- 每次重试间隔 2 秒
- 提供详细的重试日志：
  ```
  ⚠️ Model request timeout (attempt 1/3), retrying in 2s...
  ⚠️ Model request timeout (attempt 2/3), retrying in 2s...
  ```

### 3️⃣ **优化的 HTTP 客户端配置**

```python
# 配置连接池和超时
http_client = httpx.Client(
    timeout=timeout_config,
    limits=httpx.Limits(
        max_connections=10,        # 最大连接数
        max_keepalive_connections=5  # 保持活跃连接数
    ),
)
```

### 4️⃣ **错误分类处理**

区分不同类型的错误：
- `APITimeoutError`: API 请求超时
- `APIConnectionError`: 连接错误
- `RemoteProtocolError`: 流式传输中断

## 使用方法

### 方法 1: 环境变量（推荐用于临时调整）

```bash
# Windows PowerShell
$env:PHONE_AGENT_MODEL_CONNECT_TIMEOUT = "60"    # 连接超时 60 秒
$env:PHONE_AGENT_MODEL_READ_TIMEOUT = "600"      # 读取超时 10 分钟
$env:PHONE_AGENT_MODEL_MAX_RETRIES = "5"         # 最多重试 5 次
$env:PHONE_AGENT_MODEL_RETRY_DELAY = "3"         # 重试间隔 3 秒

# Linux/Mac
export PHONE_AGENT_MODEL_CONNECT_TIMEOUT=60
export PHONE_AGENT_MODEL_READ_TIMEOUT=600
export PHONE_AGENT_MODEL_MAX_RETRIES=5
export PHONE_AGENT_MODEL_RETRY_DELAY=3
```

### 方法 2: 修改配置文件

编辑 `phone_agent/config/timing.py`：

```python
@dataclass
class ModelTimingConfig:
    connect_timeout: float = 60.0   # 增加到 60 秒
    read_timeout: float = 600.0      # 增加到 10 分钟
    max_retries: int = 5             # 增加重试次数
    retry_delay: float = 3.0         # 延长重试间隔
```

### 方法 3: 代码中动态设置

```python
from phone_agent.config.timing import update_timing_config, ModelTimingConfig

# 创建自定义配置
custom_model_timing = ModelTimingConfig(
    connect_timeout=60.0,
    read_timeout=600.0,
    max_retries=5,
    retry_delay=3.0
)

# 应用配置
update_timing_config(model=custom_model_timing)
```

## 诊断步骤

### 1. 检查网络连接

```bash
# 测试到模型服务器的连接
ping your-model-server.com

# 或使用 curl 测试
curl -I https://your-model-server.com/v1
```

### 2. 检查代理设置

```bash
# Windows
echo %HTTP_PROXY%
echo %HTTPS_PROXY%

# Linux/Mac
echo $HTTP_PROXY
echo $HTTPS_PROXY
```

如果使用代理，确保代理配置正确。

### 3. 测试 API 响应时间

```python
import httpx
import time

start = time.time()
try:
    response = httpx.get("https://your-model-server.com/v1", timeout=30.0)
    print(f"响应时间: {time.time() - start:.2f}s")
    print(f"状态码: {response.status_code}")
except Exception as e:
    print(f"错误: {e}")
```

### 4. 查看详细日志

启用详细日志模式运行：
```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

## 推荐配置

根据不同场景的推荐超时设置：

| 场景 | connect_timeout | read_timeout | max_retries | 说明 |
|------|----------------|--------------|-------------|------|
| **本地模型服务** | 10s | 120s | 2 | 本地网络快速 |
| **稳定内网** | 30s | 300s | 3 | 默认配置 |
| **公网/跨境** | 60s | 600s | 5 | 网络延迟大 |
| **不稳定网络** | 90s | 900s | 7 | 频繁断线环境 |

## 代理配置示例

### 如果需要通过代理访问模型 API

#### 方法 1: 环境变量

```bash
# Windows
set HTTP_PROXY=http://proxy.company.com:8080
set HTTPS_PROXY=http://proxy.company.com:8080

# Linux/Mac
export HTTP_PROXY=http://proxy.company.com:8080
export HTTPS_PROXY=http://proxy.company.com:8080
```

#### 方法 2: 修改 client.py

```python
# 在 ModelClient.__init__ 中
http_client = httpx.Client(
    timeout=timeout_config,
    proxy="http://proxy.company.com:8080",  # 添加代理
    limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
)
```

## 常见问题 FAQ

### Q1: 为什么连接超时 30 秒还不够？

**A**: 如果网络环境差（如跨境连接、移动网络），SSL 握手可能需要更长时间。建议：
- 检查网络质量
- 增加 `connect_timeout` 到 60-90 秒
- 考虑使用代理或 VPN

### Q2: read_timeout 应该设置多少？

**A**: 取决于模型推理时间：
- 小模型（< 10B 参数）：120-300 秒
- 大模型（> 10B 参数）：300-600 秒
- 多模态模型（视觉）：600-900 秒

### Q3: 重试会不会导致重复请求？

**A**: 不会。只有在请求完全失败（超时或连接错误）时才重试，成功的请求不会重试。

### Q4: 如何禁用重试？

**A**: 设置 `max_retries = 1`（最少 1 次尝试）：
```python
ModelTimingConfig(max_retries=1)
```

## 总结

此修复通过以下方式解决 API 超时问题：

✅ **配置化超时**：所有超时参数可通过环境变量或代码配置  
✅ **智能重试**：自动重试连接和超时错误，最多 3 次  
✅ **合理默认值**：  
  - 连接超时 30 秒（建立连接）  
  - 读取超时 300 秒（等待推理）  
  - 3 次重试机会  
✅ **详细日志**：清晰显示重试进度和失败原因  
✅ **灵活配置**：支持不同网络环境的参数调整

如果问题持续，请检查：
1. 网络连接质量
2. 防火墙/代理配置
3. 模型服务器状态
4. 增加超时时间和重试次数
