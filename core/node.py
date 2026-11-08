"""Start one UNIVA testnet node: API on 5050 and P2P WebSocket on 5051."""
import argparse
import os
import sys


def main():
    parser = argparse.ArgumentParser(description="UNIVA L1 experimental testnet node")
    parser.add_argument("--data-dir", default="./data", help="directory for this node's chain/wallet data")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--api-port", type=int, default=5050)
    parser.add_argument("--p2p-port", type=int, default=5051)
    parser.add_argument("--peer", action="append", default=[], help="seed peer host (repeatable)")
    args = parser.parse_args()
    os.makedirs(args.data_dir, exist_ok=True)
    os.chdir(args.data_dir)
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if project_root not in sys.path:
        sys.path.insert(0, project_root)
    from core.network import app, blockchain
    from core.database import rebuild_index
    from core.p2p import run_p2p_in_thread
    rebuild_index(blockchain.chain)
    run_p2p_in_thread(blockchain, seed_peers=args.peer, host=args.host, port=args.p2p_port)
    import uvicorn
    print(f"UNIVA TESTNET | API http://127.0.0.1:{args.api_port} | P2P ws://{args.host}:{args.p2p_port}")
    uvicorn.run(app, host=args.host, port=args.api_port, log_level="info")


if __name__ == "__main__":
    main()
