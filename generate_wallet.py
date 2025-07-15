from shard_service import ShardService
from wallet import generate_keypair, pubkey_to_address

if "__main__" == __name__:
    number_of_shard = int(input("Input the number of shard: "))

    priv_key = generate_keypair()[0]
    while ShardService.get_shard_id(pubkey_to_address(priv_key)) != number_of_shard:
        priv_key = generate_keypair()[0]

    print(f"Private key: {priv_key}")