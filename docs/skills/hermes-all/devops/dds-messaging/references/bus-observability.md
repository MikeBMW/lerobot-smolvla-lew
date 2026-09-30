# DDS 总线可观测性 · 实测坑

目标场景: 把整套系统的节点间数据做成 **DDS 总线**上可观察的 topic(对标 Vector CANoe 的
Trace/Statistics/Restbus), 并能在量产不序列化的前提下**随时工程探测**。

## 零、收口/部署实测坑(2026-09-29)
- `os.path.getsize(不存在的文件)` 抛 FileNotFoundError ⇒ 守护进程整个 DDS 参与者建不起来, **所有话题静默**
  (现象: 状态灯全黑 + 日志刷“DDS 不可用: No such file”)。缺文件与空文件都要当“没配”。
- 改 systemd unit 前必看 `systemctl cat` 实际内容: `write_file` 对“本任务未读过的既有文件”会**拒绝写入**
  (返回错误但不抛异常), 静默留下旧路径 ⇒ 服务异常。
- 路径收口后旧路径一律留软链, 并实测一条老命令(例: 用旧路径 `import zmax_node`)。

## 一、观察者读取端必须用深历史(最容易错的一条)

发布端 QoS 若为 `BEST_EFFORT + KEEP_LAST(1)`(常见于“最新值”语义), 探针/分析仪**照抄该 QoS**
会在突发下大量丢样: 实测一轮发 182 条, 读取端只收到 **1~3 条** —— 因为读取端 history 深度=1,
两次 `take()` 之间到达的全部被覆盖。

修法(不改变发布端语义, 也不需要 RELIABLE —— 读端 RELIABLE + 写端 BEST_EFFORT 属于
**QoS 不兼容**, 根本不会匹配):

```python
from cyclonedds.core import Policy, Qos
from cyclonedds.sub import DataReader
from cyclonedds.topic import Topic
qos = Qos(Zn._p(Policy.Reliability.BestEffort, 0), Zn._p(Policy.History.KeepLast, 200))
reader = DataReader(dp, Topic(dp, "zmax/" + key, Zn.TOPICS[key]), qos=qos)
```

DDS 的 **History 不参与 RxO 匹配**, 所以读端可以在写端只留 1 条的前提下自己留 200 条。
实测: 同口径由 1~3 条提升到 80→182 条。

## 二、突发洪灌要自己节流

即使读端深历史, 写端 `KEEP_LAST(1)` 在**极高瞬时速率**下仍会覆盖尚未发出的样点(实测 80/182)。
回灌/回放类工具默认加 `--pace 0.001`(1ms/条), 182 条零丢失。这不是丢包 bug, 是 QoS 语义。

## 三、`Node.pub()/send()` 传**短键**, 不要传全名

节点封装自己会补 `zmax/` 前缀; 传 `"zmax/hw_state"` ⇒ 双重前缀 ⇒ `KeyError`。始终传 `hw_state`。

## 四、不要给每条连线开一个话题

N 条画布连线若开 N 个 topic, 发现/内存/可读性一起崩。CANoe 口径: **一条 Message 多条 Signal**
—— 全部连线走同一条已注册话题(如 `zmax/link_value`), 信号身份 = (源节点, 源端口);
新增话题必须先进注册表, 否则订阅端 `TOPICS[key]` KeyError(实测踩到)。

## 五、探针要跟随档位切换

档位白名单是唯一开关(量产 prod=0 话题是设计预期, 不是故障)。若探针只在启动时定订阅集,
切档后永远看不到新话题。每轮对账一次档位, 补订新话题、把不再允许的话题标灰而不是删掉历史。

## 六、脚本跑在仓库外时的路径反推坑

`REPO = dirname(dirname(__file__))` 这类反推: 脚本一旦被放到别处(如 ~/xxx.py), REPO 会变成
`/home`, `sys.path` 里塞进不存在的目录, 于是 `import hardware_view` 每轮抛 ModuleNotFoundError,
话题静默为空(日志里只有异常, 容易被当成"没数据")。脚本一律显式 `ZMAX_REPO=/home/ubuntu/zmax_rel`。

## 七、判定"话题活着"的三个前提(缺一个就会误报)

1. 档位白名单包含它; 2. 发布进程真的在发(看 `journalctl -u <svc>` 里有没有 ModuleNotFoundError);
3. 配对 > 0(`matched_pubs`)。
只有 `count` 会骗人: 报 0 条既可能是"设计不发", 也可能是"发了没人收"。

## 八、配置文件防呆: 空文件 ≠ 没配置

`CYCLONEDDS_URI=file://<0 字节文件>` 解析失败 ⇒ 参与者掉出默认发现网 ⇒ 现象是
“日志显示正常 write, 但配对=0、对端 0 条”。
修: 加载配置前判断 `os.path.getsize(cfg) > 0`, 否则当**未配置**处理并打一行告警;
**同一个仓库里发布端与守护端要同一套防呆**(只改一边 = 只修一半, 实测守护端早有保护、发布端漏了,
于是"主话题一直空"看着像没数据)。

## 九、最终归属: 同一条链路的代码不得分居两处

上述第 六/八 两条的根因都是“代码在仓库外 + 两边实现不同步”。把发布端/守护端/聚合端与类型定义
收进同一个可 CICD 的路径(`src/lerobot/<pkg>/` + `tools/<tool>/`), systemd 指过去;
否则每次排障都要先判“改的是哪个副本”。

## 十、回灌/回放(restbus)的口径

把工程数据(画布 json)发到总线上以便无真机时观察时:
* 报文里写明来源与性质(`kind='bus-sim'`, `text='from canvas json (工程回灌·非实测)'`),
  UI/报告必须能一眼区分“回灌”与“真机实测”;
* 发前先等配对(`wait_for_match`), 发完 linger 2s 再退 —— BEST_EFFORT 下进程立刻退出会
  让读者收不全; 持续回灌用 `--watch --rate`。
