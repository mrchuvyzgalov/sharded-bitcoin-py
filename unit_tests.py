import base64

import pytest
from ecdsa import SigningKey, SECP256k1

from beacon import BeaconBlock, BeaconChain
from blockchain import Blockchain, Transaction, Constants, ShardService
from constants import BeaconChainField, BeaconBlockField
from snapshot import Snapshot
from transaction import TxInput, TxOutput


@pytest.fixture(autouse=True)
def patch_shard_service():
    ShardService.get_shard_id = staticmethod(lambda addr: 0)

@pytest.fixture
def bc():
    return Blockchain()

def test_genesis_block_exists(bc):
    assert len(bc.chain) == 1
    assert bc.chain[0].index == 0

def test_mine_block_adds_coinbase(bc):
    block = bc.mine_block("miner")
    coinbase_tx = block.transactions[0]

    assert coinbase_tx.outputs[0].address == "miner"
    assert coinbase_tx.outputs[0].amount == Constants.MINER_REWARD

def test_add_and_validate_transaction(bc):
    block = bc.mine_block("addr1")
    bc.chain.append(block)
    bc.update_utxo_set(block.transactions[0], my_shard=0)

    coinbase_id = block.transactions[0].hash()

    tx = Transaction(
        inputs=[TxInput(coinbase_id, 0)],
        outputs=[TxOutput(10, "addr2")]
    )

    added = bc.add_transaction(tx)
    assert added
    assert tx in bc.pending_txs

def test_invalid_transaction_rejected(bc):
    tx = Transaction(
        inputs=[TxInput("nonexistent_tx", 0)],
        outputs=[TxOutput(5, "addr2")]
    )

    added = bc.add_transaction(tx)
    assert not added

def test_update_utxo_only_for_my_shard(bc):
    ShardService.get_shard_id = staticmethod(lambda addr: 0 if "my" in addr else 1)

    tx = Transaction(
        inputs=[],
        outputs=[
            TxOutput(3, "my_addr"),
            TxOutput(5, "other_addr")
        ]
    )
    bc.update_utxo_set(tx, my_shard=0)

    txid = tx.hash()
    assert 0 in bc.utxo_set[txid]
    assert 1 not in bc.utxo_set[txid]

def test_get_balance(bc):
    block = bc.mine_block("user")
    bc.chain.append(block)
    bc.update_utxo_set(block.transactions[0], my_shard=0)

    balance = bc.get_balance("user")
    assert balance == Constants.MINER_REWARD

def test_effective_utxo_excludes_pending(bc):
    block = bc.mine_block("user")
    bc.chain.append(block)
    coinbase_tx = block.transactions[0]
    bc.update_utxo_set(coinbase_tx, my_shard=0)

    tx = Transaction(
        inputs=[TxInput(coinbase_tx.hash(), 0)],
        outputs=[TxOutput(10, "addr2")]
    )
    bc.pending_txs.append(tx)

    effective = bc.get_effective_utxo_set()
    assert coinbase_tx.hash() not in effective

def test_try_to_update_chain_replaces_chain(bc):
    block = bc.mine_block("miner")
    new_chain = bc.chain + [block]
    new_utxo = {"some_tx": {0: TxOutput(7, "miner")}}

    bc.try_to_update_chain(new_chain, new_utxo)

    assert bc.chain == new_chain
    assert bc.utxo_set == new_utxo

@pytest.fixture
def keypair():
    sk = SigningKey.generate(curve=SECP256k1)
    vk = sk.get_verifying_key()
    return (
        base64.b64encode(sk.to_string()).decode(),        # privkey_b64
        base64.b64encode(vk.to_string()).decode()         # pubkey_b64
    )

@pytest.fixture
def snapshot():
    return Snapshot(
        shard_id=0,
        block_number=5,
        cross_shard_receipts={1: ["tx1", "tx2"]},
        block_hash="a" * 64
    )

@pytest.fixture
def beacon_block(snapshot):
    return BeaconBlock(
        index=1,
        previous_hash="0" * 64,
        snapshots=[snapshot],
        proposer_address="node1",
        validator_signatures={},
        timestamp=1720001234.0
    )

def test_add_signature(beacon_block):
    beacon_block.add_signature("validator1", "sig1")
    assert beacon_block.validator_signatures["validator1"] == "sig1"

def test_to_dict_contains_all_fields(beacon_block):
    d = beacon_block.to_dict()
    assert BeaconBlockField.INDEX in d
    assert BeaconBlockField.PREVIOUS_HASH in d
    assert BeaconBlockField.SNAPSHOTS in d
    assert BeaconBlockField.PROPOSER_ADDRESS in d
    assert BeaconBlockField.VALIDATOR_SIGNATURES in d
    assert BeaconBlockField.TIMESTAMP in d

@pytest.fixture
def beacon_chain():
    chain = BeaconChain()
    chain.start()
    return chain

def test_start_creates_genesis(beacon_chain):
    assert len(beacon_chain.chain) == 1
    assert beacon_chain.chain[0].index == 0

def test_add_snapshot(beacon_chain, snapshot):
    beacon_chain.add_snapshot(snapshot)
    assert beacon_chain.pending_snapshots[0] == snapshot

def test_form_block_from_pending(beacon_chain, snapshot):
    beacon_chain.add_snapshot(snapshot)
    block = beacon_chain.form_block("nodeX")
    assert block.index == 1
    assert block.proposer_address == "nodeX"
    assert len(block.snapshots) == 1
    assert beacon_chain.pending_snapshots == {}

def test_add_block_valid(beacon_chain, snapshot):
    beacon_chain.add_snapshot(snapshot)
    block = beacon_chain.form_block("nodeX")
    added = beacon_chain.add_block(block)
    assert added
    assert beacon_chain.chain[-1] == block

def test_add_block_invalid_hash(beacon_chain, snapshot):
    block = BeaconBlock(
        index=1,
        previous_hash="bad_hash",
        snapshots=[snapshot],
        proposer_address="nodeX",
        validator_signatures={}
    )
    added = beacon_chain.add_block(block)
    assert not added

def test_validate_block_success(beacon_chain):
    snapshots = [
        Snapshot(i, 10, {}, f"blockhash{i}") for i in range(Constants.NUMBER_OF_SHARDS)
    ]
    block = BeaconBlock(
        index=1,
        previous_hash=beacon_chain.chain[-1].hash(),
        snapshots=snapshots,
        proposer_address="proposer",
        validator_signatures={}
    )
    assert beacon_chain.validate_block(block)

def test_validate_block_wrong_index(beacon_chain, snapshot):
    block = BeaconBlock(
        index=3,
        previous_hash=beacon_chain.chain[-1].hash(),
        snapshots=[snapshot],
        proposer_address="X",
        validator_signatures={}
    )
    assert not beacon_chain.validate_block(block)

def test_validate_block_missing_shards(beacon_chain):
    Constants.NUMBER_OF_SHARDS = 2
    snapshots = [
        Snapshot(0, 5, {}, "hash")  # только один шард
    ]
    block = BeaconBlock(
        index=1,
        previous_hash=beacon_chain.chain[-1].hash(),
        snapshots=snapshots,
        proposer_address="x",
        validator_signatures={}
    )
    assert not beacon_chain.validate_block(block)

def test_to_dict_structure(beacon_chain):
    d = beacon_chain.to_dict()
    assert BeaconChainField.BLOCKS in d
    assert isinstance(d[BeaconChainField.BLOCKS], list)

def test_clear_chain_and_snapshots(beacon_chain, snapshot):
    beacon_chain.add_snapshot(snapshot)
    beacon_chain.clear()
    assert len(beacon_chain.chain) == 0
    assert beacon_chain.pending_snapshots == {}
