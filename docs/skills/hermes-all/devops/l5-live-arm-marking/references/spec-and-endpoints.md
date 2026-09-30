# overlay_spec.json 结构与端点

```json
{
 "updated_at": "2026-09-28 08:41:56",
 "cameras": {
   "arm": {"boxes": [{"xyxy":[300,1,360,65], "label":"mod_peg 0.75", "origin":"l5live",
                      "kind":"optical_module", "conf":0.751, "ev":"detected"}]}
 },
 "l5live": {"ts":"08:41:56", "src":"orin", "fetch_ms":5.0, "slot_ms":35.7, "yolo_ms_total":3.9,
            "cycle_ms":44.7, "n_boxes":1, "slot_state":"...", "module_state":"...", "frame_note":"..."}
}
```

- 端点: `/snapshot/overlay_arm.jpg` (叠框图, 页面第一格用的就是它)、`/snapshot/arm.jpg` (原图,
  也作 fallback 源)、`/scene.json` (含 arm 路 boxes + `by_origin` 累计计数)。
- ORIGIN_STYLE 里没有 `l5live` ⇒ 渲染成默认灰 (200,200,200)。要色区分得让服务端加样式 (本次未改服务)。
- 帧源: `http://192.168.23.66:8792/frame.jpg` (D405, 640x480, ~38-43KB/帧, 无时间戳字段)。
