from web3 import Web3
import json
from getpass import getpass
import os
from dotenv import load_dotenv


load_dotenv()
MODE = os.getenv("MODE", "LOCAL")


def get_env(key):
    # print(f"{MODE}_{key}")
    return os.getenv(f"{MODE}_{key}")

HTTP_PROVIDER = get_env("RPC_URL")
DEPLOYER_ADDRESS = get_env("SENDER_ADDRESS")
if(MODE == "LOCAL"):
    KEYSTORE_FILE = get_env("KEYSTORE_FILE")
elif(MODE == "BPNI"):
    private_key = get_env("PRIVATE_KEY")

# ------------------------------------
# 1. Connect ke RPC
# ------------------------------------
w3 = Web3(Web3.HTTPProvider(HTTP_PROVIDER))
assert w3.is_connected(), "Web3 connection failed"
print("Connected:", w3.is_connected())

# ------------------------------------
# 2. Unlock Wallet (keystore)
# ------------------------------------

if(MODE == "LOCAL"):
    with open(KEYSTORE_FILE) as kf:
        keydata = kf.read()

    pwd = getpass("Account Password: ")
    try:
        private_key = w3.eth.account.decrypt(keydata, pwd)
    except:
        raise Exception("❌ Wrong password or keystore")

    print("🔐 Private key decrypted")

# ------------------------------------
# 3. Load ABI & BIN
# ------------------------------------
with open("build/AttendanceLogger.abi") as f:
    abi = json.load(f)

with open("build/AttendanceLogger.bin") as f:
    bytecode = f.read().strip()

contract = w3.eth.contract(
    abi=abi,
    bytecode=bytecode
)

# ------------------------------------
# 4. Build Transaction
# ------------------------------------
nonce = w3.eth.get_transaction_count(DEPLOYER_ADDRESS)
chain_id = w3.eth.chain_id

tx = contract.constructor().build_transaction({
    "from": DEPLOYER_ADDRESS,
    "chainId": chain_id,
    "nonce": nonce,
    "gasPrice": w3.eth.gas_price,
})

# Estimasi gas
gas_est = w3.eth.estimate_gas(tx)
tx["gas"] = gas_est + 100000
print("Estimated gas:", gas_est)

# ------------------------------------
# 5. Sign & Send TX
# ------------------------------------
signed_tx = w3.eth.account.sign_transaction(tx, private_key)
tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)

print("🚀 Deploy TX sent:", tx_hash.hex())

# ------------------------------------
# 6. Wait Receipt
# ------------------------------------
receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
print("🎉 Contract deployed at:", receipt.contractAddress)

# optional — save
with open("contract_address.txt", "w") as f:
    f.write(receipt.contractAddress)
