/* app.js —— 组件编排器画布观察窗 SSE 消费与动态UI渲染逻辑 */

let slotsMap = {};
let eventLogList = [];
let startTime = Date.now();
let totalSlots = 5;
let completedSlots = 0;
let es = null;
let receivedRealEvent = false;

const PHASES = ["framework", "scan", "asset_fill", "verify", "deliver"];

function initCanvas() {
  updateTimer();
  setInterval(updateTimer, 1000);

  // 尝试连接真实 SSE 端点；仅当从未收到真实事件时才回退 Mock
  try {
    es = new EventSource('/api/orchestrator/stream');
    es.onmessage = (ev) => {
      try {
        const d = JSON.parse(ev.data);
        receivedRealEvent = true;
        if (d.event === 'stream_end') {
          es.close();
          updatePhaseTimeline('deliver');
          return;
        }
        handleSSEEvent(d);
      } catch(e){}
    };
    es.onerror = () => {
      es.close();
      if (!receivedRealEvent) startMockStream();
    };
  } catch(e) {
    if (!receivedRealEvent) startMockStream();
  }
}

function startMockStream() {
  if (!window.MOCK_EVENT_SEQUENCE) return;
  window.MOCK_EVENT_SEQUENCE.forEach((item, idx) => {
    setTimeout(() => {
      handleSSEEvent(item);
    }, idx * 1800);
  });
}

function handleSSEEvent(data) {
  eventLogList.push(data);
  renderLogItem(data);
  updatePhaseTimeline(data.phase);

  // 真实槽位总数（scan done 事件携带 total）
  if (typeof data.total === 'number' && data.total > 0) {
    totalSlots = data.total;
    updateProgress();
  }

  if (data.slot && data.slot !== 'main' && data.slot !== 'all') {
    if (!slotsMap[data.slot]) {
      slotsMap[data.slot] = {
        id: data.slot,
        topic: data.detail || '媒体槽位',
        status: 'pending',
        site: data.site || '自动调度',
        preview: null
      };
    }

    const slotObj = slotsMap[data.slot];
    if (data.event === 'generating' || data.event === 'prompt_ready') {
      slotObj.status = 'generating';
    } else if (data.event === 'retry') {
      slotObj.status = 'retry';
    } else if (data.event === 'done') {
      slotObj.status = 'done';
      if (data.preview) slotObj.preview = data.preview;
      completedSlots = Math.min(totalSlots, completedSlots + 1);
    } else if (data.event === 'failed') {
      slotObj.status = 'failed';
    }

    renderSlotGrid();
  }

  updateProgress();
}

function updatePhaseTimeline(currentPhase) {
  const currentIdx = PHASES.indexOf(currentPhase);
  PHASES.forEach((p, idx) => {
    const el = document.getElementById('step-' + p);
    if (!el) return;
    el.classList.remove('active', 'done');
    if (idx < currentIdx) {
      el.classList.add('done');
      el.querySelector('.step-dot').innerText = '✓';
    } else if (idx === currentIdx) {
      el.classList.add('active');
    }
  });
}

function renderSlotGrid() {
  const grid = document.getElementById('slot-grid');
  if (!grid) return;
  grid.innerHTML = '';

  Object.values(slotsMap).forEach(slot => {
    const card = document.createElement('div');
    card.className = 'slot-card';

    let badgeClass = 'badge-pending';
    let badgeText = '⏳ 待处理';
    if (slot.status === 'generating') { badgeClass = 'badge-generating'; badgeText = '🔄 生成中'; }
    else if (slot.status === 'done') { badgeClass = 'badge-done'; badgeText = '✅ 完成'; }
    else if (slot.status === 'retry') { badgeClass = 'badge-retry'; badgeText = '⚠️ 重试中'; }
    else if (slot.status === 'failed') { badgeClass = 'badge-failed'; badgeText = '❌ 失败'; }

    let previewHTML = `<div style="font-size:12px;color:var(--text-muted);">暂无预览</div>`;
    if (slot.preview) {
      previewHTML = `<img src="${slot.preview}" alt="${slot.topic}">`;
    }

    card.innerHTML = `
      <div class="slot-head">
        <span class="slot-id">#${slot.id}</span>
        <span class="slot-badge ${badgeClass}">${badgeText}</span>
      </div>
      <div class="slot-topic">主题: ${slot.topic}</div>
      <div style="font-size:12px;color:var(--text-muted);">调度站点: <b style="color:var(--primary);">${slot.site}</b></div>
      <div class="preview-container">${previewHTML}</div>
    `;

    grid.appendChild(card);
  });
}

function renderLogItem(data) {
  const stream = document.getElementById('log-stream');
  const countEl = document.getElementById('event-count');
  if (!stream) return;

  const item = document.createElement('div');
  const isErr = data.event === 'failed' || data.event === 'retry';
  const isSuccess = data.event === 'done';
  item.className = `log-item ${isErr ? 'error' : (isSuccess ? 'success' : '')}`;

  item.innerHTML = `
    <div style="display:flex;justify-content:space-between;color:var(--text-muted);font-size:11px;">
      <span>[${data.ts || new Date().toLocaleTimeString()}] ${data.phase}</span>
      <span>${data.slot}</span>
    </div>
    <div style="font-weight:700;margin-top:2px;">${data.event}: ${data.detail || ''}</div>
  `;

  stream.appendChild(item);
  stream.scrollTop = stream.scrollHeight;
  if (countEl) countEl.innerText = `${eventLogList.length} 条事件`;
}

function updateProgress() {
  const pText = document.getElementById('progress-text');
  if (pText) pText.innerText = `${completedSlots}/${totalSlots}`;
}

function updateTimer() {
  const elapsed = Math.floor((Date.now() - startTime) / 1000);
  const m = String(Math.floor(elapsed / 60)).padStart(2, '0');
  const s = String(elapsed % 60).padStart(2, '0');
  const tText = document.getElementById('timer-text');
  if (tText) tText.innerText = `${m}:${s}`;
}

function sendConfirmAction() {
  fetch('/api/orchestrator/confirm', { method: 'POST' })
    .then(r => r.json())
    .then(d => alert('✅ L2 关键节点确认提交成功！'))
    .catch(e => alert('模拟环境：已发送确认指令'));
}

window.onload = initCanvas;
