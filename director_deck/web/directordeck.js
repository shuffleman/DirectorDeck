// DirectorDeck 前端面板（M4）
//
// 目标：把“导演台”的高频操作变成按钮，不用记节点名、不用手拉线：
// - 添加下一段：复制当前段的模型/配置/剧本连线，接上 previous_segment，policy 自动填好
// - 添加素材覆盖 / 锁音 / 段级剧本：一键创建子节点并接到当前段，policy 自动切 replace
// - 重抽选中段：换种子并立刻排队
// - 查看段清单：从后端 /directordeck/segments 拉最近生成记录
// - 底部状态：显示当前执行到哪个节点（翻成中文提示）
//
// 说明：这里只依赖 ComfyUI 前端公开的 app / api / LiteGraph，不碰内部实现，
// 前端升级时最多是小修；代码注释保持口语化中文。

import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

const PREFIX = "DirectorDeck_";
const TAKE = PREFIX + "DirectorTake";

// ------------------------------------------------------------------ i18n
const I18N = {
  zh: {
    panel: "DirectorDeck 导演台",
    addNext: "添加下一段",
    addAssets: "加素材覆盖",
    addVoice: "加数字人锁音",
    addBrief: "加段级剧本",
    reroll: "重抽选中段",
    segments: "查看段清单",
    mixMode: "切换混音模式",
    duckDown: "duck -2dB",
    duckUp: "duck +2dB",
    help: "帮助",
    close: "关闭",
    needTake: "请先选中一个“视频生成器”节点（或先创建一个）",
    noNode: "没找到可操作的节点",
    done: "完成",
    failed: "失败",
    statusIdle: "空闲",
    statusRunning: "正在执行：",
    nextAdded: "已添加第 N 段，policy 全填 inherit/guide_tail",
    overrideAdded: "已添加覆盖节点并把 policy 切到 replace",
    rerolled: "已换种子并排队重抽",
    mixCycled: "混音模式：",
    duckChanged: "duck 电平：",
    needMixNode: "请先选中“数字人锁音器”（或接到它的视频生成器）",
    helpText:
      "用法：\n1) 先放好 模型加载器 / 全局配置 / 剧本加载器 / 视频生成器；\n2) 选中某个“视频生成器”，点“添加下一段”自动接链；\n3) 想单独换素材/音色/剧本，点对应按钮，会把 policy 自动切到 replace；\n4) 想重抽某段，选中它点“重抽选中段”。",
  },
  en: {
    panel: "DirectorDeck",
    addNext: "Add next segment",
    addAssets: "Add asset override",
    addVoice: "Add voice lock",
    addBrief: "Add segment brief",
    reroll: "Reroll selected",
    segments: "Segment history",
    mixMode: "Cycle mix mode",
    duckDown: "duck -2dB",
    duckUp: "duck +2dB",
    help: "Help",
    close: "Close",
    needTake: "Select a DirectorTake node first",
    noNode: "No target node found",
    done: "Done",
    failed: "Failed",
    statusIdle: "Idle",
    statusRunning: "Running: ",
    nextAdded: "Next segment added (policies: inherit / guide_tail)",
    overrideAdded: "Override node added (policy set to replace)",
    rerolled: "Seed changed and queued",
    mixCycled: "Mix mode: ",
    duckChanged: "Duck level: ",
    needMixNode: "Select a VoiceLock (or a Take connected to one) first",
    helpText:
      "Workflow:\n1) Place ModelLoader / Config / ScriptDesk / DirectorTake;\n2) Select a DirectorTake and click 'Add next segment' to chain it;\n3) Click override buttons to add assets/voice/brief nodes (policy auto = replace);\n4) Select a segment and click 'Reroll' to re-generate with a new seed.",
  },
};

let lang = (navigator.language || "zh").toLowerCase().startsWith("zh") ? "zh" : "en";
function t(key) {
  return (I18N[lang] && I18N[lang][key]) || key;
}

// ------------------------------------------------------------------ 小工具
function toast(message, ok = true) {
  const el = document.createElement("div");
  el.textContent = message;
  el.style.cssText = [
    "position:fixed", "right:20px", "bottom:24px", "z-index:99999",
    "padding:10px 14px", "border-radius:8px", "font-size:13px",
    "font-family:system-ui,sans-serif", "color:#fff", "max-width:420px",
    "box-shadow:0 4px 16px rgba(0,0,0,.35)",
    `background:${ok ? "#1f7a4d" : "#a33a3a"}`,
  ].join(";");
  document.body.appendChild(el);
  setTimeout(() => el.remove(), 3200);
}

function graphNodes(type) {
  return (app.graph?._nodes || []).filter((n) => n && n.type === type);
}

function selectedTake() {
  const selected = app.canvas?.selected_nodes || {};
  for (const id of Object.keys(selected)) {
    const node = selected[id];
    if (node && node.type === TAKE) return node;
  }
  const takes = graphNodes(TAKE);
  return takes.length ? takes[takes.length - 1] : null;
}

function widget(node, name) {
  return (node?.widgets || []).find((w) => w.name === name);
}

// ComfyUI 的 combo 控件值有可能是数组/字符串，这里统一成可读字符串。
function widgetValue(node, name) {
  const w = widget(node, name);
  if (!w) return undefined;
  const v = w.value;
  return Array.isArray(v) ? v[0] : v;
}

function setWidget(node, name, value) {
  const w = widget(node, name);
  if (!w) return false;
  w.value = value;
  return true;
}

function inputIndex(node, name) {
  return (node.inputs || []).findIndex((i) => i && i.name === name);
}

function outputIndex(node, name) {
  return (node.outputs || []).findIndex((o) => o && o.name === name);
}

function linkNodes(from, fromSlot, to, toSlot) {
  const outIdx = outputIndex(from, fromSlot);
  const inIdx = inputIndex(to, toSlot);
  if (outIdx < 0 || inIdx < 0) return false;
  from.connect(outIdx, to, inIdx);
  return true;
}

function createNode(type, pos) {
  const node = LiteGraph.createNode(type);
  if (!node) throw new Error(`节点创建失败：${type}`);
  node.pos = Array.isArray(pos) ? pos : [400, 200];
  app.graph.add(node);
  return node;
}

// 把上一段节点的某个输入“上游”原样接到新节点（模型/配置/剧本这种共享输入）。
function copyUpstream(sourceNode, targetNode, inputName) {
  const idx = inputIndex(sourceNode, inputName);
  if (idx < 0) return false;
  const linkId = sourceNode.inputs[idx]?.link;
  if (linkId == null) return false;
  const link = app.graph?.links?.[linkId] || app.graph.links?.[String(linkId)];
  if (!link) return false;
  const origin = app.graph.getNodeById(link.origin_id);
  if (!origin) return false;
  const targetIdx = inputIndex(targetNode, inputName);
  if (targetIdx < 0) return false;
  origin.connect(link.origin_slot, targetNode, targetIdx);
  return true;
}

// ------------------------------------------------------------------ 操作
function addNextSegment() {
  const take = selectedTake();
  if (!take) return toast(t("needTake"), false);
  const current = Number(widgetValue(take, "segment_index") || 1);
  const next = current + 1;
  const pos = [take.pos[0] + (take.size ? take.size[0] : 320) + 80, take.pos[1]];
  const node = createNode(TAKE, pos);

  // 新段的参数：模型/配置/剧本/素材/音色都沿用上一段，画面接上去。
  setWidget(node, "segment_index", next);
  setWidget(node, "bundle_policy", "inherit");
  setWidget(node, "config_policy", "inherit");
  setWidget(node, "assets_policy", "inherit");
  setWidget(node, "brief_policy", "inherit");
  setWidget(node, "cast_policy", "inherit");
  setWidget(node, "continuity", "guide_tail");
  setWidget(node, "seed", 0);

  for (const name of ["bundle", "config", "script"]) {
    copyUpstream(take, node, name);
  }
  linkNodes(take, "segment", node, "previous_segment");
  app.graph.setDirtyCanvas(true, true);
  toast(`${t("done")}: ${t("nextAdded").replace("N", String(next))}`);
}

function addOverride(kind) {
  const take = selectedTake();
  if (!take) return toast(t("needTake"), false);
  const configs = {
    assets: {
      type: PREFIX + "AssetShelf",
      policy: "assets_policy",
      input: "assets",
      output: "assets",
      pos: [take.pos[0] - 360, take.pos[1] - 160],
    },
    voice: {
      type: PREFIX + "VoiceLock",
      policy: "cast_policy",
      input: "cast",
      output: "cast",
      pos: [take.pos[0] - 360, take.pos[1] + 60],
    },
    brief: {
      type: PREFIX + "SegmentBrief",
      policy: "brief_policy",
      input: "brief",
      output: "brief",
      pos: [take.pos[0] - 360, take.pos[1] + 280],
    },
  }[kind];
  if (!configs) return;
  const node = createNode(configs.type, configs.pos);
  setWidget(take, configs.policy, "replace");
  if (!linkNodes(node, configs.output, take, configs.input)) {
    return toast(t("failed") + `: ${configs.input}`, false);
  }
  app.graph.setDirtyCanvas(true, true);
  toast(`${t("done")}: ${t("overrideAdded")}`);
}

function rerollSelected() {
  const take = selectedTake();
  if (!take) return toast(t("needTake"), false);
  const w = widget(take, "seed");
  if (!w) return toast(t("failed"), false);
  // 用 53 位安全整数随机种子，够大且不会丢精度。
  w.value = Math.floor(Math.random() * Number.MAX_SAFE_INTEGER);
  app.graph.setDirtyCanvas(true, true);
  app.queuePrompt(0, 1);
  toast(t("rerolled"));
}

function showDialog(title, contentBuilder) {
  const overlay = document.createElement("div");
  overlay.style.cssText = [
    "position:fixed", "inset:0", "z-index:99998", "background:rgba(0,0,0,.55)",
    "display:flex", "align-items:center", "justify-content:center",
  ].join(";");
  const box = document.createElement("div");
  box.style.cssText = [
    "background:#1f2126", "color:#e6e6e6", "border:1px solid #3a3d44",
    "border-radius:10px", "padding:16px", "width:min(820px,88vw)",
    "max-height:80vh", "overflow:auto", "font-family:system-ui,sans-serif",
    "font-size:13px", "box-shadow:0 12px 40px rgba(0,0,0,.5)",
  ].join(";");
  box.innerHTML = `<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px">
      <b style="font-size:15px">${title}</b>
      <button id="dd-close" style="background:#33363d;color:#ddd;border:1px solid #4a4e57;border-radius:6px;padding:4px 10px;cursor:pointer">${t("close")}</button>
    </div><div id="dd-body" style="white-space:pre-wrap;line-height:1.6"></div>`;
  overlay.appendChild(box);
  document.body.appendChild(overlay);
  const body = box.querySelector("#dd-body");
  contentBuilder(body);
  box.querySelector("#dd-close").onclick = () => overlay.remove();
  overlay.onclick = (event) => {
    if (event.target === overlay) overlay.remove();
  };
}

async function showSegments() {
  try {
    const response = await api.fetchApi("/directordeck/segments?limit=20");
    const data = await response.json();
    const rows = (data.segments || []).map((s, i) => {
      const lock = s.lock && s.lock.applied ? "🔒" : "";
      const refine = s.refined ? "✨" : "";
      return `${i + 1}. 第${s.index ?? "?"}段 | seed=${s.seed ?? "-"} | ${s.frames ?? "-"}帧 | ${s._mtime} ${lock}${refine}`;
    });
    showDialog(t("segments"), (body) => {
      body.textContent = rows.length ? rows.join("\n") : "（还没有段记录，先跑一次生成）";
    });
  } catch (error) {
    toast(`${t("failed")}: ${error}`, false);
  }
}

function showHelp() {
  showDialog(t("panel"), (body) => {
    body.textContent = t("helpText");
  });
}

// ------------------------------------------------------------------ 混音快捷控件
// 目标：不用点开锁音器，直接改 mix_mode / duck_db（对选中段或它接的 VoiceLock 生效）。
const MIX_MODES = ["auto_duck", "priority", "sum"];

function selectedMixNode() {
  // 1) 选中的就是锁音器
  const selected = app.canvas?.selected_nodes || {};
  for (const id of Object.keys(selected)) {
    const node = selected[id];
    if (node && node.type === "DirectorDeck_VoiceLock") return node;
  }
  // 2) 选中的是生成器：顺着 cast 输入找到上游锁音器
  const take = selectedTake();
  if (take) {
    const idx = inputIndex(take, "cast");
    if (idx >= 0) {
      const linkId = take.inputs[idx]?.link;
      if (linkId != null) {
        const link = app.graph.links?.[linkId];
        const origin = link ? app.graph.getNodeById(link.origin_id) : null;
        if (origin && origin.type === "DirectorDeck_VoiceLock") return origin;
      }
    }
  }
  // 3) 兜底：画布上最后一个锁音器
  const locks = graphNodes("DirectorDeck_VoiceLock");
  return locks.length ? locks[locks.length - 1] : null;
}

function cycleMixMode() {
  const node = selectedMixNode();
  if (!node) return toast(t("needMixNode"), false);
  const widgetRef = widget(node, "mix_mode");
  if (!widgetRef) return toast(t("failed"), false);
  const current = String(widgetRef.value || "auto_duck");
  const next = MIX_MODES[(MIX_MODES.indexOf(current) + 1) % MIX_MODES.length];
  widgetRef.value = next;
  app.graph.setDirtyCanvas(true, true);
  toast(`${t("mixCycled")}${next}`);
}

function adjustDuck(delta) {
  const node = selectedMixNode();
  if (!node) return toast(t("needMixNode"), false);
  const widgetRef = widget(node, "duck_db");
  if (!widgetRef) return toast(t("failed"), false);
  const value = Math.max(-24, Math.min(0, Number(widgetRef.value || -8) + delta));
  widgetRef.value = Math.round(value * 2) / 2;
  app.graph.setDirtyCanvas(true, true);
  toast(`${t("duckChanged")}${widgetRef.value}dB`);
}

// ------------------------------------------------------------------ 面板 UI
function buildPanel() {
  const panel = document.createElement("div");
  panel.id = "directordeck-panel";
  panel.style.cssText = [
    "position:fixed", "right:16px", "top:96px", "z-index:99997",
    "background:rgba(24,26,31,.94)", "border:1px solid #3a3d44",
    "border-radius:10px", "padding:10px", "display:flex",
    "flex-direction:column", "gap:6px", "width:170px",
    "font-family:system-ui,sans-serif", "box-shadow:0 8px 24px rgba(0,0,0,.4)",
  ].join(";");

  const title = document.createElement("div");
  title.textContent = t("panel");
  title.style.cssText = "color:#d8dbe2;font-size:12px;font-weight:600;margin-bottom:2px;cursor:pointer";
  panel.appendChild(title);

  const buttons = [
    [() => t("addNext"), addNextSegment],
    [() => t("addAssets"), () => addOverride("assets")],
    [() => t("addVoice"), () => addOverride("voice")],
    [() => t("addBrief"), () => addOverride("brief")],
    [() => t("mixMode"), cycleMixMode],
    [() => t("duckDown"), () => adjustDuck(-2)],
    [() => t("duckUp"), () => adjustDuck(2)],
    [() => t("reroll"), rerollSelected],
    [() => t("segments"), showSegments],
    [() => t("help"), showHelp],
  ];
  const labels = [];
  for (const [label, handler] of buttons) {
    const button = document.createElement("button");
    button.textContent = label();
    labels.push([button, label]);
    button.style.cssText = [
      "background:#2b2f36", "color:#e2e5ea", "border:1px solid #454a53",
      "border-radius:6px", "padding:6px 8px", "font-size:12px",
      "cursor:pointer", "text-align:left",
    ].join(";");
    button.onmouseenter = () => (button.style.background = "#363b44");
    button.onmouseleave = () => (button.style.background = "#2b2f36");
    button.onclick = handler;
    panel.appendChild(button);
  }

  // 语言切换：中文按钮负责切到英文，反之亦然。
  const langButton = document.createElement("button");
  langButton.textContent = lang === "zh" ? "EN" : "中文";
  langButton.style.cssText = [
    "margin-top:4px", "background:transparent", "color:#9aa0aa",
    "border:1px dashed #4a4e57", "border-radius:6px", "padding:3px",
    "font-size:11px", "cursor:pointer",
  ].join(";");
  langButton.onclick = () => {
    lang = lang === "zh" ? "en" : "zh";
    for (const [button, label] of labels) button.textContent = label();
    title.textContent = t("panel");
    langButton.textContent = lang === "zh" ? "EN" : "中文";
  };
  panel.appendChild(langButton);

  const status = document.createElement("div");
  status.id = "directordeck-status";
  status.textContent = t("statusIdle");
  status.style.cssText = "color:#7f8792;font-size:11px;margin-top:6px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis";
  panel.appendChild(status);

  document.body.appendChild(panel);
}

// ------------------------------------------------------------------ 注册
app.registerExtension({
  name: "DirectorDeck.Assistant",
  async setup() {
    buildPanel();

    // 执行状态：显示当前正在跑哪个节点（DirectorTake 会显示段号）。
    api.addEventListener("executing", (event) => {
      const status = document.getElementById("directordeck-status");
      if (!status) return;
      const detail = event?.detail;
      const nodeId = detail?.node ?? detail;
      if (!nodeId) {
        status.textContent = t("statusIdle");
        return;
      }
      const node = app.graph.getNodeById(Number(nodeId)) || graphNodes(TAKE).find((n) => String(n.id) === String(nodeId));
      const title = node?.title || node?.type || `#${nodeId}`;
      const index = node ? widgetValue(node, "segment_index") : undefined;
      status.textContent = `${t("statusRunning")}${title}${index ? `（第${index}段）` : ""}`;
    });
    api.addEventListener("progress", (event) => {
      const status = document.getElementById("directordeck-status");
      if (!status) return;
      const value = event?.detail?.value;
      const max = event?.detail?.max;
      if (typeof value === "number" && typeof max === "number" && max > 0) {
        status.textContent = `${t("statusRunning")}${Math.round((value / max) * 100)}%`;
      }
    });
    console.log("[DirectorDeck] 前端面板已加载");
  },
});
