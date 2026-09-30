# 飞书: 发图片 + 实时推送 (2026-09-24 实发验证, code=0)

## 1. 图片通道 (原工具只有 text/media, 发不了图)

`~/.hermes/scripts/feishu_notify.py`(仅 text) 和项目里的 `send_feishu.py`(text + 视频 media) 都发不了图片。
图片必须**两步**, 不能走 `/im/v1/files` (那是文档/媒体用的, 图片走它报错):

```bash
# ① 上传图片 → image_key   (multipart/form-data)
curl -s -X POST https://open.feishu.cn/open-apis/im/v1/images \
  -H "Authorization: Bearer $TOKEN" \
  -F "image_type=message" -F "image=@/path/to/x.png"
# → {"code":0,"data":{"image_key":"img_v3_0215r_..."}}

# ② 发图
curl -s -X POST "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id" \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"receive_id":"oc_xxx","msg_type":"image","content":"{\"image_key\":\"img_v3_...\"}"}'
# → message_id
```

- 说明文字**另发一条** `msg_type=text` (单条长文会 400, 长文拆条)
- 视频/音频仍走 `/im/v1/files` + `msg_type=media` (**file 类型只能发文档类, 230055 实锤**)
- **token 每次现取** → 不依赖 gateway 进程内缓存 ⇒ `99991663 Invalid access token` 期间这条直推通道照样能发
  (与技能正文"兜底直推"同一思路, 可作 gateway token 死掉时的告急通道)
- 群 id 取法: `~/.hermes/channel_directory.json`, 或 `grep -i Inbound ~/.hermes/logs/gateway.log` 里的 `chat_id=oc_...`
- 群消息**必须 @机器人**才触发入站事件; DM 可直接发

## 2. 实时推送的正确形状 = 只读 watcher (绝不为了推送去采集)

```python
# 轮询"内容标识", 变化才推。绝不为了推送而触发拍照/采集。
cur = last_result(cam).get("topview")        # 文件名自带序号: Finger_TopView_W960_H960_No_287.png
if cur and cur != last:                      # 首轮只记基准, 不推
    push_image(...)                          # 推新图 + 说明文字
    last = cur
```

- 反例(实测事故): "每 5s 触发一次拍照再推" → 把产线台连拍 **132 张** (审计流水为证)。推送端**只消费, 不产生**
- 新图来源是产线 HMI/PLC 或人手动触发; 推送端只是搬运
- 本机后台进程随会话结束而停 → 要常驻需挂 systemd user 服务 或 cron 每 N 分钟拉起 (cron 用 `no_agent=True` + `deliver='local'`, 由脚本自己决定发不发)

## 3. 现成实现 (本次落地, 可直接复用/照抄)

`~/lerobot-smolvla-lew/tools/aoi_feishu_push.py`
```bash
./gui-venv311/bin/python tools/aoi_feishu_push.py --text "自检"      # 只发文本 (验通道, 打印 code/message_id)
./gui-venv311/bin/python tools/aoi_feishu_push.py --once            # 推当前最新"裁减图" + 判决/裁减指标说明
./gui-venv311/bin/python tools/aoi_feishu_push.py --once --ours     # 连我们自裁后的判据图一起发 (同图双口径对照)
./gui-venv311/bin/python tools/aoi_feishu_push.py --once --grab     # ⚠️ 远端内存空时: 先真拍一张再推
./gui-venv311/bin/python tools/aoi_feishu_push.py --watch --interval 8  # 实时(只读) 
```
- 内部自带 `load_env()` 读 `~/.hermes/.env` 的 `FEISHU_APP_ID/SECRET` + 现取 token + multipart 上传 (无第三方依赖)
- 推完落盘: `reports/feishu_push/*.png`; 状态: `reports/aoi_feishu_push_state.json` (last_topview / ts)
- 说明文字模板: 尺寸/灰度均值/饱和% · 远端判决(verdict/count/ms/n) · 裁减(method/canonical/score/angle/crop_ms) · 文件名 · 推送时间
  + 明确标注「只读推送, 未触发拍照」(让收到的人知道没打扰产线)

## 4. 网关健康检查 (只读, 30 秒)

```bash
grep -iE "connected to wss|feishu connected" ~/.hermes/logs/gateway.log | tail -2
grep -i "Inbound" ~/.hermes/logs/gateway.log | tail -3
python3 -c "import json;d=json.load(open('/home/ubuntu/.hermes/gateway_state.json'));print(d['gateway_state'], d['platforms']['feishu']['state'])"
```
- `gateway_state=running` + `platforms.feishu.state=connected` = 正常
- 日志写入时间戳可能因本机时钟偏移而与本地时间不一致 (见"NTP 回拨"记录), 别据此判死
