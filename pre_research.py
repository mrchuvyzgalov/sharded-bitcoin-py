import json
import time

from beacon import BeaconBlock, create_genesis_block
from blockchain import Block
from constants import Role, Constants, BeaconChainField, MetadataType
from main import create_stake_transaction
from node import Node
from shard_service import ShardService
from snapshot import Snapshot
from transaction import Transaction, TxOutput


def prepare_miner(node: Node, amount_of_blocks: int, amount_of_tx_in_block: int) -> ([Block], [Snapshot]):
    shard_id = ShardService.get_shard_id(node.address)

    #blockchain
    for i in range(amount_of_blocks):
        if i == 0:
            tx = create_stake_transaction(node, 0)
            node.add_and_broadcast_stake_transaction(tx)
        height = len(node.blockchain.chain)
        for j in range(amount_of_tx_in_block):
            tx = Transaction([],
                             [TxOutput(Constants.MINER_REWARD, node.address)],
                             {
                                 MetadataType.HEIGHT: height,
                                 "number_of_block": i + 1,
                                 "number_of_tx": j + 1,
                               })
            node.blockchain.pending_txs.append(tx)

        new_block = node.blockchain.mine_block(node.address)
        node.verify_and_add_block(new_block)

    with open(f"research_files/blockchain_shard{shard_id}.json", "w") as f:
        json.dump(node.blockchain.to_dict(), f, indent=2)

    #snaps
    snaps = []
    for block in node.blockchain.chain[1:]:
        snapshot = Snapshot(shard_id=shard_id,
                            block_number=block.index,
                            block_hash=block.hash(),
                            cross_shard_receipts={})
        snaps.append(snapshot)

    return node.blockchain.chain, snaps

def create_beacon_blocks(snaps0, snaps1) -> list[BeaconBlock]:
    beacon_blocks: list[BeaconBlock] = [create_genesis_block()]

    for i in range(len(snaps0)):
        bblock = BeaconBlock(
            index=i + 1,
            previous_hash=beacon_blocks[-1].hash(),
            snapshots=[snaps0[i], snaps1[i]],
            proposer_address=node0.address,
            validator_signatures={},
            timestamp=time.time()
        )

        signature0 = bblock.sign_block(node0.private_key)
        signature1 = bblock.sign_block(node1.private_key)

        bblock.validator_signatures[node0.address] = signature0
        bblock.validator_signatures[node1.address] = signature1

        beacon_blocks.append(bblock)

    return beacon_blocks

if __name__ == "__main__":
    role = Role.MINER
    Constants.NUMBER_OF_SHARDS = 2
    Constants.EPOCH = 100000
    AMOUNT_OF_BLOCKS = 30
    AMOUNT_OF_TX_IN_BLOCK = 1000

    node0 = Node("0.0.0.0", 1111, role=role, wallet_file="research_files/miner_wallet_shard0.txt")
    blocks0, snaps0 = prepare_miner(node0, AMOUNT_OF_BLOCKS, AMOUNT_OF_TX_IN_BLOCK)

    node1 = Node("0.0.0.0", 2222, role=role, wallet_file="research_files/miner_wallet_shard1.txt")
    blocks1, snaps1 = prepare_miner(node1, AMOUNT_OF_BLOCKS, AMOUNT_OF_TX_IN_BLOCK)

    beacon_blocks: list[BeaconBlock] = create_beacon_blocks(snaps0, snaps1)

    beacon = {
        BeaconChainField.BLOCKS: [b.to_dict() for b in beacon_blocks]
    }

    with open(f"research_files/beacon.json", "w") as f:
        json.dump(beacon, f, indent=2)

