import queue
import random
import socket
import threading
import json
import time
from typing import Optional

from beacon import BeaconChain, BeaconBlock
from blockchain import Blockchain, Block
from constants import MessageType, MessageField, DisconnectField, Role, Constants, MetadataType, BeaconNodeField, \
    BeaconNodeDisconnectField, CreatorField, SignatureField, RequestBeaconField, RebroadcastField, Stage, \
    TxIdSendingField, GetTxsField
from deserialize_service import DeserializeService
from shard_service import ShardService
from snapshot import Snapshot
from transaction import Transaction, TxOutput
from wallet import load_wallet, pubkey_to_address, get_public_key


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
        self.private_key = load_wallet(wallet_file)
        self.public_key = get_public_key(self.private_key)
        self.address = pubkey_to_address(self.public_key)
        self._discovery_port = 9000
        self._external_ip = _get_local_ip()
        self.role = role

        self._pending_blocks: dict[str, list] = {}
        self._block_lock = threading.Lock()

        self._stake_blocks: set[int] = set()
        self.beacon_nodes: set = set()
        self.stakes: dict[str, int] = {}
        self.beacon = BeaconChain()
        self._new_beacon_block: Optional[BeaconBlock] = None

        self._message_queue = queue.Queue()

        self.stage: Stage = Stage.TX
        self._stage_lock = threading.Lock()

        self._final_block: Optional[Block] = None
        self._final_block_lock = threading.Lock()

        self._amount_of_shards_with_cross_txs: int = 0
        self._tx_lock = threading.Lock()

        self._mining_thread = None

        print(f"🟢 Node launched at {self._external_ip}:{self._port}")
        print(f"🏠 Wallet address: {self.address[:8]}...")

    def set_final_block(self, block: Optional[Block]):
        with self._final_block_lock:
            self._final_block = block

    def get_final_block(self) -> Optional[Block]:
        with self._final_block_lock:
            return self._final_block

    def set_stage(self, stage: Stage):
        with self._stage_lock:
            self.stage = stage

    def get_stage(self) -> Stage:
        with self._stage_lock:
            return self.stage

    def inc_amount_of_shards_with_cross_txs(self):
        with self._tx_lock:
            self._amount_of_shards_with_cross_txs += 1

    def restart_amount_of_shards_with_cross_txs(self):
        with self._tx_lock:
            self._amount_of_shards_with_cross_txs = 0

    def get_amount_of_shards_with_cross_txs(self) -> int:
        with self._tx_lock:
            return self._amount_of_shards_with_cross_txs

    def start(self):
        threading.Thread(target=self._listen_tcp, daemon=True).start()
        threading.Thread(target=self._listen_discovery, daemon=True).start()
        threading.Thread(target=self._broadcast_presence, daemon=True).start()
        threading.Thread(target=self._process_message_queue, daemon=True).start()

        self._mining_thread = threading.Thread(target=self._broadcast_mining, daemon=True)
        self._mining_thread.start()

    def _check_cross_transaction_sending(self):
        if self.is_beacon_node() and self._is_beacon_leader():
            last_block = self.beacon.chain[-1]
            result = {
                shard_id: []
                for shard_id in range(Constants.NUMBER_OF_SHARDS)
            }
            for snap in last_block.snapshots:
                for shard_id, txs in snap.cross_shard_receipts.items():
                    result[snap.shard_id].extend(txs)
            for shard_id in range(Constants.NUMBER_OF_SHARDS):
                self._broadcast_tx_id_sending(shard_id, result[shard_id])
                if shard_id == ShardService.get_shard_id(self.address):
                    self._message_queue.put({
                        MessageField.TYPE: MessageType.TX_ID_SENDING,
                        MessageField.DATA: {
                            TxIdSendingField.TX_IDS: result[shard_id]
                        }
                    })

    def _process_message_queue(self):
        while True:
            time.sleep(3)
            message = self._message_queue.get()
            try:
                self._handle_message(message)
            except Exception as e:
                print(f"❌ Error handling message: {e}")

    def is_beacon_node(self) -> bool:
        return len(self.beacon.chain) > 0

    def disconnect(self):
        if self.is_beacon_node():
            self._broadcast_beacon_node_disconnect()
        self._broadcast_disconnect()

    def become_a_beacon_validator(self, tx: Transaction):
        stake = tx.metadata[MetadataType.STAKE]
        self.stakes[f"{self._external_ip}:{self._port}"] = stake

        time.sleep(3)
        if len(self.beacon_nodes) == 0:
            self.beacon.start()

        if len(self.beacon_nodes) > 0:
            self._broadcast_request_beacon_chain()

    def _update_stake(self):
        for stake_block in self._stake_blocks.copy():
            if len(self.blockchain.chain) <= stake_block:
                break
            block: Block = self.blockchain.chain[stake_block]
            stake_txs = [tx for tx in block.transactions if tx.is_stake()]
            if len(stake_txs) > 0 and stake_block + Constants.EPOCH < len(self.blockchain.chain):
                for tx in stake_txs:
                    refund = Transaction([],
                                         [TxOutput(Constants.MINER_REWARD + tx.metadata[MetadataType.STAKE],
                                                   tx.metadata[MetadataType.ADDRESS])],
                                         metadata={MetadataType.REFUND: True},
                                         )
                    if self.blockchain.add_refund_transaction(refund):
                        self._broadcast_refund_transaction(refund)
                        self._stake_blocks.remove(stake_block)
                        self.beacon.clear()
                        self._broadcast_beacon_node_disconnect()
                        self._message_queue.put({
                            MessageField.TYPE: MessageType.BEACON_NODE_DISCONNECT,
                            MessageField.DATA: {
                                BeaconNodeDisconnectField.HOST: self._external_ip,
                                BeaconNodeDisconnectField.PORT: self._port,
                            }
                        })

    def _verify_and_add_block(self, block):
        if block.previous_hash == self.blockchain.chain[-1].hash():
            if self.blockchain.validate_block(block):
                self.blockchain.pending_txs.clear()
                self.blockchain.chain.append(block)
                for tx in block.transactions:
                    self.blockchain.update_utxo_set(tx, ShardService.get_shard_id(self.address))
                return True
            else:
                print("❌ The block did not pass validation")
        return False

    def _try_to_send_snapshot(self, block: Block) -> None:
        if self._is_leader():
            snapshot = Snapshot(shard_id=ShardService.get_shard_id(self.address),
                                block_number=block.index,
                                block_hash=block.hash(),
                                cross_shard_receipts=self._get_cross_shard_tx(block))
            self._broadcast_snapshot(snapshot)
            if self.is_beacon_node():
                self._message_queue.put({
                    MessageField.TYPE: MessageType.SNAPSHOT,
                    MessageField.DATA: snapshot.to_dict(),
                })

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
            self._message_queue.put(message)
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

    def _broadcast_tx_id_sending(self, shard_id: int, tx_ids: list):
        message = {
            MessageField.TYPE: MessageType.TX_ID_SENDING,
            MessageField.DATA: {
                TxIdSendingField.TX_IDS: tx_ids
            }
        }
        self._broadcast_to_shard(message, shard_id)

    def _try_to_add_block(self):
        if len(self._pending_blocks) > 0:
            best_block, best_votes = self._get_best_pending_block()
            if 2 * best_votes >= len(self.peers[ShardService.get_shard_id(self.address)]):
                self._finalize_block(block=best_block)
                self._message_queue.put(
                    {
                        MessageField.TYPE: MessageType.FINALISE_BLOCK,
                        MessageField.DATA: best_block.to_dict()
                    }
                )

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
        if len(self.beacon.pending_snapshots) == Constants.NUMBER_OF_SHARDS:
            if not self._is_beacon_leader():
                return

            creator_address = self._select_beacon_block_proposer()
            ip, port = creator_address.split(":")
            self._broadcast_creator_of_beacon_block(ip, int(port))
            message = {
                MessageField.TYPE: MessageType.CREATOR,
                MessageField.DATA: {
                    CreatorField.HOST: ip,
                    CreatorField.PORT: port
                }
            }
            self._message_queue.put(message)

    def _send_txs(self, tx_ids: list):
        if not self._is_leader():
            return
        tx_set = set(tx_ids)
        txs: list[Transaction] = [tx for tx in self.get_final_block().transactions if tx.hash() in tx_set]

        my_shard = ShardService.get_shard_id(self.address)
        result = { to_shard: [] for to_shard in range(Constants.NUMBER_OF_SHARDS) }

        for tx in txs:
            for out in tx.outputs:
                out_shard = ShardService.get_shard_id(out.address)
                if out_shard != my_shard:
                    result[out_shard].append(tx)
                    break

        for to_shard, txs in result.items():
            self._broadcast_txs(to_shard, txs)
        self._message_queue.put({
            MessageField.TYPE: MessageType.GET_TXS,
            MessageField.DATA: { GetTxsField.TRANSACTIONS: [tx.to_dict() for tx in result[my_shard]] }
        })

    def _handle_message(self, message: dict):
        msg_type = message.get(MessageField.TYPE)
        data = message.get(MessageField.DATA)

        if msg_type == MessageType.TX:
            print("TX message")
            tx = DeserializeService.deserialize_tx(data)
            self.blockchain.add_transaction(tx)

        elif msg_type == MessageType.GET_TXS:
            txs = DeserializeService.deserialize_txs(data)
            print(f"GET_TXS message")
            for tx in txs:
                self.blockchain.update_utxo_set(tx, ShardService.get_shard_id(self.address))
            if self._is_leader():
                self._broadcast_to_all_beacon_nodes({MessageField.TYPE: MessageType.TXS_RECEIVED})
                self._message_queue.put({MessageField.TYPE: MessageType.TXS_RECEIVED})

        elif msg_type == MessageType.TXS_RECEIVED:
            if self._is_beacon_leader():
                print("TXS_RECEIVED message")
                self.inc_amount_of_shards_with_cross_txs()

                if self.get_amount_of_shards_with_cross_txs() == Constants.NUMBER_OF_SHARDS:
                    self.restart_amount_of_shards_with_cross_txs()
                    self._broadcast_continue_mining()
                    self._message_queue.put({MessageField.TYPE: MessageType.CONTINUE_MINING})

        elif msg_type == MessageType.TX_ID_SENDING:
            if self._is_leader():
                tx_ids = DeserializeService.deserialize_tx_id_sending(data)
                self._send_txs(tx_ids)

        elif msg_type == MessageType.REFUND:
            print("REFUND message")
            tx = DeserializeService.deserialize_tx(data)
            self.blockchain.add_refund_transaction(tx)

        elif msg_type == MessageType.FINALISE_BLOCK:
            print("FINALISE_BLOCK message")
            block = DeserializeService.deserialize_block(data)
            self._clear_pending_blocks()
            self.set_final_block(block)
            self._try_to_send_snapshot(block)

        elif msg_type == MessageType.REBROADCAST:
            print("REBROADCAST message")
            self.set_stage(Stage.MINING)
            host, port, block = DeserializeService.deserialize_rebroadcast(data)

            if host != self._external_ip or port != int(self._port):
                if block.previous_hash == self.blockchain.chain[-1].hash():
                    if self.blockchain.validate_block(block):
                        self._register_pending_block(block)

            self._try_to_add_block()

        elif msg_type == MessageType.BLOCK:
            print("BLOCK message")
            self.set_stage(Stage.MINING)
            block = DeserializeService.deserialize_block(data)

            if block.previous_hash == self.blockchain.chain[-1].hash():
                self._register_pending_block(block)
                self._rebroadcast_block(block)
                self._message_queue.put(
                    {
                        MessageField.TYPE: MessageType.REBROADCAST,
                        MessageField.DATA: {
                            RebroadcastField.HOST: self._external_ip,
                            RebroadcastField.PORT: self._port,
                            RebroadcastField.BLOCK: block.to_dict()
                        }
                    }
                )


        elif msg_type == MessageType.REQUEST_CHAIN:
            print("REQUEST_CHAIN message")
            self._broadcast_chain()

        elif msg_type == MessageType.CHAIN:
            print("CHAIN message")
            blocks = DeserializeService.deserialize_chain(data)
            self.blockchain.try_to_update_chain(blocks)

        elif msg_type == MessageType.SNAPSHOT:
            print("SNAPSHOT message")
            if self.is_beacon_node():
                snapshot = DeserializeService.deserialize_snapshot(data)
                self.beacon.add_snapshot(snapshot)
                self._try_to_choose_creator_of_beacon_block()

        elif msg_type == MessageType.MINING:
            print("MINING message")
            self.set_stage(Stage.MINING)
            if self.role == Role.MINER:
                block = self.blockchain.mine_block(self.address)
                self._register_pending_block(block)

                self._broadcast_block(block)
                self._message_queue.put({
                    MessageField.TYPE: MessageType.BLOCK,
                    MessageField.DATA: block.to_dict()
                })

        elif msg_type == MessageType.DISCONNECT:
            print("DISCONNECT message")
            peer_to_remove = DeserializeService.deserialize_disconnect(data)
            self.peers[peer_to_remove[2]].remove(peer_to_remove[:1])

        elif msg_type == MessageType.BEACON_NODE_DISCONNECT:
            print("BEACON NODE_DISCONNECT message")
            ip, port, stake = DeserializeService.deserialize_beacon_node(data)
            full_ip = f"{ip}:{port}"
            self.beacon_nodes.remove(full_ip)
            self.stakes.pop(full_ip, None)

        elif msg_type == MessageType.CREATOR:
            print("CREATOR message")
            ip, port = DeserializeService.deserialize_creator_of_beacon_node(data)
            if ip == self._external_ip and int(port) == self._port:
                self._send_beacon_block()

        elif msg_type == MessageType.BEACON_BLOCK:
            print("BEACON BLOCK message")
            block = DeserializeService.deserialize_beacon_block(data)
            if self.is_beacon_node():
                if self.beacon.validate_block(block):
                    signature = block.sign_block(self.private_key)
                    self._broadcast_signature(signature)
                    self._message_queue.put(
                        {
                            MessageField.TYPE: MessageType.SIGNATURE,
                            MessageField.DATA: {
                                SignatureField.ADDRESS: self.address,
                                SignatureField.SIGNATURE: signature
                            }
                        }
                    )

        elif msg_type == MessageType.SIGNATURE:
            print("SIGNATURE message")
            address, signature = DeserializeService.deserialize_signature(data)

            if self._is_beacon_creator():
                self._new_beacon_block.add_signature(address, signature)
                if self._try_to_add_beacon_block():
                    self._broadcast_broadcast_beacon_block()
                    self._message_queue.put(
                        {
                            MessageField.TYPE: MessageType.BROADCAST_BEACON_BLOCK,
                            MessageField.DATA: self._new_beacon_block.to_dict()
                        }
                    )

        elif msg_type == MessageType.BROADCAST_BEACON_BLOCK:
            if self.get_stage() == Stage.MINING and self.get_final_block():
                print("BROADCAST BEACON BLOCK message")
                block = DeserializeService.deserialize_beacon_block(data)
                self._new_beacon_block = None

                if self.is_beacon_node():
                    self.beacon.add_block(block)
                    self._check_cross_transaction_sending()

        elif msg_type == MessageType.CONTINUE_MINING:
            if self.get_final_block():
                print("CONTINUE_MINING message")
                self._verify_and_add_block(self.get_final_block())
                self.set_final_block(None)
                if self.is_beacon_node():
                    self._update_stake()
                self.set_stage(Stage.TX)
                self._mining_thread = threading.Thread(target=self._broadcast_mining, daemon=True)
                self._mining_thread.start()

        elif msg_type == MessageType.REQUEST_BEACON:
            print("REQUEST_BEACON message")
            ip, port = DeserializeService.deserialize_request_beacon_chain(data)
            if self.is_beacon_node():
                self._broadcast_beacon_chain(f"{ip}:{port}")

        elif msg_type == MessageType.BEACON_CHAIN:
            print("BEACON CHAIN message")
            blocks = DeserializeService.deserialize_beacon_chain(data)
            self.beacon.start_with_chain(blocks)

        else:
            print("⚠️ Unknown message type:", msg_type)

    def _broadcast_continue_mining(self):
        self._broadcast_to_all({
            MessageField.TYPE: MessageType.CONTINUE_MINING
        })

    def _broadcast_txs(self, to_shard: int, txs: list):
        self._broadcast_to_shard(
            {
                MessageField.TYPE: MessageType.GET_TXS,
                MessageField.DATA: {
                    GetTxsField.TRANSACTIONS: [tx.to_dict() for tx in txs]
                }
            },
            shard_id= to_shard
        )

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
            if ip != self._external_ip or int(port) != self._port:
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
        self._message_queue.put(
            {
                MessageField.TYPE: MessageType.BEACON_BLOCK,
                MessageField.DATA: self._new_beacon_block.to_dict()
            }
        )

    def _finalize_block(self, block: Block):
        self._broadcast({
            MessageField.TYPE: MessageType.FINALISE_BLOCK,
            MessageField.DATA: block.to_dict()
        })

    def _rebroadcast_block(self, block: Block):
        self._broadcast({
            MessageField.TYPE: MessageType.REBROADCAST,
            MessageField.DATA: {
                RebroadcastField.HOST: self._external_ip,
                RebroadcastField.PORT: self._port,
                RebroadcastField.BLOCK: block.to_dict()
            }
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

    def _broadcast_to_shard(self, message: dict, shard_id: int):
        raw = json.dumps(message).encode()
        for peer in self.peers[shard_id].copy():
            try:
                with socket.socket() as s:
                    s.connect(peer)
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
                ip = self._external_ip
                port = self._port
                shard_id = ShardService.get_shard_id(self.address)
                is_beacon = self.is_beacon_node()
                stake = self.stakes[f"{ip}:{port}"] if is_beacon else 0

                response = f"{ip}:{port}:{shard_id}:{is_beacon}:{stake}"
                sock.sendto(response.encode(), addr)

    def _broadcast_request_chain(self):
        self._broadcast({
            MessageField.TYPE: MessageType.REQUEST_CHAIN
        })

    def _broadcast_mining(self):
        time.sleep(Constants.TIME_TO_SLEEP)
        if self._is_leader():
            message = {MessageField.TYPE: MessageType.MINING}
            self._broadcast(message)
            if self.role == Role.MINER:
                self._message_queue.put(message)

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
                        peer_host, peer_port, shard_id, is_beacon, stake = data.decode().split(":")
                        if peer_host == self._external_ip and int(peer_port) == self._port:
                            continue
                        print(f"Came: {peer_host}:{peer_port}:{shard_id}:{is_beacon}:{stake}")
                        peer = (peer_host, int(peer_port))
                        self.peers[int(shard_id)].add(peer)

                        full_ip = f"{peer_host}:{peer_port}"

                        if bool(is_beacon):
                            if full_ip not in self.beacon_nodes:
                                self.beacon_nodes.add(full_ip)
                                self.stakes[full_ip] = int(stake)
                        else:
                            self.beacon_nodes.remove(full_ip)
                            self.stakes.pop(full_ip, None)

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
