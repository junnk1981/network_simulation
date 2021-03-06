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

# INITIAL_FLOW_TABLE = [
#     [
#         {"eth_src": HOST_LIST[0]["mac"], "eth_dst": HOST_LIST[1]["mac"], "out_port": 2)},
#         {"eth_src": HOST_LIST[0]["mac"], "eth_dst": HOST_LIST[2]["mac"], "out_port": 3)},
#         {"eth_src": HOST_LIST[0]["mac"], "eth_dst": HOST_LIST[3]["mac"], "out_port": 4)},
#         {"eth_src": HOST_LIST[0]["mac"], "eth_dst": HOST_LIST[4]["mac"], "out_port": 4)},
#         {"eth_src": HOST_LIST[0]["mac"], "eth_dst": HOST_LIST[5]["mac"], "out_port": 2)},
#         {"eth_src": HOST_LIST[0]["mac"], "eth_dst": HOST_LIST[6]["mac"], "out_port": 2)},
#         {"eth_src": HOST_LIST[0]["mac"], "eth_dst": HOST_LIST[7]["mac"], "out_port": 2)},
#         {"eth_src": HOST_LIST[0]["mac"], "eth_dst": HOST_LIST[8]["mac"], "out_port": 2)},
#         {"eth_src": HOST_LIST[0]["mac"], "eth_dst": HOST_LIST[9]["mac"], "out_port": 2)},
#         {"eth_src": HOST_LIST[0]["mac"], "eth_dst": HOST_LIST[10]["mac"], "out_port": 2)},
#         {"eth_src": HOST_LIST[0]["mac"], "eth_dst": HOST_LIST[11]["mac"], "out_port": 2)},
#         {"eth_src": HOST_LIST[0]["mac"], "eth_dst": HOST_LIST[12]["mac"], "out_port": 2)},
#         {"eth_src": HOST_LIST[0]["mac"], "eth_dst": HOST_LIST[13]["mac"], "out_port": 2)},
#         {"eth_src": HOST_LIST[0]["mac"], "eth_dst": HOST_LIST[14]["mac"], "out_port": 2)},
#         {"eth_src": HOST_LIST[0]["mac"], "eth_dst": HOST_LIST[15]["mac"], "out_port": 2)},
#         {"eth_src": HOST_LIST[0]["mac"], "eth_dst": HOST_LIST[16]["mac"], "out_port": 2)},
#         {"eth_src": HOST_LIST[0]["mac"], "eth_dst": HOST_LIST[17]["mac"], "out_port": 2)},
#         {"eth_src": HOST_LIST[0]["mac"], "eth_dst": HOST_LIST[18]["mac"], "out_port": 2)}
#     ]

# ]