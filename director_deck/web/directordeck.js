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
const SCRIPT_IMPORT = PREFIX + "ScriptImport";

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
    buildGen: "按剧本建生成器",
    buildOutput: "补全合并输出",
    needImport: "请先选中“剧本导入（素材自动匹配）”节点（或先在画布上放一个）",
    needTemplate: "请先在画布上放一个“视频生成器”作为模板（模型/配置/素材接法会复制）",
    builtGenerators: "已按剧本创建 N 段视频生成器",
    builtOutput: "已补全 FinalCut / 视频输出节点",
    noTakes: "画布上没有“视频生成器”，先放一个或点“按剧本建生成器”",
    addCutInput: "合并器 +1 段输入",
    needCut: "请先选中“多段合并器”（或先在画布上放一个）",
    cutInputAdded: "已给合并器加一组段输入",
    rerollNode: "🔄 再次生成本段",
    mergeNode: "🎬 手动合并本片",
    finalNode: "🎬 生成最终视频",
    rerolledSeg: "已为第 N 段换种子并再次生成",
    mergeQueued: "已触发一次手动合并（等待执行）",
    finalQueued: "已触发最终处理（等待执行）",
    canvasLocked: "分辨率预设生效：宽/高自动同步；要手填宽高请把“分辨率”改成“自定义（用宽高）”",
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
    buildGen: "Build Take chain",
    buildOutput: "Build merge/output",
    needImport: "Select a ScriptImport node first (or add one to the canvas)",
    needTemplate: "Place one DirectorTake as a template first (model/config/asset wiring is copied)",
    builtGenerators: "Created N Take nodes from the script",
    builtOutput: "FinalCut / video output nodes created",
    noTakes: "No DirectorTake on canvas. Add one first, or click 'Build Take chain'",
    addCutInput: "FinalCut +1 segment",
    needCut: "Select a FinalCut node first (or add one to the canvas)",
    cutInputAdded: "Added one segment input group to FinalCut",
    rerollNode: "🔄 Regenerate this segment",
    mergeNode: "🎬 Manual merge",
    finalNode: "🎬 Generate final video",
    rerolledSeg: "New seed queued for segment N",
    mergeQueued: "Manual merge queued",
    finalQueued: "Final processing queued",
    canvasLocked: "Resolution preset is active: width/height follow it. Choose '自定义（用宽高）' to edit them manually.",
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

function setInputLabel(node, name, label) {
  const w = widget(node, name);
  if (w) {
    w.label = label;
    w.localized_name = label;
  }
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
  localizeNode(node);
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

// ---------------------------------------------------------- 节点上的快捷按钮
// 用 ComfyUI 的 DOM widget 在节点本体上挂两个按钮：
// - 视频生成器：🔄 再次生成本段（换种子并排队）
// - 多段合并器：🎬 手动合并本片（merge_token +1，后端才真正合并）
function installNodeButton(node, label, handler) {
  if (!node || typeof node.addDOMWidget !== "function") return;
  node.__ddButtons = node.__ddButtons || new Set();
  if (node.__ddButtons.has(label)) return;
  const button = document.createElement("button");
  button.textContent = label;
  button.style.cssText = [
    "width:100%", "height:32px", "min-height:32px", "max-height:32px",
    "margin:2px 0", "padding:4px 8px", "box-sizing:border-box",
    "background:#2b4a6b", "color:#eaf2ff", "border:1px solid #4b6f96",
    "border-radius:6px", "font-size:12px", "cursor:pointer",
    "display:block", "flex:0 0 auto",
  ].join(";");
  button.onclick = (event) => {
    event.preventDefault();
    event.stopPropagation();
    handler();
  };
  try {
    const domWidget = node.addDOMWidget(`dd_btn_${label}`, "button", button, { serialize: false });
    if (domWidget) {
      domWidget.serialize = false;
      if (domWidget.options) domWidget.options.serialize = false;
      // ComfyUI 的 DOM widget 默认按剩余空间拉伸；这里固定 32px，别让按钮变成一大块。
      domWidget.computeSize = (width) => [width || 200, 36];
    }
    node.__ddButtons.add(label);
    const needed = node.computeSize ? node.computeSize() : null;
    if (needed && node.size && node.size[1] < needed[1]) {
      node.setSize([node.size[0], needed[1]]);
    }
    app.graph.setDirtyCanvas(true, true);
  } catch (error) {
    console.warn("[DirectorDeck] 节点按钮添加失败（不影响使用）：", error);
  }
}

function rerollTakeNode(node) {
  const seedWidget = widget(node, "seed");
  if (!seedWidget) return toast(t("failed"), false);
  // 用 53 位安全整数随机种子，够大且不会丢精度。
  seedWidget.value = Math.floor(Math.random() * Number.MAX_SAFE_INTEGER);
  setWidget(node, "cache_mode", "auto");
  app.graph.setDirtyCanvas(true, true);
  app.queuePrompt(0, 1);
  const index = widgetValue(node, "segment_index");
  toast(`${t("done")}: ${t("rerolledSeg").replace("N", String(index || "?"))}`);
}

function triggerManualMerge(node) {
  const tokenWidget = widget(node, "merge_token");
  if (!tokenWidget) return toast(t("failed"), false);
  tokenWidget.value = Number(tokenWidget.value || 0) + 1;
  app.graph.setDirtyCanvas(true, true);
  app.queuePrompt(0, 1);
  toast(t("mergeQueued"));
}

function triggerFinalVideo(node) {
  const tokenWidget = widget(node, "run_token");
  if (!tokenWidget) return toast(t("failed"), false);
  tokenWidget.value = Number(tokenWidget.value || 0) + 1;
  app.graph.setDirtyCanvas(true, true);
  app.queuePrompt(0, 1);
  toast(t("finalQueued"));
}

function installNodeActions(node) {
  const type = nodeTypeOf(node);
  if (!type) return;
  if (type === TAKE) installNodeButton(node, t("rerollNode"), () => rerollTakeNode(node));
  if (type === PREFIX + "FinalCut") installNodeButton(node, t("mergeNode"), () => triggerManualMerge(node));
  if (type === PREFIX + "FinalRefine") installNodeButton(node, t("finalNode"), () => triggerFinalVideo(node));
}

// ---------------------------------------------------------- 剧本导入 -> 自动建链
// 目标：外部剧本丢进“剧本导入”节点后，点一下就把 N 个视频生成器按段接好；
// 再点一下补全 FinalCut + 视频输出。模板节点的模型/配置/素材/音色接法会被复制。

function selectedImportNode() {
  const selected = app.canvas?.selected_nodes || {};
  for (const id of Object.keys(selected)) {
    const node = selected[id];
    if (node && node.type === SCRIPT_IMPORT) return node;
  }
  const imports = graphNodes(SCRIPT_IMPORT);
  return imports.length ? imports[imports.length - 1] : null;
}

// 从剧本导入节点的 script 控件里估段数：优先 JSON.segments，其次“第N段”/V6 段头。
function countScriptSegments(node) {
  const raw = String(widgetValue(node, "script") || "");
  try {
    const data = JSON.parse(raw);
    if (Array.isArray(data)) return Math.max(1, data.length);
    if (data && Array.isArray(data.segments)) return Math.max(1, data.segments.length);
  } catch (e) {
    // 不是 JSON，继续按文本数段头
  }
  const headers = raw.match(/第\s*(?:[0-9]{1,3}|[一二三四五六七八九十]{1,3})\s*[段幕镜场]/g);
  if (headers && headers.length) return headers.length;
  const v6 = raw.match(/【\s*第\s*\d+\s*段/g);
  if (v6 && v6.length) return v6.length;
  return 1;
}

function copyWidgets(from, to) {
  for (const w of from.widgets || []) setWidget(to, w.name, w.value);
}

// 先试模板节点已有的上游，再试剧本导入节点自己的可选输入（assets/cast 常从那边来）。
function wireShared(template, scriptNode, target, inputName) {
  if (copyUpstream(template, target, inputName)) return true;
  return copyUpstream(scriptNode, target, inputName);
}

function hasUpstream(node, inputName) {
  const idx = inputIndex(node, inputName);
  if (idx < 0) return false;
  return node.inputs[idx]?.link != null;
}

function buildGeneratorsFromScript() {
  const src = selectedImportNode();
  if (!src) return toast(t("needImport"), false);
  const template = selectedTake();
  if (!template) return toast(t("needTemplate"), false);
  const count = Math.max(1, Math.min(24, countScriptSegments(src)));

  const height = (template.size ? template.size[1] : 520) + 70;
  const takes = [template];
  for (let i = 2; i <= count; i += 1) {
    const node = createNode(TAKE, [template.pos[0], template.pos[1] + (i - 1) * height]);
    copyWidgets(template, node);
    takes.push(node);
  }

  const templateHasAssets = hasUpstream(template, "assets");
  const templateHasCast = hasUpstream(template, "cast");
  const templateHasBrief = hasUpstream(template, "brief");

  for (let i = 0; i < takes.length; i += 1) {
    const node = takes[i];
    if (i > 0) {
      copyUpstream(template, node, "bundle");
      copyUpstream(template, node, "config");
    }
    // 共享上游：模板没有的话，从剧本导入节点的 assets/cast 输入借
    for (const name of ["assets", "cast", "brief"]) wireShared(template, src, node, name);

    linkNodes(src, "script", node, "script");
    setWidget(node, "segment_index", i + 1);
    setWidget(node, "seed", 0);
    setWidget(node, "cache_mode", "auto");
    if (i === 0) {
      setWidget(node, "bundle_policy", "provided");
      setWidget(node, "config_policy", "inherit");
      setWidget(node, "assets_policy", templateHasAssets ? "replace" : "clear");
      setWidget(node, "brief_policy", templateHasBrief ? "replace" : "inherit");
      setWidget(node, "cast_policy", templateHasCast ? "replace" : "inherit");
      setWidget(node, "continuity", "start");
    } else {
      setWidget(node, "bundle_policy", "inherit");
      setWidget(node, "config_policy", "inherit");
      setWidget(node, "assets_policy", templateHasAssets ? "inherit" : "clear");
      setWidget(node, "brief_policy", "inherit");
      setWidget(node, "cast_policy", templateHasCast ? "inherit" : "inherit");
      setWidget(node, "continuity", "latent_tail");
    }
    if (i > 0) linkNodes(takes[i - 1], "segment", node, "previous_segment");
  }
  app.graph.setDirtyCanvas(true, true);
  toast(`${t("done")}: ${t("builtGenerators").replace("N", String(count))}`);
}

function buildOutputChain() {
  let takes = graphNodes(TAKE);
  if (!takes.length) return toast(t("noTakes"), false);
  takes = takes.slice().sort((a, b) => {
    return Number(widgetValue(a, "segment_index") || 0) - Number(widgetValue(b, "segment_index") || 0);
  });
  const last = takes[takes.length - 1];
  const x = last.pos[0] + (last.size ? last.size[0] : 360) + 80;
  const y = last.pos[1];

  const cut = createNode(PREFIX + "FinalCut", [x, y]);
  // 段数没有上限：Take 有几段就给 FinalCut 补几组动态输入（5、6、7...）。
  ensureCutInputs(cut, takes.length);
  setWidget(cut, "save_manifest", true);
  setWidget(cut, "audio_from_source", true);
  setWidget(cut, "audio_crossfade_ms", 80);
  takes.forEach((take, index) => {
    const suffix = `_${index + 1}`;
    linkNodes(take, "segment", cut, "segment" + suffix);
    linkNodes(take, "images", cut, "images" + suffix);
    linkNodes(take, "audio", cut, "audio" + suffix);
  });

  const video = createNode("CreateVideo", [x + 520, y]);
  setWidget(video, "fps", 24);
  linkNodes(cut, "images", video, "images");
  linkNodes(cut, "audio", video, "audio");

  const save = createNode("SaveVideo", [x + 900, y]);
  setWidget(save, "filename_prefix", "DirectorDeck/auto_chain");
  linkNodes(video, "video", save, "video");

  app.graph.setDirtyCanvas(true, true);
  toast(`${t("done")}: ${t("builtOutput")}`);
}

// ---------------------------------------------------- 合并器动态段输入（无上限）
// FinalCut 默认只声明了 4 组输入；这里可以继续加 segment_5/images_5/audio_5...
// 后端 merge(**kwargs) 会把它们收进来，所以段数只受显存限制。
const CUT = PREFIX + "FinalCut";

function selectedCut() {
  const selected = app.canvas?.selected_nodes || {};
  for (const id of Object.keys(selected)) {
    const node = selected[id];
    if (node && node.type === CUT) return node;
  }
  const cuts = graphNodes(CUT);
  return cuts.length ? cuts[cuts.length - 1] : null;
}

function cutInputCount(node) {
  let count = 1;
  for (const input of node.inputs || []) {
    const match = /^(?:segment|images|audio)_(\d+)$/.exec(input.name || "");
    if (match) count = Math.max(count, Number(match[1]));
  }
  return count;
}

function ensureCutInputs(node, target) {
  const count = Math.max(1, Number(target) || 1);
  for (let index = 1; index <= count; index += 1) {
    for (const [prefix, type] of [["segment", "DIRECTOR_SEGMENT"], ["images", "IMAGE"], ["audio", "AUDIO"]]) {
      const name = `${prefix}_${index}`;
      if (!(node.inputs || []).some((input) => input.name === name)) {
        node.addInput(name, type);
      }
    }
  }
  for (const input of node.inputs || []) {
    const match = /^(segment|images|audio)_(\d+)$/.exec(input.name || "");
    if (!match) continue;
    const suffix = match[1] === "segment" ? "段" : match[1] === "images" ? "段画面" : "段音轨";
    input.label = `第${match[2]}${suffix}`;
    input.localized_name = input.label;
  }
  const width = node.size ? node.size[0] : 420;
  node.size = [width, Math.max(node.size ? node.size[1] : 420, 140 + count * 62)];
  app.graph.setDirtyCanvas(true, true);
}

function addCutInput() {
  const cut = selectedCut();
  if (!cut) return toast(t("needCut"), false);
  ensureCutInputs(cut, cutInputCount(cut) + 1);
  toast(`${t("done")}: ${t("cutInputAdded")}`);
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
    [() => t("buildGen"), buildGeneratorsFromScript],
    [() => t("buildOutput"), buildOutputChain],
    [() => t("addCutInput"), addCutInput],
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

// ------------------------------------------------------ 参数中文名（只改显示）
// ComfyUI 的 API 字段名必须保持英文（工作流/脚本/缓存都靠它），
// 这里只改控件和插头在画布上的显示名；值（如 inherit/auto_duck）保持原样。
const NODE_INPUT_ZH = {
  DirectorDeck_ModelLoader: {
    fl2va_model: "主模型", text_encoder: "文本编码器", video_vae: "视频 VAE",
    audio_vae: "音频 VAE", weight_dtype: "权重精度", vram_tier: "显存策略",
    ref2va_model: "参考模型（可选）", lora_1: "LoRA 1", strength_1: "LoRA 1 强度",
    lora_2: "LoRA 2", strength_2: "LoRA 2 强度", lora_3: "LoRA 3",
    strength_3: "LoRA 3 强度", lora_4: "LoRA 4", strength_4: "LoRA 4 强度",
    shift_video: "视频 Shift", shift_audio: "音频 Shift",
  },
  DirectorDeck_DirectorConfig: {
    width: "宽度", height: "高度", segment_seconds: "段时长（秒）",
    handoff_frames: "衔接帧数", sampler_name: "采样器", scheduler: "调度器",
    steps: "采样步数", denoise: "去噪强度", sigmas_string: "Sigma 序列",
    interpolate_to_steps: "插值步数", seed_strategy: "种子策略",
    seed_base: "基础种子", preview: "预览", vram_policy: "显存策略",
    cleanup_segments: "段显存清理", seam_enabled: "接缝修正",
    seam_window: "接缝窗口", seam_max_add: "接缝最大补偿",
    seam_gain_limit: "接缝增益上限", output_dir: "输出目录",
    resolution: "分辨率", aspect_ratio: "画面比例",
  },
  DirectorDeck_AssetShelf: {
    image_1: "图片 1", image_2: "图片 2", image_3: "图片 3", image_4: "图片 4",
    image_5: "图片 5", image_6: "图片 6", image_7: "图片 7", image_8: "图片 8",
    image_9: "图片 9",
  },
  DirectorDeck_ScriptDesk: {
    text: "剧本文本", mode: "分段模式", default_seconds: "默认段长（秒）",
    max_segments: "最大段数", keep_header: "保留段标题", regex_pattern: "自定义分段正则",
  },
  DirectorDeck_SegmentBrief: {
    text: "段文案", seconds: "时长（秒）", dialogue: "对白", refs: "图片引用",
  },
  DirectorDeck_FramePlanner: {
    script: "剧本", config: "全局配置", keep_full: "保留完整计划",
  },
  DirectorDeck_DirectorTake: {
    bundle: "模型组合", config: "全局配置", script: "剧本", assets: "素材库（可选）",
    brief: "段级剧本", cast: "角色音色表", previous_segment: "上一段",
    segment_index: "段号", bundle_policy: "模型策略", config_policy: "配置策略",
    assets_policy: "素材策略", brief_policy: "剧本策略", cast_policy: "音色策略",
    continuity: "续写模式", seed: "种子", cache_mode: "抽卡缓存",
  },
  DirectorDeck_SeamFixer: {
    prev_images: "上一段画面", cur_images: "当前段画面", cur_head: "衔接帧数",
    enabled: "启用", window: "窗口", max_add: "最大补偿", gain_limit: "增益上限",
  },
  DirectorDeck_FinalCut: {
    segment_1: "第 1 段", images_1: "第 1 段画面", audio_1: "第 1 段音轨",
    segment_2: "第 2 段", images_2: "第 2 段画面", audio_2: "第 2 段音轨",
    segment_3: "第 3 段", images_3: "第 3 段画面", audio_3: "第 3 段音轨",
    segment_4: "第 4 段", images_4: "第 4 段画面", audio_4: "第 4 段音轨",
    save_manifest: "保存清单", audio_from_source: "源音轨无损",
    audio_crossfade_ms: "边界淡入淡出（毫秒）",
    merge_mode: "合并方式", merge_token: "合并触发 token",
  },
  DirectorDeck_SegmentCache: {
    segment: "段数据", mode: "操作", scope: "范围",
  },
  DirectorDeck_VoiceLock: {
    roles: "角色表", lock_audio: "锁音", mix_mode: "混音模式",
    duck_db: "Duck 深度（dB）", attack_ms: "压下时间（毫秒）",
    release_ms: "恢复时间（毫秒）", audio_1: "音频 1", audio_2: "音频 2",
    audio_3: "音频 3",
  },
  DirectorDeck_TTSBooth: {
    breeze_model: "TTS 模型", lines: "台词表", auto_start: "自动排期",
    auto_split: "自动分段", pause_ms: "句间停顿（毫秒）",
    chars_per_second: "预估语速", max_seconds: "单段上限（秒）",
    mix_mode: "混音模式", duck_db: "Duck 深度（dB）",
    attack_ms: "压下时间（毫秒）", release_ms: "恢复时间（毫秒）",
    cfg_scale: "指令强度", max_new_tokens: "最大音频帧数",
    temperature: "温度", top_k: "Top-K", top_p: "Top-P",
    repetition_penalty: "重复惩罚", depth_temperature: "深度温度",
    depth_top_k: "深度 Top-K", depth_top_p: "深度 Top-P", seed: "种子",
  },
  DirectorDeck_ScriptImport: {
    script: "剧本内容", format: "剧本格式", segment_seconds: "默认段长（秒）",
    match_assets: "自动匹配素材", match_scenes: "匹配场景",
    min_score: "匹配阈值", assets: "素材库", cast: "角色音色库",
  },
  DirectorDeck_Refiner: {
    bundle: "模型组合", segment: "段数据", images: "画面", audio: "音轨",
    mode: "二采模式", denoise: "去噪强度", steps: "步数",
    sampler_name: "采样器", scheduler: "调度器", upscale: "放大倍数",
  },
  DirectorDeck_FinalRefine: {
    bundle: "模型组合", images: "成片画面", audio: "成片音轨",
    mode: "处理模式", prompt: "二采提示词", seed: "种子",
    latent_denoise: "二采去噪", latent_steps: "二采步数",
    latent_sampler: "二采采样器", latent_scheduler: "二采调度器",
    refiner_lora: "二采 LoRA", refiner_lora_strength: "二采 LoRA 强度",
    relay_model: "RelayVSR 模型", relay_vae: "RelayVSR VAE",
    relay_detail: "Flash 解码细节", relay_lock_exposure: "锁定原曝光",
    lanczos_scale: "Lanczos 倍数", target_width: "目标宽度",
    target_height: "目标高度", free_vram: "处理前释放显存",
    save_video: "保存最终视频", output_dir: "输出目录",
    filename_prefix: "文件名前缀", run_mode: "执行方式", run_token: "触发 token",
    segment: "段数据（可选）", config: "全局配置（可选）",
  },
};

const NODE_OUTPUT_ZH = {
  DirectorDeck_ModelLoader: { bundle: "模型组合", summary: "摘要" },
  DirectorDeck_DirectorConfig: { config: "全局配置" },
  DirectorDeck_AssetShelf: { assets: "素材库" },
  DirectorDeck_ScriptDesk: { script: "剧本", summary: "摘要" },
  DirectorDeck_SegmentBrief: { brief: "段级剧本" },
  DirectorDeck_FramePlanner: { plan: "帧计划", summary: "摘要" },
  DirectorDeck_DirectorTake: { segment: "段数据", images: "画面", audio: "音轨" },
  DirectorDeck_SeamFixer: { images: "画面", info: "接缝信息", report: "接缝报告" },
  DirectorDeck_FinalCut: { images: "成片画面", audio: "成片音轨", manifest: "成片清单" },
  DirectorDeck_SegmentCache: { segment: "段数据", summary: "摘要", report: "缓存报告" },
  DirectorDeck_VoiceLock: { cast: "角色音色表", summary: "摘要" },
  DirectorDeck_TTSBooth: {
    cast: "角色音色表", audio_1: "音频 1", audio_2: "音频 2", audio_3: "音频 3",
    summary: "摘要", total_seconds: "总时长", segment_count: "段数", plan: "分段计划",
  },
  DirectorDeck_ScriptImport: {
    script: "剧本", script_text: "剧本正文", mapping: "匹配对照表",
    summary: "摘要", segment_count: "段数",
  },
  DirectorDeck_Refiner: { segment: "段数据", images: "画面", audio: "音轨" },
  DirectorDeck_FinalRefine: { images: "最终画面", audio: "最终音轨", report: "处理报告" },
};

// 关键：输入/输出插头的显示名要在“节点定义”阶段就写进去。
// ComfyUI 前端创建插头时读的是 input spec 的 display_name / slot 的 localized_name，
// 只在 nodeCreated 之后再改 label，Vue 渲染的插头不一定会重新取。
function patchNodeDef(nodeType, nodeData) {
  const inputMap = NODE_INPUT_ZH[nodeData.name];
  const outputMap = NODE_OUTPUT_ZH[nodeData.name];
  if (!inputMap && !outputMap) return;

  // 1) 输入 spec 直接写入 display_name（socket 和控件都会用到）。
  if (inputMap && nodeData.input) {
    for (const group of ["required", "optional"]) {
      const specs = nodeData.input[group];
      if (!specs) continue;
      for (const [name, label] of Object.entries(inputMap)) {
        const spec = specs[name];
        if (!Array.isArray(spec)) continue;
        let options = spec[1];
        if (!options || typeof options !== "object" || Array.isArray(options)) {
          options = {};
          spec[1] = options;
        }
        options.display_name = label;
        options.localized_name = label;
      }
    }
  }

  // 2) addInput / addOutput 时立刻补 label+localized_name；
  //    这样新建节点、加载工作流、动态加段输入都能在第一帧就是中文。
  const proto = nodeType.prototype;
  if (proto.__ddZhPatched) return;
  proto.__ddZhPatched = true;

  const originalAddInput = proto.addInput;
  if (inputMap && typeof originalAddInput === "function") {
    proto.addInput = function (name, type, ...rest) {
      const input = originalAddInput.call(this, name, type, ...rest);
      let label = inputMap[name];
      if (!label) {
        const match = /^(segment|images|audio)_(\d+)$/.exec(String(name || ""));
        if (match) {
          const suffix = match[1] === "segment" ? "段"
            : match[1] === "images" ? "段画面" : "段音轨";
          label = `第${match[2]}${suffix}`;
        }
      }
      if (input && label) {
        input.label = label;
        input.localized_name = label;
      }
      return input;
    };
  }

  const originalAddOutput = proto.addOutput;
  if (outputMap && typeof originalAddOutput === "function") {
    proto.addOutput = function (name, type, ...rest) {
      const output = originalAddOutput.call(this, name, type, ...rest);
      const label = outputMap[name];
      if (output && label) {
        output.label = label;
        output.localized_name = label;
      }
      return output;
    };
  }
}

function nodeTypeOf(node) {
  return (node && (node.type || node.comfyClass || node.constructor?.comfyClass)) || "";
}

function localizeNode(node) {
  const type = nodeTypeOf(node);
  if (!type || !type.startsWith(PREFIX)) return;
  const inputMap = NODE_INPUT_ZH[type];
  if (inputMap) {
    for (const w of node.widgets || []) {
      const label = inputMap[w.name];
      if (label) {
        w.label = label;
        w.localized_name = label;
      }
    }
    for (const input of node.inputs || []) {
      const label = inputMap[input.name];
      if (label) {
        input.label = label;
        input.localized_name = label;
      }
    }
  }
  const outputMap = NODE_OUTPUT_ZH[type];
  if (outputMap) {
    for (const output of node.outputs || []) {
      const label = outputMap[output.name];
      if (label) {
        output.label = label;
        output.localized_name = label;
      }
    }
  }
  if (type === "DirectorDeck_DirectorConfig") bindConfigCanvas(node);
  if (type === "DirectorDeck_FinalCut") {
    // 动态加的 segment_5... 也要有中文插头名（静态映射只覆盖到 4）。
    for (const input of node.inputs || []) {
      const match = /^(segment|images|audio)_(\d+)$/.exec(input.name || "");
      if (!match) continue;
      const suffix = match[1] === "segment" ? "段" : match[1] === "images" ? "段画面" : "段音轨";
      input.label = `第${match[2]}${suffix}`;
      input.localized_name = input.label;
    }
  }
  installNodeActions(node);
}

// 分辨率预设和 backend core/frames.py 保持一致（只用于把宽高控件同步成预设值）。
const RESOLUTION_PRESETS = {
  "480p": { "16:9 横屏": [864, 480], "9:16 竖屏": [480, 864], "1:1 方形": [480, 480] },
  "720p": { "16:9 横屏": [1280, 704], "9:16 竖屏": [704, 1280], "1:1 方形": [704, 704] },
  "768p": { "16:9 横屏": [1376, 768], "9:16 竖屏": [768, 1376], "1:1 方形": [768, 768] },
  "1080p": { "16:9 横屏": [1920, 1088], "9:16 竖屏": [1088, 1920], "1:1 方形": [1088, 1088] },
};

function syncConfigCanvas(node) {
  const resolution = String(widgetValue(node, "resolution") || "");
  const aspect = String(widgetValue(node, "aspect_ratio") || "16:9 横屏");
  const table = RESOLUTION_PRESETS[resolution];
  const preset = !!table;
  // 预设生效时把宽高标成“自动”，避免用户以为手填生效。
  setInputLabel(node, "width", preset ? "宽度（预设自动）" : "宽度");
  setInputLabel(node, "height", preset ? "高度（预设自动）" : "高度");
  setInputLabel(node, "aspect_ratio", preset ? "画面比例" : "画面比例（自定义时忽略）");
  if (!preset || !table[aspect]) return;  // 自定义/未知：保留手填宽高
  const [width, height] = table[aspect];
  setWidget(node, "width", width);
  setWidget(node, "height", height);
  app.graph.setDirtyCanvas(true, true);
}

function bindConfigCanvas(node) {
  if (node.__ddConfigBound) {
    syncConfigCanvas(node);
    return;
  }
  node.__ddConfigBound = true;
  for (const name of ["resolution", "aspect_ratio"]) {
    const w = widget(node, name);
    if (!w) continue;
    const previous = w.callback;
    w.callback = function (...args) {
      if (previous) {
        try { previous.apply(this, args); } catch (e) { console.warn(e); }
      }
      syncConfigCanvas(node);
    };
  }
  // 预设生效时，手改宽高会被立刻改回预设值（并提示一次），避免“控件和实际不一致”。
  for (const name of ["width", "height"]) {
    const w = widget(node, name);
    if (!w) continue;
    const previous = w.callback;
    w.callback = function (...args) {
      if (previous) {
        try { previous.apply(this, args); } catch (e) { console.warn(e); }
      }
      const active = !!RESOLUTION_PRESETS[String(widgetValue(node, "resolution") || "")];
      if (!active) return;
      syncConfigCanvas(node);
      const now = Date.now();
      if (!node.__ddLockToastAt || now - node.__ddLockToastAt > 2000) {
        node.__ddLockToastAt = now;
        toast(t("canvasLocked"), false);
      }
    };
  }
  syncConfigCanvas(node);
}

// ------------------------------------------------------------------ 注册
app.registerExtension({
  name: "DirectorDeck.Assistant",
  // 在节点定义阶段就把输入/输出插头名写成中文（渲染第一帧就是中文）。
  beforeRegisterNodeDef(nodeType, nodeData) {
    patchNodeDef(nodeType, nodeData);
  },
  // 新建/加载节点时把参数显示名换成中文（API 字段名仍是英文）。
  nodeCreated(node) {
    localizeNode(node);
  },
  loadedGraphNode(node) {
    localizeNode(node);
  },
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
