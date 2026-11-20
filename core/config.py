"""
UNIVA Network - Locked Protocol Parameters & Mainnet/Testnet Separation (P7).

All core monetary and consensus constants are locked here and verified by
automated tests so neither testnet configs nor upgrades can accidentally drift
the protocol economics.
"""
import os
from typing import Dict, Any

# ─── LOCKED IMMUTABLE PROTOCOL CONSTANTS ─────────────────────────────────────
NETWORK_NAME = "UNIVA"
TICKER = "UNIVA"
PROTOCOL_VERSION = "4.1.0"
MIN_PROTOCOL_VERSION = "4.0.0"

MAX_SUPPLY = 21_000_001.0       # Maximum coin supply (locked)
INITIAL_REWARD = 100.0          # Initial PC block reward (locked)
MOBILE_REWARD = 10.0            # Mobile light-miner reward tier (<= max subsidy)
TARGET_BLOCK_TIME = 60          # Target block interval in seconds (locked)
HALVING_INTERVAL = 43_200       # Halving every 43,200 blocks (~30 days, locked)
DIFFICULTY_ADJUST = 60          # Retargeting window in blocks (locked)
INITIAL_DIFF = 4                # Initial PoW leading hex zeros
NATIVE_ADDRESS_LENGTH = 30      # Standard native UNIVA address length (locked)

# ─── NETWORK PROFILES (STRICT MAINNET vs TESTNET ISOLATION) ──────────────────
NETWORK_PROFILES: Dict[str, Dict[str, Any]] = {
    "mainnet": {
        "network": "mainnet",
        "network_id": "UNIVA-MAIN-1",
        "chain_id": 210001,
        "chain_id_hex": "0x33451",
        "address_prefix": "univa",
        "genesis_message": "UNIVA Network 2026 - Tum Aglar Tek Cati Altinda - Evrensel Ozgurluk Agi",
        "genesis_time": 1735689600.0,
        "genesis_miner": "univa0000000000univa",
        "default_chain_file": "univa_chain.json",
        "default_db_file": "univa_chain.db",
        "default_dex_file": "univa_dex_state.json",
        "default_offline_file": "univa_offline_state.json",
        "default_http_port": 5050,
        "default_p2p_port": 5051,
    },
    "testnet": {
        "network": "testnet",
        "network_id": "UNIVA-TEST-2",
        "chain_id": 210002,
        "chain_id_hex": "0x33452",
        "address_prefix": "tuniv",
        "genesis_message": "UNIVA Testnet Genesis: Isolated Sandbox Chain 2026",
        "genesis_time": 1741564860.0,
        "genesis_miner": "tuniv0000000000tuniv",
        "default_chain_file": "univa_testnet_chain.json",
        "default_db_file": "univa_testnet_chain.db",
        "default_dex_file": "univa_testnet_dex_state.json",
        "default_offline_file": "univa_testnet_offline_state.json",
        "default_http_port": 15050,
        "default_p2p_port": 15051,
    },
}


def get_active_network_name() -> str:
    val = (os.environ.get("UNIVA_NETWORK") or "mainnet").strip().lower()
    return val if val in NETWORK_PROFILES else "mainnet"


def get_network_config(network: str = None) -> Dict[str, Any]:
    name = (network or get_active_network_name()).strip().lower()
    if name not in NETWORK_PROFILES:
        raise ValueError(f"Unsupported UNIVA network profile: {name}")
    return dict(NETWORK_PROFILES[name])


def parse_version_tuple(version_str: str) -> tuple:
    try:
        parts = [int(p) for p in str(version_str or "0.0.0").strip().lstrip("v").split(".")[:3]]
        while len(parts) < 3:
            parts.append(0)
        return tuple(parts)
    except Exception:
        return (0, 0, 0)


def is_protocol_version_compatible(peer_version: str) -> bool:
    return parse_version_tuple(peer_version) >= parse_version_tuple(MIN_PROTOCOL_VERSION)
