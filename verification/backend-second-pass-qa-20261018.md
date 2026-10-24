# 后端第二轮：复现、修复、再次验证

范围：公开行情传输及消息边界、警报跨日及持久化生命周期。所有输入均为临时目录和本机 fixture；未调用私有账户或交易接口，未播放实际声音，未改启动项，未重启生产。

## 阶段一

- **停止后的迟到声音线程覆盖新设置。** 阻塞 notifier 超过 stop 的 1 秒等待上限，重建监控并保存关闭声音及 7.5% 阈值，随后释放旧线程：原实现会把磁盘设置恢复成旧值。修复为封闭实例的迟到状态只写内存；stop 在锁内完成最后一次持久化。
- **超大 JSON 整数使行情校验异常退出。** 400 位 `serverTime` 会在 `float()` 抛出 OverflowError。修复为无效数字，返回已清洗的 UNEXPECTED_SCHEMA 错误，恢复线程可以继续工作。

阶段一相关 75 项测试通过。

## 阶段二

- **现货初始化只读固定前缀。** 合法 JSON 加超过 2 MB 空格及坏尾部、或者声明较长 Content-Length 但只返回合法 JSON 前缀，都曾被误判成功。现复用完整、有界、带总时限的响应读取逻辑。
- **非有限 JSON。** 严格解析拒绝 NaN、Infinity、-Infinity，以及嵌套字段中的 `1e999`。后者原会变成无穷浮点，破坏后续禁止非有限数字的 JSON 快照。
- **警报 WS 编码自动探测。** Python 的 json.loads 会把 UTF-16 字节自动当作有效消息，实测可以建立基线并触发警报。现按 WS 文本协议严格解码 UTF-8，再解析 JSON；原有 UTF-8 字节及文本保持有效。
- **跨午夜组合检查。** 前一天交易、缺少 E/T、布尔时间、NaN、未来时间、错误 ID 不污染当天基线；新一天正确触发一次，重启后不重复触发。

新增 `test_backend_failure_injection.py` 共 9 项。实质缺陷均先观察失败，再修复后重测。最终命令：

```text
python -B -m unittest test_backend_failure_injection test_btc_alert test_binance_btc_options test_market_stability test_public_gzip test_realtime_market test_market_ingress_qa test_btc_terminal_server
```

结果：178 项通过，11.458 秒。包含现有消息顺序、队列 generation/receipt、压缩、超时、限流、端点及警报持久化测试。

修改文件：`btc_alert.py`、`binance_btc_options.py`；新增上述测试文件。该次审查范围内没有已知未决可复现缺陷。此结论有明确的 fixture、模块和边界范围；不代表外部网络或行情服务不会故障。全站总回归和部署由主任务处理。
