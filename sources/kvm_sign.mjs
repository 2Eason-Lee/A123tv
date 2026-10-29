// 4kvm.tv 播放地址签名器（Deno / Node 都能跑）
//
// 用法（由 kvm.py 调用，不手工执行）：
//   echo '{"userlink":"xxx","items":[{"dataid":"40779","secret":"ch4phdr82"}]}' \
//     | deno run --allow-read sources/kvm_sign.mjs
//   # 没装 deno 时可以直接用 Node 18+：
//   echo '...' | node sources/kvm_sign.mjs
//
// 输出：JSON 数组，顺序和输入 items 一致
//   [{"ok":true,"dataid":"40779","url":"/video/play?p=..."}]
//
// 原理：站点前端用 WASM 里的 build_play_url(dataid, secret, quality, userlink)
// 生成带 k 签名的 /video/play 地址，k 无法用普通哈希手算，所以这里直接跑官方 WASM。

import init, { build_play_url } from './wasm/nbmovie_wasm.js';

const isDeno = typeof Deno !== 'undefined';

let readFile;
let readStdin;
if (isDeno) {
  readFile = (p) => Deno.readFileSync(p);
  readStdin = async () => await new Response(Deno.stdin.readable).text();
} else {
  const { readFileSync } = await import('node:fs');
  readFile = (p) => readFileSync(p);
  readStdin = async () => readFileSync(0, 'utf8');
}

const wasmPath = new URL('./wasm/nbmovie_wasm_bg.wasm', import.meta.url);
await init({ module_or_path: readFile(wasmPath) });

const raw = await readStdin();
const input = JSON.parse(raw || '{}');

const userlink = String(input.userlink || '0');
const quality = String(input.quality || '1080');
const items = Array.isArray(input.items) ? input.items : [];

const out = items.map((it) => {
  const dataid = String(it?.dataid || '');
  const secret = String(it?.secret || '');
  try {
    return {
      ok: true,
      dataid,
      url: build_play_url(dataid, secret, quality, userlink),
    };
  } catch (e) {
    return { ok: false, dataid, error: String(e) };
  }
});

console.log(JSON.stringify(out));
