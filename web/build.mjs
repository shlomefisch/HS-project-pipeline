// Builds the installable web app into dist/.
//   node build.mjs           production build
//   node build.mjs --serve   rebuild on change, served on :5173, API proxied to :8000
import * as esbuild from "esbuild";
import { cpSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { createHash } from "node:crypto";
import http from "node:http";

const serve = process.argv.includes("--serve");
const out = "dist";

rmSync(out, { recursive: true, force: true });
mkdirSync(`${out}/assets`, { recursive: true });
cpSync("public", out, { recursive: true });

const options = {
  entryPoints: ["src/main.tsx"],
  bundle: true,
  minify: !serve,
  sourcemap: true,
  target: ["es2020", "chrome100"],
  jsx: "automatic",
  outdir: `${out}/assets`,
  entryNames: serve ? "[name]" : "[name]-[hash]",
  metafile: true,
  loader: { ".css": "css" },
  define: { "process.env.NODE_ENV": JSON.stringify(serve ? "development" : "production") },
  logLevel: "info",
};

function writeIndex(metafile) {
  const outputs = Object.keys(metafile.outputs);
  const js = outputs.find((f) => f.endsWith(".js")).replace(`${out}/`, "");
  const css = outputs.find((f) => f.endsWith(".css"));
  const html = readFileSync("public/index.html", "utf8")
    .replace("<!--CSS-->", css ? `<link rel="stylesheet" href="/${css.replace(`${out}/`, "")}">` : "")
    .replace("<!--JS-->", `<script type="module" src="/${js}"></script>`);
  writeFileSync(`${out}/index.html`, html);
  // A new build changes the service worker, so phones pick up the update.
  const version = createHash("sha1").update(outputs.join("|")).digest("hex").slice(0, 10);
  const sw = readFileSync("public/sw.js", "utf8").replace("__VERSION__", version);
  writeFileSync(`${out}/sw.js`, sw);
}

if (!serve) {
  const result = await esbuild.build(options);
  writeIndex(result.metafile);
} else {
  const ctx = await esbuild.context({
    ...options,
    plugins: [{ name: "index", setup(b) { b.onEnd((r) => r.metafile && writeIndex(r.metafile)); } }],
  });
  await ctx.watch();
  const { port } = await ctx.serve({ servedir: out, port: 5174 });
  http
    .createServer((req, res) => {
      const toApi = req.url.startsWith("/api/");
      const target = toApi ? { port: 8000 } : { port };
      const isAsset = /\.[a-z0-9]+$/i.test(req.url.split("?")[0]);
      const path = toApi || isAsset ? req.url : "/index.html";
      const p = http.request({ hostname: "127.0.0.1", ...target, path, method: req.method, headers: req.headers }, (r) => {
        res.writeHead(r.statusCode, r.headers);
        r.pipe(res);
      });
      req.pipe(p);
    })
    .listen(5173, () => console.log("App on http://localhost:5173 (API proxied to :8000)"));
}
