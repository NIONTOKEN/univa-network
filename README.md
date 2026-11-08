# UNIVA L1 — Experimental Testnet Package

This package preserves the uploaded project's `core/` layout and adds missing pieces required to run a local experimental testnet. It is **not mainnet-ready** and must not be used to store real funds.

## What was in the uploaded ZIP

The archive contained only `core/blockchain.py`, `core/miner.py`, `core/p2p.py`, `core/wallet.py`, and `test_dex.py`. The test file imported `core.dex`, which was absent, so the original test failed immediately with `ModuleNotFoundError`. The archive also had no dependency manifest, HTTP API/node launcher, or standalone database module.

## Included now

- `core/dex.py`: local integer-base-unit AMM reference implementation; 10 bps (0.1%) default fee, minimum LP lock, slippage checks, proportional liquidity removal.
- Hardened experimental `core/blockchain.py`: signed-transfer checks, sender address/public-key binding, transaction ID/signature checks, nonce checks, pending incoming funds excluded from spendable balance, fee rewards, block acceptance checks, and contextual chain validation.
- `core/p2p.py`: received blocks are now passed through blockchain validation before append/relay; invalid transactions are not relayed.
- `core/database.py`: SQLite WAL side-index for blocks, transactions, and peers; it can be rebuilt from the validated JSON chain and is not the consensus source of truth.
- `core/network.py`: FastAPI endpoints for health, stats, blocks, balances, transaction submission, mining, and a small JSON-RPC-style interface.
- `core/node.py`: node launcher (API port 5050, P2P WebSocket port 5051 by default).
- Wallet uses `ecdsa` when installed and has a `cryptography` secp256k1 fallback.
- Tests for DEX math/slippage, signed transfers, invalid blocks, sync acceptance, and persistence.

## Install

Python 3.10+ recommended.

```bash
python -m venv .venv
# Windows PowerShell:
.\.venv\Scripts\Activate.ps1
# macOS/Linux:
# source .venv/bin/activate
python -m pip install -r requirements.txt
python -m pytest -q
```

## Start one node

Run from the project root:

```bash
python -m core.node --data-dir ./data-node1 --host 0.0.0.0 --api-port 5050 --p2p-port 5051
```

Check `http://127.0.0.1:5050/health`, `/stats`, `/chain`, and `/docs`.

Create a wallet with Python:

```python
from core.wallet import UnivaWallet
w = UnivaWallet.create_new()
w.save("wallet.json")
print(w.address)
```

Mine a testnet block to that wallet (node running):

```bash
curl -X POST http://127.0.0.1:5050/mine/YOUR_UNIVA_ADDRESS
```

Submit a signed transaction by constructing it with `blockchain.create_transaction(wallet, recipient, amount, fee)` in a local Python program and POSTing `{"tx": ...}` to `/transactions`.

## Two-node test

Use two separate data directories and distinct API/P2P ports. Start node 1 on P2P 5051. Start node 2 on P2P 5052 and provide node 1 as a seed, e.g. `--peer 127.0.0.1:5051`. On separate computers, allow the selected API/P2P TCP ports through the firewall and use the first computer's LAN/public IP.

## Important limitations before mainnet

1. **Address length:** the requested `univa` + 10 Base31 characters + `univa` format has only about 49.5 bits of namespace. This is far too small to provide the collision resistance expected of a public cryptocurrency. Keep this format for a closed testnet only; before mainnet, approve a longer address format or a secure address/alias registry design.
2. **Consensus:** the implementation still uses a simple leading-zero-nibble difficulty and an experimental retarget policy, not a peer-reviewed Bitcoin-style target/chainwork implementation. Fork choice is not yet based on accumulated work.
3. **Persistence:** JSON chain persistence is the consensus source of truth. SQLite is an auxiliary rebuildable index; crash/fork recovery still needs additional adversarial testing.
4. **DEX:** `core/dex.py` is currently an in-process AMM simulation. Its reserves and token balances are not committed into L1 consensus/state, so it is **not yet a native on-chain DEX**.
5. **P2P:** this is a small testnet protocol, not hardened against hostile peers, denial-of-service, oversized messages, eclipse attacks, or network partitions.
6. **Mempool/consensus:** do not expose this testnet to untrusted public traffic. Additional independent security review, fuzzing, fork tests, deterministic state transition tests, and a chainwork fork-choice implementation are required before any public launch.
7. **No real funds:** mined coins have no market value; never use real private keys or funds in this experimental package.

## API quick reference

- `GET /health`
- `GET /stats`
- `GET /chain?from_height=0&limit=100`
- `GET /block/{height}`
- `GET /balance/{address}`
- `POST /transactions` with `{"tx": {...signed transaction...}}`
- `POST /mine/{miner_address}`
- `POST /rpc` with JSON-RPC-style methods `getblockcount`, `getbestblockhash`, `getblockhash`, `getblock`, `getbalance`, `getnetworkinfo`, `getmininginfo`, `sendrawtransaction`

The RPC is a small method-name-compatible surface only, not full Bitcoin Core RPC compatibility.
