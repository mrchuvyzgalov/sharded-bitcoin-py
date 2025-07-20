import base64
import time
import hashlib

from ecdsa import ecdsa, SigningKey, SECP256k1

from snapshot import Snapshot
from constants import BeaconBlockField, Constants, BeaconChainField


class BeaconBlock:
    def __init__(self,
                 index,
                 previous_hash,
                 snapshots: list[Snapshot],
                 proposer_address: str,
                 validator_signatures: dict,
                 timestamp=None) -> None:
        self.index = index
        self.previous_hash = previous_hash
        self.snapshots = snapshots
        self.proposer_address = proposer_address
        self.validator_signatures = validator_signatures  # {validator: signature}
        self.timestamp = timestamp or time.time()

    def hash(self) -> str:
        raw = f"{self.index}{self.previous_hash}{self.proposer_address}{self.timestamp}"
        raw += "".join(s.block_hash for s in self.snapshots)
        raw += "".join(self.validator_signatures)
        return hashlib.sha256(raw.encode()).hexdigest()

    def hash_content(self) -> str:
        raw = f"{self.index}{self.previous_hash}{self.proposer_address}{self.timestamp}"
        raw += "".join(s.block_hash for s in self.snapshots)
        return hashlib.sha256(raw.encode()).hexdigest()

    def sign_block(self, privkey_wif: str) -> str:
        sk = SigningKey.from_string(base64.b64decode(privkey_wif), curve=SECP256k1)
        message_hash = self.hash_content().encode()
        return base64.b64encode(sk.sign(message_hash)).decode()

    def add_signature(self, validator: str, signature: str):
        self.validator_signatures[validator] = signature

    def to_dict(self) -> dict:
        return {
            BeaconBlockField.INDEX: self.index,
            BeaconBlockField.PREVIOUS_HASH: self.previous_hash,
            BeaconBlockField.SNAPSHOTS: [s.to_dict() for s in self.snapshots],
            BeaconBlockField.PROPOSER_ADDRESS: self.proposer_address,
            BeaconBlockField.VALIDATOR_SIGNATURES: self.validator_signatures,
            BeaconBlockField.TIMESTAMP: self.timestamp
        }


def create_genesis_block() -> BeaconBlock:
    return BeaconBlock(
        index=0,
        previous_hash="0" * 64,
        snapshots=[],
        proposer_address="genesis",
        validator_signatures={},
        timestamp=1720000000.0
    )


class BeaconChain:
    def __init__(self):
        self.chain: list[BeaconBlock] = []
        self.pending_snapshots: dict[int, Snapshot] = {}

    def start(self) -> None:
        self.chain.append(create_genesis_block())

    def start_with_chain(self, blocks: list[BeaconBlock]) -> None:
        self.chain = blocks

    def add_snapshot(self, snapshot: Snapshot):
        self.pending_snapshots[snapshot.shard_id] = snapshot

    def form_block(self, proposer_address: str) -> BeaconBlock:
        block = BeaconBlock(
            index=len(self.chain),
            previous_hash=self.chain[-1].hash(),
            snapshots=list(self.pending_snapshots.values()),
            proposer_address=proposer_address,
            validator_signatures={},
            timestamp=time.time()
        )
        self.pending_snapshots.clear()
        return block

    def add_block(self, block: BeaconBlock) -> bool:
        if block.previous_hash == self.chain[-1].hash():
            self.chain.append(block)
            self.pending_snapshots.clear()
            return True
        return False

    def validate_block(self, block: BeaconBlock) -> bool:
        if block.previous_hash != self.chain[-1].hash():
            return False
        if block.index != len(self.chain):
            return False
        if len(set([x.shard_id for x in block.snapshots])) != Constants.NUMBER_OF_SHARDS:
            return False
        return True

    def to_dict(self) -> dict:
        return { BeaconChainField.BLOCKS: [block.to_dict() for block in self.chain] }

    def clear(self):
        self.chain.clear()
        self.pending_snapshots.clear()

    def print_chain(self) -> None:
        print("\n📦 Current Beacon blockchain:")
        for block in self.chain:
            print(f"  Block #{block.index} | hash: {block.hash()[:8]}... | prev: {block.previous_hash[:8]}...")
            for sn in block.snapshots:
                print(f"    └─ sn {sn.hash()[:8]}...")