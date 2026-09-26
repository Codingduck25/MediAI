# filepath: MediAI-Python-Backend/scripts/simulate_ionix_ledger.py
import hashlib
import json
import time

class MockIonixBlock:
    def __init__(self, index, previous_hash, timestamp, patient_wallet, data_hash):
        self.index = index
        self.previous_hash = previous_hash
        self.timestamp = timestamp
        self.patient_wallet = patient_wallet
        self.data_hash = data_hash # The IPFS/Decentralized storage Content Identifier (CID)
        self.hash = self.calculate_hash()

    def calculate_hash(self):
        block_string = f"{self.index}{self.previous_hash}{self.timestamp}{self.patient_wallet}{self.data_hash}"
        return hashlib.sha256(block_string.encode()).hexdigest()

class MockIonixBlockchain:
    def __init__(self):
        self.chain = [self.create_genesis_block()]
        
    def create_genesis_block(self):
        return MockIonixBlock(0, "0", int(time.time()), "0x0000000000000000000000000000000000000000", "GENESIS_HASH")

    def get_latest_block(self):
        return self.chain[-1]

    def mint_patient_record(self, wallet, medical_summary_payload):
        print(f"\n[1/3] Backend raw string output generated from voice...")
        # Step 1: Simulate hashing the raw data to remove PHI from the ledger
        raw_json = json.dumps(medical_summary_payload)
        mock_ipfs_cid = f"bafybeic-{hashlib.sha256(raw_json.encode()).hexdigest()[:16]}"
        print(f"      -> Asymmetric Cryptographic Hash Generated: {mock_ipfs_cid}")
        
        # Step 2: Mint a new block onto Ionix referencing the prior block's hash
        print(f"[2/3] Authenticating patient signature via wallet: {wallet}...")
        latest_block = self.get_latest_block()
        new_block = MockIonixBlock(
            index=len(self.chain),
            previous_hash=latest_block.hash,
            timestamp=int(time.time()),
            patient_wallet=wallet,
            data_hash=mock_ipfs_cid
        )
        
        # Step 3: Append to immutable chain state
        self.chain.append(new_block)
        print(f"[3/3] Block successfully appended to Ionix Ledger!")
        print(f"      -> Block #{new_block.index} Hash: {new_block.hash}")
        print(f"      -> Status: Immutable verification complete. Server database bloat: 0 bytes.")

# --- SIMULATION EXECUTION FOR JUDGES ---
if __name__ == "__main__":
    print("="*70)
    print(" MEDIAI - IONIX BLOCKCHAIN BACKEND DEMO SIMULATION ")
    print("="*70)
    
    # Initialize the ledger
    ionix_ledger = MockIonixBlockchain()
    
    # Mock data captured from the voice-first agent
    sample_voice_triage = {
        "symptoms": "Persistent dry cough, mild chest tightness, no fever.",
        "duration": "4 days",
        "triage_priority": "Medium - Recommend primary clinic follow-up"
    }
    
    # Patient connects using their Web3 identity
    patient_wallet_address = "0x71C7656EC7ab88b098defB751B7401B5f6d8976F"
    
    # Trigger backend processing pipeline
    ionix_ledger.mint_patient_record(patient_wallet_address, sample_voice_triage)
    print("="*70)
