import copy
import tempfile
import time

import pytest

from constants import Role, Constants
from main import create_stake_transaction, create_transaction
from node import Node
from shard_service import ShardService
from wallet import generate_keypair, pubkey_to_address


@pytest.fixture
def temp_wallet_file1():
    privkey, _ = generate_keypair()
    path = tempfile.mktemp()
    with open(path, "w") as f:
        f.write(privkey)
    return path

@pytest.fixture
def temp_wallet_file2():
    privkey, _ = generate_keypair()
    path = tempfile.mktemp()
    with open(path, "w") as f:
        f.write(privkey)
    return path

@pytest.fixture
def temp_wallet_file_shard0():
    privkey, pubkey = generate_keypair()

    while ShardService.get_shard_id(pubkey_to_address(pubkey)) != 0:
        privkey, pubkey = generate_keypair()

    path = tempfile.mktemp()
    with open(path, "w") as f:
        f.write(privkey)
    return path

@pytest.fixture
def temp_wallet_file_shard1():
    privkey, pubkey = generate_keypair()

    while ShardService.get_shard_id(pubkey_to_address(pubkey)) != 1:
        privkey, pubkey = generate_keypair()

    path = tempfile.mktemp()
    with open(path, "w") as f:
        f.write(privkey)
    return path

def test_miner_node_creates_block_and_updates_balance_in_one_shard(temp_wallet_file1):
    Constants.NUMBER_OF_SHARDS = 1

    host = "127.0.0.1"
    port = 1111

    node = Node(host=host, port=port, role=Role.MINER, wallet_file=temp_wallet_file1)
    node.start()

    stake_tx = create_stake_transaction(node, 0)
    node.add_and_broadcast_stake_transaction(stake_tx)

    time.sleep(Constants.TIME_TO_SLEEP * 1.5)

    chain = node.blockchain.chain
    assert len(chain) == 2, "Expected 2 blocks (including genesis)"

    last_block = chain[-1]
    assert len(last_block.transactions) == 2, "The last block must contain 2 transaction (coinbase + stake)"

    coinbase = last_block.transactions[0]
    stake = last_block.transactions[1]
    assert coinbase.is_coinbase(), "The transaction must be coinbase"
    assert stake.is_stake(), "The transaction must be coinbase"

    balance = node.blockchain.get_balance(node.address)
    assert balance == Constants.MINER_REWARD, f"The balance should be {Constants.MINER_REWARD}, but it is {balance}"

    beacon = node.beacon.chain
    assert len(beacon) == 2, "Expected 2 beacon blocks (including genesis)"

    last_beacon_block = beacon[-1]
    assert len(last_beacon_block.snapshots) == 1, "The last beacon block must contain 1 snapshot"

def test_node_can_synchronize_chain_in_one_shard(temp_wallet_file1, temp_wallet_file2):
    Constants.NUMBER_OF_SHARDS = 1

    host = "127.0.0.1"
    miner_port = 1111
    user_port = 2222

    miner_node = Node(host=host, port=miner_port, role=Role.MINER, wallet_file=temp_wallet_file1)
    user_node = Node(host=host, port=user_port, role=Role.USER, wallet_file=temp_wallet_file2)

    # mocks
    miner_node.external_ip = host
    user_node.external_ip = host

    miner_node._listen_tcp = None
    user_node._listen_tcp = None

    miner_node._handle_tcp_connection = None
    user_node._handle_tcp_connection = None

    miner_node._listen_discovery = None
    user_node._listen_discovery = None

    miner_node._broadcast_presence = None
    user_node._broadcast_presence = None

    def broadcast_to_user(message: dict):
        if len(miner_node.peers[0]) > 0:
            user_node.message_queue.put(message)

    def broadcast_to_miner(message: dict):
        if len(user_node.peers[0]) > 0:
            miner_node.message_queue.put(message)

    miner_node._broadcast = broadcast_to_user
    user_node._broadcast = broadcast_to_miner

    miner_node._broadcast_to_all_beacon_nodes = lambda x: None
    user_node._broadcast_to_all_beacon_nodes = broadcast_to_miner

    def broadcast_to_user_common(message: dict, peer: str):
        if len(miner_node.peers[0]) > 0:
            user_node.message_queue.put(message)

    miner_node._broadcast_to_user = broadcast_to_user_common
    user_node._broadcast_to_user = lambda x: None

    def broadcast_to_shard_for_user(message: dict, shard_id: int):
        if len(miner_node.peers[0]) > 0:
            user_node.message_queue.put(message)

    def broadcast_to_shard_for_miner(message: dict, shard_id: int):
        if len(user_node.peers[0]) > 0:
            miner_node.message_queue.put(message)

    miner_node._broadcast_to_shard = broadcast_to_shard_for_user
    user_node._broadcast_to_shard = broadcast_to_shard_for_miner

    miner_node._broadcast_to_all = broadcast_to_user
    user_node._broadcast_to_all = broadcast_to_miner

    # start miner node
    miner_node.start()

    stake_tx = create_stake_transaction(miner_node, 0)
    miner_node.add_and_broadcast_stake_transaction(stake_tx)

    time.sleep(Constants.TIME_TO_SLEEP * 1.5)

    # start user node
    user_node.start()

    miner_node.peers[0].add((host, user_port))
    user_node.peers[0].add((host, miner_port))

    user_node._broadcast_request_chain()

    time.sleep(5)

    miner_chain = copy.deepcopy(miner_node.blockchain.chain)
    user_chain = copy.deepcopy(user_node.blockchain.chain)

    miner_balance = miner_node.blockchain.get_balance(miner_node.address)
    user_balance = user_node.blockchain.get_balance(user_node.address)

    assert len(miner_chain) == 2, "Expected 2 miner blocks (including genesis)"
    assert len(user_chain) == 2, "Expected 2 user blocks (including genesis)"

    assert [b.to_dict() for b in miner_chain] == [b.to_dict() for b in user_chain], "Expected that the chains are identical"

    assert miner_balance == Constants.MINER_REWARD, f"The miner balance should be {Constants.MINER_REWARD}, but it is {user_balance}"
    assert user_balance == 0, f"The user balance should be 0, but it is {user_balance}"

def test_transaction_propagates_between_nodes_in_one_shard(temp_wallet_file1, temp_wallet_file2):
    Constants.NUMBER_OF_SHARDS = 1

    host = "127.0.0.1"
    miner_port = 1111
    user_port = 2222

    miner_node = Node(host=host, port=miner_port, role=Role.MINER, wallet_file=temp_wallet_file1)
    user_node = Node(host=host, port=user_port, role=Role.USER, wallet_file=temp_wallet_file2)

    # mocks
    miner_node.external_ip = host
    user_node.external_ip = host

    miner_node._listen_tcp = None
    user_node._listen_tcp = None

    miner_node._handle_tcp_connection = None
    user_node._handle_tcp_connection = None

    miner_node._listen_discovery = None
    user_node._listen_discovery = None

    miner_node._broadcast_presence = None
    user_node._broadcast_presence = None

    def broadcast_to_user(message: dict):
        if len(miner_node.peers[0]) > 0:
            user_node.message_queue.put(message)

    def broadcast_to_miner(message: dict):
        if len(user_node.peers[0]) > 0:
            miner_node.message_queue.put(message)

    miner_node._broadcast = broadcast_to_user
    user_node._broadcast = broadcast_to_miner

    miner_node._broadcast_to_all_beacon_nodes = lambda x: None
    user_node._broadcast_to_all_beacon_nodes = broadcast_to_miner

    def broadcast_to_user_common(message: dict, peer: str):
        if len(miner_node.peers[0]) > 0:
            user_node.message_queue.put(message)

    miner_node._broadcast_to_user = broadcast_to_user_common
    user_node._broadcast_to_user = lambda x: None

    def broadcast_to_shard_for_user(message: dict, shard_id: int):
        if len(miner_node.peers[0]) > 0:
            user_node.message_queue.put(message)

    def broadcast_to_shard_for_miner(message: dict, shard_id: int):
        if len(user_node.peers[0]) > 0:
            miner_node.message_queue.put(message)

    miner_node._broadcast_to_shard = broadcast_to_shard_for_user
    user_node._broadcast_to_shard = broadcast_to_shard_for_miner

    miner_node._broadcast_to_all = broadcast_to_user
    user_node._broadcast_to_all = broadcast_to_miner

    # start miner node
    miner_node.start()

    stake_tx = create_stake_transaction(miner_node, 0)
    miner_node.add_and_broadcast_stake_transaction(stake_tx)

    time.sleep(Constants.TIME_TO_SLEEP * 1.5)

    # start user node
    user_node.start()

    miner_node.peers[0].add((host, user_port))
    user_node.peers[0].add((host, miner_port))

    user_node._broadcast_request_chain()

    time.sleep(5)

    coins_to_send = 3
    tx = create_transaction(miner_node, to_address=user_node.address, amount=coins_to_send)
    miner_node.add_and_broadcast_tx(tx)

    time.sleep(Constants.TIME_TO_SLEEP * 2)

    miner_chain = copy.deepcopy(miner_node.blockchain.chain)
    user_chain = copy.deepcopy(user_node.blockchain.chain)

    miner_balance = miner_node.blockchain.get_balance(miner_node.address)
    user_balance = user_node.blockchain.get_balance(user_node.address)

    expected_miner_balance = Constants.MINER_REWARD * 2 - coins_to_send
    expected_user_balance = coins_to_send

    assert len(miner_chain) == 3, "Expected 3 miner blocks (including genesis)"
    assert len(user_chain) == 3, "Expected 3 user blocks (including genesis)"

    assert miner_balance == expected_miner_balance, \
        f"The miner balance should be {expected_miner_balance}, but it is {miner_balance}"
    assert user_balance == expected_user_balance, \
        f"The user balance should be {expected_user_balance}, but it is {user_balance}"

def test_node_can_synchronize_beacon_chain_in_two_shards(temp_wallet_file_shard0, temp_wallet_file_shard1):
    Constants.NUMBER_OF_SHARDS = 2

    host = "127.0.0.1"
    miner_port0 = 1111
    miner_port1 = 2222

    miner_node0 = Node(host=host, port=miner_port0, role=Role.MINER, wallet_file=temp_wallet_file_shard0)
    miner_node1 = Node(host=host, port=miner_port1, role=Role.MINER, wallet_file=temp_wallet_file_shard1)

    # mocks
    miner_node0.external_ip = host
    miner_node1.external_ip = host

    miner_node0._listen_tcp = None
    miner_node1._listen_tcp = None

    miner_node0._handle_tcp_connection = None
    miner_node1._handle_tcp_connection = None

    miner_node0._listen_discovery = None
    miner_node1._listen_discovery = None

    miner_node0._broadcast_presence = None
    miner_node1._broadcast_presence = None

    miner_node0._broadcast = lambda x: None
    miner_node1._broadcast = lambda x: None

    def broadcast_to_all_beacon_node_of_shard1(message: dict):
        if len(miner_node0.peers[1]) > 0:
            miner_node1.message_queue.put(message)

    def broadcast_to_all_beacon_node_of_shard0(message: dict):
        if len(miner_node1.peers[0]) > 0:
            miner_node0.message_queue.put(message)

    miner_node0._broadcast_to_all_beacon_nodes = broadcast_to_all_beacon_node_of_shard1
    miner_node1._broadcast_to_all_beacon_nodes = broadcast_to_all_beacon_node_of_shard0

    miner_node0._broadcast_to_user = lambda x: None
    miner_node1._broadcast_to_user = lambda x: None

    def broadcast_to_shard1(message: dict, shard_id: int):
        if len(miner_node0.peers[1]) > 0:
            miner_node1.message_queue.put(message)

    def broadcast_to_shard0(message: dict, shard_id: int):
        if len(miner_node1.peers[0]) > 0:
            miner_node0.message_queue.put(message)

    miner_node0._broadcast_to_shard = broadcast_to_shard1
    miner_node1._broadcast_to_shard = broadcast_to_shard0

    miner_node0._broadcast_to_all = broadcast_to_all_beacon_node_of_shard1
    miner_node1._broadcast_to_all = broadcast_to_all_beacon_node_of_shard0

    # start miner nodes
    miner_node0.start()
    stake_tx = create_stake_transaction(miner_node0, 0)
    miner_node0.add_and_broadcast_stake_transaction(stake_tx)

    time.sleep(3)

    miner_node1.start()
    stake_tx = create_stake_transaction(miner_node1, 0)
    miner_node1.add_and_broadcast_stake_transaction(stake_tx)

    miner_node0.peers[1].add((host, miner_port1))
    miner_node1.peers[0].add((host, miner_port0))

    miner_node0.beacon_nodes.add(f"{host}:{miner_port1}")
    miner_node1.beacon_nodes.add(f"{host}:{miner_port0}")

    miner_node0.stakes[f"{host}:{miner_port0}"] = 0
    miner_node0.stakes[f"{host}:{miner_port1}"] = 0
    miner_node1.stakes[f"{host}:{miner_port0}"] = 0
    miner_node1.stakes[f"{host}:{miner_port1}"] = 0

    time.sleep(Constants.TIME_TO_SLEEP * 1.5)

    miner_chain0 = copy.deepcopy(miner_node0.beacon.chain)
    miner_chain1 = copy.deepcopy(miner_node1.beacon.chain)

    miner_balance0 = miner_node0.blockchain.get_balance(miner_node0.address)
    miner_balance1 = miner_node1.blockchain.get_balance(miner_node1.address)

    assert len(miner_chain0) == 2, "Expected 2 miner0 beacon blocks (including genesis)"
    assert len(miner_chain1) == 2, "Expected 2 miner1 beacon blocks (including genesis)"

    assert [b.to_dict() for b in miner_chain0] == [b.to_dict() for b in miner_chain1], "Expected that the beacon chains are identical"
    assert len(miner_chain0[-1].snapshots) == 2, "Expected 2 snaps in the beacon chain"

    assert miner_balance0 == Constants.MINER_REWARD, f"The miner balance should be {Constants.MINER_REWARD}, but it is {miner_balance0}"
    assert miner_balance1 == Constants.MINER_REWARD, f"The miner balance should be {Constants.MINER_REWARD}, but it is {miner_balance1}"

def test_cross_transaction_propagates_between_two_shards(temp_wallet_file_shard0, temp_wallet_file_shard1):
    Constants.NUMBER_OF_SHARDS = 2

    host = "127.0.0.1"
    miner_port0 = 1111
    miner_port1 = 2222

    miner_node0 = Node(host=host, port=miner_port0, role=Role.MINER, wallet_file=temp_wallet_file_shard0)
    miner_node1 = Node(host=host, port=miner_port1, role=Role.MINER, wallet_file=temp_wallet_file_shard1)

    # mocks
    miner_node0.external_ip = host
    miner_node1.external_ip = host

    miner_node0._listen_tcp = None
    miner_node1._listen_tcp = None

    miner_node0._handle_tcp_connection = None
    miner_node1._handle_tcp_connection = None

    miner_node0._listen_discovery = None
    miner_node1._listen_discovery = None

    miner_node0._broadcast_presence = None
    miner_node1._broadcast_presence = None

    miner_node0._broadcast = lambda x: None
    miner_node1._broadcast = lambda x: None

    def broadcast_to_all_beacon_node_of_shard1(message: dict):
        if len(miner_node0.peers[1]) > 0:
            miner_node1.message_queue.put(message)

    def broadcast_to_all_beacon_node_of_shard0(message: dict):
        if len(miner_node1.peers[0]) > 0:
            miner_node0.message_queue.put(message)

    miner_node0._broadcast_to_all_beacon_nodes = broadcast_to_all_beacon_node_of_shard1
    miner_node1._broadcast_to_all_beacon_nodes = broadcast_to_all_beacon_node_of_shard0

    miner_node0._broadcast_to_user = lambda x: None
    miner_node1._broadcast_to_user = lambda x: None

    def broadcast_to_shard1(message: dict, shard_id: int):
        if shard_id == 1 and len(miner_node0.peers[1]) > 0:
            miner_node1.message_queue.put(message)

    def broadcast_to_shard0(message: dict, shard_id: int):
        if shard_id == 0 and len(miner_node1.peers[0]) > 0:
            miner_node0.message_queue.put(message)

    miner_node0._broadcast_to_shard = broadcast_to_shard1
    miner_node1._broadcast_to_shard = broadcast_to_shard0

    miner_node0._broadcast_to_all = broadcast_to_all_beacon_node_of_shard1
    miner_node1._broadcast_to_all = broadcast_to_all_beacon_node_of_shard0

    # start miner nodes
    miner_node0.start()
    stake_tx = create_stake_transaction(miner_node0, 0)
    miner_node0.add_and_broadcast_stake_transaction(stake_tx)

    time.sleep(3)

    miner_node1.start()
    stake_tx = create_stake_transaction(miner_node1, 0)
    miner_node1.add_and_broadcast_stake_transaction(stake_tx)

    miner_node0.peers[1].add((host, miner_port1))
    miner_node1.peers[0].add((host, miner_port0))

    miner_node0.beacon_nodes.add(f"{host}:{miner_port1}")
    miner_node1.beacon_nodes.add(f"{host}:{miner_port0}")

    miner_node0.stakes[f"{host}:{miner_port0}"] = 0
    miner_node0.stakes[f"{host}:{miner_port1}"] = 0
    miner_node1.stakes[f"{host}:{miner_port0}"] = 0
    miner_node1.stakes[f"{host}:{miner_port1}"] = 0

    time.sleep(Constants.TIME_TO_SLEEP * 1.5)

    coins_to_send = 3
    tx = create_transaction(miner_node0, to_address=miner_node1.address, amount=coins_to_send)
    miner_node0.add_and_broadcast_tx(tx)

    time.sleep(Constants.TIME_TO_SLEEP)

    miner_chain0 = copy.deepcopy(miner_node0.beacon.chain)
    miner_chain1 = copy.deepcopy(miner_node1.beacon.chain)

    assert len(miner_chain0) == 3, "Expected 3 miner0 beacon blocks (including genesis)"
    assert len(miner_chain1) == 3, "Expected 3 miner1 beacon blocks (including genesis)"

    miner_chain0 = copy.deepcopy(miner_node0.blockchain.chain)
    miner_chain1 = copy.deepcopy(miner_node1.blockchain.chain)

    miner_balance0 = miner_node0.blockchain.get_balance(miner_node0.address)
    miner_balance1 = miner_node1.blockchain.get_balance(miner_node1.address)

    expected_miner_balance0 = Constants.MINER_REWARD * 2 - coins_to_send
    expected_miner_balance1 = Constants.MINER_REWARD * 2 + coins_to_send

    assert len(miner_chain0) == 3, "Expected 3 miner0 blocks (including genesis)"
    assert len(miner_chain1) == 3, "Expected 3 miner1 blocks (including genesis)"

    assert miner_balance0 == expected_miner_balance0, \
        f"The miner0 balance should be {expected_miner_balance0}, but it is {miner_balance0}"
    assert miner_balance1 == expected_miner_balance1, \
        f"The miner1 balance should be {expected_miner_balance1}, but it is {miner_balance1}"