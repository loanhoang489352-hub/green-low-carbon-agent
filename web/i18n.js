/**
 * Web UI i18n — P6.L
 *
 * 用法:
 *   1. 在 HTML 加 <script src="/i18n.js"></script>
 *   2. 标记关键元素: <h1 data-i18n="ui.title">绿色低碳智能体</h1>
 *   3. 浮动切换器(右上角)自动注入,点中/En 即时切换
 *   4. 选中语言存 localStorage 跨刷新保留
 */
(function () {
  "use strict";

  // ========== 翻译字典(与 src/i18n/__init__.py 同步) ==========
  const I18N = {
    zh: {
      "ui.title": "绿色低碳智能体",
      "ui.subtitle": "个性化低碳生活助手",
      "ui.welcome": "🌱 欢迎使用绿色低碳助手",
      "ui.intro": "你好!我是绿色低碳智能体,可以帮你了解环保知识、推荐低碳行动、分析碳足迹。",
      "ui.chat_placeholder": "输入你的问题...",
      "ui.send": "发送",
      "ui.thinking": "思考中...",
      "ui.locale_switch": "语言",
      "ui.api_key_placeholder": "输入你的 API Key...",
      "ui.model_placeholder": "留空使用默认模型,如:gpt-4o-mini",
      "ui.login": "登录",
      "ui.register": "注册",
      "ui.feedback_placeholder": "请输入您的反馈意见...",
      "ui.reason_placeholder": "补充说明(可选)...",
      "ui.logout": "退出登录",
      "ui.recommend": "为你推荐",
      "ui.knowledge_refs": "参考资料",
      "ui.profile": "个人画像",
    },
    en: {
      "ui.title": "Green Low-Carbon Agent",
      "ui.subtitle": "Personalized Low-Carbon Lifestyle Assistant",
      "ui.welcome": "🌱 Welcome to the Green Low-Carbon Agent",
      "ui.intro": "Hi! I'm your Green Low-Carbon Agent. I can help you learn about environmental topics, recommend low-carbon actions, and analyze your carbon footprint.",
      "ui.chat_placeholder": "Ask your question...",
      "ui.send": "Send",
      "ui.thinking": "Thinking...",
      "ui.locale_switch": "Language",
      "ui.api_key_placeholder": "Enter your API Key...",
      "ui.model_placeholder": "Leave empty for default model (e.g. gpt-4o-mini)",
      "ui.login": "Log in",
      "ui.register": "Sign up",
      "ui.feedback_placeholder": "Please enter your feedback...",
      "ui.reason_placeholder": "Additional notes (optional)...",
      "ui.logout": "Log out",
      "ui.recommend": "Recommended for you",
      "ui.knowledge_refs": "References",
      "ui.profile": "Profile",
    },
  };

  // ========== locale 持久化 ==========
  const STORAGE_KEY = "green_agent_locale";
  function getLocale() {
    // 优先级:localStorage > URL ?lang= > navigator.language
    const url = new URL(window.location.href);
    const urlLang = url.searchParams.get("lang");
    if (urlLang && (urlLang === "zh" || urlLang === "en")) {
      localStorage.setItem(STORAGE_KEY, urlLang);
      return urlLang;
    }
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored === "zh" || stored === "en") return stored;
    const nav = (navigator.language || "zh").toLowerCase();
    return nav.startsWith("en") ? "en" : "zh";
  }

  function setLocale(loc) {
    if (loc !== "zh" && loc !== "en") return;
    localStorage.setItem(STORAGE_KEY, loc);
    applyI18n(loc);
    // 同步 <html lang> 属性
    document.documentElement.lang = loc === "zh" ? "zh-CN" : "en";
  }

  // ========== DOM 替换 ==========
  function applyI18n(loc) {
    const dict = I18N[loc] || I18N.zh;

    // 0. P6.P: <title>(P6.L 之前没改,补)
    if (dict["ui.title"]) document.title = dict["ui.title"];

    // 1. data-i18n 元素(替换 textContent)
    document.querySelectorAll("[data-i18n]").forEach((el) => {
      const key = el.getAttribute("data-i18n");
      const txt = dict[key];
      if (txt !== undefined) el.textContent = txt;
    });

    // 2. data-i18n-placeholder 元素(替换 placeholder)
    document.querySelectorAll("[data-i18n-placeholder]").forEach((el) => {
      const key = el.getAttribute("data-i18n-placeholder");
      const txt = dict[key];
      if (txt !== undefined) el.setAttribute("placeholder", txt);
    });

    // 3. 同步切换器状态
    const sel = document.getElementById("lang-switcher-select");
    if (sel) sel.value = loc;

    // 4. 写 cookie 供后端 Accept-Language 用
    document.cookie = `lang=${loc}; path=/; max-age=31536000`;
  }

  // ========== 浮动语言切换器 ==========
  function injectSwitcher() {
    if (document.getElementById("lang-switcher")) return; // 避免重复注入
    const wrap = document.createElement("div");
    wrap.id = "lang-switcher";
    wrap.style.cssText = [
      "position:fixed",
      "top:20px",
      "right:130px",  // P6.S.2 fix: 让出设置按钮(api-key-btn 在 right:20px)
      "z-index:99",   // 比设置按钮(z-index:100)低,防止遮挡
      "background:rgba(255,255,255,0.95)",
      "border-radius:20px",
      "padding:4px 10px",
      "box-shadow:0 2px 8px rgba(0,0,0,0.15)",
      "font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif",
      "font-size:13px",
      "user-select:none",
      "display:flex",
      "align-items:center",
      "gap:6px",
    ].join(";");
    wrap.innerHTML =
      '<span style="color:#666;">🌐</span>' +
      '<select id="lang-switcher-select" style="border:none;background:transparent;cursor:pointer;font-size:13px;outline:none;">' +
      '<option value="zh">中文</option>' +
      '<option value="en">English</option>' +
      "</select>";
    wrap.querySelector("select").addEventListener("change", (e) => {
      setLocale(e.target.value);
    });
    document.body.appendChild(wrap);
  }

  // ========== fetch 包装:自动带 Accept-Language ==========
  function patchFetch() {
    if (window.__i18nFetchPatched) return;
    const origFetch = window.fetch.bind(window);
    window.fetch = function (input, init) {
      init = init || {};
      init.headers = init.headers || {};
      const loc = getLocale();
      // 设 Accept-Language(后端会读它返对应 locale 错误消息)
      if (typeof init.headers.set === "function") {
        // Headers 对象
        if (!init.headers.has("Accept-Language")) {
          init.headers.set("Accept-Language", loc);
        }
      } else {
        // 数组或普通对象
        const keys = Object.keys(init.headers).map((k) => k.toLowerCase());
        if (!keys.includes("accept-language")) {
          init.headers["Accept-Language"] = loc;
        }
      }
      return origFetch(input, init);
    };
    window.__i18nFetchPatched = true;
  }

  // ========== 初始化 ==========
  function init() {
    const loc = getLocale();
    document.documentElement.lang = loc === "zh" ? "zh-CN" : "en";
    patchFetch();
    injectSwitcher();
    applyI18n(loc);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
