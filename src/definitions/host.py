NUM_HOST = 19

HOST_LIST = []

for i in range(NUM_HOST):
    mac=str(hex(i + 1))[2:].zfill(12)
    HOST_LIST.append(
        {
            "name": f"h{i + 1}",
            "mac": f"{mac[0]}{mac[1]}:{mac[2]}{mac[3]}:{mac[4]}{mac[5]}:{mac[6]}{mac[7]}:{mac[8]}{mac[9]}:{mac[10]}{mac[11]}",
            "ip": f"10.0.0.{i}"
        }
    )
