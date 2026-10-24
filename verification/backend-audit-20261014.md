# 本机比特币终端后端回归记录

日期：2026-10-14（北京时间）。审计范围是行情、警报、声音任务、余额数据代理、本机 API 与期权实时缓存；启动器和浏览器交互由独立回归覆盖。

## 测试结果

下面的离线命令共运行 **144 项测试，全部通过**，未访问账户、未使用 API Key，声音播放使用模拟对象，未触发真实邮件或响铃。

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
& 'C:\Users\yxh\AppData\Local\Programs\Python\Python39\python.exe' -m unittest test_btc_alert test_btc_terminal_server test_alert_sound test_binance_btc_options test_dashboard_server test_realtime_market
```

| 文件 | 测试数 |
| --- | ---: |
| test_btc_alert.py | 49 |
| test_btc_terminal_server.py | 20 |
| test_alert_sound.py | 9 |
| test_binance_btc_options.py | 8 |
| test_dashboard_server.py | 35 |
| test_realtime_market.py | 23 |
| 合计 | 144 |

## 本轮发现并修复的问题

- 警报服务重启后 revision 从低值重新开始，浏览器可能丢弃新服务的快照。新增进程实例标识 instance_id；前端据此识别服务重启。
- Python 默认 JSON 解码会吞掉重复字段。修改设置请求现在拒绝重复 JSON 字段、非标准 NaN/Infinity、重复 Host/Origin/Content-Length 以及重复动作和类型请求头，拒绝时不改变设置。
- 停止过程中的警报操作原先可能抛 RuntimeError 并直接断开。现在返回可识别的 HTTP 503 错误。
- 浏览器切换页面中止下载，或关闭 keep-alive 连接，会产生无意义的连接异常堆栈。现按普通断连处理；后续请求仍正常。
- 钱包提供方的 Retry-After HTTP 日期原先退化为 60 秒；没有头部的 HTTP 418 也只等待 60 秒。现在尊重 HTTP 日期，418 缺少有效头部至少等待一小时；并发限流不会缩短已有禁用间隔。
- 期权旧连接在阻塞 recv 期间更换订阅/停止后可能仍提交晚到帧，甚至报告旧订阅成功。现在收到帧后重新核实当前 generation。关闭一个连接异常不会阻止其余连接关闭或新订阅启动。

## 覆盖的重要行为

本轮新增 18 项回归，包含实例重启、北京时间午夜前的晚到交易、过期行情恢复、畸形日 K 的原子拒绝、损坏设置恢复、未完成声音任务不重复播放、关闭声音取消当前及排队任务、重复 JSON/请求头、停止 API 响应、下载中断后恢复、HTTP 日期限流、相同钱包请求并发去重、超大/非法上游响应不缓存、期权旧 generation 与停止后的晚到帧、订阅拒绝和关闭错误隔离。

原有回归同时验证：当天零点价格与 2.5% 精确边界、上涨/下跌各一次并跨重启去重、静态资源和路径隔离、同源约束、无交易接口、REST 与 WS 的排序/并发合并、失效目录和覆盖状态、限流预算、WAV 格式及 Windows 异步播放/取消。

首次运行中静态脚本读取出现一次 2 秒超时；未降低断言或修改该超时。后续同一测试和完整套件均通过。最终完整运行约 12.5 秒。

离线回归证明程序分支和边界行为，不保证第三方提供方永不维护、网络永不断开或电脑睡眠时能播放声音。实际本机页面、启动注册及真实服务状态仍需与浏览器/启动器回归共同验收。
