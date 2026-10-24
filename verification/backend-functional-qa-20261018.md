# 后端功能与故障恢复复核

日期：2026-10-18。范围：公开行情输入、盘口恢复调度、恢复状态投影、行情 HTTP/SSE 端点。未读取私有凭据或账户，未调用交易 API，未重启生产服务。

## 已修复的问题

1. **未来 WS 事件污染排序水位。** 之前五类事件（指数、标记、盘口、24 小时统计、成交）可以带未来 60 秒的 `E`，用真实接收时间刷新字段并把排序水位推到未来。修复后按实际接收时间、已经核验的交易所时钟偏移以及 2 秒容差检查；成交 `T` 同样检查。盘口合并队列在写入自身水位之前也检查，避免缓存虽拒绝、队列仍丢弃后续正常盘口。
2. **缺少盘口序列号会清空已知序列号。** 收到缺少 `u` 的更新后，缓存曾将已知序列号置空，下一条低序列号盘口可以覆盖。修复后保留已经观察到的序列保护。
3. **WS 恢复后仍显示旧恢复失败。** 对外状态现在根据当前完整、新鲜的 WS 数据投影为 `live`，并在数据失效后取消覆盖。原始 HTTP 失败诊断、`last_attempt_at` 和 `last_success_at` 保留；不会虚构 HTTP 成功或修改数据时间。覆盖晚到 HTTP 失败再次写入的竞态。
4. **16 个关注合约时固定顺序调度产生饥饿。** 16 个盘口每 8 秒刷新需要 120 权重/分钟，超过自身 80 的预算。改为随受保护合约数量调整间隔，并从最旧的完整盘口开始修复；指数预算和实际滚动上限继续保留。

## 有界离线模拟证据

16 个关注合约、180 秒、逐秒驱动；仅替换线程调度与网络，结果经过实际验证及完整盘口提交逻辑。前 30 秒作为预热。此结果属于可重复故障模拟，不是生产在线观测。

| 指标 | 修复前 | 修复后 |
|---|---:|---:|
| 预热后最大深度年龄 | 36.99 秒 | 16.0 秒 |
| 深度年龄超过 30 秒的合约样本 | 23 | 0 |
| 各合约刷新次数范围 | 12–15 | 全部 11 |
| 恢复滚动权重 | ≤ 80/分钟 | ≤ 80/分钟 |

## 验证

新增测试：`test_market_ingress_qa.py` 7 项、`test_recovery_state_qa.py` 4 项、`test_focused_market_fairness.py` 1 项。未来事件、恢复状态和调度问题均先构造失败再修复。

相关最终回归命令：

```text
python -B -m unittest test_focused_market_fairness test_market_ingress_qa test_recovery_state_qa test_focused_market_api test_focused_market_recovery test_mark_fallback test_realtime_market test_dashboard_server test_quote_health test_shared_market_frames test_mark_watch_routes
```

结果：200 项通过，6.337 秒。

另一个端点组合覆盖 `test_btc_terminal_server`、`test_mark_watch_routes`、`test_focused_market_api`、`test_shared_market_frames` 和三个新增测试模块（序列号测试加入前），59 项通过，10.470 秒。最终集成检查与生产部署由主任务完成。

## 限制

这些修复不会降低字段新鲜度标准；网络完全不可用、公开接口限流或缺少实际买盘时仍必须停止把旧数据当作可成交数据。调度模拟使用快速成功的 REST 响应，不能据此承诺真实上游故障期间不出现同步状态。
