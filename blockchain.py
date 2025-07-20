import copy
import time
import hashlib

from constants import BlockField, BlockchainField, Constants, MetadataType
from shard_service import ShardService
from transaction import Transaction, TxOutput


class Block:
    def __init__(self,
                 index,
                 previous_hash,
                 transactions,
                 nonce: int =0,
                 timestamp=None) -> None:
        self.index = index
        self.previous_hash = previous_hash
        self.transactions = transactions
        self.nonce = nonce
        self.timestamp = timestamp or time.time()

    def hash(self) -> str:
        block_string = f"{self.index}{self.previous_hash}{self.nonce}{self.timestamp}" + \
            "".join(tx.hash() for tx in self.transactions)
        return hashlib.sha256(block_string.encode()).hexdigest()

    def to_dict(self) -> dict:
        return {
            BlockField.INDEX: self.index,
            BlockField.PREVIOUS_HASH: self.previous_hash,
            BlockField.TRANSACTIONS: [tx.to_dict() for tx in self.transactions],
            BlockField.NONCE: self.nonce,
            BlockField.TIMESTAMP: self.timestamp
        }


def _create_genesis_block() -> Block:
    return Block(0, "0" * 64, [], 0, 1720000000.0)


class Blockchain:
    def __init__(self) -> None:
        self.chain = [_create_genesis_block()]
        self.pending_txs = []
        self.utxo_set = {}
        self.difficulty = Constants.DIFFICULTY

    def print_chain(self) -> None:
        print("\n📦 Current blockchain:")
        for block in self.chain:
            print(f"  Block #{block.index} | hash: {block.hash()[:8]}... | prev: {block.previous_hash[:8]}...")
            for tx in block.transactions:
                print(f"    └─ tx {tx.hash()[:8]}")

    def mine_block(self, miner_address: str) -> Block:
        height = len(self.chain)
        coinbase = Transaction([], [TxOutput(Constants.MINER_REWARD, miner_address)], {MetadataType.HEIGHT: height})
        txs = [coinbase] + self.pending_txs
        block = Block(height, self.chain[-1].hash(), txs)

        while not block.hash().startswith("0" * self.difficulty):
            block.nonce += 1

        self.pending_txs.clear()
        return block

    def get_effective_utxo_set(self):
        temp_utxo = copy.deepcopy(self.utxo_set)

        for tx in self.pending_txs:
            for txin in tx.inputs:
                if txin.tx_id in temp_utxo and txin.index in temp_utxo[txin.tx_id]:
                    del temp_utxo[txin.tx_id][txin.index]
                    if not temp_utxo[txin.tx_id]:
                        del temp_utxo[txin.tx_id]
        return temp_utxo

    def add_refund_transaction(self, tx):
        if tx.hash() in [t.hash() for t in self.pending_txs]:
            return False
        self.pending_txs.append(tx)
        return True

    def add_transaction(self, tx):
        if tx.hash() in [t.hash() for t in self.pending_txs]:
            return False
        if not self.validate_transaction(tx):
            return False
        self.pending_txs.append(tx)
        return True

    def update_utxo_set(self, tx: Transaction, my_shard: int):
        txid = tx.hash()

        for txin in tx.inputs:
            if txin.tx_id in self.utxo_set and txin.index in self.utxo_set[txin.tx_id]:
                del self.utxo_set[txin.tx_id][txin.index]
                if not self.utxo_set[txin.tx_id]:
                    del self.utxo_set[txin.tx_id]

        for index, txout in enumerate(tx.outputs):
            receiver_shard = ShardService.get_shard_id(txout.address)

            if receiver_shard != my_shard:
                continue

            if txid not in self.utxo_set:
                self.utxo_set[txid] = {}
            self.utxo_set[txid][index] = txout

    def rebuild_utxo_set(self, my_shard: int):
        self.utxo_set = {}
        spent = set()

        for block in self.chain:
            for tx in block.transactions:
                txid = tx.hash()
                for txin in tx.inputs:
                    spent.add((txin.tx_id, txin.index))
                for index, txout in enumerate(tx.outputs):
                    if (txid, index) not in spent:
                        if ShardService.get_shard_id(txout.address) == my_shard:
                            if txid not in self.utxo_set:
                                self.utxo_set[txid] = {}
                            self.utxo_set[txid][index] = txout

    def validate_transaction(self, tx):
        input_sum = 0
        output_sum = 0
        for txin in tx.inputs:
            utxo = self.utxo_set.get(txin.tx_id, {}).get(txin.index)
            if not utxo:
                return False
            input_sum += utxo.amount
        for txout in tx.outputs:
            output_sum += txout.amount
        return output_sum <= input_sum

    def print_utxo_set(self):
        print("🔎 Current UTXO set:")
        for txid, outputs in self.utxo_set.items():
            for index, txout in outputs.items():
                print(f"🧱 {txid[:8]}:{index} → {txout.amount} to {txout.address[:8]}...")

    def validate_block(self, block):
        if block.previous_hash != self.chain[-1].hash():
            return False

        temp_utxo = copy.deepcopy(self.utxo_set)

        for i, tx in enumerate(block.transactions):
            input_total = 0
            output_total = 0

            for txin in tx.inputs:
                utxo = temp_utxo.get(txin.tx_id, {}).get(txin.index)
                if not utxo:
                    print(f"❌ In block: input {txin.tx_id[:8]}:{txin.index} not found")
                    return False
                input_total += utxo.amount

            for txout in tx.outputs:
                output_total += txout.amount

            if not tx.is_coinbase() and tx.is_refund():
                if input_total < output_total:
                    print(f"❌ Тx #{i}: input < output")
                    return False

            for txin in tx.inputs:
                del temp_utxo[txin.tx_id][txin.index]
                if not temp_utxo[txin.tx_id]:
                    del temp_utxo[txin.tx_id]
            temp_utxo[tx.hash()] = {
                idx: txout for idx, txout in enumerate(tx.outputs)
            }

        return True

    def try_to_update_chain(self, blocks: list[Block], utxo: dict):
        if len(self.chain) < len(blocks):
            self.chain = blocks.copy()
            self.utxo_set = utxo.copy()

    def get_balance(self, address: str) -> float:
        balance = 0.0
        for txid, outputs in self.utxo_set.items():
            for index, txout in outputs.items():
                if txout.address == address:
                    balance += txout.amount
        return balance

    def to_dict(self):
        return {
            BlockchainField.BLOCKS: [block.to_dict() for block in self.chain],
            BlockchainField.UTXOS: {
                txid: {
                    str(index): txout.to_dict()
                    for index, txout in outputs.items()
                }
                for txid, outputs in self.utxo_set.items()
            }
        }