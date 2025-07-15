import hashlib

from constants import Constants


class ShardService:
    @staticmethod
    def get_shard_id(public_key: str) -> int:
        return int(hashlib.sha256(public_key.encode()).hexdigest(), 16) % Constants.NUMBER_OF_SHARDS
