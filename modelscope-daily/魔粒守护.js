#!/usr/bin/env node
/**
 * 魔搭社区（ModelScope）每日魔粒守护
 * ---------------------------------------------------------------
 * 职责（仅此三项，全部作用于本人账号，不对外产生任何内容）：
 *   1. 保活登录态：每日唤起一次站点访问，触发平台的「每日发放」魔粒
 *   2. 到账核对：校验 daily_active(200) 与 aliyun_bindlogin(50) 是否已入账
 *   3. 额度播报：输出余额、临期魔粒、近期消耗与利用率，提示别让额度白白过期
 *
 * 明确不做（虚假互动，已从原方案中剔除）：
 *   × 批量点赞 / 收藏未浏览过的模型
 *   × 自动发布社区评论
 *
 * 免密原理：通过 opencli 的浏览器桥接复用本地 Chrome 已登录 Session，
 *          脚本内不含任何账号、密码或 Cookie。
 *
 * 幂等：同一天重复运行不会重复领取（平台侧按日发放），脚本只做核对与记录。
 */

'use strict';

const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');

const ROOT = __dirname;
const CFG = JSON.parse(fs.readFileSync(path.join(ROOT, 'config.json'), 'utf8'));
const LOG_DIR = path.join(ROOT, 'logs');
if (!fs.existsSync(LOG_DIR)) fs.mkdirSync(LOG_DIR, { recursive: true });

/* ---------------- 工具 ---------------- */

// 平台按北京时间结算，本机时区可能不是 CST，必须显式换算
function todayCN() {
  return new Intl.DateTimeFormat('en-CA', {
    timeZone: CFG.timeZone,
    year: 'numeric', month: '2-digit', day: '2-digit',
  }).format(new Date());
}

function nowStamp() {
  return new Intl.DateTimeFormat('zh-CN', {
    timeZone: CFG.timeZone,
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
  }).format(new Date());
}

const runLog = [];
// 本脚本自己打开的标签页 targetId，收尾时定向关闭
let SELF_TAB = null;

function log(msg) {
  const line = `[${nowStamp()}] ${msg}`;
  runLog.push(line);
  console.log(line);
}

// opencli 的 stdout 会混入 node 实验性警告，需剥离后再解析
function stripNoise(s) {
  return s
    .split('\n')
    .filter((l) => !/^\(node:\d+\)/.test(l) && !/^\(Use `node --trace-warnings/.test(l))
    .join('\n')
    .trim();
}

/**
 * 解析 opencli 的调用方式。
 * 首选：用 node 直接执行包入口 dist/src/main.js —— 绕开 Windows 下
 *       .cmd 包装器 + shell:true 带来的引号/转义破坏（eval 传的是 JS 源码，
 *       一旦被 shell 二次解析就会损坏）。
 * 兜底：直接调 opencli(.cmd)，需要 shell。
 */
function resolveOpencli() {
  const candidates = [
    CFG.opencliEntry,
    path.join(process.env.APPDATA || '', 'npm/node_modules/@jackwener/opencli/dist/src/main.js'),
    path.join(process.env.APPDATA || '', 'npm/node_modules/opencli/dist/src/main.js'),
  ].filter(Boolean);

  for (const c of candidates) {
    if (c && fs.existsSync(c)) return { mode: 'node', entry: c };
  }
  return { mode: 'cmd', entry: CFG.opencliBin || 'opencli' };
}

const OPENCLI = resolveOpencli();

function opencli(args, timeoutMs = 120000) {
  const opts = {
    encoding: 'utf8',
    timeout: timeoutMs,
    windowsHide: true,
    maxBuffer: 32 * 1024 * 1024,
    // 捕获 stderr，避免 node 实验性警告污染计划任务日志
    stdio: ['ignore', 'pipe', 'pipe'],
  };
  try {
    let out;
    if (OPENCLI.mode === 'node') {
      out = execFileSync(process.execPath, [OPENCLI.entry, ...args], opts);
    } else {
      out = execFileSync(OPENCLI.entry, args, { ...opts, shell: true });
    }
    return { ok: true, out: stripNoise(out) };
  } catch (e) {
    const detail = stripNoise([e.stdout, e.stderr, e.message].filter(Boolean).join('\n'));
    return { ok: false, out: detail };
  }
}

function browser(cmdArgs, timeoutMs) {
  return opencli(['browser', CFG.session, ...cmdArgs], timeoutMs);
}

// 在页面上下文里发同源 fetch，复用浏览器 Cookie
function pageFetchJSON(apiPath) {
  // 浏览器侧用 r.text() 而非 r.json()：接口返回非 JSON（如 HTML 登录页）时
  // 不会抛 "Failed to execute 'json' on 'Response'"；文本交给下方容错解析。
  const js = `fetch(${JSON.stringify(apiPath)},{credentials:'include'}).then(r=>r.text()).then(t=>JSON.stringify({__text:t})).catch(e=>JSON.stringify({__err:String(e)}))`;
  const r = browser(['eval', js]);
  if (!r.ok) return { __err: r.out };
  const body = r.out;
  const start = body.indexOf('{');
  if (start < 0) return { __err: 'no json in output: ' + body.slice(0, 200) };
  // opencli eval 偶发在 JSON 后附尾随行（更新提示等）：截取到第一个完整 JSON
  // 对象的结束，忽略其后的非空白尾巴，避免 "Unexpected non-whitespace character
  // after JSON" 类报错。
  let obj;
  try {
    obj = JSON.parse(body.slice(start));
  } catch (e) {
    const m = body.slice(start).match(/\{[\s\S]*?\}(?=\s|$)/);
    if (!m) return { __err: 'parse fail: ' + body.slice(start, start + 200) };
    try { obj = JSON.parse(m[0]); } catch (e2) {
      return { __err: 'parse fail: ' + body.slice(start, start + 200) };
    }
  }
  if (obj.__err) return { __err: obj.__err };
  if (obj.__text !== undefined) {
    try { return JSON.parse(obj.__text); } catch (e) {
      return { __err: 'not json: ' + obj.__text.slice(0, 200) };
    }
  }
  return obj;
}

function sleep(sec) {
  Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, sec * 1000);
}

/* ---------------- 主流程 ---------------- */

function main() {
  const day = todayCN();
  const result = {
    date_cn: day,
    ran_at: nowStamp(),
    bridge_ok: false,
    granted: {},
    all_granted: false,
    balance: null,
    recent_spend: [],
    notes: [],
  };

  // 1) 桥接自检
  const doc = opencli(['doctor'], 60000);
  if (!doc.ok || !/Daemon: running/.test(doc.out)) {
    log('桥接不可用，中止。请确认 Chrome 已启动且 opencli 扩展在线。');
    log(doc.out.slice(0, 500));
    result.notes.push('opencli 桥接不可用');
    finish(result, 2);
    return;
  }
  result.bridge_ok = true;
  log('桥接正常（daemon + 扩展在线）');

  // 2) 唤起站点，触发每日发放；失败或未到账则按 retry 重试
  let attempt = 0;
  let balance = null;
  let txns = [];

  while (attempt <= CFG.retry) {
    const url = attempt === 0 ? CFG.urls.primary : CFG.urls.fallback;
    log(`第 ${attempt + 1} 次唤起：${url}`);
    const opened = browser(['open', url, '--window', 'background'], 120000);
    if (!opened.ok) {
      log('页面打开失败：' + opened.out.slice(0, 200));
      attempt++;
      continue;
    }
    // 记录本脚本自己开的 tab，收尾时只关这一个，绝不影响用户其它窗口
    const m = opened.out.match(/"page"\s*:\s*"([^"]+)"/);
    if (m) SELF_TAB = m[1];
    sleep(CFG.waitSecondsAfterOpen);

    const bal = pageFetchJSON(CFG.api.balance);
    const tx = pageFetchJSON(CFG.api.transactions);

    if (bal.__err || !bal.success) {
      log('余额接口异常（可能未登录）：' + JSON.stringify(bal).slice(0, 200));
      attempt++;
      continue;
    }
    balance = bal.data;
    txns = (tx && tx.data && tx.data.records) || [];

    // 校验当日「每日发放」是否到账
    const granted = {};
    for (const rule of CFG.expectDailyRules) {
      const hit = txns.find(
        (r) => r.gmt_created === day && r.type === 'EARN' && r.rule_key === rule.rule_key
      );
      granted[rule.rule_key] = {
        label: rule.label,
        expect: rule.expect,
        got: hit ? hit.total_amount : 0,
        ok: !!hit,
        expire_at: hit ? hit.expire_at : null,
      };
    }
    result.granted = granted;
    result.all_granted = Object.values(granted).every((g) => g.ok);

    if (result.all_granted) {
      log('每日魔粒已全部到账');
      break;
    }
    log('尚有未到账项，准备重试：' + Object.values(granted).filter((g) => !g.ok).map((g) => g.label).join('、'));
    attempt++;
  }

  if (!balance) {
    result.notes.push('未能读取余额，疑似登录态失效——请在本地 Chrome 手动登录一次魔搭');
    log(result.notes[result.notes.length - 1]);
    finish(result, 3);
    return;
  }

  result.balance = balance;

  // 3) 近 7 天消耗统计（用于利用率提示）
  const spend = txns.filter((r) => r.type === 'SPEND_CONFIRM');
  result.recent_spend = spend.slice(0, 7).map((r) => ({
    date: r.gmt_created,
    amount: r.total_amount,
    count: r.count,
    tier: r.model_tier || '',
  }));

  if (!result.all_granted) {
    result.notes.push('部分每日魔粒未到账，可能是平台发放延迟或规则调整，建议人工核查一次');
  }

  finish(result, result.all_granted ? 0 : 1);
}

/* ---------------- 输出 ---------------- */

function finish(result, exitCode) {
  const day = result.date_cn;

  // 收尾：只关闭本脚本开的那个标签页（按 targetId 定向），不动用户其它窗口
  if (CFG.closeTabAfterRun && SELF_TAB) {
    const c = opencli(['browser', CFG.session, 'tab', 'close', SELF_TAB], 30000);
    log(c.ok ? '已关闭本次运行创建的标签页' : '标签页关闭失败（可忽略）');
  }

  // 结构化日志（按日一份）
  fs.writeFileSync(
    path.join(LOG_DIR, `${day}.json`),
    JSON.stringify(result, null, 2),
    'utf8'
  );

  // 运行流水（追加）
  fs.appendFileSync(path.join(LOG_DIR, 'run.log'), runLog.join('\n') + '\n', 'utf8');

  // 人类可读日报（覆盖最新一份）
  fs.writeFileSync(path.join(LOG_DIR, '魔粒日报.md'), renderReport(result), 'utf8');

  log(`完成，退出码 ${exitCode}`);
  process.exit(exitCode);
}

function renderReport(r) {
  const L = [];
  L.push(`# 魔搭魔粒日报 · ${r.date_cn}`);
  L.push('');
  L.push(`运行时间（北京时间）：${r.ran_at}`);
  L.push('');

  L.push('## 每日发放到账');
  L.push('');
  L.push('| 项目 | 应发 | 实发 | 状态 | 过期时间 |');
  L.push('|---|---:|---:|:--:|---|');
  let total = 0;
  for (const g of Object.values(r.granted)) {
    total += g.got || 0;
    L.push(`| ${g.label} | ${g.expect} | ${g.got} | ${g.ok ? '✅' : '⏳'} | ${g.expire_at || '—'} |`);
  }
  L.push(`| **合计** | **250** | **${total}** | ${r.all_granted ? '✅' : '⏳'} | — |`);
  L.push('');

  if (r.balance) {
    L.push('## 账户余额');
    L.push('');
    L.push(`- 总余额：**${r.balance.total_balance}** 魔粒（可用 ${r.balance.available_balance}，冻结 ${r.balance.frozen_amount}）`);
    L.push(`- 最近一批过期：**${r.balance.nearest_expiry_amount}** 魔粒 @ ${r.balance.nearest_expiry_at}`);
    L.push(`- 账户等级：${r.balance.user_level}`);
    L.push('');
  }

  if (r.recent_spend.length) {
    L.push('## 近期消耗');
    L.push('');
    L.push('| 日期 | 消耗魔粒 | 调用次数 | 模型档位 |');
    L.push('|---|---:|---:|---|');
    for (const s of r.recent_spend) {
      L.push(`| ${s.date} | ${s.amount} | ${s.count} | ${s.tier} |`);
    }
    L.push('');

    const days = r.recent_spend.length;
    const avg = r.recent_spend.reduce((a, b) => a + (b.amount || 0), 0) / days;
    const waste = Math.max(0, 250 - avg);
    const pct = ((waste / 250) * 100).toFixed(1);
    L.push('## 额度利用率');
    L.push('');
    L.push(`- 近 ${days} 天日均消耗：**${avg.toFixed(1)}** 魔粒`);
    L.push(`- 每日白给额度：**250** 魔粒（旗舰模型 2 粒/次 ≈ **125 次**调用）`);
    L.push(`- 日均闲置过期：约 **${waste.toFixed(1)}** 魔粒（**${pct}%**）`);
    L.push('');
    if (waste > 100) {
      L.push(`> 每天有 ${pct}% 的免费额度未使用就过期。魔粒为短期额度（24 小时），攒不下来。`);
      L.push('> 优先考虑把这部分额度接进实际项目消费，而不是去争取更多额度。');
      L.push('');
    }
  }

  if (r.notes.length) {
    L.push('## 提示');
    L.push('');
    for (const n of r.notes) L.push(`- ${n}`);
    L.push('');
  }

  L.push('---');
  L.push('');
  L.push('本脚本仅执行「登录态保活 + 到账核对 + 额度播报」，不含批量点赞与自动评论。');
  return L.join('\n');
}

main();
