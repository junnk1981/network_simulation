# スイッチの数と名前・MACアドレス・IPアドレスを定義
from definitions.host import HOST_LIST
NUM_SWITCH = 7

SWITCH_LIST = []

for i in range(NUM_SWITCH):
    mac=str(hex(16**3 + i + 1))[2:].zfill(12)
    SWITCH_LIST.append(
        {
            "name": f"s{i + 1}",
            "mac": f"{mac[0]}{mac[1]}:{mac[2]}{mac[3]}:{mac[4]}{mac[5]}:{mac[6]}{mac[7]}:{mac[8]}{mac[9]}:{mac[10]}{mac[11]}",
            "ip": f"10.0.0.{i + 100}"
        }
    )
