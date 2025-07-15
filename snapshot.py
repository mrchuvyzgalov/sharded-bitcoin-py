import hashlib
import json

from constants import SnapshotField


class Snapshot:
    def __init__(self,
                 shard_id,
                 block_number,
                 cross_shard_receipts,
                 block_hash):
        self.shard_id: int = shard_id
        self.block_number: int = block_number
        self.cross_shard_receipts: dict[int, list] = cross_shard_receipts
        self.block_hash: str = block_hash

    def to_dict(self) -> dict:
        return {
            SnapshotField.SHARD_ID: self.shard_id,
            SnapshotField.BLOCK_NUMBER: self.block_number,
            SnapshotField.BLOCK_HASH: self.block_hash,
            SnapshotField.CROSS_SHARD_RECEIPTS: self.cross_shard_receipts
        }

    def hash(self) -> str:
        snapshot_string = json.dumps(self.to_dict(), sort_keys=True)
        return hashlib.sha256(snapshot_string.encode()).hexdigest()