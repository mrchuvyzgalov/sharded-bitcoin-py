import random
import socket
import threading
import json
import time

from beacon import BeaconChain, BeaconBlock
from blockchain import Blockchain, Block
from constants import MessageType, MessageField, DisconnectField, Role, Constants, MetadataType, BeaconNodeField, \
    BeaconNodeDisconnectField, CreatorField, SignatureField, RequestBeaconField
from deserialize_service import DeserializeService
from shard_service import ShardService
from snapshot import Snapshot
from transaction import Transaction, TxOutput
from wallet import load_wallet, pubkey_to_address


def _get_local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
    except Exception:
        ip = "127.0.0.1"
    finally:
        s.close()
    return ip


class Node:
    def __init__(self, host: str, port: int, role: Role = Role.USER, wallet_file="my_wallet.txt"):
        self._host = host
        self._port = port
        self.peers: dict[int, set] = {
            shard_id: set()
            for shard_id in range(Constants.NUMBER_OF_SHARDS)
        } # {shard : {peers} }
        self.blockchain = Blockchain()
        self.wallet = load_wallet(wallet_file)
        self.address = pubkey_to_address(self.wallet)
        self._discovery_port = 9000
        self._external_ip = _get_local_ip()
        self.role = role
        self._pending_blocks: dict[str, list] = {}
        self._block_lock = threading.Lock()
        self._stake_blocks: set[int] = set()
        self.beacon_nodes: set = set()
        self.stakes: dict[str, int] = {}
        self.beacon = BeaconChain()
        self._pending_snapshots: dict[int, Snapshot] = {}
        self._new_beacon_block: BeaconBlock = None

        print(f"🟢 Node launched at {self._external_ip}:{self._port}")
        print(f"🏠 Wallet address: {self.address[:8]}...")

    def start(self):
        threading.Thread(target=self._listen_tcp, daemon=True).start()
        threading.Thread(target=self._listen_discovery, daemon=True).start()
        threading.Thread(target=self._broadcast_presence, daemon=True).start()
        threading.Thread(target=self._broadcast_mining, daemon=True).start()
        threading.Thread(target=self._update_stake, daemon=True).start()

    def is_beacon_node(self) -> bool:
        return len(self.beacon.chain) > 0

    def disconnect(self):
        self._broadcast_disconnect()

    def become_a_beacon_validator(self, tx: Transaction):
        if len(self.beacon_nodes) == 0:
            self.beacon.start()

        stake = tx.metadata[MetadataType.STAKE]
        self.stakes[f"{self._external_ip}:{self._port}"] = stake

        if len(self.beacon_nodes) > 0:
            self._broadcast_request_beacon_chain()

    def _update_stake(self):
        while True:
            for stake_block in self._stake_blocks.copy():
                if len(self.blockchain.chain) <= stake_block:
                    break
                block: Block = self.blockchain.chain[stake_block]
                stake_txs = [tx for tx in block.transactions if tx.is_stake()]
                if len(stake_txs) > 0 and stake_block + Constants.EPOCH < len(self.blockchain.chain):
                    for tx in stake_txs:
                        refund = Transaction([],
                                             [TxOutput(Constants.MINER_REWARD + tx.metadata[MetadataType.STAKE],tx.metadata[MetadataType.ADDRESS])],
                                             metadata={ MetadataType.REFUND: True },
                                             )
                        if self.blockchain.add_refund_transaction(refund):
                            self._broadcast_refund_transaction(refund)
                            self._stake_blocks.remove(stake_block)
                            self.beacon.clear()
                            self._broadcast_beacon_node_disconnect()
            time.sleep(Constants.TIME_TO_SLEEP)

    def _verify_and_add_block(self, block):
        if block.previous_hash == self.blockchain.chain[-1].hash():
            self._clear_pending_blocks()
            if self.blockchain.validate_block(block):
                self.blockchain.chain.append(block)
                for tx in block.transactions:
                    self.blockchain.update_utxo_set(tx)
                self._try_to_send_snapshot(block)
                return True
            else:
                print("❌ The block did not pass validation")
        return False

    def _try_to_send_snapshot(self, block: Block) -> None:
        print("Trying to send snapshot...")
        if self._is_leader():
            snapshot = Snapshot(shard_id=ShardService.get_shard_id(self.address),
                                block_number=block.index,
                                block_hash=block.hash(),
                                cross_shard_receipts=self._get_cross_shard_tx(block))
            print(f"Snapshot: {snapshot.to_dict()}")
            self._broadcast_snapshot(snapshot)
            message = {
                MessageField.TYPE: MessageType.SNAPSHOT,
                MessageField.DATA: snapshot.to_dict(),
            }
            self._handle_message(message)

    def _get_cross_shard_tx(self, block: Block):
        result: dict[int, list] = {
            shard_id: list()
            for shard_id in range(Constants.NUMBER_OF_SHARDS)
            if shard_id != ShardService.get_shard_id(self.address)
        }

        for tx in block.transactions:
            if tx.is_cross_shard():
                result[tx.get_shard_destination()].append(tx.hash())

        return result

    def _listen_tcp(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind((self._host, self._port))
        sock.listen()
        print("📥 Waiting for TCP connections...")
        while True:
            conn, _ = sock.accept()
            threading.Thread(target=self._handle_tcp_connection, args=(conn,), daemon=True).start()

    def _handle_tcp_connection(self, conn):
        try:
            data = conn.recv(100000).decode()
            if not data:
                return
            message = json.loads(data)
            self._handle_message(message)
        except Exception as e:
            print("❌ TCP error:", e)
        finally:
            conn.close()

    def _register_pending_block(self, block):
        block_hash = block.hash()
        with self._block_lock:
            if block_hash not in self._pending_blocks:
                self._pending_blocks[block_hash] = [block, 1]
            else:
                self._pending_blocks[block_hash][1] += 1

    def _get_best_pending_block(self):
        with self._block_lock:
            if not self._pending_blocks:
                return None
            block, votes = max(self._pending_blocks.values(), key=lambda x: x[1])
            return block, votes

    def _clear_pending_blocks(self):
        with self._block_lock:
            self._pending_blocks.clear()

    def _try_to_add_block(self):
        if len(self._pending_blocks) > 0:
            best_block, best_votes = self._get_best_pending_block()
            if 2 * best_votes >= len(self.peers[ShardService.get_shard_id(self.address)]):
                if len(self.peers[ShardService.get_shard_id(self.address)]) > 0:
                    self._finalize_block(best_block)
                self._verify_and_add_block(best_block)

    def _select_beacon_block_proposer(self) -> str:
        total_stake = sum(self.stakes.values())
        r = random.uniform(0, total_stake)
        acc = 0
        for validator, stake in self.stakes.items():
            acc += stake
            if acc >= r:
                return validator
        return list(self.stakes.keys())[-1]

    def _try_to_choose_creator_of_beacon_block(self):
        print(f"Amount of snaps: {self.beacon.pending_snapshots}")
        print(f"Is B Leader: {self._is_beacon_leader()}")
        if len(self.beacon.pending_snapshots) == Constants.NUMBER_OF_SHARDS:
            if not self._is_beacon_leader():
                return

            creator_address = self._select_beacon_block_proposer()
            print(creator_address)
            ip, port = creator_address.split(":")
            self._broadcast_creator_of_beacon_block(ip, int(port))
            message = {
                MessageField.TYPE: MessageType.CREATOR,
                MessageField.DATA: {
                    CreatorField.HOST: ip,
                    CreatorField.PORT: port
                }
            }
            self._handle_message(message)
            pass

    def _handle_message(self, message: dict):
        msg_type = message.get(MessageField.TYPE)
        data = message.get(MessageField.DATA)

        if msg_type == MessageType.TX:
            tx = DeserializeService.deserialize_tx(data)
            self.blockchain.add_transaction(tx)

        elif msg_type == MessageType.REFUND:
            tx = DeserializeService.deserialize_tx(data)
            self.blockchain.add_refund_transaction(tx)

        elif msg_type == MessageType.FINALISE_BLOCK:
            block = DeserializeService.deserialize_block(data)
            self._verify_and_add_block(block)

        elif msg_type == MessageType.REBROADCAST:
            block = DeserializeService.deserialize_block(data)

            if block.previous_hash == self.blockchain.chain[-1].hash():
                if self.blockchain.validate_block(block):
                    self._register_pending_block(block)

            self._try_to_add_block()

        elif msg_type == MessageType.BLOCK:
            block = DeserializeService.deserialize_block(data)

            if block.previous_hash == self.blockchain.chain[-1].hash():
                if self.blockchain.validate_block(block):
                    self._register_pending_block(block)
                    self._rebroadcast_block(block)

        elif msg_type == MessageType.REQUEST_CHAIN:
            self._broadcast_chain()

        elif msg_type == MessageType.CHAIN:
            blocks = DeserializeService.deserialize_chain(data)
            self.blockchain.try_to_update_chain(blocks)

        elif msg_type == MessageType.SNAPSHOT:
            print("Received Snapshot")
            if self.is_beacon_node():
                snapshot = DeserializeService.deserialize_snapshot(data)
                self.beacon.add_snapshot(snapshot)
                self._try_to_choose_creator_of_beacon_block()

        elif msg_type == MessageType.MINING:
            if self.role == Role.MINER:
                block = self.blockchain.mine_block(self.address)
                self._register_pending_block(block)

                if len(self.peers[ShardService.get_shard_id(self.address)]) > 0:
                    self._broadcast_block(block)
                else:
                    self._try_to_add_block()

        elif msg_type == MessageType.DISCONNECT:
            peer_to_remove = DeserializeService.deserialize_disconnect(data)
            self.peers[peer_to_remove[2]].remove(peer_to_remove[:1])

        elif msg_type == MessageType.BEACON_NODE:
            ip, port, stake = DeserializeService.deserialize_beacon_node(data)
            beacon_peer = f"{ip}:{port}"
            if beacon_peer not in self.beacon_nodes:
                self.beacon_nodes.add(beacon_peer)
                if self.is_beacon_node():
                    self._broadcast_beacon_node(self.stakes[f"{self._external_ip}:{self._port}"])
                print(f"New Node: {list(self.beacon_nodes)}")

        elif msg_type == MessageType.BEACON_NODE_DISCONNECT:
            ip, port, stake = DeserializeService.deserialize_beacon_node(data)
            self.beacon_nodes.remove(f"{ip}:{port}")
            del self.stakes[f"{ip}:{port}"]
            print(f"Remove Node: {list(self.beacon_nodes)}")

        elif msg_type == MessageType.CREATOR:
            print(f"CREATOR MESSAGE: {data}")
            ip, port = DeserializeService.deserialize_creator_of_beacon_node(data)
            if ip == self._external_ip and int(port) == self._port:
                print(f"Try to send beacon block: {data}")
                self._send_beacon_block()

        elif msg_type == MessageType.BEACON_BLOCK:
            block = DeserializeService.deserialize_beacon_block(data)
            if self.is_beacon_node():
                print(f"B BLOCK: {block.snapshots}")
                if self.beacon.validate_block(block):
                    print(f"Signing block: {block.to_dict()}")
                    signature = block.sign_block(self.wallet)
                    self._broadcast_signature(signature)

                    if len(self.beacon_nodes) == 0:
                        print("Try to add blocks")
                        if self._try_to_add_beacon_block():
                            print("Block added")
                            self._new_beacon_block = None


        elif msg_type == MessageType.SIGNATURE:
            address, signature = DeserializeService.deserialize_signature(data)

            if self._is_beacon_creator():
                self._new_beacon_block.add_signature(address, signature)
                if self._try_to_add_beacon_block():
                    self._broadcast_broadcast_beacon_block()
                    self._new_beacon_block = None

        elif msg_type == MessageType.BROADCAST_BEACON_BLOCK:
            block = DeserializeService.deserialize_beacon_block(data)

            if self.is_beacon_node():
                self.beacon.add_block(block)

        elif msg_type == MessageType.REQUEST_BEACON:
            ip, port = DeserializeService.deserialize_request_beacon_chain(data)
            if self.is_beacon_node():
                self._broadcast_beacon_chain(f"{ip}:{port}")

        elif msg_type == MessageType.BEACON_NODE:
            blocks = DeserializeService.deserialize_beacon_chain(data)
            self.beacon.start_with_chain(blocks)
            stake = self.stakes[f"{self._external_ip}:{self._port}"]
            self._broadcast_beacon_node(stake)

        else:
            print("⚠️ Unknown message type:", msg_type)

    def _broadcast_request_beacon_chain(self):
        self._broadcast_to_all_beacon_nodes(
            {
                MessageField.TYPE: MessageType.REQUEST_BEACON,
                MessageField.DATA: {
                    RequestBeaconField.HOST: self._external_ip,
                    RequestBeaconField.PORT: self._port,
                }
            }
        )

    def _broadcast_broadcast_beacon_block(self):
        self._broadcast_to_all_beacon_nodes({
            MessageField.TYPE: MessageType.BROADCAST_BEACON_BLOCK,
            MessageField.DATA: self._new_beacon_block.to_dict()
        })

    def _broadcast_to_all_beacon_nodes(self, message: dict):
        raw = json.dumps(message).encode()
        for node in self.beacon_nodes:
            ip, port = node.split(":")
            peer = (ip, int(port))
            try:
                with socket.socket() as s:
                    s.connect(peer)
                    s.send(raw)
            except Exception as e:
                print(f"❌ Failed to send {message['type']} → {peer}: {e}")

    def _try_to_add_beacon_block(self) -> bool:
        if not self._is_beacon_creator():
            return False
        if not self.is_beacon_node():
            return False
        elif 3 * len(self._new_beacon_block.validator_signatures) >= 2 * len(self.beacon_nodes):
            self.beacon.add_block(self._new_beacon_block)
            return True
        return False

    def _is_beacon_creator(self):
        return (self._new_beacon_block is not None) and (self._new_beacon_block.proposer_address == self.address)

    def _broadcast_signature(self, signature: str):
        self._broadcast_to_all_beacon_nodes({
            MessageField.TYPE: MessageType.SIGNATURE,
            MessageField.DATA: {
                SignatureField.ADDRESS: self.address,
                SignatureField.SIGNATURE: signature
            }
        })

    def _send_beacon_block(self):
        self._new_beacon_block = self.beacon.form_block(self.address)
        self._broadcast_beacon_block(self._new_beacon_block)

        if len(self.beacon_nodes) == 0:
            message = {
                MessageField.TYPE: MessageType.BEACON_BLOCK,
                MessageField.DATA: self._new_beacon_block.to_dict()
            }
            self._handle_message(message)

    def _finalize_block(self, block: Block):
        self._broadcast({
            MessageField.TYPE: MessageType.FINALISE_BLOCK,
            MessageField.DATA: block.to_dict()
        })

    def _rebroadcast_block(self, block: Block):
        self._broadcast({
            MessageField.TYPE: MessageType.REBROADCAST,
            MessageField.DATA: block.to_dict()
        })

    def _broadcast_disconnect(self):
        self._broadcast({
            MessageField.TYPE: MessageType.DISCONNECT,
            MessageField.DATA: {
                DisconnectField.HOST: self._external_ip,
                DisconnectField.PORT: self._port,
                DisconnectField.SHARD: ShardService.get_shard_id(self.address)
            }
        })

    def _broadcast_beacon_chain(self, peer: str):
        self._broadcast_to_user({
            MessageField.TYPE: MessageType.BEACON_CHAIN,
            MessageField.DATA: self.beacon.to_dict()
        },
            peer
        )

    def _broadcast_to_user(self, message: dict, peer: str):
        raw = json.dumps(message).encode()
        ip, port = peer.split(":")
        try:
            with socket.socket() as s:
                s.connect((ip, int(port)))
                s.send(raw)
        except Exception as e:
            print(f"❌ Failed to send {message['type']} → {peer}: {e}")

    def _broadcast(self, message: dict):
        raw = json.dumps(message).encode()
        for peer in self.peers[ShardService.get_shard_id(self.address)].copy():
            try:
                with socket.socket() as s:
                    s.connect(peer)
                    s.send(raw)
            except Exception as e:
                print(f"❌ Failed to send {message['type']} → {peer}: {e}")

    def _broadcast_to_all(self, message: dict):
        raw = json.dumps(message).encode()
        for shard in range(Constants.NUMBER_OF_SHARDS):
            for peer in self.peers[shard].copy():
                try:
                    with socket.socket() as s:
                        s.connect(peer)
                        s.send(raw)
                except Exception as e:
                    print(f"❌ Failed to send {message['type']} → {peer}: {e}")

    def _broadcast_creator_of_beacon_block(self, ip: str, port: int):
        self._broadcast_to_all_beacon_nodes({
            MessageField.TYPE: MessageType.CREATOR,
            MessageField.DATA: {
                CreatorField.HOST: ip,
                CreatorField.PORT: port
            }
        })

    def _broadcast_snapshot(self, snapshot: Snapshot):
        self._broadcast_to_all_beacon_nodes({
            MessageField.TYPE: MessageType.SNAPSHOT,
            MessageField.DATA: snapshot.to_dict()
        })

    def _broadcast_chain(self):
        self._broadcast({
            MessageField.TYPE: MessageType.CHAIN,
            MessageField.DATA: self.blockchain.to_dict()})

    def _broadcast_beacon_node(self, stake: int):
        self._broadcast_to_all({
            MessageField.TYPE: MessageType.BEACON_NODE,
            MessageField.DATA: {
                BeaconNodeField.HOST: self._external_ip,
                BeaconNodeField.PORT: self._port,
                BeaconNodeField.STAKE: stake
            }
        })

    def _broadcast_beacon_node_disconnect(self):
        self._broadcast_to_all({
            MessageField.TYPE: MessageType.BEACON_NODE_DISCONNECT,
            MessageField.DATA: {
                BeaconNodeDisconnectField.HOST: self._external_ip,
                BeaconNodeDisconnectField.PORT: self._port,
            }
        })

    def _broadcast_refund_transaction(self, tx: Transaction):
        self._broadcast({
            MessageField.TYPE: MessageType.REFUND,
            MessageField.DATA: tx.to_dict()
        })

    def broadcast_transaction(self, tx: Transaction):
        self._broadcast({
            MessageField.TYPE: MessageType.TX,
            MessageField.DATA: tx.to_dict()
        })

    def broadcast_stake_transaction(self, tx: Transaction):
        self._stake_blocks.add(len(self.blockchain.chain))
        self.broadcast_transaction(tx)

    def _broadcast_block(self, block):
        self._broadcast({
            MessageField.TYPE: MessageType.BLOCK,
            MessageField.DATA: block.to_dict()
        })

    def _broadcast_beacon_block(self, block: BeaconBlock):
        self._broadcast_to_all_beacon_nodes({
            MessageField.TYPE: MessageType.BEACON_BLOCK,
            MessageField.DATA: block.to_dict()
        })

    def _listen_discovery(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind(('', self._discovery_port))
        while True:
            data, addr = sock.recvfrom(1024)
            if data == b"DISCOVER":
                response = f"{self._external_ip}:{self._port}:{ShardService.get_shard_id(self.address)}"
                sock.sendto(response.encode(), addr)

    def _broadcast_request_chain(self):
        self._broadcast({
            MessageField.TYPE: MessageType.REQUEST_CHAIN
        })

    def _broadcast_mining(self):
        while True:
            time.sleep(Constants.TIME_TO_SLEEP)
            if self._is_leader():
                message = {MessageField.TYPE: MessageType.MINING}
                self._broadcast(message)
                if self.role == Role.MINER:
                    self._handle_message(message)

    def _broadcast_presence(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        while True:
            try:
                sock.sendto(b"DISCOVER", ('<broadcast>', self._discovery_port))
                sock.settimeout(1.0)
                while True:
                    try:
                        data, addr = sock.recvfrom(1024)
                        peer_host, peer_port, shard_id = data.decode().split(":")
                        if peer_host == self._external_ip and int(peer_port) == self._port:
                            continue
                        peer = (peer_host, int(peer_port))
                        self.peers[int(shard_id)].add(peer)
                        if len(self.blockchain.chain) < 3:
                            self._broadcast_request_chain()
                    except socket.timeout:
                        break
            except Exception as e:
                print("Error during UDP discovery:", e)
            time.sleep(5)

    def _is_leader(self) -> bool:
        my_id = f"{self._external_ip}:{self._port}"
        peer_ids = [f"{host}:{port}" for (host, port) in self.peers[ShardService.get_shard_id(self.address)]]
        return my_id == min([my_id] + peer_ids)

    def _is_beacon_leader(self) -> bool:
        if not self.is_beacon_node():
            return False

        my_id = f"{self._external_ip}:{self._port}"
        peers_ids = [node_address for node_address in self.beacon_nodes]
        return my_id == min([my_id] + peers_ids)
