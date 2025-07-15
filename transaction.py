import hashlib
import json
import ecdsa
import base64

from constants import TxInputField, TxOutputField, MetadataType, TxField
from shard_service import ShardService


class TxInput:
    def __init__(self,
                 tx_id: str,
                 index: int,
                 signature: str = "",
                 pubkey: str = "") -> None:
        self.tx_id = tx_id  # ID of last transaction
        self.index = index  # index of output
        self.signature = signature
        self.pubkey = pubkey

    def to_dict(self) -> dict:
        return {
            TxInputField.TX_ID: self.tx_id,
            TxInputField.INDEX: self.index,
            TxInputField.SIGNATURE: self.signature,
            TxInputField.PUBKEY: self.pubkey
        }


class TxOutput:
    def __init__(self,
                 amount: int,
                 address: str) -> None:
        self.amount = amount
        self.address = address  # address of receiver

    def to_dict(self) -> dict:
        return {
            TxOutputField.AMOUNT: self.amount,
            TxOutputField.ADDRESS: self.address
        }


class Transaction:
    def __init__(self,
                 inputs: list[TxInput],
                 outputs: list[TxOutput],
                 metadata: dict = None) -> None:
        self.inputs = inputs
        self.outputs = outputs
        self.metadata = metadata or {}

    def is_coinbase(self) -> bool:
        return MetadataType.HEIGHT in self.metadata

    def to_dict(self, include_signatures=True) -> dict:
        return {
            TxField.INPUTS: [i.to_dict() if include_signatures else {
                TxInputField.TX_ID: i.tx_id,
                TxInputField.INDEX: i.index
            } for i in self.inputs],
            TxField.OUTPUTS: [o.to_dict() for o in self.outputs],
            TxField.METADATA: self.metadata
        }

    def to_json(self, include_signatures=True) -> str:
        return json.dumps(self.to_dict(include_signatures), sort_keys=True)

    def is_cross_shard(self) -> bool:
        if self.is_coinbase() or self.is_stake():
            return False
        shard_id_sender = ShardService.get_shard_id(self.inputs[0].pubkey)
        return shard_id_sender != self.get_shard_destination()

    def is_stake(self) -> bool:
        return MetadataType.EPOCH in self.metadata

    def is_refund(self) -> bool:
        return MetadataType.REFUND in self.metadata

    def get_shard_destination(self) -> int:
        shard_id_receivers = list(set([ShardService.get_shard_id(out.address) for out in self.outputs]))
        if self.is_coinbase():
            return shard_id_receivers[0]
        shard_id_sender = ShardService.get_shard_id(self.inputs[0].pubkey)
        return next((x for x in shard_id_receivers if x != shard_id_sender), None)

    def hash(self) -> str:
        tx_str = self.to_json(include_signatures=False)
        return hashlib.sha256(tx_str.encode()).hexdigest()

    def sign_input(self, index: int, privkey_wif: str) -> None:
        sk = ecdsa.SigningKey.from_string(base64.b64decode(privkey_wif), curve=ecdsa.SECP256k1)
        message = self.hash()
        signature = sk.sign(message.encode())
        self.inputs[index].signature = base64.b64encode(signature).decode()
        self.inputs[index].pubkey = base64.b64encode(sk.get_verifying_key().to_string()).decode()

    def is_valid(self, utxo_set: dict[str, dict[int, TxOutput]]) -> bool:
        input_sum = 0
        output_sum = 0

        for i, txin in enumerate(self.inputs):
            if txin.tx_id not in utxo_set or txin.index not in utxo_set[txin.tx_id]:
                print("Invalid input: missing UTXO")
                return False

            utxo = utxo_set[txin.tx_id][txin.index]
            input_sum += utxo.amount

            pubkey_bytes = base64.b64decode(txin.pubkey)
            signature = base64.b64decode(txin.signature)
            vk = ecdsa.VerifyingKey.from_string(pubkey_bytes, curve=ecdsa.SECP256k1)

            try:
                vk.verify(signature, self.hash().encode())
            except ecdsa.BadSignatureError:
                print("Invalid signature")
                return False

            derived_address = hashlib.sha256(pubkey_bytes).hexdigest()
            if utxo.address != derived_address:
                print("Public key does not match address")
                return False

        for txout in self.outputs:
            if txout.amount <= 0:
                print("Invalid output amount")
                return False
            output_sum += txout.amount

        if input_sum < output_sum:
            print("Output sum exceeds input sum")
            return False

        return True

def create_coinbase_tx(address: str, amount: int, height: int) -> Transaction:
    inputs = [TxInput(tx_id="", index=-1)]
    outputs = [TxOutput(amount, address)]
    metadata = { MetadataType.HEIGHT: height }
    return Transaction(inputs, outputs, metadata=metadata)