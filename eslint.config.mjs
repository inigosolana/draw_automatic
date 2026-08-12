// Config ESLint para el JS de front (static/js). El objetivo principal es la
// regla no-undef: caza variables usadas fuera de su ámbito (p. ej. una const
// definida en otro IIFE), que fue el fallo que dejaba la subida a GLPI colgada.
const G = {};
[
  // navegador
  "window","document","fetch","FormData","console","setTimeout","clearTimeout",
  "setInterval","clearInterval","localStorage","sessionStorage","location","navigator",
  "alert","confirm","prompt","URL","URLSearchParams","Blob","FileReader","File","FileList",
  "Image","Event","CustomEvent","XMLHttpRequest","HTMLElement","Node","NodeList","MutationObserver",
  "requestAnimationFrame","cancelAnimationFrame","atob","btoa","structuredClone","getComputedStyle",
  "DOMParser","XMLSerializer","Option","AbortController","TextDecoder","TextEncoder","history","screen",
  // ECMAScript
  "Promise","Map","Set","WeakMap","WeakSet","JSON","Math","Date","Array","Object","String","Number",
  "Boolean","RegExp","Error","Symbol","Proxy","Reflect","BigInt","Intl","parseInt","parseFloat","isNaN",
  "isFinite","encodeURIComponent","decodeURIComponent","encodeURI","decodeURI","globalThis",
  // librerias de terceros cargadas por <script>
  "Chart"
].forEach(k => (G[k] = "readonly"));
export default [
  { ignores: ["static/js/**/*.min.js", "static/js/chart-*.js"] },
  {
    files: ["static/js/**/*.js"],
    languageOptions: { ecmaVersion: 2022, sourceType: "script", globals: G },
    rules: { "no-undef": "error", "no-unused-vars": "off" }
  }
];
