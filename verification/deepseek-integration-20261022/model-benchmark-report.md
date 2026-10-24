# DeepSeek 期权筛选实测

测试时间：2026-10-22T18:46:13.508907+08:00

两个模型使用相同公开行情摘要、六条中文需求、同一提示词和输出上限；并发最多 2，关闭 HTTP 重试。
测试衡量条件提取准确率与响应延迟，不衡量交易策略的预期收益。单次小样本不代表长期服务水平。

| 模型 | 完成 | 整题正确 | 字段正确 | 中位延迟 | Token 总量 |
|---|---:|---:|---:|---:|---:|
| deepseek-flash | 6/6 | 6/6 | 53/53 | 1.41 秒 | 8814 |
| deepseek-v4-pro | 6/6 | 6/6 | 53/53 | 2.30 秒 | 8879 |

推荐默认模型：deepseek-flash


完整规范化条件、简短回复、澄清问题、逐字段评分、实际返回模型和用量保存在同目录 JSON 中。
未保存密钥、Authorization、原始响应体或隐藏推理。

[官方模型列表](https://api-docs.deepseek.com/api/list-models/) · [官方接口](https://api-docs.deepseek.com/api/create-chat-completion/)
