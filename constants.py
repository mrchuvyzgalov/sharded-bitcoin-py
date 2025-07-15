from enum import Enum


class MessageType:
    TX = "tx"
    BLOCK = "block"
    REQUEST_CHAIN = "request_chain"
    CHAIN = "chain"
    MINING = "mining"
    REBROADCAST = "rebroadcast"
    FINALISE_BLOCK = "finalize_block"
    DISCONNECT = "disconnect"
    REFUND = "refund"
    BEACON_NODE = "beacon_node"
    BEACON_NODE_DISCONNECT = "beacon_node_disconnect"
    SNAPSHOT = "snapshot"
    CREATOR = "creator"
    BEACON_BLOCK = "beacon_block"
    SIGNATURE = "signature"
    BROADCAST_BEACON_BLOCK = "broadcast_beacon_block"
    REQUEST_BEACON = "request_beacon"
    BEACON_CHAIN = "beacon_chain"

class MessageField:
    TYPE = "type"
    DATA = "data"

class TxInputField:
    TX_ID = "tx_id"
    INDEX = "index"
    SIGNATURE = "signature"
    PUBKEY = "pubkey"

class TxOutputField:
    AMOUNT = "amount"
    ADDRESS = "address"

class TxField:
    INPUTS = "inputs"
    OUTPUTS = "outputs"
    METADATA = "metadata"

class MetadataType:
    HEIGHT = "height"
    EPOCH = "epoch"
    STAKE = "stake"
    ADDRESS = "address"
    REFUND = "refund"

class BlockField:
    INDEX = "index"
    PREVIOUS_HASH = "previous_hash"
    TRANSACTIONS = "transactions"
    NONCE = "nonce"
    TIMESTAMP = "timestamp"

class BlockchainField:
    BLOCKS = "blocks"

class DisconnectField:
    HOST = "host"
    PORT = "port"
    SHARD = "shard"

class Constants:
    NUMBER_OF_SHARDS = 2
    MINER_REWARD = 50 / NUMBER_OF_SHARDS
    EPOCH = 100
    DIFFICULTY = 3
    TIME_TO_SLEEP = 60

class BeaconBlockField:
    INDEX = "index"
    PREVIOUS_HASH = "previous_hash"
    SNAPSHOTS = "snapshots"
    PROPOSER_ADDRESS = "proposer_address"
    VALIDATOR_SIGNATURES = "validator_signatures"
    TIMESTAMP = "timestamp"

class BeaconNodeField:
    HOST = "host"
    PORT = "port"
    STAKE = "stake"

class BeaconNodeDisconnectField:
    HOST = "host"
    PORT = "port"

class CreatorField:
    HOST = "host"
    PORT = "port"

class SnapshotField:
    SHARD_ID = "shard_id"
    BLOCK_NUMBER = "block_number"
    BLOCK_HASH = "block_hash"
    CROSS_SHARD_RECEIPTS = "cross_shard_receipts"

class SignatureField:
    ADDRESS = "address"
    SIGNATURE = "signature"

class BroadcastBeaconBlockField:
    INDEX = "index"
    PREVIOUS_HASH = "previous_hash"
    SNAPSHOTS = "snapshots"
    PROPOSER_ADDRESS = "proposer_address"
    VALIDATOR_SIGNATURES = "validator_signatures"
    TIMESTAMP = "timestamp"

class RequestBeaconField:
    HOST = "host"
    PORT = "port"

class BeaconChainField:
    BLOCKS = "blocks"

class Role(Enum):
    MINER = "miner"
    USER = "user"
