"""Export a research figure, without adding anything to the dashboard."""
import json
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
from analyze_puts import distribution, QTY

ROOT = Path(__file__).resolve().parent
font_path = Path("C:/Windows/Fonts/msyh.ttc")
if font_path.is_file():
    font_manager.fontManager.addfont(str(font_path))
    plt.rcParams["font.family"] = font_manager.FontProperties(fname=str(font_path)).get_name()
plt.rcParams["axes.unicode_minus"] = False
data = json.loads((ROOT/"results.json").read_text(encoding="utf-8"))
rows = {r["strike"]: r for r in data["rows"]}
spot = data["metadata"]["spot_index"]
xs = [0.3+i*0.002 for i in range(251)]
fig, ax = plt.subplots(figsize=(11.8, 6.8), dpi=150)
fig.patch.set_facecolor("#f8f6ef")
ax.set_facecolor("#fffdf8")
colors = {60000:"#527d72",64000:"#b2674a",70000:"#506e9c"}
for strike, color in colors.items():
    row = rows[strike]
    years = row["days"]/365
    credit = row["net_max_profit_0_01"]/QTY
    values = [distribution(spot,strike,years,sigma,0,credit)["ev"]*QTY for sigma in xs]
    ax.plot([x*100 for x in xs], values, color=color, linewidth=2.6,
            label="{:,} Put".format(strike))
    for sigma in (0.4,0.6,0.8):
        y = distribution(spot,strike,years,sigma,0,credit)["ev"]*QTY
        ax.scatter([sigma*100],[y],color=color,s=24,zorder=5)
low, high = sorted(data["metadata"]["rv"][str(n)]*100 for n in (30,60))
ax.axvspan(low, high, color="#ddd4b7", alpha=0.45,label="近30/60日已实现波动区间（非预测）")
ax.axhline(0, color="#55564e", linewidth=1, linestyle="--")
ax.set(xlim=(30,80), ylim=(-10.3,2.7), xlabel="假设未来年化波动率（%）",
       ylabel="卖出 0.01 张的模型平均净利润（USDT）")
ax.set_title("期望收益的排名，会随未来波动假设改变",loc="left",fontsize=18,pad=18)
ax.grid(axis="y",color="#e6e1d5",linewidth=0.7)
ax.spines[["top","right"]].set_visible(False)
ax.legend(loc="lower left",frameon=False,fontsize=10)
fig.text(0.12,0.035,"2026-10-30 到期 · BTC指数 81,805.13 · 同一零漂移 GBM 分布 · 已计开仓及行权费\n"
         "情景分析：不是价格预测；未模拟提前平仓、跳跌或强平。快照：北京时间 2026-10-15 01:38:23。",
         color="#66655c",fontsize=9)
fig.subplots_adjust(bottom=0.19,top=0.87,left=0.12,right=0.96)
fig.savefig(ROOT/"波动假设与期望收益.png",facecolor=fig.get_facecolor())
fig.savefig(ROOT/"波动假设与期望收益.svg",facecolor=fig.get_facecolor())
plt.close(fig)
print("Sensitivity figure saved.")
