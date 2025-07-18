from typing import List

from beacon import BeaconBlock
from blockchain import Block
from constants import TxField, BlockField, BlockchainField, DisconnectField, SnapshotField, BeaconNodeField, \
    CreatorField, BeaconBlockField, SignatureField, BeaconChainField, RequestBeaconField, RebroadcastField, Stage, \
    TxIdSendingField, GetTxsField
from snapshot import Snapshot
from transaction import Transaction, TxInput, TxOutput


class DeserializeService:
    @staticmethod
    def deserialize_tx(data: dict) -> Transaction:
        inputs = [TxInput(**i) for i in data[TxField.INPUTS]]
        outputs = [TxOutput(**o) for o in data[TxField.OUTPUTS]]
        metadata = data.get(TxField.METADATA, {})
        return Transaction(inputs, outputs, metadata)

    @staticmethod
    def deserialize_block(data: dict) -> Block:
        txs = [DeserializeService.deserialize_tx(tx) for tx in data[BlockField.TRANSACTIONS]]
        return Block(
            index=data[BlockField.INDEX],
            previous_hash=data[BlockField.PREVIOUS_HASH],
            transactions=txs,
            nonce=data[BlockField.NONCE],
            timestamp=data[BlockField.TIMESTAMP]
        )

    @staticmethod
    def deserialize_rebroadcast(data: dict) -> (str, int, Block):
        block = DeserializeService.deserialize_block(data[RebroadcastField.BLOCK])
        return data[RebroadcastField.HOST], int(data[RebroadcastField.PORT]), block

    @staticmethod
    def deserialize_chain(data: dict) -> List[Block]:
        blocks = [DeserializeService.deserialize_block(block) for block in data[BlockchainField.BLOCKS]]
        return blocks

    @staticmethod
    def deserialize_disconnect(data: dict) -> (str, int, int):
        return data[DisconnectField.HOST], data[DisconnectField.PORT], data[DisconnectField.SHARD]

    @staticmethod
    def deserialize_beacon_node(data: dict) -> (str, int, int):
        return data[BeaconNodeField.HOST], data[BeaconNodeField.PORT], data[BeaconNodeField.STAKE]

    @staticmethod
    def deserialize_snapshot(data: dict) -> Snapshot:
        return Snapshot(
            shard_id=data[SnapshotField.SHARD_ID],
            block_number=data[SnapshotField.BLOCK_NUMBER],
            block_hash=data[SnapshotField.BLOCK_HASH],
            cross_shard_receipts=DeserializeService._dict_str_keys_to_int(data[SnapshotField.CROSS_SHARD_RECEIPTS])
        )

    @staticmethod
    def deserialize_beacon_block(data: dict) -> BeaconBlock:
        return BeaconBlock(
            index=data[BeaconBlockField.INDEX],
            previous_hash=data[BeaconBlockField.PREVIOUS_HASH],
            snapshots=[DeserializeService.deserialize_snapshot(s) for s in data[BeaconBlockField.SNAPSHOTS]],
            proposer_address=data[BeaconBlockField.PROPOSER_ADDRESS],
            validator_signatures=data[BeaconBlockField.VALIDATOR_SIGNATURES],
            timestamp=data[BeaconBlockField.TIMESTAMP]
        )

    @staticmethod
    def deserialize_creator_of_beacon_node(data: dict) -> (str, int):
        return data[CreatorField.HOST], int(data[CreatorField.PORT])

    @staticmethod
    def deserialize_request_beacon_chain(data: dict) -> (str, int):
        return data[RequestBeaconField.HOST], int(data[RequestBeaconField.PORT])

    @staticmethod
    def deserialize_beacon_chain(data: dict) -> List[BeaconBlock]:
        blocks = [DeserializeService.deserialize_beacon_block(block) for block in data[BeaconChainField.BLOCKS]]
        return blocks

    @staticmethod
    def deserialize_signature(data: dict) -> (str, str):
        return data[SignatureField.ADDRESS], data[SignatureField.SIGNATURE]

    @staticmethod
    def deserialize_tx_id_sending(data: dict) -> list:
        return data[TxIdSendingField.TX_IDS]

    @staticmethod
    def deserialize_txs(data: dict) -> list[Transaction]:
        return [DeserializeService.deserialize_tx(tx) for tx in data[GetTxsField.TRANSACTIONS]]

    @staticmethod
    def _dict_str_keys_to_int(d: dict[str, list]) -> dict[int, list]:
        return {int(k): v for k, v in d.items()}
