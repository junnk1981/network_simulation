NUM_SWITCH = 7
NUM_HOST = 19

SWITCH_NAME = "s{num}"
HOST_NAME = "h{num}"

LINK = [
    ["s1", "1", "h1", "1"],
    ["s1", "2", "h2", "1"],
    ["s1", "3", "h3", "1"],
    ["s2", "1", "h4", "1"],
    ["s2", "2", "h5", "1"],
    ["s3", "1", "h6", "1"],
    ["s3", "2", "h7", "1"],
    ["s4", "1", "h8", "1"],
    ["s4", "2", "h9", "1"],
    ["s4", "3", "h10", "1"],
    ["s5", "1", "h11", "1"],
    ["s5", "2", "h12", "1"],
    ["s5", "3", "h13", "1"],
    ["s6", "1", "h14", "1"],
    ["s6", "2", "h15", "1"],
    ["s6", "3", "h16", "1"],
    ["s7", "1", "h17", "1"],
    ["s7", "2", "h18", "1"],
    ["s7", "3", "h19", "1"],
    ["s1", "4", "s2", "3"],
    # ["s1", "5", "s7", "4"],
    ["s2", "4", "s3", "3"],
    # ["s2", "5", "s6", "4"],
    ["s2", "6", "s7", "5"],
    ["s3", "4", "s4", "4"],
    ["s4", "5", "s5", "4"],
    # ["s4", "6", "s6", "5"],
    ["s5", "5", "s6", "6"],
    ["s6", "7", "s7", "6"]
]

# LINK2 = [
#     "s1":[
#         "1": "h1",
#         "2": "h2",
#         "3": "h3",
#     ]
# ]

