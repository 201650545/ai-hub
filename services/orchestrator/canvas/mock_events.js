/* mock_events.js —— 模拟组件编排器 SSE 事件流推演数据 */

window.MOCK_EVENT_SEQUENCE = [
  { ts: "14:04:01", phase: "framework", slot: "main", event: "framework_start", detail: "正在生成 HTML 七段式课件骨架..." },
  { ts: "14:04:05", phase: "framework", slot: "main", event: "framework_done", detail: "框架生成完成，含 5 个媒体槽位" },
  { ts: "14:04:06", phase: "scan", slot: "main", event: "scan_done", detail: "扫描到 4 个图片槽位，1 个视频槽位" },
  { ts: "14:04:08", phase: "asset_fill", slot: "p12_market", event: "prompt_ready", detail: "超市场景对话 - 提示词就绪", site: "豆包生图" },
  { ts: "14:04:10", phase: "asset_fill", slot: "p12_market", event: "generating", detail: "opencli 注入提示词，正在生图..." },
  { ts: "14:04:16", phase: "asset_fill", slot: "p12_market", event: "done", detail: "生图成功并存入课时文件夹", preview: "../勘探样例/probe_zhipu.png", site: "豆包生图" },
  { ts: "14:04:18", phase: "asset_fill", slot: "p15_reading", event: "generating", detail: "正在生成图书角场景...", site: "智谱清言 AI" },
  { ts: "14:04:22", phase: "asset_fill", slot: "p15_reading", event: "done", detail: "图书角插图提取完成", preview: "../勘探样例/probe_liblib.png", site: "智谱清言 AI" },
  { ts: "14:04:24", phase: "asset_fill", slot: "p20_video", event: "generating", detail: "检索 B站 英文数字儿歌视频...", site: "B站" },
  { ts: "14:04:26", phase: "asset_fill", slot: "p20_video", event: "done", detail: "提取 BV1xx411c7yy，嵌入代码成功", site: "B站" },
  { ts: "14:04:28", phase: "verify", slot: "main", event: "verify_start", detail: "正在执行 6 项 HTML 课件 verify 校验..." },
  { ts: "14:04:30", phase: "verify", slot: "main", event: "verify_done", detail: "Verify 全项绿灯通过！" },
  { ts: "14:04:32", phase: "deliver", slot: "main", event: "deliver_done", detail: "课件自动打包交付完工！" }
];
