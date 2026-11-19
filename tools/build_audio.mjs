// Listening audio generator (offline, Flite TTS).
//
// materials/listening/partN/*.json ichidagi "script" dan shu JSON yoniga mp3 yasaydi.
//   npm i echogarden          (bir marta, shu papkada)
//   node build_audio.mjs      (hammasini qayta yasaydi)
//   node build_audio.mjs part3   (faqat bitta partni)
//
// Talab: ffmpeg (PATH da bo'lishi kerak).
//
// "script" elementlari:
//   {"v": "N", "t": "..."}  - gap (v = ovoz: N, F1, F2, F3, M1, M2, M3)
//   {"pause": 3}            - sekund jimlik
//   {"beep": 1}             - qisqa signal (savollar orasida)

import fs from 'fs'
import path from 'path'
import { fileURLToPath } from 'url'
import { spawnSync } from 'child_process'

const { synthesize } = await import('echogarden/dist/synthesis/FliteTTS.js')

// Flite (WASM) bitta jarayonda ko'p marta ishga tushirilsa qulaydi, shuning uchun har bir gap
// alohida jarayonda sintez qilinadi: `node build_audio.mjs --synth <ovoz> <tezlik> <pitch|-> <matn>`
if (process.argv[2] === '--synth') {
  const [, , , voice, rate, pitch, text] = process.argv
  const r = await synthesize(text, voice, undefined, parseFloat(rate), pitch === '-' ? undefined : parseFloat(pitch),
    undefined, { logLevel: 'silent' })
  const a = r.rawAudio.audioChannels[0]
  // quvur (pipe) to'lguncha yozilgach chiqamiz, aks holda ovoz kesilib qoladi
  process.stdout.write(Buffer.from(a.buffer, a.byteOffset, a.byteLength), () => process.exit(0))
  await new Promise(() => {})
}

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', 'materials', 'listening')
const SR = 16000

// ovoz -> [flite ovozi, tezlik, pitch (Hz yoki undefined)]
const VOICES = {
  N:  ['kal16', 0.95, undefined],   // diktor
  M1: ['rms',   0.92, undefined],
  M2: ['awb',   0.92, undefined],
  M3: ['rms',   0.92, 105],
  F1: ['slt',   0.92, undefined],
  F2: ['slt',   0.92, 150],
  F3: ['slt',   0.92, 235],
}

const silence = (sec) => new Float32Array(Math.round(SR * sec))

function beep() {
  const n = Math.round(SR * 0.35)
  const out = new Float32Array(n)
  for (let i = 0; i < n; i++) {
    const env = Math.min(1, i / 400, (n - i) / 400)
    out[i] = 0.35 * env * Math.sin(2 * Math.PI * 880 * i / SR)
  }
  return out
}

function concat(chunks) {
  const total = chunks.reduce((s, c) => s + c.length, 0)
  const out = new Float32Array(total)
  let o = 0
  for (const c of chunks) { out.set(c, o); o += c.length }
  return out
}

function wavBuffer(samples) {
  const buf = Buffer.alloc(44 + samples.length * 2)
  buf.write('RIFF', 0); buf.writeUInt32LE(36 + samples.length * 2, 4); buf.write('WAVE', 8)
  buf.write('fmt ', 12); buf.writeUInt32LE(16, 16); buf.writeUInt16LE(1, 20); buf.writeUInt16LE(1, 22)
  buf.writeUInt32LE(SR, 24); buf.writeUInt32LE(SR * 2, 28); buf.writeUInt16LE(2, 32); buf.writeUInt16LE(16, 34)
  buf.write('data', 36); buf.writeUInt32LE(samples.length * 2, 40)
  for (let i = 0; i < samples.length; i++) {
    const v = Math.max(-1, Math.min(1, samples[i]))
    buf.writeInt16LE(Math.round(v * 32767), 44 + i * 2)
  }
  return buf
}

async function say(voiceKey, text) {
  const [voice, rate, pitch] = VOICES[voiceKey] || VOICES.N
  const r = spawnSync(process.execPath, ['--no-warnings', fileURLToPath(import.meta.url), '--synth',
    voice, String(rate), pitch === undefined ? '-' : String(pitch), text],
    { maxBuffer: 256 * 1024 * 1024 })
  if (r.status !== 0 || !r.stdout.length) throw new Error(`Sintez xatosi (${voiceKey}): ${text.slice(0, 40)}`)
  const b = r.stdout
  return new Float32Array(b.buffer.slice(b.byteOffset, b.byteOffset + b.byteLength))
}

async function build(jsonPath) {
  const data = JSON.parse(fs.readFileSync(jsonPath, 'utf8'))
  if (!data.script || !data.audio) return
  const chunks = []
  let prev = null
  for (const seg of data.script) {
    if (seg.pause) { chunks.push(silence(seg.pause)); prev = null; continue }
    if (seg.beep) { chunks.push(silence(0.3), beep(), silence(0.6)); prev = null; continue }
    if (prev !== null) chunks.push(silence(prev === seg.v ? 0.35 : 0.7))
    chunks.push(await say(seg.v, seg.t))
    prev = seg.v
  }
  chunks.push(silence(1))
  const wav = jsonPath.replace(/\.json$/, '.tmp.wav')
  const mp3 = path.join(path.dirname(jsonPath), data.audio)
  fs.writeFileSync(wav, wavBuffer(concat(chunks)))
  const r = spawnSync('ffmpeg', ['-y', '-loglevel', 'error', '-i', wav, '-af', 'loudnorm=I=-18:TP=-2',
    '-ar', '24000', '-ac', '1', '-codec:a', 'libmp3lame', '-b:a', '56k', mp3], { stdio: 'inherit' })
  fs.unlinkSync(wav)
  if (r.status !== 0) throw new Error('ffmpeg xatosi: ' + jsonPath)
  console.log('OK', path.relative(ROOT, mp3), (fs.statSync(mp3).size / 1024).toFixed(0) + ' KB')
}

const only = process.argv[2]
for (const part of fs.readdirSync(ROOT).sort()) {
  if (only && part !== only) continue
  const dir = path.join(ROOT, part)
  if (!fs.statSync(dir).isDirectory()) continue
  for (const f of fs.readdirSync(dir).sort()) {
    if (f.endsWith('.json')) await build(path.join(dir, f))
  }
}
