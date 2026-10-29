# 本机比特币余额模块

原页面来源为 `yxhBlog` 最新工作树的余额模板和计算核心。这里保留独立副本，原项目不受修改。

运行 `node terminal/wallet/build_wallet.mjs` 会读取 `terminal/data/bitcoin-balance-snapshot.json` 和 `bitcoin-cny-rates.json`，校验完整交易历史后生成 `wallet.html`。生成页面包含计算代码和初始化数据，导出 HTML 后也可独立打开。

`wallet.html`、本机缓存及导出的 HTML 均包含钱包地址和资产记录，仅保存在本机，不随公开源码发布。克隆仓库后须先配置并取得自己的已核验余额快照和汇率文件，再运行上述构建命令；不要把真实快照或生成页面提交到公开仓库。

本地服务器仅将生成的 `wallet.html` 映射到 `/wallet.html`；源文件、测试和 `terminal/data` 不需提供静态访问。页面使用 `/api/wallet/proxy` 的固定只读资源，浏览器不会提交登录凭据或 API Key。

| resource | 参数 | 固定上游 |
| --- | --- | --- |
| address | address | `https://mempool.space/api/address/{address}` |
| transactions | address，可选 cursor | `https://mempool.space/api/address/{address}/txs/chain[/{cursor}]` |
| history | 无 | `https://mempool.space/api/v1/historical-price?currency=USD` |
| quote | 无 | `https://mempool.space/api/v1/prices` |
| fx | from，to，格式 YYYY-MM-DD | `https://api.frankfurter.dev/v2/rates?from={from}&to={to}&base=USD&quotes=CNY&providers=ecb` |

服务端应固定 provider、限定已配置地址、校验 cursor 为 64 位十六进制、严格校验日期。页面不接受任意代理 URL。用 `file://` 打开的导出文件会直接使用上述固定公开服务。

余额估值沿用 mempool.space 的 BTC/USD 采样价格；人民币使用上一可用日的 ECB 参考汇率。它与价格警报的币安 BTC/USDT 是两个明确标注的价格口径。

嵌入页面后使用 `postMessage({type: 'wallet-height', height}, location.origin)` 上报正文高度。父页面需同时检查消息来源窗口和同源 origin。

验证：`node --test terminal/wallet/test_wallet_core.mjs terminal/wallet/test_wallet_page.mjs`。覆盖完整余额对账、历史估值、转账剔除盈亏、汇率、计价/周期切换、刷新失败保留数据、恢复刷新、代理资源及高度消息。

页面测试直接用 `wallet.template.html` 和 `core.mjs` 在内存中构建页面，使用合成的钱包地址、交易和行情，无需 `wallet.html`、`terminal/data` 或交易所凭据。计算核心另有可选的本机真实快照检查；没有本机文件时该项自动跳过。
