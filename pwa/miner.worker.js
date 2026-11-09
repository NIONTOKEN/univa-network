/**
 * UNIVA Network - Browser Mining Web Worker
 * Pure JS SHA-256 Proof-of-Work (Standard ASCII - Zero Dependencies)
 */

'use strict';

const K = [
  0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,
  0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,
  0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,
  0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,
  0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,
  0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,
  0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,
  0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2
];

function rotr(n, x) { return (x >>> n) | (x << (32 - n)); }
function s0(x) { return rotr(2, x) ^ rotr(13, x) ^ rotr(22, x); }
function s1(x) { return rotr(6, x) ^ rotr(11, x) ^ rotr(25, x); }
function g0(x) { return rotr(7, x) ^ rotr(18, x) ^ (x >>> 3); }
function g1(x) { return rotr(17, x) ^ rotr(19, x) ^ (x >>> 10); }
function Ch(x, y, z) { return (x & y) ^ (~x & z); }
function Maj(x, y, z) { return (x & y) ^ (x & z) ^ (y & z); }

function sha256(message) {
  const bytes = new TextEncoder().encode(message);
  const len = bytes.length;
  const bitLen = len * 8;
  const paddedLen = Math.ceil((len + 9) / 64) * 64;
  const padded = new Uint8Array(paddedLen);
  padded.set(bytes);
  padded[len] = 0x80;
  new DataView(padded.buffer).setUint32(paddedLen - 4, bitLen & 0xffffffff, false);
  let H = [
    0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a,
    0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19
  ];
  const W = new Int32Array(64);
  for (let i = 0; i < paddedLen; i += 64) {
    const dv = new DataView(padded.buffer, i, 64);
    for (let j = 0; j < 16; j++) W[j] = dv.getInt32(j * 4, false);
    for (let j = 16; j < 64; j++) {
      W[j] = (g1(W[j - 2]) + W[j - 7] + g0(W[j - 15]) + W[j - 16]) | 0;
    }
    let [a, b, c, d, e, f, g, h] = H;
    for (let j = 0; j < 64; j++) {
      const T1 = (h + s1(e) + Ch(e, f, g) + K[j] + W[j]) | 0;
      const T2 = (s0(a) + Maj(a, b, c)) | 0;
      h = g; g = f; f = e; e = (d + T1) | 0;
      d = c; c = b; b = a; a = (T1 + T2) | 0;
    }
    H = [
      (H[0] + a) >>> 0, (H[1] + b) >>> 0, (H[2] + c) >>> 0, (H[3] + d) >>> 0,
      (H[4] + e) >>> 0, (H[5] + f) >>> 0, (H[6] + g) >>> 0, (H[7] + h) >>> 0
    ];
  }
  return H.map(v => v.toString(16).padStart(8, '0')).join('');
}

function makeBlockHash(data) {
  const sorted = {
    difficulty: data.difficulty,
    index: data.index,
    merkle_root: data.merkle_root,
    miner_address: data.miner_address,
    nonce: data.nonce,
    previous_hash: data.previous_hash,
    reward: data.reward,
    timestamp: data.timestamp
  };
  return sha256(JSON.stringify(sorted));
}

let isRunning = false;

self.onmessage = function(e) {
  const msg = e.data;
  if (!msg) return;

  if (msg.type === 'STOP') {
    isRunning = false;
    return;
  }

  if (msg.type === 'START') {
    isRunning = true;
    const task = msg.data;
    const targetPrefix = '0'.repeat(task.difficulty);
    let nonce = task.startNonce || 0;
    let hashes = 0;
    let lastReport = Date.now();

    function step() {
      if (!isRunning) return;
      const batchSize = 1000;
      for (let i = 0; i < batchSize; i++) {
        task.nonce = nonce;
        const h = makeBlockHash(task);
        hashes++;
        if (h.startsWith(targetPrefix)) {
          isRunning = false;
          self.postMessage({
            type: 'FOUND',
            nonce: nonce,
            hash: h,
            blockData: task
          });
          return;
        }
        nonce++;
      }

      const now = Date.now();
      if (now - lastReport >= 1000) {
        const hashrate = Math.round((hashes * 1000) / (now - lastReport));
        self.postMessage({
          type: 'PROGRESS',
          hashrate: hashrate,
          nonce: nonce
        });
        hashes = 0;
        lastReport = now;
      }

      setTimeout(step, 0);
    }

    step();
  }
};
