# DeepSeek 官方接口核实

核实日期：2026-10-22。仅使用官方文档；未读取或调用任何 API Key。

## 模型与地址

- V4.1 Flash 当前版本为 DeepSeek-V4.1-Flash-1017，调用 ID 为 **deepseek-flash**。
- V4 Pro 当前版本为 DeepSeek-V4-Pro-0813，调用 ID 为 **deepseek-v4-pro**。
- 官方模型发现接口为 GET https://api.deepseek.com/models，返回 ID、名称、上下文和输出限制等元数据。[模型列表](https://api-docs.deepseek.com/api/list-models/)、[当前模型与价格](https://api-docs.deepseek.com/quick_start/pricing/)

9 月 10 日发布文章曾宣布 Pro 请求切换至 Flash，但更新后的官方日志明确说明：为响应用户需求，9 月 14 日后仍继续提供 Pro API，计费不变。应以当前模型发现、更新日志和价格页为准，不把旧发布文章的计划当成已实施事实。[官方更新日志](https://api-docs.deepseek.com/updates/)

## 请求与结构化输出

POST https://api.deepseek.com/chat/completions，使用 messages 和上述模型 ID。两个模型默认开启思考，默认 effort 为 high。快速提取筛选条件时应明确使用 thinking.type=disabled 或 reasoning_effort=none，并主动限制 max_tokens。文档允许最大输出 393216 token，但本功能无需使用此额度。[Chat Completions](https://api-docs.deepseek.com/api/create-chat-completion/)

response_format.type=json_object 可约束 JSON 语法；提示词也必须明确包含 json 和输出示例。官方指出仍可能返回空内容，达到长度上限可能截断，因此后端仍需检查 finish_reason、内容、字段白名单、类型和范围。该接口没有普通 response_format=json_schema 选项。[JSON 输出](https://api-docs.deepseek.com/guides/json_mode/)

思考模式下 temperature 等参数无效。Flash 在非思考模式下忽略 top_p；不能据 temperature=0 宣称输出完全确定。使用思考加 tools 时，后续请求必须完整回传之前的 reasoning_content，否则会返回 400。单次 JSON 条件解析可以避免这条工具链复杂性。[思考模式](https://api-docs.deepseek.com/guides/thinking_mode/)

工具 strict 模式属于 Beta，要求 https://api.deepseek.com/beta，所有函数 strict=true；每个对象必须设置所有属性 required 和 additionalProperties=false。普通 JSON 输出不能替代本地业务校验。[工具调用](https://api-docs.deepseek.com/guides/tool_calls/)

## 稳定性与成本

限额按账号累计，与 Key 数量无关；当前并发限制为 Flash 2500、Pro 500，超额返回 429。非流式等待可持续返回空行，SSE 可返回 keep-alive 注释，尚未开始推理的请求最长可等待 10 分钟。**推论：仅设置 socket 读取超时不足以保证总时限，应另设整体截止时间、响应体上限及后台并发上限。**[限流与隔离](https://api-docs.deepseek.com/quick_start/rate_limit/)

400/422 表示请求格式或参数错误，401 表示认证失败，402 表示余额不足；这些应明确反馈而非循环重试。429 应退避，500/503 可在短暂等待后重试；应限制重试次数，防止重复消费与阻塞。[错误代码](https://api-docs.deepseek.com/quick_start/error_codes/)

上下文缓存默认启用，匹配已持久化的完整前缀，命中不保证。保持系统提示在动态数据前面有助于复用；实际命中量可读取 usage.prompt_cache_hit_tokens / prompt_cache_miss_tokens。[上下文缓存](https://api-docs.deepseek.com/guides/kv_cache/)

当前峰时每百万 token 的缓存未命中输入/输出：Flash 为 $0.30/$1.20，Pro 为 $1.32/$3.96；非峰时均减半。应保存实际 usage，并根据同一组需求的有效结果、延迟与 token 消耗比较模型，不能从官方宣传直接推断本应用质量。[价格页](https://api-docs.deepseek.com/quick_start/pricing/)

## 本功能的实现建议

这是工程建议：模型负责把自然语言转换为受限条件，后端用同一份公开行情快照执行筛选与计算，再验证返回合约的身份、到期日、方向和有效报价。无需把交易所 Key 发给模型；行情线程与模型调用之间不应持有共享锁。筛选结果应附快照时间及状态，不能把旧结果重新标为实时。
