"""UNIVA Sovereign Layer-1 Protocol Configuration & Mainnet/Testnet Separation (P7).

Immutable Protocol Parameters (locked — NEVER change without formal governance approval):
  - Project Name       : UNIVA
  - Consensus          : SHA-256 Proof of Work (BIP-113 MTP)
  - Target Block Time  : 60 seconds
  - Max Supply         : 21,000,001 UNIVA
  - Initial Reward     : 100 UNIVA
  - Halving Interval   : 43,200 blocks
  - Difficulty Adjust  : 60 blocks
  - Native Address Len : 30 characters (Base31)
"""
import os
from typing import Dict, Any, Optional

# ─── IMMUTABLE PROTOCOL CONSTANTS ────────────────────────────────────────────
PROJECT_NAME = "UNIVA"
TICKER = "UNIVA"
PROTOCOL_VERSION = "4.0.0"
MIN_PEER_PROTOCOL_VERSION = "4.0.0"

MAX_SUPPLY = 21_000_001.0
INITIAL_REWARD = 100.0
TARGET_BLOCK_TIME = 60          # seconds
HALVING_INTERVAL = 43_200       # blocks (~30 days)
DIFFICULTY_ADJUST = 60          # blocks
INITIAL_DIFF = 4
NATIVE_ADDRESS_LENGTH = 30

# Canonical Mainnet Genesis (locked forever; must match live univa_chain.json block #0)
MAINNET_GENESIS_MESSAGE = "UNIVA Network 2026 - Tum Aglar Tek Cati Altinda - Evrensel Ozgurluk Agi"
MAINNET_GENESIS_TIME = 1735689600.0
MAINNET_GENESIS_MINER = "univa0000000000univa"

# Isolated Testnet Genesis (distinct hash guarantees zero cross-network P2P contamination)
TESTNET_GENESIS_MESSAGE = "UNIVA Testnet Genesis: Isolated Sandbox Network (Zero Mainnet Value)."
TESTNET_GENESIS_TIME = 1735689601.0
TESTNET_GENESIS_MINER = "tuniva222222222222222222tuniva"

NETWORK_PROFILES: Dict[str, Dict[str, Any]] = {
    "mainnet": {
        "network_id": "mainnet",
        "network_name": "UNIVA Network",
        "chain_id_dec": 210001,
        "chain_id_hex": hex(210001),  # 0x33451
        "address_prefix": "univa",
        "genesis_message": MAINNET_GENESIS_MESSAGE,
        "genesis_time": MAINNET_GENESIS_TIME,
        "genesis_miner": MAINNET_GENESIS_MINER,
        "default_chain_file": "univa_chain.json",
        "default_dex_file": "univa_dex_state.json",
        "default_offline_file": "univa_offline_state.json",
        "default_http_port": 5050,
        "default_p2p_port": 5051,
        "is_testnet": False,
    },
    "testnet": {
        "network_id": "testnet",
        "network_name": "UNIVA Testnet",
        "chain_id_dec": 210002,
        "chain_id_hex": hex(210002),  # 0x33452
        "address_prefix": "tuniva",
        "genesis_message": TESTNET_GENESIS_MESSAGE,
        "genesis_time": TESTNET_GENESIS_TIME,
        "genesis_miner": TESTNET_GENESIS_MINER,
        "default_chain_file": "univa_testnet_chain.json",
        "default_dex_file": "univa_testnet_dex_state.json",
        "default_offline_file": "univa_testnet_offline_state.json",
        "default_http_port": 15050,
        "default_p2p_port": 15051,
        "is_testnet": True,
    },
}


def get_active_network() -> str:
    raw = os.environ.get("UNIVA_NETWORK", "mainnet").strip().lower()
    return "testnet" if raw == "testnet" else "mainnet"


def get_network_config(network: Optional[str] = None) -> Dict[str, Any]:
    net_key = (network or get_active_network()).strip().lower()
    if net_key not in NETWORK_PROFILES:
        raise ValueError(f"Unsupported UNIVA network profile: {net_key}")
    return dict(NETWORK_PROFILES[net_key])


def get_locked_protocol_manifest(network: Optional[str] = None) -> Dict[str, Any]:
    cfg = get_network_config(network)
    return {
        "project": PROJECT_NAME,
        "ticker": TICKER,
        "protocol_version": PROTOCOL_VERSION,
        "min_peer_protocol_version": MIN_PEER_PROTOCOL_VERSION,
        "consensus": "SHA-256 Proof of Work (BIP-113 MTP)",
        "max_supply": MAX_SUPPLY,
        "initial_reward": INITIAL_REWARD,
        "target_block_time_sec": TARGET_BLOCK_TIME,
        "halving_interval_blocks": HALVING_INTERVAL,
        "difficulty_adjust_blocks": DIFFICULTY_ADJUST,
        "initial_difficulty": INITIAL_DIFF,
        "native_address_length": NATIVE_ADDRESS_LENGTH,
        "network": cfg["network_id"],
        "network_name": cfg["network_name"],
        "chain_id_dec": cfg["chain_id_dec"],
        "chain_id_hex": cfg["chain_id_hex"],
        "address_prefix": cfg["address_prefix"],
        "is_testnet": cfg["is_testnet"],
    }
