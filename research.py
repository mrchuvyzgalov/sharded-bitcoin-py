import json
import random
import sys
import time

from constants import Role, Stage, Constants
from deserialize_service import DeserializeService
from main import ensure_wallet, choose_port, create_stake_transaction, create_transaction
from node import Node
from shard_service import ShardService

amount_of_generated_blocks = 3
coins_to_send = 1
delay = 0.12

def start_best_case_research(node: Node, addresses: list[str]) -> (int, float): # (amount of added txs, time)
    amount_of_blocks_before = len(node.blockchain.chain)

    amount_of_added_txs = 0
    start = time.time()

    while len(node.blockchain.chain) - amount_of_blocks_before != amount_of_generated_blocks:
        if node.get_stage() != Stage.TX:
            time.sleep(delay)
            continue

        address = random.choice([a for a in addresses if ShardService.get_shard_id(a) == node.address])

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

        address = random.choice([a for a in addresses if ShardService.get_shard_id(a) != node.address])

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
    addresses = list()
    while True:
        print("\n===== Menu =====")
        print("1. Show address")
        print("2. Add address")
        print("3. Show blockchain")
        print("4. Show peers")
        print("5. Show number of shard")
        print("6. Become a Beacon validator")
        print("7. Show beacon")
        print("8. Show beacon nodes")
        print("9. Start best case research")
        print("10. Start worse case research")
        print("11. Start random case research")
        print("0. Exit")

        choice = input("Choice: ").strip()
        if choice == "1":
            print("🏠 Address:", node.address)

        elif choice == "2":
            address = input("Address: ")
            addresses.append(address)
            print("Address was added")

        elif choice == "3":
            node.blockchain.print_chain()

        elif choice == "4":
            print("🔗 Connected peers:")
            for shard_id, peers in node.peers.items():
                print(f" Shard {shard_id}: ")
                for peer in peers:
                    print(f"   -{peer}")

        elif choice == "5":
            print(f"Your number of shard: {ShardService.get_shard_id(node.address)}")

        elif choice == "6":
            if node.get_stage() != Stage.TX:
                print("Wait a little bit... And repeat")
                continue
            if node.is_beacon_node():
                print(f"You are already a Beacon node")
                continue

            stake = 0
            try:
                stake = int(stake)
                tx = create_stake_transaction(node, stake)
                if tx:
                    node.add_and_broadcast_stake_transaction(tx)
            except Exception:
                print(f"❌ Data error")
            print(f"")

        elif choice == "7":
            node.beacon.print_chain()

        elif choice == "8":
            print(list(node.beacon_nodes))

        elif choice == "9":
            print("Best case research started")
            tx_amount, sec = start_best_case_research(node, addresses)
            print("Amount of transactions: ", tx_amount)
            print("Time spent: ", sec / 60.0, " minutes")
            print("TPS: ", tx_amount / sec)

        elif choice == "10":
            print("Worse case research started")
            tx_amount, sec = start_worse_case_research(node, addresses)
            print("Amount of transactions: ", tx_amount)
            print("Time spent: ", sec / 60.0, " minutes")
            print("TPS: ", tx_amount / sec)

        elif choice == "11":
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

    with open(f"research_files/blockchain_shard{shard_id}", "r") as f:
        blockchain_data = json.load(f)
        blocks, utxo = DeserializeService.deserialize_chain(blockchain_data)
        node.blockchain.chain = blocks
        node.blockchain.utxo_set = utxo

    with open(f"research_files/beacon.json", "r") as f:
        beacon_data = json.load(f)
        blocks = DeserializeService.deserialize_beacon_chain(beacon_data)
        node.beacon.chain = blocks

if __name__ == "__main__":
    role = Role.USER
    Constants.EPOCH = 10000
    shard = None

    if len(sys.argv) > 1:
        command = sys.argv[1]
        shard = int(sys.argv[2])
        if command == "miner":
            role = Role.MINER

    wallet_file = "my_wallet.txt"

    if shard == 0:
        wallet_file = "research_files/my_wallet_shard0.txt"
    elif shard == 1:
        wallet_file = "research_files/my_wallet_shard1.txt"
    else:
        ensure_wallet()
    port = choose_port()
    node = Node("0.0.0.0", port, role=role, wallet_file=wallet_file)

    if role == Role.MINER:
        print("Preparation started...")
        prepare_node(node)
        print("Preparation finished")

    node.start()

    show_menu(node)