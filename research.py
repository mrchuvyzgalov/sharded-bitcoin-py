import json
import random
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np

from constants import Role, Stage, Constants
from deserialize_service import DeserializeService
from main import choose_port, create_transaction
from node import Node
from shard_service import ShardService
from wallet import load_wallet, get_public_key, pubkey_to_address

amount_of_generated_blocks = 3
coins_to_send = 1
delay = 0.01

def start_best_case_research(node: Node, addresses: list[str]) -> None:
    # time_of_work, amount of transactions, tps, transaction latency

    amount_of_blocks_before = len(node.blockchain.chain)

    tx_submit_time = {}
    tx_latencies = []

    old_amount_of_blocks = len(node.blockchain.chain)

    amount_of_added_txs = 0
    start = time.time()

    while len(node.blockchain.chain) - amount_of_blocks_before != amount_of_generated_blocks:
        if len(node.blockchain.chain) - old_amount_of_blocks == 1:
            old_amount_of_blocks = len(node.blockchain.chain)

            for tx in node.blockchain.chain[-1].transactions:
                tx_id = tx.hash()
                if tx_id in tx_submit_time:
                    latency = time.time() - tx_submit_time[tx_id]
                    tx_latencies.append(latency)

        if node.get_stage() != Stage.TX:
            time.sleep(delay)
            continue

        address = random.choice([a for a in addresses
                                 if ShardService.get_shard_id(a) == ShardService.get_shard_id(node.address)])

        tx = create_transaction(node, address, coins_to_send)
        if node.add_and_broadcast_tx(tx):
            amount_of_added_txs += 1
            tx_submit_time[tx.hash()] = time.time()

        time.sleep(delay)

    time_of_work = time.time() - start
    tps = amount_of_added_txs / time_of_work

    print("Amount of transactions: ", amount_of_added_txs)
    print("Time spent: ", time_of_work / 60.0, " minutes")
    print("TPS: ", tps)

    print("📊 Transaction Latency (ms):")
    with open("research_files/t_latency.txt", "w") as f:
        for item in tx_latencies:
            f.write(f"{item}\n")
    print(f"  avg: {np.mean(tx_latencies) * 1000:.2}")
    print(f"  min: {np.min(tx_latencies) * 1000:.2}")
    print(f"  max: {np.max(tx_latencies) * 1000:.2}")
    print(f"  std: {np.std(tx_latencies) * 1000:.2}")

    # read_latency

    latencies = []
    addresses.append(node.address)

    for i in range(2000):
        addr = addresses[i % len(addresses)]
        if ShardService.get_shard_id(addr) != ShardService.get_shard_id(node.address):
            continue
        t1 = time.perf_counter()
        node.blockchain.get_balance(addr)
        t2 = time.perf_counter()
        latencies.append(t2 - t1)

    print("Read Latency (ns):")
    print(f"  avg: {statistics.mean(latencies) * 1_000_000_000:.2f}")
    print(f"  min: {min(latencies) * 1_000_000_000:.2f}")
    print(f"  max: {max(latencies) * 1_000_000_000:.2f}")
    print(f"  std: {statistics.stdev(latencies) * 1_000_000_000:.2f}")

    # read_throughput

    NUM_THREADS = 10
    READS_PER_THREAD = 1000

    def read_task():
        count = 0
        for i in range(READS_PER_THREAD):
            node.blockchain.get_balance(node.address)
            count += 1
        return count

    start = time.time()
    with ThreadPoolExecutor(max_workers=NUM_THREADS) as executor:
        futures = [executor.submit(read_task) for _ in range(NUM_THREADS)]
        results = [f.result() for f in futures]
    end = time.time()

    total_reads = sum(results)
    throughput = total_reads / (end - start)
    print(f"Read Throughput: {throughput:.2f} reads/sec")

def start_worse_case_research(node: Node, addresses: list[str]) -> None:
    # time_of_work, amount of transactions, tps, transaction latency

    amount_of_blocks_before = len(node.blockchain.chain)

    tx_submit_time = {}
    tx_latencies = []

    old_amount_of_blocks = len(node.blockchain.chain)

    amount_of_added_txs = 0
    start = time.time()

    while len(node.blockchain.chain) - amount_of_blocks_before != amount_of_generated_blocks:
        if len(node.blockchain.chain) - old_amount_of_blocks == 1:
            old_amount_of_blocks = len(node.blockchain.chain)

            for tx in node.blockchain.chain[-1].transactions:
                tx_id = tx.hash()
                if tx_id in tx_submit_time:
                    latency = time.time() - tx_submit_time[tx_id]
                    tx_latencies.append(latency)

        if node.get_stage() != Stage.TX:
            time.sleep(delay)
            continue

        address = random.choice([a for a in addresses
                                 if ShardService.get_shard_id(a) != ShardService.get_shard_id(node.address)])

        tx = create_transaction(node, address, coins_to_send)
        if node.add_and_broadcast_tx(tx):
            amount_of_added_txs += 1
            tx_submit_time[tx.hash()] = time.time()

        time.sleep(delay)

    time_of_work = time.time() - start
    tps = amount_of_added_txs / time_of_work

    print("Amount of transactions: ", amount_of_added_txs)
    print("Time spent: ", time_of_work / 60.0, " minutes")
    print("TPS: ", tps)

    print("📊 Transaction Latency (ms):")
    with open("research_files/t_latency.txt", "w") as f:
        for item in tx_latencies:
            f.write(f"{item}\n")
    print(f"  avg: {np.mean(tx_latencies) * 1000:.2}")
    print(f"  min: {np.min(tx_latencies) * 1000:.2}")
    print(f"  max: {np.max(tx_latencies) * 1000:.2}")
    print(f"  std: {np.std(tx_latencies) * 1000:.2}")

    # read_latency

    latencies = []
    addresses.append(node.address)

    for i in range(2000):
        addr = addresses[i % len(addresses)]
        if ShardService.get_shard_id(addr) != ShardService.get_shard_id(node.address):
            continue
        t1 = time.perf_counter()
        node.blockchain.get_balance(addr)
        t2 = time.perf_counter()
        latencies.append(t2 - t1)

    print("Read Latency (ns):")
    print(f"  avg: {statistics.mean(latencies) * 1_000_000_000:.2f}")
    print(f"  min: {min(latencies) * 1_000_000_000:.2f}")
    print(f"  max: {max(latencies) * 1_000_000_000:.2f}")
    print(f"  std: {statistics.stdev(latencies) * 1_000_000_000:.2f}")

    # read_throughput

    NUM_THREADS = 10
    READS_PER_THREAD = 1000

    def read_task():
        count = 0
        for i in range(READS_PER_THREAD):
            node.blockchain.get_balance(node.address)
            count += 1
        return count

    start = time.time()
    with ThreadPoolExecutor(max_workers=NUM_THREADS) as executor:
        futures = [executor.submit(read_task) for _ in range(NUM_THREADS)]
        results = [f.result() for f in futures]
    end = time.time()

    total_reads = sum(results)
    throughput = total_reads / (end - start)
    print(f"Read Throughput: {throughput:.2f} reads/sec")


def start_random_case_research(node: Node, addresses: list[str]) -> None:
    # time_of_work, amount of transactions, tps, transaction latency

    amount_of_blocks_before = len(node.blockchain.chain)

    tx_submit_time = {}
    tx_latencies = []

    old_amount_of_blocks = len(node.blockchain.chain)

    amount_of_added_txs = 0
    start = time.time()

    while len(node.blockchain.chain) - amount_of_blocks_before != amount_of_generated_blocks:
        if len(node.blockchain.chain) - old_amount_of_blocks == 1:
            old_amount_of_blocks = len(node.blockchain.chain)

            for tx in node.blockchain.chain[-1].transactions:
                tx_id = tx.hash()
                if tx_id in tx_submit_time:
                    latency = time.time() - tx_submit_time[tx_id]
                    tx_latencies.append(latency)

        if node.get_stage() != Stage.TX:
            time.sleep(delay)
            continue

        tx = create_transaction(node, random.choice(addresses), coins_to_send)
        if node.add_and_broadcast_tx(tx):
            amount_of_added_txs += 1
            tx_submit_time[tx.hash()] = time.time()

        time.sleep(delay)

    time_of_work = time.time() - start
    tps = amount_of_added_txs / time_of_work

    print("Amount of transactions: ", amount_of_added_txs)
    print("Time spent: ", time_of_work / 60.0, " minutes")
    print("TPS: ", tps)

    print("📊 Transaction Latency (ms):")
    with open("research_files/t_latency.txt", "w") as f:
        for item in tx_latencies:
            f.write(f"{item}\n")
    print(f"  avg: {np.mean(tx_latencies) * 1000:.2}")
    print(f"  min: {np.min(tx_latencies) * 1000:.2}")
    print(f"  max: {np.max(tx_latencies) * 1000:.2}")
    print(f"  std: {np.std(tx_latencies) * 1000:.2}")

    # read_latency

    latencies = []
    addresses.append(node.address)

    for i in range(2000):
        addr = addresses[i % len(addresses)]
        if ShardService.get_shard_id(addr) != ShardService.get_shard_id(node.address):
            continue
        t1 = time.perf_counter()
        node.blockchain.get_balance(addr)
        t2 = time.perf_counter()
        latencies.append(t2 - t1)

    print("Read Latency (ns):")
    print(f"  avg: {statistics.mean(latencies) * 1_000_000_000:.2f}")
    print(f"  min: {min(latencies) * 1_000_000_000:.2f}")
    print(f"  max: {max(latencies) * 1_000_000_000:.2f}")
    print(f"  std: {statistics.stdev(latencies) * 1_000_000_000:.2f}")

    # read_throughput

    NUM_THREADS = 10
    READS_PER_THREAD = 1000

    def read_task():
        count = 0
        for i in range(READS_PER_THREAD):
            node.blockchain.get_balance(node.address)
            count += 1
        return count

    start = time.time()
    with ThreadPoolExecutor(max_workers=NUM_THREADS) as executor:
        futures = [executor.submit(read_task) for _ in range(NUM_THREADS)]
        results = [f.result() for f in futures]
    end = time.time()

    total_reads = sum(results)
    throughput = total_reads / (end - start)
    print(f"Read Throughput: {throughput:.2f} reads/sec")

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
            start_best_case_research(node, addresses)
            print("Best case research finished")

        elif choice == "2":
            print("Worse case research started")
            start_worse_case_research(node, addresses)
            print("Worse case research finished")

        elif choice == "3":
            print("Random case research started")
            start_random_case_research(node, addresses)
            print("Random case research finished")

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