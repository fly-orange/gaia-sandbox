# gaia-sandbox

所有 GAIA 题目共用 **一个常驻 OpenHands SDK 服务进程**；每题建立独立
Conversation 和 Docker 沙箱。沙箱仅运行工具，不运行 OpenHands Agent Server。
一个题目结束后销毁它的沙箱，服务进程继续处理下一题。

这是 SDK 驱动的自定义 Agent HTTP 服务，不是原版 `openhands-agent-server` REST
API 的兼容实现，也不是在一个代理后面隐藏 N 个 Agent Server。

```text
GAIA client（题目、附件；标准答案不发送到服务）
                    │ HTTP
                    ▼
常驻服务：一个 PID / 一个 asyncio event loop
  ├─ Conversation A / OpenHands Agent A ──→ Docker A（工具环境）
  ├─ Conversation B / OpenHands Agent B ──→ Docker B（工具环境）
  └─ Conversation C / OpenHands Agent C ──→ Docker C（工具环境）
          │
          └── 共用一个外部 vLLM endpoint
```

共享的是服务进程、SDK 代码和调度器，不是题目历史、LLM metrics 对象或文件系统。
工具目标由服务端绑定，模型参数只有命令，不能选择别的容器 ID。

## 1. 安装（推荐 Linux / WSL2）

要求 Python 3.12+、uv、Linux Docker Engine、已启动且支持 tool calling 的模型服务。
本项目不自动安装 Docker，不自动启动 GPU 推理服务。

```bash
git clone https://github.com/fly-orange/gaia-sandbox.git
cd gaia-sandbox
uv sync --locked --extra data --extra test
cp config.example.toml config.toml
cp .env.example .env
docker build -f docker/sandbox.Dockerfile -t gaia-sandbox:0.1 .
```

在 `.env` 中设置随机 `GAIA_SERVER_TOKEN` 和 `VLLM_API_KEY`。
在 `config.toml` 中设置模型名称、URL 和 GAIA 数据路径。默认绑定 `127.0.0.1:8765`。
源码采用 editable 安装，修改 `src/` 或 `vendor/` 后重启服务即可生效。

**模型 URL 从常驻服务所在机器访问**，不再从每题沙箱访问。因此，vLLM 位于同一
宿主机时应使用 `http://127.0.0.1:8000/v1`，而不是 `host.docker.internal`。
示例模型 ID 仅为配置示例，请换成 vLLM 实际的 served-model-name；本项目不替你选择
模型的 tool-call parser。图片题需模型本身支持视觉输入。

```bash
uv run gaia-sandbox plan
uv run gaia-sandbox doctor
```

## 2. 数据集

支持本地官方布局的 JSONL / Parquet（包括匹配该布局的 ModelScope 下载）：

```text
data/GAIA/2023/validation/metadata.jsonl  或 metadata.parquet
data/GAIA/2023/validation/<附件>
data/GAIA/2023/test/metadata.jsonl        或 metadata.parquet
```

也可以先接受 Hugging Face GAIA 数据集条款，设置 `HF_TOKEN`，再执行：

```bash
uv run gaia-sandbox download
```

`gaia.level=0` 表示所有难度，`gaia.limit=0` 表示所有题。默认仅 3 题、1 worker。
每次请求最多一个附件、20 MiB；超限明确报错，不静默跳过。ZIP 以原文件上传，
由 Agent 在自己的沙箱中解压，不在控制进程解压。标准答案只在评测客户端评分。
test split 没有公开答案，因此 `score/accuracy=null`，不会伪报为 0 分。

## 3. 启动常驻服务，再运行评测

终端 A（保持运行）：

```bash
uv run gaia-sandbox serve
```

终端 B：

```bash
uv run gaia-sandbox run
```

要先测 1 题，将 `gaia.limit=1`。之后更改实验配置时使用新的 `gaia.output_dir`。
例如对比并发 1/2/4/8：分别设置 `gaia.workers`，并保证
`server.max_concurrency` 足够大。不要增加 Uvicorn workers；否则不再是单服务进程。

服务提供带 Bearer Token 认证的 `GET /health` 和 `POST /tasks`。
`/health` 返回 `server_pid/server_id/active/waiting/completed`，可核对不同批次和题目
仍由同一个常驻服务处理。客户端可用 `GAIA_SERVER_URL` 指向另一台受控服务器。

重复执行同一批次时跳过成功完成的题目；失败题重新创建沙箱与 Conversation。
这叫题目级续跑，不是恢复旧 Conversation。limit 在续跑过滤之前应用，不会因为
重复执行 1 题 smoke 而不断选出下一道题。配置、数据、服务源码指纹变更会拒绝混入
同一输出目录。不要让多个评测客户端同时写入同一个输出目录。

## 4. 负载信息

```text
runs/server/<server_id>/
  server-manifest.json        服务参数、PID、源码与配置指纹
  server-metrics.jsonl        整个常驻进程的 CPU 累计时间、RSS、线程数、活跃任务数
  <run_id>/
    request.json             题目与附件名；不含标准答案
    events.jsonl             SDK 事件轨迹与采集时间戳
    sandbox-metrics.jsonl    该题容器 CPU、内存、网络、块 I/O、进程数和阶段
    result.json              答案、LLM metrics、时延、容器 ID 和错误/清理状态
runs/evaluation/
  manifest.json
  output.jsonl
  summary.json
```

记录 queue / initialization / agent / cleanup / total 秒数，以及初始化后与销毁前的
容器 CPU 累计计数。`total_seconds` 不包含排队时间；`request_timeout` 限制 Agent
运行阶段，Docker 操作还有各自 API 超时。初始化/清理时间不可当作纯解题时间。
超时或错误保留轨迹并尝试销毁沙箱；清理失败记录 `cleanup_error`，必须人工检查残留。

服务进程 CPU 是共享总量，并发区间重叠时**不能把各题起止区间的服务 CPU 差分相加**，
也不能冒充准确的单题 CPU 归因。单题沙箱 CPU 可按各自容器统计；服务开销按整批
差分或单并发实验分析。RSS 是进程驻留内存；Docker memory_bytes 是 cgroup 内存
usage，可能包含页缓存，不等同于 RSS。1 秒采样可能漏掉短峰值，可以调整采样间隔。

本版本未集成 GPU/DCGM、vLLM Prometheus 和硬件 perf 计数器。LLM metrics 是 SDK
统计，并不代表实测 GPU 利用率、能耗或显存带宽。可在模型服务器另行采集这些指标，
用时间戳对齐整批实验，但并发动态 batching 下不能把整卡功耗直接归给单题。

## 5. 工具与可比性

Agent 使用 OpenHands SDK 原生推理循环，工具集合固定为沙箱 Bash、Finish、Think。
沙箱预装 Python、requests、文档处理、ffmpeg、OCR 和 Playwright/Chromium。
Agent 可通过 Python 操作浏览器。图片附件直接送入支持视觉的模型。

这里**没有原版 GAIA 的 Tavily MCP 和原版 browser-use 工具集合**；也没有自动
把浏览器截图作为新的视觉 observation 回传模型。首版目的是清晰测量共享服务架构，
不是声称复现原版 GAIA 分数。工具集合、prompt、环境变化都会影响成绩和负载。
公开结果请标注 `gaia-sandbox/sandbox-command`，记录模型、镜像 ID、源码指纹，
勿与原版 OpenHands 得分当作只有部署架构不同的严格 A/B 实验。

## 6. 安全边界

- 不把 Docker socket、控制服务源码、其他题目目录或模型/HF 凭据挂入沙箱。
- 容器非 root、drop ALL capabilities、no-new-privileges、CPU/内存/PID 限额。
- 宿主服务持有 Docker API 权限，属于受信任控制面；只部署在独立测试机，不暴露公网。
- `bridge` 是允许联网的模式，**不是出网隔离或防火墙**。部署机应禁止沙箱访问
  宿主控制端口、其他沙箱、企业内网和云 metadata；离线实验可设置 `network="none"`。
- Docker 不是对恶意多租户的完整安全边界；不要放生产数据。题目能消耗容器磁盘空间，
  当前未配置每容器磁盘配额；建议专用磁盘/VM，并监控磁盘使用量。
- 工具输出在容器内截断，再送到服务；原始日志可能包含题目敏感数据，`runs/` 不提交。
- 不使用用户技能/项目技能/全局视觉工具。新增工具必须通过绑定的 sandbox 执行，
  不要加本地 Terminal/FileEditor/MCP subprocess 绕过边界。
- 正常结束和异常会清理容器；kill -9/宿主崩溃可能留下容器。只按
  `gaia.role=sandbox` 和对应 `gaia.run_id` 检查清理，禁止全局 docker prune。

## 7. 版本管理与 GitHub

`vendor/software-agent-sdk/` 是普通源码目录，不是 git submodule，没有内部 `.git`，
没有 `.upstream`。来源 SHA、许可证和本地补丁见 [vendor/PROVENANCE.md](vendor/PROVENANCE.md)。
`uv.lock` 固定依赖解析结果，SDK 使用仓内源码。修改 SDK 和平台代码可放在同一个 commit。

```bash
git status --short
git diff -- src vendor
git add src tests vendor README.md pyproject.toml uv.lock
git commit -m "Update shared Agent server and SDK"
git push -u origin main
```

不提交 `.env`、`config.toml`、数据集、运行结果、虚拟环境或缓存。
请先确认 GAIA 数据许可；数据集不能随代码一起上传。

## 8. 测试与验收

```bash
uv run pytest -q
uv run ruff check src tests
# 需要 Linux Docker 和已构建的镜像：
RUN_DOCKER_TESTS=1 uv run pytest -m docker -q
```

默认测试使用真实 SDK，但模拟 LLM 回复和 Docker。它们验证共享 PID、独立会话、
工具定向、并发限制、超时清理、鉴权、附件路径和评分。不能替代真实模型/容器验收。
完整验收：先通过 Docker isolation 测试，再通过 doctor，跑一题，再跑两题并发，
核对 server_id/server_pid 一致、container_id 不同，以及题后容器已回收。

本地 Python 3.12 + 真实 SDK 测试可运行；当前开发机没有 Docker，也没有已配置的
模型服务，因此不能宣称已跑通真实 GAIA。参见 [VALIDATION.md](VALIDATION.md)。
