import json
import random
import sys
import time

from constants import Role, Stage, Constants
from deserialize_service import DeserializeService
from main import choose_port, create_transaction
from node import Node
from shard_service import ShardService
from wallet import load_wallet, get_public_key, pubkey_to_address

amount_of_generated_blocks = 3
coins_to_send = 1
delay = 0.01

def start_best_case_research(node: Node, addresses: list[str]) -> (int, float): # (amount of added txs, time)
    amount_of_blocks_before = len(node.blockchain.chain)

    amount_of_added_txs = 0
    start = time.time()

    while len(node.blockchain.chain) - amount_of_blocks_before != amount_of_generated_blocks:
        if node.get_stage() != Stage.TX:
            time.sleep(delay)
            continue

        address = random.choice([a for a in addresses
                                 if ShardService.get_shard_id(a) == ShardService.get_shard_id(node.address)])

        tx = create_transaction(node, address, coins_to_send)
        if node.add_and_broadcast_tx(tx):
            amount_of_added_txs += 1

        time.sleep(delay)

    return amount_of_added_txs, time.time() - start

def start_worse_case_research(node: Node, addresses: list[str]) -> (int, float): # (amount of added txs, time)
    amount_of_blocks_before = len(node.blockchain.chain)

    amount_of_added_txs = 0
    start = time.time()

    while len(node.blockchain.chain) - amount_of_blocks_before != amount_of_generated_blocks:
        if node.get_stage() != Stage.TX:
            time.sleep(delay)
            continue

        address = random.choice([a for a in addresses
                                 if ShardService.get_shard_id(a) != ShardService.get_shard_id(node.address)])

        tx = create_transaction(node, address, coins_to_send)
        if node.add_and_broadcast_tx(tx):
            amount_of_added_txs += 1

        time.sleep(delay)

    return amount_of_added_txs, time.time() - start

def start_random_case_research(node: Node, addresses: list[str]) -> (int, float): # (amount of added txs, time)
    amount_of_blocks_before = len(node.blockchain.chain)

    amount_of_added_txs = 0
    start = time.time()

    while len(node.blockchain.chain) - amount_of_blocks_before != amount_of_generated_blocks:
        if node.get_stage() != Stage.TX:
            time.sleep(delay)
            continue

        tx = create_transaction(node, random.choice(addresses), coins_to_send)
        if node.add_and_broadcast_tx(tx):
            amount_of_added_txs += 1

        time.sleep(delay)

    return amount_of_added_txs, time.time() - start

def show_menu(node: Node):
    addresses = get_addresses(node)

    while True:
        print("\n===== Menu =====")
        print("1. Start best case research")
        print("2. Start worse case research")
        print("3. Start random case research")
        print("0. Exit")

        choice = input("Choice: ").strip()
        if choice == "1":
            print("Best case research started")
            tx_amount, sec = start_best_case_research(node, addresses)
            print("Amount of transactions: ", tx_amount)
            print("Time spent: ", sec / 60.0, " minutes")
            print("TPS: ", tx_amount / sec)

        elif choice == "2":
            print("Worse case research started")
            tx_amount, sec = start_worse_case_research(node, addresses)
            print("Amount of transactions: ", tx_amount)
            print("Time spent: ", sec / 60.0, " minutes")
            print("TPS: ", tx_amount / sec)

        elif choice == "3":
            print("Random case research started")
            tx_amount, sec = start_random_case_research(node, addresses)
            print("Amount of transactions: ", tx_amount)
            print("Time spent: ", sec / 60.0, " minutes")
            print("TPS: ", tx_amount / sec)

        elif choice == "0":
            node.disconnect()
            print("👋 Goodbye!")
            break
        else:
            print("⚠️ Incorrect input")

def prepare_node(node: Node):
    shard_id = ShardService.get_shard_id(node.address)

    with open(f"research_files/blockchain_shard{shard_id}.json", "r") as f:
        blockchain_data = json.load(f)
        blocks, utxo = DeserializeService.deserialize_chain(blockchain_data)
        node.blockchain.chain = blocks
        node.blockchain.utxo_set = utxo

    with open(f"research_files/beacon.json", "r") as f:
        beacon_data = json.load(f)
        blocks = DeserializeService.deserialize_beacon_chain(beacon_data)
        node.beacon.chain = blocks

    node.stakes[f"{node.external_ip}:{node.port}"] = 0

def get_addresses(node: Node) -> list[str]:
    wallet_files = [
        "research_files/miner_wallet_shard0.txt",
        "research_files/miner_wallet_shard1.txt",
        "research_files/user_wallet_shard0.txt",
        "research_files/user_wallet_shard1.txt"
    ]

    pr_keys: list[str] = []

    for wallet_f in wallet_files:
        pr_keys.append(load_wallet(wallet_f))

    return [pubkey_to_address(get_public_key(pr_key))
            for pr_key in pr_keys
            if pr_key != node.private_key]

if __name__ == "__main__":
    role = Role.USER
    Constants.EPOCH = 10000
    Constants.TIME_TO_SLEEP = 600
    AMOUNT_OF_START_BLOCKS = 30
    shard = None
    wallet_file = "my_wallet.txt"

    if len(sys.argv) > 1:
        command = sys.argv[1]
        shard = int(sys.argv[2])
        if command == "miner":
            role = Role.MINER
            if shard == 0:
                wallet_file = "research_files/miner_wallet_shard0.txt"
            elif shard == 1:
                wallet_file = "research_files/miner_wallet_shard1.txt"
        elif command == "user":
            role = Role.USER
            if shard == 0:
                wallet_file = "research_files/user_wallet_shard0.txt"
            elif shard == 1:
                wallet_file = "research_files/user_wallet_shard1.txt"

    port = choose_port()
    node = Node("0.0.0.0", port, role=role, wallet_file=wallet_file)

    if role == Role.MINER:
        print("Preparation started...")
        prepare_node(node)
        print("Preparation finished")

    node.start()

    while True:
        time.sleep(2)
        if len(node.blockchain.chain) >= AMOUNT_OF_START_BLOCKS:
            break

    print("❗❗❗You can start research...")
    show_menu(node)