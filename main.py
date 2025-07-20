import sys
import socket
import random
import os

from constants import Role, Constants, MetadataType, Stage
from node import Node
from shard_service import ShardService
from transaction import TxInput, TxOutput, Transaction
from wallet import save_wallet, generate_keypair

WALLET_FILE = os.getenv("WALLET_FILE", "my_wallet.txt")

def ensure_wallet():
    if not os.path.exists(WALLET_FILE):
        print("🔐 Wallet not found. Generate a new one...")
        priv, _ = generate_keypair()
        save_wallet(WALLET_FILE, priv)
        print("✅ The wallet is saved in", WALLET_FILE)

def choose_port(default=5000, max_attempts=100):
    for _ in range(max_attempts):
        port = default + random.randint(0, 1000)
        try:
            s = socket.socket()
            s.bind(("127.0.0.1", port))
            s.close()
            return port
        except:
            continue
    raise Exception("❌ Failed to select a free port")

def show_menu(node: Node):
    while True:
        print("\n===== Menu =====")
        print("1. Show address")
        print("2. Show balance")
        print("3. Send coins")
        print("4. Show blockchain")
        print("5. Show peers")
        print("6. Show number of shard")
        print("7. Become a Beacon validator")
        print("8. Show beacon")
        print("9. Show beacon nodes")
        print("0. Exit")

        choice = input("Choice: ").strip()
        if choice == "1":
            print("🏠 Address:", node.address)

        elif choice == "2":
            bal = node.blockchain.get_balance(node.address)
            print(f"💰 Balance: {bal} BTC")

        elif choice == "3":
            if node.get_stage() != Stage.TX:
                print("Wait a little bit... And repeat")
                continue
            to = input("Recipient (address): ").strip()
            amt = input("Amount of coins: ").strip()
            try:
                amt = int(amt)
                tx = create_transaction(node, to, amt)
                if tx:
                    node.add_and_broadcast_tx(tx)
            except:
                print(f"❌ Data error")

        elif choice == "4":
            node.blockchain.print_chain()

        elif choice == "5":
            print("🔗 Connected peers:")
            for shard_id, peers in node.peers.items():
                print(f" Shard {shard_id}: ")
                for peer in peers:
                    print(f"   -{peer}")

        elif choice == "6":
            print(f"Your number of shard: {ShardService.get_shard_id(node.address)}")

        elif choice == "7":
            if node.get_stage() != Stage.TX:
                print("Wait a little bit... And repeat")
                continue
            if node.is_beacon_node():
                print(f"You are already a Beacon node")
                continue

            stake = input("Stake: ").strip()
            try:
                stake = int(stake)
                tx = create_stake_transaction(node, stake)
                if tx:
                    node.add_and_broadcast_stake_transaction(tx)
            except Exception:
                print(f"❌ Data error")
            print(f"")

        elif choice == "8":
            node.beacon.print_chain()

        elif choice == "9":
            print(list(node.beacon_nodes))

        elif choice == "0":
            node.disconnect()
            print("👋 Goodbye!")
            break
        else:
            print("⚠️ Incorrect input")

def create_stake_transaction(node: Node,
                             stake: int) -> Transaction | None:
    utxos = node.blockchain.get_effective_utxo_set()
    my_address = node.address
    my_privkey = node.private_key

    selected_inputs = []
    total = 0

    for txid, outputs in utxos.items():
        for index, out in outputs.items():
            if out.address == my_address:
                selected_inputs.append((txid, index, out.amount))
                total += out.amount
                if total >= stake:
                    break
        if total >= stake:
            break

    if total < stake:
        print("❌ No suitable outputs")
        return None

    inputs = [TxInput(txid, index) for txid, index, _ in selected_inputs]
    outputs = []
    if total > stake:
        outputs.append(TxOutput(total - stake, my_address))

    tx = Transaction(inputs, outputs, metadata={
        MetadataType.EPOCH: Constants.EPOCH,
        MetadataType.STAKE: stake,
        MetadataType.ADDRESS: my_address
    })
    for i in range(len(inputs)):
        tx.sign_input(i, my_privkey)
    return tx

def create_transaction(node: Node, to_address: str, amount: int) -> Transaction | None:
    utxos = node.blockchain.get_effective_utxo_set()
    my_address = node.address
    my_privkey = node.private_key

    selected_inputs = []
    total = 0

    for txid, outputs in utxos.items():
        for index, out in outputs.items():
            if out.address == my_address:
                selected_inputs.append((txid, index, out.amount))
                total += out.amount
                if total >= amount:
                    break
        if total >= amount:
            break

    if total < amount:
        print("❌ No suitable outputs")
        return None

    inputs = [TxInput(txid, index) for txid, index, _ in selected_inputs]
    outputs = [TxOutput(amount, to_address)]
    if total > amount:
        outputs.append(TxOutput(total - amount, my_address))

    tx = Transaction(inputs, outputs)
    for i in range(len(inputs)):
        tx.sign_input(i, my_privkey)
    return tx

if __name__ == "__main__":
    role = Role.USER

    if len(sys.argv) > 1:
        command = sys.argv[1]
        if command == "miner":
            role = Role.MINER

    ensure_wallet()
    port = choose_port()
    node = Node("0.0.0.0", port, role=role)
    node.start()

    show_menu(node)
