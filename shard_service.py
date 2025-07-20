import hashlib

from constants import Constants


class ShardService:
    @staticmethod
    def get_shard_id(address: str) -> int:
        return int(hashlib.sha256(address.encode()).hexdigest(), 16) % Constants.NUMBER_OF_SHARDS
