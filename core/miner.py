"""
UNIVA Network - CPU Miner Module
"""

import threading
import time


class UnivaMiner:
    def __init__(self, blockchain, miner_address: str):
        self.blockchain    = blockchain
        self.miner_address = miner_address
        self.is_mining     = False
        self._stop_event   = threading.Event()
        self._thread       = None
        self.blocks_found  = 0
        self.hash_rate     = 0.0

        self.on_block_found = None
        self.on_hash_rate   = None

    def start(self):
        if self.is_mining:
            return
        self.is_mining = True
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._mine_loop, daemon=True)
        self._thread.start()

    def stop(self):
        if not self.is_mining:
            return
        self.is_mining = False
        self._stop_event.set()

    def _mine_loop(self):
        while not self._stop_event.is_set():
            t0 = time.time()
            block = self.blockchain.mine_pending_transactions(
                self.miner_address,
                stop_event=self._stop_event
            )
            elapsed = time.time() - t0
            if block:
                self.blocks_found += 1
                if elapsed > 0:
                    self.hash_rate = (block.nonce + 1) / elapsed
                    if self.on_hash_rate:
                        self.on_hash_rate(self.hash_rate)
                if self.on_block_found:
                    self.on_block_found(block)
            time.sleep(0.1)
