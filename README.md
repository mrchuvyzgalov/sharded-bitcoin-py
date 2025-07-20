# 🧱 Sharded-Bitcoin‑Py (Python Sharded Bitcoin Simulator)

Simulation of a simplified Sharded Bitcoin-like network (with 2 shards) implemented in Python using UTXO model, P2P messaging, mining, and consensus mechanisms.

---

## 🚀 Features

- **Decentralized P2P network** — no central server; peer discovery via UDP
- **UTXO model** — transaction inputs/outputs with double-spend prevention
- **Mining mode** — proof-of-work mining for shards and proof-of-stake for beacon
- **Block voting consensus** — majority selection on forks
- **Wallet & key generation** — ECDSA-based address creation
- **CLI interface** — balance query, transaction sending, blockchain viewing
- **Dockerized multi-node setup** — launching several nodes and miners

---

## 📋 Repository Structure

- **beacon.py** — beacon set logic  
- **blockchain.py** — blockchain and UTXO set logic  
- **constants.py** — constants for describing messages between nodes  
- **deserialize_service.py** — functions for deserialization  
- **transaction.py** — transactions, inputs/outputs, and signatures 
- **wallet.py** — key generation and address handling  
- **node.py** — P2P networking, message handling, synchronization  
- **main.py** — CLI entry point (node or miner mode)
- **pre_research.py** — Preparation stage before research
- **unit_tests.py** — Unit tests for blockchain/beacon logic
- **integration_tests.py** — Integration tests for node communication logic
- **research.py** — master thesis research
- **shard_service.py** — shard-related functions
- **snapshot.py** — snapshot class
- **Dockerfile** — docker build for single node  
- **docker-compose.yml** — multi-node configuration (nodes + miners)  
- **README.md** — project documentation (this file)  


---

## 🧩 Dependencies

Python modules:

```bash
pip install ecdsa
pip install pytest
```


---

## 🚀 Run Modes

**1. Node mode (non-miner):**

```bash
python main.py user {number of shard (0/1)}
```

For example:

```bash
python main.py user 0
```

**2. Miner mode:**

```bash
python main.py miner {number of shard (0/1)}
```

For example:

```bash
python main.py user 1
```

---

## 🐳 Docker Setup

If you want to test the program in Docker, follow these instructions:  

**1. Build images:**

```bash
docker-compose build
```

**2. Launch containers:**

```bash
docker-compose up
```

By default, this starts:

- **6 nodes:** cli_node1, cli_node2, cli_node3, cli_node4, cli_node5, cli_node6

**3. Go into the containers:**

```bash
docker exec -it {container_name} bash
```

For example:

```bash
docker exec -it cli_node1 bash
```

**4. Launch the program:**

Run the program as shown in **Run Modes** section


---

## 🧪 Test Execution 

To launch Unit tests, execute the following command:


```bash
pytest unit_tests.py
```

To launch Integration tests, execute the following command:


```bash
pytest integration_tests.py
```


---

## 📊 Running TPS Research

The research on transactions per second (TPS) is a crucial part of my Master’s Thesis, aimed at comparing two different Bitcoin architectures. This module is designed to measure the TPS of the system.  

The experiment involves 2 miner nodes (one node in shard 0, one node in shard 1) and 2 non-miner nodes (one node in shard 0, one node in shard 1). First, the miners are initialized and mines 2000 blocks to prepare the blockchain. After this preparation phase, the 2 non-miner nodes join the network.  

During the experiment, the miner sends 1 BTC every 0.08 seconds to a randomly selected node, with the experiment running until 3 new blocks are mined. Three modes of sharded Bitcoin operation are tested:

1. **Best-case (intra-shard transfers):** each miner sends 1 BTC every 0.08 seconds to nodes within the same shard, minimizing cross-shard overhead  
2. **Worst-case (cross-shard transfers):** each miner sends 1 BTC every 0.08 seconds to nodes in different shards, maximizing inter-shard coordination via the Beacon Chain  
3. **Random-case:** each miner sends 1 BTC every 0.08 seconds to randomly selected nodes, resulting in a probabilistic mix of intra- and cross-shard transactions  
This setup enables the estimation of the approximate transactions-per-second (TPS) under each scenario.

In ordef to launch miner, execute the following command:

```bash
python research.py miner {number of shard (0/1)}
```

For example:

```bash
python research.py miner 0
```

In order to launch non-miner, execute the following command:

```bash
python research.py user {number of shard (0/1)}
```

For example:

```bash
python research.py user 1
```

To start the research, you need to follow these steps:  

1. Launch miner node and wait until the miner preparation is complete  
2. Launch 3 non-miner nodes  
3. Pass the addresses of other nodes to the miner node via CLI  
4. Launch researching in the miner node and wait the results  
5. When the research is complete, you will see the following results: amount of added transactions, time spent and tps


---

## 📄 License

Licensed under MIT. See [LICENSE](./LICENSE) file for full terms.


---

## 🤝 Author

Kirill Chuvyzgalov — Developed as a Master's research project in Constructor University Bremen.
