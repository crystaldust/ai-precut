// 剪辑台 · 平台文案（M16）：按浏览器 UA 判断是不是 Windows，给界面文案选 Mac / Windows 版本。
// 必须先于 jobs.js / support.js / step-export.js 加载。没有 navigator（测试沙箱、非浏览器环境）一律当 Mac。
const IS_WIN = typeof navigator !== 'undefined' && /Windows/.test(navigator.userAgent || '');
function platformCopy(mac, win){ return IS_WIN ? win : mac; }
