# Deep Research 并发压测

压测脚本把 Deep Research 当作普通 SSE 服务访问，不导入业务 Agent，也不修改
业务流程。Locust 页面中的主要指标是：

```text
SSE /api/research/stream [workflow]
```

它表示从请求发出到收到 `workflow_done` 的完整耗时，而
`/api/research/stream [connect]` 只表示 HTTP 建连和响应头耗时。

## 安装

```bash
cd deep-research-agent
.venv/bin/pip install -r load_tests/requirements.txt
```

## 启动后端

```bash
.venv/bin/python -m uvicorn backend.api.app:app \
  --app-dir src --host 127.0.0.1 --port 8000
```

## 低并发阶梯压测

Deep Research 会真实调用 LLM 和搜索服务，建议从 1、2、4 并发逐级测试：

```bash
export LOAD_TEST_ONCE_PER_USER=true

.venv/bin/locust -f load_tests/locustfile.py \
  --host http://127.0.0.1:8000 \
  --headless -u 1 -r 1 -t 20m \
  --csv load_tests/results/users_1
```

把 `-u 1` 依次改成 `2`、`4`，每个虚拟用户只执行一次完整研究。任务完成后
Locust 用户会停止；`-t` 只是防止异常情况下无限等待。

也可以启动 Web 控制台：

```bash
.venv/bin/locust -f load_tests/locustfile.py \
  --host http://127.0.0.1:8000
```

浏览器访问 `http://127.0.0.1:8089`。

## 可选环境变量

```text
LOAD_TEST_BACKEND=duckduckgo
LOAD_TEST_TOPIC=用于固定三轮压测工作量的单个研究问题
LOAD_TEST_TOPICS_FILE=benchmarks/cases.json
LOAD_TEST_READ_TIMEOUT_SECONDS=1200
LOAD_TEST_WAIT_MIN_SECONDS=1
LOAD_TEST_WAIT_MAX_SECONDS=3
LOAD_TEST_ONCE_PER_USER=true
```

## 重点观察

- Workflow 请求数、失败率；
- P50、P95、P99；
- 每秒请求数；
- `workflow_failed`、`api_error` 和连接中断；
- 1、2、4 并发下延迟和失败率的变化。

真实模型具有费用、限流和网络波动。不要直接使用高并发；一次只改变一个变量，
并保存 Locust CSV，才能进行可靠的优化前后对比。
